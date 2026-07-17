from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.database import Database
from app.models import Candidate, Resume, ResumeAiExtractionJob, ResumeSourceBlock
from app.schemas import ResumeFactsSaveRequest, ResumeFactsSubmission
from app.services.deepseek_provider import (
    DeepSeekProviderError,
    EvidenceBlock,
    extract_resume_candidate_name,
    extract_resume_core_facts,
    extract_resume_facts,
)
from app.services.resume_service import (
    FactValidationError,
    _assert_raw_value_grounded,
    _source_text_by_ids,
    get_resume,
    prepare_ai_draft_facts,
    save_facts,
)


logger = logging.getLogger(__name__)

AI_EXTRACTION_QUEUED = "queued"
AI_EXTRACTION_RUNNING = "running"
AI_EXTRACTION_COMPLETED = "completed"
AI_EXTRACTION_NEEDS_ATTENTION = "needs_attention"
AI_EXTRACTION_UNAVAILABLE = "unavailable"

_RETRYABLE_HTTP_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}
_NO_KEY_ERROR = "deepseek_api_key_not_configured"
_RETRYABLE_STRUCTURED_RESPONSE_ERRORS = frozenset(
    {
        "deepseek_empty_structured_facts",
        "deepseek_invalid_structured_response",
        "deepseek_tool_call_missing",
        "deepseek_arguments_missing",
    }
)


class AiExtractionJobError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClaimedAiExtractionJob:
    job_id: str
    resume_id: str
    input_facts_version: int
    previous_error: str | None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ai_extraction_state(
    resume: Resume,
) -> tuple[str, str | None]:
    """Return the UI-safe status for the most recent durable AI job."""

    job = resume.ai_extraction_job
    if job is not None:
        return job.status, job.last_error
    if resume.extraction_status == "text_ready":
        # This is only expected for pre-worker legacy data.  New uploads create
        # a job in the same transaction as the Resume row.
        return AI_EXTRACTION_NEEDS_ATTENTION, "ai_extraction_not_queued"
    return AI_EXTRACTION_NEEDS_ATTENTION, "native_pdf_text_unavailable"


def enqueue_uploaded_resume_ai_extraction(
    session: Session,
    *,
    resume: Resume,
    settings: AppSettings,
) -> ResumeAiExtractionJob | None:
    """Create a native-text AI job inside the caller's upload transaction.

    PDFs that did not reach ``text_ready`` are deliberately not queued: V1
    does not invoke OCR and an LLM cannot safely recover unavailable text.
    """

    if resume.extraction_status != "text_ready":
        return None
    existing = resume.ai_extraction_job
    if existing is not None:
        return existing
    now = utcnow()
    job = ResumeAiExtractionJob(
        resume_id=resume.id,
        status=(
            AI_EXTRACTION_QUEUED
            if settings.deepseek_api_key
            else AI_EXTRACTION_UNAVAILABLE
        ),
        attempt_count=0,
        max_attempts=settings.ai_extraction_job_max_attempts,
        input_facts_version=resume.facts_version,
        next_attempt_at=now if settings.deepseek_api_key else None,
        last_error=None if settings.deepseek_api_key else _NO_KEY_ERROR,
        requested_at=now,
    )
    session.add(job)
    resume.ai_extraction_job = job
    session.flush()
    return job


def request_resume_ai_extraction(
    session: Session,
    *,
    resume_id: str,
    settings: AppSettings,
) -> Resume:
    """Queue/requeue AI extraction without executing a model call in HTTP.

    A completed human review is immutable here.  Retry is available only while
    the resume is still inactive and pending review, so an old delayed job can
    never replace confirmed screening data.
    """

    resume = get_resume(session, resume_id)
    job = resume.ai_extraction_job
    if job is None:
        if resume.extraction_status != "text_ready":
            raise AiExtractionJobError("resume_has_no_native_text_for_ai_extraction")
        enqueue_uploaded_resume_ai_extraction(session, resume=resume, settings=settings)
        return resume

    if job.status in {AI_EXTRACTION_QUEUED, AI_EXTRACTION_RUNNING}:
        return resume
    if resume.is_active or resume.extraction_status == "ready":
        raise AiExtractionJobError("completed_resume_cannot_be_reextracted")
    if resume.extraction_status not in {"text_ready", "needs_review"}:
        raise AiExtractionJobError("resume_has_no_native_text_for_ai_extraction")
    if not resume.source_blocks:
        raise AiExtractionJobError("resume_has_no_native_text_for_ai_extraction")

    now = utcnow()
    job.status = (
        AI_EXTRACTION_QUEUED if settings.deepseek_api_key else AI_EXTRACTION_UNAVAILABLE
    )
    job.attempt_count = 0
    job.max_attempts = settings.ai_extraction_job_max_attempts
    job.input_facts_version = resume.facts_version
    job.next_attempt_at = now if settings.deepseek_api_key else None
    job.lease_owner = None
    job.lease_expires_at = None
    job.last_error = None if settings.deepseek_api_key else _NO_KEY_ERROR
    job.requested_at = now
    job.started_at = None
    job.completed_at = None
    session.flush()
    return resume


def backfill_unnamed_candidate_names(
    database: Database,
    *,
    settings: AppSettings,
    limit: int = 100,
) -> tuple[int, int]:
    """Fill only empty candidate names without touching completed facts.

    The compact extraction fallback deliberately omits identity. This bounded
    repair calls a name-only contract and keeps the same page-evidence check
    before writing, so it can never replace an existing name or alter scores,
    summaries, or screening facts.
    """

    if limit < 1:
        return 0, 0
    if not settings.deepseek_api_key:
        raise AiExtractionJobError(_NO_KEY_ERROR)

    with database.session_factory() as session:
        resume_ids = session.scalars(
            select(Resume.id)
            .join(Candidate, Candidate.id == Resume.candidate_id)
            .where(
                or_(Candidate.display_name.is_(None), Candidate.display_name == ""),
            )
            .order_by(Resume.created_at.asc(), Resume.id.asc())
            .limit(limit)
        ).all()

    updated = 0
    skipped = 0
    for resume_id in resume_ids:
        with database.session_factory() as session:
            resume = session.get(Resume, resume_id)
            if resume is None:
                continue
            source_blocks = session.scalars(
                select(ResumeSourceBlock)
                .where(ResumeSourceBlock.resume_id == resume.id)
                .order_by(ResumeSourceBlock.page_no, ResumeSourceBlock.block_id)
            ).all()
            blocks = [
                EvidenceBlock(
                    block_id=block.block_id,
                    page_no=block.page_no,
                    block_type=block.block_type,
                    text=block.text,
                )
                for block in source_blocks
            ]
        if not blocks:
            skipped += 1
            continue
        try:
            draft = extract_resume_candidate_name(
                api_key=settings.deepseek_api_key,
                model=settings.deepseek_model,
                timeout_seconds=settings.deepseek_timeout_seconds,
                blocks=blocks,
            )
        except DeepSeekProviderError:
            skipped += 1
            continue
        if draft.value is None:
            skipped += 1
            continue

        with database.session_factory() as session:
            resume = session.scalar(
                select(Resume).where(Resume.id == resume_id).with_for_update()
            )
            if resume is None:
                continue
            candidate = session.scalar(
                select(Candidate)
                .where(Candidate.id == resume.candidate_id)
                .with_for_update()
            )
            if candidate is None:
                session.rollback()
                continue
            if candidate.display_name and candidate.display_name.strip():
                session.rollback()
                continue
            try:
                evidence_text = _source_text_by_ids(
                    session,
                    resume_id=resume.id,
                    block_ids=draft.evidence_block_ids,
                )
                _assert_raw_value_grounded(
                    value=draft.value,
                    source_text=evidence_text,
                    label="candidate_name_raw",
                )
            except FactValidationError:
                session.rollback()
                skipped += 1
                continue
            candidate.display_name = draft.value
            session.commit()
            updated += 1
    return updated, skipped


def run_ai_extraction_worker_once(
    database: Database,
    *,
    settings: AppSettings,
    worker_id: str,
) -> bool:
    """Claim and process at most one persisted job.  Returns whether one ran."""

    claimed = _claim_next_job(database, settings=settings, worker_id=worker_id)
    if claimed is None:
        return False
    _process_claimed_job(
        database,
        settings=settings,
        worker_id=worker_id,
        claimed=claimed,
    )
    return True


def _claim_next_job(
    database: Database,
    *,
    settings: AppSettings,
    worker_id: str,
) -> ClaimedAiExtractionJob | None:
    now = utcnow()
    with database.session_factory() as session:
        if not settings.deepseek_api_key:
            _mark_jobs_unavailable_without_key(session, now=now)
            session.commit()
            return None

        # A deploy/restart can make a previously unavailable job executable.
        session.execute(
            update(ResumeAiExtractionJob)
            .where(
                ResumeAiExtractionJob.status == AI_EXTRACTION_UNAVAILABLE,
                ResumeAiExtractionJob.last_error == _NO_KEY_ERROR,
            )
            .values(
                status=AI_EXTRACTION_QUEUED,
                next_attempt_at=now,
                last_error=None,
                lease_owner=None,
                lease_expires_at=None,
            )
        )
        _recover_expired_leases(session, now=now)

        eligible = and_(
            ResumeAiExtractionJob.status == AI_EXTRACTION_QUEUED,
            ResumeAiExtractionJob.attempt_count < ResumeAiExtractionJob.max_attempts,
            or_(
                ResumeAiExtractionJob.next_attempt_at.is_(None),
                ResumeAiExtractionJob.next_attempt_at <= now,
            ),
        )
        candidate = session.execute(
            select(ResumeAiExtractionJob.id, ResumeAiExtractionJob.last_error)
            .where(eligible)
            .order_by(
                ResumeAiExtractionJob.next_attempt_at.asc(),
                ResumeAiExtractionJob.requested_at.asc(),
                ResumeAiExtractionJob.id.asc(),
            )
            .limit(1)
        ).one_or_none()
        if candidate is None:
            session.commit()
            return None
        candidate_id = candidate[0]
        previous_error = candidate[1]

        lease_expires_at = now + timedelta(
            seconds=settings.ai_extraction_job_lease_seconds
        )
        claim = session.execute(
            update(ResumeAiExtractionJob)
            .where(ResumeAiExtractionJob.id == candidate_id, eligible)
            .values(
                status=AI_EXTRACTION_RUNNING,
                attempt_count=ResumeAiExtractionJob.attempt_count + 1,
                started_at=now,
                lease_owner=worker_id,
                lease_expires_at=lease_expires_at,
                next_attempt_at=None,
                last_error=None,
            )
        )
        if claim.rowcount != 1:
            session.rollback()
            return None
        job = session.get(ResumeAiExtractionJob, candidate_id)
        assert job is not None
        claimed = ClaimedAiExtractionJob(
            job_id=job.id,
            resume_id=job.resume_id,
            input_facts_version=job.input_facts_version,
            previous_error=previous_error,
        )
        session.commit()
        return claimed


def _mark_jobs_unavailable_without_key(session: Session, *, now: datetime) -> None:
    session.execute(
        update(ResumeAiExtractionJob)
        .where(ResumeAiExtractionJob.status == AI_EXTRACTION_QUEUED)
        .values(
            status=AI_EXTRACTION_UNAVAILABLE,
            next_attempt_at=None,
            lease_owner=None,
            lease_expires_at=None,
            last_error=_NO_KEY_ERROR,
            completed_at=now,
        )
    )
    session.execute(
        update(ResumeAiExtractionJob)
        .where(
            ResumeAiExtractionJob.status == AI_EXTRACTION_RUNNING,
            ResumeAiExtractionJob.lease_expires_at.is_not(None),
            ResumeAiExtractionJob.lease_expires_at <= now,
        )
        .values(
            status=AI_EXTRACTION_UNAVAILABLE,
            next_attempt_at=None,
            lease_owner=None,
            lease_expires_at=None,
            last_error=_NO_KEY_ERROR,
            completed_at=now,
        )
    )


def _recover_expired_leases(session: Session, *, now: datetime) -> None:
    expired = and_(
        ResumeAiExtractionJob.status == AI_EXTRACTION_RUNNING,
        ResumeAiExtractionJob.lease_expires_at.is_not(None),
        ResumeAiExtractionJob.lease_expires_at <= now,
    )
    session.execute(
        update(ResumeAiExtractionJob)
        .where(expired, ResumeAiExtractionJob.attempt_count >= ResumeAiExtractionJob.max_attempts)
        .values(
            status=AI_EXTRACTION_NEEDS_ATTENTION,
            lease_owner=None,
            lease_expires_at=None,
            next_attempt_at=None,
            last_error="ai_extraction_worker_lease_expired",
            completed_at=now,
        )
    )
    session.execute(
        update(ResumeAiExtractionJob)
        .where(expired, ResumeAiExtractionJob.attempt_count < ResumeAiExtractionJob.max_attempts)
        .values(
            status=AI_EXTRACTION_QUEUED,
            lease_owner=None,
            lease_expires_at=None,
            next_attempt_at=now,
            last_error="ai_extraction_worker_lease_expired",
        )
    )


def _process_claimed_job(
    database: Database,
    *,
    settings: AppSettings,
    worker_id: str,
    claimed: ClaimedAiExtractionJob,
) -> None:
    try:
        blocks = _load_claimed_source_blocks(
            database,
            worker_id=worker_id,
            claimed=claimed,
        )
    except AiExtractionJobError as exc:
        _finish_failure(
            database,
            worker_id=worker_id,
            job_id=claimed.job_id,
            error=str(exc),
            retryable=False,
        )
        return

    core_fallback = claimed.previous_error in _RETRYABLE_STRUCTURED_RESPONSE_ERRORS
    try:
        if core_fallback:
            facts = extract_resume_core_facts(
                api_key=settings.deepseek_api_key or "",
                model=settings.deepseek_model,
                timeout_seconds=settings.deepseek_timeout_seconds,
                blocks=blocks,
            )
        else:
            facts = extract_resume_facts(
                api_key=settings.deepseek_api_key or "",
                model=settings.deepseek_model,
                timeout_seconds=settings.deepseek_timeout_seconds,
                blocks=blocks,
            )
    except DeepSeekProviderError as exc:
        error = str(exc)
        _finish_failure(
            database,
            worker_id=worker_id,
            job_id=claimed.job_id,
            error=error,
            retryable=_is_retryable_deepseek_error(error),
        )
        return
    except Exception:  # pragma: no cover - defensive containment for the worker
        logger.exception("Unexpected AI resume extraction worker failure")
        _finish_failure(
            database,
            worker_id=worker_id,
            job_id=claimed.job_id,
            error="ai_extraction_worker_error",
            retryable=True,
        )
        return

    try:
        _save_completed_ai_facts(
            database,
            worker_id=worker_id,
            claimed=claimed,
            facts=facts,
            model=settings.deepseek_model,
            core_fallback=core_fallback,
        )
    except FactValidationError as exc:
        _finish_failure(
            database,
            worker_id=worker_id,
            job_id=claimed.job_id,
            error=str(exc),
            retryable=False,
        )
    except AiExtractionJobError as exc:
        _finish_failure(
            database,
            worker_id=worker_id,
            job_id=claimed.job_id,
            error=str(exc),
            retryable=False,
        )
    except Exception:  # pragma: no cover - defensive containment for database faults
        logger.exception("Unable to persist AI resume extraction result")
        _finish_failure(
            database,
            worker_id=worker_id,
            job_id=claimed.job_id,
            error="ai_extraction_persist_failed",
            retryable=True,
        )


def _load_claimed_source_blocks(
    database: Database,
    *,
    worker_id: str,
    claimed: ClaimedAiExtractionJob,
) -> list[EvidenceBlock]:
    with database.session_factory() as session:
        job = _owned_running_job(session, job_id=claimed.job_id, worker_id=worker_id)
        if job is None:
            raise AiExtractionJobError("ai_extraction_job_lease_lost")
        resume = session.get(Resume, claimed.resume_id)
        if resume is None:
            raise AiExtractionJobError("resume_not_found")
        _assert_resume_unchanged_for_job(resume, job=job)
        source_blocks = session.scalars(
            select(ResumeSourceBlock)
            .where(ResumeSourceBlock.resume_id == resume.id)
            .order_by(ResumeSourceBlock.page_no, ResumeSourceBlock.block_id)
        ).all()
        if not source_blocks:
            raise AiExtractionJobError("resume_has_no_native_text_for_ai_extraction")
        blocks = [
            EvidenceBlock(
                block_id=block.block_id,
                page_no=block.page_no,
                block_type=block.block_type,
                text=block.text,
            )
            for block in source_blocks
        ]
        # No transaction is held while the external provider call is in flight.
        session.rollback()
        return blocks


def _save_completed_ai_facts(
    database: Database,
    *,
    worker_id: str,
    claimed: ClaimedAiExtractionJob,
    facts: ResumeFactsSubmission,
    model: str,
    core_fallback: bool = False,
) -> None:
    with database.session_factory() as session:
        # Lock the job and resume only for the short persistence transaction.
        # The external AI request has already completed, so this does not hold
        # a database lock during network I/O.  It closes the race where a human
        # completes review between the version check and the AI result save.
        job = _owned_running_job(
            session,
            job_id=claimed.job_id,
            worker_id=worker_id,
            for_update=True,
        )
        if job is None:
            session.rollback()
            raise AiExtractionJobError("ai_extraction_job_lease_lost")
        resume = session.scalar(
            select(Resume)
            .where(Resume.id == claimed.resume_id)
            .with_for_update()
        )
        if resume is None:
            session.rollback()
            raise AiExtractionJobError("resume_not_found")
        _assert_resume_unchanged_for_job(resume, job=job)
        try:
            prepared_facts, is_partial_draft = prepare_ai_draft_facts(
                session,
                resume_id=resume.id,
                facts=facts,
            )
            saved_resume = save_facts(
                session,
                resume_id=resume.id,
                request=ResumeFactsSaveRequest(facts=prepared_facts),
                created_by=f"ai:{model}",
                force_pending_review=True,
                auto_activate=True,
            )
            quality_flags = set(saved_resume.quality_flags or [])
            if is_partial_draft:
                quality_flags.add("ai_draft_partial_source_grounding")
            else:
                quality_flags.discard("ai_draft_partial_source_grounding")
            if core_fallback:
                quality_flags.add("ai_draft_details_pending")
            else:
                quality_flags.discard("ai_draft_details_pending")
            saved_resume.quality_flags = sorted(quality_flags)
            # All facts have been source-grounded before saving. A completed
            # extraction must therefore be the active screening version.
            if saved_resume.extraction_status != "ready" or not saved_resume.is_active:
                raise AiExtractionJobError("ai_extraction_must_auto_activate")
            job.status = AI_EXTRACTION_COMPLETED
            job.lease_owner = None
            job.lease_expires_at = None
            job.next_attempt_at = None
            job.last_error = None
            job.completed_at = utcnow()
            session.commit()
        except Exception:
            session.rollback()
            raise


def _finish_failure(
    database: Database,
    *,
    worker_id: str,
    job_id: str,
    error: str,
    retryable: bool,
) -> None:
    now = utcnow()
    with database.session_factory() as session:
        job = _owned_running_job(session, job_id=job_id, worker_id=worker_id)
        if job is None:
            session.rollback()
            return
        retry = retryable and job.attempt_count < job.max_attempts
        if retry:
            delay_seconds = min(60, 2 ** max(job.attempt_count - 1, 0))
            job.status = AI_EXTRACTION_QUEUED
            job.next_attempt_at = now + timedelta(seconds=delay_seconds)
            job.completed_at = None
        else:
            job.status = AI_EXTRACTION_NEEDS_ATTENTION
            job.next_attempt_at = None
            job.completed_at = now
        job.lease_owner = None
        job.lease_expires_at = None
        job.last_error = error[:2000]
        session.commit()


def _owned_running_job(
    session: Session,
    *,
    job_id: str,
    worker_id: str,
    for_update: bool = False,
) -> ResumeAiExtractionJob | None:
    statement = select(ResumeAiExtractionJob).where(
        ResumeAiExtractionJob.id == job_id,
        ResumeAiExtractionJob.status == AI_EXTRACTION_RUNNING,
        ResumeAiExtractionJob.lease_owner == worker_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def _assert_resume_unchanged_for_job(
    resume: Resume,
    *,
    job: ResumeAiExtractionJob,
) -> None:
    if resume.is_active or resume.extraction_status == "ready":
        raise AiExtractionJobError("resume_changed_before_ai_extraction_completed")
    if resume.extraction_status not in {"text_ready", "needs_review"}:
        raise AiExtractionJobError("resume_has_no_native_text_for_ai_extraction")
    if resume.facts_version != job.input_facts_version:
        raise AiExtractionJobError("resume_changed_before_ai_extraction_completed")


def _is_retryable_deepseek_error(error: str) -> bool:
    if error in {
        "deepseek_network_error",
        "deepseek_timeout",
        *_RETRYABLE_STRUCTURED_RESPONSE_ERRORS,
    }:
        return True
    matched = re.fullmatch(r"deepseek_http_(\d{3})", error)
    return bool(matched and int(matched.group(1)) in _RETRYABLE_HTTP_STATUSES)


__all__ = [
    "AI_EXTRACTION_COMPLETED",
    "AI_EXTRACTION_NEEDS_ATTENTION",
    "AI_EXTRACTION_QUEUED",
    "AI_EXTRACTION_RUNNING",
    "AI_EXTRACTION_UNAVAILABLE",
    "AiExtractionJobError",
    "ai_extraction_state",
    "backfill_unnamed_candidate_names",
    "enqueue_uploaded_resume_ai_extraction",
    "request_resume_ai_extraction",
    "run_ai_extraction_worker_once",
]
