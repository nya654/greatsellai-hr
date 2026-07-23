"""Confirmation-first AI talent-search profiles.

The service deliberately separates three moments that used to be conflated by
the recruiting Agent: drafting a search plan, an HR confirming that plan, and
running deterministic recall plus evidence-grounded semantic matching.  A
browser cannot supply a candidate set or bypass a confirmed hard-filter
snapshot.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import AppSettings
from app.models import (
    JobMatch,
    JobMatchBatch,
    JobMatchBatchItem,
    JobMatchRequirementResult,
    JobVersion,
    Resume,
    TalentSearchProfile,
    TalentSearchProfileRevision,
    TalentSearchRun,
)
from app.schemas import (
    CandidateSearchRequest,
    CandidateSearchResponse,
    EducationFilter,
    JobMatchRequirementResponse,
    TalentSearchHardFilters,
    TalentSearchProfileConfirmRequest,
    TalentSearchProfileGenerateRequest,
    TalentSearchProfileRefineRequest,
    TalentSearchProfileResponse,
    TalentSearchProfileRevisionResponse,
    TalentSearchProfileRunRequest,
    TalentSearchProfileSearchRequest,
    TalentSearchProfileMatchResult,
    TalentSearchRunResponse,
)
from app.services.ai_gateway_service import (
    AiExecutionSpec,
    AiGatewayError,
    ai_gateway_credentials_configured,
    ai_gateway_execution,
    gateway_prompt_transport_arguments,
)
from app.services.deepseek_provider import (
    DeepSeekProviderError,
    generate_talent_search_profile,
)
from app.services.job_match_batch_service import enqueue_job_version_match_batch
from app.services.job_service import (
    JobServiceError,
    classify_job_match_lane,
    create_talent_search_match_job_version,
    derive_job_match_score,
)
from app.services.search_service import SearchValidationError, search_candidates


class TalentSearchProfileServiceError(RuntimeError):
    """Stable, non-sensitive profile workflow errors."""


class TalentSearchProfileNotFoundError(TalentSearchProfileServiceError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _require_ai_gateway_credentials(settings: AppSettings) -> None:
    if not ai_gateway_credentials_configured(settings):
        raise TalentSearchProfileServiceError("deepseek_api_key_not_configured")


def _current_revision(
    session: Session,
    *,
    profile: TalentSearchProfile,
) -> TalentSearchProfileRevision:
    revision = session.scalar(
        select(TalentSearchProfileRevision).where(
            TalentSearchProfileRevision.profile_id == profile.id,
            TalentSearchProfileRevision.revision_number
            == profile.current_revision_number,
        )
    )
    if revision is None:
        raise TalentSearchProfileServiceError("talent_search_profile_revision_missing")
    return revision


def _current_displayed_revision(
    session: Session,
    *,
    profile: TalentSearchProfile,
    expected_revision_id: str,
) -> TalentSearchProfileRevision:
    """Return only the revision the recruiter explicitly reviewed.

    A profile can be open in more than one browser tab.  Without this check,
    one tab could confirm or run a newer AI revision created by another tab.
    """

    revision = _current_revision(session, profile=profile)
    if revision.id != expected_revision_id:
        raise TalentSearchProfileServiceError("talent_search_profile_revision_not_current")
    return revision


def _profile_or_not_found(
    session: Session,
    *,
    profile_id: str,
    for_update: bool = False,
) -> TalentSearchProfile:
    statement = select(TalentSearchProfile).where(TalentSearchProfile.id == profile_id)
    if for_update:
        # Postgres serializes confirm/refine/start for one profile. SQLite
        # safely ignores this clause in local tests, while the explicit
        # revision token still protects stale browser actions everywhere.
        statement = statement.with_for_update()
    profile = session.scalar(statement)
    if profile is None:
        # Keep tenant and object existence indistinguishable to callers.
        raise TalentSearchProfileNotFoundError("talent_search_profile_not_found")
    return profile


def _revision_response(
    revision: TalentSearchProfileRevision,
) -> TalentSearchProfileRevisionResponse:
    try:
        hard_filters = TalentSearchHardFilters.model_validate(revision.hard_filters or {})
    except ValueError as exc:  # Defensive guard for historical malformed rows.
        raise TalentSearchProfileServiceError("talent_search_profile_revision_invalid") from exc
    return TalentSearchProfileRevisionResponse(
        revision_id=revision.id,
        revision_number=revision.revision_number,
        source=revision.source,
        status=revision.status,
        title=revision.title,
        summary=revision.summary,
        hard_filters=hard_filters,
        verification_requirements=revision.verification_requirements or [],
        preferred_requirements=revision.preferred_requirements or [],
        aliases=revision.aliases or [],
        clarifying_questions=revision.clarifying_questions or [],
        created_at=revision.created_at.isoformat(),
        confirmed_at=(revision.confirmed_at.isoformat() if revision.confirmed_at else None),
    )


def _profile_response(
    session: Session,
    *,
    profile: TalentSearchProfile,
) -> TalentSearchProfileResponse:
    return TalentSearchProfileResponse(
        profile_id=profile.id,
        source_type=profile.source_type,
        source_job_version_id=profile.source_job_version_id,
        original_request=profile.original_request,
        status=profile.status,
        current_revision=_revision_response(_current_revision(session, profile=profile)),
        created_at=profile.created_at.isoformat(),
        updated_at=profile.updated_at.isoformat(),
    )


def _normal_source_job_version(
    session: Session,
    *,
    job_version_id: str | None,
) -> JobVersion | None:
    if job_version_id is None:
        return None
    job_version = session.get(JobVersion, job_version_id)
    if job_version is None or job_version.job.kind != "job":
        raise TalentSearchProfileNotFoundError("job_version_not_found")
    return job_version


def _generate_profile_payload(
    session: Session,
    *,
    settings: AppSettings,
    profile_id: str,
    actor_user_id: str | None,
    request_message: str,
    source_job_version: JobVersion | None,
    previous_revision: TalentSearchProfileRevision | None,
) -> dict[str, object]:
    _require_ai_gateway_credentials(settings)
    api_key, model, timeout_seconds = gateway_prompt_transport_arguments(settings)
    previous_profile: dict[str, object] | None = None
    if previous_revision is not None:
        previous_profile = {
            "title": previous_revision.title,
            "summary": previous_revision.summary,
            "hard_filters": previous_revision.hard_filters or {},
            "verification_requirements": previous_revision.verification_requirements or [],
            "preferred_requirements": previous_revision.preferred_requirements or [],
            "aliases": previous_revision.aliases or [],
            "clarifying_questions": previous_revision.clarifying_questions or [],
        }
    try:
        with ai_gateway_execution(
            session,
            settings=settings,
            spec=AiExecutionSpec(
                feature="talent_search_profile",
                business_ref_type="talent_search_profile",
                business_ref_id=profile_id,
                actor_user_id=actor_user_id,
                contract_version="talent_search_profile.v1",
            ),
        ):
            return generate_talent_search_profile(
                api_key=api_key,
                model=model,
                timeout_seconds=timeout_seconds,
                request_message=request_message,
                source_job_text=(source_job_version.raw_text if source_job_version else None),
                previous_profile=previous_profile,
            )
    except AiGatewayError as exc:
        raise TalentSearchProfileServiceError(str(exc)) from exc


def _new_revision(
    *,
    profile: TalentSearchProfile,
    source: str,
    revision_number: int,
    generated: Mapping[str, object],
) -> TalentSearchProfileRevision:
    return TalentSearchProfileRevision(
        profile_id=profile.id,
        revision_number=revision_number,
        source=source,
        status="draft",
        title=str(generated["title"]),
        summary=str(generated["summary"]),
        hard_filters=dict(generated["hard_filters"]),
        verification_requirements=list(generated["verification_requirements"]),
        preferred_requirements=list(generated["preferred_requirements"]),
        aliases=list(generated["aliases"]),
        clarifying_questions=list(generated["clarifying_questions"]),
        model_name="gateway-managed",
    )


def generate_profile(
    session: Session,
    *,
    payload: TalentSearchProfileGenerateRequest,
    settings: AppSettings,
    actor_user_id: str | None,
) -> TalentSearchProfileResponse:
    """Generate a draft only. No recall, no candidate access, no matching."""

    source_job_version = _normal_source_job_version(
        session,
        job_version_id=payload.job_version_id,
    )
    profile_id = str(uuid4())
    generated = _generate_profile_payload(
        session,
        settings=settings,
        profile_id=profile_id,
        actor_user_id=actor_user_id,
        request_message=payload.message,
        source_job_version=source_job_version,
        previous_revision=None,
    )
    profile = TalentSearchProfile(
        id=profile_id,
        title=str(generated["title"]),
        source_type="job" if source_job_version is not None else "freeform",
        source_job_version_id=(source_job_version.id if source_job_version else None),
        original_request=payload.message,
        status="draft",
        current_revision_number=1,
        created_by_user_id=actor_user_id,
    )
    session.add(profile)
    revision = _new_revision(
        profile=profile,
        source="ai_generated",
        revision_number=1,
        generated=generated,
    )
    session.add(revision)
    session.flush()
    return _profile_response(session, profile=profile)


def refine_profile(
    session: Session,
    *,
    profile_id: str,
    payload: TalentSearchProfileRefineRequest,
    settings: AppSettings,
    actor_user_id: str | None,
) -> TalentSearchProfileResponse:
    """Create a new draft revision without overwriting HR's prior draft."""

    profile = _profile_or_not_found(session, profile_id=profile_id, for_update=True)
    current = _current_displayed_revision(
        session,
        profile=profile,
        expected_revision_id=payload.revision_id,
    )
    if current.status == "superseded":
        raise TalentSearchProfileServiceError("talent_search_profile_revision_superseded")
    source_job_version = _normal_source_job_version(
        session,
        job_version_id=profile.source_job_version_id,
    )
    generated = _generate_profile_payload(
        session,
        settings=settings,
        profile_id=profile.id,
        actor_user_id=actor_user_id,
        request_message=payload.message,
        source_job_version=source_job_version,
        previous_revision=current,
    )
    current.status = "superseded"
    profile.status = "draft"
    profile.current_revision_number += 1
    profile.title = str(generated["title"])
    revision = _new_revision(
        profile=profile,
        source="ai_refined",
        revision_number=profile.current_revision_number,
        generated=generated,
    )
    session.add(revision)
    session.flush()
    return _profile_response(session, profile=profile)


def confirm_profile(
    session: Session,
    *,
    profile_id: str,
    payload: TalentSearchProfileConfirmRequest,
    actor_user_id: str | None,
) -> TalentSearchProfileResponse:
    """Freeze the current draft and create its private semantic-match target."""

    profile = _profile_or_not_found(session, profile_id=profile_id, for_update=True)
    revision = _current_displayed_revision(
        session,
        profile=profile,
        expected_revision_id=payload.revision_id,
    )
    if revision.status != "draft" or profile.status != "draft":
        raise TalentSearchProfileServiceError("talent_search_profile_not_draft")
    match_version = create_talent_search_match_job_version(
        session,
        title=revision.title,
        verification_requirements=revision.verification_requirements or [],
        preferred_requirements=revision.preferred_requirements or [],
    )
    revision.match_job_version_id = match_version.id if match_version else None
    revision.status = "confirmed"
    revision.confirmed_at = _utcnow()
    revision.confirmed_by_user_id = actor_user_id
    profile.status = "confirmed"
    profile.confirmed_revision_number = revision.revision_number
    session.flush()
    return _profile_response(session, profile=profile)


def _search_request_from_hard_filters(
    hard_filters: TalentSearchHardFilters,
    *,
    limit: int,
    cursor: str | None,
) -> CandidateSearchRequest:
    education_any_of = (
        [
            EducationFilter(
                institution_classifications_any_of=(
                    hard_filters.institution_classifications_any_of
                )
            )
        ]
        if hard_filters.institution_classifications_any_of
        else []
    )
    return CandidateSearchRequest(
        highest_degree_in=hard_filters.highest_degree_in,
        graduation_status=hard_filters.graduation_status,
        fresh_graduate_start_month=hard_filters.fresh_graduate_start_month,
        fresh_graduate_end_month=hard_filters.fresh_graduate_end_month,
        min_employment_months=hard_filters.min_employment_months,
        min_employment_or_internship_months=(
            hard_filters.min_employment_or_internship_months
        ),
        experience_types_all_of=hard_filters.experience_types_all_of,
        education_any_of=education_any_of,
        skills_all_of=hard_filters.skills_all_of,
        language_credentials_all_of=hard_filters.language_credentials_all_of,
        limit=limit,
        cursor=cursor,
    )


def _recall_all_matching_resume_ids(
    session: Session,
    *,
    hard_filters: TalentSearchHardFilters,
) -> list[str]:
    cursor: str | None = None
    recalled: list[str] = []
    seen: set[str] = set()
    while True:
        response = search_candidates(
            session,
            _search_request_from_hard_filters(
                hard_filters,
                limit=100,
                cursor=cursor,
            ),
        )
        for item in response.items:
            if item.resume_id not in seen:
                seen.add(item.resume_id)
                recalled.append(item.resume_id)
        if response.next_cursor is None:
            return recalled
        cursor = response.next_cursor


def _candidate_recall_response(
    session: Session,
    *,
    run: TalentSearchRun,
    limit: int,
    cursor: str | None,
) -> CandidateSearchResponse:
    try:
        hard_filters = TalentSearchHardFilters.model_validate(run.hard_filter_snapshot or {})
    except ValueError as exc:
        raise TalentSearchProfileServiceError("talent_search_run_snapshot_invalid") from exc
    try:
        return search_candidates(
            session,
            _search_request_from_hard_filters(
                hard_filters,
                limit=limit,
                cursor=cursor,
            ),
            resume_ids=set(run.recalled_resume_ids or []),
        )
    except SearchValidationError as exc:
        # A cursor is only pagination state; never leak low-level parser
        # details or turn a bad browser token into a 500.
        raise TalentSearchProfileServiceError("talent_search_profile_invalid_cursor") from exc


def _run_status(run: TalentSearchRun, batch: JobMatchBatch | None) -> str:
    if batch is not None and batch.status in {"queued", "running", "completed", "partial"}:
        return batch.status
    return run.status if run.status in {"queued", "running", "completed", "partial"} else "completed"


def _profile_match_result(match: JobMatch) -> TalentSearchProfileMatchResult:
    """Serialize an internal match without leaking its hidden JD carrier."""

    confidence = match.evidence_coverage
    return TalentSearchProfileMatchResult(
        match_id=match.id,
        resume_id=match.resume_id,
        candidate_id=match.resume.candidate_id,
        candidate_display_name=(
            match.resume.candidate.display_name
            if match.resume.candidate is not None
            else None
        ),
        facts_version=match.facts_version,
        match_score=derive_job_match_score(
            total_score=match.total_score,
            evidence_coverage=confidence,
        ),
        match_confidence=confidence,
        match_lane=classify_job_match_lane(
            hard_requirement_status=match.hard_requirement_status,
            match_confidence=confidence,
        ),
        hard_requirement_status=match.hard_requirement_status,
        analysis=match.analysis or {},
        requirement_results=[
            JobMatchRequirementResponse(
                requirement_id=result.requirement_id,
                requirement_key=result.requirement.requirement_key,
                priority=result.requirement.priority,
                requirement_text=result.requirement.raw_requirement,
                clause_ids=result.requirement.clause_ids or [],
                outcome=result.outcome,
                reason=result.reason,
                fact_ids=result.fact_ids or [],
                missing_or_uncertain=result.missing_or_uncertain,
                score_contribution=result.score_contribution,
            )
            for result in sorted(
                match.requirement_results,
                key=lambda item: item.requirement.sort_order,
            )
        ],
        status=match.status,
        created_at=match.created_at.isoformat(),
    )


def _profile_match_results(
    session: Session,
    *,
    batch: JobMatchBatch | None,
) -> list[TalentSearchProfileMatchResult]:
    """Return only successfully materialized results from this one batch."""

    if batch is None:
        return []
    items = session.scalars(
        select(JobMatchBatchItem)
        .where(JobMatchBatchItem.batch_id == batch.id)
        .options(
            selectinload(JobMatchBatchItem.job_match)
            .selectinload(JobMatch.resume)
            .selectinload(Resume.candidate),
            selectinload(JobMatchBatchItem.job_match)
            .selectinload(JobMatch.requirement_results)
            .selectinload(JobMatchRequirementResult.requirement),
        )
    ).all()
    matches = [item.job_match for item in items if item.job_match is not None]
    matches.sort(
        key=lambda match: (
            {"recommended": 0, "pending": 1, "unmet": 2}[
                classify_job_match_lane(
                    hard_requirement_status=match.hard_requirement_status,
                    match_confidence=match.evidence_coverage,
                )
            ],
            -derive_job_match_score(
                total_score=match.total_score,
                evidence_coverage=match.evidence_coverage,
            ),
            -(match.evidence_coverage or 0.0),
            match.id,
        )
    )
    return [_profile_match_result(match) for match in matches]


def _run_response(
    session: Session,
    *,
    run: TalentSearchRun,
    limit: int,
    cursor: str | None,
) -> TalentSearchRunResponse:
    batch = session.get(JobMatchBatch, run.job_match_batch_id) if run.job_match_batch_id else None
    return TalentSearchRunResponse(
        run_id=run.id,
        profile_id=run.profile_id,
        revision_id=run.revision_id,
        status=_run_status(run, batch),
        total_recalled_count=run.total_recalled_count,
        job_match_batch_id=run.job_match_batch_id,
        match_total_count=batch.total_count if batch is not None else 0,
        match_completed_count=batch.completed_count if batch is not None else 0,
        match_failed_count=batch.failed_count if batch is not None else 0,
        match_results=_profile_match_results(session, batch=batch),
        created_at=run.created_at.isoformat(),
        updated_at=run.updated_at.isoformat(),
        candidate_recall=_candidate_recall_response(
            session,
            run=run,
            limit=limit,
            cursor=cursor,
        ),
    )


def _existing_run_for_revision(
    session: Session,
    *,
    revision: TalentSearchProfileRevision,
) -> TalentSearchRun | None:
    runs = session.scalars(
        select(TalentSearchRun)
        .where(
            TalentSearchRun.revision_id == revision.id,
        )
        .order_by(TalentSearchRun.created_at.desc())
    ).all()
    for run in runs:
        batch = session.get(JobMatchBatch, run.job_match_batch_id) if run.job_match_batch_id else None
        status = _run_status(run, batch)
        if run.status != status:
            run.status = status
        # A confirmed revision has one durable search execution. Returning a
        # completed run as well prevents a double click or page reload from
        # silently spending another N×M AI batch. A future explicit rerun can
        # create a new revision instead of mutating this audit record.
        return run
    return None


def start_profile_search(
    session: Session,
    *,
    profile_id: str,
    payload: TalentSearchProfileRunRequest,
    settings: AppSettings,
) -> TalentSearchRunResponse:
    """Recall from the frozen profile, then queue semantic matching for that set."""

    profile = _profile_or_not_found(session, profile_id=profile_id, for_update=True)
    revision = _current_displayed_revision(
        session,
        profile=profile,
        expected_revision_id=payload.revision_id,
    )
    if (
        profile.status != "confirmed"
        or revision.status != "confirmed"
        or profile.confirmed_revision_number != revision.revision_number
    ):
        raise TalentSearchProfileServiceError("talent_search_profile_not_confirmed")
    existing_run = _existing_run_for_revision(session, revision=revision)
    if existing_run is not None:
        return _run_response(
            session,
            run=existing_run,
            limit=payload.limit,
            cursor=payload.cursor,
        )
    try:
        hard_filters = TalentSearchHardFilters.model_validate(revision.hard_filters or {})
    except ValueError as exc:
        raise TalentSearchProfileServiceError("talent_search_profile_revision_invalid") from exc
    recalled_resume_ids = _recall_all_matching_resume_ids(
        session,
        hard_filters=hard_filters,
    )
    run = TalentSearchRun(
        profile_id=profile.id,
        revision_id=revision.id,
        hard_filter_snapshot=hard_filters.model_dump(mode="json"),
        recalled_resume_ids=recalled_resume_ids,
        status="completed",
        total_recalled_count=len(recalled_resume_ids),
    )
    session.add(run)
    session.flush()
    if revision.match_job_version_id and recalled_resume_ids:
        match_version = session.get(JobVersion, revision.match_job_version_id)
        if (
            match_version is None
            or match_version.organization_id != profile.organization_id
            or match_version.job.kind != "talent_search_profile"
        ):
            raise TalentSearchProfileServiceError("talent_search_profile_match_target_invalid")
        batch = enqueue_job_version_match_batch(
            session,
            job_version_id=revision.match_job_version_id,
            settings=settings,
            resume_ids=recalled_resume_ids,
            allow_internal_job=True,
        )
        run.job_match_batch_id = batch.batch_id
        run.status = batch.status
    session.flush()
    return _run_response(
        session,
        run=run,
        limit=payload.limit,
        cursor=payload.cursor,
    )


def get_profile(session: Session, *, profile_id: str) -> TalentSearchProfileResponse:
    return _profile_response(session, profile=_profile_or_not_found(session, profile_id=profile_id))


def list_profiles(
    session: Session,
    *,
    limit: int = 12,
) -> list[TalentSearchProfileResponse]:
    """Return recent profile drafts/runs for drawer recovery after reload."""

    profiles = session.scalars(
        select(TalentSearchProfile)
        .order_by(TalentSearchProfile.updated_at.desc(), TalentSearchProfile.id.desc())
        .limit(limit)
    ).all()
    return [_profile_response(session, profile=profile) for profile in profiles]


def get_profile_run(
    session: Session,
    *,
    profile_id: str,
    run_id: str,
    payload: TalentSearchProfileSearchRequest,
) -> TalentSearchRunResponse:
    _profile_or_not_found(session, profile_id=profile_id)
    run = session.get(TalentSearchRun, run_id)
    if run is None or run.profile_id != profile_id:
        raise TalentSearchProfileNotFoundError("talent_search_run_not_found")
    return _run_response(session, run=run, limit=payload.limit, cursor=payload.cursor)


__all__ = [
    "DeepSeekProviderError",
    "JobServiceError",
    "TalentSearchProfileNotFoundError",
    "TalentSearchProfileServiceError",
    "confirm_profile",
    "generate_profile",
    "get_profile",
    "get_profile_run",
    "list_profiles",
    "refine_profile",
    "start_profile_search",
]
