# 智能匹配 × 通用评分 闭环设计

- 日期：2026-08-10
- 状态：已拍板方向（左右并排两个表）
- 范围：智能匹配界面分「JD 匹配」与「通用评分」两个表（左右并排，直观对比）；匹配时自动补分形成闭环
- 相关：[[MatchWorkspace.tsx]] 智能匹配；[[job_match_batch_service.py]] JD 匹配批次；
  [[resume_score_batch_service.py]] 通用评分批次；[[resume_library_service.py]] 评分派生；
  简历库评分生成中动画（`score_task_state`）

## 背景与目标

智能匹配目前只产出 JD 匹配结果（匹配度 / 分档 / 硬条件 / 逐条理由）。用户要求：**智能匹配界面不止 JD 匹配**，
把通用评分闭环进来；并且**两个维度分开、各自成表**，不合并、不加权、不做综合分。
为保证评分表有数据，**匹配时自动补分**：发起岗位评估时，同一批合格候选人顺带入队所选模板的通用评分批次。

## 已拍板的方向（用户 2026-08-10 确认）

1. **分两个表**：智能匹配界面 = 「JD 匹配」表 + 「通用评分」表，**左右并排布局**，可直接对比。
2. **无权重、无综合分**：JD 匹配度与通用评分是两条独立信号，各自为凭。
3. **匹配时自动补分**：发起岗位评估时顺带入队通用评分，形成闭环。

## 设计

### 1. 前端：左右并排两个表

智能匹配工作区顶部保留现有 JD 版本选择器，新增**评分模板选择器**（默认工作区最新模板）。
下方**左右并排两个表**，同屏直观对比同一批候选人的 JD 匹配度与通用分：

- **左表「JD 匹配」**：现有 `MatchLeaderboard`，逻辑、列、排序、详情全部不动。
- **右表「通用评分」**：新增。按所选评分模板列出候选人的分数：
  - 每行：候选人、通用分（`total_score`）、状态（succeeded / needs_review / overridden / 无分）、生成中动画。
  - 评分生成期间显示脉动圆点 +「评分生成中…」（**复用简历库评分格的动画语言与 `score_task_state`**）。
  - 无分：显示「尚无通用评分」；模板无分数来源时提示。
- 工作区**没有评分模板**时：评分表禁用，提示「去评分工作区创建模板」。

评分表的数据源为「所选模板 + 当前事实版本 + 活跃批次派生」，与简历库同款派生，**抽共享 helper**，不复制两份。

### 2. 闭环：匹配时自动补分

- 前端「开始岗位评估」请求带上 `score_template_id`。
- 后端 `match-all` 入队 JD 匹配批次后，对**同一批合格候选人**入队所选模板的通用评分批次
  （复用 `enqueue_resume_score_batch`；若其只支持全量/单个，则新增按 `resume_ids` 入队的内部入口，
  不改变现有公共行为）。
- 评分表轮询评分批次（复用 2.5s 轮询节奏 + 进行中动画），完成后自动落分。

### 3. 后端

- `POST /v1/job-versions/{job_version_id}/match-all` body 加可选 `score_template_id`。
- 新增 `GET /v1/job-versions/{job_version_id}/score-leaderboard?template_id=...`：
  返回该 JD 合格候选人列表的 `score_total / score_status / score_task_state`，以及当前评分批次状态
  （`batch_id / status / completed_count / total_count`）。
- **无新表、无迁移**；复用 `OrganizationScoped` 租户隔离（`with_loader_criteria`）。

### 4. 测试

- **后端单测**：
  - `match-all` 带 `score_template_id` 时同时创建匹配批次与评分批次；不带时行为与现在完全一致。
  - 租户隔离：另一工作区的评分批次/模板不泄漏到本工作区评分表。
  - 评分榜派生：有分 / 无分 / 生成中（queued/running）三种状态正确；无活跃批次回落到无分。
- **前端 e2e**：左右两个表同屏；评分表生成中动画 → 完成后落分（复用 mock 基建，不调真实 AI）。

## 非目标（YAGNI）

- 无权重、无综合分、不把评分并入匹配排序。
- 不改 `MatchLeaderboard` 现有列与排序。
- 不做上下分区 / Tab 切换（已拍板左右并排）。
- 不动简历库、评分工作区既有功能。

## 实现落点

- `app/schemas.py`：`JobMatchBatchEnqueue`/新请求模型加 `score_template_id`；新增 score-leaderboard 响应。
- `app/services/job_match_batch_service.py`：`enqueue_job_version_match_batch` 支持顺带创建评分批次（按子集）。
- `app/services/resume_score_batch_service.py`：暴露按 `resume_ids` 入队的内部入口（若需要）。
- `app/services/resume_library_service.py`：把 `_active_score_task_states` 抽成共享 helper 或等价复用。
- `app/main.py`：`match-all` 请求体 + 新 score-leaderboard 端点。
- `web/src/features/job-match/MatchWorkspace.tsx`：左右并排布局容器 + 评分表 + 模板选择器 + 复用动画/轮询。
- `web/src/types.ts`：score-leaderboard 类型。
- `web/e2e/`：左右两表同屏 + 评分动画落分 e2e。
