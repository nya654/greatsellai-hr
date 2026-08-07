# 预发布与生产晋级

> 当前流程：staging 在美国发布 Runner 上直接构建该 commit 的镜像并经 SSH 流式传输到 staging 主机
> （不经中国 TCR），部署成功后只保留新 SHA 一套镜像。生产采用"静默拉 + 人工发"：staging 验证并
> 公网 smoke 通过后，由发布 Runner 直连生产机，把已验证镜像经白名单 relay key 预加载到生产机
> （只 `docker load -i`，不发布）；负责人手动运行 **Production promotion**（`PROMOTE` +
> production Environment 审批）才发布。生产机地址与 SSH key 不进仓库：relay 私钥以
> `PROD_RELAY_SSH_PRIVATE_KEY` 放在 `staging` Environment（白名单限定，见下方信任面）。
> 版本号使用日期 + 当日序号（`stg-YYYYMMDD-N` / `prod-YYYYMMDD-N`，过渡期兼容历史
> `<commit>` 后缀标签）。历史 TCR 方案见 [TCR 发布镜像配置](TCR_RELEASE_SETUP.md)，仅作参考。

## 发布链路

```text
PR 完整 CI
  → 合并 main
  → main CI 验证来源（main-release-provenance）
  → 自动构建 API / Caddy 镜像并流式传输到 staging，部署并执行公网 smoke
  → 发布 Runner 白名单 relay key 静默预加载已验证镜像到生产机（只 docker load -i，不发布）
  → 人工运行 Production promotion（PROMOTE + production Environment 审批）
  → 校验 staging 记录 + 生产机镜像 ID == 记录 → 创建 prod-YYYYMMDD-N → 部署同一镜像
```

生产不会因为 `main` 合并自动发布。静默拉只把镜像灌到生产机，不触碰 compose、迁移或运行服务；
发布只在 `production` Environment 内发生。预发布未完成、冒烟检查失败、`main` 在验收期间前进、
镜像 ID 不一致时 staging 会失败关闭；生产机镜像缺失或对不上 staging 记录时 promotion 也会
失败关闭，不会误发。

当前预发布和生产可以同机，也可以部署在不同 Docker 主机；它们始终是两个独立 Compose 项目。
生产晋级不依赖两端共享 Docker 镜像缓存：镜像由发布 Runner 经白名单 relay key 预加载到生产机，
内容 ID 跨 `docker save/load` 保留，promotion 只校验生产机镜像 ID == staging 记录即证明是同一镜像。
预发布应用以
`RESUME_V3_ENVIRONMENT=production` 运行，以覆盖生产专属的 HTTPS、安全、数据生命周期和投递逻辑；隔离由独立项目、数据库、数据卷、网络、代理地址与预发布域名保证：

- production：`resume-screening-v3`、生产 `.env.production`、生产数据卷和 `172.30.0.0/24`；
- staging：`resume-screening-v3-staging`、独立 `.env.staging`、独立数据卷和 `172.31.0.0/24`；
- staging Caddy 仍监听旧主机私有 `172.17.0.1:18080`。在生产迁移到新主机期间，旧主机上
  **已经运行的** Caddy 保留 `staging.hr.greatsellai.net` 的既有精确路由；它不属于新生产
  Compose 项目，也不会被任何生产发布、回滚或恢复工作流刷新、重建或接管。

预发布不携带生产数据库、PDF 或任何生产数据快照。`.env.staging` 必须逐项人工复制当前
生产实际运行值（包含非密钥开关、模型、限额和超时），但它仍是独立文件，绝不能直接引用
`.env.production`；仅数据库连接、文件卷、网络、Trusted Proxy、公开 URL 和 OAuth 回调保持
staging 值。生产数据快照是另一个显式、单向、脱敏优先的运维任务，绝不能被部署工作流自动执行。

同一 Google 或 Microsoft OAuth Client 还必须在供应商控制台额外允许 staging 的两个回调地址，
否则会出现 `redirect_uri_mismatch`。

## GitHub Environments

当前迁移桥接期不运行任何 “staging gateway bootstrap”。旧机 Caddy 是保留中的既有运行时，
不是新生产环境的一部分；不要停止、重建或用新版本覆盖它。日常流程仍是 CI 自动部署
staging，最后由人工 `PROMOTE` 晋级生产；这些流程均不会修改旧机的 staging 网关。

在 **Settings → Environments** 创建 `staging`。所有值只放在该 Environment，不进入仓库、
Runner 常驻环境或代码。

### `staging` secrets

- `STAGING_SSH_PRIVATE_KEY`
- `STAGING_SSH_KNOWN_HOSTS`
- `PROD_RELAY_SSH_PRIVATE_KEY`：白名单限定的 relay 私钥，供自动 staging-release job 在发布
  Runner 上直连生产预加载（见下方信任面）。绝不放进 repo secrets 或任何主机。
- `PROD_RELAY_SSH_KNOWN_HOSTS`：经可信渠道核验过的生产机 host key。

### `staging` variables

- `STAGING_DEPLOY_HOST`：例如 `ubuntu@<same-host>`；
- `STAGING_PROJECT_DIR`：`/home/ubuntu/resume-screening-v3-staging`；
- `STAGING_HISTORY_DIR`：`/home/ubuntu/greatsellai-hr-staging-deployments`；
- `STAGING_PUBLIC_URL`：`https://staging.hr.greatsellai.net`；
- `PROD_RELAY_HOST`：`ubuntu@<生产主机地址>`。

`production` 的 `PROD_*` secrets/variables 必须只指向新生产主机；`staging` 的
`STAGING_*` 继续指向旧主机。建议为 `production` 配置 Required reviewer；这会让
**Production promotion** 在验证完 staging 后暂停，直到负责人批准。

`STAGING_DEPLOY_HOST` 与 `PROD_DEPLOY_HOST` 可以指向不同 Docker 主机。生产晋级只接受 staging
记录里的 API/Caddy image ID：promotion 校验生产机已预加载镜像 ID 与记录一致、revision 一致、
平台为 `linux/amd64`，才创建 `prod-*` 并部署；镜像缺失或对不上就失败关闭，绝不在生产机重建
镜像。镜像由发布 Runner 直连预加载（静默拉），`PROD_DEPLOY_HOST` 仅用于 promotion 时连生产
机做校验与发布。

## 服务器一次性准备

1. 创建 `/home/ubuntu/resume-screening-v3-staging`，只放置 `.env.staging` 和由发布流程写入的
   `compose.yml`；不要创建 `.env.production`。
2. 从 `.env.staging.example` 创建独立 `.env.staging`：只为 staging 数据库生成专用密码；其余
   运行时服务值必须逐项复制当前生产实际值，但必须保留 staging 的 Trusted Proxy、公开 URL 和 OAuth
   回调地址，且不得直接引用或挂载 `.env.production`。
3. 创建 staging history 目录，例如
   `/home/ubuntu/greatsellai-hr-staging-deployments`，仅部署用户可写。
4. DNS 将 `staging.hr.greatsellai.net` 继续指向旧 staging 服务器。迁移期间保留旧机现有
   Caddy 容器及其精确路由，不修改该 DNS、Caddy、staging 数据卷或 `.env.staging`。绝不让
   新生产主机接管该子域、`greatsellai.net` 根目录或泛域名。

新生产镜像刻意不再携带 staging 路由。部署/回滚到带旧路由的历史 Caddy 源码或镜像会被
生产发布脚本拒绝，避免新主机错误代理到自身不存在的 `172.17.0.1:18080`。

### 发布 Runner 直连生产（新增信任面）

自动 staging-release job 持有白名单限定的 relay 私钥，在发布 Runner 上直连生产预加载镜像，这是
新增信任面，务必按最小权限配置：

1. 生成专用 relay keypair（ed25519，注释 `release-relay->production`）。私钥放入 `staging`
   Environment 的 secret `PROD_RELAY_SSH_PRIVATE_KEY`；公钥稍后通过 **Relay bootstrap** 装到
   生产机。配合的 `PROD_RELAY_SSH_KNOWN_HOSTS`（生产机 host key）与 `PROD_RELAY_HOST`
   （`ubuntu@<生产机地址>`）也放在 `staging` Environment。地址与私钥不进仓库、不进 repo
   secrets、不落任何主机。
2. 生产机 `authorized_keys` 加入该公钥，用 `command=` 强制走白名单包装脚本
   `/home/ubuntu/.relay-allow.sh`（仓库里的 `scripts/relay-allow.sh`），只放行静默拉所需命令：
   `true`（可达性探测）、`mkdir -p`（relay 目录）、`tee`（流式写入 `.tar.gz`）、
   `docker load -i`（文件版加载）、`rm -f`（清理）以及仅针对 greatsellai-hr 镜像的
   `docker image inspect --format '{{.Id}}'`（ID 回查），并禁止 port-forwarding / agent / X11。
   安装与轮换由 **Relay bootstrap** 工作流完成（手动、`production` Environment、只装公钥不碰
   私钥）。拿到该 key 的最坏情况是覆盖预加载镜像（DoS），不能开 shell、读文件或部署出恶意
   镜像——发布由 `production` Environment 的 `PROMOTE` + 审批 + 镜像 ID fail-closed 校验兜底。
3. 生产防火墙需放行 GitHub-hosted 发布 Runner 出站 IP 段到 22 端口（按
   <https://api.github.com/meta> 的 `actions` ranges 配置），不再只放行 staging IP。
4. 发布 Runner 默认不限速；需要限速时传 `--throttle-mbps`（runner 上需安装 `pv`）。
5. 首次验证可手动走通一次：本机 `docker save <示例镜像> | gzip | ssh -i <relay-key> \
   ubuntu@<prod> "sudo -n tee /var/lib/greatsellai-relay/x.tar.gz"`，再 `sudo -n docker load -i \
   /var/lib/greatsellai-relay/x.tar.gz` 并核对 image ID，最后 `sudo -n rm -f` 清理。

## 日常操作

1. 合并经过 CI 的 PR 到 `main`。
2. 等待 **Staging release** 自动运行；它会先做只读 Compose 预检，创建或复用
   `stg-YYYYMMDD-N` 标签，构建该 commit 的 API/Caddy 镜像并经 SSH 流式传输到 staging，
   部署后检查：`/health`、匿名 session、匿名原文件访问拒绝和 `/login` 页面。smoke 通过后，
   由发布 Runner 直连生产机把已验证镜像静默预加载（只 `docker load -i`，不发布）。
3. 在 `https://staging.hr.greatsellai.net/login` 做业务验收。若 `main` 在验收期间前进，新的
   main 会生成新的 staging 候选；旧候选不能被晋级。
4. 在 Actions 手动运行 **Production promotion**，从 `main` 输入 `PROMOTE`。工作流会验证当前
   main 的唯一 `stg-*` tag、源码 archive SHA-256、staging release record（direct 记录核对
   API/Caddy image ID 与 revision），再核对生产机已预加载镜像 ID 与记录一致、平台为
   `linux/amd64`，全部一致才创建 `prod-YYYYMMDD-N` 并以 `--prebuilt-images` 部署。
5. 已有 `prod-*` 的重部署和回滚仍只用于恢复，不是绕过 staging 的新代码发布入口。

## 验收与故障处理

- **Staging release 失败**：不会创建可晋级生产的完成记录。修复 PR 后走新的 main；同一 commit
  可通过手动 `STAGE` 重试，已有同 SHA 的 `stg-*` 不会被移动。若静默拉步骤本身失败，本次
  staging release 标红，但 staging 部署与完成记录不受影响，也不阻塞下一次自动 staging；
  重跑 `STAGE` 会复用不可变 `stg-*` 标签并重新执行静默拉。
- **Production promotion 失败**：常见于生产机未预加载镜像（镜像缺失或 ID 对不上 staging 记录），
  工作流会失败关闭。不要在生产机上 build 来“补救”，这会破坏同一镜像保证；重跑一次 staging
  release 触发静默拉后再次 promotion。
- **Staging 不可达**：检查旧 staging 主机上原有的 Caddy 容器和 `172.17.0.1:18080` 私有
  监听是否仍在运行。新生产 Caddy 故意不包含 staging 路由；不要把 staging 域名、DNS 或
  旧机 Caddy 改到新生产主机来“修复”。
- **仅需要重试生产部署**：选择已有 `prod-*` 使用 **Production deploy**；不要手工伪造
  `stg-*` 或 `prod-*` 标签。
