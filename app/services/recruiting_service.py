"""Human-controlled recruiting workflow and job-application services.

This module deliberately does not depend on an LLM.  A candidate application
is a durable, recruiter-created record which pins the JD, workflow and resume
fact revisions that were visible at the time of the action.  AI features may
later attach advisory material, but they must never call the transition
functions below.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Candidate,
    CandidateDataAuditEvent,
    Job,
    JobApplication,
    JobApplicationStageTransition,
    JobVersion,
    OrganizationMembership,
    RecruitingWorkflow,
    RecruitingWorkflowStage,
    RecruitingWorkflowVersion,
    Resume,
    ResumeFactSnapshot,
    UserAccount,
)
from app.schemas import (
    JobApplicationCreate,
    JobApplicationDetailResponse,
    JobApplicationListResponse,
    JobApplicationResponse,
    JobApplicationStageTransitionResponse,
    JobRecruitingSettingsResponse,
    JobRecruitingSettingsUpdate,
    RecruitingMemberResponse,
    RecruitingWorkflowCreate,
    RecruitingWorkflowResponse,
    RecruitingWorkflowStageInput,
    RecruitingWorkflowStageResponse,
    RecruitingWorkflowVersionCreate,
    RecruitingWorkflowVersionResponse,
)
from app.tenant_scope import organization_context_id


class RecruitingServiceError(RuntimeError):
    """A stable, content-free recruiting-domain failure."""


DEFAULT_WORKFLOW_NAME = "默认招聘流程"
DEFAULT_WORKFLOW_STAGES: tuple[tuple[str, str, str, int], ...] = (
    ("pending_screen", "待筛选", "active", 10),
    ("initial_screen", "初筛", "active", 20),
    ("interview", "面试", "active", 30),
    ("final_interview", "复试", "active", 40),
    ("offer", "Offer", "active", 50),
    ("hired", "已录用", "hired", 90),
    ("rejected", "已淘汰", "rejected", 100),
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _organization_id(session: Session) -> str:
    return organization_context_id(session)


def _stages_for_version(
    session: Session,
    *,
    workflow_version_id: str,
) -> list[RecruitingWorkflowStage]:
    return session.scalars(
        select(RecruitingWorkflowStage)
        .where(RecruitingWorkflowStage.workflow_version_id == workflow_version_id)
        .order_by(RecruitingWorkflowStage.sort_order, RecruitingWorkflowStage.id)
    ).all()


def _stage_response(stage: RecruitingWorkflowStage) -> RecruitingWorkflowStageResponse:
    return RecruitingWorkflowStageResponse(
        stage_id=stage.id,
        workflow_version_id=stage.workflow_version_id,
        stage_key=stage.stage_key,
        name=stage.name,
        stage_type=stage.stage_type,
        sort_order=stage.sort_order,
    )


def _workflow_version_response(
    session: Session,
    workflow_version: RecruitingWorkflowVersion,
) -> RecruitingWorkflowVersionResponse:
    return RecruitingWorkflowVersionResponse(
        workflow_version_id=workflow_version.id,
        workflow_id=workflow_version.workflow_id,
        version=workflow_version.version,
        status=workflow_version.status,
        created_at=workflow_version.created_at.isoformat(),
        published_at=(
            workflow_version.published_at.isoformat()
            if workflow_version.published_at is not None
            else None
        ),
        stages=[
            _stage_response(stage)
            for stage in _stages_for_version(session, workflow_version_id=workflow_version.id)
        ],
    )


def _workflow_response(
    session: Session,
    workflow: RecruitingWorkflow,
) -> RecruitingWorkflowResponse:
    versions = session.scalars(
        select(RecruitingWorkflowVersion)
        .where(RecruitingWorkflowVersion.workflow_id == workflow.id)
        .order_by(RecruitingWorkflowVersion.version.desc())
    ).all()
    return RecruitingWorkflowResponse(
        workflow_id=workflow.id,
        name=workflow.name,
        created_at=workflow.created_at.isoformat(),
        updated_at=workflow.updated_at.isoformat(),
        versions=[_workflow_version_response(session, item) for item in versions],
    )


def _validate_publishable_stages(stages: Iterable[RecruitingWorkflowStage]) -> None:
    stage_list = list(stages)
    active_stages = [stage for stage in stage_list if stage.stage_type == "active"]
    hired_stages = [stage for stage in stage_list if stage.stage_type == "hired"]
    rejected_stages = [stage for stage in stage_list if stage.stage_type == "rejected"]
    if not active_stages:
        raise RecruitingServiceError("workflow_requires_active_stage")
    if len(hired_stages) != 1:
        raise RecruitingServiceError("workflow_requires_one_hired_stage")
    if len(rejected_stages) != 1:
        raise RecruitingServiceError("workflow_requires_one_rejected_stage")
    if any(stage.sort_order < 0 for stage in stage_list):
        raise RecruitingServiceError("workflow_stage_order_invalid")


def _create_workflow_version(
    session: Session,
    *,
    workflow: RecruitingWorkflow,
    version_number: int,
    stage_inputs: Iterable[RecruitingWorkflowStageInput],
    published: bool,
) -> RecruitingWorkflowVersion:
    now = utcnow()
    workflow_version = RecruitingWorkflowVersion(
        organization_id=_organization_id(session),
        workflow_id=workflow.id,
        version=version_number,
        status="published" if published else "draft",
        published_at=now if published else None,
    )
    session.add(workflow_version)
    session.flush()
    for stage_input in sorted(stage_inputs, key=lambda item: (item.sort_order, item.stage_key)):
        session.add(
            RecruitingWorkflowStage(
                organization_id=_organization_id(session),
                workflow_version_id=workflow_version.id,
                stage_key=stage_input.stage_key,
                name=stage_input.name,
                stage_type=stage_input.stage_type,
                sort_order=stage_input.sort_order,
            )
        )
    session.flush()
    _validate_publishable_stages(_stages_for_version(session, workflow_version_id=workflow_version.id))
    return workflow_version


def _default_workflow_stage_inputs() -> list[RecruitingWorkflowStageInput]:
    return [
        RecruitingWorkflowStageInput(
            stage_key=stage_key,
            name=name,
            stage_type=stage_type,
            sort_order=sort_order,
        )
        for stage_key, name, stage_type, sort_order in DEFAULT_WORKFLOW_STAGES
    ]


def ensure_default_recruiting_workflow(session: Session) -> RecruitingWorkflowVersion:
    """Return the workspace's immutable default workflow, creating it once.

    The idempotent lookup keeps first-use setup out of the recruiter UI.  It
    is only called from write paths (or an explicit initialization route), so
    an ordinary list/read request never mutates tenant data.
    """

    workflow = session.scalar(
        select(RecruitingWorkflow)
        .where(RecruitingWorkflow.name == DEFAULT_WORKFLOW_NAME)
        .with_for_update()
    )
    if workflow is None:
        # A missing row cannot be locked. Contain the unique-name race in a
        # savepoint so a second first-use request can load the winner without
        # rolling back its caller's pending Job/JD changes.
        try:
            with session.begin_nested():
                workflow = RecruitingWorkflow(
                    organization_id=_organization_id(session),
                    name=DEFAULT_WORKFLOW_NAME,
                )
                session.add(workflow)
                session.flush()
                workflow_version = _create_workflow_version(
                    session,
                    workflow=workflow,
                    version_number=1,
                    stage_inputs=_default_workflow_stage_inputs(),
                    published=True,
                )
        except IntegrityError as exc:
            workflow = session.scalar(
                select(RecruitingWorkflow)
                .where(RecruitingWorkflow.name == DEFAULT_WORKFLOW_NAME)
                .with_for_update()
            )
            if workflow is None:
                raise RecruitingServiceError("recruiting_default_workflow_unavailable") from exc
        else:
            return workflow_version

    published = session.scalar(
        select(RecruitingWorkflowVersion)
        .where(
            RecruitingWorkflowVersion.workflow_id == workflow.id,
            RecruitingWorkflowVersion.status == "published",
        )
        .order_by(RecruitingWorkflowVersion.version.desc())
    )
    if published is not None:
        return published

    next_version = (
        session.scalar(
            select(func.max(RecruitingWorkflowVersion.version)).where(
                RecruitingWorkflowVersion.workflow_id == workflow.id
            )
        )
        or 0
    ) + 1
    return _create_workflow_version(
        session,
        workflow=workflow,
        version_number=next_version,
        stage_inputs=_default_workflow_stage_inputs(),
        published=True,
    )


def create_recruiting_workflow(
    session: Session,
    *,
    payload: RecruitingWorkflowCreate,
) -> RecruitingWorkflowResponse:
    workflow = RecruitingWorkflow(
        organization_id=_organization_id(session),
        name=payload.name,
    )
    session.add(workflow)
    try:
        session.flush()
    except IntegrityError as exc:
        raise RecruitingServiceError("recruiting_workflow_name_taken") from exc
    _create_workflow_version(
        session,
        workflow=workflow,
        version_number=1,
        stage_inputs=payload.stages,
        # A complete new workflow is ready for a recruiter to use. Further
        # edits become a later immutable version rather than an in-place save.
        published=True,
    )
    session.flush()
    return _workflow_response(session, workflow)


def list_recruiting_workflows(session: Session) -> list[RecruitingWorkflowResponse]:
    workflows = session.scalars(
        select(RecruitingWorkflow).order_by(
            RecruitingWorkflow.updated_at.desc(),
            RecruitingWorkflow.id.desc(),
        )
    ).all()
    return [_workflow_response(session, workflow) for workflow in workflows]


def create_recruiting_workflow_version(
    session: Session,
    *,
    workflow_id: str,
    payload: RecruitingWorkflowVersionCreate,
) -> RecruitingWorkflowVersionResponse:
    workflow = session.scalar(
        select(RecruitingWorkflow)
        .where(RecruitingWorkflow.id == workflow_id)
        .with_for_update()
    )
    if workflow is None:
        raise RecruitingServiceError("recruiting_workflow_not_found")
    next_version = (
        session.scalar(
            select(func.max(RecruitingWorkflowVersion.version)).where(
                RecruitingWorkflowVersion.workflow_id == workflow.id
            )
        )
        or 0
    ) + 1
    workflow_version = _create_workflow_version(
        session,
        workflow=workflow,
        version_number=next_version,
        stage_inputs=payload.stages,
        published=False,
    )
    session.flush()
    return _workflow_version_response(session, workflow_version)


def publish_recruiting_workflow_version(
    session: Session,
    *,
    workflow_version_id: str,
) -> RecruitingWorkflowVersionResponse:
    workflow_version = session.scalar(
        select(RecruitingWorkflowVersion)
        .where(RecruitingWorkflowVersion.id == workflow_version_id)
        .with_for_update()
    )
    if workflow_version is None:
        raise RecruitingServiceError("recruiting_workflow_version_not_found")
    if workflow_version.status != "draft":
        raise RecruitingServiceError("recruiting_workflow_version_not_draft")
    _validate_publishable_stages(
        _stages_for_version(session, workflow_version_id=workflow_version.id)
    )
    workflow_version.status = "published"
    workflow_version.published_at = utcnow()
    session.flush()
    return _workflow_version_response(session, workflow_version)


def list_recruiting_members(session: Session) -> list[RecruitingMemberResponse]:
    rows = session.execute(
        select(OrganizationMembership, UserAccount)
        .join(UserAccount, UserAccount.id == OrganizationMembership.user_id)
        .where(
            OrganizationMembership.organization_id == _organization_id(session),
            OrganizationMembership.is_active.is_(True),
            UserAccount.is_active.is_(True),
        )
        .order_by(UserAccount.full_name, UserAccount.id)
    ).all()
    return [
        RecruitingMemberResponse(
            user_id=user.id,
            display_name=user.full_name,
            role=membership.role,
        )
        for membership, user in rows
    ]


def _active_member_or_error(session: Session, *, user_id: str) -> None:
    member = session.scalar(
        select(OrganizationMembership.id)
        .join(UserAccount, UserAccount.id == OrganizationMembership.user_id)
        .where(
            OrganizationMembership.organization_id == _organization_id(session),
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.is_active.is_(True),
            UserAccount.is_active.is_(True),
        )
    )
    if member is None:
        # Use the same code for a non-existent account, another tenant's
        # account, and an inactive membership. It exposes no account detail.
        raise RecruitingServiceError("recruiting_owner_not_found")


def _load_job(session: Session, *, job_id: str, for_update: bool = False) -> Job:
    statement = select(Job).where(Job.id == job_id, Job.kind == "job")
    if for_update:
        statement = statement.with_for_update()
    job = session.scalar(statement)
    if job is None:
        raise RecruitingServiceError("recruiting_job_not_found")
    return job


def _load_published_workflow_version(
    session: Session,
    *,
    workflow_version_id: str,
) -> RecruitingWorkflowVersion:
    workflow_version = session.scalar(
        select(RecruitingWorkflowVersion).where(
            RecruitingWorkflowVersion.id == workflow_version_id,
            RecruitingWorkflowVersion.status == "published",
        )
    )
    if workflow_version is None:
        raise RecruitingServiceError("recruiting_workflow_version_not_found")
    return workflow_version


def _load_workflow_version(
    session: Session,
    *,
    workflow_version_id: str,
) -> RecruitingWorkflowVersion:
    """Load a pinned historical version without requiring it stay published."""

    workflow_version = session.scalar(
        select(RecruitingWorkflowVersion).where(
            RecruitingWorkflowVersion.id == workflow_version_id,
        )
    )
    if workflow_version is None:
        raise RecruitingServiceError("recruiting_workflow_version_not_found")
    return workflow_version


def initialize_job_recruiting_defaults(
    session: Session,
    *,
    job_id: str,
    owner_user_id: str | None,
    initial_recruiting_status: str | None = None,
) -> JobRecruitingSettingsResponse:
    """Initialize new or legacy JDs without mutating later recruiter choices."""

    job = _load_job(session, job_id=job_id, for_update=True)
    if job.recruiting_workflow_version_id is None:
        job.recruiting_workflow_version_id = ensure_default_recruiting_workflow(session).id
    if owner_user_id is not None and job.owner_user_id is None:
        _active_member_or_error(session, user_id=owner_user_id)
        job.owner_user_id = owner_user_id
    if initial_recruiting_status in {"draft", "open", "paused", "closed"}:
        # This is used only on the normal Job-creation route. A newly created
        # JD without confirmed requirements is a recruiting draft rather than
        # an apparently open position that cannot accept an application.
        job.recruiting_status = initial_recruiting_status
    elif job.recruiting_status not in {"draft", "open", "paused", "closed"}:
        job.recruiting_status = "open"
    session.flush()
    return _job_settings_response(job)


def _workflow_metadata(
    session: Session,
    workflow_version_id: str | None,
) -> tuple[str | None, int | None, str | None]:
    if workflow_version_id is None:
        return None, None, None
    row = session.execute(
        select(
            RecruitingWorkflowVersion.id,
            RecruitingWorkflowVersion.version,
            RecruitingWorkflow.name,
        )
        .join(RecruitingWorkflow, RecruitingWorkflow.id == RecruitingWorkflowVersion.workflow_id)
        .where(RecruitingWorkflowVersion.id == workflow_version_id)
    ).one_or_none()
    if row is None:
        return None, None, None
    return row[0], row[1], row[2]


def _owner_display_name(session: Session, owner_user_id: str | None) -> str | None:
    if owner_user_id is None:
        return None
    return session.scalar(select(UserAccount.full_name).where(UserAccount.id == owner_user_id))


def _active_application_count(session: Session, *, job_id: str) -> int:
    return int(
        session.scalar(
            select(func.count(JobApplication.id))
            .join(Candidate, Candidate.id == JobApplication.candidate_id)
            .join(Resume, Resume.id == JobApplication.resume_id)
            .where(
                JobApplication.job_id == job_id,
                JobApplication.is_current.is_(True),
                JobApplication.status == "active",
            )
        )
        or 0
    )


def _latest_job_version(session: Session, *, job: Job) -> JobVersion | None:
    return session.scalar(
        select(JobVersion)
        .where(JobVersion.job_id == job.id, JobVersion.version == job.version)
    )


def _job_settings_response(job: Job) -> JobRecruitingSettingsResponse:
    return JobRecruitingSettingsResponse(
        job_id=job.id,
        recruiting_status=job.recruiting_status,
        department=job.department,
        owner_user_id=job.owner_user_id,
        hc_total=job.hc_total,
        recruiting_workflow_version_id=job.recruiting_workflow_version_id,
        updated_at=job.updated_at.isoformat(),
    )


def _job_response(session: Session, *, job: Job):
    """Build a stable response without loading candidate data into a Job row."""

    # Import lazily while schema field additions remain independent from the
    # existing JD API. This also makes the response builder explicit rather
    # than relying on an ORM object to serialize relationships implicitly.
    from app.schemas import RecruitingJobResponse

    workflow_version_id, workflow_version_number, workflow_name = _workflow_metadata(
        session,
        job.recruiting_workflow_version_id,
    )
    job_version = _latest_job_version(session, job=job)
    return RecruitingJobResponse(
        job_id=job.id,
        title=job.title,
        current_job_version_id=job_version.id if job_version is not None else None,
        current_job_version_number=job_version.version if job_version is not None else None,
        recruiting_status=job.recruiting_status,
        department=job.department,
        owner_user_id=job.owner_user_id,
        owner_display_name=_owner_display_name(session, job.owner_user_id),
        hc_total=job.hc_total,
        recruiting_workflow_version_id=workflow_version_id,
        workflow_version_number=workflow_version_number,
        workflow_name=workflow_name,
        active_application_count=_active_application_count(session, job_id=job.id),
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
    )


def list_recruiting_jobs(session: Session):
    from app.schemas import RecruitingJobListResponse

    jobs = session.scalars(
        select(Job)
        .where(Job.kind == "job")
        .order_by(Job.updated_at.desc(), Job.id.desc())
    ).all()
    items = [_job_response(session, job=job) for job in jobs]
    return RecruitingJobListResponse(items=items, total=len(items))


def get_recruiting_job(session: Session, *, job_id: str):
    return _job_response(session, job=_load_job(session, job_id=job_id))


def update_job_recruiting_settings(
    session: Session,
    *,
    job_id: str,
    payload: JobRecruitingSettingsUpdate,
) -> JobRecruitingSettingsResponse:
    job = _load_job(session, job_id=job_id, for_update=True)
    fields = payload.model_fields_set
    if "recruiting_status" in fields:
        job.recruiting_status = payload.recruiting_status  # type: ignore[assignment]
    if "department" in fields:
        job.department = payload.department
    if "owner_user_id" in fields:
        if payload.owner_user_id is not None:
            _active_member_or_error(session, user_id=payload.owner_user_id)
        job.owner_user_id = payload.owner_user_id
    if "hc_total" in fields:
        job.hc_total = payload.hc_total  # type: ignore[assignment]
    if "recruiting_workflow_version_id" in fields:
        if payload.recruiting_workflow_version_id is None:
            job.recruiting_workflow_version_id = None
        else:
            job.recruiting_workflow_version_id = _load_published_workflow_version(
                session,
                workflow_version_id=payload.recruiting_workflow_version_id,
            ).id
    session.flush()
    return _job_settings_response(job)


def _ready_candidate_resume_snapshot(
    session: Session,
    *,
    candidate_id: str,
) -> tuple[Candidate, Resume, ResumeFactSnapshot]:
    candidate = session.scalar(
        select(Candidate)
        .where(Candidate.id == candidate_id)
        .with_for_update()
    )
    if candidate is None:
        raise RecruitingServiceError("recruiting_candidate_not_found")
    resume = session.scalar(
        select(Resume)
        .join(Candidate, Candidate.id == Resume.candidate_id)
        .where(
            Resume.candidate_id == candidate.id,
            Resume.is_active.is_(True),
            Resume.extraction_status == "ready",
        )
        .order_by(Resume.updated_at.desc(), Resume.id.desc())
        .with_for_update()
    )
    if resume is None:
        raise RecruitingServiceError("candidate_has_no_active_ready_resume")
    snapshot = session.scalar(
        select(ResumeFactSnapshot).where(
            ResumeFactSnapshot.resume_id == resume.id,
            ResumeFactSnapshot.facts_version == resume.facts_version,
        )
    )
    if snapshot is None:
        raise RecruitingServiceError("candidate_resume_snapshot_not_found")
    return candidate, resume, snapshot


def _current_confirmed_job_version(session: Session, *, job: Job) -> JobVersion:
    job_version = session.scalar(
        select(JobVersion).where(
            JobVersion.job_id == job.id,
            JobVersion.version == job.version,
            JobVersion.status == "confirmed",
        )
    )
    if job_version is None:
        raise RecruitingServiceError("recruiting_job_has_no_confirmed_jd")
    return job_version


def _first_active_stage(
    session: Session,
    *,
    workflow_version: RecruitingWorkflowVersion,
) -> RecruitingWorkflowStage:
    stage = session.scalar(
        select(RecruitingWorkflowStage)
        .where(
            RecruitingWorkflowStage.workflow_version_id == workflow_version.id,
            RecruitingWorkflowStage.stage_type == "active",
        )
        .order_by(RecruitingWorkflowStage.sort_order, RecruitingWorkflowStage.id)
    )
    if stage is None:
        raise RecruitingServiceError("workflow_requires_active_stage")
    return stage


def _record_application_audit(
    session: Session,
    *,
    actor_user_id: str,
    action: str,
    application: JobApplication,
    request_id: str | None,
) -> None:
    # CandidateDataAuditEvent intentionally contains only opaque IDs and a
    # controlled event type. Recruiter notes stay in the application history,
    # not a broad audit feed that may survive the candidate's lifecycle purge.
    session.add(
        CandidateDataAuditEvent(
            organization_id=_organization_id(session),
            actor_user_id=actor_user_id,
            actor_kind="user",
            action=action,
            target_type="job_application",
            target_id=application.id,
            candidate_id=application.candidate_id,
            resume_id=application.resume_id,
            request_id=request_id,
            source_kind="web",
            result="authorized",
        )
    )


def _application_response(
    session: Session,
    *,
    application: JobApplication,
    candidate_display_name: str | None,
    job_title: str,
):
    from app.schemas import JobApplicationResponse

    # ``Job.title`` is a mutable current-version cache. The application must
    # display the title that belonged to its pinned JD revision, otherwise a
    # later JD edit would rewrite the historical recruiting record.
    snapshot_job_title = session.scalar(
        select(JobVersion.title).where(JobVersion.id == application.job_version_id)
    )
    workflow_version = _load_workflow_version(
        session,
        workflow_version_id=application.workflow_version_id,
    )
    workflow = session.scalar(
        select(RecruitingWorkflow).where(RecruitingWorkflow.id == workflow_version.workflow_id)
    )
    return JobApplicationResponse(
        application_id=application.id,
        job_id=application.job_id,
        job_title=snapshot_job_title or job_title,
        candidate_id=application.candidate_id,
        candidate_display_name=candidate_display_name,
        resume_id=application.resume_id,
        resume_fact_snapshot_id=application.resume_fact_snapshot_id,
        resume_facts_version=application.resume_facts_version,
        job_version_id=application.job_version_id,
        job_version_number=application.job_version_number,
        workflow_version_id=application.workflow_version_id,
        workflow_version_number=application.workflow_version_number,
        workflow_name=workflow.name if workflow is not None else None,
        current_stage_id=application.current_stage_id,
        current_stage_key=application.current_stage_key,
        current_stage_name=application.current_stage_name,
        current_stage_type=application.current_stage_type,
        current_stage_sort_order=session.scalar(
            select(RecruitingWorkflowStage.sort_order).where(
                RecruitingWorkflowStage.id == application.current_stage_id,
                RecruitingWorkflowStage.workflow_version_id == application.workflow_version_id,
            )
        )
        or 0,
        status=application.status,
        is_current=application.is_current,
        round_number=application.round_number,
        state_version=application.state_version,
        added_by_user_id=application.added_by_user_id,
        created_at=application.created_at.isoformat(),
        updated_at=application.updated_at.isoformat(),
    )


def _transition_response(
    transition: JobApplicationStageTransition,
) -> JobApplicationStageTransitionResponse:
    return JobApplicationStageTransitionResponse(
        transition_id=transition.id,
        application_id=transition.application_id,
        state_version_after=transition.state_version_after,
        from_stage_id=transition.from_stage_id,
        from_stage_key=transition.from_stage_key,
        from_stage_name=transition.from_stage_name,
        from_stage_type=transition.from_stage_type,
        to_stage_id=transition.to_stage_id,
        to_stage_key=transition.to_stage_key,
        to_stage_name=transition.to_stage_name,
        to_stage_type=transition.to_stage_type,
        action=transition.action,
        actor_user_id=transition.actor_user_id,
        note=transition.note,
        created_at=transition.created_at.isoformat(),
    )


def create_job_application(
    session: Session,
    *,
    job_id: str,
    payload: JobApplicationCreate,
    actor_user_id: str,
    request_id: str | None = None,
):
    job = _load_job(session, job_id=job_id, for_update=True)
    if job.recruiting_status != "open":
        raise RecruitingServiceError("recruiting_job_not_open")
    if job.recruiting_workflow_version_id is None:
        job.recruiting_workflow_version_id = ensure_default_recruiting_workflow(session).id
    workflow_version = _load_published_workflow_version(
        session,
        workflow_version_id=job.recruiting_workflow_version_id,
    )
    job_version = _current_confirmed_job_version(session, job=job)
    candidate, resume, snapshot = _ready_candidate_resume_snapshot(
        session,
        candidate_id=payload.candidate_id,
    )
    current = session.scalar(
        select(JobApplication)
        .where(
            JobApplication.job_id == job.id,
            JobApplication.candidate_id == candidate.id,
            JobApplication.is_current.is_(True),
        )
        .with_for_update()
    )
    if current is not None and current.status == "active":
        raise RecruitingServiceError("candidate_already_has_active_application")
    if current is not None:
        current.is_current = False
        next_round = current.round_number + 1
    else:
        next_round = 1
    first_stage = _first_active_stage(session, workflow_version=workflow_version)
    application = JobApplication(
        organization_id=_organization_id(session),
        job_id=job.id,
        candidate_id=candidate.id,
        resume_id=resume.id,
        resume_fact_snapshot_id=snapshot.id,
        resume_facts_version=snapshot.facts_version,
        job_version_id=job_version.id,
        job_version_number=job_version.version,
        workflow_version_id=workflow_version.id,
        workflow_version_number=workflow_version.version,
        current_stage_id=first_stage.id,
        current_stage_key=first_stage.stage_key,
        current_stage_name=first_stage.name,
        current_stage_type=first_stage.stage_type,
        status="active",
        is_current=True,
        round_number=next_round,
        state_version=1,
        added_by_user_id=actor_user_id,
    )
    session.add(application)
    try:
        session.flush()
    except IntegrityError as exc:
        # A partial unique index is the final guard when two recruiters add
        # the same candidate to the same job at nearly the same time.
        raise RecruitingServiceError("candidate_already_has_active_application") from exc
    transition = JobApplicationStageTransition(
        organization_id=_organization_id(session),
        application_id=application.id,
        state_version_after=1,
        from_stage_id=None,
        from_stage_key=None,
        from_stage_name=None,
        from_stage_type=None,
        to_stage_id=first_stage.id,
        to_stage_key=first_stage.stage_key,
        to_stage_name=first_stage.name,
        to_stage_type=first_stage.stage_type,
        action="initial",
        actor_user_id=actor_user_id,
        note=None,
    )
    session.add(transition)
    _record_application_audit(
        session,
        actor_user_id=actor_user_id,
        action="job_application_created",
        application=application,
        request_id=request_id,
    )
    try:
        session.flush()
    except IntegrityError as exc:
        # The partial unique index handles two simultaneous add requests even
        # on a database where row locks are not eagerly acquired.
        raise RecruitingServiceError("candidate_already_has_active_application") from exc
    return _application_response(
        session,
        application=application,
        candidate_display_name=candidate.display_name,
        job_title=job.title,
    )


def _visible_application(
    session: Session,
    *,
    application_id: str,
    for_update: bool = False,
) -> tuple[JobApplication, Candidate, Resume, Job]:
    """Load an application only through live candidate/privacy roots."""

    statement = (
        select(JobApplication, Candidate, Resume, Job)
        .join(Candidate, Candidate.id == JobApplication.candidate_id)
        .join(Resume, Resume.id == JobApplication.resume_id)
        .join(Job, Job.id == JobApplication.job_id)
        .where(JobApplication.id == application_id, Job.kind == "job")
    )
    if for_update:
        statement = statement.with_for_update()
    row = session.execute(statement).one_or_none()
    if row is None:
        raise RecruitingServiceError("job_application_not_found")
    return row


def list_job_applications(
    session: Session,
    *,
    job_id: str,
    include_history: bool = False,
) -> JobApplicationListResponse:
    _load_job(session, job_id=job_id)
    statement = (
        select(JobApplication, Candidate.display_name, Job.title)
        .join(Candidate, Candidate.id == JobApplication.candidate_id)
        .join(Resume, Resume.id == JobApplication.resume_id)
        .join(Job, Job.id == JobApplication.job_id)
        .where(JobApplication.job_id == job_id)
        .order_by(
            JobApplication.is_current.desc(),
            JobApplication.round_number.desc(),
            JobApplication.updated_at.desc(),
            JobApplication.id.desc(),
        )
    )
    if not include_history:
        statement = statement.where(JobApplication.is_current.is_(True))
    rows = session.execute(statement).all()
    items = [
        _application_response(
            session,
            application=application,
            candidate_display_name=display_name,
            job_title=job_title,
        )
        for application, display_name, job_title in rows
    ]
    return JobApplicationListResponse(items=items, total=len(items))


def list_candidate_job_applications(
    session: Session,
    *,
    candidate_id: str,
    include_history: bool = True,
) -> JobApplicationListResponse:
    candidate = session.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if candidate is None:
        raise RecruitingServiceError("recruiting_candidate_not_found")
    statement = (
        select(JobApplication, Candidate.display_name, Job.title)
        .join(Candidate, Candidate.id == JobApplication.candidate_id)
        .join(Resume, Resume.id == JobApplication.resume_id)
        .join(Job, Job.id == JobApplication.job_id)
        .where(JobApplication.candidate_id == candidate_id, Job.kind == "job")
        .order_by(
            JobApplication.is_current.desc(),
            JobApplication.round_number.desc(),
            JobApplication.updated_at.desc(),
            JobApplication.id.desc(),
        )
    )
    if not include_history:
        statement = statement.where(JobApplication.is_current.is_(True))
    rows = session.execute(statement).all()
    items = [
        _application_response(
            session,
            application=application,
            candidate_display_name=display_name,
            job_title=job_title,
        )
        for application, display_name, job_title in rows
    ]
    return JobApplicationListResponse(items=items, total=len(items))


def get_job_application(
    session: Session,
    *,
    application_id: str,
) -> JobApplicationDetailResponse:
    application, candidate, _resume, job = _visible_application(
        session,
        application_id=application_id,
    )
    transitions = session.scalars(
        select(JobApplicationStageTransition)
        .where(JobApplicationStageTransition.application_id == application.id)
        .order_by(
            JobApplicationStageTransition.state_version_after,
            JobApplicationStageTransition.id,
        )
    ).all()
    return JobApplicationDetailResponse(
        **_application_response(
            session,
            application=application,
            candidate_display_name=candidate.display_name,
            job_title=job.title,
        ).model_dump(),
        stage_transitions=[_transition_response(item) for item in transitions],
    )


def _stage_by_type(
    stages: Iterable[RecruitingWorkflowStage],
    stage_type: str,
) -> RecruitingWorkflowStage | None:
    return next((stage for stage in stages if stage.stage_type == stage_type), None)


def _next_transition_target(
    *,
    application: JobApplication,
    stages: list[RecruitingWorkflowStage],
    action: str,
) -> tuple[RecruitingWorkflowStage, str]:
    current_stage = next((stage for stage in stages if stage.id == application.current_stage_id), None)
    if current_stage is None:
        raise RecruitingServiceError("job_application_current_stage_not_found")
    if current_stage.stage_type != "active":
        raise RecruitingServiceError("job_application_not_active")
    active_stages = [stage for stage in stages if stage.stage_type == "active"]
    active_index = next(
        (index for index, stage in enumerate(active_stages) if stage.id == current_stage.id),
        None,
    )
    if active_index is None:
        raise RecruitingServiceError("job_application_current_stage_not_found")
    if action == "advance":
        if active_index + 1 >= len(active_stages):
            raise RecruitingServiceError("job_application_no_next_stage")
        return active_stages[active_index + 1], "advance"
    if action == "return":
        if active_index == 0:
            raise RecruitingServiceError("job_application_no_previous_stage")
        return active_stages[active_index - 1], "return"
    if action == "reject":
        rejected = _stage_by_type(stages, "rejected")
        if rejected is None:
            raise RecruitingServiceError("workflow_requires_one_rejected_stage")
        return rejected, "reject"
    if action == "hire":
        if active_index != len(active_stages) - 1:
            raise RecruitingServiceError("job_application_hire_requires_final_active_stage")
        hired = _stage_by_type(stages, "hired")
        if hired is None:
            raise RecruitingServiceError("workflow_requires_one_hired_stage")
        return hired, "hire"
    raise RecruitingServiceError("job_application_transition_action_invalid")


def transition_job_application(
    session: Session,
    *,
    application_id: str,
    action: str,
    payload: Any,
    actor_user_id: str,
    request_id: str | None = None,
) -> JobApplicationDetailResponse:
    """Advance, return, reject or hire an application by explicit human call.

    ``payload`` is intentionally only an optimistic state version plus an
    optional human note. No endpoint accepts an AI recommendation, a browser
    supplied target-stage ID, or an automatic transition flag.
    """

    application, candidate, _resume, job = _visible_application(
        session,
        application_id=application_id,
        for_update=True,
    )
    expected_state_version = int(getattr(payload, "expected_state_version"))
    note = getattr(payload, "note", None)
    if application.state_version != expected_state_version:
        raise RecruitingServiceError("job_application_state_version_conflict")
    if job.recruiting_status != "open":
        raise RecruitingServiceError("recruiting_job_not_open")
    if application.status != "active":
        raise RecruitingServiceError("job_application_not_active")
    stages = _stages_for_version(session, workflow_version_id=application.workflow_version_id)
    target_stage, direction = _next_transition_target(
        application=application,
        stages=stages,
        action=action,
    )
    old_state_version = application.state_version
    new_state_version = old_state_version + 1
    next_status = (
        "hired"
        if target_stage.stage_type == "hired"
        else "rejected"
        if target_stage.stage_type == "rejected"
        else "active"
    )
    result = session.execute(
        update(JobApplication)
        .where(
            JobApplication.id == application.id,
            JobApplication.organization_id == _organization_id(session),
            JobApplication.state_version == expected_state_version,
            JobApplication.status == "active",
        )
        .values(
            current_stage_id=target_stage.id,
            current_stage_key=target_stage.stage_key,
            current_stage_name=target_stage.name,
            current_stage_type=target_stage.stage_type,
            status=next_status,
            state_version=new_state_version,
            updated_at=utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise RecruitingServiceError("job_application_state_version_conflict")
    transition = JobApplicationStageTransition(
        organization_id=_organization_id(session),
        application_id=application.id,
        state_version_after=new_state_version,
        from_stage_id=application.current_stage_id,
        from_stage_key=application.current_stage_key,
        from_stage_name=application.current_stage_name,
        from_stage_type=application.current_stage_type,
        to_stage_id=target_stage.id,
        to_stage_key=target_stage.stage_key,
        to_stage_name=target_stage.name,
        to_stage_type=target_stage.stage_type,
        action=direction,
        actor_user_id=actor_user_id,
        note=note,
    )
    session.add(transition)
    _record_application_audit(
        session,
        actor_user_id=actor_user_id,
        action=f"job_application_{direction}",
        application=application,
        request_id=request_id,
    )
    session.flush()
    # The conditional bulk update intentionally bypassed the identity map.
    # Re-query through live Candidate/Resume roots before building a response.
    session.expire(application)
    return get_job_application(session, application_id=application.id)


__all__ = [
    "RecruitingServiceError",
    "create_job_application",
    "create_recruiting_workflow",
    "create_recruiting_workflow_version",
    "ensure_default_recruiting_workflow",
    "get_job_application",
    "get_recruiting_job",
    "initialize_job_recruiting_defaults",
    "list_candidate_job_applications",
    "list_job_applications",
    "list_recruiting_jobs",
    "list_recruiting_members",
    "list_recruiting_workflows",
    "publish_recruiting_workflow_version",
    "transition_job_application",
    "update_job_recruiting_settings",
]
