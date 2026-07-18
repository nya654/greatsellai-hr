from __future__ import annotations

import json

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.models import Resume, ResumeFactSnapshot, ResumeSummary
from app.schemas import (
    ResumeSummaryManualCreate,
    ResumeSummaryResponse,
)
from app.services.deepseek_provider import (
    DeepSeekProviderError,
    summarize_resume_fact_snapshot,
)
from app.services.resume_eligibility import has_unreliable_source_text


class SummaryServiceError(RuntimeError):
    pass


class ResumeSummaryNotFoundError(SummaryServiceError):
    pass


def _response(summary: ResumeSummary) -> ResumeSummaryResponse:
    return ResumeSummaryResponse(
        summary_id=summary.id,
        resume_id=summary.resume_id,
        fact_snapshot_id=summary.fact_snapshot_id,
        facts_version=summary.facts_version,
        content=summary.content or {},
        source=summary.source,
        supersedes_id=summary.supersedes_id,
        is_current=summary.is_current,
        status=summary.status,
        model_name=summary.model_name,
        created_at=summary.created_at.isoformat(),
    )


def _ready_resume_snapshot(
    session: Session,
    *,
    resume_id: str,
) -> tuple[Resume, ResumeFactSnapshot, dict[str, object]]:
    resume = session.get(Resume, resume_id)
    if resume is None:
        raise SummaryServiceError("resume_not_found")
    if resume.extraction_status != "ready" or not resume.is_active:
        raise SummaryServiceError("resume_must_be_active_and_ready_for_summary")
    if has_unreliable_source_text(resume.quality_flags):
        raise SummaryServiceError("resume_source_text_unreliable")
    snapshot = session.scalar(
        select(ResumeFactSnapshot)
        .where(ResumeFactSnapshot.resume_id == resume.id)
        .order_by(ResumeFactSnapshot.facts_version.desc())
    )
    if snapshot is None or snapshot.facts_version != resume.facts_version:
        raise SummaryServiceError("resume_fact_snapshot_not_current")
    try:
        payload = json.loads(snapshot.canonical_facts_json)
    except json.JSONDecodeError as exc:
        raise SummaryServiceError("resume_fact_snapshot_invalid") from exc
    if not isinstance(payload, dict):
        raise SummaryServiceError("resume_fact_snapshot_invalid")
    return resume, snapshot, payload


def _set_current(
    session: Session,
    *,
    resume_id: str,
) -> None:
    session.execute(
        update(ResumeSummary)
        .where(ResumeSummary.resume_id == resume_id, ResumeSummary.is_current.is_(True))
        .values(is_current=False)
    )


def generate_resume_summary(
    session: Session,
    *,
    resume_id: str,
    settings: AppSettings,
) -> ResumeSummaryResponse:
    if not settings.deepseek_api_key:
        raise SummaryServiceError("deepseek_api_key_not_configured")
    resume, snapshot, fact_snapshot = _ready_resume_snapshot(session, resume_id=resume_id)
    content = summarize_resume_fact_snapshot(
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_model,
        timeout_seconds=settings.deepseek_timeout_seconds,
        fact_snapshot=fact_snapshot,
    )
    _set_current(session, resume_id=resume.id)
    summary = ResumeSummary(
        resume_id=resume.id,
        fact_snapshot_id=snapshot.id,
        facts_version=snapshot.facts_version,
        content=content,
        source="ai",
        is_current=True,
        status="succeeded",
        model_name=settings.deepseek_model,
    )
    session.add(summary)
    session.flush()
    return _response(summary)


def get_resume_summary(session: Session, *, summary_id: str) -> ResumeSummaryResponse:
    summary = session.get(ResumeSummary, summary_id)
    if summary is None:
        raise ResumeSummaryNotFoundError("resume_summary_not_found")
    return _response(summary)


def list_resume_summaries(
    session: Session,
    *,
    resume_id: str,
) -> list[ResumeSummaryResponse]:
    summaries = session.scalars(
        select(ResumeSummary)
        .where(ResumeSummary.resume_id == resume_id)
        .order_by(ResumeSummary.created_at.desc(), ResumeSummary.id.desc())
    ).all()
    return [_response(summary) for summary in summaries]


def create_manual_summary_version(
    session: Session,
    *,
    summary_id: str,
    payload: ResumeSummaryManualCreate,
) -> ResumeSummaryResponse:
    prior_summary = session.get(ResumeSummary, summary_id)
    if prior_summary is None:
        raise ResumeSummaryNotFoundError("resume_summary_not_found")
    _, current_snapshot, _ = _ready_resume_snapshot(
        session,
        resume_id=prior_summary.resume_id,
    )
    if (
        prior_summary.fact_snapshot_id != current_snapshot.id
        or prior_summary.facts_version != current_snapshot.facts_version
    ):
        raise SummaryServiceError("resume_summary_not_current_facts")
    _set_current(session, resume_id=prior_summary.resume_id)
    summary = ResumeSummary(
        resume_id=prior_summary.resume_id,
        fact_snapshot_id=prior_summary.fact_snapshot_id,
        facts_version=prior_summary.facts_version,
        content={
            "schema_version": "resume_summary.manual.v1",
            "sections": {key.strip(): value.strip() for key, value in payload.content.items()},
        },
        source="manual",
        supersedes_id=prior_summary.id,
        is_current=True,
        status="succeeded",
        model_name=None,
    )
    session.add(summary)
    session.flush()
    return _response(summary)


__all__ = [
    "DeepSeekProviderError",
    "ResumeSummaryNotFoundError",
    "SummaryServiceError",
    "create_manual_summary_version",
    "generate_resume_summary",
    "get_resume_summary",
    "list_resume_summaries",
]
