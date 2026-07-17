from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Float,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    display_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    resumes: Mapped[list["Resume"]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
    )


class Resume(Base):
    __tablename__ = "resumes"
    __table_args__ = (
        Index(
            "uq_active_resume_per_candidate",
            "candidate_id",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    source_page_count: Mapped[int] = mapped_column(Integer)
    parsed_page_count: Mapped[int] = mapped_column(Integer)
    extraction_status: Mapped[str] = mapped_column(String(32), index=True)
    quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    parser_version: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_985_211: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    highest_degree: Mapped[str | None] = mapped_column(String(32), index=True)
    employment_months: Mapped[int] = mapped_column(Integer, default=0, index=True)
    employment_or_internship_months: Mapped[int] = mapped_column(Integer, default=0, index=True)
    facts_version: Mapped[int] = mapped_column(Integer, default=0)
    raw_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    candidate: Mapped[Candidate] = relationship(back_populates="resumes")
    source_blocks: Mapped[list["ResumeSourceBlock"]] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
    )
    educations: Mapped[list["ResumeEducation"]] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
    )
    experiences: Mapped[list["ResumeExperience"]] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
    )
    skills: Mapped[list["ResumeSkill"]] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
    )
    review_actions: Mapped[list["ResumeReviewAction"]] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
    )
    fact_snapshots: Mapped[list["ResumeFactSnapshot"]] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
    )
    scores: Mapped[list["ResumeScore"]] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
    )
    summaries: Mapped[list["ResumeSummary"]] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
    )
    job_matches: Mapped[list["JobMatch"]] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
    )
    upload_idempotency_keys: Mapped[list["ResumeUploadIdempotencyKey"]] = (
        relationship(
            back_populates="resume",
            cascade="all, delete-orphan",
        )
    )
    ai_extraction_job: Mapped["ResumeAiExtractionJob | None"] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
        uselist=False,
    )


class ResumeUploadIdempotencyKey(Base):
    """Durable replay record for the convenience resume upload endpoint.

    The client supplied key is stored only as a SHA-256 digest.  This keeps the
    key opaque to database readers while still allowing a retry to find the
    original upload deterministically.
    """

    __tablename__ = "resume_upload_idempotency_keys"

    idempotency_key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    content_sha256: Mapped[str] = mapped_column(String(64))
    resume_id: Mapped[str] = mapped_column(
        ForeignKey("resumes.id"),
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    resume: Mapped[Resume] = relationship(back_populates="upload_idempotency_keys")


class ResumeAiExtractionJob(Base):
    """Durable, lease-based AI structured-facts extraction work for one resume.

    There is intentionally one mutable job per resume.  Re-running extraction
    resets that job only while the resume remains pending human review, which
    prevents a delayed worker from silently replacing already-confirmed facts.
    """

    __tablename__ = "resume_ai_extraction_jobs"
    __table_args__ = (
        UniqueConstraint("resume_id", name="uq_resume_ai_extraction_job_resume"),
        Index(
            "ix_resume_ai_extraction_job_claim",
            "status",
            "next_attempt_at",
        ),
        Index(
            "ix_resume_ai_extraction_job_lease",
            "status",
            "lease_expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    input_facts_version: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    resume: Mapped[Resume] = relationship(back_populates="ai_extraction_job")


class ResumeSourceBlock(Base):
    __tablename__ = "resume_source_blocks"
    __table_args__ = (UniqueConstraint("resume_id", "block_id", name="uq_resume_block_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), index=True)
    block_id: Mapped[str] = mapped_column(String(64))
    page_no: Mapped[int] = mapped_column(Integer)
    block_type: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)

    resume: Mapped[Resume] = relationship(back_populates="source_blocks")


class ResumeEducation(Base):
    __tablename__ = "resume_educations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), index=True)
    school_name_raw: Mapped[str] = mapped_column(String(255))
    school_key: Mapped[str | None] = mapped_column(String(255), index=True)
    institution_id: Mapped[str | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    school_match_state: Mapped[str] = mapped_column(String(32), default="unmatched")
    degree: Mapped[str] = mapped_column(String(32), index=True)
    major_raw: Mapped[str | None] = mapped_column(String(255))
    major_key: Mapped[str | None] = mapped_column(String(255), index=True)
    start_month: Mapped[str | None] = mapped_column(String(7))
    end_month: Mapped[str | None] = mapped_column(String(7))
    evidence_block_ids: Mapped[list[str]] = mapped_column(JSON, default=list)

    resume: Mapped[Resume] = relationship(back_populates="educations")


class ResumeExperience(Base):
    __tablename__ = "resume_experiences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), index=True)
    experience_type: Mapped[str] = mapped_column(String(32), index=True)
    # The explicit name of a project, competition, research activity, or
    # employment entry.  It is intentionally separate from the organization
    # and role so all three recruiter-facing concepts remain traceable.
    experience_name_raw: Mapped[str | None] = mapped_column(String(255))
    experience_name_key: Mapped[str | None] = mapped_column(String(255), index=True)
    organization_name_raw: Mapped[str | None] = mapped_column(String(255))
    organization_key: Mapped[str | None] = mapped_column(String(255), index=True)
    title_raw: Mapped[str | None] = mapped_column(String(255))
    title_key: Mapped[str | None] = mapped_column(String(255), index=True)
    start_month: Mapped[str | None] = mapped_column(String(7))
    end_month: Mapped[str | None] = mapped_column(String(7))
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_block_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    classification_evidence_block_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Each item is {"detail_raw": str, "evidence_block_ids": list[str]}.
    # V1 does not filter on individual responsibilities, so a JSON column
    # keeps the parent fact and its per-detail proof atomic at save time.
    detail_items: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)

    resume: Mapped[Resume] = relationship(back_populates="experiences")


class ResumeSkill(Base):
    __tablename__ = "resume_skills"
    __table_args__ = (UniqueConstraint("resume_id", "skill_key", name="uq_resume_skill"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), index=True)
    skill_key: Mapped[str] = mapped_column(String(120), index=True)
    skill_display: Mapped[str] = mapped_column(String(120))
    evidence_block_ids: Mapped[list[str]] = mapped_column(JSON, default=list)

    resume: Mapped[Resume] = relationship(back_populates="skills")


class ResumeReviewAction(Base):
    __tablename__ = "resume_review_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(100), default="single_admin")
    note: Mapped[str | None] = mapped_column(Text)
    old_values: Mapped[dict[str, object] | None] = mapped_column(JSON)
    new_values: Mapped[dict[str, object] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    resume: Mapped[Resume] = relationship(back_populates="review_actions")


class ResumeFactSnapshot(Base):
    """Append-only, reproducible representation of one saved facts revision."""

    __tablename__ = "resume_fact_snapshots"
    __table_args__ = (
        UniqueConstraint("resume_id", "facts_version", name="uq_resume_fact_snapshot_version"),
        Index("ix_resume_fact_snapshot_sha256", "facts_sha256"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), index=True)
    facts_version: Mapped[int] = mapped_column(Integer)
    canonical_facts_json: Mapped[str] = mapped_column(Text)
    facts_sha256: Mapped[str] = mapped_column(String(64))
    source_block_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    resume: Mapped[Resume] = relationship(back_populates="fact_snapshots")
    scores: Mapped[list["ResumeScore"]] = relationship(back_populates="fact_snapshot")
    job_matches: Mapped[list["JobMatch"]] = relationship(back_populates="fact_snapshot")


class Institution(Base):
    __tablename__ = "institutions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    roster_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    canonical_name: Mapped[str] = mapped_column(String(255))
    canonical_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    is_985_211: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    registry_version: Mapped[str] = mapped_column(String(64))

    aliases: Mapped[list["InstitutionAlias"]] = relationship(
        back_populates="institution",
        cascade="all, delete-orphan",
    )


class InstitutionAlias(Base):
    __tablename__ = "institution_aliases"

    alias_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    institution_id: Mapped[str] = mapped_column(ForeignKey("institutions.id"), index=True)

    institution: Mapped[Institution] = relationship(back_populates="aliases")


class SavedFilter(Base):
    __tablename__ = "saved_filters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    filters: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class ScoreTemplate(Base):
    __tablename__ = "score_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    dimensions: Mapped[list["ScoreTemplateDimension"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
    )
    scores: Mapped[list["ResumeScore"]] = relationship(back_populates="template")


class ScoreTemplateDimension(Base):
    __tablename__ = "score_template_dimensions"
    __table_args__ = (
        UniqueConstraint("template_id", "key", name="uq_score_template_dimension_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    template_id: Mapped[str] = mapped_column(ForeignKey("score_templates.id"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(120))
    weight: Mapped[int] = mapped_column(Integer)
    max_raw_score: Mapped[int] = mapped_column(
        Integer,
        default=100,
        server_default=text("100"),
    )
    guidance: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer)

    template: Mapped[ScoreTemplate] = relationship(back_populates="dimensions")


class ResumeScore(Base):
    __tablename__ = "resume_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), index=True)
    fact_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("resume_fact_snapshots.id"),
        nullable=True,
        index=True,
    )
    template_id: Mapped[str] = mapped_column(ForeignKey("score_templates.id"), index=True)
    facts_version: Mapped[int] = mapped_column(Integer)
    template_version: Mapped[int] = mapped_column(Integer)
    total_score: Mapped[float] = mapped_column(Float)
    ai_total_score: Mapped[float | None] = mapped_column(Float)
    dimension_scores: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    analysis: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    model_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    resume: Mapped[Resume] = relationship(back_populates="scores")
    fact_snapshot: Mapped[ResumeFactSnapshot | None] = relationship(back_populates="scores")
    template: Mapped[ScoreTemplate] = relationship(back_populates="scores")


class ResumeSummary(Base):
    __tablename__ = "resume_summaries"
    __table_args__ = (
        Index(
            "uq_current_resume_summary",
            "resume_id",
            unique=True,
            sqlite_where=text("is_current = 1"),
            postgresql_where=text("is_current = true"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), index=True)
    fact_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("resume_fact_snapshots.id"),
        nullable=True,
        index=True,
    )
    facts_version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(
        String(32),
        default="ai",
        server_default=text("'ai'"),
    )
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("resume_summaries.id"),
        nullable=True,
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32))
    model_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    resume: Mapped[Resume] = relationship(back_populates="summaries")
    fact_snapshot: Mapped[ResumeFactSnapshot | None] = relationship()


class Job(Base):
    """Current-version cache; immutable JD evidence lives in ``JobVersion``."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(200))
    jd_text: Mapped[str] = mapped_column(Text)
    requirements: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    matches: Mapped[list["JobMatch"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )
    versions: Mapped[list["JobVersion"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )


class JobVersion(Base):
    __tablename__ = "job_versions"
    __table_args__ = (
        UniqueConstraint("job_id", "version", name="uq_job_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    raw_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped[Job] = relationship(back_populates="versions")
    clauses: Mapped[list["JobSourceClause"]] = relationship(
        back_populates="job_version",
        cascade="all, delete-orphan",
    )
    requirements: Mapped[list["JobRequirement"]] = relationship(
        back_populates="job_version",
        cascade="all, delete-orphan",
    )
    matches: Mapped[list["JobMatch"]] = relationship(back_populates="job_version_record")


class JobSourceClause(Base):
    __tablename__ = "job_source_clauses"
    __table_args__ = (
        UniqueConstraint("job_version_id", "clause_id", name="uq_job_clause_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_version_id: Mapped[str] = mapped_column(ForeignKey("job_versions.id"), index=True)
    clause_id: Mapped[str] = mapped_column(String(64))
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)

    job_version: Mapped[JobVersion] = relationship(back_populates="clauses")


class JobRequirement(Base):
    __tablename__ = "job_requirements"
    __table_args__ = (
        UniqueConstraint("job_version_id", "requirement_key", name="uq_job_requirement_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_version_id: Mapped[str] = mapped_column(ForeignKey("job_versions.id"), index=True)
    requirement_key: Mapped[str] = mapped_column(String(64))
    priority: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    raw_requirement: Mapped[str] = mapped_column(Text)
    normalized_value: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    minimum_months: Mapped[int | None] = mapped_column(Integer)
    weight: Mapped[int] = mapped_column(Integer)
    clause_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    sort_order: Mapped[int] = mapped_column(Integer)

    job_version: Mapped[JobVersion] = relationship(back_populates="requirements")
    match_results: Mapped[list["JobMatchRequirementResult"]] = relationship(
        back_populates="requirement",
    )


class JobMatch(Base):
    __tablename__ = "job_matches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    job_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("job_versions.id"),
        nullable=True,
        index=True,
    )
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), index=True)
    fact_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("resume_fact_snapshots.id"),
        nullable=True,
        index=True,
    )
    facts_version: Mapped[int] = mapped_column(Integer)
    job_version: Mapped[int] = mapped_column(Integer)
    total_score: Mapped[float] = mapped_column(Float)
    must_have_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    evidence_coverage: Mapped[float | None] = mapped_column(Float)
    hard_requirement_status: Mapped[str | None] = mapped_column(String(32))
    analysis: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32))
    model_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[Job] = relationship(back_populates="matches")
    job_version_record: Mapped[JobVersion | None] = relationship(back_populates="matches")
    resume: Mapped[Resume] = relationship(back_populates="job_matches")
    fact_snapshot: Mapped[ResumeFactSnapshot | None] = relationship(back_populates="job_matches")
    requirement_results: Mapped[list["JobMatchRequirementResult"]] = relationship(
        back_populates="job_match",
        cascade="all, delete-orphan",
    )


class JobMatchRequirementResult(Base):
    __tablename__ = "job_match_requirement_results"
    __table_args__ = (
        UniqueConstraint("job_match_id", "requirement_id", name="uq_job_match_requirement"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_match_id: Mapped[str] = mapped_column(ForeignKey("job_matches.id"), index=True)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("job_requirements.id"), index=True)
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    fact_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing_or_uncertain: Mapped[str | None] = mapped_column(Text)
    score_contribution: Mapped[float] = mapped_column(Float)

    job_match: Mapped[JobMatch] = relationship(back_populates="requirement_results")
    requirement: Mapped[JobRequirement] = relationship(back_populates="match_results")


class JobMatchBatch(Base):
    """A durable, JD-version-scoped batch of AI resume matches."""

    __tablename__ = "job_match_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_version_id: Mapped[str] = mapped_column(ForeignKey("job_versions.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    job_version_record: Mapped[JobVersion] = relationship()
    items: Mapped[list["JobMatchBatchItem"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
    )


class JobMatchBatchItem(Base):
    __tablename__ = "job_match_batch_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "resume_id", name="uq_job_match_batch_item_resume"),
        Index("ix_job_match_batch_item_claim", "status", "next_attempt_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("job_match_batches.id"), index=True)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), index=True)
    fact_snapshot_id: Mapped[str] = mapped_column(ForeignKey("resume_fact_snapshots.id"), index=True)
    facts_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    job_match_id: Mapped[str | None] = mapped_column(ForeignKey("job_matches.id"), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    batch: Mapped[JobMatchBatch] = relationship(back_populates="items")
    resume: Mapped[Resume] = relationship()
    fact_snapshot: Mapped[ResumeFactSnapshot] = relationship()
    job_match: Mapped[JobMatch | None] = relationship()
