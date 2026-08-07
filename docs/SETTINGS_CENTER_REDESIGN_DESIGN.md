# SETTINGS_CENTER_REDESIGN_DESIGN

> 状态：待评审
> 日期：2026-08-06
> 范围：工作区设置页重构（`web/src/features/workspace-settings/`）+ 新增两个设置区块

## 一、背景与目标

当前设置页只有两个分类（收件邮箱、候选人数据与保留），结构单薄，视觉与内部
交互层级不统一，且缺少用户真正需要的两类设置（AI 导入自动化、筛选显示字段）。

本次重构把设置页升级为"设置中心"：

- **信息架构**：从平铺 2 项升级为左侧边栏 + 分组，可扩展。
- **范围**：新增「AI 导入处理」「筛选显示字段」两个区块。
- **交互一致性**：所有区块统一进一套设置内容框架，消除内嵌页风格割裂。
- **视觉**：对齐"数智红"工作台审美基准（`--red: #d71618`、暖中性色）。

## 二、现状盘点

### 页面结构

`WorkspaceSettingsPage`（`web/src/features/workspace-settings/WorkspaceSettingsPage.tsx`）
是唯一入口（侧栏"设置"→ 工作区），内部以顶部卡片网格导航切换两个内嵌页：

| 区块 | 组件 | 规模 | 内容 |
|---|---|---|---|
| 收件邮箱 | `MailboxPage`（`embedded`） | ~1981 行 | 服务商 / 收件身份 / 首次入库范围 / 连接与同步 / 投递渠道规则 |
| 候选人数据与保留 | `CandidateDataLifecyclePage`（`embedded`） | ~556 行 | 保留策略 / 可恢复删除 / 资料导出 / 访问审计 / 到期清理记录 |

两页均**只**在设置页内被渲染（无独立路由），重构自由度完整。

### 相关现状

- **AI 处理链路**：上传仅存 PDF；AI 提取、总结、评分全部手动触发
  （`queue-ai-extraction` / `put facts` / `activate` / `score-all`），导入时无任何自动化。
- **筛选结果列**（`ResultsPane`）：列由当前筛选条件自动推断
  （`activeResultDisplayColumns`），用户无法手动固定。
- **设置存储**：后端无通用"工作区设置 / 用户偏好"表。
- **评分模板**：工作区级（`score_templates`），有 `template_id`，列表接口已有。
- **设计基线**：全局 `styles.css` 已使用数智红令牌（`--red: #d71618` 等），
  设置页自身 CSS（`workspace-settings.css`）为卡片网格 + 红 tint 选中态。

## 三、目标信息架构

```
设置中心（左侧边栏 + 右侧内容）
├─ 工作区设置（仅作用当前工作区）
│   ├─ 收件邮箱
│   ├─ 候选人数据与保留
│   └─ AI 导入处理            ← 新增
└─ 个人偏好（仅作用我的账号）
    └─ 筛选显示字段            ← 新增
```

- `WorkspaceSettingsSection` 扩展为 4 项：`mailbox` / `data` / `ai-import` / `display-fields`。
- 边栏两项分组，分别标注"工作区设置 / 个人偏好"；权限沿用现状
  （`canManageMailbox` / `canManageCandidateData` 控制工作区组内可见性）。
- 新区块权限：AI 导入处理 = 工作区管理员；筛选显示字段 = 所有登录用户。

## 四、区块设计

### 4.1 收件邮箱（重构展示层）

业务逻辑与数据流不变，展示层改为 Semi 主从结构：

- **左列**：收件通道列表（通道名 / 服务商·认证方式 / 邮箱 / 状态标签），
  可选中、可新建通道。
- **右列**：选中通道的详情——连接与同步表单、首次入库范围、运行状态、
  投递渠道规则、内容保留与历史。
- 替换当前 `MailboxChannelList` 置顶面板的横向布局为左列选择。

### 4.2 候选人数据与保留（现有保留）

同上。内部 5 个子面板（保留/恢复/导出/审计/清理）保留，统一外壳。

### 4.3 AI 导入处理（新增）

控制简历导入时是否自动生成 AI 总结与评分。

| 设置项 | 控件 | 规则 |
|---|---|---|
| 自动生成 AI 总结 | 开关 | **默认开** |
| 自动评分 | 开关 | **默认开**；依赖已选默认评分模板，未选时显示强校验提示并等待模板确定 |
| 默认评分模板 | 下拉（工作区模板列表） | 必选；自动评分开启时展示为强校验 |
| 触发来源 | 分段选择 | 手动上传 / 邮箱入库 / 两者，**默认两者都开** |

行为语义：

- **默认全开**：新设置行默认 总结开 + 评分开 + 触发来源两者都开，
  开箱即用即全自动化（导入即跑 AI 提取 → 总结 → 评分）。
- 开启任意自动化 = 导入时该简历会自动进入「AI 提取 → 总结 → 评分」链路
  （提取是总结/评分的事实前提，故一并自动化）。
- 有真实 AI 调用成本，UI 需在开启时给出明确提示文案。
- 自动评分依赖默认模板：若工作区尚无任何评分模板，自动评分保持开启
  但评分链路暂不触发，需先在工作区创建/选择一个默认模板。
- 切换仅对**之后**导入的简历生效，不回溯已导入简历。

### 4.4 筛选显示字段（新增，账号级）

控制筛选结果表固定显示的列。

- 可选字段全集来自 `CandidateSearchDisplayFieldKey`（22 个，`web/src/types.ts`），
  中文标签复用 `ResultsPane` 现有映射。
- 多选清单，每个账号独立保存。
- 生效逻辑：**用户的选择 = 结果表列集**（"筛选说明"列固定保留）；
  未做过任何选择时（初始态）沿用现有自动推断行为，不破坏现状。
- 该区块为账号级，页面需明确标注"仅影响我的账号"。

## 五、视觉与交互

**核心原则：设置区域弃用现有自定义 CSS（`workspace-settings.css`、
邮箱/候选人数据各页自定义 class），全部用 Semi 组件重做展示层**
（遵循 `AGENTS.md`：常规控件优先 `@douyinfe/semi-ui-19`，已有封装用封装）。

- **设置中心骨架**：Semi `Layout`（Sider + Content）+ `Navigation` 左侧分组边栏
  （工作区设置 / 个人偏好），选中态走数智红主题。
- **收件邮箱主从结构**：区块内**左侧一列 = 通道列表**（Semi `List` 可选行 或
  纵向 `Tabs`），**右侧 = 通道详情**（连接表单 / 运行状态 / 投递规则 / 内容保留）。
  替换当前"通道列表在详情上方"的横向布局。
- **控件映射**：按钮/输入/选择/进度用既有封装 `BackofficeButton` /
  `BackofficeInput` / `BackofficeSelect` / `BackofficeProgress`；
  其余用 Semi `Form`、`Switch`、`Tag`、`Table`、`Toast`、`CheckboxGroup`。
- **统一内容框架**：所有区块共用 Semi 面板/卡片容器与统一标题层级。

## 六、后端数据模型与接口

### 6.1 新表 `workspace_ai_import_settings`（工作区级）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string PK | |
| `organization_id` | FK unique | 一工作区一行 |
| `auto_summary_enabled` | bool | 默认 true |
| `auto_score_enabled` | bool | 默认 true |
| `default_score_template_id` | FK nullable | 指向 `score_templates` |
| `trigger_manual_upload` | bool | 默认 true |
| `trigger_mailbox_import` | bool | 默认 true |
| `updated_at` | datetime | |

### 6.2 新表 `user_filter_display_preferences`（账号级）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string PK | |
| `user_id` | FK unique | 一账号一行 |
| `display_field_keys` | string[] | `CandidateSearchDisplayFieldKey` 子集 |
| `updated_at` | datetime | |

### 6.3 接口

- `GET/PUT /v1/settings/ai-import`（需工作区管理员）— 读写 AI 导入配置。
- `GET/PUT /v1/settings/display-fields`（需登录）— 读写当前账号显示字段。
- 遵循现有组织上下文隔离（`OrganizationScoped` + `set_organization_context`）。

## 七、数据流：导入自动处理链路

```
简历入库（手动上传 或 邮箱入库）
  → 命中触发来源？ ──否──> 结束（保持现状）
  → 是
  → 排入 AI 提取任务（request_resume_ai_extraction）
  → 提取完成
      → auto_summary_enabled？ → 排入总结任务
      → auto_score_enabled 且已选默认模板？ → 以默认模板排入评分任务
```

实现要点：

- **现状基线**：`save_pdf_resume` 已自动排队**文档提取**（原生文本/OCR，
  `enqueue_uploaded_resume_document_extraction`），手动上传与邮箱入库一致。
  本设置新增的是其后的 **AI 提取 → 总结 → 评分** 三步自动化。
- 在**手动上传**（`/v1/resumes/upload`）与**邮箱入库**（mailbox import service）
  两个入口，按配置 + 来源决定是否排入 AI 提取。
- 总结/评分在 AI 提取完成后的**同一 worker 钩子**里判断设置再排入，
  避免在无事实时排入导致失败重试。
- 评分使用 `run_resume_score` 以默认模板对单简历评分。
- 不新增内联模型调用，全部走现有后台任务队列。

## 八、错误处理与边界

- 自动评分默认开启，但未选默认评分模板时评分链路不触发，UI 展示强校验提示
  （若工作区无模板则引导先创建模板）。
- 提取/总结/评分任务失败沿用现有重试与状态展示，不在设置页新增错误路径。
- 未配置模型服务/无 API Key 时：任务失败按现有 worker 错误记录，
  设置页不阻塞配置保存。
- 仅作用当前工作区/账号，任何越权读写返回现有鉴权错误。

## 九、测试策略

- **后端**：两个新表迁移；设置读写接口的鉴权与组织/账号隔离；
  导入入口按「来源 × 开关」矩阵正确排入/不排入任务。
- **前端**：`web` 生产构建；设置中心骨架渲染、边栏分组与权限隐藏；
  AI 导入设置交互（无模板禁用自动评分）；
  显示字段选择持久化并作用于结果列。
- **e2e**（`web/e2e/`）：管理员设置 AI 导入开关后上传，验证任务进入队列；
  账号切换显示字段后结果列变化。
- 含迁移：验证安全升级路径（新表为增量，无回滚数据风险）。

## 十、范围与不做的事

本次**不做**：

- **不重写**邮箱/候选人数据的**业务逻辑与数据流**（API 调用、状态管理、鉴权保持
  不变），只重构其**展示层**为 Semi 组件。
- 不纳入平台管理后台（AI 运营 / 套餐 / 组织等）进工作区设置。
- 不新增"招聘工作流""账号资料/通知"等区块（后续可扩展）。
- 不回填已导入简历的 AI 总结/评分。

## 十一、涉及文件（预估）

- **设置骨架**：`WorkspaceSettingsPage.tsx`、`workspace-navigation-types.ts`、
  `WorkspaceViewRouter.tsx`、`App.tsx`（section 传参）；删除
  `workspace-settings.css`。
- **邮箱区块**：`MailboxPage.tsx`、`MailboxChannelList.tsx` 展示层 Semi 化，
  通道列表改为左列主从；随附邮箱自定义 CSS 清理。
- **候选人数据区块**：`CandidateDataLifecyclePage.tsx` 展示层 Semi 化。
- **新区块**：新增 `AiImportSettingsPanel`、`DisplayFieldsSettingsPanel`（Semi）。
- **后端**：`app/models.py`（两表）、迁移、`app/main.py`（两接口 + 导入钩子）、
  `app/services/`（设置读取/写服务）。
