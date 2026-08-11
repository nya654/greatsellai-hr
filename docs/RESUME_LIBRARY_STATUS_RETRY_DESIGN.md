# 简历库状态栏筛选 + 一键重试 设计

**日期：** 2026-08-10
**状态：** 已确认（与产品对齐）

## 背景与目标

简历库（`ResumeLibraryPage`）中每份简历有多个异步处理流（文档提取、AI 结构化提取、候选人名字提取、AI 总结、模板评分）。任一环节失败（或服务暂时不可用）时，简历会停留在异常状态，目前**列表页没有任何重试入口**——总结失败只能进详情页重试，AI 提取失败在列表页无路可走，评分失败无法重跑。

**目标：** HR 在简历库列表页就能恢复失败/异常的简历：

1. 顶部状态栏从只读统计升级为**可点击筛选**的 tab；
2. 筛选结果**勾选多行**后批量重试，行内也保留**单条重试**；
3. 重试按失败态自动分派到对应流程，全程**异步入队**（worker 后台跑），前端反馈「已重试 N / 跳过 M」。

## 现状（探索结论）

- 顶部状态栏（`library-queue-summary`）目前是**只读统计**，只统计**当前页**（`pageOverview`：progress / waiting / attention / unscored），不可点击筛选。现有筛选只有「按收件通道」。
- 每份简历的状态维度（来自 `resume_library_service.list_resume_library`）：
  - `extraction_status`：文档提取（`failed` = 解析失败）
  - `ai_extraction_status`：`needs_attention` / `unavailable` / `failed` / `queued` / `running`
  - `candidate_name_extraction_status`：姓名识别
  - `ai_summary_status`：`failed` / `unavailable` / `queued` / `running` / `succeeded`
  - `score_status`：简历最近一次 `ResumeScore.status`（`succeeded` / `overridden` / `needs_review` 等）
- 现有可复用的重排服务：
  - `request_resume_document_extraction`（`document_extraction_job_service.py`）：未激活简历重跑原文件解析；`is_active` 或 `extraction_status == "ready"` 拒绝；AI 提取进行中拒绝。
  - `request_resume_ai_extraction`（`ai_extraction_job_service.py`）：仅未激活且 `extraction_status in {text_ready, needs_review}` 时可重排；`ready` 拒绝。
  - `POST /resumes/{id}/summaries`：摘要生成/重排（详情页已有入口）。
  - 批量评分：`enqueue_resume_score_batch`（`resume_score_batch_service.py`），`ResumeScoreBatch` 按模板冻结版本，worker 逐 item 跑。
- 简历库列表项 `score_status / score_total / score_template_name` 均取自简历**最近一条** `ResumeScore`。

## 前端交互

### 状态栏 tab（可点击筛选）

顶部状态栏升级为四档互斥 tab，点击即筛选（与「按收件通道」筛选可叠加），再次点击同 tab 取消筛选：

| Tab | 包含 | 可重试 |
|---|---|---|
| 处理中 | AI 提取中/排队、姓名识别中、总结生成中、等待启用 | 否（进行中） |
| 需处理 | 文档提取失败、AI 提取失败/服务不可用、源文本质量异常、版本已更新 | 是 |
| 待评分 | 从未评分（`score_total == null`）+ 评分异常（曾评分但 `score_status` 非 succeeded/overridden） | 是 |
| 待总结 | 总结失败 / 总结暂不可用 | 是 |

对应后端列表 API 新增 `status_filter` 参数（四档映射成后端过滤条件，见下）。

### 勾选批量重试 / 全选整库

- 列表行加勾选框（多选）；勾选 ≥1 项时，顶部/操作区出现「重试所选 (N)」按钮。
- 表头 checkbox = **全选整个简历库**（跨页、忽略状态/来源筛选）：勾选后按钮变为「重试全部 (N)」（N = 全库总数），走 `{ all: true }` 批量端点；行勾选框在全选模式下全部选中且禁用。
- 点击后调批量重试端点，toast 反馈「已重试 N 份 / 跳过 M 份（含原因）」，随后刷新列表。

### 行内单条重试

- 失败/异常项（需处理 / 待评分 / 待总结 任一状态命中）行尾显示「重试」按钮。
- 点击调单条重试端点，成功后该项回到 queued 状态（列表轮询刷新）。

### 不可重试提示

- 跳过原因以 toast / 按钮 tooltip 展示（见「跳过原因」）。

## 后端 API

### 单条重试

```
POST /v1/resumes/{resume_id}/retry-failed
→ 200 { queued: ["document_extraction"|"ai_extraction"|"summary"|"score"], skipped: [] }
```

### 批量重试

```
POST /v1/resumes/retry-failed
body: { resume_ids: [uuid, ...] }   # 指定勾选的简历
  或  { all: true }                 # 整个简历库（忽略状态/来源筛选）
→ 200 {
  queued: [{ resume_id, actions: [...] }],
  skipped: [{ resume_id, reason: string }],
  queued_count: N,
  skipped_count: M,
}
```

- `resume_ids` 与 `all` **二选一**（同时传或都不传 → 422）；`resume_ids` 上限 100。
- `all: true` 时后端按工作区 org 作用域拉全库逐份分派（无失败/缺失环节的简历计为 skipped）。
- 单条/批量共用同一**分派器**（见下），批量逐份收集 queued / skipped 统计。
- 权限：沿用现有 `require_single_admin`；服务层校验 workspace / 存在性。

### 列表 API 状态筛选

`GET /v1/resumes?status_filter=...`（或现有列表端点加参数）：

| 值 | 过滤条件 |
|---|---|
| `processing` | 处理中 / 等待（进行中，不可重试） |
| `attention` | 需处理（失败/异常，可重试） |
| `unscored` | 待评分（从未评分 + 评分异常） |
| `summary_pending` | 待总结（总结失败/不可用） |

四档互斥，优先级从高到低（一份简历归入最先命中的档）：待总结（仅 active+ready 时总结失败）→ 需处理 → 待评分 → 处理中。

## 重试分派器

新增 `retry_resume_failed(session, *, resume_id, settings) -> RetryDispatch`（`resume_library_service.py` 或新 `resume_retry_service.py`），按以下顺序逐项检查并分派（每项命中即记录 action，多项可同时触发）：

| 失败态 | 动作 | 复用服务 |
|---|---|---|
| `extraction_status == "failed"` | 文档重新解析 | `request_resume_document_extraction` |
| `ai_extraction_status in {needs_attention, unavailable, failed}` 且未 active | AI 提取重排 | `request_resume_ai_extraction` |
| `ai_summary_status in {failed, unavailable}` 或从未总结（`None`），且 `is_active and extraction_status == "ready"` | 总结（重排/首次） | `request_resume_summary_job` |
| 评分异常（最近一次评分尝试 failed） | 沿用最近模板重跑 | `enqueue_resume_score_batch(template_id=原模板)` |
| 从未评分（无任何评分尝试）且当前可评分 | 首次评分：用工作区自动评分模板（`WorkspaceAiImportSettings.score_template_ids`）逐模板入队 | `enqueue_resume_score_batch` |

已排队（`queued`/`running`）的流程跳过（不重复入队）。

## 评分重试机制

- 失败评分重跑：简历最近一次**评分尝试**（`ResumeScoreBatchItem`）失败时，沿用该尝试模板当前版本 + 简历当前 fact snapshot 入队（`enqueue_resume_score_batch(template_id=原模板, resume_id=...)`）。
- 首次评分（补评分）：从未有任何评分尝试的简历，若当前可评分（active + ready + 可靠源文本 + 有 fact snapshot），用工作区自动评分模板（`WorkspaceAiImportSettings.score_template_ids`）逐模板入队。
- **边界**：工作区未配置自动评分模板 → 跳过（`no_score_template`）；模板已归档 → 跳过（`template_archived`）。

## 跳过原因（返回给前端）

| reason | 含义 |
|---|---|
| `active_resume_immutable` | 已完成简历不可重排（文档/AI 提取） |
| `job_already_running` | 对应流程正在排队/运行 |
| `no_score_template` | 工作区未配置自动评分模板，无法补首次评分 |
| `template_archived` | 评分模板已归档 |
| `resume_not_scoreable` | 简历当前不可评分（失败评分无法重跑） |
| `no_failed_step` | 该简历当前无失败/缺失项 |

## 测试计划

**后端：**
- 单条分派：文档失败 / AI 提取失败 / 总结失败 / 评分异常 各一例，断言 action 与复用服务被正确调用（monkeypatch 服务函数）。
- 批量：混合输入 → 统计 queued / skipped；按模板分组建 batch。
- 跳过：active+ready 拒绝、job running 拒绝、从未评分跳过、模板归档跳过。
- 状态筛选：`status_filter` 四档各自过滤正确、互斥归档、与来源筛选叠加。

**前端：**
- 状态栏四档点击筛选 / 取消筛选；筛选后勾选 → 「重试所选 (N)」出现；行内重试按钮只在失败项显示；toast 反馈「已重试 N / 跳过 M」。

## 明确不做

- 候选人名字提取**不**做独立重试入口（失败时通常伴随 AI 提取重排/文档重解析；如需可后续单列）。
- **不做**重试任务中心/逐份进度页（超出现有需求，先靠列表轮询）。
