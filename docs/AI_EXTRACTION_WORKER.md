# AI 简历提取后台任务

上传 API 不会等待模型响应。原生 PDF 文本解析成功后，API 会在同一数据库事务中创建一条 AI 提取任务；随后由独立 worker 调用模型。浏览器不传递、也不会获得模型密钥。

## 状态

- `queued`：已入队，等待 worker。
- `running`：worker 已获得租约并正在调用模型。
- `completed`：结构化事实已通过字段级原文证据校验并写入，简历为 `ready` 且 `is_active=true`，可立即参与筛选。
- `needs_attention`：模型结果无可用字段、网络重试耗尽或数据校验失败；可在上传页重新入队或重新上传 PDF。
- `unavailable`：服务端未配置 `DEEPSEEK_API_KEY`，没有发起模型请求。

扫描件、加密件或原生文字质量不合格的 PDF 不会入队；V1 不依赖 OCR，接口会返回 `needs_attention` 与原因。

## 本地运行

API 与 worker 分别启动：

```powershell
uvicorn app.main:app --reload
python -m app.ai_extraction_worker
```

只处理一条任务后退出可使用：

```powershell
python -m app.ai_extraction_worker --once
```

## 云端部署

`compose.yml` 已包含 `worker` 服务，会在数据库迁移和院校名册初始化完成后启动。它与 API 使用同一份服务端环境变量；不要把 `DEEPSEEK_API_KEY` 放入前端或请求体。

可选运行参数：

- `RESUME_V3_AI_EXTRACTION_JOB_MAX_ATTEMPTS`：单任务自动重试上限，默认 `3`。
- `RESUME_V3_AI_EXTRACTION_JOB_LEASE_SECONDS`：worker 租约，默认 `180`；必须至少比 `DEEPSEEK_TIMEOUT_SECONDS` 多 30 秒。
- `RESUME_V3_AI_EXTRACTION_WORKER_POLL_SECONDS`：空队列轮询间隔，默认 `2`。

worker 以数据库租约领取任务，因此重启、重复启动或短暂网络失败不会让两个 worker 同时写入同一份简历；过期租约会被安全回收，已自动启用的新版本不会被旧任务覆盖。
