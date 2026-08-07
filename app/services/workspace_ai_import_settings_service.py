"""Workspace-scoped AI import processing preference services.

The preference row is created lazily with all-auto defaults on first read,
matching the "默认全开" product decision.  Every read and write resolves the
workspace from the session tenant context rather than a caller-supplied ID, so
a request can never touch another workspace's row even if it knows the
resource primary key.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ScoreTemplate, WorkspaceAiImportSettings
from app.schemas import AiImportSettingsResponse, AiImportSettingsUpdate
from app.tenant_scope import organization_context_id


def _default_row(session: Session) -> WorkspaceAiImportSettings:
    organization_id = organization_context_id(session)
    row = session.scalar(
        select(WorkspaceAiImportSettings).where(
            WorkspaceAiImportSettings.organization_id == organization_id
        )
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
        score_template_ids=list(row.score_template_ids or []),
        trigger_manual_upload=row.trigger_manual_upload,
        trigger_mailbox_import=row.trigger_mailbox_import,
    )


def should_auto_process_source(session: Session, *, source: str) -> bool:
    settings = ai_import_settings_response(session)
    if not settings.auto_summary_enabled and not settings.auto_score_enabled:
        return False
    if source == "mailbox_attachment":
        return settings.trigger_mailbox_import
    return settings.trigger_manual_upload


def update_ai_import_settings(
    session: Session,
    *,
    request: AiImportSettingsUpdate,
    actor_user_id: str,
) -> AiImportSettingsResponse:
    organization_id = organization_context_id(session)
    seen: set[str] = set()
    for template_id in request.score_template_ids:
        if template_id in seen:
            raise ValueError("duplicate_score_template")
        template = session.get(ScoreTemplate, template_id)
        if template is None or template.organization_id != organization_id:
            raise ValueError("score_template_not_found")
        seen.add(template_id)
    if request.auto_score_enabled and not request.score_template_ids:
        raise ValueError("score_template_required")

    row = _default_row(session)
    row.auto_summary_enabled = request.auto_summary_enabled
    row.auto_score_enabled = request.auto_score_enabled
    row.score_template_ids = list(request.score_template_ids)
    row.trigger_manual_upload = request.trigger_manual_upload
    row.trigger_mailbox_import = request.trigger_mailbox_import
    row.updated_by_user_id = actor_user_id
    session.flush()
    return ai_import_settings_response(session)
