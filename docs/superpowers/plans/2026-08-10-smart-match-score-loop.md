# 智能匹配 × 通用评分 闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 智能匹配界面拆成左右并排两个表——「JD 匹配」表保持现状、「通用评分」表按所选评分模板列出同一批合格候选人的分数；发起岗位评估时自动为同一批候选人补分（闭环）。

**Architecture:** 前端在 `MatchWorkspace` 顶部新增评分模板选择器（默认最新），下方用 grid 容器左右并排 `MatchLeaderboard`（不动）与新增 `ScoreLeaderboard`；「开始岗位评分」请求带上 `score_template_id`。后端 `match-all` 入队 JD 匹配批次后，对同一批合格候选人顺带入队所选模板的通用评分批次（`enqueue_resume_score_batch` 新增按 `resume_ids` 子集入队的参数）；新增 `GET /v1/job-versions/{id}/score-leaderboard?template_id=...`，复用简历库的 `score_task_state` 派生与动画语言，无新表、无迁移。

**Tech Stack:** FastAPI + SQLAlchemy（`with_loader_criteria` 租户隔离）、React 19 + Semi UI + Vite + TypeScript、Playwright e2e。

## Global Constraints

- **无新表、无迁移**；租户隔离完全复用 `OrganizationScoped` + `with_loader_criteria`，不手写 org 谓词做列表隔离。
- **两维度分开、各自成表**：不合并、不加权、不做综合分；JD 匹配度与通用分是两条独立信号。
- **不改 `MatchLeaderboard` 现有列与排序**（左表零改动）。
- **左右并排布局**；窄屏（≤1080px）回落为上下堆叠。
- **复用脉动圆点动画语言**（`library-ai-orb-gradient` 2.4s + 1.4s pulse）与 `score_task_state` 派生，`prefers-reduced-motion` 降级为静态。
- 轮询沿用 **2.5s 节奏**（`AI_STATUS_POLL_INTERVAL_MS`）；每 tick 只发 1 个页面级请求，只读、不触碰评分队列。
- **`match-all` 不带 `score_template_id` 时行为与现在完全一致**（无 body 的旧调用不受影响）。
- `score_template_id`/`resume_ids` 均为服务端/受控输入，非浏览器自由文本；组织过滤照旧为纵深防御。
- UI 文案与产品语境一致：生成中显示「评分生成中…」，无分显示「尚无通用评分」，无模板提示「去评分工作区创建模板」。
- 中文注释/文案风格与现有 `greatsellai-hr` 代码一致；测试用现有 fixture（`_save_ready_resume`、`_seed_ready_resume`、`_create_job`、`_workspace`、`ai_client`）。

---

## 文件结构

- **后端（app/）**
  - `app/services/resume_score_batch_service.py`（改）— `enqueue_resume_score_batch` 新增 `resume_ids` 子集参数。
  - `app/services/resume_library_service.py`（改）— `_active_score_task_states` 公开化为 `active_score_task_states`（加 `template_id` 过滤）+ 新增 `latest_current_scores_by_template` 共享 helper。
  - `app/services/job_match_batch_service.py`（改）— `enqueue_job_version_match_batch` 新增 `score_template_id` 顺带补分；新增 `list_job_version_score_leaderboard`。
  - `app/schemas.py`（改）— `JobMatchBatchEnqueue`、`ScoreLeaderboardItem`、`ScoreLeaderboardResponse`。
  - `app/main.py`（改）— `match-all` 接受可选 body；新增 score-leaderboard GET 端点。
- **后端（tests/）**
  - `tests/test_resume_score_batch_single.py`（改）— `resume_ids` 子集入队用例。
  - `tests/test_job_match_batches.py`（改）— match-all 带 `score_template_id` 顺带补分用例。
  - `tests/test_job_match_score_leaderboard.py`（新）— 评分榜派生、端点、租户隔离。
- **前端（web/src/）**
  - `web/src/types.ts`（改）— ScoreLeaderboard 类型。
  - `web/src/api.ts`（改）— `enqueueAllJobMatches` 带可选模板、`listJobVersionScoreLeaderboard`。
  - `web/src/features/job-match/ScoreLeaderboard.tsx`（新）— 右表组件 + 生成中动画。
  - `web/src/features/job-match/MatchWorkspace.tsx`（改）— 模板选择器 + 左右并排容器 + runAllMatches 带模板 + 评分榜轮询。
  - `web/src/features/job-match/job-match.css`（改）— `.score-loop-tables` grid、`.score-template-switcher`、评分动画 CSS。
- **前端（web/e2e/）**
  - `web/e2e/job-match-score-loop.spec.ts`（新）— 左右两表同屏 + 动画落分 e2e。

---

### Task 1: `enqueue_resume_score_batch` 支持按 `resume_ids` 子集入队

**Files:**
- Modify: `app/services/resume_score_batch_service.py:220-276`
- Test: `tests/test_resume_score_batch_single.py`

**Interfaces:**
- Produces: `enqueue_resume_score_batch(session, *, template_id, settings, resume_id=None, resume_ids=None) -> ResumeScoreBatchResponse`。新增 `resume_ids: list[str] | None = None`：给定子集时只对该子集内的可评分简历建批次；有活跃批次时把子集项追加进去（按 (batch, resume) 唯一约束幂等）；`resume_id=None and resume_ids=None`（全量）时保留现有 coalesce 行为（直接返回活跃批次）。

- [ ] **Step 1: Write the failing test**

在 `tests/test_resume_score_batch_single.py` 末尾追加两个测试（复用该文件已有的 `_settings`、`_workspace`、`_seed_ready_resume`、`_scoreable_template`）：

```python
def test_enqueue_score_batch_scoped_to_resume_subset(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = Database("sqlite://")
    database.create_all()
    try:
        with database.session_factory() as session:
            organization = Organization(name="Subset score batch org")
            session.add(organization)
            session.flush()
            organization_id = organization.id
            first_resume_id, _ = _seed_ready_resume(
                session, organization_id=organization_id, label="subset-one"
            )
            second_resume_id, _ = _seed_ready_resume(
                session, organization_id=organization_id, label="subset-two"
            )
            third_resume_id, _ = _seed_ready_resume(
                session, organization_id=organization_id, label="subset-three"
            )
            with _workspace(session, organization_id):
                template = _scoreable_template(session, name="Subset template")

                response = resume_score_batch_service.enqueue_resume_score_batch(
                    session,
                    template_id=template.id,
                    settings=settings,
                    resume_ids=[first_resume_id, second_resume_id],
                )

                assert response.status == "queued"
                assert response.total_count == 2
                items = session.scalars(
                    select(ResumeScoreBatchItem).where(
                        ResumeScoreBatchItem.batch_id == response.batch_id
                    )
                ).all()
                assert {item.resume_id for item in items} == {
                    first_resume_id,
                    second_resume_id,
                }
                assert third_resume_id not in {item.resume_id for item in items}
    finally:
        database.dispose()


def test_score_batch_resume_subset_appends_to_active_batch_idempotently(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = Database("sqlite://")
    database.create_all()
    try:
        with database.session_factory() as session:
            organization = Organization(name="Subset append score batch org")
            session.add(organization)
            session.flush()
            organization_id = organization.id
            first_resume_id, _ = _seed_ready_resume(
                session, organization_id=organization_id, label="append-one"
            )
            second_resume_id, _ = _seed_ready_resume(
                session, organization_id=organization_id, label="append-two"
            )
            with _workspace(session, organization_id):
                template = _scoreable_template(session, name="Append template")

                first = resume_score_batch_service.enqueue_resume_score_batch(
                    session,
                    template_id=template.id,
                    settings=settings,
                    resume_ids=[first_resume_id],
                )
                assert first.total_count == 1

                second = resume_score_batch_service.enqueue_resume_score_batch(
                    session,
                    template_id=template.id,
                    settings=settings,
                    resume_ids=[first_resume_id, second_resume_id],
                )
                assert second.batch_id == first.batch_id
                assert second.total_count == 2

                # 重复入队同一子集：按 (batch, resume) 唯一约束幂等，不产生重复项。
                third = resume_score_batch_service.enqueue_resume_score_batch(
                    session,
                    template_id=template.id,
                    settings=settings,
                    resume_ids=[first_resume_id],
                )
                assert third.batch_id == first.batch_id
                assert third.total_count == 2
    finally:
        database.dispose()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_resume_score_batch_single.py::test_enqueue_score_batch_scoped_to_resume_subset tests/test_resume_score_batch_single.py::test_score_batch_resume_subset_appends_to_active_batch_idempotently -v`
Expected: FAIL — `TypeError: enqueue_resume_score_batch() got an unexpected keyword argument 'resume_ids'`

- [ ] **Step 3: Implement minimal code**

`app/services/resume_score_batch_service.py`，`enqueue_resume_score_batch` 签名加参数（220-226 行附近）：

```python
def enqueue_resume_score_batch(
    session: Session,
    *,
    template_id: str,
    settings: AppSettings,
    resume_id: str | None = None,
    resume_ids: list[str] | None = None,
) -> ResumeScoreBatchResponse:
```

更新 docstring 首段，说明 `resume_ids`：给定一个子集时，批次只包含该子集内当前可评分的简历（追加到活跃批次、幂等），语义与单简历一致。

全量 coalesce 条件（第 248 行）改为只对「非子集、非单简历」的调用生效：

```python
    if existing is not None and resume_id is None and resume_ids is None:
        return _batch_response(existing)
```

快照过滤（第 274-275 行之后）加子集分支：

```python
    if resume_id is not None:
        snapshot_query = snapshot_query.where(Resume.id == resume_id)
    elif resume_ids is not None:
        snapshot_query = snapshot_query.where(Resume.id.in_(resume_ids))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_resume_score_batch_single.py -v`
Expected: 全部 PASS（含既有单简历用例，保证向后兼容）。

- [ ] **Step 5: Run full backend suite**

Run: `pytest tests/test_resume_score_batches.py tests/test_resume_score_batch_single.py tests/test_resume_score_batch_tenant_isolation.py -q`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add app/services/resume_score_batch_service.py tests/test_resume_score_batch_single.py
git commit -m "feat(score): 支持按 resume_ids 子集入队通用评分批次"
```

---

### Task 2: 共享评分派生 helper（`active_score_task_states` + `latest_current_scores_by_template`）

**Files:**
- Modify: `app/services/resume_library_service.py:48-77`、调用点约 216 行
- Test: `tests/test_resume_library_api.py`

**Interfaces:**
- Produces:
  - `active_score_task_states(session, resume_ids: list[str], *, template_id: str | None = None) -> dict[str, str]` — 公开化 `_active_score_task_states`，新增可选 `template_id`：指定时只统计该模板的活跃批次项（供评分榜按所选模板显示「生成中」）；不指定时行为与简历库现状完全一致（任一模板活跃即算）。
  - `latest_current_scores_by_template(session, *, resume_ids: list[str], template_id: str) -> dict[str, ResumeScore]` — 每份简历在该模板下最新一条「当前 facts 版本 + 终态状态」的 `ResumeScore`。

- [ ] **Step 1: Write the failing test**

在 `tests/test_resume_library_api.py` 追加（复用该文件既有 `_save_ready_resume`、`_template_payload`、`ai_client`、`bypass_organization_scope`、`database` 模式）：

```python
def test_score_task_state_is_scoped_to_selected_template(ai_client) -> None:
    """另一个模板的活跃批次不得让本模板的评分榜显示“生成中”。"""

    _, resume_id = _save_ready_resume(
        ai_client,
        source_text="教育经历 清华大学 计算机 本科。工作经历 Acme Python Engineer。技能 Python SQL",
    )
    template = ai_client.post("/v1/score-templates", json=_template_payload())
    assert template.status_code == 200, template.text
    template_id = template.json()["template_id"]
    other = ai_client.post(
        "/v1/score-templates",
        json={**_template_payload(), "name": "Other template"},
    )
    assert other.status_code == 200, other.text
    other_id = other.json()["template_id"]

    batch = ai_client.post(f"/v1/score-templates/{other_id}/score-all")
    assert batch.status_code == 200, batch.text

    from app.services.resume_library_service import (
        active_score_task_states,
        latest_current_scores_by_template,
    )

    database = ai_client.app.state.database
    with database.session_factory() as session:
        assert active_score_task_states(session, [resume_id], template_id=template_id) == {}
        assert set(
            active_score_task_states(session, [resume_id], template_id=other_id)
        ) == {resume_id}
        assert latest_current_scores_by_template(
            session, resume_ids=[resume_id], template_id=template_id
        ) == {}
```

> 说明：`ai_client` 夹具在 `bypass_organization_scope` 之外建立 org 上下文，活跃批次查询因此带租户过滤。`latest_current_scores_by_template` 在此用例里应返回空（批次还没跑、无已完成评分）。

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_resume_library_api.py::test_score_task_state_is_scoped_to_selected_template -v`
Expected: FAIL — `ImportError: cannot import name 'active_score_task_states'`（函数仍是私有/无 template_id 参数）。

- [ ] **Step 3: Implement minimal code**

`app/services/resume_library_service.py`：

把 `_active_score_task_states`（48-77 行）重命名为公开 `active_score_task_states`，签名加 `template_id` 过滤：

```python
def active_score_task_states(
    session: Session,
    resume_ids: list[str],
    *,
    template_id: str | None = None,
) -> dict[str, str]:
    """Map resume_id -> 'queued' | 'running' from active batch items.

    Runs under the session's tenant scope (``with_loader_criteria``), so a
    foreign workspace's batch can never surface here.  When ``template_id``
    is given, only active batches for that template count, so one template's
    in-flight score never leaks into another template's table.  When a resume
    appears in several active batches, ``running`` wins over ``queued``.
    """

    if not resume_ids:
        return {}
    statement = select(
        ResumeScoreBatchItem.resume_id, ResumeScoreBatchItem.status
    ).join(
        ResumeScoreBatch,
        ResumeScoreBatch.id == ResumeScoreBatchItem.batch_id,
    )
    if template_id is not None:
        statement = statement.where(ResumeScoreBatch.template_id == template_id)
    rows = session.execute(
        statement.where(
            ResumeScoreBatchItem.resume_id.in_(resume_ids),
            ResumeScoreBatchItem.status.in_(_IN_PROGRESS_SCORE_STATUSES),
            ResumeScoreBatch.status.in_(_IN_PROGRESS_SCORE_STATUSES),
        )
    ).all()
    state_by_resume: dict[str, str] = {}
    for resume_id, item_status in rows:
        if item_status == "running" or resume_id not in state_by_resume:
            state_by_resume[resume_id] = item_status
    return state_by_resume
```

在 `_latest_current_score`（141 行附近）之后新增共享 helper：

```python
def latest_current_scores_by_template(
    session: Session,
    *,
    resume_ids: list[str],
    template_id: str,
) -> dict[str, ResumeScore]:
    """Latest current-facts score per resume for one template.

    Mirrors ``_latest_current_score`` but query-scoped to one template so the
    score leaderboard can show each candidate's score for the selected rule
    without loading every template's rows.  Facts-version filtering is applied
    by the caller (which knows each resume's current facts_version).
    """

    if not resume_ids:
        return {}
    rows = session.execute(
        select(ResumeScore)
        .where(
            ResumeScore.resume_id.in_(resume_ids),
            ResumeScore.template_id == template_id,
            ResumeScore.status.in_(_CURRENT_SCORE_STATUSES),
        )
        .order_by(ResumeScore.created_at.desc(), ResumeScore.id.desc())
    ).all()
    latest: dict[str, ResumeScore] = {}
    for score in rows:
        latest.setdefault(score.resume_id, score)
    return latest
```

把 `list_resume_library` 内 216 行附近的调用改为公开名（行为不变，不传 template_id）：

```python
    task_states = active_score_task_states(session, resume_ids)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_resume_library_api.py -q`
Expected: PASS（含既有 score_task_state 用例 + 新用例）。

- [ ] **Step 5: Commit**

```bash
git add app/services/resume_library_service.py tests/test_resume_library_api.py
git commit -m "feat(score): 抽共享评分派生 helper 并支持按模板过滤 task_state"
```

---

### Task 3: `enqueue_job_version_match_batch` 支持 `score_template_id` 顺带补分

**Files:**
- Modify: `app/services/job_match_batch_service.py:304-446`
- Test: `tests/test_job_match_batches.py`

**Interfaces:**
- Consumes: `enqueue_resume_score_batch(..., resume_ids=...)`（Task 1）。
- Produces: `enqueue_job_version_match_batch(session, *, job_version_id, settings, resume_ids=None, allow_internal_job=False, score_template_id=None) -> JobMatchBatchResponse`。带 `score_template_id` 时，入队匹配批次后对**同一批** `snapshots` 的 resume_ids 顺带入队通用评分批次；不带时与现状完全一致。

- [ ] **Step 1: Write the failing test**

在 `tests/test_job_match_batches.py` 追加（复用该文件既有的 `_save_ready_resume`、`_create_job`、`ai_client`、`database.session_factory()` 模式；`_template_payload` 从 `test_resume_score_batches` 导入）：

```python
def test_job_match_batch_with_score_template_id_also_enqueues_score_batch(
    ai_client,
) -> None:
    from app.models import ResumeScoreBatch

    source_text = "教育经历 清华大学 计算机 工作经历 Acme Python Engineer 技能 Python SQL"
    _, first_resume_id = _save_ready_resume(ai_client, source_text=source_text)
    _, second_resume_id = _save_ready_resume(ai_client, source_text=source_text)
    job = _create_job(
        ai_client,
        requirements=JobRequirements(must_have=["Python experience"]),
    )
    job_version_id = str(job["job_version_id"])
    template = ai_client.post("/v1/score-templates", json=_template_payload())
    assert template.status_code == 200, template.text
    template_id = template.json()["template_id"]
    database = ai_client.app.state.database

    with database.session_factory() as session:
        match_response = job_match_batch_service.enqueue_job_version_match_batch(
            session,
            job_version_id=job_version_id,
            settings=ai_client.app.state.settings,
            score_template_id=template_id,
        )
        assert match_response.total_count == 2
        score_batch = session.scalar(
            select(ResumeScoreBatch).where(
                ResumeScoreBatch.template_id == template_id,
                ResumeScoreBatch.status == "queued",
            )
        )
        assert score_batch is not None
        assert score_batch.total_count == 2


def test_job_match_batch_without_score_template_id_skips_score_batch(
    ai_client,
) -> None:
    from app.models import ResumeScoreBatch

    source_text = "教育经历 清华大学 计算机 工作经历 Acme Python Engineer 技能 Python SQL"
    _, first_resume_id = _save_ready_resume(ai_client, source_text=source_text)
    job = _create_job(
        ai_client,
        requirements=JobRequirements(must_have=["Python experience"]),
    )
    job_version_id = str(job["job_version_id"])
    database = ai_client.app.state.database

    with database.session_factory() as session:
        match_response = job_match_batch_service.enqueue_job_version_match_batch(
            session,
            job_version_id=job_version_id,
            settings=ai_client.app.state.settings,
        )
        assert match_response.total_count == 1
        assert session.scalar(select(func.count(ResumeScoreBatch.id))) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_job_match_batches.py::test_job_match_batch_with_score_template_id_also_enqueues_score_batch tests/test_job_match_batches.py::test_job_match_batch_without_score_template_id_skips_score_batch -v`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'score_template_id'`

- [ ] **Step 3: Implement minimal code**

`app/services/job_match_batch_service.py`：

文件顶部 import 区加（确认现有 import 里没有 `func` 则一并补上 `from sqlalchemy import func`；本任务只需 `enqueue_resume_score_batch`）：

```python
from app.services.resume_score_batch_service import enqueue_resume_score_batch
```

`enqueue_job_version_match_batch`（304-311 行）签名加参数：

```python
def enqueue_job_version_match_batch(
    session: Session,
    *,
    job_version_id: str,
    settings: AppSettings,
    resume_ids: Sequence[str] | None = None,
    allow_internal_job: bool = False,
    score_template_id: str | None = None,
) -> JobMatchBatchResponse:
```

docstring 首段补充一句：带 `score_template_id` 时顺带对同一批合格候选人入队通用评分批次。

两个 return 前各插入同一段（追加路径在 385 行 `return _batch_response(existing)` 之前；创建路径在 446 行 `return _batch_response(batch)` 之前）：

```python
        if score_template_id is not None and snapshots:
            enqueue_resume_score_batch(
                session,
                template_id=score_template_id,
                settings=settings,
                resume_ids=[snapshot[0] for snapshot in snapshots],
            )
```

> 追加路径的 `snapshots` 已按本次请求 scope 去重；创建路径的 `snapshots` 即本请求的完整合格集。两者都是「这一批被匹配的候选人」。

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_job_match_batches.py -q`
Expected: PASS（含既有用例，证明无 `score_template_id` 时行为不变）。

- [ ] **Step 5: Commit**

```bash
git add app/services/job_match_batch_service.py tests/test_job_match_batches.py
git commit -m "feat(match): match-all 支持 score_template_id 顺带补分"
```

---

### Task 4: 评分榜服务 `list_job_version_score_leaderboard` + Schemas

**Files:**
- Modify: `app/services/job_match_batch_service.py`（新增函数 + import）
- Modify: `app/schemas.py:3772-3800` 附近
- Test: `tests/test_job_match_score_leaderboard.py`（新）

**Interfaces:**
- Consumes: `active_score_task_states`、`latest_current_scores_by_template`（Task 2）；`_require_scoreable_template`、`_existing_active_batch`、`_batch_response`（resume_score_batch_service 私有，同包直引）；`_eligible_batch_snapshots`（本文件）。
- Produces:
  - Schemas: `ScoreLeaderboardItem{resume_id, candidate_id, candidate_display_name, score_total, score_status, score_task_state}`、`ScoreLeaderboardResponse{items, batch}`。
  - `list_job_version_score_leaderboard(session, *, job_version_id, template_id) -> ScoreLeaderboardResponse` — 候选集 = 该 JD 的合格候选人（`_eligible_batch_snapshots`），按 score_total 降序（无分置底）；`batch` = 该模板当前活跃评分批次（无则 `None`）。

- [ ] **Step 1: Write the failing test**

新建 `tests/test_job_match_score_leaderboard.py`：

```python
from __future__ import annotations

from sqlalchemy import select

from app.models import ResumeScore, ResumeScoreBatch, ResumeScoreBatchItem
from app.services import job_match_batch_service, resume_score_batch_service
from test_filter_mvp_contract import _save_ready_resume
from test_job_service import _create_job
from test_resume_score_batches import _template_payload


def test_score_leaderboard_derivation_states(ai_client) -> None:
    """有分 / 无分 / 生成中 / 无活跃批次四种派生正确。"""

    source_text = "教育经历 清华大学 计算机 工作经历 Acme Python Engineer 技能 Python SQL"
    _, scored_resume_id = _save_ready_resume(ai_client, source_text=source_text)
    _, unscored_resume_id = _save_ready_resume(ai_client, source_text=source_text)
    job = _create_job(ai_client, requirements=JobRequirements(must_have=["Python experience"]))
    job_version_id = str(job["job_version_id"])
    template = ai_client.post("/v1/score-templates", json=_template_payload())
    assert template.status_code == 200, template.text
    template_id = template.json()["template_id"]
    database = ai_client.app.state.database

    # 只对 scored 简历跑评分批次，并跑完，得到一条已完成的分数。
    with database.session_factory() as session:
        resume_score_batch_service.enqueue_resume_score_batch(
            session,
            template_id=template_id,
            settings=ai_client.app.state.settings,
            resume_ids=[scored_resume_id],
        )
        session.commit()

    assert resume_score_batch_service.run_resume_score_batch_worker_once(
        database,
        settings=ai_client.app.state.settings,
        worker_id="leaderboard-worker",
    )
    assert not resume_score_batch_service.run_resume_score_batch_worker_once(
        database,
        settings=ai_client.app.state.settings,
        worker_id="leaderboard-worker",
    )

    with database.session_factory() as session:
        board = job_match_batch_service.list_job_version_score_leaderboard(
            session,
            job_version_id=job_version_id,
            template_id=template_id,
        )
        assert board.batch is None
        by_resume = {item.resume_id: item for item in board.items}
        assert set(by_resume) == {scored_resume_id, unscored_resume_id}
        scored = by_resume[scored_resume_id]
        assert scored.score_status == "succeeded"
        assert scored.score_total is not None
        assert scored.score_task_state == "none"
        assert by_resume[unscored_resume_id].score_total is None
        assert by_resume[unscored_resume_id].score_task_state == "none"


def test_score_leaderboard_reports_active_batch_task_state(ai_client) -> None:
    source_text = "教育经历 清华大学 计算机 工作经历 Acme Python Engineer 技能 Python SQL"
    _, resume_id = _save_ready_resume(ai_client, source_text=source_text)
    job = _create_job(ai_client, requirements=JobRequirements(must_have=["Python experience"]))
    job_version_id = str(job["job_version_id"])
    template = ai_client.post("/v1/score-templates", json=_template_payload())
    assert template.status_code == 200, template.text
    template_id = template.json()["template_id"]
    database = ai_client.app.state.database

    with database.session_factory() as session:
        resume_score_batch_service.enqueue_resume_score_batch(
            session,
            template_id=template_id,
            settings=ai_client.app.state.settings,
            resume_ids=[resume_id],
        )
        session.commit()

    with database.session_factory() as session:
        board = job_match_batch_service.list_job_version_score_leaderboard(
            session,
            job_version_id=job_version_id,
            template_id=template_id,
        )
        assert board.batch is not None
        assert board.batch.status == "queued"
        assert board.batch.total_count == 1
        assert board.items[0].score_task_state == "queued"


def test_score_leaderboard_rejects_unknown_job_or_template(ai_client) -> None:
    from app.services.job_service import JobVersionNotFoundError
    from app.services.score_service import ScoreTemplateNotFoundError

    job = _create_job(
        ai_client,
        requirements=JobRequirements(must_have=["Python experience"]),
    )
    job_version_id = str(job["job_version_id"])
    template = ai_client.post("/v1/score-templates", json=_template_payload())
    assert template.status_code == 200, template.text
    template_id = template.json()["template_id"]
    database = ai_client.app.state.database

    with database.session_factory() as session:
        try:
            job_match_batch_service.list_job_version_score_leaderboard(
                session,
                job_version_id="00000000-0000-4000-8000-000000000000",
                template_id=template_id,
            )
        except JobVersionNotFoundError:
            pass
        else:
            raise AssertionError("expected JobVersionNotFoundError")

        try:
            job_match_batch_service.list_job_version_score_leaderboard(
                session,
                job_version_id=job_version_id,
                template_id="00000000-0000-4000-8000-000000000000",
            )
        except ScoreTemplateNotFoundError:
            pass
        else:
            raise AssertionError("expected ScoreTemplateNotFoundError")
```

> 注意：导入 `JobRequirements`。若测试模块里用到了 `_score_output` 走真实 worker，可复用 `test_resume_score_batches._score_output`；本计划里的 worker 调用用 monkeypatch 打分，见 Step 3 的实现说明（worker 会对 AI 打分打桩）。为让单测不触真实 AI，在 `ai_client` 上追加 monkeypatch，与 `test_resume_score_batches.py` 的 `fake_score_provider` 一致。若运行环境无 monkeypatch 夹具，则在 Step 1 测试签名加 `monkeypatch` 参数并把 `test_resume_score_batches._score_output` 的打桩套用上来。

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_job_match_score_leaderboard.py -v`
Expected: FAIL — `ImportError: cannot import name 'list_job_version_score_leaderboard' from 'app.services.job_match_batch_service'`

- [ ] **Step 3: Implement minimal code**

`app/schemas.py`，在 `JobMatchBatchResponse`（3776 行）之后追加：

```python
class JobMatchBatchEnqueue(ApiModel):
    score_template_id: str | None = None


class ScoreLeaderboardItem(ApiModel):
    resume_id: str
    candidate_id: str
    candidate_display_name: str | None
    score_total: float | None
    score_status: str | None
    score_task_state: Literal["none", "queued", "running"] = "none"


class ScoreLeaderboardResponse(ApiModel):
    items: list[ScoreLeaderboardItem]
    batch: ResumeScoreBatchResponse | None = None
```

`app/services/job_match_batch_service.py`：

import 区追加（`Candidate` 进 models import；评分相关从同包服务直引私有 helper，理由：同包内复用既有派生，且测试已广泛直引私有名）：

```python
from app.models import (
    ...,
    Candidate,
    ...,
)
from app.services.resume_library_service import (
    active_score_task_states,
    latest_current_scores_by_template,
)
from app.services.resume_score_batch_service import (
    _batch_response,
    _existing_active_batch,
    _require_scoreable_template,
    enqueue_resume_score_batch,
)
```

文件末尾（`get_job_match_batch` / `list_job_match_batch_items` 之后、`__all__` 之前）新增：

```python
def list_job_version_score_leaderboard(
    session: Session,
    *,
    job_version_id: str,
    template_id: str,
) -> ScoreLeaderboardResponse:
    """List the JD's eligible candidates with their general scores.

    The candidate set is the same server-derived eligible batch the JD matcher
    scores, so the right-hand score table can be compared side-by-side with the
    match leaderboard.  Each row carries the latest current-facts score for the
    selected template plus an in-progress marker derived from that template's
    active batch (reusing the resume library's helper).  Tenant isolation for
    the template and its batch follows ``with_loader_criteria`` / explicit
    organization predicates, exactly like the existing JD and score services.
    """

    job_version = session.scalar(
        select(JobVersion)
        .join(Job, Job.id == JobVersion.job_id)
        .where(JobVersion.id == job_version_id, Job.kind == "job")
    )
    if job_version is None:
        raise JobVersionNotFoundError("job_version_not_found")
    template, _ = _require_scoreable_template(session, template_id=template_id)

    snapshots = _eligible_batch_snapshots(
        session,
        organization_id=job_version.organization_id,
        resume_ids=None,
    )
    resume_ids = [resume_id for resume_id, _, _ in snapshots]
    facts_version_by_resume = {
        resume_id: facts_version for resume_id, _, facts_version in snapshots
    }
    scores_by_resume = latest_current_scores_by_template(
        session,
        resume_ids=resume_ids,
        template_id=template.id,
    )
    task_states = active_score_task_states(
        session,
        resume_ids,
        template_id=template.id,
    )

    candidates_by_resume: dict[str, tuple[str, str | None]] = {}
    if resume_ids:
        candidates_by_resume = {
            resume_id: (candidate_id, display_name)
            for resume_id, candidate_id, display_name in session.execute(
                select(Resume.id, Resume.candidate_id, Candidate.display_name)
                .join(Candidate, Candidate.id == Resume.candidate_id)
                .where(Resume.id.in_(resume_ids))
            ).all()
        }

    items = []
    for resume_id in resume_ids:
        score = scores_by_resume.get(resume_id)
        if (
            score is not None
            and score.facts_version != facts_version_by_resume.get(resume_id)
        ):
            score = None
        candidate_id, display_name = candidates_by_resume.get(
            resume_id, ("", None)
        )
        items.append(
            ScoreLeaderboardItem(
                resume_id=resume_id,
                candidate_id=candidate_id,
                candidate_display_name=display_name,
                score_total=score.total_score if score is not None else None,
                score_status=score.status if score is not None else None,
                score_task_state=task_states.get(resume_id, "none"),
            )
        )
    items.sort(
        key=lambda item: (
            item.score_total is None,
            -(item.score_total or 0.0),
            item.candidate_display_name or "",
        )
    )

    batch = _existing_active_batch(
        session,
        template_id=template.id,
        template_version=template.version,
        organization_id=template.organization_id,
    )
    return ScoreLeaderboardResponse(
        items=items,
        batch=_batch_response(batch) if batch is not None else None,
    )
```

更新 `__all__`（约 1140 行），加 `"list_job_version_score_leaderboard"`。

若 `_eligible_batch_snapshots` 与 `JobVersionNotFoundError`、`ScoreLeaderboard*` schema 尚未在 `job_match_batch_service.py` 作用域内，同步补 import（该文件已 import `JobVersionNotFoundError`、`_eligible_batch_snapshots`；`ScoreLeaderboardItem/Response` 需从 `app.schemas` 引入）。

> 真实 worker 打分：`run_resume_score_batch_worker_once` 会调用真实 deepseek 打分，单测必须打桩。沿用 `test_resume_score_batches._score_output`，在测试里 `monkeypatch.setattr("app.services.score_service.score_resume_fact_snapshot", fake_score_provider)`。

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_job_match_score_leaderboard.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add app/schemas.py app/services/job_match_batch_service.py tests/test_job_match_score_leaderboard.py
git commit -m "feat(match): 新增 JD 通用评分榜派生服务"
```

---

### Task 5: HTTP 端点——`match-all` 可选 body + `GET score-leaderboard`

**Files:**
- Modify: `app/main.py:7683-7705`、`app/main.py`（新 GET 端点，置于 matches 端点之后）
- Test: `tests/test_job_match_score_leaderboard.py`（追加 HTTP 用例）

**Interfaces:**
- Consumes: `JobMatchBatchEnqueue`、`ScoreLeaderboardResponse`、`list_job_version_score_leaderboard`、`enqueue_job_version_match_batch(score_template_id=...)`（Task 3/4）。
- Produces:
  - `POST /v1/job-versions/{job_version_id}/match-all` 接受可选 body `JobMatchBatchEnqueue`；无 body 时与现状完全一致。错误映射：`JobVersionNotFoundError`/`ScoreTemplateNotFoundError` → 404，`ScoreServiceError` → 409，`JobServiceError` → 既有 `_raise_job_service_error`。
  - `GET /v1/job-versions/{job_version_id}/score-leaderboard?template_id=...` → `ScoreLeaderboardResponse`。`JobVersionNotFoundError`/`ScoreTemplateNotFoundError` → 404，`ScoreServiceError` → 409。

- [ ] **Step 1: Write the failing test**

在 `tests/test_job_match_score_leaderboard.py` 追加：

```python
def test_match_all_endpoint_with_score_template_id_enqueues_both_batches(
    ai_client,
    monkeypatch,
) -> None:
    from app.models import ResumeScoreBatch
    from test_resume_score_batches import _score_output

    def fake_score_provider(**kwargs: object) -> dict[str, object]:
        return _score_output(**kwargs)

    monkeypatch.setattr(
        "app.services.score_service.score_resume_fact_snapshot",
        fake_score_provider,
    )

    source_text = "教育经历 清华大学 计算机 工作经历 Acme Python Engineer 技能 Python SQL"
    _save_ready_resume(ai_client, source_text=source_text)
    _save_ready_resume(ai_client, source_text=source_text)
    job = _create_job(
        ai_client,
        requirements=JobRequirements(must_have=["Python experience"]),
    )
    job_version_id = str(job["job_version_id"])
    template = ai_client.post("/v1/score-templates", json=_template_payload())
    assert template.status_code == 200, template.text
    template_id = template.json()["template_id"]

    matched = ai_client.post(
        f"/v1/job-versions/{job_version_id}/match-all",
        json={"score_template_id": template_id},
    )
    assert matched.status_code == 200, matched.text
    assert matched.json()["status"] == "queued"
    assert matched.json()["total_count"] == 2

    database = ai_client.app.state.database
    with database.session_factory() as session:
        score_batch = session.scalar(
            select(ResumeScoreBatch).where(
                ResumeScoreBatch.template_id == template_id,
                ResumeScoreBatch.status == "queued",
            )
        )
        assert score_batch is not None
        assert score_batch.total_count == 2


def test_match_all_endpoint_without_body_is_backward_compatible(ai_client) -> None:
    from app.models import ResumeScoreBatch

    source_text = "教育经历 清华大学 计算机 工作经历 Acme Python Engineer 技能 Python SQL"
    _save_ready_resume(ai_client, source_text=source_text)
    job = _create_job(
        ai_client,
        requirements=JobRequirements(must_have=["Python experience"]),
    )
    job_version_id = str(job["job_version_id"])

    matched = ai_client.post(f"/v1/job-versions/{job_version_id}/match-all")
    assert matched.status_code == 200, matched.text
    assert matched.json()["total_count"] == 1

    database = ai_client.app.state.database
    with database.session_factory() as session:
        assert session.scalar(select(func.count(ResumeScoreBatch.id))) == 0


def test_score_leaderboard_endpoint_returns_items_and_batch(ai_client) -> None:
    source_text = "教育经历 清华大学 计算机 工作经历 Acme Python Engineer 技能 Python SQL"
    _save_ready_resume(ai_client, source_text=source_text)
    job = _create_job(
        ai_client,
        requirements=JobRequirements(must_have=["Python experience"]),
    )
    job_version_id = str(job["job_version_id"])
    template = ai_client.post("/v1/score-templates", json=_template_payload())
    assert template.status_code == 200, template.text
    template_id = template.json()["template_id"]

    board = ai_client.get(
        f"/v1/job-versions/{job_version_id}/score-leaderboard",
        params={"template_id": template_id},
    )
    assert board.status_code == 200, board.text
    payload = board.json()
    assert payload["batch"] is None
    assert len(payload["items"]) == 1
    assert payload["items"][0]["score_task_state"] == "none"
```

> 每个测试文件顶部已 `from sqlalchemy import select`；需补 `from sqlalchemy import func` 与 `JobRequirements` 导入。

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_job_match_score_leaderboard.py -v`
Expected: 新增三个用例 FAIL（端点 422/404 或未接受 body）。

- [ ] **Step 3: Implement minimal code**

`app/main.py`，`from app.schemas import (...)`（58 行区）追加 `JobMatchBatchEnqueue`、`ScoreLeaderboardResponse`。

`match-all` 端点（7683-7705 行）改为接受可选 body 并映射评分错误：

```python
    @app.post(
        "/v1/job-versions/{job_version_id}/match-all",
        response_model=JobMatchBatchResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def post_enqueue_job_version_match_batch(
        job_version_id: str,
        payload: JobMatchBatchEnqueue | None = None,
        session: Session = Depends(get_session),
    ) -> JobMatchBatchResponse:
        try:
            response = enqueue_job_version_match_batch(
                session,
                job_version_id=job_version_id,
                settings=settings,
                score_template_id=payload.score_template_id if payload else None,
            )
        except JobVersionNotFoundError as exc:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ScoreTemplateNotFoundError as exc:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ScoreServiceError as exc:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except JobServiceError as exc:
            session.rollback()
            _raise_job_service_error(exc)
        _commit_or_raise(session)
        return response
```

在 `GET /v1/job-versions/{job_version_id}/matches` 端点之后新增评分榜端点：

```python
    @app.get(
        "/v1/job-versions/{job_version_id}/score-leaderboard",
        response_model=ScoreLeaderboardResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def get_job_version_score_leaderboard(
        job_version_id: str,
        template_id: str,
        session: Session = Depends(get_session),
    ) -> ScoreLeaderboardResponse:
        try:
            return list_job_version_score_leaderboard(
                session,
                job_version_id=job_version_id,
                template_id=template_id,
            )
        except JobVersionNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ScoreTemplateNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ScoreServiceError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_job_match_score_leaderboard.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: Run full backend suite**

Run: `pytest -q`
Expected: 全量通过（既有 1191 用例 + 新增用例）。

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_job_match_score_leaderboard.py
git commit -m "feat(match): match-all 接受 score_template_id 并新增 score-leaderboard 端点"
```

---

### Task 6: 后端租户隔离单测（两工作区）

**Files:**
- Test: `tests/test_job_match_score_leaderboard.py`（追加）

**Interfaces:**
- Consumes: `score_batch_workspace_clients`、`_register_and_login`、`_seed_ready_resume`（test_resume_score_batch_tenant_isolation）、`_workspace`（tenant_scope）、`job_service.create_job`。

- [ ] **Step 1: Write the failing test**

在 `tests/test_job_match_score_leaderboard.py` 追加：

```python
def test_score_leaderboard_is_tenant_isolated(
    score_batch_workspace_clients,
) -> None:
    from app.schemas import JobRequirements as JReqs
    from app.services import job_service
    from test_resume_score_batch_tenant_isolation import (
        _create_template,
        _register_and_login,
        _seed_ready_resume,
    )

    client_a, client_b = score_batch_workspace_clients
    organization_a = _register_and_login(
        client_a,
        organization_name="Leaderboard Alpha",
        email="leaderboard-alpha@example.com",
    )
    organization_b = _register_and_login(
        client_b,
        organization_name="Leaderboard Beta",
        email="leaderboard-beta@example.com",
    )
    _, foreign_resume_id = _seed_ready_resume(
        _session(client_a),
        organization_id=organization_b,
        label="beta-ready",
    )
    a_session = _session(client_a)
    with _workspace(a_session, organization_a):
        a_resume_id, _ = _seed_ready_resume(
            a_session,
            organization_id=organization_a,
            label="alpha-ready",
        )
        template_a = _create_template(client_a, name="Alpha template")
        job = job_service.create_job(
            a_session,
            payload=JReqs(must_have=["Python experience"]) and _job_create_payload(),
        )
        a_session.commit()
    job_version_id = str(job.job_version_id)

    # B 工作区的评分批次/简历不得泄漏到 A 的评分榜。
    b_session = _session(client_b)
    with _workspace(b_session, organization_b):
        _score_batch_for(b_session, template_id=_create_template(client_b, name="Beta template"), resume_id=foreign_resume_id)
        b_session.commit()

    board = client_a.get(
        f"/v1/job-versions/{job_version_id}/score-leaderboard",
        params={"template_id": template_a},
    )
    assert board.status_code == 200, board.text
    assert {item["resume_id"] for item in board.json()["items"]} == {a_resume_id}

    # A 工作区评分榜看不到 B 的模板。
    foreign = client_a.get(
        f"/v1/job-versions/{job_version_id}/score-leaderboard",
        params={"template_id": b_template_id},
    )
    assert foreign.status_code == 404, foreign.text
```

> 该测试引用了本测试模块未定义的 `_session`、`_score_batch_for`、`_job_create_payload`、`b_template_id`。请在实现时补齐这些局部小 helper（每个都极短，见下）。完整可运行版本：

```python
def _job_create_payload() -> dict[str, object]:
    from app.schemas import JobCreate, JobRequirements

    return JobCreate(
        title="Tenant Backend Engineer",
        jd_text="Must have Python experience.",
        requirements=JobRequirements(must_have=["Python experience"]),
    ).model_dump()


def test_score_leaderboard_is_tenant_isolated(
    score_batch_workspace_clients,
) -> None:
    from app.services import job_service
    from test_resume_score_batch_tenant_isolation import (
        _create_template,
        _register_and_login,
        _seed_ready_resume,
    )

    client_a, client_b = score_batch_workspace_clients
    organization_a = _register_and_login(
        client_a,
        organization_name="Leaderboard Alpha",
        email="leaderboard-alpha@example.com",
    )
    organization_b = _register_and_login(
        client_b,
        organization_name="Leaderboard Beta",
        email="leaderboard-beta@example.com",
    )
    database = client_a.app.state.database

    with database.session_factory() as session:
        with _workspace(session, organization_a):
            a_resume_id, _ = _seed_ready_resume(
                session, organization_id=organization_a, label="alpha-ready"
            )
        template_a = _create_template(client_a, name="Alpha template")

        with _workspace(session, organization_a):
            job = job_service.create_job(
                session,
                payload=JobCreate(
                    title="Tenant Backend Engineer",
                    jd_text="Must have Python experience.",
                    requirements=JobRequirements(
                        must_have=["Python experience"]
                    ),
                ),
            )
        session.commit()
    job_version_id = str(job.job_version_id)

    with database.session_factory() as session:
        with _workspace(session, organization_b):
            _seed_ready_resume(
                session, organization_id=organization_b, label="beta-ready"
            )
        b_template_id = _create_template(client_b, name="Beta template")
        session.commit()

    board = client_a.get(
        f"/v1/job-versions/{job_version_id}/score-leaderboard",
        params={"template_id": template_a},
    )
    assert board.status_code == 200, board.text
    assert {item["resume_id"] for item in board.json()["items"]} == {a_resume_id}

    foreign = client_a.get(
        f"/v1/job-versions/{job_version_id}/score-leaderboard",
        params={"template_id": b_template_id},
    )
    assert foreign.status_code == 404, foreign.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_job_match_score_leaderboard.py::test_score_leaderboard_is_tenant_isolated -v`
Expected: FAIL — 端点尚未存在（404/422）。

- [ ] **Step 3: 实现**

该用例不新增产品代码（依赖 Task 4/5 的端点 + 既有 `with_loader_criteria`），只需把测试写对。若 `_create_template`/`_seed_ready_resume` 的导入路径与签名有出入，以 `test_resume_score_batch_tenant_isolation.py` 实际定义为准。

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_job_match_score_leaderboard.py -v`
Expected: PASS（含 B 工作区 resume 不泄漏、B 模板对 A 404）。

- [ ] **Step 5: Commit**

```bash
git add tests/test_job_match_score_leaderboard.py
git commit -m "test(match): 评分榜跨工作区租户隔离"
```

---

### Task 7: 前端类型 + API 客户端

**Files:**
- Modify: `web/src/types.ts`（`ScoreTemplate` 约 1594 行、`ResumeScoreBatch` 约 1695 行附近）
- Modify: `web/src/api.ts:1028-1030`（`enqueueAllJobMatches`）、`web/src/api.ts`（`listJobVersionMatches` 1046 行附近加新方法）

**Interfaces:**
- Produces:
  - `ScoreLeaderboardItem`、`ScoreLeaderboard`（TS 类型）。
  - `api.enqueueAllJobMatches(jobVersionId, scoreTemplateId?)` — 带 `score_template_id` body（未传则无 body）。
  - `api.listJobVersionScoreLeaderboard(jobVersionId, templateId): Promise<ScoreLeaderboard>`。

- [ ] **Step 1: Write the failing test（类型/编译门）**

Run: `cd web && npx tsc --noEmit`
Expected: 当前应通过（作为基线）。

在 `web/src/types.ts` 追加类型后，再跑一次 `npx tsc --noEmit` 确认不破坏既有类型。

- [ ] **Step 2: Implement**

`web/src/types.ts`（放在 `ScoreTemplate` 附近）：

```ts
export interface ScoreLeaderboardItem {
  resume_id: string;
  candidate_id: string;
  candidate_display_name: string | null;
  score_total: number | null;
  score_status: "succeeded" | "needs_review" | "overridden" | null;
  score_task_state: "none" | "queued" | "running";
}

export interface ScoreLeaderboard {
  items: ScoreLeaderboardItem[];
  batch: ResumeScoreBatch | null;
}
```

`web/src/api.ts`：

```ts
    enqueueAllJobMatches(
      jobVersionId: string,
      scoreTemplateId?: string,
    ): Promise<JobMatchBatch> {
      return request<JobMatchBatch>(
        `/job-versions/${resourcePath(jobVersionId)}/match-all`,
        {
          method: "POST",
          body: scoreTemplateId
            ? { score_template_id: scoreTemplateId }
            : undefined,
        },
      );
    },
```

`listJobVersionMatches` 之后加：

```ts
    listJobVersionScoreLeaderboard(
      jobVersionId: string,
      templateId: string,
    ): Promise<ScoreLeaderboard> {
      return request<ScoreLeaderboard>(
        `/job-versions/${resourcePath(jobVersionId)}/score-leaderboard?template_id=${encodeURIComponent(templateId)}`,
      );
    },
```

`request<T>` 已处理可选 body（`body !== undefined` 时 `JSON.stringify`），无需改动。

- [ ] **Step 3: Verify build**

Run: `cd web && npm run build`
Expected: 构建通过。

- [ ] **Step 4: Commit**

```bash
git add web/src/types.ts web/src/api.ts
git commit -m "feat(web): 评分榜类型与 API 客户端"
```

---

### Task 8: 评分表组件 `ScoreLeaderboard` + 动画 CSS

**Files:**
- Create: `web/src/features/job-match/ScoreLeaderboard.tsx`
- Modify: `web/src/features/job-match/job-match.css`

**Interfaces:**
- Consumes: `ScoreLeaderboard` 类型（Task 7）、`Icon`、`match-table`/`match-results-loading`/`empty-state` 等既有 class。
- Produces: `ScoreLeaderboard({ board, loading, templateName })` 组件；`.score-leaderboard`、`.score-activity`（脉动圆点 + 「评分生成中…」）、`.score-number`、`.score-muted`、`score-ai-orb-gradient`/`score-activity-pulse` keyframes + `prefers-reduced-motion`。

- [ ] **Step 1: Write the failing test（编译门）**

Run: `cd web && npx tsc --noEmit`
Expected: 基线通过；加入组件后无类型错误。

- [ ] **Step 2: Create the component**

`web/src/features/job-match/ScoreLeaderboard.tsx`：

```tsx
import type { ScoreLeaderboard as ScoreLeaderboardData } from "../../types";
import { Icon } from "../../icons";

function scoreTaskInProgress(state: string): boolean {
  return state === "queued" || state === "running";
}

export function ScoreLeaderboard({
  board,
  loading,
  templateName,
}: {
  board: ScoreLeaderboardData;
  loading: boolean;
  templateName: string | null;
}) {
  const batchActive =
    board.batch?.status === "queued" || board.batch?.status === "running";
  return (
    <section className="panel score-leaderboard">
      <div className="panel-heading">
        <div>
          <h2>通用评分</h2>
          <p>
            {templateName
              ? `模板：${templateName}`
              : "按所选评分模板对合格候选人打分"}
          </p>
        </div>
        {batchActive && board.batch ? (
          <span className="status-pill" role="status">
            评分任务进行中 {board.batch.completed_count}/{board.batch.total_count}
          </span>
        ) : (
          <span className="status-pill">{board.items.length} 名候选人</span>
        )}
      </div>
      {loading ? (
        <div
          aria-busy="true"
          aria-label="正在加载通用评分"
          className="match-results-loading"
        >
          <span className="skeleton match-results-loading-card" />
          <span className="skeleton match-results-loading-card" />
        </div>
      ) : board.items.length ? (
        <div className="match-table-wrap">
          <table className="match-table">
            <thead>
              <tr>
                <th scope="col">排名</th>
                <th scope="col">候选人</th>
                <th scope="col">通用分</th>
                <th scope="col">状态</th>
              </tr>
            </thead>
            <tbody>
              {board.items.map((item, index) => (
                <ScoreRow key={item.resume_id} item={item} rank={index + 1} />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty-state match-empty-state">
          <div className="empty-state-inner">
            <span className="empty-glyph">
              <Icon name="activity" size={23} />
            </span>
            <h2>尚无通用评分</h2>
            <p>发起岗位评估时会自动为同一批候选人补分。</p>
          </div>
        </div>
      )}
    </section>
  );
}

function ScoreRow({
  item,
  rank,
}: {
  item: ScoreLeaderboardData["items"][number];
  rank: number;
}) {
  const inProgress = scoreTaskInProgress(item.score_task_state);
  return (
    <tr className="score-candidate-row">
      <td className="score-rank">
        <span className="match-rank-number">{rank}</span>
      </td>
      <td>
        <strong>{item.candidate_display_name?.trim() || "未命名候选人"}</strong>
      </td>
      <td>
        {inProgress ? (
          <span className="score-activity" role="status" aria-label="评分生成中">
            <span className="score-activity-dot" aria-hidden="true" />
            <span className="score-activity-copy">评分生成中…</span>
          </span>
        ) : item.score_total !== null ? (
          <strong className="score-number">{item.score_total.toFixed(1)}</strong>
        ) : (
          <span className="score-muted">尚无通用评分</span>
        )}
      </td>
      <td>{scoreStatusLabel(item.score_status)}</td>
    </tr>
  );
}

function scoreStatusLabel(
  status: ScoreLeaderboardData["items"][number]["score_status"],
): string {
  if (status === "succeeded") return "已完成";
  if (status === "needs_review") return "待人工复核";
  if (status === "overridden") return "已人工覆盖";
  return "—";
}
```

- [ ] **Step 3: Add animation + table CSS**

`web/src/features/job-match/job-match.css` 追加（复用简历库脉动圆点动画语言，命名空间到 job-match）：

```css
.backoffice-ui-root .job-match-workspace .score-leaderboard {
  /* 与左表高度独立，避免 grid 拉伸被空态撑高 */
  align-self: start;
}

.backoffice-ui-root .job-match-workspace .score-activity {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  color: #4338ca;
  font-size: 0.6875rem;
  font-weight: 600;
  line-height: 1.2;
  white-space: nowrap;
}

.backoffice-ui-root .job-match-workspace .score-activity-dot {
  width: 0.5rem;
  height: 0.5rem;
  flex: none;
  background: linear-gradient(135deg, #2563eb 0%, #7c3aed 48%, #d946ef 100%);
  background-size: 180% 180%;
  border-radius: 9999px;
  box-shadow: 0 0 6px rgb(79 70 229 / 0.45);
  animation:
    score-ai-orb-gradient 2.4s ease-in-out infinite,
    score-activity-pulse 1.4s ease-in-out infinite;
}

@keyframes score-ai-orb-gradient {
  0%,
  100% {
    background-position: 0% 50%;
  }

  50% {
    background-position: 100% 50%;
  }
}

@keyframes score-activity-pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }

  50% {
    opacity: 0.45;
    transform: scale(0.72);
  }
}

@media (prefers-reduced-motion: reduce) {
  .backoffice-ui-root .job-match-workspace .score-activity-dot {
    animation: none;
  }
}

.backoffice-ui-root .job-match-workspace .score-number {
  color: #4338ca;
  font-size: 0.875rem;
}

.backoffice-ui-root .job-match-workspace .score-muted {
  color: var(--ink-muted);
  font-size: 0.8125rem;
}
```

- [ ] **Step 4: Verify build**

Run: `cd web && npm run build`
Expected: 通过。

- [ ] **Step 5: Commit**

```bash
git add web/src/features/job-match/ScoreLeaderboard.tsx web/src/features/job-match/job-match.css
git commit -m "feat(web): 通用评分表组件与生成中动画"
```

---

### Task 9: `MatchWorkspace` 接线——模板选择器 + 左右并排 + 补分闭环

**Files:**
- Modify: `web/src/features/job-match/MatchWorkspace.tsx`
- Modify: `web/src/features/job-match/job-match.css`（`.score-loop-tables`、`.score-template-switcher`）

**Interfaces:**
- Consumes: `ScoreLeaderboard`（Task 8）、`ScoreTemplate`/`ScoreLeaderboard` 类型与 api（Task 7）、`AI_STATUS_POLL_INTERVAL_MS`。
- Produces: 顶部（jd-switcher 下方）评分模板选择器（默认最新模板，无模板时禁用提示）；「开始岗位评分」携带 `scoreTemplateId`；匹配区下方 `.score-loop-tables` grid 左右并排 `MatchLeaderboard` + `ScoreLeaderboard`；评分榜轮询（active 时 2.5s 拉取）。

- [ ] **Step 1: Write the failing test（编译门）**

Run: `cd web && npx tsc --noEmit`
Expected: 基线通过；接线后无类型错误。

- [ ] **Step 2: Add state + imports**

`web/src/features/job-match/MatchWorkspace.tsx`：

import 区追加（类型、组件、轮询常量）：

```ts
import { AI_STATUS_POLL_INTERVAL_MS } from "../../backoffice/utils/ai-extraction";
import { ScoreLeaderboard } from "./ScoreLeaderboard";
import type {
  JobMatch,
  JobMatchBatch,
  JobMatchBatchItem,
  JobMatchRequirementResult,
  JobRequirements,
  JobVersion,
  ScoreLeaderboard as ScoreLeaderboardData,
  ScoreTemplate,
} from "../../types";
```

state（`matchesLoading` 之后）加：

```ts
  const [scoreTemplates, setScoreTemplates] = useState<ScoreTemplate[]>([]);
  const [scoreTemplateId, setScoreTemplateId] = useState("");
  const [scoreLeaderboard, setScoreLeaderboard] =
    useState<ScoreLeaderboardData | null>(null);
  const [scoreLeaderboardLoading, setScoreLeaderboardLoading] = useState(false);
  const selectedScoreTemplate = useMemo(
    () => scoreTemplates.find((item) => item.template_id === scoreTemplateId) ?? null,
    [scoreTemplates, scoreTemplateId],
  );
```

- [ ] **Step 3: Load templates + leaderboard + polling effects**

`runAllMatches`（327-352 行）改为携带模板并在成功后刷新评分榜：

```ts
  const runAllMatches = async () => {
    if (!jobVersion || jobVersion.status !== "confirmed") {
      notify("error", "请先启用岗位，再批量匹配简历。");
      return;
    }
    if (!jobVersion.requirements.length) {
      notify("error", "原版 JD 未生成匹配条件，不能批量运行 AI 匹配。");
      return;
    }
    setLoading(true);
    try {
      const response = await api.enqueueAllJobMatches(
        jobVersion.job_version_id,
        scoreTemplateId || undefined,
      );
      setMatchBatch(response);
      setBatchItems([]);
      void fetchScoreLeaderboard();
      notify(
        "success",
        `已将 ${response.total_count} 份简历加入岗位评估队列。`,
      );
    } catch (error) {
      notify("error", formatError(error));
    } finally {
      setLoading(false);
    }
  };
```

模板加载 effect（matching 模式、进页面一次）：

```ts
  useEffect(() => {
    if (mode !== "matching") return;
    let cancelled = false;
    void api
      .listScoreTemplates()
      .then((templates) => {
        if (cancelled) return;
        setScoreTemplates(templates);
        setScoreTemplateId((current) =>
          current && templates.some((item) => item.template_id === current)
            ? current
            : (templates[0]?.template_id ?? ""),
        );
      })
      .catch(() => {
        // 评分模板加载失败不阻塞匹配；无模板时评分表会显示提示。
      });
    return () => {
      cancelled = true;
    };
  }, [mode]);

  const fetchScoreLeaderboard = useCallback(() => {
    if (
      mode !== "matching" ||
      !jobVersion ||
      jobVersion.status !== "confirmed" ||
      !jobVersion.requirements.length ||
      !scoreTemplateId
    ) {
      setScoreLeaderboard(null);
      return;
    }
    setScoreLeaderboardLoading(true);
    void api
      .listJobVersionScoreLeaderboard(jobVersion.job_version_id, scoreTemplateId)
      .then((board) => setScoreLeaderboard(board))
      .catch((error) => notify("error", formatError(error)))
      .finally(() => setScoreLeaderboardLoading(false));
  }, [jobVersion, mode, notify, formatError, scoreTemplateId]);
```

> `runAllMatches` 引用了 `fetchScoreLeaderboard`（在其定义之前），用 `useCallback` 且保持引用稳定即可；若 lint 要求先声明再使用，把 `fetchScoreLeaderboard` 的 `useCallback` 定义移到 `runAllMatches` 之前。

评分榜轮询（active 时 2.5s；每 tick 一个请求，全部结束即停）：

```ts
  useEffect(() => {
    const board = scoreLeaderboard;
    const active =
      board?.batch?.status === "queued" ||
      board?.batch?.status === "running" ||
      (board?.items.some(
        (item) =>
          item.score_task_state === "queued" ||
          item.score_task_state === "running",
      ) ?? false);
    if (!active) return;
    const timer = window.setInterval(() => {
      void fetchScoreLeaderboard();
    }, AI_STATUS_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [fetchScoreLeaderboard, scoreLeaderboard]);
```

- [ ] **Step 4: Add template selector UI + two-table grid**

顶部模板选择器：放在 jd-switcher（444-491 行）之后、同一 `panel` 内：

```tsx
            {isMatching && (
              <div className="score-template-switcher">
                <div>
                  <span className="field-label">通用评分模板</span>
                  <p>发起岗位评估时，会自动为同一批候选人按此模板补分。</p>
                </div>
                <div className="score-template-select">
                  {scoreTemplates.length ? (
                    <BackofficeSelect
                      ariaLabel="选择通用评分模板"
                      id="score-template-selector"
                      onChange={(value) => setScoreTemplateId(value)}
                      options={scoreTemplates.map((template) => ({
                        label: template.name,
                        value: template.template_id,
                      }))}
                      value={scoreTemplateId}
                    />
                  ) : (
                    <p className="score-template-hint">
                      尚未创建评分模板，去评分工作区创建模板后即可自动补分。
                    </p>
                  )}
                </div>
              </div>
            )}
```

两表容器：把 814-820 行的 `MatchLeaderboard` 替换为左右并排 grid：

```tsx
          {isMatching && jobCanMatch && (
            <div className="score-loop-tables">
              <MatchLeaderboard
                loading={matchesLoading}
                matches={jobMatches}
                onOpenResume={onOpenMatchedResume}
              />
              <ScoreLeaderboard
                board={scoreLeaderboard ?? { items: [], batch: null }}
                loading={scoreLeaderboardLoading}
                templateName={selectedScoreTemplate?.name ?? null}
              />
            </div>
          )}
```

- [ ] **Step 5: Add layout CSS**

`job-match.css` 追加：

```css
.backoffice-ui-root .job-match-workspace .score-loop-tables {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--space-lg);
  align-items: start;
}

@media (max-width: 1080px) {
  .backoffice-ui-root .job-match-workspace .score-loop-tables {
    grid-template-columns: minmax(0, 1fr);
  }
}

.backoffice-ui-root .job-match-workspace .score-template-switcher {
  display: flex;
  gap: var(--space-md);
  align-items: end;
  justify-content: space-between;
  padding: 0 0 var(--space-md);
  margin: 0 0 var(--space-lg);
  border-bottom: 1px solid var(--line);
}

.backoffice-ui-root .job-match-workspace .score-template-switcher p {
  margin: 0.3rem 0 0;
  color: var(--ink-muted);
  font-size: 0.8125rem;
}

.backoffice-ui-root .job-match-workspace .score-template-select {
  flex: 0 1 22rem;
}

.backoffice-ui-root .job-match-workspace .score-template-hint {
  color: var(--ink-muted);
  font-size: 0.8125rem;
}
```

- [ ] **Step 6: Verify build**

Run: `cd web && npm run build`
Expected: 通过。

- [ ] **Step 7: Commit**

```bash
git add web/src/features/job-match/MatchWorkspace.tsx web/src/features/job-match/job-match.css
git commit -m "feat(web): 智能匹配左右并排评分表与补分闭环接线"
```

---

### Task 10: 前端 e2e——左右两表同屏 + 评分动画落分

**Files:**
- Create: `web/e2e/job-match-score-loop.spec.ts`

**Interfaces:**
- Consumes: `registerAndVerify`、`seedWorkspaceFixture`（`e2e/playwright_app.py` 已种 3 份简历 + 已确认 JD「E2E 后端工程师」+ 评分模板「E2E 评分规则」+ resume[0] 的 76.0 分）。

- [ ] **Step 1: Write the failing test**

```ts
import { expect, test } from "@playwright/test";

import { registerAndVerify, seedWorkspaceFixture } from "./helpers";

test("智能匹配左右并排两个表，通用评分可生成中并落分", async ({ page }) => {
  await registerAndVerify(page, "job-match-score-loop");
  await seedWorkspaceFixture(page);

  // 评分榜生成中 → 完成后落分：前 2 次轮询返回 running，之后返回 none + 88 分。
  let leaderboardPolls = 0;
  await page.route("**/v1/job-versions/**/score-leaderboard**", async (route) => {
    const response = await route.fetch();
    const payload = (await response.json()) as {
      items?: Array<Record<string, unknown>>;
      batch?: Record<string, unknown> | null;
    };
    leaderboardPolls += 1;
    const stillGenerating = leaderboardPolls <= 2;
    await route.fulfill({
      response,
      json: {
        ...payload,
        batch: stillGenerating
          ? {
              batch_id: "e2e-score-batch",
              status: "running",
              total_count: 1,
              completed_count: 0,
            }
          : null,
        items: (payload.items ?? []).map((item, index) => ({
          ...item,
          score_task_state: stillGenerating ? "running" : "none",
          score_total: stillGenerating ? null : index === 0 ? 88 : null,
          score_status: stillGenerating ? null : index === 0 ? "succeeded" : null,
        })),
      },
    });
  });

  await page.getByRole("button", { name: "智能匹配", exact: true }).click();

  // 左右并排两个表。
  const matchTable = page.locator(".match-leaderboard");
  const scoreTable = page.locator(".score-leaderboard");
  await expect(matchTable).toBeVisible();
  await expect(scoreTable).toBeVisible();
  await expect(page.locator(".score-loop-tables")).toBeVisible();

  // 评分表生成中动画。
  const activity = scoreTable.locator(".score-activity").first();
  await expect(activity).toBeVisible();
  await expect(activity).toHaveAttribute("role", "status");
  await expect(scoreTable.getByText("评分生成中…").first()).toBeVisible();
  const dot = activity.locator(".score-activity-dot");
  await expect(dot).toHaveAttribute("aria-hidden", "true");

  // 完成后动画消失、回到分数数字。
  await expect(activity).not.toBeVisible({ timeout: 10_000 });
  await expect(scoreTable.locator(".score-number").first()).toHaveText("88.0");
});
```

> `registerAndVerify`/`seedWorkspaceFixture` 的导航目标以 `web/e2e/helpers.ts` 现有约定为准；若「智能匹配」按钮文案不同，以导航到匹配工作区的既有 e2e 写法为准（参考 `web/e2e/job-match.spec.ts` 或 `match-workspace.spec.ts` 里的进入方式）。若 fixture 未给 JD 预跑匹配，先用真实接口触发一次「开始岗位评分」再断言两表。

- [ ] **Step 2: Run the e2e test**

Run: `cd web && npx playwright test e2e/job-match-score-loop.spec.ts`
Expected: FAIL（新文件，端点/组件尚未全量生效前先红）——随后在实现完整后转绿。

> 注意：机器并行测试争用（8012/5176 端口）会让 vite 崩。e2e 必须独占串行跑，不要与 pytest 并行。

- [ ] **Step 3: Iterate until green**

按 `resume-library-score-activity.spec.ts` 的 mock 模式校准轮询次数与路由匹配；确认「开始岗位评分」按钮、左右两表容器、`.score-activity` 类名与实现一致。

- [ ] **Step 4: Run the e2e test again**

Run: `cd web && npx playwright test e2e/job-match-score-loop.spec.ts`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add web/e2e/job-match-score-loop.spec.ts
git commit -m "test(web): 智能匹配左右两表与评分动画落分 e2e"
```

---

### Task 11: 收尾验证

- [ ] **Step 1: 后端全量**

Run: `pytest -q`
Expected: 全部 PASS（含既有 1191 passed, 17 skipped 基线）。

- [ ] **Step 2: 前端构建**

Run: `cd web && npm run build`
Expected: 通过。

- [ ] **Step 3: e2e 串行全跑**

Run: `cd web && npx playwright test`
Expected: 既有 e2e + 新增 `job-match-score-loop.spec.ts` 全绿。

- [ ] **Step 4: 自查对照设计**

对照 `docs/superpowers/specs/2026-08-10-smart-match-score-loop-design.md` 逐条核对：
- 左表「JD 匹配」未改动列/排序；右表「通用评分」新增。
- 顶部模板选择器默认最新；无模板时评分表禁用并提示。
- 匹配时自动补分（`match-all` 带 `score_template_id` → 同一批候选人入评分批次）。
- 无权重、无综合分、无新表迁移。

- [ ] **Step 5: Commit（若 Step 1-3 有补丁）**

```bash
git add -A
git commit -m "test: 收尾验证通过"
```

---

## Self-Review 记录

- **Spec 覆盖**：左右并排两表（Task 9/10）、模板选择器（Task 9）、match-all 带 `score_template_id` 补分（Task 3/5）、score-leaderboard 端点（Task 4/5）、派生共享 helper（Task 2）、动画复用（Task 8）、无模板提示（Task 9）、租户隔离（Task 6）、无新表/迁移（全部）、`MatchLeaderboard` 不动（Task 9 仅包裹不修改）——全部有落点。
- **占位符扫描**：无 TBD/TODO；每个代码步骤给全实际代码。Task 6 内联了两版测试（先精简版后完整版），已明确以完整版为准并注明 helper 依赖既有模块。
- **类型一致性**：`score_task_state` 统一 `"none" | "queued" | "running"`；`score_total` 前端 `number | null` ↔ 后端 `float | None`；`batch` 复用 `ResumeScoreBatchResponse`/`ResumeScoreBatch`；`active_score_task_states`/`latest_current_scores_by_template` 在两个 task 中的签名一致；`enqueue_resume_score_batch(..., resume_ids=...)` 在两个消费点签名一致。
