from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.normalization import normalized_key


Month = str
DegreeLevel = Literal["unknown", "associate", "bachelor", "master", "doctor"]
ExperienceType = Literal[
    "employment",
    "internship",
    "project",
    "competition",
    "other",
    "unknown",
]

MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
CANDIDATE_NAME_LABEL_PATTERN = re.compile(
    r"(?i)^\s*(?:\u59d3\u540d|name)\s*[:\uff1a]"
)
CANDIDATE_NAME_UNSAFE_CHARACTER_PATTERN = re.compile(r"[\r\n@]")


def clean_string_list(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized:
            raise ValueError("list values must not be blank")
        if not normalized_key(normalized):
            raise ValueError("list values must contain searchable characters")
        if normalized not in seen:
            seen.add(normalized)
            cleaned.append(normalized)
    return cleaned


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthLogin(ApiModel):
    password: str = Field(min_length=1, max_length=512)


class AuthSession(ApiModel):
    authenticated: bool
    login_required: bool


class RecruitingAgentRequest(ApiModel):
    """One bounded recruiting-assistant turn.

    The browser supplies only the user's current selection.  The assistant
    never receives a PDF or unrestricted database access from the client.
    """

    message: str = Field(min_length=1, max_length=2000)
    job_version_id: str | None = Field(default=None, max_length=64)
    resume_id: str | None = Field(default=None, max_length=64)


class RecruitingAgentCandidate(ApiModel):
    candidate_id: str
    resume_id: str
    display_name: str | None
    detail: str
    score: float | None = None


class RecruitingAgentAction(ApiModel):
    action: Literal["open_resume", "open_match_workspace"]
    label: str
    resume_id: str | None = None


class RecruitingAgentToolTrace(ApiModel):
    tool: str
    summary: str


class RecruitingAgentResponse(ApiModel):
    message: str
    intent: Literal[
        "search_candidates",
        "run_job_matching",
        "show_job_ranking",
        "explain_candidate",
        "help",
    ]
    job_version_id: str | None = None
    candidates: list[RecruitingAgentCandidate] = Field(default_factory=list)
    actions: list[RecruitingAgentAction] = Field(default_factory=list)
    tool_trace: list[RecruitingAgentToolTrace] = Field(default_factory=list)
    batch_id: str | None = None


class CandidateCreate(ApiModel):
    display_name: str | None = Field(default=None, max_length=200)


class CandidateCreated(ApiModel):
    candidate_id: str


class ResumeUploadResponse(ApiModel):
    resume_id: str
    candidate_id: str
    candidate_display_name: str | None
    extraction_status: str
    ai_extraction_status: str
    ai_extraction_error: str | None
    source_page_count: int
    parsed_page_count: int
    quality_flags: list[str]


class ResumeReviewQueueItem(ApiModel):
    resume_id: str
    candidate_id: str
    candidate_display_name: str | None
    original_filename: str
    extraction_status: str
    ai_extraction_status: str
    ai_extraction_error: str | None
    quality_flags: list[str]
    created_at: datetime


class ResumeReviewQueueResponse(ApiModel):
    items: list[ResumeReviewQueueItem]
    total: int
    page: int
    page_size: int


class ResumeDetail(ApiModel):
    resume_id: str
    candidate_id: str
    candidate_display_name: str | None
    extraction_status: str
    ai_extraction_status: str
    ai_extraction_error: str | None
    is_active: bool
    is_985_211: bool | None
    highest_degree: DegreeLevel | None
    employment_months: int
    employment_or_internship_months: int
    source_page_count: int
    parsed_page_count: int
    quality_flags: list[str]


class ResumeSourceBlockResponse(ApiModel):
    block_id: str
    page_no: int
    block_type: str
    text: str


class ResumeEducationResponse(ApiModel):
    school_name_raw: str
    school_match_state: str
    degree: DegreeLevel
    major_raw: str | None
    start_month: Month | None
    end_month: Month | None
    evidence_block_ids: list[str]


class ResumeExperienceDetailResponse(ApiModel):
    detail_raw: str
    evidence_block_ids: list[str]


class ResumeExperienceResponse(ApiModel):
    experience_type: ExperienceType
    experience_name_raw: str | None
    organization_name_raw: str | None
    title_raw: str | None
    start_month: Month | None
    end_month: Month | None
    is_current: bool
    evidence_block_ids: list[str]
    classification_evidence_block_ids: list[str]
    detail_items: list[ResumeExperienceDetailResponse]


class ResumeSkillResponse(ApiModel):
    skill_display: str
    evidence_block_ids: list[str]


class ResumeReviewActionResponse(ApiModel):
    action: str
    actor: str
    note: str | None
    created_at: str


class ResumeReviewDetail(ResumeDetail):
    original_filename: str
    facts_version: int
    source_blocks: list[ResumeSourceBlockResponse]
    education: list[ResumeEducationResponse]
    experiences: list[ResumeExperienceResponse]
    skills: list[ResumeSkillResponse]
    review_actions: list[ResumeReviewActionResponse]


class EducationFact(ApiModel):
    school_name_raw: str = Field(min_length=1, max_length=255)
    degree: DegreeLevel = "unknown"
    # Produced by the AI rulebook only. Manual save paths may omit both fields
    # and the backend still performs its own local-registry calculation.
    ai_985_211_judgment: bool = False
    ai_institution_roster_id: str | None = Field(default=None, max_length=64)
    major_raw: str | None = Field(default=None, max_length=255)
    start_month: Month | None = None
    end_month: Month | None = None
    evidence_block_ids: list[str] = Field(min_length=1, max_length=8)

    @field_validator("start_month", "end_month")
    @classmethod
    def valid_month(cls, value: Month | None) -> Month | None:
        if value is not None and not MONTH_PATTERN.fullmatch(value):
            raise ValueError("month must use YYYY-MM")
        return value

    @field_validator("evidence_block_ids")
    @classmethod
    def valid_evidence_block_ids(cls, value: list[str]) -> list[str]:
        return clean_string_list(value)

    @model_validator(mode="after")
    def valid_date_range(self) -> "EducationFact":
        if self.start_month and self.end_month and self.end_month < self.start_month:
            raise ValueError("end_month must not be earlier than start_month")
        return self


class ExperienceDetailItem(ApiModel):
    """One verbatim, source-cited responsibility or contribution."""

    detail_raw: str = Field(min_length=1, max_length=800)
    evidence_block_ids: list[str] = Field(min_length=1, max_length=4)

    @field_validator("detail_raw")
    @classmethod
    def valid_detail_raw(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or not normalized_key(normalized):
            raise ValueError("detail_raw must contain searchable characters")
        return normalized

    @field_validator("evidence_block_ids")
    @classmethod
    def valid_evidence_block_ids(cls, value: list[str]) -> list[str]:
        return clean_string_list(value)


class ExperienceFact(ApiModel):
    experience_type: ExperienceType
    experience_name_raw: str | None = Field(default=None, max_length=255)
    organization_name_raw: str | None = Field(default=None, max_length=255)
    title_raw: str | None = Field(default=None, max_length=255)
    start_month: Month | None = None
    end_month: Month | None = None
    is_current: bool = False
    evidence_block_ids: list[str] = Field(min_length=1, max_length=8)
    classification_evidence_block_ids: list[str] = Field(default_factory=list, max_length=8)
    detail_items: list[ExperienceDetailItem] = Field(default_factory=list, max_length=12)

    @field_validator("start_month", "end_month")
    @classmethod
    def valid_month(cls, value: Month | None) -> Month | None:
        if value is not None and not MONTH_PATTERN.fullmatch(value):
            raise ValueError("month must use YYYY-MM")
        return value

    @field_validator("evidence_block_ids", "classification_evidence_block_ids")
    @classmethod
    def valid_evidence_block_ids(cls, value: list[str]) -> list[str]:
        return clean_string_list(value)

    @model_validator(mode="after")
    def enforce_work_context(self) -> "ExperienceFact":
        if self.experience_type in {"employment", "internship"}:
            if not self.organization_name_raw or not self.title_raw:
                raise ValueError(
                    "employment and internship require organization_name_raw and title_raw"
                )
            if not self.classification_evidence_block_ids:
                raise ValueError(
                    "employment and internship require classification_evidence_block_ids"
                )
        if self.start_month and self.end_month and self.end_month < self.start_month:
            raise ValueError("end_month must not be earlier than start_month")
        if self.is_current and self.end_month:
            raise ValueError("current experience must not have end_month")
        return self


class SkillFact(ApiModel):
    skill_display: str = Field(min_length=1, max_length=120)
    evidence_block_ids: list[str] = Field(min_length=1, max_length=4)

    @field_validator("evidence_block_ids")
    @classmethod
    def valid_evidence_block_ids(cls, value: list[str]) -> list[str]:
        return clean_string_list(value)


class ResumeFactsSubmission(ApiModel):
    schema_version: Literal["resume_facts.v1"] = "resume_facts.v1"
    # Identity is used only to name the candidate record after AI extraction.
    # It is intentionally excluded from the immutable fact snapshot consumed
    # by summaries, scoring, and JD matching.
    candidate_name_raw: str | None = Field(default=None, max_length=80)
    candidate_name_evidence_block_ids: list[str] = Field(
        default_factory=list,
        max_length=2,
    )
    education: list[EducationFact] = Field(default_factory=list, max_length=8)
    experiences: list[ExperienceFact] = Field(default_factory=list, max_length=20)
    skills: list[SkillFact] = Field(default_factory=list, max_length=50)

    @field_validator("candidate_name_raw")
    @classmethod
    def valid_candidate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if CANDIDATE_NAME_LABEL_PATTERN.search(cleaned):
            raise ValueError("candidate_name_raw_must_not_include_label")
        if CANDIDATE_NAME_UNSAFE_CHARACTER_PATTERN.search(cleaned):
            raise ValueError("candidate_name_raw_contains_unsafe_character")
        return cleaned

    @field_validator("candidate_name_evidence_block_ids")
    @classmethod
    def valid_candidate_name_evidence_block_ids(cls, value: list[str]) -> list[str]:
        return clean_string_list(value)

    @model_validator(mode="after")
    def has_at_least_one_fact(self) -> "ResumeFactsSubmission":
        if self.candidate_name_raw and not self.candidate_name_evidence_block_ids:
            raise ValueError("candidate_name_requires_evidence_block_id")
        if not self.candidate_name_raw and self.candidate_name_evidence_block_ids:
            raise ValueError("candidate_name_evidence_requires_candidate_name")
        if not (self.education or self.experiences or self.skills):
            raise ValueError("at least one structured fact is required")
        return self


class ResumeFactsSaveRequest(ApiModel):
    facts: ResumeFactsSubmission
    complete_review: bool = False
    review_note: str | None = Field(default=None, max_length=1000)
    # A manual decision is only allowed while completing review.  Automatic
    # extraction must never turn an unresolved school name into false.
    is_985_211_override: bool | None = None

    @model_validator(mode="after")
    def valid_manual_override(self) -> "ResumeFactsSaveRequest":
        if self.is_985_211_override is not None and not self.complete_review:
            raise ValueError("is_985_211_override_requires_complete_review")
        return self


class ResumeActivateRequest(ApiModel):
    note: str | None = Field(default=None, max_length=1000)


class EducationFilter(ApiModel):
    degree_in: list[DegreeLevel] = Field(default_factory=list, max_length=5)
    school_name_contains: list[str] = Field(default_factory=list, max_length=8)
    major_contains: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("school_name_contains", "major_contains")
    @classmethod
    def valid_text_filters(cls, value: list[str]) -> list[str]:
        return clean_string_list(value)


class ExperienceFilter(ApiModel):
    experience_types: list[ExperienceType] = Field(
        default_factory=lambda: ["employment", "internship"],
        max_length=5,
    )
    organization_name_contains: list[str] = Field(default_factory=list, max_length=8)
    title_contains: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("organization_name_contains", "title_contains")
    @classmethod
    def valid_text_filters(cls, value: list[str]) -> list[str]:
        return clean_string_list(value)


class CandidateSearchRequest(ApiModel):
    is_985_211: bool | None = None
    min_employment_months: int | None = Field(default=None, ge=0, le=720)
    min_employment_or_internship_months: int | None = Field(default=None, ge=0, le=720)
    education_any_of: list[EducationFilter] = Field(default_factory=list, max_length=10)
    experience_any_of: list[ExperienceFilter] = Field(default_factory=list, max_length=10)
    skills_all_of: list[str] = Field(default_factory=list, max_length=20)
    skills_any_of: list[str] = Field(default_factory=list, max_length=20)
    keywords_all_of: list[str] = Field(default_factory=list, max_length=10)
    keywords_any_of: list[str] = Field(default_factory=list, max_length=10)
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator(
        "skills_all_of",
        "skills_any_of",
        "keywords_all_of",
        "keywords_any_of",
    )
    @classmethod
    def valid_skill_filters(cls, value: list[str]) -> list[str]:
        return clean_string_list(value)


class CandidateSearchItem(ApiModel):
    candidate_id: str
    display_name: str | None
    resume_id: str
    is_985_211: bool
    highest_degree: DegreeLevel | None
    employment_months: int
    matched_filters: list[str]
    matched_evidence: list["CandidateSearchMatch"] = Field(default_factory=list)


class CandidateSearchMatch(ApiModel):
    filter_key: str
    label: str
    fact_type: Literal["aggregate", "education", "experience", "skill", "keyword"]
    evidence_block_ids: list[str]


class CandidateSearchResponse(ApiModel):
    items: list[CandidateSearchItem]
    next_cursor: str | None = None
    needs_review_count: int = 0


class ResumeLibraryItem(ApiModel):
    """A compact, recruiter-facing row for the persistent resume library."""

    resume_id: str
    candidate_id: str
    display_name: str | None
    original_filename: str
    created_at: str
    extraction_status: str
    ai_extraction_status: str
    ai_extraction_error: str | None = None
    is_active: bool
    summary_preview: str | None = None
    summary_created_at: str | None = None
    score_total: float | None = None
    score_status: str | None = None
    score_template_name: str | None = None
    score_created_at: str | None = None


class ResumeLibraryResponse(ApiModel):
    items: list[ResumeLibraryItem]
    total: int
    page: int
    page_size: int


class SavedFilterCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    filters: CandidateSearchRequest

    @model_validator(mode="after")
    def no_cursor_in_saved_filter(self) -> "SavedFilterCreate":
        if self.filters.cursor is not None:
            raise ValueError("saved_filter_cannot_include_cursor")
        return self


class SavedFilterResponse(ApiModel):
    saved_filter_id: str
    name: str
    filters: CandidateSearchRequest
    created_at: str
    updated_at: str


class ScoreDimensionInput(ApiModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    label: str = Field(min_length=1, max_length=120)
    weight: int = Field(ge=0, le=100)
    max_raw_score: int = Field(default=100, ge=1, le=100)
    guidance: str | None = Field(default=None, max_length=1000)


class ScoreTemplateCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    dimensions: list[ScoreDimensionInput] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def valid_weights_and_keys(self) -> "ScoreTemplateCreate":
        if sum(item.weight for item in self.dimensions) != 100:
            raise ValueError("dimension weights must sum to 100")
        keys = [item.key for item in self.dimensions]
        if len(keys) != len(set(keys)):
            raise ValueError("dimension keys must be unique")
        return self


class ScoreTemplateResponse(ApiModel):
    template_id: str
    name: str
    description: str | None
    version: int
    dimensions: list[ScoreDimensionInput]


class ResumeScoreResponse(ApiModel):
    score_id: str
    resume_id: str
    fact_snapshot_id: str | None
    template_id: str
    facts_version: int
    template_version: int
    total_score: float
    ai_total_score: float | None
    dimension_scores: list[dict[str, object]]
    analysis: dict[str, object]
    status: str
    model_name: str | None
    created_at: str


class ResumeScoreCreate(ApiModel):
    template_id: str


class ResumeScoreOverride(ApiModel):
    raw_score: float = Field(ge=0, le=100)
    reason: str = Field(min_length=1, max_length=1000)


class ResumeSummaryResponse(ApiModel):
    summary_id: str
    resume_id: str
    fact_snapshot_id: str | None
    facts_version: int
    content: dict[str, object]
    source: str
    supersedes_id: str | None
    is_current: bool
    status: str
    model_name: str | None
    created_at: str


class ResumeSummaryManualCreate(ApiModel):
    content: dict[str, str]

    @model_validator(mode="after")
    def non_empty_content(self) -> "ResumeSummaryManualCreate":
        if not self.content or not any(value.strip() for value in self.content.values()):
            raise ValueError("manual_summary_content_must_not_be_empty")
        if any(not key.strip() or not value.strip() for key, value in self.content.items()):
            raise ValueError("manual_summary_sections_must_not_be_blank")
        return self


class JobRequirements(ApiModel):
    must_have: list[str] = Field(default_factory=list, max_length=20)
    preferred: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("must_have", "preferred")
    @classmethod
    def valid_requirements(cls, value: list[str]) -> list[str]:
        return clean_string_list(value)


class JobCreate(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    jd_text: str = Field(min_length=1, max_length=20000)
    requirements: JobRequirements = Field(default_factory=JobRequirements)


class JobResponse(ApiModel):
    job_id: str
    title: str
    jd_text: str
    requirements: JobRequirements
    version: int


JobRequirementPriority = Literal["must_have", "preferred"]
JobRequirementCategory = Literal[
    "skill",
    "experience",
    "education",
    "major",
    "keyword",
    "other",
]


class JobClauseResponse(ApiModel):
    clause_id: str
    ordinal: int
    text: str


class JobRequirementInput(ApiModel):
    # Keep this compatible with the strict JD-provider contract.  The model is
    # allowed to issue stable keys such as `requirement-001`, while manually
    # created requirements can still use the shorter `req-001` form.
    requirement_key: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_-]{1,63}$",
    )
    priority: JobRequirementPriority
    category: JobRequirementCategory
    raw_requirement: str = Field(min_length=1, max_length=1000)
    terms: list[str] = Field(default_factory=list, max_length=10)
    minimum_months: int | None = Field(default=None, ge=0, le=720)
    clause_ids: list[str] = Field(min_length=1, max_length=20)

    @field_validator("terms", "clause_ids")
    @classmethod
    def valid_requirement_lists(cls, value: list[str]) -> list[str]:
        return clean_string_list(value)


class JobRequirementResponse(ApiModel):
    requirement_id: str
    requirement_key: str
    priority: JobRequirementPriority
    category: JobRequirementCategory
    raw_requirement: str
    terms: list[str]
    minimum_months: int | None
    weight: int
    clause_ids: list[str]
    sort_order: int


class JobVersionResponse(ApiModel):
    job_version_id: str
    job_id: str
    version: int
    title: str
    raw_text: str
    status: Literal["draft", "confirmed", "archived"]
    created_at: str
    confirmed_at: str | None
    clauses: list[JobClauseResponse]
    requirements: list[JobRequirementResponse]


class JobVersionRequirementsUpdate(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    requirements: list[JobRequirementInput] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def unique_requirement_keys(self) -> "JobVersionRequirementsUpdate":
        explicit_keys = [
            requirement.requirement_key
            for requirement in self.requirements
            if requirement.requirement_key is not None
        ]
        if len(explicit_keys) != len(set(explicit_keys)):
            raise ValueError("job_requirement_keys_must_be_unique")
        return self


class JobMatchCreate(ApiModel):
    job_version_id: str


class JobMatchBatchResponse(ApiModel):
    batch_id: str
    job_version_id: str
    status: str
    total_count: int
    completed_count: int
    failed_count: int
    requested_at: str
    started_at: str | None
    completed_at: str | None
    last_error: str | None


class JobMatchRequirementResponse(ApiModel):
    requirement_id: str
    requirement_key: str
    priority: JobRequirementPriority
    requirement_text: str
    clause_ids: list[str]
    outcome: Literal["met", "partial", "not_met", "unknown"]
    reason: str
    fact_ids: list[str]
    missing_or_uncertain: str | None
    score_contribution: float


class JobMatchResponse(ApiModel):
    match_id: str
    job_id: str
    job_version_id: str | None
    resume_id: str
    candidate_id: str
    candidate_display_name: str | None
    fact_snapshot_id: str | None
    facts_version: int
    job_version: int
    total_score: float
    must_have_passed: bool | None
    evidence_coverage: float | None
    hard_requirement_status: str | None
    analysis: dict[str, object]
    requirement_results: list[JobMatchRequirementResponse]
    status: str
    model_name: str | None
    created_at: str
