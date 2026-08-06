# 生产直传晋级链设计（静默拉 + 人工发）

- 日期：2026-08-06
- 状态：方向已拍板，本设计待审阅
- 相关：[[staging-release.yml]] 直传模型；[[CI_CD.md]] 生产晋级链当前暂停

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
3. **传输走 staging 主机中转**：staging 主机持有连生产的 SSH key，生产防火墙只
   放行 staging 主机 IP（窄面）；GitHub Runner 的临时 IP 不对外开放。
4. 发布只在 `production` Environment 里发生；静默拉不碰 compose、迁移、重启。

## 架构

```
GitHub Runner (美国)                     staging 主机 (美国)                 生产机 (中国)
  构建 API/Caddy 镜像
  ── docker save | gzip | ssh docker load ──▶ 镜像
      （现有 staging 部署，不变）                 │
                                                 ▼ 静默拉（新增步骤）
   部署 staging + 公网 smoke 通过后               docker save | gzip | ssh docker load
      ── ssh staging 触发 ──────────────────▶    ──────────────────────────────▶ 预加载镜像（不发布）
                                                                                  │
       负责人手动跑 Production promotion                                        │
       （PROMOTE + production Environment + 审批）                                ▼
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
"Remove superseded staging images" 之前新增一步，由 Runner 触发 staging 主机执行：

```yaml
- name: Pre-load verified images to production host
  if: steps.ready.outputs.stage == 'true'
  env:
    STAGING_DEPLOY_HOST: ${{ vars.STAGING_DEPLOY_HOST }}
    RELEASE_SHA: ${{ env.RELEASE_SHA }}
  run: |
    set -Eeuo pipefail
    cat scripts/stream-images-to-production.sh \
      | ssh -i "$RUNNER_TEMP/greatsell-staging-deploy" \
        -o StrictHostKeyChecking=yes "$STAGING_DEPLOY_HOST" \
        "bash -s $RELEASE_SHA"
```

新增 `scripts/stream-images-to-production.sh`（在 staging 主机上执行）：

- 参数：`<release-sha>`、可选 `--throttle-mbps`（默认 8）。
- 对 API 和 Caddy 各执行：
  `sudo -n docker save greatsellai-hr-api:<sha> | gzip -1 | [pv -L <rate>m |] ssh -o BatchMode=yes -o StrictHostKeyChecking=yes production "sudo -n docker load"`
- 校验：本地镜像必须存在且 `revision == sha`；load 完成后回查生产机上该 SHA 镜像
  ID 必须等于本地镜像 ID，不一致即失败（fail-closed）。
- 生产机地址与 SSH key **不进入仓库**：staging 主机 `~/.ssh/config` 提供 `production`
  别名（见"服务器侧一次性配置"）。脚本只引用 `ssh production`。
- 传输不过 staging 主机出站瓶颈：镜像 gzip 后约 1–1.5GB，美中链路本身限速在个位数
  MB/s，`pv -L 8m` 进一步把占用钉在可控值，不影响 staging 上其他服务带宽。

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

- 生产 SSH key 只存在于 staging 主机（服务器侧配置，不进仓库、不进 GitHub
  secrets）；Runner 触发 staging 执行，工作流不接触生产凭据。
- 生产机 `authorized_keys` 用 `command=` 把 staging 的 key 限制为只允许
  `docker load`，并禁止 port-forwarding / agent / X11。拿到该 key 的最坏情况是覆盖
  预加载镜像（DoS），不能部署出恶意镜像——发布由 production Environment 的
  `PROMOTE` + 审批 + 镜像 ID fail-closed 校验兜底。
- 生产防火墙只放行 staging 主机 IP 的 22 端口。
- staging 主机因中转获得生产访问能力，属新增信任面，需在文档中显式说明。

## 服务器侧一次性配置（实现本设计的前置条件）

1. staging 主机 `ubuntu` 用户生成专用 keypair；写入 `~/.ssh/config`：
   ```
   Host production
     HostName <生产机地址>
     User ubuntu
     IdentityFile ~/.ssh/<专用key>
   ```
   并把生产机 host key 加入 `~/.ssh/known_hosts`。
2. 生产机 `authorized_keys` 加入 staging 公钥，`command="sudo docker load ..."`
   限制（具体实现见实现计划）。
3. 生产防火墙放行 staging 主机 IP → 生产机 22。
4. staging 主机安装 `pv`（限速用，一条 `apt-get install -y pv`）。
5. 用 staging 主机本地验证 `docker save <示例镜像> | gzip | ssh production docker load`
   可达，并把验证结果记录下来。

## 改动清单

- `.github/workflows/staging-release.yml`：新增 "Pre-load verified images to
  production host" 步骤。
- `scripts/stream-images-to-production.sh`：新增，staging 主机侧 save|gzip|load +
  ID 回查校验。
- `scripts/verify-staging-release.sh`：支持 direct 记录分叉。
- `scripts/verify-preloaded-production-images.sh`：新增，生产机预加载镜像 ID 校验。
- `.github/workflows/production-release.yml`：替换 TCR 拉取为预加载镜像校验，
  更新 job outputs。
- `docs/CI_CD.md`、`docs/STAGING_RELEASE.md`：更新为直传 + staging 中转模型，
  说明新增信任面；`docs/TCR_RELEASE_SETUP.md` 保留为历史说明。
