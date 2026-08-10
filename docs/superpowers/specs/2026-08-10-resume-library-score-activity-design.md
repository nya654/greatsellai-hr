# 简历库评分生成动画设计

- 日期：2026-08-10
- 状态：已拍板
- 范围：简历库（`ResumeLibraryPage`）逐行"AI 评分"列，在批量通用评分进行中显示脉动动画
- 相关：[[score_service.py]] 自动评分链路；[[ResumeLibraryPage.tsx]] 简历库；`library-ai-orb` 呼吸球动画语言

## 背景与目标

系统已能全自动生成简历评分（`run_resume_score`：结构化事实快照 → DeepSeek strict-function
评分 → 服务端确定性加权）。批量入口在"通用评分"工作区（`ScoreWorkspace`），把整个简历库入队，
前端 2.5s 轮询批次。

简历库本身的"AI 提取"已经有成熟的呼吸球动画（`library-ai-orb` + 轮转文案 + ETA，且尊重
`prefers-reduced-motion`）。但"AI 评分"列目前只有两种静态状态：有分显示数字、没分显示
"尚无通用评分"。**批量评分进行中时，简历库对"正在生成"毫无感知**，用户看不到评分在推进。

目标：简历库逐行"AI 评分"格在评分生成期间显示一个脉动圆点 + "评分生成中…"动画（复用现有
呼吸球视觉语言），完成后自动变成分数数字。

## 已拍板的方向（用户 2026-08-10 确认）

1. **位置：简历库，逐行评分格**（非顶部汇总条，非智能匹配面板）。
2. **风格：脉动圆点 + 文案**"评分生成中…"，与 AI 提取呼吸球同一套动画语言。
3. **完成态**：动画消失，评分格回到现有分数数字展示。

## 设计

### 1. 后端：库接口暴露"评分进行中"状态（派生字段，无迁移）

`list_resume_library` 响应每项新增计算字段：

```
score_task_state: "none" | "queued" | "running"
```

- **只算不落库**：由当前工作区活跃评分批次 item 派生，无迁移、无新表。
- **派生来源**：`ResumeScoreBatchItem`（OrganizationScoped），取
  `batch.status IN ('queued','running')` 且 `item.status IN ('queued','running')`
  的 item，按 `resume_id` 建 map；item.status=`queued` → `queued`，`running` → `running`。
- **租户隔离**：`ResumeScoreBatchItem.organization_id` 已建索引（
  `ix_resume_score_batch_item_organization_claim`），查询按当前工作区 `organization_id`
  过滤，跨工作区批次不泄漏。
- **现有字段不动**：`score_status`（最终状态）、`score_total`、`score_template_name`、
  `score_created_at` 语义不变，互不干扰。

### 2. 前端：评分格动画（简历库）

- **类型**：`ResumeLibraryItem` 加 `score_task_state: "none" | "queued" | "running"`。
- **评分格渲染顺序**（`ResumeLibraryPage.tsx` 评分列）：
  1. `score_task_state` 为 `queued` / `running` → 渲染脉动圆点 + "评分生成中…"，
     带 `role="status"` 与 aria-label（如"正在生成 AI 评分"），圆点 `aria-hidden`。
  2. 否则维持现状：分数 / 尚无通用评分 / 完成提取后可评分。
- **重新评分**：已有分数且正在重新评分时，运行期间用动画盖住旧分数（旧分已过期，
  显示旧分反而误导）。生成完成自动落新分数。
- **轮询（整页单请求，不是逐行）**：现有自动刷新本就是一次 `listResumeLibrary(page, pageSize)`
  每 `AI_STATUS_POLL_INTERVAL_MS`（2500ms）—— 不是按行轮询。本次只把该刷新条件追加
  "存在 `score_task_state` 为 queued/running 的行"，**请求数不变：每 tick 仍只发 1 个
  页面请求**，动画只是这份响应的纯渲染，不各自触发请求。条件命中任一进行中行才开定时器，
  全部结束即停。该接口只读数据库，不触碰 AI 评分队列，不会消耗评分算力。且条件只看**当前页**
  的行：若进行中的评分都在其他页，当前页不轮询，请求数天然 ≤1/2.5s。
- **动画**：新增轻量圆点类，复用 `library-ai-orb-gradient` / `library-ai-orb-shine`
  关键帧的脉动语言（圆点呼吸 + 微光），并遵守 `prefers-reduced-motion` 降级为静态
  （与现有 `.library-ai-activity` 一致）。
- **顶部汇总条**：现有"处理中 / 需处理 / 待评分"计数保持原逻辑不动，控制范围。

### 3. 边界情况

- 批次失败 / 完成 → item 变 `failed` / `succeeded` → `score_task_state` 回到 `none`，
  动画停止，回到分数或"尚无通用评分"。
- 同一简历同时出现在不同模板的活跃批次 → 任一 item 进行中即显示动画（`uq_..._active_template`
  只限制同模板，跨模板可能并存，取最宽口径）。
- 无活跃批次 → `score_task_state = "none"`，行为与现在完全一致（向后兼容）。
- 源文本质量有问题 / 版本已更新的简历不在批次内 → 不受影响，维持现有展示。

### 4. 测试

- **后端单测**：
  - `list_resume_library` 在活跃批次 queued / running / 无批次三种情况下返回正确的
    `score_task_state`。
  - 租户隔离：另一工作区的进行中批次不影响本工作区库返回值。
  - 批次完成/失败后状态回落到 `none`。
- **前端 e2e**：评分进行中评分格显示动画，完成后变为分数（复用现有 mock 基建，
  不调真实 AI）。

## 非目标（YAGNI）

- 不加评分 ETA 估算（提取动画有 ETA，评分先不引复杂度）。
- 不改智能匹配已有的 `BackofficeProgress` 进度条。
- 不动顶部汇总条计数、不动 `ScoreWorkspace` 批量面板。
- 不做分数落定时的数字滚动动画（本次只做"生成中"动画）。

## 实现落点

- `app/services/resume_library_service.py`：`list_resume_library` 派生 `score_task_state`。
- `app/schemas.py`：库 item schema 加字段。
- `web/src/types.ts`：`ResumeLibraryItem` 加 `score_task_state`。
- `web/src/features/library/ResumeLibraryPage.tsx`：评分格分支 + 轮询条件 + aria。
- `web/src/features/library/resume-library.css`：脉动圆点动画 + reduced-motion。
- `tests/`：后端单测（库状态 + 租户隔离）。
- `web/e2e/`：进行中动画 / 完成后分数。
