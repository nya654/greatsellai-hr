from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Resume,
    ResumeEducation,
    ResumeScore,
    ResumeScoreBatch,
    ResumeScoreBatchItem,
    ResumeSummary,
)
from app.schemas import (
    ResumeAnalysisWaitEstimate as ResumeAnalysisWaitEstimateResponse,
    ResumeLibraryItem,
    ResumeLibraryResponse,
)
from app.services.ai_extraction_job_service import ai_extraction_state
from app.services.candidate_favorite_service import favorite_candidate_ids
from app.services.candidate_name_job_service import candidate_name_extraction_state
from app.services.normalization import DEGREE_RANK
from app.services.resume_analysis_wait_estimate_service import (
    estimate_pending_resume_analysis_waits,
)
from app.services.resume_retry_service import resume_library_status_tone
from app.services.resume_score_batch_service import ITEM_FAILED
from app.services.resume_summary_job_service import summary_generation_state
from app.services.source_tag_service import resume_source_tag_references


_SUMMARY_SECTION_ORDER = (
    "candidate_positioning",
    "work_and_internship",
    "core_skills",
    "strengths",
)
# Keep review-needed AI scores visible in the recruiter library.  They remain
# clearly labelled by their status and are never an automatic hiring decision.
_CURRENT_SCORE_STATUSES = {"succeeded", "needs_review", "overridden"}
# A row's score is "in progress" while an active batch item owns it.  Both
# the batch and the item must be non-terminal for the derivation to fire.
_IN_PROGRESS_SCORE_STATUSES = ("queued", "running")
_PREVIEW_MAX_CHARS = 220


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


def _isoformat(value: datetime) -> str:
    """Preserve the API's UTC offset when SQLite reloads a naive timestamp."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _section_text(value: object) -> str | None:
    if isinstance(value, Mapping):
        content = value.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _summary_preview(content: object) -> str | None:
    if not isinstance(content, Mapping):
        return None
    sections = content.get("sections")
    if not isinstance(sections, Mapping):
        return None

    text = next(
        (
            rendered
            for key in _SUMMARY_SECTION_ORDER
            if (rendered := _section_text(sections.get(key)))
        ),
        None,
    )
    if text is None:
        text = next(
            (
                rendered
                for value in sections.values()
                if (rendered := _section_text(value))
            ),
            None,
        )
    if text is None:
        return None
    normalized = " ".join(text.split())
    if len(normalized) <= _PREVIEW_MAX_CHARS:
        return normalized
    return f"{normalized[:_PREVIEW_MAX_CHARS - 1].rstrip()}…"


def _current_summary(resume: Resume) -> ResumeSummary | None:
    candidates = [
        summary
        for summary in resume.summaries
        if summary.is_current
        and summary.status == "succeeded"
        and summary.facts_version == resume.facts_version
    ]
    return max(candidates, key=lambda summary: (summary.created_at, summary.id), default=None)


def _latest_current_score(resume: Resume) -> ResumeScore | None:
    candidates = [
        score
        for score in resume.scores
        if score.facts_version == resume.facts_version
        and score.status in _CURRENT_SCORE_STATUSES
    ]
    return max(candidates, key=lambda score: (score.created_at, score.id), default=None)


def _highest_education(resume: Resume) -> ResumeEducation | None:
    """Return the education record that grounds the compact library profile."""

    return max(
        resume.educations,
        key=lambda item: (
            DEGREE_RANK.get(item.degree, 0),
            item.end_month or "",
            item.id,
        ),
        default=None,
    )


def _latest_score_attempt_by_resume(
    session: Session,
    *,
    resume_ids: list[str],
) -> dict[str, ResumeScoreBatchItem]:
    """Return the most recent durable score attempt per resume, if any."""

    if not resume_ids:
        return {}
    rows = session.execute(
        select(ResumeScoreBatchItem)
        .where(ResumeScoreBatchItem.resume_id.in_(resume_ids))
        .order_by(
            ResumeScoreBatchItem.updated_at.desc(),
            ResumeScoreBatchItem.id.desc(),
        )
    ).scalars().all()
    latest: dict[str, ResumeScoreBatchItem] = {}
    for row in rows:
        latest.setdefault(row.resume_id, row)
    return latest


def _library_state_for_tone(
    session: Session,
    resume: Resume,
    *,
    wait_estimates: Mapping[str, object],
    score_attempts: Mapping[str, ResumeScoreBatchItem],
) -> str | None:
    """Classify one resume into its status tab for the filtered view."""

    ai_status, _ = ai_extraction_state(resume)
    summary_status, _ = summary_generation_state(resume)
    score_attempt = score_attempts.get(resume.id)
    return resume_library_status_tone(
        resume,
        ai_status=ai_status,
        summary_status=summary_status,
        wait_estimate_present=resume.id in wait_estimates,
        score_retryable=score_attempt is not None and score_attempt.status == ITEM_FAILED,
        current_score_present=_latest_current_score(resume) is not None,
    )


_STATUS_TONE_KEYS = ("processing", "attention", "unscored", "summary_pending")


def _status_tone_counts(
    session: Session,
    resumes: list[Resume],
) -> dict[str, int]:
    """Count every resume's status tab across the whole library.

    The tab badges must stay stable while paging, so these come from the full
    result set, never from the paginated slice returned to the page.
    """

    counts = {tone: 0 for tone in _STATUS_TONE_KEYS}
    if not resumes:
        return counts
    wait_estimates = estimate_pending_resume_analysis_waits(
        session,
        resumes=resumes,
    )
    score_attempts = _latest_score_attempt_by_resume(
        session,
        resume_ids=[resume.id for resume in resumes],
    )
    for resume in resumes:
        tone = _library_state_for_tone(
            session,
            resume,
            wait_estimates=wait_estimates,
            score_attempts=score_attempts,
        )
        if tone is not None:
            counts[tone] += 1
    return counts


_LIBRARY_LOAD_OPTIONS = (
    selectinload(Resume.candidate),
    selectinload(Resume.document_extraction_job),
    selectinload(Resume.ai_extraction_job),
    selectinload(Resume.candidate_name_extraction_job),
    selectinload(Resume.educations),
    selectinload(Resume.summaries),
    selectinload(Resume.summary_jobs),
    selectinload(Resume.scores).selectinload(ResumeScore.template),
)


def list_resume_library(
    session: Session,
    *,
    page: int,
    page_size: int,
    mailbox_config_id: str | None = None,
    viewer_user_id: str | None = None,
    status_filter: Literal[
        "processing", "attention", "unscored", "summary_pending"
    ] | None = None,
) -> ResumeLibraryResponse:
    """List uploaded resume versions without exposing raw extracted facts.

    ``status_filter`` narrows the view to one mutually exclusive status tab.
    The four buckets depend on per-resume job states that are impractical to
    express as SQL, so the filtered path classifies every matching resume in
    Python before paginating.  Without a filter the common list uses the
    existing SQL-paged fast path.
    """

    filters = []
    if mailbox_config_id is not None:
        filters.append(Resume.source_mailbox_config_id == mailbox_config_id)
    base_statement = (
        select(Resume)
        .options(*_LIBRARY_LOAD_OPTIONS)
        .where(*filters)
        .order_by(Resume.created_at.desc(), Resume.id.desc())
    )

    if status_filter is None:
        all_resumes = session.scalars(base_statement).all()
        total = len(all_resumes)
        resumes = all_resumes[(page - 1) * page_size : page * page_size]
    else:
        all_resumes = session.scalars(base_statement).all()
        wait_estimates = estimate_pending_resume_analysis_waits(
            session,
            resumes=all_resumes,
        )
        score_attempts = _latest_score_attempt_by_resume(
            session,
            resume_ids=[resume.id for resume in all_resumes],
        )
        filtered = [
            resume
            for resume in all_resumes
            if _library_state_for_tone(
                session,
                resume,
                wait_estimates=wait_estimates,
                score_attempts=score_attempts,
            )
            == status_filter
        ]
        total = len(filtered)
        resumes = filtered[(page - 1) * page_size : page * page_size]

    source_tags_by_resume = resume_source_tag_references(
        session,
        resume_ids=[resume.id for resume in resumes],
    )
    favorited_candidate_ids = (
        favorite_candidate_ids(
            session,
            user_id=viewer_user_id,
            candidate_ids={resume.candidate_id for resume in resumes},
        )
        if viewer_user_id is not None
        else set()
    )
    wait_estimates = estimate_pending_resume_analysis_waits(
        session,
        resumes=resumes,
    )
    score_attempts = _latest_score_attempt_by_resume(
        session,
        resume_ids=[resume.id for resume in resumes],
    )
    score_task_states = _active_score_task_states(
        session,
        resume_ids=[resume.id for resume in resumes],
    )
    items: list[ResumeLibraryItem] = []
    for resume in resumes:
        highest_education = _highest_education(resume)
        summary = _current_summary(resume)
        score = _latest_current_score(resume)
        ai_status, ai_error = ai_extraction_state(resume)
        candidate_name_status, candidate_name_error = candidate_name_extraction_state(
            resume
        )
        summary_status, summary_error = summary_generation_state(resume)
        wait_estimate = wait_estimates.get(resume.id)
        score_attempt = score_attempts.get(resume.id)
        items.append(
            ResumeLibraryItem(
                resume_id=resume.id,
                candidate_id=resume.candidate_id,
                display_name=resume.candidate.display_name,
                original_filename=resume.original_filename,
                is_favorited=resume.candidate_id in favorited_candidate_ids,
                created_at=_isoformat(resume.created_at),
                extraction_status=resume.extraction_status,
                ai_extraction_status=ai_status,
                ai_extraction_error=ai_error,
                candidate_name_extraction_status=candidate_name_status,
                candidate_name_extraction_error=candidate_name_error,
                analysis_wait_estimate=(
                    ResumeAnalysisWaitEstimateResponse(
                        target=wait_estimate.target,
                        phase=wait_estimate.phase,
                        state=wait_estimate.state,
                        estimated_min_seconds=wait_estimate.estimated_min_seconds,
                        estimated_max_seconds=wait_estimate.estimated_max_seconds,
                        confidence=wait_estimate.confidence,
                    )
                    if wait_estimate is not None
                    else None
                ),
                ai_summary_status=summary_status,
                ai_summary_error=summary_error,
                is_active=resume.is_active,
                ingestion_source_type=resume.ingestion_source_type,
                source_mailbox_config_id=resume.source_mailbox_config_id,
                source_mailbox_label=resume.source_mailbox_label_snapshot,
                source_tags=source_tags_by_resume.get(resume.id, []),
                quality_flags=resume.quality_flags or [],
                graduation_month=(
                    highest_education.end_month if highest_education is not None else None
                ),
                employment_months=resume.employment_months,
                employment_or_internship_months=resume.employment_or_internship_months,
                education_school=(
                    highest_education.school_name_raw
                    if highest_education is not None
                    else None
                ),
                highest_degree=(
                    highest_education.degree
                    if highest_education is not None
                    else resume.highest_degree
                ),
                summary_preview=_summary_preview(summary.content) if summary else None,
                summary_created_at=_isoformat(summary.created_at) if summary else None,
                score_total=score.total_score if score else None,
                score_status=score.status if score else None,
                score_template_name=score.template.name if score and score.template else None,
                score_created_at=_isoformat(score.created_at) if score else None,
                latest_score_status=(
                    score_attempt.status if score_attempt is not None else None
                ),
                score_retryable=(
                    score_attempt is not None and score_attempt.status == ITEM_FAILED
                ),
                score_task_state=score_task_states.get(resume.id, "none"),
            )
        )
    status_counts = _status_tone_counts(session, all_resumes)
    return ResumeLibraryResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        status_counts=status_counts,
        all_total=len(all_resumes),
    )


__all__ = ["list_resume_library"]
