# V3 云服务器部署

当前部署单元是 API、PostgreSQL、一次性迁移任务和 Caddy。Caddy 镜像会在构建阶段通过 `web/package-lock.json` 安装前端依赖、构建 React/Vite 静态文件，并在同一个 HTTPS 域名下提供页面与 API。

公网只暴露 Caddy 的 `80/443` 端口：

- `https://<domain>/v1/*` 与 `https://<domain>/health` 由 Caddy 反向代理到内部 `api` 服务；
- 其余路径由 Caddy 直接提供 `web/dist`，并回退到 `index.html`，因此刷新或直达前端路由不会 404；
- `api`、`db` 与 `migrate` 都没有宿主机端口映射。前端构建产物不包含 API 代理，API 的唯一公网入口是 Caddy 的显式路径规则。

## 首次部署

1. 在 Linux 云服务器安装 Docker Engine 和 Docker Compose 插件，并将域名 A/AAAA 记录指向服务器。
2. 将仓库部署到服务器，复制 `.env.production.example` 为 `.env.production`，填写域名、数据库密码和管理员令牌。不要把该文件提交到 Git。
3. 启动：

   ```bash
   docker compose --env-file .env.production up --build -d
   ```

   前端依赖会在 Docker 多阶段构建中通过 `npm ci` 安装；服务器检出目录不需要、也不会使用 `web/node_modules`。

4. `migrate` 容器会先运行 `alembic upgrade head`，再显式写入 985/211 院校注册表；只有它成功后 API 才会启动。
5. 验证：

   ```bash
   curl https://your-domain.example/health
   curl -I https://your-domain.example/
   ```

生产 Web 进程不会运行 `create_all()`，也不会在启动时改写院校名单。这避免多副本启动时的 DDL/种子数据竞争。

浏览器使用同源的 `/v1/*` 请求 API，不需要在生产环境设置前端 API 域名或开放 CORS。首次签发 HTTPS 证书前，请确认域名 A/AAAA 记录已生效，并且云防火墙放行 `80` 与 `443`。

## AI 提取 worker

`compose.yml` 的 `worker` 服务负责执行已经持久化的 AI 简历提取任务；上传 API 本身不等待模型调用。部署前在 `.env.production` 设置服务端 `DEEPSEEK_API_KEY`，worker 与 API 会读取同一份环境变量，密钥绝不出现在浏览器、前端构建产物或请求体中。

未配置密钥时，新任务会显示为 `unavailable` 而不会调用模型；配置密钥并重启 `worker` 后会安全地重新进入队列。任务状态、租约、重试上限和本地启动方式见 [AI 提取后台任务](AI_EXTRACTION_WORKER.md)。

## 更新与备份

- 更新镜像/代码后重复 `docker compose --env-file .env.production up --build -d`；迁移任务是幂等的。
- 定期执行 PostgreSQL 逻辑备份，并演练恢复。上传的 PDF 当前位于 Docker volume `uploads_data`，备份时必须与数据库一起处理。
- 管理接口需要请求头 `X-Admin-Token`。服务端的期望值只配置在环境变量中；首期单账号工作台由管理员在“连接配置”中把同一口令保存在自己的浏览器 `localStorage` 后随请求头发送，绝不写入源码、请求 URL 或上传内容。后续接入正式登录时，应改为 HttpOnly 会话而不是沿用浏览器存储。
- 在上线真实简历前，务必使用 HTTPS 域名并限制服务器 SSH、数据库端口和 Docker 管理权限。
