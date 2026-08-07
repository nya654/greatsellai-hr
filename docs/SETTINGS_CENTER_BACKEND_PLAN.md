# Settings Center Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add backend storage + endpoints for workspace AI-import settings and per-user filter display-field preferences, and wire resume import/extraction so auto AI summary + scoring run when enabled.

**Architecture:** Two new org/user-scoped tables with GET/PUT endpoints (following the existing `CandidateDataRetentionPolicy` singleton + `require_organization_admin` pattern). Import hooks gate AI-extraction enqueueing by source (`manual_upload` / `mailbox_attachment`); the AI-extraction completion hook (`_save_completed_ai_facts`) enqueues summary + a single-resume score batch when enabled. No inline model calls — everything reuses existing worker queues.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy 2, Alembic, Pytest.

## Global Constraints

- **Organization isolation is mandatory.** Every new row/query must carry `organization_id` and go through the session org-scoping (`OrganizationScoped` mixin + `set_organization_context`). Never query by resource ID alone.
- **Defaults (from design):** `auto_summary_enabled=true`, `auto_score_enabled=true`, `trigger_manual_upload=true`, `trigger_mailbox_import=true`, `default_score_template_id=null`.
- **Auto-score requires a default template.** A PUT that enables `auto_score_enabled` without `default_score_template_id` must fail with `422 default_score_template_required`; a provided template must belong to the caller's org.
- **No inline AI model calls in workers.** Scoring for the auto-chain must go through the batch queue (extended with a `resume_id` scope), never `run_resume_score` inline.
- **Migration safety:** new tables are additive (no data backfill, no destructive change). Each migration gets a downgrade.
- **Source values:** `Resume.ingestion_source_type` is `"manual_upload"` (default) or `"mailbox_attachment"` (set by mailbox import).
- **Run full backend suite + safe-upgrade check before finishing.** Commit after each green task.

---

### Task 1: `WorkspaceAiImportSettings` model

**Files:**
- Modify: `app/models.py` (add class near `CandidateDataRetentionPolicy`, ~line 1379)
- Create: `migrations/versions/20260806_0059_workspace_ai_import_settings.py`
- Test: `tests/test_settings_ai_import_api.py` (created in Task 3; here only the migration test is added if the repo convention demands it — see below)

**Interfaces:**
- Consumes: `OrganizationScoped`, `Base`, `new_id`, `utcnow` (all defined in `app/models.py`), `ScoreTemplate`, `UserAccount` FKs.
- Produces: `WorkspaceAiImportSettings` ORM class with fields `id`, `organization_id`, `auto_summary_enabled: bool`, `auto_score_enabled: bool`, `default_score_template_id: str|None`, `trigger_manual_upload: bool`, `trigger_mailbox_import: bool`, `updated_by_user_id: str|None`, `created_at`, `updated_at`. Unique per `organization_id`.

- [ ] **Step 1: Write the failing migration test**

Create `tests/test_settings_ai_import_migration.py` (the repo has a `test_*_migration.py` convention, e.g. `test_document_ocr_metrics_migration.py`). Read that file first and mirror its fixture/assert style. A representative check:

```python
from __future__ import annotations

from sqlalchemy import inspect


def test_workspace_ai_import_settings_table_exists(client):
    inspector = inspect(client.app.state.database.engine)
    assert "workspace_ai_import_settings" in inspector.get_table_names()
    columns = {c["name"] for c in inspector.get_columns("workspace_ai_import_settings")}
    assert {
        "id",
        "organization_id",
        "auto_summary_enabled",
        "auto_score_enabled",
        "default_score_template_id",
        "trigger_manual_upload",
        "trigger_mailbox_import",
        "updated_by_user_id",
        "created_at",
        "updated_at",
    } <= columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_settings_ai_import_migration.py -v`
Expected: FAIL — table does not exist (migration not yet written).

- [ ] **Step 3: Write the model + migration**

In `app/models.py`, add (mirror the `CandidateDataRetentionPolicy` class):

```python
class WorkspaceAiImportSettings(OrganizationScoped, Base):
    """One AI import-processing preference row per workspace.

    Controls whether imported resumes auto-run AI summary / scoring and for
    which ingestion sources. Rows are created lazily with all-auto defaults,
    matching the "默认全开" product decision.
    """

    __tablename__ = "workspace_ai_import_settings"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            name="uq_workspace_ai_import_settings_organization",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    auto_summary_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_score_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    default_score_template_id: Mapped[str | None] = mapped_column(
        ForeignKey("score_templates.id"),
        nullable=True,
    )
    trigger_manual_upload: Mapped[bool] = mapped_column(Boolean, default=True)
    trigger_mailbox_import: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_accounts.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
```

Create the migration `migrations/versions/20260806_0059_workspace_ai_import_settings.py` (check `migrations/env.py` for the exact `sa` import; `revision="20260806_0059"`, `down_revision="20260806_0058"`):

```python
"""Add per-workspace AI import processing settings.

Revision ID: 20260806_0059
Revises: 20260806_0058
Create Date: 2026-08-06 16:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260806_0059"
down_revision: Union[str, Sequence[str], None] = "20260806_0058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workspace_ai_import_settings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("auto_summary_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("auto_score_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_score_template_id", sa.String(length=36), nullable=True),
        sa.Column("trigger_manual_upload", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("trigger_mailbox_import", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["default_score_template_id"], ["score_templates.id"]),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["user_accounts.id"]),
        sa.UniqueConstraint("organization_id", name="uq_workspace_ai_import_settings_organization"),
    )
    op.create_index(
        "ix_workspace_ai_import_settings_organization_id",
        "workspace_ai_import_settings",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_ai_import_settings_organization_id",
        table_name="workspace_ai_import_settings",
    )
    op.drop_table("workspace_ai_import_settings")
```

- [ ] **Step 4: Apply migration + run test to verify it passes**

Run: `python -m pytest tests/test_settings_ai_import_migration.py -v` (the `client` fixture creates the schema from migrations — mirror whatever the other migration tests do).
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/models.py migrations/versions/20260806_0059_workspace_ai_import_settings.py tests/test_settings_ai_import_migration.py
git commit -m "feat: add workspace_ai_import_settings model + migration"
```

---

### Task 2: `UserFilterDisplayPreference` model

**Files:**
- Modify: `app/models.py`
- Create: `migrations/versions/20260806_0060_user_filter_display_preferences.py`
- Test: `tests/test_settings_display_fields_migration.py`

**Interfaces:**
- Consumes: `OrganizationScoped`, `Base`, `new_id`, `utcnow`.
- Produces: `UserFilterDisplayPreference` with `id`, `user_id` (unique), `organization_id`, `display_field_keys: list[str]`, `updated_at`.

- [ ] **Step 1: Write the failing migration test**

```python
def test_user_filter_display_preferences_table_exists(client):
    inspector = inspect(client.app.state.database.engine)
    assert "user_filter_display_preferences" in inspector.get_table_names()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_settings_display_fields_migration.py -v`
Expected: FAIL.

- [ ] **Step 3: Write the model + migration**

```python
class UserFilterDisplayPreference(OrganizationScoped, Base):
    """Per-user filter result column preference.

    A row exists only after the user has saved an explicit selection. Absence
    means "fall back to auto-derived columns" in the results pane.
    """

    __tablename__ = "user_filter_display_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_filter_display_preferences_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id"),
        unique=True,
    )
    display_field_keys: Mapped[list[str]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
```

Check whether `JSON` is already imported in `app/models.py`; if not, add `from sqlalchemy import JSON` to its imports.

Migration `20260806_0060` (`down_revision="20260806_0059"`), using `sa.JSON()` and mirroring Task 1's table shape (`organization_id` FK, `user_id` FK + unique, `updated_at`).

- [ ] **Step 4: Apply migration + run test**

Run: `python -m pytest tests/test_settings_display_fields_migration.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/models.py migrations/versions/20260806_0060_user_filter_display_preferences.py tests/test_settings_display_fields_migration.py
git commit -m "feat: add user_filter_display_preferences model + migration"
```

---

### Task 3: AI import settings service + GET/PUT endpoints

**Files:**
- Create: `app/services/workspace_ai_import_settings_service.py`
- Modify: `app/schemas.py` (add `AiImportSettingsUpdate`, `AiImportSettingsResponse` near other settings schemas, ~line 1479)
- Modify: `app/main.py` (add two endpoints; place near the candidate-data retention endpoints)
- Create: `tests/test_settings_ai_import_api.py`

**Interfaces:**
- Consumes: `WorkspaceAiImportSettings` (Task 1), `ScoreTemplate`, `organization_context_id`, `_commit_or_raise`, `require_organization_admin`, `ApiModel`.
- Produces:
  - `ai_import_settings_response(session) -> AiImportSettingsResponse` — lazily creates the default row on read.
  - `update_ai_import_settings(session, *, request: AiImportSettingsUpdate, actor_user_id: str) -> AiImportSettingsResponse` — validates template, persists, returns response.
  - HTTP `GET /v1/settings/ai-import`, `PUT /v1/settings/ai-import` (both `require_organization_admin`).

- [ ] **Step 1: Write the failing API tests**

`tests/test_settings_ai_import_api.py` — mirror the `_register_and_login` helper from `tests/test_candidate_data_lifecycle.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from test_candidate_data_lifecycle import _register_and_login


def _admin_client(client: TestClient) -> TestClient:
    # register + login a workspace admin, set client.auth cookies, return client
    _register_and_login(
        client,
        organization_name="Settings Ai Import Org",
        email="settings-ai-admin@example.com",
    )
    return client


def test_ai_import_settings_defaults(client):
    c = _admin_client(client)
    response = c.get("/v1/settings/ai-import")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["auto_summary_enabled"] is True
    assert body["auto_score_enabled"] is True
    assert body["trigger_manual_upload"] is True
    assert body["trigger_mailbox_import"] is True
    assert body["default_score_template_id"] is None


def test_ai_import_settings_require_admin(client):
    # a non-admin authenticated member must get 403 on GET
    ...


def test_ai_import_settings_toggle_and_persist(client):
    c = _admin_client(client)
    response = c.put(
        "/v1/settings/ai-import",
        json={
            "auto_summary_enabled": False,
            "auto_score_enabled": False,
            "default_score_template_id": None,
            "trigger_manual_upload": True,
            "trigger_mailbox_import": False,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["auto_summary_enabled"] is False
    assert body["trigger_mailbox_import"] is False
    # persisted across reads
    again = c.get("/v1/settings/ai-import")
    assert again.json()["auto_summary_enabled"] is False


def test_ai_import_settings_auto_score_requires_template(client):
    c = _admin_client(client)
    response = c.put(
        "/v1/settings/ai-import",
        json={
            "auto_summary_enabled": True,
            "auto_score_enabled": True,
            "default_score_template_id": None,
            "trigger_manual_upload": True,
            "trigger_mailbox_import": True,
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "default_score_template_required"


def test_ai_import_settings_org_isolation(client):
    # two workspaces: updating one must not affect the other
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_settings_ai_import_api.py -v`
Expected: FAIL — routes return 404/`testclient` error (endpoints not defined).

- [ ] **Step 3: Write the service**

```python
from __future__ import annotations

from sqlalchemy import select

from app.database import Session
from app.models import (
    ScoreTemplate,
    WorkspaceAiImportSettings,
    utcnow,
)
from app.schemas import AiImportSettingsUpdate, AiImportSettingsResponse
from app.tenant_scope import organization_context_id


def _default_row(session: Session) -> WorkspaceAiImportSettings:
    organization_id = organization_context_id(session)
    row = session.scalar(
        select(WorkspaceAiImportSettings)
        .where(WorkspaceAiImportSettings.organization_id == organization_id)
    )
    if row is not None:
        return row
    row = WorkspaceAiImportSettings(organization_id=organization_id)
    session.add(row)
    session.flush()
    return row


def ai_import_settings_response(session: Session) -> AiImportSettingsResponse:
    row = _default_row(session)
    return AiImportSettingsResponse(
        auto_summary_enabled=row.auto_summary_enabled,
        auto_score_enabled=row.auto_score_enabled,
        default_score_template_id=row.default_score_template_id,
        trigger_manual_upload=row.trigger_manual_upload,
        trigger_mailbox_import=row.trigger_mailbox_import,
    )


def update_ai_import_settings(
    session: Session,
    *,
    request: AiImportSettingsUpdate,
    actor_user_id: str,
) -> AiImportSettingsResponse:
    organization_id = organization_context_id(session)
    if request.default_score_template_id is not None:
        template = session.get(ScoreTemplate, request.default_score_template_id)
        if template is None or template.organization_id != organization_id:
            raise ValueError("default_score_template_not_found")
    if request.auto_score_enabled and not request.default_score_template_id:
        raise ValueError("default_score_template_required")

    row = _default_row(session)
    row.auto_summary_enabled = request.auto_summary_enabled
    row.auto_score_enabled = request.auto_score_enabled
    row.default_score_template_id = request.default_score_template_id
    row.trigger_manual_upload = request.trigger_manual_upload
    row.trigger_mailbox_import = request.trigger_mailbox_import
    row.updated_by_user_id = actor_user_id
    session.flush()
    return ai_import_settings_response(session)
```

Check the real import path of `organization_context_id` (`app/tenant_scope.py` — verified) and import it from there.

- [ ] **Step 4: Write schemas**

In `app/schemas.py`:

```python
class AiImportSettingsUpdate(ApiModel):
    auto_summary_enabled: bool
    auto_score_enabled: bool
    default_score_template_id: str | None = None
    trigger_manual_upload: bool
    trigger_mailbox_import: bool


class AiImportSettingsResponse(ApiModel):
    auto_summary_enabled: bool
    auto_score_enabled: bool
    default_score_template_id: str | None
    trigger_manual_upload: bool
    trigger_mailbox_import: bool
```

- [ ] **Step 5: Write the endpoints**

In `app/main.py`, near the candidate-data retention endpoints (import the service + schemas at the top):

```python
@app.get(
    "/v1/settings/ai-import",
    response_model=AiImportSettingsResponse,
    dependencies=[Depends(require_organization_admin)],
)
def get_ai_import_settings(session: Session = Depends(get_session)) -> AiImportSettingsResponse:
    response = ai_import_settings_response(session)
    _commit_or_raise(session)
    return response


@app.put(
    "/v1/settings/ai-import",
    response_model=AiImportSettingsResponse,
    dependencies=[Depends(require_organization_admin)],
)
def put_ai_import_settings(
    payload: AiImportSettingsUpdate,
    principal: AuthPrincipal = Depends(require_organization_admin),
    session: Session = Depends(get_session),
) -> AiImportSettingsResponse:
    try:
        response = update_ai_import_settings(
            session,
            request=payload,
            actor_user_id=principal.user.id,
        )
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    _commit_or_raise(session)
    return response
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_settings_ai_import_api.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/services/workspace_ai_import_settings_service.py app/schemas.py app/main.py tests/test_settings_ai_import_api.py
git commit -m "feat: add workspace AI import settings GET/PUT endpoints"
```

---

### Task 4: Display-field preferences service + GET/PUT endpoints

**Files:**
- Create: `app/services/user_filter_display_preferences_service.py`
- Modify: `app/schemas.py`, `app/main.py`
- Create: `tests/test_settings_display_fields_api.py`

**Interfaces:**
- Consumes: `UserFilterDisplayPreference` (Task 2), `require_authenticated_member`, `ApiModel`.
- Produces:
  - `display_field_preferences_response(session, *, user_id) -> DisplayFieldPreferencesResponse`
  - `update_display_field_preferences(session, *, user_id, field_keys: list[str]) -> DisplayFieldPreferencesResponse`
  - `VALID_DISPLAY_FIELD_KEYS: frozenset[str]` — copy the 22 keys verbatim from `web/src/types.ts` `CandidateSearchDisplayFieldKey`.
  - HTTP `GET /v1/settings/display-fields`, `PUT /v1/settings/display-fields` (any authenticated member).

- [ ] **Step 1: Write the failing API tests**

```python
def test_display_fields_defaults_empty(client):
    c = _register_and_login(client, ...)  # any member
    response = c.get("/v1/settings/display-fields")
    assert response.status_code == 200
    assert response.json() == {"display_field_keys": []}


def test_display_fields_save_and_read(client):
    c = ...
    response = c.put(
        "/v1/settings/display-fields",
        json={"display_field_keys": ["school", "major", "skills"]},
    )
    assert response.status_code == 200
    assert response.json()["display_field_keys"] == ["school", "major", "skills"]
    assert c.get("/v1/settings/display-fields").json()["display_field_keys"] == ["school", "major", "skills"]


def test_display_fields_reject_unknown_key(client):
    response = c.put("/v1/settings/display-fields", json={"display_field_keys": ["not_a_real_key"]})
    assert response.status_code == 422


def test_display_fields_per_user_isolation(client):
    # user A's selection must not appear for user B in the same workspace
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_settings_display_fields_api.py -v`
Expected: FAIL (routes undefined).

- [ ] **Step 3: Write the service**

```python
from __future__ import annotations

from sqlalchemy import select

from app.database import Session
from app.models import UserFilterDisplayPreference, utcnow
from app.schemas import DisplayFieldPreferencesResponse

VALID_DISPLAY_FIELD_KEYS = frozenset({
    "institution_classifications",
    "highest_degree",
    "education_degree",
    "graduation",
    "employment_months",
    "employment_or_internship_months",
    "gender",
    "age",
    "school",
    "major",
    "academic_performance",
    "experience_type",
    "experience_name",
    "organization",
    "title",
    "experience_award",
    "skills",
    "language",
    "scholarship",
    "competition",
    "leadership",
    "keywords",
})


def _row_for_user(session: Session, *, user_id: str, organization_id: str) -> UserFilterDisplayPreference:
    row = session.scalar(
        select(UserFilterDisplayPreference).where(
            UserFilterDisplayPreference.user_id == user_id,
            UserFilterDisplayPreference.organization_id == organization_id,
        )
    )
    if row is not None:
        return row
    row = UserFilterDisplayPreference(
        user_id=user_id,
        organization_id=organization_id,
        display_field_keys=[],
    )
    session.add(row)
    return row


def display_field_preferences_response(session: Session, *, user_id: str, organization_id: str) -> DisplayFieldPreferencesResponse:
    row = _row_for_user(session, user_id=user_id, organization_id=organization_id)
    return DisplayFieldPreferencesResponse(display_field_keys=list(row.display_field_keys or []))


def update_display_field_preferences(
    session: Session,
    *,
    user_id: str,
    organization_id: str,
    field_keys: list[str],
) -> DisplayFieldPreferencesResponse:
    unknown = [key for key in field_keys if key not in VALID_DISPLAY_FIELD_KEYS]
    if unknown:
        raise ValueError("unknown_display_field_key")
    deduped = list(dict.fromkeys(field_keys))
    row = _row_for_user(session, user_id=user_id, organization_id=organization_id)
    row.display_field_keys = deduped
    session.flush()
    return DisplayFieldPreferencesResponse(display_field_keys=deduped)
```

- [ ] **Step 4: Write schemas**

```python
class DisplayFieldPreferencesUpdate(ApiModel):
    display_field_keys: list[str]


class DisplayFieldPreferencesResponse(ApiModel):
    display_field_keys: list[str]
```

- [ ] **Step 5: Write the endpoints**

Use `require_authenticated_member` (defined at `app/main.py:2100`) so any signed-in member can read/write their own preference:

```python
@app.get(
    "/v1/settings/display-fields",
    response_model=DisplayFieldPreferencesResponse,
)
def get_display_field_preferences(
    principal: AuthPrincipal = Depends(require_authenticated_member),
    session: Session = Depends(get_session),
) -> DisplayFieldPreferencesResponse:
    response = display_field_preferences_response(
        session,
        user_id=principal.user.id,
        organization_id=principal.organization_id,
    )
    _commit_or_raise(session)
    return response


@app.put(
    "/v1/settings/display-fields",
    response_model=DisplayFieldPreferencesResponse,
)
def put_display_field_preferences(
    payload: DisplayFieldPreferencesUpdate,
    principal: AuthPrincipal = Depends(require_authenticated_member),
    session: Session = Depends(get_session),
) -> DisplayFieldPreferencesResponse:
    try:
        response = update_display_field_preferences(
            session,
            user_id=principal.user.id,
            organization_id=principal.organization_id,
            field_keys=payload.display_field_keys,
        )
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    _commit_or_raise(session)
    return response
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_settings_display_fields_api.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/services/user_filter_display_preferences_service.py app/schemas.py app/main.py tests/test_settings_display_fields_api.py
git commit -m "feat: add per-user filter display-field preferences endpoints"
```

---

### Task 5: Extend `enqueue_resume_score_batch` with a `resume_id` scope

**Files:**
- Modify: `app/services/resume_score_batch_service.py` (`enqueue_resume_score_batch`, ~line 220)
- Modify: `app/schemas.py` if a new request shape is needed (not required — use keyword args)
- Create: `tests/test_resume_score_batch_single.py`

**Interfaces:**
- Consumes: existing `_require_scoreable_template`, `_route_pin_for_new_score_batch`, `_existing_active_batch`.
- Produces: `enqueue_resume_score_batch(session, *, template_id: str, settings: AppSettings, resume_id: str | None = None)` — when `resume_id` is given, the batch contains exactly that one resume item instead of all scoreable resumes.

- [ ] **Step 1: Write the failing test**

Mirror an existing batch test (read `tests/test_resume_score_batch_*.py` / `test_ai_gateway_*` for fixtures that create a scoreable resume + template). Representative shape:

```python
def test_enqueue_score_batch_scoped_to_single_resume(client):
    # create two scoreable resumes + one template
    # call service.enqueue_resume_score_batch(session, template_id=t.id, settings=settings, resume_id=r1.id)
    # assert batch has 1 item and item.resume_id == r1.id
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — `enqueue_resume_score_batch` has no `resume_id` parameter.

- [ ] **Step 3: Implement**

In `enqueue_resume_score_batch`, after building the snapshot query, add an optional WHERE when `resume_id is not None`:

```python
def enqueue_resume_score_batch(
    session: Session,
    *,
    template_id: str,
    settings: AppSettings,
    resume_id: str | None = None,
) -> ResumeScoreBatchResponse:
    ...
    query = select(
        Resume.id,
        ResumeFactSnapshot.id,
        ResumeFactSnapshot.facts_version,
        Resume.quality_flags,
    ).join(
        ResumeFactSnapshot,
        and_(
            ResumeFactSnapshot.resume_id == Resume.id,
            ResumeFactSnapshot.facts_version == Resume.facts_version,
        ),
    ).where(
        Resume.organization_id == organization_id,
        Resume.is_active.is_(True),
        # ... existing eligibility filters
    )
    if resume_id is not None:
        query = query.where(Resume.id == resume_id)
    snapshot_rows = session.execute(query).all()
    if not snapshot_rows:
        raise ScoreServiceError("no_scoreable_resumes")
    # ... create batch + items as today, but only for the one row
```

Read the full existing function and thread `resume_id` through both the snapshot query and the item-creation loop so the scope truly limits the batch. The empty case (`resume_id` that isn't scoreable) must raise `ScoreServiceError("no_scoreable_resumes")` like today.

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/resume_score_batch_service.py tests/test_resume_score_batch_single.py
git commit -m "feat: scope score batch enqueue to a single resume"
```

---

### Task 6: Manual-upload import hook (auto enqueue AI extraction)

**Files:**
- Modify: `app/main.py` (`_persist_new_candidate_resume` and `_persist_existing_candidate_resume`, ~line 655-800)
- Modify: `app/services/workspace_ai_import_settings_service.py` (add a gate helper)
- Create: `tests/test_settings_ai_import_upload_hook.py`

**Interfaces:**
- Consumes: `ai_import_settings_response` (Task 3), `enqueue_uploaded_resume_ai_extraction` (defined `app/services/ai_extraction_job_service.py:156`).
- Produces:
  - `should_auto_process_source(session, *, source: str) -> bool` — True when the workspace settings have any automation on AND that source's trigger is on. `source` is `"manual_upload"` or `"mailbox_attachment"`.
  - Manual upload path enqueues AI extraction after `save_pdf_resume` when the gate passes.

- [ ] **Step 1: Write the failing test**

```python
def test_manual_upload_auto_enqueues_ai_extraction(client):
    c = _register_and_login(client, ...)
    # PUT /v1/settings/ai-import → keep defaults (all on)
    pdf = make_pdf_with_text(b"resume text here")
    response = c.post(
        "/v1/resumes/upload",
        files={"file": ("resume.pdf", pdf, "application/pdf")},
    )
    assert response.status_code == 201
    resume_id = response.json()["resume_id"]
    # assert an ai_extraction job row exists for resume_id
    job = ...  # query ResumeAiExtractionJob
    assert job is not None


def test_manual_upload_respects_trigger_off(client):
    # PUT settings: trigger_manual_upload=False
    # upload → no ai_extraction job enqueued
```

Mirror the upload test conventions from `tests/test_batch_upload_api.py` / `tests/test_document_extraction_jobs.py` (auth cookies, PDF bytes, idempotency header).

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL — upload does not enqueue AI extraction.

- [ ] **Step 3: Add the gate helper**

In `workspace_ai_import_settings_service.py`:

```python
def should_auto_process_source(session: Session, *, source: str) -> bool:
    settings = ai_import_settings_response(session)
    if not settings.auto_summary_enabled and not settings.auto_score_enabled:
        return False
    if source == "mailbox_attachment":
        return settings.trigger_mailbox_import
    return settings.trigger_manual_upload
```

- [ ] **Step 4: Wire the upload hooks**

In `_persist_new_candidate_resume` (and the existing-candidate variant), after `resume = save_pdf_resume(...)` and before the return/commit, add:

```python
from app.services.ai_extraction_job_service import enqueue_uploaded_resume_ai_extraction
from app.services.workspace_ai_import_settings_service import should_auto_process_source

# inside the session scope, after save_pdf_resume + flush/commit of the resume
if should_auto_process_source(session, source="manual_upload"):
    enqueue_uploaded_resume_ai_extraction(
        session,
        resume=resume,
        settings=settings,
    )
```

Place it so the AI-extraction job row commits in the same transaction as the resume (mirror how `enqueue_uploaded_resume_document_extraction` is already called inside `save_pdf_resume`). Verify `enqueue_uploaded_resume_ai_extraction`'s exact signature before calling (it may take `resume` or `resume_id`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_settings_ai_import_upload_hook.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/services/workspace_ai_import_settings_service.py tests/test_settings_ai_import_upload_hook.py
git commit -m "feat: auto-enqueue AI extraction on manual upload when enabled"
```

---

### Task 7: Mailbox-import hook (auto enqueue AI extraction)

**Files:**
- Modify: `app/services/mailbox_import_service.py` (the per-attachment ingest function that calls `save_pdf_resume`, ~line 3683)
- Create: `tests/test_settings_ai_import_mailbox_hook.py`

**Interfaces:**
- Consumes: `should_auto_process_source`, `enqueue_uploaded_resume_ai_extraction`.
- Produces: mailbox-imported resumes get AI extraction auto-enqueued when `trigger_mailbox_import` + any automation is on.

- [ ] **Step 1: Write the failing test**

Use the mailbox import test double fixture (`mailbox_imap_test_double_adapter` in `conftest.py`) — read an existing mailbox import test (`tests/test_candidate_data_mailbox_replay.py` or `tests/test_mailbox_import_*.py`) and mirror it:

```python
def test_mailbox_import_auto_enqueues_ai_extraction(client):
    # enable defaults (all on)
    # run a mailbox import that ingests one attachment
    # assert an ai_extraction job exists for the imported resume
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL.

- [ ] **Step 3: Wire the hook**

In the mailbox import ingest path, after `resume = save_pdf_resume(...)` and after the `ingestion_source_type`/`source_mailbox_*` assignments, add:

```python
if should_auto_process_source(session, source="mailbox_attachment"):
    enqueue_uploaded_resume_ai_extraction(
        session,
        resume=resume,
        settings=settings,
    )
```

Confirm the mailbox ingest function has access to `settings`; if not, thread it through from the caller.

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/mailbox_import_service.py tests/test_settings_ai_import_mailbox_hook.py
git commit -m "feat: auto-enqueue AI extraction on mailbox import when enabled"
```

---

### Task 8: AI-extraction completion hook (auto summary + score)

**Files:**
- Modify: `app/services/ai_extraction_job_service.py` (`_save_completed_ai_facts`, ~line 924)
- Create: `tests/test_settings_ai_import_completion_hook.py`

**Interfaces:**
- Consumes: `should_auto_process_source` + the settings row (`ai_import_settings_response`), `enqueue_resume_summary_job` (already imported at line 43), `enqueue_resume_score_batch` (Task 5), resume's `ingestion_source_type`.
- Produces: after `save_facts` succeeds inside `_save_completed_ai_facts`:
  - if `auto_summary_enabled` and source-gated → `enqueue_resume_summary_job(session, resume=..., settings=settings)`
  - if `auto_score_enabled`, `default_score_template_id` set, and source-gated → `enqueue_resume_score_batch(session, template_id=..., settings=settings, resume_id=resume.id)`

- [ ] **Step 1: Write the failing test**

Mirror the AI-extraction flow tests (`tests/test_ai_extraction_jobs.py`) to drive a job to completion, then assert the summary job + score batch item are enqueued:

```python
def test_extraction_completion_auto_enqueues_summary_and_score(client):
    # register admin, keep ai-import defaults (all on)
    # create a default score template via /v1/score-templates
    # PUT /v1/settings/ai-import with default_score_template_id set (auto_score on)
    # upload a resume → extraction completes via worker cycle
    # assert a ResumeSummaryJob row exists for the resume
    # assert a ResumeScoreBatchItem exists for the resume
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — completion only saves facts, no summary/score job.

- [ ] **Step 3: Implement**

In `_save_completed_ai_facts`, after `save_facts` returns `saved_resume` (and after `session.flush()` of facts), add:

```python
from app.services.workspace_ai_import_settings_service import (
    ai_import_settings_response,
    should_auto_process_source,
)
from app.services.resume_score_batch_service import enqueue_resume_score_batch

# ... after facts are persisted (saved_resume available):
source = saved_resume.ingestion_source_type or "manual_upload"
if should_auto_process_source(session, source=source):
    settings_row = ai_import_settings_response(session)
    if settings_row.auto_summary_enabled:
        enqueue_resume_summary_job(
            session,
            resume=saved_resume,
            settings=settings,
        )
    if settings_row.auto_score_enabled and settings_row.default_score_template_id:
        enqueue_resume_score_batch(
            session,
            template_id=settings_row.default_score_template_id,
            settings=settings,
            resume_id=saved_resume.id,
        )
```

Read the surrounding transaction to place this where the summary/score rows commit atomically with the completed facts. If `enqueue_resume_summary_job` requires a specific resume state (active facts), confirm `save_facts` has already produced it (it has — `_save_completed_ai_facts` calls `save_facts`).

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/ai_extraction_job_service.py tests/test_settings_ai_import_completion_hook.py
git commit -m "feat: auto-enqueue summary and single-resume score after AI extraction completes"
```

---

### Task 9: Full backend verification

**Files:**
- No new files.

- [ ] **Step 1: Run the full backend suite**

Run: `python -m pytest -q`
Expected: all green (including pre-existing tests).

- [ ] **Step 2: Verify the migration upgrade + downgrade path**

Run: `alembic upgrade head` then `alembic downgrade -1` then `alembic upgrade head` against a scratch/local database.
Expected: both new tables apply and roll back cleanly with no data-loss warnings.

- [ ] **Step 3: Commit any remaining changes and summarize**

```bash
git status --short
git add -A
git commit -m "chore: settings center backend verification"
```
