from __future__ import annotations

import hashlib
import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware

from app.config import AppSettings
from app.database import Database, get_session
from app.models import Candidate, Resume
from app.schemas import (
    AuthLogin,
    AuthSession,
    CandidateCreate,
    CandidateCreated,
    CandidateSearchRequest,
    CandidateSearchResponse,
    JobCreate,
    JobMatchBatchResponse,
    JobMatchCreate,
    JobMatchResponse,
    JobVersionRequirementsUpdate,
    JobVersionResponse,
    ResumeDetail,
    ResumeActivateRequest,
    ResumeFactsSaveRequest,
    ResumeReviewActionResponse,
    ResumeReviewDetail,
    ResumeSourceBlockResponse,
    ResumeEducationResponse,
    ResumeExperienceDetailResponse,
    ResumeExperienceResponse,
    ResumeReviewQueueItem,
    ResumeReviewQueueResponse,
    ResumeLibraryResponse,
    ResumeSkillResponse,
    ResumeUploadResponse,
    RecruitingAgentRequest,
    RecruitingAgentResponse,
    ResumeScoreCreate,
    ResumeScoreOverride,
    ResumeScoreResponse,
    ResumeSummaryManualCreate,
    ResumeSummaryResponse,
    SavedFilterCreate,
    SavedFilterResponse,
    ScoreTemplateCreate,
    ScoreTemplateResponse,
)
from app.services.institution_service import (
    is_institution_registry_seeded,
    seed_institution_registry,
)
from app.services.ai_extraction_job_service import (
    AiExtractionJobError,
    ai_extraction_state,
    enqueue_uploaded_resume_ai_extraction,
    request_resume_ai_extraction,
)
from app.services.resume_service import (
    FactValidationError,
    IdempotencyConflictError,
    NotFoundError,
    ResumeServiceError,
    UploadValidationError,
    activate_ready_resume,
    create_candidate,
    discard_uploaded_pdf,
    get_idempotent_upload_resume,
    get_resume,
    normalize_upload_idempotency_key,
    reconcile_legacy_completed_ai_resumes,
    register_upload_idempotency_key,
    save_facts,
    save_pdf_resume,
    validate_pdf_resume_upload,
)
from app.services.saved_filter_service import (
    SavedFilterNotFoundError,
    create_saved_filter,
    delete_saved_filter,
    list_saved_filters,
)
from app.services.search_service import SearchValidationError, search_candidates
from app.services.resume_library_service import list_resume_library
from app.services.recruiting_agent_service import (
    RecruitingAgentServiceError,
    run_recruiting_agent_turn,
)
from app.services.score_service import (
    DeepSeekProviderError,
    ResumeScoreNotFoundError,
    ScoreServiceError,
    ScoreTemplateNotFoundError,
    create_score_template,
    get_resume_score,
    list_score_templates,
    list_resume_scores,
    override_score_dimension,
    run_resume_score,
)
from app.services.summary_service import (
    DeepSeekProviderError as SummaryDeepSeekProviderError,
    ResumeSummaryNotFoundError,
    SummaryServiceError,
    create_manual_summary_version,
    generate_resume_summary,
    get_resume_summary,
    list_resume_summaries,
)
from app.services.job_service import (
    DeepSeekProviderError as JobDeepSeekProviderError,
    JobMatchNotFoundError,
    JobNotFoundError,
    JobServiceError,
    JobVersionNotFoundError,
    confirm_job_version,
    create_job,
    create_job_version,
    extract_job_version_requirements,
    get_job_match,
    get_latest_confirmed_job_version,
    get_job_version,
    list_confirmed_job_versions,
    list_job_version_matches,
    list_job_versions,
    list_resume_job_matches,
    run_job_match,
    update_job_version_requirements,
)
from app.services.job_match_batch_service import (
    enqueue_job_version_match_batch,
    get_job_match_batch,
)


def _resume_detail(resume: object) -> ResumeDetail:
    ai_extraction_status, ai_extraction_error = ai_extraction_state(resume)
    return ResumeDetail(
        resume_id=resume.id,
        candidate_id=resume.candidate_id,
        candidate_display_name=resume.candidate.display_name,
        extraction_status=resume.extraction_status,
        ai_extraction_status=ai_extraction_status,
        ai_extraction_error=ai_extraction_error,
        is_active=resume.is_active,
        is_985_211=resume.is_985_211,
        highest_degree=resume.highest_degree,
        employment_months=resume.employment_months,
        employment_or_internship_months=resume.employment_or_internship_months,
        source_page_count=resume.source_page_count,
        parsed_page_count=resume.parsed_page_count,
        quality_flags=resume.quality_flags or [],
    )


def _resume_upload_response(resume: object) -> ResumeUploadResponse:
    ai_extraction_status, ai_extraction_error = ai_extraction_state(resume)
    return ResumeUploadResponse(
        resume_id=resume.id,
        candidate_id=resume.candidate_id,
        candidate_display_name=resume.candidate.display_name,
        extraction_status=resume.extraction_status,
        ai_extraction_status=ai_extraction_status,
        ai_extraction_error=ai_extraction_error,
        source_page_count=resume.source_page_count,
        parsed_page_count=resume.parsed_page_count,
        quality_flags=resume.quality_flags or [],
    )


def _resume_original_pdf_path(*, settings: AppSettings, storage_key: str) -> Path:
    """Resolve an uploaded resume only when it remains inside the upload root."""

    try:
        upload_root = settings.upload_dir.resolve()
        source_path = (upload_root / storage_key).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="resume_original_file_not_found",
        ) from exc

    if (
        source_path.parent != upload_root
        or source_path.suffix.lower() != ".pdf"
        or not source_path.is_file()
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="resume_original_file_not_found",
        )
    return source_path


def _commit_or_raise(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="database_conflict",
        ) from exc


def _raise_job_service_error(exc: JobServiceError) -> None:
    """Translate predictable JD workflow failures into stable HTTP results."""

    code = str(exc)
    if code in {"resume_not_found"}:
        response_status = status.HTTP_404_NOT_FOUND
    elif code == "deepseek_api_key_not_configured":
        response_status = status.HTTP_503_SERVICE_UNAVAILABLE
    elif code in {
        "jd_text_has_no_clauses",
        "job_requirement_clause_not_found",
        "job_requirement_not_grounded_in_clauses",
        "job_requirement_not_grounded_in_jd",
        "job_requirement_keys_must_be_unique",
    }:
        response_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    else:
        response_status = status.HTTP_409_CONFLICT
    raise HTTPException(status_code=response_status, detail=code) from exc


def _resume_review_detail(resume: object) -> ResumeReviewDetail:
    base = _resume_detail(resume)
    return ResumeReviewDetail(
        **base.model_dump(),
        original_filename=resume.original_filename,
        facts_version=resume.facts_version,
        source_blocks=[
            ResumeSourceBlockResponse(
                block_id=block.block_id,
                page_no=block.page_no,
                block_type=block.block_type,
                text=block.text,
            )
            for block in sorted(
                resume.source_blocks,
                key=lambda block: (block.page_no, block.block_id),
            )
        ],
        education=[
            ResumeEducationResponse(
                school_name_raw=education.school_name_raw,
                school_match_state=education.school_match_state,
                degree=education.degree,
                major_raw=education.major_raw,
                start_month=education.start_month,
                end_month=education.end_month,
                evidence_block_ids=education.evidence_block_ids or [],
            )
            for education in resume.educations
        ],
        experiences=[
            ResumeExperienceResponse(
                experience_type=experience.experience_type,
                experience_name_raw=experience.experience_name_raw,
                organization_name_raw=experience.organization_name_raw,
                title_raw=experience.title_raw,
                start_month=experience.start_month,
                end_month=experience.end_month,
                is_current=experience.is_current,
                evidence_block_ids=experience.evidence_block_ids or [],
                classification_evidence_block_ids=(
                    experience.classification_evidence_block_ids or []
                ),
                detail_items=[
                    ResumeExperienceDetailResponse(
                        detail_raw=item["detail_raw"],
                        evidence_block_ids=item["evidence_block_ids"],
                    )
                    for item in (experience.detail_items or [])
                    if isinstance(item, dict)
                    and isinstance(item.get("detail_raw"), str)
                    and isinstance(item.get("evidence_block_ids"), list)
                ],
            )
            for experience in resume.experiences
        ],
        skills=[
            ResumeSkillResponse(
                skill_display=skill.skill_display,
                evidence_block_ids=skill.evidence_block_ids or [],
            )
            for skill in resume.skills
        ],
        review_actions=[
            ResumeReviewActionResponse(
                action=action.action,
                actor=action.actor,
                note=action.note,
                created_at=action.created_at.isoformat(),
            )
            for action in sorted(
                resume.review_actions,
                key=lambda action: (action.created_at, action.id),
                reverse=True,
            )
        ],
    )


async def require_single_admin(
    request: Request,
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    settings: AppSettings = request.app.state.settings
    if settings.allow_unauthenticated:
        return
    if request.session.get("resume_v3_authenticated") is True:
        return
    if not settings.admin_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="server_missing_admin_token",
        )
    if x_admin_token is None or not hmac.compare_digest(
        x_admin_token,
        settings.admin_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_admin_token",
        )


def create_app(settings_override: AppSettings | None = None) -> FastAPI:
    settings = settings_override or AppSettings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.validate_runtime()
        settings.ensure_directories()
        database = Database(
            settings.database_url,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
        )
        if settings.auto_create_schema:
            database.create_all()
        with database.session_factory() as session:
            if settings.seed_registry_on_startup:
                seed_institution_registry(session)
            elif not is_institution_registry_seeded(session):
                raise RuntimeError("institution_registry_not_seeded")
            reconcile_legacy_completed_ai_resumes(session)
            session.commit()
        app.state.settings = settings
        app.state.database = database
        try:
            yield
        finally:
            database.dispose()

    app = FastAPI(
        title="Resume Screening V3",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        SessionMiddleware,
        # The fallback only serves explicitly unauthenticated local workspaces.
        # Production validation requires an independently configured secret.
        secret_key=settings.session_secret or settings.admin_token or "resume-v3-development-session",
        session_cookie="resume_v3_session",
        max_age=60 * 60 * 12,
        same_site="strict",
        https_only=settings.session_cookie_secure,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/auth/session", response_model=AuthSession)
    async def get_auth_session(request: Request) -> AuthSession:
        return AuthSession(
            authenticated=(
                settings.allow_unauthenticated
                or request.session.get("resume_v3_authenticated") is True
            ),
            login_required=not settings.allow_unauthenticated,
        )

    @app.post("/v1/auth/login", response_model=AuthSession)
    async def post_auth_login(payload: AuthLogin, request: Request) -> AuthSession:
        if settings.allow_unauthenticated:
            request.session["resume_v3_authenticated"] = True
            return AuthSession(authenticated=True, login_required=False)
        if not settings.admin_token:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="server_missing_admin_token",
            )
        if not hmac.compare_digest(payload.password, settings.admin_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_login_credentials",
            )
        request.session.clear()
        request.session["resume_v3_authenticated"] = True
        return AuthSession(authenticated=True, login_required=True)

    @app.post("/v1/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def post_auth_logout(request: Request) -> None:
        request.session.clear()

    @app.post(
        "/v1/recruiting-agent/turns",
        response_model=RecruitingAgentResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def post_recruiting_agent_turn(
        payload: RecruitingAgentRequest,
        session: Session = Depends(get_session),
    ) -> RecruitingAgentResponse:
        """Run one bounded, tool-backed recruiter assistant turn."""

        try:
            response = run_recruiting_agent_turn(
                session,
                payload=payload,
                settings=settings,
            )
        except RecruitingAgentServiceError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
        except JobServiceError as exc:
            _raise_job_service_error(exc)
        _commit_or_raise(session)
        return response

    @app.post(
        "/v1/candidates",
        response_model=CandidateCreated,
        dependencies=[Depends(require_single_admin)],
    )
    def post_candidate(
        payload: CandidateCreate,
        session: Session = Depends(get_session),
    ) -> CandidateCreated:
        candidate = create_candidate(session, display_name=payload.display_name)
        _commit_or_raise(session)
        return CandidateCreated(candidate_id=candidate.id)

    @app.post(
        "/v1/candidates/{candidate_id}/resumes",
        response_model=ResumeUploadResponse,
        dependencies=[Depends(require_single_admin)],
    )
    async def post_resume(
        candidate_id: str,
        file: UploadFile = File(...),
        session: Session = Depends(get_session),
    ) -> ResumeUploadResponse:
        if file.content_type and file.content_type not in {
            "application/pdf",
            "application/octet-stream",
        }:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="content_type_must_be_pdf",
            )
        content = await file.read(settings.max_upload_bytes + 1)
        storage_key: str | None = None
        try:
            resume = save_pdf_resume(
                session,
                candidate_id=candidate_id,
                original_filename=file.filename,
                content=content,
                settings=settings,
            )
            storage_key = resume.storage_key
            enqueue_uploaded_resume_ai_extraction(
                session,
                resume=resume,
                settings=settings,
            )
            _commit_or_raise(session)
        except NotFoundError as exc:
            session.rollback()
            discard_uploaded_pdf(settings, storage_key=storage_key)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except UploadValidationError as exc:
            session.rollback()
            discard_uploaded_pdf(settings, storage_key=storage_key)
            response_status = (
                status.HTTP_413_CONTENT_TOO_LARGE
                if str(exc) == "file_too_large"
                else status.HTTP_422_UNPROCESSABLE_CONTENT
            )
            raise HTTPException(status_code=response_status, detail=str(exc)) from exc
        except HTTPException:
            discard_uploaded_pdf(settings, storage_key=storage_key)
            raise
        except Exception:
            session.rollback()
            discard_uploaded_pdf(settings, storage_key=storage_key)
            raise
        return _resume_upload_response(resume)

    @app.post(
        "/v1/resumes/upload",
        response_model=ResumeUploadResponse,
        dependencies=[Depends(require_single_admin)],
    )
    async def post_new_candidate_resume(
        file: UploadFile = File(...),
        idempotency_key: Annotated[
            str | None,
            Header(alias="Idempotency-Key"),
        ] = None,
        session: Session = Depends(get_session),
    ) -> ResumeUploadResponse:
        """Convenience upload flow used by the single-account web app."""

        if file.content_type and file.content_type not in {
            "application/pdf",
            "application/octet-stream",
        }:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="content_type_must_be_pdf",
            )
        try:
            normalized_idempotency_key = normalize_upload_idempotency_key(
                idempotency_key
            )
        except UploadValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        content = await file.read(settings.max_upload_bytes + 1)
        try:
            validate_pdf_resume_upload(
                original_filename=file.filename,
                content=content,
                settings=settings,
            )
        except UploadValidationError as exc:
            response_status = (
                status.HTTP_413_CONTENT_TOO_LARGE
                if str(exc) == "file_too_large"
                else status.HTTP_422_UNPROCESSABLE_CONTENT
            )
            raise HTTPException(status_code=response_status, detail=str(exc)) from exc

        content_sha256 = hashlib.sha256(content).hexdigest()
        if normalized_idempotency_key is not None:
            try:
                replayed_resume = get_idempotent_upload_resume(
                    session,
                    idempotency_key=normalized_idempotency_key,
                    content_sha256=content_sha256,
                )
            except IdempotencyConflictError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=str(exc),
                ) from exc
            if replayed_resume is not None:
                return _resume_upload_response(replayed_resume)

        storage_key: str | None = None
        try:
            # A new upload starts unnamed. The AI extraction worker may fill
            # Candidate.display_name only from source-grounded resume text.
            candidate = create_candidate(session, display_name=None)
            resume = save_pdf_resume(
                session,
                candidate_id=candidate.id,
                original_filename=file.filename,
                content=content,
                settings=settings,
            )
            storage_key = resume.storage_key
            if normalized_idempotency_key is not None:
                register_upload_idempotency_key(
                    session,
                    idempotency_key=normalized_idempotency_key,
                    content_sha256=content_sha256,
                    resume_id=resume.id,
                )
                # Surface a competing idempotency key before the transaction
                # commits, so its just-written PDF can be removed.
                session.flush()
            enqueue_uploaded_resume_ai_extraction(
                session,
                resume=resume,
                settings=settings,
            )
            session.commit()
        except UploadValidationError as exc:
            session.rollback()
            discard_uploaded_pdf(settings, storage_key=storage_key)
            response_status = (
                status.HTTP_413_CONTENT_TOO_LARGE
                if str(exc) == "file_too_large"
                else status.HTTP_422_UNPROCESSABLE_CONTENT
            )
            raise HTTPException(status_code=response_status, detail=str(exc)) from exc
        except IntegrityError as exc:
            session.rollback()
            discard_uploaded_pdf(settings, storage_key=storage_key)
            if normalized_idempotency_key is not None:
                try:
                    replayed_resume = get_idempotent_upload_resume(
                        session,
                        idempotency_key=normalized_idempotency_key,
                        content_sha256=content_sha256,
                    )
                except IdempotencyConflictError as conflict:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=str(conflict),
                    ) from conflict
                if replayed_resume is not None:
                    return _resume_upload_response(replayed_resume)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="database_conflict",
            ) from exc
        except Exception:
            session.rollback()
            discard_uploaded_pdf(settings, storage_key=storage_key)
            raise
        return _resume_upload_response(resume)

    @app.get(
        "/v1/resumes/review-queue",
        response_model=ResumeReviewQueueResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def get_resume_review_queue(
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 25,
        session: Session = Depends(get_session),
    ) -> ResumeReviewQueueResponse:
        """List pending uploads for the manual review workflow, newest first."""

        pending = Resume.is_active.is_(False)
        total = session.scalar(
            select(func.count()).select_from(Resume).where(pending)
        )
        rows = session.execute(
            select(Resume, Candidate.display_name)
            .join(Candidate, Resume.candidate_id == Candidate.id)
            .options(selectinload(Resume.ai_extraction_job))
            .where(pending)
            .order_by(Resume.created_at.desc(), Resume.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return ResumeReviewQueueResponse(
            items=[
                ResumeReviewQueueItem(
                    resume_id=resume.id,
                    candidate_id=resume.candidate_id,
                    candidate_display_name=display_name,
                    original_filename=resume.original_filename,
                    extraction_status=resume.extraction_status,
                    ai_extraction_status=ai_extraction_state(resume)[0],
                    ai_extraction_error=ai_extraction_state(resume)[1],
                    quality_flags=resume.quality_flags or [],
                    created_at=resume.created_at,
                )
                for resume, display_name in rows
            ],
            total=int(total or 0),
            page=page,
            page_size=page_size,
        )

    @app.get(
        "/v1/resumes/{resume_id}",
        response_model=ResumeDetail,
        dependencies=[Depends(require_single_admin)],
    )
    def get_resume_detail(
        resume_id: str,
        session: Session = Depends(get_session),
    ) -> ResumeDetail:
        try:
            resume = get_resume(session, resume_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return _resume_detail(resume)

    @app.get(
        "/v1/resumes/{resume_id}/review",
        response_model=ResumeReviewDetail,
        dependencies=[Depends(require_single_admin)],
    )
    def get_resume_review_detail(
        resume_id: str,
        session: Session = Depends(get_session),
    ) -> ResumeReviewDetail:
        try:
            resume = get_resume(session, resume_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return _resume_review_detail(resume)

    @app.get(
        "/v1/resumes/{resume_id}/original-file",
        response_class=FileResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def get_resume_original_file(
        resume_id: str,
        session: Session = Depends(get_session),
    ) -> FileResponse:
        try:
            resume = get_resume(session, resume_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

        source_path = _resume_original_pdf_path(
            settings=settings,
            storage_key=resume.storage_key,
        )
        return FileResponse(
            path=source_path,
            media_type="application/pdf",
            filename=resume.original_filename,
            content_disposition_type="inline",
        )

    @app.put(
        "/v1/resumes/{resume_id}/facts",
        response_model=ResumeDetail,
        dependencies=[Depends(require_single_admin)],
    )
    def put_resume_facts(
        resume_id: str,
        payload: ResumeFactsSaveRequest,
        session: Session = Depends(get_session),
    ) -> ResumeDetail:
        try:
            resume = save_facts(session, resume_id=resume_id, request=payload)
        except NotFoundError as exc:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except FactValidationError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        _commit_or_raise(session)
        return _resume_detail(resume)

    @app.post(
        "/v1/resumes/{resume_id}/activate",
        response_model=ResumeDetail,
        dependencies=[Depends(require_single_admin)],
    )
    def post_activate_resume(
        resume_id: str,
        payload: ResumeActivateRequest,
        session: Session = Depends(get_session),
    ) -> ResumeDetail:
        try:
            resume = activate_ready_resume(
                session,
                resume_id=resume_id,
                note=payload.note,
            )
        except NotFoundError as exc:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except FactValidationError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        _commit_or_raise(session)
        return _resume_detail(resume)

    @app.post(
        "/v1/resumes/{resume_id}/queue-ai-extraction",
        response_model=ResumeDetail,
        dependencies=[Depends(require_single_admin)],
    )
    def post_queue_resume_ai_extraction(
        resume_id: str,
        session: Session = Depends(get_session),
    ) -> ResumeDetail:
        try:
            resume = request_resume_ai_extraction(
                session,
                resume_id=resume_id,
                settings=settings,
            )
        except NotFoundError as exc:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AiExtractionJobError as exc:
            session.rollback()
            response_status = (
                status.HTTP_422_UNPROCESSABLE_CONTENT
                if str(exc) == "resume_has_no_native_text_for_ai_extraction"
                else status.HTTP_409_CONFLICT
            )
            raise HTTPException(status_code=response_status, detail=str(exc)) from exc
        _commit_or_raise(session)
        return _resume_detail(resume)

    @app.post(
        "/v1/resumes/{resume_id}/extract-facts",
        response_model=ResumeDetail,
        dependencies=[Depends(require_single_admin)],
        deprecated=True,
    )
    def post_extract_resume_facts_compatibility_alias(
        resume_id: str,
        session: Session = Depends(get_session),
    ) -> ResumeDetail:
        """Compatibility alias; it queues work and never calls a model inline."""

        try:
            resume = request_resume_ai_extraction(
                session,
                resume_id=resume_id,
                settings=settings,
            )
        except NotFoundError as exc:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AiExtractionJobError as exc:
            session.rollback()
            response_status = (
                status.HTTP_422_UNPROCESSABLE_CONTENT
                if str(exc) == "resume_has_no_native_text_for_ai_extraction"
                else status.HTTP_409_CONFLICT
            )
            raise HTTPException(status_code=response_status, detail=str(exc)) from exc
        _commit_or_raise(session)
        return _resume_detail(resume)

    @app.post(
        "/v1/candidates/search",
        response_model=CandidateSearchResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def post_candidate_search(
        payload: CandidateSearchRequest,
        session: Session = Depends(get_session),
    ) -> CandidateSearchResponse:
        try:
            return search_candidates(session, payload)
        except SearchValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    @app.get(
        "/v1/resume-library",
        response_model=ResumeLibraryResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def get_resume_library(
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 50,
        session: Session = Depends(get_session),
    ) -> ResumeLibraryResponse:
        return list_resume_library(session, page=page, page_size=page_size)

    @app.post(
        "/v1/saved-filters",
        response_model=SavedFilterResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def post_saved_filter(
        payload: SavedFilterCreate,
        session: Session = Depends(get_session),
    ) -> SavedFilterResponse:
        response = create_saved_filter(session, payload=payload)
        _commit_or_raise(session)
        return response

    @app.get(
        "/v1/saved-filters",
        response_model=list[SavedFilterResponse],
        dependencies=[Depends(require_single_admin)],
    )
    def get_saved_filters(
        session: Session = Depends(get_session),
    ) -> list[SavedFilterResponse]:
        return list_saved_filters(session)

    @app.delete(
        "/v1/saved-filters/{saved_filter_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_single_admin)],
    )
    def delete_saved_filter_endpoint(
        saved_filter_id: str,
        session: Session = Depends(get_session),
    ) -> None:
        try:
            delete_saved_filter(session, saved_filter_id=saved_filter_id)
        except SavedFilterNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        _commit_or_raise(session)

    @app.post(
        "/v1/score-templates",
        response_model=ScoreTemplateResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def post_score_template(
        payload: ScoreTemplateCreate,
        session: Session = Depends(get_session),
    ) -> ScoreTemplateResponse:
        response = create_score_template(session, payload=payload)
        _commit_or_raise(session)
        return response

    @app.get(
        "/v1/score-templates",
        response_model=list[ScoreTemplateResponse],
        dependencies=[Depends(require_single_admin)],
    )
    def get_score_templates(
        session: Session = Depends(get_session),
    ) -> list[ScoreTemplateResponse]:
        return list_score_templates(session)

    @app.post(
        "/v1/resumes/{resume_id}/scores",
        response_model=ResumeScoreResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def post_resume_score(
        resume_id: str,
        payload: ResumeScoreCreate,
        session: Session = Depends(get_session),
    ) -> ResumeScoreResponse:
        try:
            response = run_resume_score(
                session,
                resume_id=resume_id,
                payload=payload,
                settings=settings,
            )
        except ScoreTemplateNotFoundError as exc:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ScoreServiceError as exc:
            session.rollback()
            response_status = (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if str(exc) == "deepseek_api_key_not_configured"
                else status.HTTP_409_CONFLICT
            )
            raise HTTPException(status_code=response_status, detail=str(exc)) from exc
        except DeepSeekProviderError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="score_provider_failed",
            ) from exc
        _commit_or_raise(session)
        return response

    @app.get(
        "/v1/resume-scores/{score_id}",
        response_model=ResumeScoreResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def get_score(
        score_id: str,
        session: Session = Depends(get_session),
    ) -> ResumeScoreResponse:
        try:
            return get_resume_score(session, score_id=score_id)
        except ResumeScoreNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.get(
        "/v1/resumes/{resume_id}/scores",
        response_model=list[ResumeScoreResponse],
        dependencies=[Depends(require_single_admin)],
    )
    def get_resume_score_history(
        resume_id: str,
        session: Session = Depends(get_session),
    ) -> list[ResumeScoreResponse]:
        try:
            return list_resume_scores(session, resume_id=resume_id)
        except ScoreServiceError as exc:
            response_status = (
                status.HTTP_404_NOT_FOUND
                if str(exc) == "resume_not_found"
                else status.HTTP_409_CONFLICT
            )
            raise HTTPException(status_code=response_status, detail=str(exc)) from exc

    @app.post(
        "/v1/resume-scores/{score_id}/dimensions/{dimension_key}/override",
        response_model=ResumeScoreResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def post_score_override(
        score_id: str,
        dimension_key: str,
        payload: ResumeScoreOverride,
        session: Session = Depends(get_session),
    ) -> ResumeScoreResponse:
        try:
            response = override_score_dimension(
                session,
                score_id=score_id,
                dimension_key=dimension_key,
                payload=payload,
            )
        except ResumeScoreNotFoundError as exc:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ScoreServiceError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        _commit_or_raise(session)
        return response

    @app.post(
        "/v1/resumes/{resume_id}/summaries",
        response_model=ResumeSummaryResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def post_resume_summary(
        resume_id: str,
        session: Session = Depends(get_session),
    ) -> ResumeSummaryResponse:
        try:
            response = generate_resume_summary(
                session,
                resume_id=resume_id,
                settings=settings,
            )
        except SummaryServiceError as exc:
            session.rollback()
            response_status = (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if str(exc) == "deepseek_api_key_not_configured"
                else (
                    status.HTTP_404_NOT_FOUND
                    if str(exc) == "resume_not_found"
                    else status.HTTP_409_CONFLICT
                )
            )
            raise HTTPException(status_code=response_status, detail=str(exc)) from exc
        except SummaryDeepSeekProviderError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="summary_provider_failed",
            ) from exc
        _commit_or_raise(session)
        return response

    @app.get(
        "/v1/resume-summaries/{summary_id}",
        response_model=ResumeSummaryResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def get_summary(
        summary_id: str,
        session: Session = Depends(get_session),
    ) -> ResumeSummaryResponse:
        try:
            return get_resume_summary(session, summary_id=summary_id)
        except ResumeSummaryNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.get(
        "/v1/resumes/{resume_id}/summaries",
        response_model=list[ResumeSummaryResponse],
        dependencies=[Depends(require_single_admin)],
    )
    def get_resume_summary_versions(
        resume_id: str,
        session: Session = Depends(get_session),
    ) -> list[ResumeSummaryResponse]:
        return list_resume_summaries(session, resume_id=resume_id)

    @app.post(
        "/v1/resume-summaries/{summary_id}/manual-versions",
        response_model=ResumeSummaryResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def post_manual_summary_version(
        summary_id: str,
        payload: ResumeSummaryManualCreate,
        session: Session = Depends(get_session),
    ) -> ResumeSummaryResponse:
        try:
            response = create_manual_summary_version(
                session,
                summary_id=summary_id,
                payload=payload,
            )
        except ResumeSummaryNotFoundError as exc:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except SummaryServiceError as exc:
            session.rollback()
            response_status = (
                status.HTTP_404_NOT_FOUND
                if str(exc) == "resume_not_found"
                else status.HTTP_409_CONFLICT
            )
            raise HTTPException(status_code=response_status, detail=str(exc)) from exc
        _commit_or_raise(session)
        return response

    @app.post(
        "/v1/jobs",
        response_model=JobVersionResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def post_job(
        payload: JobCreate,
        session: Session = Depends(get_session),
    ) -> JobVersionResponse:
        """Create a new immutable JD version (draft unless requirements are supplied)."""

        try:
            response = create_job(session, payload=payload)
        except JobServiceError as exc:
            session.rollback()
            _raise_job_service_error(exc)
        _commit_or_raise(session)
        return response

    @app.post(
        "/v1/jobs/{job_id}/versions",
        response_model=JobVersionResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def post_job_version(
        job_id: str,
        payload: JobCreate,
        session: Session = Depends(get_session),
    ) -> JobVersionResponse:
        try:
            response = create_job_version(session, job_id=job_id, payload=payload)
        except JobNotFoundError as exc:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except JobServiceError as exc:
            session.rollback()
            _raise_job_service_error(exc)
        _commit_or_raise(session)
        return response

    @app.get(
        "/v1/jobs/{job_id}/versions",
        response_model=list[JobVersionResponse],
        dependencies=[Depends(require_single_admin)],
    )
    def get_job_versions(
        job_id: str,
        session: Session = Depends(get_session),
    ) -> list[JobVersionResponse]:
        try:
            return list_job_versions(session, job_id=job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.get(
        "/v1/jobs/latest-confirmed-version",
        response_model=JobVersionResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def get_latest_confirmed_job_version_detail(
        session: Session = Depends(get_session),
    ) -> JobVersionResponse:
        try:
            return get_latest_confirmed_job_version(session)
        except JobVersionNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.get(
        "/v1/jobs/confirmed-versions",
        response_model=list[JobVersionResponse],
        dependencies=[Depends(require_single_admin)],
    )
    def get_confirmed_job_versions(
        session: Session = Depends(get_session),
    ) -> list[JobVersionResponse]:
        """List the saved JDs available in the workspace switcher."""

        return list_confirmed_job_versions(session)

    @app.get(
        "/v1/job-versions/{job_version_id}",
        response_model=JobVersionResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def get_job_version_detail(
        job_version_id: str,
        session: Session = Depends(get_session),
    ) -> JobVersionResponse:
        try:
            return get_job_version(session, job_version_id=job_version_id)
        except JobVersionNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.get(
        "/v1/job-versions/{job_version_id}/matches",
        response_model=list[JobMatchResponse],
        dependencies=[Depends(require_single_admin)],
    )
    def get_job_version_match_history(
        job_version_id: str,
        session: Session = Depends(get_session),
    ) -> list[JobMatchResponse]:
        try:
            return list_job_version_matches(session, job_version_id=job_version_id)
        except JobVersionNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.post(
        "/v1/job-versions/{job_version_id}/extract",
        response_model=JobVersionResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def post_extract_job_version_requirements(
        job_version_id: str,
        session: Session = Depends(get_session),
    ) -> JobVersionResponse:
        try:
            response = extract_job_version_requirements(
                session,
                job_version_id=job_version_id,
                settings=settings,
            )
        except JobVersionNotFoundError as exc:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except JobServiceError as exc:
            session.rollback()
            _raise_job_service_error(exc)
        except JobDeepSeekProviderError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="jd_requirements_provider_failed",
            ) from exc
        _commit_or_raise(session)
        return response

    @app.put(
        "/v1/job-versions/{job_version_id}/requirements",
        response_model=JobVersionResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def put_job_version_requirements(
        job_version_id: str,
        payload: JobVersionRequirementsUpdate,
        session: Session = Depends(get_session),
    ) -> JobVersionResponse:
        try:
            response = update_job_version_requirements(
                session,
                job_version_id=job_version_id,
                payload=payload,
            )
        except JobVersionNotFoundError as exc:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except JobServiceError as exc:
            session.rollback()
            _raise_job_service_error(exc)
        _commit_or_raise(session)
        return response

    @app.post(
        "/v1/job-versions/{job_version_id}/confirm",
        response_model=JobVersionResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def post_confirm_job_version(
        job_version_id: str,
        session: Session = Depends(get_session),
    ) -> JobVersionResponse:
        try:
            response = confirm_job_version(session, job_version_id=job_version_id)
        except JobVersionNotFoundError as exc:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except JobServiceError as exc:
            session.rollback()
            _raise_job_service_error(exc)
        _commit_or_raise(session)
        return response

    @app.post(
        "/v1/job-versions/{job_version_id}/match-all",
        response_model=JobMatchBatchResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def post_enqueue_job_version_match_batch(
        job_version_id: str,
        session: Session = Depends(get_session),
    ) -> JobMatchBatchResponse:
        try:
            response = enqueue_job_version_match_batch(
                session,
                job_version_id=job_version_id,
                settings=settings,
            )
        except JobVersionNotFoundError as exc:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except JobServiceError as exc:
            session.rollback()
            _raise_job_service_error(exc)
        _commit_or_raise(session)
        return response

    @app.get(
        "/v1/job-match-batches/{batch_id}",
        response_model=JobMatchBatchResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def get_job_match_batch_status(
        batch_id: str,
        session: Session = Depends(get_session),
    ) -> JobMatchBatchResponse:
        try:
            return get_job_match_batch(session, batch_id=batch_id)
        except JobServiceError as exc:
            _raise_job_service_error(exc)

    @app.post(
        "/v1/resumes/{resume_id}/job-matches",
        response_model=JobMatchResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def post_job_match(
        resume_id: str,
        payload: JobMatchCreate,
        session: Session = Depends(get_session),
    ) -> JobMatchResponse:
        try:
            response = run_job_match(
                session,
                resume_id=resume_id,
                payload=payload,
                settings=settings,
            )
        except JobVersionNotFoundError as exc:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except JobServiceError as exc:
            session.rollback()
            _raise_job_service_error(exc)
        except JobDeepSeekProviderError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="jd_match_provider_failed",
            ) from exc
        _commit_or_raise(session)
        return response

    @app.get(
        "/v1/resumes/{resume_id}/job-matches",
        response_model=list[JobMatchResponse],
        dependencies=[Depends(require_single_admin)],
    )
    def get_resume_job_match_history(
        resume_id: str,
        session: Session = Depends(get_session),
    ) -> list[JobMatchResponse]:
        try:
            return list_resume_job_matches(session, resume_id=resume_id)
        except JobServiceError as exc:
            _raise_job_service_error(exc)

    @app.get(
        "/v1/job-matches/{match_id}",
        response_model=JobMatchResponse,
        dependencies=[Depends(require_single_admin)],
    )
    def get_job_match_detail(
        match_id: str,
        session: Session = Depends(get_session),
    ) -> JobMatchResponse:
        try:
            return get_job_match(session, match_id=match_id)
        except JobMatchNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return app


app = create_app()
