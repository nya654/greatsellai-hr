# 简历库评分生成动画 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 简历库逐行"AI 评分"格在评分生成期间显示脉动圆点 + "评分生成中…"动画，完成后自动变回分数数字。

**Architecture:** 后端在 `list_resume_library` 响应里派生一个永不落库的 `score_task_state` 字段（取自当前工作区活跃评分批次 item，租户自动隔离，无迁移），前端评分格据此渲染动画并扩展现有整页轮询的 `.some()` 触发条件。请求数不变：每 tick 仍只发 1 个页面级请求。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.0（`with_loader_criteria` 租户隔离）、React 19 + Semi UI + Vite + TypeScript、Playwright e2e。

**Spec:** `docs/superpowers/specs/2026-08-10-resume-library-score-activity-design.md`

## Global Constraints

- `score_task_state` 只算不落库，值域严格为 `"none" | "queued" | "running"`，默认 `"none"`。
- 派生查询必须命中 `ResumeScoreBatchItem.status IN ('queued','running')` **且** `ResumeScoreBatch.status IN ('queued','running')`；跨模板多个活跃 item 时取最宽口径（任一 running → `running`，否则任一 queued → `queued`）。
- 租户隔离靠现有 `with_loader_criteria`（`tenant_scope.py`），派生查询**不得**手写 `organization_id` 谓词，也不得 `bypass_organization_scope`。
- 现有字段语义不变：`score_total` / `score_status` / `score_template_name` / `score_created_at` 互不干扰。
- 前端轮询保持整页单请求（`AI_STATUS_POLL_INTERVAL_MS = 2500`），仅在当前页存在 `score_task_state` 为 queued/running 的行时触发；该请求只读数据库、不触碰 AI 评分队列。
- 重新评分时，运行期间动画盖住旧分数（旧分已过期）。
- 动画复用 `library-ai-orb-gradient` 脉动语言，遵守 `prefers-reduced-motion` 降级为静态。
- 完成态回到现有分数数字展示；不做评分 ETA、不动顶部汇总条、不动 `ScoreWorkspace` / `MatchWorkspace`。
- 无障碍：动画容器 `role="status"` + `aria-label="正在生成 AI 评分"`，圆点 `aria-hidden`。
- 测试环境：后端 `python -m pytest -q`；前端 `npm run build`（含 tsc）；e2e `npm run e2e`（**必须独占串行跑**，见机器并行争用 memory）。

---

### Task 1: 后端 `score_task_state`（schema + 派生 + 单测）

**Files:**
- Test: `tests/test_resume_library_api.py`（改字段全集断言 + 加 3 个状态测试）
- Create: `tests/test_resume_library_score_activity.py`（租户隔离测试）
- Modify: `app/schemas.py:3024`（`ResumeLibraryItem` 加字段）
- Modify: `app/services/resume_library_service.py`（imports + 派生 helper + populate）

**Interfaces:**
- Consumes: `ResumeScoreBatchItem.status` / `ResumeScoreBatch.status`（既有列，`OrganizationScoped`）、`ai_client` fixture（`tests/conftest.py:127`）、`_save_ready_resume`（`test_filter_mvp_contract.py:195`）、`_template_payload`（`test_score_service.py`）、`_register_and_login` / `_seed_ready_resume`（`test_resume_score_batch_tenant_isolation.py`）。
- Produces: `ResumeLibraryItem.score_task_state: Literal["none", "queued", "running"] = "none"`；`list_resume_library(...)` 每项返回该字段。Task 2 的前端类型依赖此字段名。

- [ ] **Step 1: 写失败的后端测试**

在 `tests/test_resume_library_api.py` 顶部 import 区追加：

```python
from sqlalchemy import select

from app.models import ResumeScoreBatchItem
from app.tenant_scope import bypass_organization_scope
```

（`select` 已在第 5 行 import，勿重复；若已在，只加后两个 import。）

把 `test_resume_library_returns_current_ai_summary_preview_and_score` 的字段全集断言（第 56-87 行 `assert set(item) == {...}`）加入 `"score_task_state"`，并在 `assert item["score_created_at"] == ...` 之后加一行：

```python
    assert item["score_task_state"] == "none"
```

在同一文件末尾追加三个状态测试：

```python
def test_resume_library_reports_queued_score_task_state(ai_client) -> None:
    _, resume_id = _save_ready_resume(
        ai_client,
        source_text="教育经历 清华大学 计算机 本科。工作经历 Acme Python Engineer。技能 Python SQL",
    )
    template = ai_client.post("/v1/score-templates", json=_template_payload())
    assert template.status_code == 200, template.text
    batch = ai_client.post(
        f"/v1/score-templates/{template.json()['template_id']}/score-all"
    )
    assert batch.status_code == 200, batch.text
    assert batch.json()["total_count"] == 1

    response = ai_client.get("/v1/resume-library")
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["resume_id"] == resume_id
    assert item["score_task_state"] == "queued"
    # 尚无完成的评分行，静态评分字段保持为空。
    assert item["score_total"] is None


def test_resume_library_score_task_state_becomes_running_then_none(ai_client) -> None:
    _, resume_id = _save_ready_resume(
        ai_client,
        source_text="教育经历 清华大学 计算机 本科。工作经历 Acme Python Engineer。技能 Python SQL",
    )
    template = ai_client.post("/v1/score-templates", json=_template_payload())
    assert template.status_code == 200, template.text
    batch = ai_client.post(
        f"/v1/score-templates/{template.json()['template_id']}/score-all"
    )
    assert batch.status_code == 200, batch.text
    batch_id = batch.json()["batch_id"]

    database = ai_client.app.state.database
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            item = session.scalar(
                select(ResumeScoreBatchItem).where(
                    ResumeScoreBatchItem.batch_id == batch_id
                )
            )
            assert item is not None
            item.status = "running"
            session.commit()

    running = ai_client.get("/v1/resume-library")
    assert running.status_code == 200, running.text
    row = running.json()["items"][0]
    assert row["resume_id"] == resume_id
    assert row["score_task_state"] == "running"

    with database.session_factory() as session:
        with bypass_organization_scope(session):
            item = session.scalar(
                select(ResumeScoreBatchItem).where(
                    ResumeScoreBatchItem.batch_id == batch_id
                )
            )
            assert item is not None
            item.status = "succeeded"
            session.commit()

    finished = ai_client.get("/v1/resume-library")
    assert finished.status_code == 200, finished.text
    assert finished.json()["items"][0]["score_task_state"] == "none"


def test_resume_library_score_task_state_none_without_active_batch(ai_client) -> None:
    _, resume_id = _save_ready_resume(
        ai_client,
        source_text="教育经历 清华大学 计算机 本科。工作经历 Acme Python Engineer。技能 Python SQL",
    )
    response = ai_client.get("/v1/resume-library")
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["resume_id"] == resume_id
    assert item["score_task_state"] == "none"
```

新建 `tests/test_resume_library_score_activity.py`（租户隔离，双工作区共用一库）：

```python
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import AppSettings
from app.main import create_app
from app.models import ResumeScoreBatchItem
from app.tenant_scope import bypass_organization_scope
from test_resume_score_batch_tenant_isolation import (
    _register_and_login,
    _seed_ready_resume,
)


def _settings(tmp_path: Path) -> AppSettings:
    data_dir = tmp_path / "data"
    return AppSettings(
        project_dir=tmp_path,
        data_dir=data_dir,
        upload_dir=data_dir / "uploads",
        database_url="sqlite://",
        allow_unauthenticated=False,
        session_secret="resume-library-score-activity-tenant-secret",
        transactional_email_provider="test",
        public_app_url="http://testserver",
        deepseek_api_key="resume-library-score-activity-test-key",
        deepseek_model="unit-test-model",
        min_text_chars_per_page=20,
    )


@pytest.fixture
def library_workspace_clients(tmp_path: Path) -> Iterator[tuple[TestClient, TestClient]]:
    """Two authenticated workspaces sharing one test database."""

    app = create_app(_settings(tmp_path))
    with TestClient(app):
        client_a = TestClient(app)
        client_b = TestClient(app)
        try:
            yield client_a, client_b
        finally:
            client_a.close()
            client_b.close()


def _template_payload(name: str) -> dict[str, object]:
    return {
        "name": name,
        "description": "Workspace-scoped library activity fixture.",
        "dimensions": [
            {
                "label": "Skills",
                "weight": 100,
                "guidance": "Use explicit resume facts only.",
            }
        ],
    }


def test_foreign_workspace_score_batch_never_leaks_into_library_activity(
    library_workspace_clients: tuple[TestClient, TestClient],
) -> None:
    client_a, client_b = library_workspace_clients
    organization_a = _register_and_login(
        client_a,
        organization_name="Library Activity Alpha",
        email="library-activity-alpha@example.test",
    )
    organization_b = _register_and_login(
        client_b,
        organization_name="Library Activity Beta",
        email="library-activity-beta@example.test",
    )

    database = client_a.app.state.database
    with database.session_factory() as session:
        resume_a_id, _ = _seed_ready_resume(
            session,
            organization_id=organization_a,
            label="library-alpha-ready",
        )
        resume_b_id, _ = _seed_ready_resume(
            session,
            organization_id=organization_b,
            label="library-beta-ready",
        )
        session.commit()

    template_b_id = client_b.post(
        "/v1/score-templates",
        json=_template_payload("Beta activity template"),
    )
    assert template_b_id.status_code == 200, template_b_id.text
    batch_b = client_b.post(
        f"/v1/score-templates/{template_b_id.json()['template_id']}/score-all"
    )
    assert batch_b.status_code == 200, batch_b.text
    batch_b_id = batch_b.json()["batch_id"]

    # 把 B 的 item 置为 running，让潜在泄漏最大化。
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            item = session.scalar(
                select(ResumeScoreBatchItem).where(
                    ResumeScoreBatchItem.batch_id == batch_b_id
                )
            )
            assert item is not None
            item.status = "running"
            session.commit()

    library_a = client_a.get("/v1/resume-library")
    assert library_a.status_code == 200, library_a.text
    a_items = library_a.json()["items"]
    assert {item["resume_id"] for item in a_items} == {resume_a_id}
    assert a_items[0]["score_task_state"] == "none"

    library_b = client_b.get("/v1/resume-library")
    assert library_b.status_code == 200, library_b.text
    b_by_resume = {
        item["resume_id"]: item["score_task_state"]
        for item in library_b.json()["items"]
    }
    assert b_by_resume[resume_b_id] == "running"
```

> 注：`parse_qs`/`urlsplit` 被 `_register_and_login` 内部用到，该 import 已由 `_register_and_login` 所属模块承担；本文件按上面的 import 列表写，若本地 ruff/flake8 报未用 import 再删即可（仓库未配置 Python linter，见 Global Constraints 测试环境说明）。

- [ ] **Step 2: 运行新测试确认失败**

Run: `python -m pytest -q tests/test_resume_library_api.py tests/test_resume_library_score_activity.py`
Expected: 4 个新断言失败——`test_resume_library_returns_current_ai_summary_preview_and_score` 因 `assert set(item) == {...}` 报 `key 'score_task_state'` 缺失；另外 3 个状态测试与租户隔离测试报 `KeyError: 'score_task_state'`（API 尚未返回该键）。

- [ ] **Step 3: schema 加字段**

在 `app/schemas.py` 的 `ResumeLibraryItem`（第 3021-3024 行）末尾追加：

```python
    score_total: float | None = None
    score_status: str | None = None
    score_template_name: str | None = None
    score_created_at: str | None = None
    # 派生字段，永不落库：当前工作区是否有活跃评分批次正在为这一行生成分数。
    # 供简历库在评分生成期间渲染"评分生成中"动画，无需等待完成的评分行。
    score_task_state: Literal["none", "queued", "running"] = "none"
```

（`Literal` 已在 `app/schemas.py:6` import。）

- [ ] **Step 4: service 派生 + populate**

`app/services/resume_library_service.py`：

把 import 改为：

```python
from app.models import (
    Resume,
    ResumeEducation,
    ResumeScore,
    ResumeScoreBatch,
    ResumeScoreBatchItem,
    ResumeSummary,
)
```

在 `_CURRENT_SCORE_STATUSES` 定义（第 34 行）下方加：

```python
# A row's score is "in progress" while an active batch item owns it.  Both
# the batch and the item must be non-terminal for the derivation to fire.
_IN_PROGRESS_SCORE_STATUSES = ("queued", "running")


def _active_score_task_states(
    session: Session,
    resume_ids: list[str],
) -> dict[str, str]:
    """Map resume_id -> 'queued' | 'running' from active batch items.

    Runs under the session's tenant scope (``with_loader_criteria``), so a
    foreign workspace's batch can never surface here.  When a resume appears
    in several active batches, ``running`` wins over ``queued``.
    """

    if not resume_ids:
        return {}
    rows = session.execute(
        select(ResumeScoreBatchItem.resume_id, ResumeScoreBatchItem.status)
        .join(
            ResumeScoreBatch,
            ResumeScoreBatch.id == ResumeScoreBatchItem.batch_id,
        )
        .where(
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

在 `list_resume_library` 里 `wait_estimates = ...` 之后、`items: list[ResumeLibraryItem] = []` 之前加：

```python
    score_task_states = _active_score_task_states(
        session,
        resume_ids=[resume.id for resume in resumes],
    )
```

在 `ResumeLibraryItem(...)` 构造末尾（`score_created_at=...` 之后）加：

```python
                score_created_at=_isoformat(score.created_at) if score else None,
                score_task_state=score_task_states.get(resume.id, "none"),
```

- [ ] **Step 5: 运行新测试确认通过**

Run: `python -m pytest -q tests/test_resume_library_api.py tests/test_resume_library_score_activity.py`
Expected: 全部通过（原有测试 + 新增 4 个）。

- [ ] **Step 6: 全量后端回归**

Run: `python -m compileall -q app && python -m pytest -q`
Expected: 编译通过、全部测试绿。若出现与 `ResumeLibraryItem` 构造有关的既有调用失败（例如别的测试显式构造该 schema），按报错补齐 `score_task_state`（默认值 `"none"` 通常已覆盖）。

- [ ] **Step 7: 提交**

```bash
git add app/schemas.py app/services/resume_library_service.py tests/test_resume_library_api.py tests/test_resume_library_score_activity.py
git commit -m "feat: derive score_task_state in resume library for score activity animation"
```

---

### Task 2: 前端评分格动画（类型 + helper + 轮询 + 评分格 + CSS）

**Files:**
- Modify: `web/src/types.ts:1493-1496`（`ResumeLibraryItem`）
- Modify: `web/src/backoffice/utils/ai-extraction.ts`（加 `scoreTaskIsInProgress`）
- Modify: `web/src/features/library/ResumeLibraryPage.tsx:427-441`（轮询条件）+ `750-777`（评分格分支）
- Modify: `web/src/features/library/resume-library.css`（脉动圆点 + reduced-motion）

**Interfaces:**
- Consumes: Task 1 的 `score_task_state: "none" | "queued" | "running"`。
- Produces: 评分格渲染 `.library-score-activity`（`role="status"`）+ `.library-score-activity-dot`（`aria-hidden`）；e2e（Task 3）定位这两个类名。

- [ ] **Step 1: `types.ts` 加字段**

在 `ResumeLibraryItem`（第 1496 行 `score_created_at` 之后）加：

```ts
  score_total: number | null;
  score_status: string | null;
  score_template_name: string | null;
  score_created_at: string | null;
  score_task_state: "none" | "queued" | "running";
```

- [ ] **Step 2: `ai-extraction.ts` 加 helper**

在 `web/src/backoffice/utils/ai-extraction.ts` 末尾加：

```ts
/** The automatic score for this library row is still queued or running. */
export function scoreTaskIsInProgress(
  state: "none" | "queued" | "running" | undefined,
): boolean {
  return state === "queued" || state === "running";
}
```

- [ ] **Step 3: 轮询条件扩展**

`web/src/features/library/ResumeLibraryPage.tsx` 第 11-15 行的 import 加 `scoreTaskIsInProgress`：

```ts
import {
  AI_STATUS_POLL_INTERVAL_MS,
  aiExtractionIsInProgress,
  aiSummaryIsInProgress,
  scoreTaskIsInProgress,
} from "../../backoffice/utils/ai-extraction";
```

第 427-441 行的 `.some()` 条件追加评分任务状态：

```ts
    if (
      !library?.items.some((item) =>
        aiExtractionIsInProgress(item.ai_extraction_status) ||
        aiExtractionIsInProgress(item.candidate_name_extraction_status) ||
        aiSummaryIsInProgress(item.ai_summary_status) ||
        scoreTaskIsInProgress(item.score_task_state),
      )
    ) {
      return undefined;
    }
```

请求数不变：整页仍每 tick 只发 1 个 `loadLibrary()`。

- [ ] **Step 4: 评分格分支**

把第 759 行 `) : item.score_total !== null ? (` 之前插入动画分支（位于 `sourceTextIssue` / `supersededReparse` 两个质量前置分支之后、分数数字之前）：

```tsx
                        ) : scoreTaskIsInProgress(item.score_task_state) ? (
                          <div
                            className="library-score-activity"
                            role="status"
                            aria-label="正在生成 AI 评分"
                          >
                            <span
                              className="library-score-activity-dot"
                              aria-hidden="true"
                            />
                            <span className="library-score-activity-copy">
                              评分生成中…
                            </span>
                          </div>
                        ) : item.score_total !== null ? (
```

重新评分场景下此分支先于分数分支执行，运行期间动画天然盖住旧分。

- [ ] **Step 5: CSS 动画 + reduced-motion**

`web/src/features/library/resume-library.css` 在 `@keyframes library-ai-orb-shine`（第 318-334 行）之后、`prefers-reduced-motion` 块（第 336 行）之前加：

```css
.backoffice-ui-root .resume-library-page .library-score-activity {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  color: #4338ca;
  font-size: 0.6875rem;
  font-weight: 600;
  line-height: 1.2;
  white-space: nowrap;
}

.backoffice-ui-root .resume-library-page .library-score-activity-dot {
  width: 0.5rem;
  height: 0.5rem;
  flex: none;
  background: linear-gradient(135deg, #2563eb 0%, #7c3aed 48%, #d946ef 100%);
  background-size: 180% 180%;
  border-radius: 9999px;
  box-shadow: 0 0 6px rgb(79 70 229 / 0.45);
  animation:
    library-ai-orb-gradient 2.4s ease-in-out infinite,
    library-score-activity-pulse 1.4s ease-in-out infinite;
}

@keyframes library-score-activity-pulse {
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
```

在既有 `@media (prefers-reduced-motion: reduce)` 块（第 336-341 行）内、关闭 orb 动画的选择器之后追加：

```css
@media (prefers-reduced-motion: reduce) {
  .backoffice-ui-root .resume-library-page .library-ai-activity.is-running .library-ai-orb,
  .backoffice-ui-root .resume-library-page .library-ai-activity.is-running .library-ai-orb::after {
    animation: none;
  }

  .backoffice-ui-root .resume-library-page .library-score-activity-dot {
    animation: none;
  }
}
```

- [ ] **Step 6: 前端构建（类型检查）**

Run: `cd web && npm run build`
Expected: `tsc -b` 与 `vite build` 均成功。若类型报错，多为 mock/其他文件显式构造 `ResumeLibraryItem` 缺 `score_task_state`，补 `"none"`。

- [ ] **Step 7: 提交**

```bash
git add web/src/types.ts web/src/backoffice/utils/ai-extraction.ts web/src/features/library/ResumeLibraryPage.tsx web/src/features/library/resume-library.css
git commit -m "feat: animate resume library score cell while a batch score is generating"
```

---

### Task 3: 前端 e2e（进行中动画 → 完成后分数）

**Files:**
- Create: `web/e2e/resume-library-score-activity.spec.ts`

**Interfaces:**
- Consumes: `registerAndVerify` / `seedWorkspaceFixture`（`web/e2e/helpers.ts`）；Task 2 的 `.library-score-activity`、`.library-score strong` 渲染；后端 `/v1/resume-library` 响应的 `score_task_state`。
- Produces: 一条可独立运行的 Playwright 用例。

- [ ] **Step 1: 写 e2e**

新建 `web/e2e/resume-library-score-activity.spec.ts`：

```ts
import { expect, test } from "@playwright/test";

import { registerAndVerify, seedWorkspaceFixture } from "./helpers";

test("评分生成中显示动画，完成后变为分数", async ({ page }) => {
  await registerAndVerify(page, "resume-library-score-activity");
  await seedWorkspaceFixture(page);

  let libraryPolls = 0;
  await page.route("**/v1/resume-library**", async (route) => {
    const response = await route.fetch();
    const payload = (await response.json()) as {
      items?: Array<Record<string, unknown>>;
    };
    libraryPolls += 1;
    const scoreStillGenerating = libraryPolls <= 2;
    await route.fulfill({
      response,
      json: {
        ...payload,
        items: (payload.items ?? []).map((item) => ({
          ...item,
          score_task_state: scoreStillGenerating ? "running" : "none",
          score_total: scoreStillGenerating ? null : 88,
          score_status: scoreStillGenerating ? null : "succeeded",
          score_template_name: scoreStillGenerating ? null : "E2E 评分规则",
          score_created_at: scoreStillGenerating
            ? null
            : "2026-08-10T00:00:00+00:00",
        })),
      },
    });
  });

  await page.getByRole("button", { name: "简历库", exact: true }).click();

  const activity = page.locator(".library-score-activity");
  await expect(activity.first()).toBeVisible();
  await expect(
    page.getByText("评分生成中…", { exact: true }).first(),
  ).toBeVisible();
  const dot = activity.first().locator(".library-score-activity-dot");
  await expect(dot).toBeVisible();
  await expect(dot).toHaveAttribute("aria-hidden", "true");
  await expect(activity.first()).toHaveAttribute("role", "status");

  // 前 2 次轮询返回 running，之后返回 none，动画应消失、回到分数数字。
  await expect(activity.first()).not.toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".library-score strong").first()).toHaveText("88.0");
});
```

- [ ] **Step 2: 独占串行跑 e2e**

Run: `cd web && npm run test:e2e -- resume-library-score-activity.spec.ts`
Expected: 通过。**必须单独串行运行**——不要与 pytest 或 vite dev 并行（撞 8012/5176 端口会导致 vite 崩溃、e2e 无产物 exit 1）。

- [ ] **Step 3: 提交**

```bash
git add web/e2e/resume-library-score-activity.spec.ts
git commit -m "test(e2e): resume library score activity animation then score"
```

---

### Task 4: 完整验证与收尾

- [ ] **Step 1: 全量回归（串行）**

Run: `python -m pytest -q && cd web && npm run build`
Expected: 全部绿、构建通过。

- [ ] **Step 2: 推送分支并开 PR**

```bash
git push -u origin feat/resume-library-score-activity
gh pr create --fill
```

- [ ] **Step 3: 等待 CI 全绿后合并（含 `--delete-branch` 时留意 settings-center 占位问题，沿用既有合并习惯）**

Run: `gh pr checks <num> --watch && gh pr merge <num> --squash`
Expected: Backend tests / Web build / PostgreSQL mailbox race / UTF-8 全绿后 squash 合并。

---

## Self-Review

**1. Spec 覆盖核对：**
- 派生字段（§1 后端）→ Task 1 Step 3-4。
- 租户隔离（§1 第三条）→ Task 1 `_active_score_task_states` 靠 `with_loader_criteria`，无手写 org 谓词；Task 1 租户测试。
- 评分格动画 + 完成回落（§2）→ Task 2 Step 4 + Task 3。
- 重新评分盖旧分（§2 第 3 条）→ Task 2 Step 4 分支先于分数分支。
- 轮询条件 + 请求数不变 + 只读（§2 轮询条）→ Task 2 Step 3，未新增任何请求。
- reduced-motion（§2 动画条）→ Task 2 Step 5。
- aria（§2）→ Task 2 Step 4 `role="status"` / `aria-label` / `aria-hidden`，Task 3 断言。
- 无活跃批次向后兼容（§3）→ Task 1 第三个测试 + schema 默认 `"none"`。
- 测试（§4 后端 + e2e）→ Task 1 / Task 3。
- 非目标（YAGNI）→ 无 ETA、未动汇总条/Workspace/匹配面板、无数值滚动动画。✔

**2. Placeholder 扫描：** 全部步骤含具体代码与运行命令，无 "TBD"/"TODO"/"实现细节后续补"。✔

**3. 类型一致性：** 后端 `score_task_state`（schema 默认 `"none"`）→ 前端 `"none" | "queued" | "running"`（Task 2 Step 1）→ helper `scoreTaskIsInProgress`（Step 2）→ e2e mock 键名 `score_task_state` 与 CSS 类名 `.library-score-activity` / `.library-score-activity-dot` 全程一致。Task 1 断言 `item["score_task_state"]`、Task 3 断言 `role="status"` 与 `.library-score strong` 均与实现匹配。✔
