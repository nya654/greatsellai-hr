# 简历筛选 V3

这是一个独立重写项目。旧系统和旧的 resume_text 不会被导入为 V3 的可筛选事实。

- [产品需求文档](docs/PRD.md)
- [全项目实施计划](docs/IMPLEMENTATION_PLAN.md)
- [AI 提取后台任务](docs/AI_EXTRACTION_WORKER.md)

当前版本已覆盖：重新上传 PDF → 解析质量校验 → AI 从原文识别候选人姓名（不可靠则留空）并提取教育/经历/技能 → 字段级原文证据校验并自动启用 → 简历库汇总（AI 总结预览、最新 AI 评分、原 PDF）→ 条件筛选 → AI 评分、总结与 JD 匹配；React/Vite 工作台通过同域名 Caddy 静态部署，浏览器只请求同源的 `/v1/*` API。

本地启动（开发环境会自动建 SQLite 表并写入院校名单）：

```powershell
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload
```

需要自动 AI 提取时，在另一个终端启动持久 worker（密钥只放在服务端 `DEEPSEEK_API_KEY`）：

```powershell
python -m app.ai_extraction_worker
```

前端本地开发（另开一个终端；Vite 会将 `/v1` 和 `/health` 代理到本机 API）：

```powershell
cd web
npm ci
npm run dev
```

云服务器部署说明见 [DEPLOYMENT.md](docs/DEPLOYMENT.md)。生产环境必须先跑 Alembic 迁移和显式院校名单初始化，不能依赖 Web 启动建表；Caddy 是唯一暴露公网端口的服务，同时负责 HTTPS、静态前端和 `/v1/*` API 反代。

## 已实现的 API 闭环

- 筛选：`POST /v1/candidates/search`，支持 985/211、学历、经历、技能、关键词和保存筛选器。
- 简历库：`GET /v1/resume-library` 返回每份已上传 PDF 的处理状态、AI 总结预览与最新 AI 评分；不暴露结构化事实明细。
- 原件核验：`GET /v1/resumes/{resume_id}/original-file` 受管理口令保护，以 `inline` PDF 返回；前端使用带认证头的 Blob 预览，不把口令暴露到 URL。
- 评分：创建评分模板、按不可变事实快照评分、保留评分历史，并可人工覆写单个维度。
- 总结：生成结构化 AI 总结；事实重存后旧总结会自动标记为历史，不能误作当前总结。
- JD：创建版本化 JD、AI 提取后人工确认需求、按确认版匹配，并返回 JD 条款与简历 fact 证据。

需要模型的接口只读取服务端的 `DEEPSEEK_API_KEY`；浏览器和请求体都不传递密钥。接口文档在本地启动后访问 `/docs`。
