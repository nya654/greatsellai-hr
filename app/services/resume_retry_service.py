"""One-click retry dispatch for failed/abnormal resume library states.

Every library row carries several independent asynchronous pipelines
(document parsing, AI extraction, automatic summary, template scoring).  A
failure in any one of them leaves the resume stuck with no list-page retry
path.  This service classifies each failure and re-queues the matching worker
job, or returns a stable skip reason when the failure cannot be retried yet.
A ready resume that never ran a pipeline also gets it here: a missing
automatic summary is generated and a never-scored resume is first-time scored
with the workspace's configured automatic-scoring templates.

The dispatcher only enqueues durable background work; it never runs a model
or document parser inside the request.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.models import (
    Resume,
    ResumeFactSnapshot,
    ResumeScoreBatchItem,
    ScoreTemplate,
)
from app.services.ai_extraction_job_service import (
    AI_EXTRACTION_NEEDS_ATTENTION,
    AI_EXTRACTION_QUEUED,
    AI_EXTRACTION_RUNNING,
    AI_EXTRACTION_UNAVAILABLE,
    ai_extraction_state,
    request_resume_ai_extraction,
)
from app.services.document_extraction_job_service import (
    DOCUMENT_EXTRACTION_QUEUED,
    DOCUMENT_EXTRACTION_RUNNING,
    request_resume_document_extraction,
)
from app.services.resume_eligibility import has_unreliable_source_text
from app.services.resume_score_batch_service import (
    ITEM_FAILED,
    ScoreServiceError,
    ScoreTemplateNotFoundError,
    enqueue_resume_score_batch,
)
from app.services.resume_summary_job_service import (
    SUMMARY_JOB_FAILED,
    SUMMARY_JOB_UNAVAILABLE,
    request_resume_summary_job,
    summary_generation_state,
)
from app.services.workspace_ai_import_settings_service import (
    ai_import_settings_response,
)

# Actions mirror the durable worker queues the dispatcher re-queues.
ACTION_DOCUMENT_EXTRACTION = "document_extraction"
ACTION_AI_EXTRACTION = "ai_extraction"
ACTION_SUMMARY = "summary"
ACTION_SCORE = "score"

# Stable skip reasons surfaced to the frontend retry tooltip.
SKIP_ACTIVE_RESUME_IMMUTABLE = "active_resume_immutable"
SKIP_JOB_ALREADY_RUNNING = "job_already_running"
SKIP_NO_SCORE_TEMPLATE = "no_score_template"
SKIP_TEMPLATE_ARCHIVED = "template_archived"
SKIP_RESUME_NOT_SCOREABLE = "resume_not_scoreable"
SKIP_NO_FAILED_STEP = "no_failed_step"

_REPARSE_SUPERSEDED_FLAG = "reparse_source_superseded_before_completion"


@dataclass(frozen=True)
class ResumeRetryDispatch:
    """Retry outcome for exactly one resume.

    ``actions`` holds every worker queue the dispatcher successfully re-queued.
    ``skip_reasons`` holds the specific reason a *triggered* branch could not
    run (an unrelated resume with no failed step yields no entry here; the
    caller reports ``no_failed_step`` when both lists are empty).
    """

    resume_id: str
    actions: tuple[str, ...] = ()
    skip_reasons: tuple[str, ...] = ()


def retry_resume_failed(
    session: Session,
    *,
    resume: Resume,
    settings: AppSettings,
) -> ResumeRetryDispatch:
    """Dispatch retries (and first-time summary/score) for one resume.

    Branches are checked in dependency order so one failed pipeline cannot
    race a replacement: a failed document parse owns the source re-extraction,
    an in-progress replacement blocks AI extraction, and summary/score work
    only runs for a resume that is currently active and extraction-ready.
    """

    actions: list[str] = []
    skip_reasons: list[str] = []
    document_job = resume.document_extraction_job
    ai_job = resume.ai_extraction_job

    # 1. Failed document parsing → re-normalize the original source file.
    if resume.extraction_status == "failed":
        if resume.is_active or resume.extraction_status == "ready":
            skip_reasons.append(SKIP_ACTIVE_RESUME_IMMUTABLE)
        elif ai_job is not None and ai_job.status in {
            AI_EXTRACTION_QUEUED,
            AI_EXTRACTION_RUNNING,
        }:
            skip_reasons.append(SKIP_JOB_ALREADY_RUNNING)
        else:
            request_resume_document_extraction(
                session,
                resume_id=resume.id,
                settings=settings,
            )
            actions.append(ACTION_DOCUMENT_EXTRACTION)

    # 2. Failed/unavailable AI extraction → re-queue the AI job.  The source
    # must still be the pending text_ready/needs_review revision; a failed
    # parse above (or a running replacement) is owned by branch 1.
    ai_status, _ = ai_extraction_state(resume)
    if (
        ai_status in {AI_EXTRACTION_NEEDS_ATTENTION, AI_EXTRACTION_UNAVAILABLE}
        and not resume.is_active
        and resume.extraction_status in {"text_ready", "needs_review"}
        and resume.source_blocks
    ):
        if document_job is not None and document_job.status in {
            DOCUMENT_EXTRACTION_QUEUED,
            DOCUMENT_EXTRACTION_RUNNING,
        }:
            skip_reasons.append(SKIP_JOB_ALREADY_RUNNING)
        else:
            request_resume_ai_extraction(
                session,
                resume_id=resume.id,
                settings=settings,
            )
            actions.append(ACTION_AI_EXTRACTION)

    # 3. Failed/unavailable automatic summary, or a ready resume with no
    # summary yet for current facts → (re-)generate for current facts.
    summary_status, _ = summary_generation_state(resume)
    if (
        resume.is_active
        and resume.extraction_status == "ready"
        and not has_unreliable_source_text(resume.quality_flags)
        and summary_status in {SUMMARY_JOB_FAILED, SUMMARY_JOB_UNAVAILABLE, None}
    ):
        request_resume_summary_job(session, resume=resume, settings=settings)
        actions.append(ACTION_SUMMARY)

    # 4. Failed template scoring → re-queue with the same template.  A resume
    # with no score attempt at all (never scored) is first-time scored with
    # the workspace's configured automatic-scoring templates.
    latest_attempt = _latest_score_attempt(session, resume_id=resume.id)
    if latest_attempt is not None and latest_attempt.status == ITEM_FAILED:
        batch = latest_attempt.batch
        template = (
            session.get(ScoreTemplate, batch.template_id) if batch is not None else None
        )
        if template is None or template.is_archived:
            skip_reasons.append(SKIP_TEMPLATE_ARCHIVED)
        elif not _resume_scoreable_now(session, resume=resume):
            skip_reasons.append(SKIP_RESUME_NOT_SCOREABLE)
        else:
            _enqueue_scoped_score(
                session,
                resume=resume,
                settings=settings,
                template_id=batch.template_id,
                skip_reasons=skip_reasons,
                actions=actions,
            )
    elif latest_attempt is None and _resume_scoreable_now(session, resume=resume):
        template_ids = _auto_score_template_ids(session)
        if not template_ids:
            skip_reasons.append(SKIP_NO_SCORE_TEMPLATE)
        else:
            for template_id in template_ids:
                _enqueue_scoped_score(
                    session,
                    resume=resume,
                    settings=settings,
                    template_id=template_id,
                    skip_reasons=skip_reasons,
                    actions=actions,
                )

    return ResumeRetryDispatch(
        resume_id=resume.id,
        actions=tuple(actions),
        skip_reasons=tuple(skip_reasons),
    )


def _auto_score_template_ids(session: Session) -> list[str]:
    """The workspace's configured automatic-scoring templates."""

    return list(ai_import_settings_response(session).score_template_ids)


def _enqueue_scoped_score(
    session: Session,
    *,
    resume: Resume,
    settings: AppSettings,
    template_id: str,
    skip_reasons: list[str],
    actions: list[str],
) -> None:
    """Enqueue one scoped score; record a stable skip reason on failure."""

    try:
        enqueue_resume_score_batch(
            session,
            template_id=template_id,
            settings=settings,
            resume_id=resume.id,
        )
    except (ScoreServiceError, ScoreTemplateNotFoundError, ValueError):
        skip_reasons.append(SKIP_TEMPLATE_ARCHIVED)
    else:
        actions.append(ACTION_SCORE)


def _latest_score_attempt(
    session: Session,
    *,
    resume_id: str,
) -> ResumeScoreBatchItem | None:
    """Return the most recent durable score attempt for a resume, if any."""

    return session.scalar(
        select(ResumeScoreBatchItem)
        .where(ResumeScoreBatchItem.resume_id == resume_id)
        .order_by(
            ResumeScoreBatchItem.updated_at.desc(),
            ResumeScoreBatchItem.id.desc(),
        )
        .limit(1)
    )


def _resume_scoreable_now(session: Session, *, resume: Resume) -> bool:
    """Mirror the score batch enqueue's scoreability gate for a scoped retry."""

    if not resume.is_active or resume.extraction_status != "ready":
        return False
    if has_unreliable_source_text(resume.quality_flags):
        return False
    snapshot = session.scalar(
        select(ResumeFactSnapshot.id).where(
            ResumeFactSnapshot.resume_id == resume.id,
            ResumeFactSnapshot.facts_version == resume.facts_version,
        )
    )
    return snapshot is not None


def resume_library_status_tone(
    resume: Resume,
    *,
    ai_status: str,
    summary_status: str | None,
    wait_estimate_present: bool,
    score_retryable: bool,
    current_score_present: bool,
) -> str | None:
    """Classify one resume into a mutually exclusive status tab.

    Priority follows the design: summary failure of an otherwise ready resume
    wins over its missing score, source-quality problems and pipeline failures
    win over a missing score, and a missing score is only reported for a ready
    resume (an in-progress resume legitimately has no score yet).  Any
    remaining inactive/queued state (including name recognition in flight)
    falls into the processing tab.
    """

    if (
        resume.is_active
        and resume.extraction_status == "ready"
        and not has_unreliable_source_text(resume.quality_flags)
    ):
        if summary_status in {SUMMARY_JOB_FAILED, SUMMARY_JOB_UNAVAILABLE}:
            return "summary_pending"
        if summary_status in {"queued", "running"} or wait_estimate_present:
            return "processing"
        if not current_score_present or score_retryable:
            return "unscored"
        return None

    if has_unreliable_source_text(resume.quality_flags):
        return "attention"
    if _REPARSE_SUPERSEDED_FLAG in (resume.quality_flags or []):
        return "attention"
    if resume.extraction_status == "failed":
        return "attention"
    if ai_status in {AI_EXTRACTION_NEEDS_ATTENTION, AI_EXTRACTION_UNAVAILABLE}:
        return "attention"
    return "processing"


__all__ = [
    "ACTION_AI_EXTRACTION",
    "ACTION_DOCUMENT_EXTRACTION",
    "ACTION_SCORE",
    "ACTION_SUMMARY",
    "SKIP_ACTIVE_RESUME_IMMUTABLE",
    "SKIP_JOB_ALREADY_RUNNING",
    "SKIP_NO_FAILED_STEP",
    "SKIP_NO_SCORE_TEMPLATE",
    "SKIP_RESUME_NOT_SCOREABLE",
    "SKIP_TEMPLATE_ARCHIVED",
    "ResumeRetryDispatch",
    "resume_library_status_tone",
    "retry_resume_failed",
]
