# 生产直传晋级链设计（静默拉 + 人工发）

- 日期：2026-08-06
- 状态：方向已拍板；传输路径已修订为"发布 Runner 直连生产"（见下方修订说明）
- 相关：[[staging-release.yml]] 直传模型；[[CI_CD.md]] 生产晋级链当前暂停

## 修订说明（2026-08-06，验证后）

原设计（下方正文"已拍板的方向"第 3 条）让 **staging 主机中转**预加载镜像。验证静默拉
机制时实测：staging→prod 出站仅 ~22-28KB/s（staging 入站快、出站慢，疑为腾讯抗 DDoS
对 ssh 暴破触发带宽限速或出站带宽包过低），API 镜像压缩后约 1GB，按此速度需 ~10 小时，
不可接受。用户拍板改为 **GitHub 发布 Runner 直连生产机**：镜像构建在同一 Runner 上，
直接 `docker save | gzip | ssh` 流到 prod，绕过 staging 慢出站。代价是生产防火墙需放行
GitHub-hosted Runner 出站 IP 段（面大）、且 relay 私钥要放进 `staging` Environment
（GitHub environments 是 job 级作用域，静默拉步骤只能读 staging env 的 secret）。

正文中凡与本修订冲突的描述，以本修订为准；下面已就地更新为最终模型。

## 背景与目标

生产在中国（单机），staging 在美国。仓库为公开仓库，发布构建在 GitHub-hosted
Runner（`ubuntu-latest`）。`main` CI 已不再推 TCR 镜像，staging 直传记录缺 TCR
字段，`verify-staging-release.sh` 对 direct 记录 fail-closed，因此生产晋级链当前
暂停、不会误发。

目标：恢复生产晋级链。镜像由 staging 验证并公网 smoke 通过后，**静默预加载**到
生产机（只 `docker load`，不发布）；负责人人工点按钮（**Production promotion**，
`PROMOTE` + production Environment 审批）才执行发布（切换 compose、迁移、健康
检查）。

## 已拍板的方向（用户 2026-08-06 确认）

1. **静默拉 + 人工发**：staging 部署验证通过后自动把镜像灌到生产机（不发布），
   人工点按钮才发布。
2. **单台生产机不走 TCR 中转**：直传一次（美国 → 中国）即足够，TCR 只是多养一个
   registry。
3. **发布 Runner 直连生产（修订）**：静默拉由构建镜像的同一个 GitHub 发布 Runner 直接
   SSH 到生产机执行，不经 staging 中转；relay 私钥以白名单限定方式放在 `staging`
   Environment（静默拉步骤属于 staging release job，只能读 staging env），生产防火墙需
   放行 GitHub-hosted Runner 出站 IP 段。
4. 发布只在 `production` Environment 里发生；静默拉不碰 compose、迁移、重启。

## 架构

```
GitHub Runner (美国)                                    生产机 (中国)
  构建 API/Caddy 镜像
  ── docker save | gzip | ssh docker load ──▶ 镜像（staging 部署，不变）
      │
      ▼ 部署 staging + 公网 smoke 通过后
  ── docker save | gzip | ssh "sudo tee x.tar.gz" ──▶ 预加载镜像（不发布）
      （同一 Runner 直连生产，白名单 relay key）         │
                                                       ▼
  负责人手动跑 Production promotion
  （PROMOTE + production Environment + 审批）
  ── 校验 staging 记录 + 生产机镜像 ID == staging 记录 ──▶ 切换 compose、迁移、健康检查
```

关键不变式：

- **镜像内容 ID 跨 docker save/load 保留**：staging 主机上部署时已校验
  `revision == SHA`（deploy-staging.sh direct 路径），`docker save | docker load`
  保留镜像 ID，因此生产机上镜像 ID 必须等于 staging 记录里的 `api_image_id` /
  `caddy_image_id`。这条 ID 对账链是晋级校验的核心。
- **发布仍只在 production Environment**：静默拉只把镜像放到生产机，不触碰
  compose/迁移/服务。

## 一、静默拉（staging-release.yml 新增步骤）

在 "Deploy immutable candidate and run public smoke checks" 通过后、
"Remove superseded staging images" 之前，由 Runner 上用 `staging` Environment 里的
relay 凭据直接执行（修订：不再 `cat 脚本 | ssh staging` 中转）：

```yaml
- name: Configure production relay SSH
  if: steps.ready.outputs.stage == 'true'
  env:
    PROD_RELAY_HOST: ${{ vars.PROD_RELAY_HOST }}
    PROD_RELAY_SSH_PRIVATE_KEY: ${{ secrets.PROD_RELAY_SSH_PRIVATE_KEY }}
    PROD_RELAY_SSH_KNOWN_HOSTS: ${{ secrets.PROD_RELAY_SSH_KNOWN_HOSTS }}
  run: |
    set -Eeuo pipefail
    umask 077
    printf '%s\n' "$PROD_RELAY_SSH_PRIVATE_KEY" > "$RUNNER_TEMP/greatsell-prod-relay"
    chmod 600 "$RUNNER_TEMP/greatsell-prod-relay"
    printf '%s\n' "$PROD_RELAY_SSH_KNOWN_HOSTS" > "$RUNNER_TEMP/known_hosts_prod"

- name: Pre-load verified images to production host
  if: steps.ready.outputs.stage == 'true'
  env:
    PROD_RELAY_HOST: ${{ vars.PROD_RELAY_HOST }}
    RELEASE_SHA: ${{ env.RELEASE_SHA }}
  run: |
    set -Eeuo pipefail
    scripts/stream-images-to-production.sh "$RELEASE_SHA" \
      --host "$PROD_RELAY_HOST" \
      --ssh-key "$RUNNER_TEMP/greatsell-prod-relay" \
      --known-hosts "$RUNNER_TEMP/known_hosts_prod"
```

新增 `scripts/stream-images-to-production.sh`（在发布 Runner 上执行）：

- 参数：`<release-sha>`、`--host <user@host>`、`--ssh-key <path>`、
  `--known-hosts <path>`、可选 `--throttle-mbps`（默认 0 不限速）。
- 对 API 和 Caddy 各执行：
  `docker save greatsellai-hr-api:<sha> | gzip -1 | [pv -L <rate>m |] ssh -i <relay-key> \
  "sudo -n tee /var/lib/greatsellai-relay/x.tar.gz"`，随后
  `sudo -n docker load -i /var/lib/greatsellai-relay/x.tar.gz`，最后 `sudo -n rm -f`。
- 校验：本地镜像必须存在且 `revision == sha`；load 完成后回查生产机上该 SHA 镜像
  ID 必须等于本地镜像 ID，不一致即失败（fail-closed）。
- 生产机地址与 SSH key **不进入仓库**：relay 私钥在 `staging` Environment
  （`PROD_RELAY_SSH_PRIVATE_KEY`），`known_hosts` 固定校验；脚本只接受显式传参。
- 走文件版 `tee + docker load -i`：`docker load` 从管道读会永久卡死（dockerd 读 HTTP
  body 阻塞），从可 seekable 文件加载则正常（0.8s/50MB 层）；白名单
  `scripts/relay-allow.sh` 只放行 relay 目录内 `.tar.gz` 的写/加载/清理。

失败语义：该步骤失败会令本次 staging release 标红，但**不影响 staging 部署与
staging 记录**（记录在 smoke 通过时已写 `state=complete`），也不阻塞下一次自动
staging。生产机未预加载时，**Production promotion** 会在校验镜像步骤 fail-closed，
并提示重跑 staging release（`STAGE` 手动重试会复用不可变 `stg-*` 标签并重新执行
静默拉）。

## 二、晋级校验适配（verify-staging-release.sh）

现在它对 direct 记录 fail-closed，因为要求 TCR registry / config digest / CI
workflow_run 字段。改为按记录的 `image_delivery` 分叉：

- **`image_delivery=direct`**：校验 staging 记录里的 `api_image_id`/`caddy_image_id`
  与 staging 主机上实际镜像 ID 一致，且 `revision == release-sha`；**跳过** TCR
  registry、config digest、workflow_run 校验。`--github-output` 改输出
  `api_image_id`、`caddy_image_id`（替代 registry/digest/ci 字段）。
- **`image_delivery=tcr`**（历史记录）：保持现有校验逻辑不变。

## 三、生产 promotion（production-release.yml）

`promote` job 用 "校验生产机已预加载镜像" 替换原来的 TCR 拉取 + CI 镜像校验两步：

1. 保留：preflight、建 `prod-*` 标签、`deploy-production.sh --prebuilt-images`
   （迁移 + 健康检查）。
2. 删除："Pull exact completed staging images from TCR"、
   "Verify production host holds CI-attested images"。
3. 新增 `scripts/verify-preloaded-production-images.sh`：在生产机上校验
   `greatsellai-hr-api:<sha>` / `greatsellai-hr-caddy:<sha>` 的镜像 ID 分别等于
   staging 记录里的 `api_image_id`/`caddy_image_id`，`revision == sha`，
   platform 为 `linux/amd64`。**fail-closed**：镜像缺失或对不上就拒绝，绝不构建、
   绝不用别的镜像。

`verify-staging` job 的输出从 TCR 字段改为 `api_image_id`/`caddy_image_id`。

## 四、回滚

生产机上预加载镜像**只增不减**（静默拉不清理旧镜像），因此最近几个版本的镜像都
还在生产机，回滚到近期 `prod-*` 标签可用。回滚到镜像已被更早版本占用/未预加载的
老标签会 fail-closed（符合现有"绝不在生产机重建镜像"约束），需人工预加载该版本。

## 五、安全边界

- 生产 relay 私钥只存在于 `staging` Environment 的 secret（不进仓库、不进 repo
  secrets、不落任何主机）；自动 staging-release job 在发布 Runner 上用它直连生产，
  工作流不接触 `production` Environment 的部署密钥。
- 生产机 `authorized_keys` 用 `command=` 把该公钥限制为白名单包装脚本
  `/home/ubuntu/.relay-allow.sh`，只放行 `true` / `mkdir -p` / `tee *.tar.gz` /
  `docker load -i` / `rm -f` / greatsellai-hr 镜像的 `image inspect`，并禁止
  port-forwarding / agent / X11。拿到该 key 的最坏情况是覆盖预加载镜像（DoS），不能
  部署出恶意镜像——发布由 production Environment 的 `PROMOTE` + 审批 + 镜像 ID
  fail-closed 校验兜底。
- 生产防火墙需放行 GitHub-hosted 发布 Runner 出站 IP 段（`https://api.github.com/meta`
  的 `actions` ranges）到 22 端口；不再只放行 staging IP。Runner IP 面大，但该 key 被
  白名单限定，最坏影响仍是 DoS 级，不由它发布。
- 自动 staging-release job 持有连接生产的能力，属新增信任面，需在文档中显式说明。

## 服务器侧一次性配置（实现本设计的前置条件）

1. 生成专用 relay keypair（ed25519，注释 `release-relay->production`）。私钥放入
   `staging` Environment 的 secret `PROD_RELAY_SSH_PRIVATE_KEY`，配合 secret
   `PROD_RELAY_SSH_KNOWN_HOSTS`（生产机 host key）与 variable `PROD_RELAY_HOST`
   （`ubuntu@<生产机地址>`）。
2. 生产机 `authorized_keys` 加入该公钥，`command=/home/ubuntu/.relay-allow.sh`
   白名单限制（安装与轮换走 **Relay bootstrap** 工作流，手动、`production`
   Environment、只装公钥不碰私钥）。
3. 生产防火墙放行 GitHub-hosted 发布 Runner 出站 IP 段 → 生产机 22。
4. 发布 Runner 默认不限速；需要限速时传 `--throttle-mbps`（runner 上需装 `pv`）。
5. 首次验证手动走通一次：`docker save <示例镜像> | gzip | ssh -i <relay-key> \
   ubuntu@<prod> "sudo -n tee /var/lib/greatsellai-relay/x.tar.gz"`，再
   `sudo -n docker load -i` 核对 image ID，最后 `sudo -n rm -f` 清理。

## 六、版本号（日期 + 当日序号）

用户反馈 git 提交 hash（如 `stg-20260806-397c3d6`）看不懂，需要可读版本号管理发布。
拍板形式：**日期 + 当日序号**，hash 只作审计保留在发布记录里。

- 新标签格式：`stg-YYYYMMDD-N` / `prod-YYYYMMDD-N`，`N` 为当天该类标签的第几个
  （从 1 起）。校验正则 `^(stg|prod)-[0-9]{8}-[1-9][0-9]*$`。
- `N` 的计算：`git tag --list "stg-YYYYMMDD-[0-9]*"`（只数同格式标签，不含历史
  `<sha>` 后缀标签）计数 + 1。标签创建被 release lane 并发组串行化，无竞态。
- 过渡期**同时接受新旧两种格式**（`^...-[0-9a-f]{7,40}$` 与 `^...-[1-9][0-9]*$`），
  以便首个生产晋级仍可消费当前已部署的旧格式 `stg-20260806-397c3d6`。
- 删除依赖"标签后缀=commit"的自我校验（`tag##*-` 检查）：commit 一律从
  `git rev-parse refs/tags/$tag^{commit}` 解析，标签不可变 + 发布记录里的
  `commit=<full sha>` 保留审计链。
- 发布记录（`current-release.env` / `releases/*.env`）继续写 `tag` 与 `commit`，
  展示时优先显示可读 tag（即版本号）。

## 改动清单

- `.github/workflows/staging-release.yml`：新增 "Configure production relay SSH" +
  "Pre-load verified images to production host" 步骤（Runner 直连生产，relay 凭据取自
  `staging` Environment）；创建标签改为日期+序号格式。
- `scripts/stream-images-to-production.sh`：新增，发布 Runner 侧 save|gzip|tee|
  load -i + ID 回查校验。
- `scripts/verify-staging-release.sh`：支持 direct 记录分叉。
- `scripts/verify-preloaded-production-images.sh`：新增，生产机预加载镜像 ID 校验。
- `.github/workflows/production-release.yml`：替换 TCR 拉取为预加载镜像校验，
  更新 job outputs；创建 `prod-*` 标签改为日期+序号格式，解析 staging 标签兼容
  新旧两种格式。
- `.github/workflows/relay-bootstrap.yml`：新增，手动安装/轮换 relay 公钥到生产机
  （`command=` 白名单包装脚本，只装公钥不碰私钥）。
- 标签格式迁移（新旧格式兼容 + 移除 `tag##*-` 自我校验）：
  - `.github/workflows/`：`production-deploy.yml`、`production-rollback.yml`、
    `production-pending-finalize.yml`、`production-healthy-pending-finalize.yml`、
    `production-legacy-reconcile.yml`。
  - `scripts/`：`create-staging-tag.sh`、`create-production-tag.sh`、
    `deploy-staging.sh`、`deploy-production.sh`、`verify-staging-release.sh`、
    `remote-release-helper.sh`、`finalize-pending-release.sh`、
    `finalize-healthy-pending-release.sh`、`reconcile-legacy-pending-release.sh`、
    `restore-production-backup.sh`。
- `docs/CI_CD.md`、`docs/STAGING_RELEASE.md`：更新为直传 + 发布 Runner 直连生产模型 +
  日期序号版本号，说明新增信任面（`staging` Environment 白名单 relay key、GitHub
  Runner IP 段防火墙）；`docs/TCR_RELEASE_SETUP.md` 保留为历史说明。
