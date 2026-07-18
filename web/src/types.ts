/**
 * TypeScript representations of the public FastAPI contracts in app/schemas.py.
 * Dates stay as strings because the API serializes them as ISO-8601 text.
 */

export type DegreeLevel =
  | "unknown"
  | "associate"
  | "bachelor"
  | "master"
  | "doctor";

export type ExperienceType =
  | "employment"
  | "internship"
  | "project"
  | "competition"
  | "other"
  | "unknown";

export type JobRequirementPriority = "must_have" | "preferred";

export type JobRequirementCategory =
  | "skill"
  | "experience"
  | "education"
  | "major"
  | "keyword"
  | "other";

export type JobMatchOutcome = "met" | "partial" | "not_met" | "unknown";

/**
 * Server-owned lifecycle for the asynchronous AI fact extraction job.
 * This is deliberately separate from `extraction_status`, which describes
 * native-PDF parsing and the human-review lifecycle.
 */
export type AiExtractionStatus =
  | "queued"
  | "running"
  | "completed"
  | "needs_attention"
  | "unavailable";

export type JsonObject = Record<string, unknown>;

export interface CandidateCreateInput {
  display_name?: string | null;
}

export interface CandidateCreated {
  candidate_id: string;
}

export interface MailboxConfig {
  configured: boolean;
  imap_host: string | null;
  imap_port: number | null;
  email_address: string | null;
  mailbox: string | null;
  enabled: boolean;
  password_configured: boolean;
  import_started_at: string | null;
  last_synced_at: string | null;
  last_sync_error: string | null;
}

export interface MailboxConfigUpdate {
  imap_host: string;
  imap_port: number;
  email_address: string;
  mailbox: string;
  password?: string;
  enabled: boolean;
}

export interface MailboxSync {
  configured: boolean;
  imported_count: number;
  duplicate_count: number;
  skipped_count: number;
  failed_count: number;
  last_synced_at: string | null;
  last_sync_error: string | null;
}

export interface MailboxImportHistoryItem {
  attachment_filename: string;
  status: string;
  error: string | null;
  resume_id: string | null;
  created_at: string;
}

export interface MailboxImportHistory {
  items: MailboxImportHistoryItem[];
  total: number;
}

export type RecruitingAgentIntent =
  | "search_candidates"
  | "run_job_matching"
  | "show_job_ranking"
  | "explain_candidate"
  | "score_current_candidate"
  | "help";

export interface RecruitingAgentTurnInput {
  message: string;
  job_version_id?: string | null;
  resume_id?: string | null;
}

export interface RecruitingAgentCandidate {
  candidate_id: string;
  resume_id: string;
  display_name: string | null;
  detail: string;
  score: number | null;
}

export interface RecruitingAgentAction {
  action: "open_resume" | "open_match_workspace";
  label: string;
  resume_id: string | null;
}

export interface RecruitingAgentToolTrace {
  tool: string;
  summary: string;
}

export interface RecruitingAgentTurn {
  message: string;
  intent: RecruitingAgentIntent;
  job_version_id: string | null;
  candidates: RecruitingAgentCandidate[];
  actions: RecruitingAgentAction[];
  tool_trace: RecruitingAgentToolTrace[];
  batch_id: string | null;
}

export interface ResumeUploadResponse {
  resume_id: string;
  candidate_id: string;
  /** null until AI finds a source-grounded candidate name. */
  candidate_display_name: string | null;
  extraction_status: string;
  ai_extraction_status: AiExtractionStatus;
  ai_extraction_error: string | null;
  source_page_count: number;
  parsed_page_count: number;
  quality_flags: string[];
}

export interface ResumeReviewQueueItem {
  resume_id: string;
  candidate_id: string;
  candidate_display_name: string | null;
  original_filename: string;
  extraction_status: string;
  ai_extraction_status: AiExtractionStatus;
  ai_extraction_error: string | null;
  quality_flags: string[];
  created_at: string;
}

export interface ResumeReviewQueueResponse {
  items: ResumeReviewQueueItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface ResumeDetail {
  resume_id: string;
  candidate_id: string;
  candidate_display_name: string | null;
  extraction_status: string;
  ai_extraction_status: AiExtractionStatus;
  ai_extraction_error: string | null;
  is_active: boolean;
  /** null means the school decision still needs a reviewer. */
  is_985_211: boolean | null;
  highest_degree: DegreeLevel | null;
  employment_months: number;
  employment_or_internship_months: number;
  source_page_count: number;
  parsed_page_count: number;
  quality_flags: string[];
}

export interface ResumeSourceBlock {
  block_id: string;
  page_no: number;
  block_type: string;
  text: string;
}

export interface ResumeEducation {
  school_name_raw: string;
  school_match_state: string;
  degree: DegreeLevel;
  major_raw: string | null;
  start_month: string | null;
  end_month: string | null;
  evidence_block_ids: string[];
}

export interface ResumeExperience {
  experience_type: ExperienceType;
  experience_name_raw: string | null;
  organization_name_raw: string | null;
  title_raw: string | null;
  start_month: string | null;
  end_month: string | null;
  is_current: boolean;
  evidence_block_ids: string[];
  classification_evidence_block_ids: string[];
  detail_items: ResumeExperienceDetailItem[];
}

export interface ResumeExperienceDetailItem {
  detail_raw: string;
  evidence_block_ids: string[];
}

export interface ResumeSkill {
  skill_display: string;
  evidence_block_ids: string[];
}

export interface ResumeReviewAction {
  action: string;
  actor: string;
  note: string | null;
  created_at: string;
}

export interface ResumeReviewDetail extends ResumeDetail {
  original_filename: string;
  facts_version: number;
  source_blocks: ResumeSourceBlock[];
  education: ResumeEducation[];
  experiences: ResumeExperience[];
  skills: ResumeSkill[];
  review_actions: ResumeReviewAction[];
}

export interface EducationFactInput {
  school_name_raw: string;
  degree?: DegreeLevel;
  major_raw?: string | null;
  start_month?: string | null;
  end_month?: string | null;
  evidence_block_ids: string[];
}

export interface ExperienceFactInput {
  experience_type: ExperienceType;
  experience_name_raw?: string | null;
  organization_name_raw?: string | null;
  title_raw?: string | null;
  start_month?: string | null;
  end_month?: string | null;
  is_current?: boolean;
  evidence_block_ids: string[];
  classification_evidence_block_ids?: string[];
  detail_items?: ResumeExperienceDetailItem[];
}

export interface SkillFactInput {
  skill_display: string;
  evidence_block_ids: string[];
}

export interface ResumeFactsSubmission {
  schema_version?: "resume_facts.v1";
  education?: EducationFactInput[];
  experiences?: ExperienceFactInput[];
  skills?: SkillFactInput[];
}

export interface ResumeFactsSaveRequest {
  facts: ResumeFactsSubmission;
  complete_review?: boolean;
  review_note?: string | null;
  /** Only valid when complete_review is true. */
  is_985_211_override?: boolean | null;
}

export interface ResumeActivateRequest {
  note?: string | null;
}

export interface EducationFilter {
  degree_in?: DegreeLevel[];
  school_name_contains?: string[];
  major_contains?: string[];
}

export interface ExperienceFilter {
  experience_types?: ExperienceType[];
  organization_name_contains?: string[];
  title_contains?: string[];
}

export interface CandidateSearchRequest {
  is_985_211?: boolean | null;
  min_employment_months?: number | null;
  min_employment_or_internship_months?: number | null;
  education_any_of?: EducationFilter[];
  experience_any_of?: ExperienceFilter[];
  skills_all_of?: string[];
  skills_any_of?: string[];
  keywords_all_of?: string[];
  keywords_any_of?: string[];
  limit?: number;
  cursor?: string | null;
}

export interface CandidateSearchMatch {
  filter_key: string;
  label: string;
  fact_type: "aggregate" | "education" | "experience" | "skill" | "keyword";
  evidence_block_ids: string[];
}

export interface CandidateSearchItem {
  candidate_id: string;
  display_name: string | null;
  resume_id: string;
  original_filename: string;
  is_985_211: boolean;
  highest_degree: DegreeLevel | null;
  employment_months: number;
  employment_or_internship_months: number;
  summary_preview: string | null;
  score_total: number | null;
  score_template_name: string | null;
  matched_filters: string[];
  matched_evidence: CandidateSearchMatch[];
}

export interface CandidateSearchResponse {
  items: CandidateSearchItem[];
  next_cursor: string | null;
  needs_review_count: number;
}

export interface ResumeLibraryItem {
  resume_id: string;
  candidate_id: string;
  display_name: string | null;
  original_filename: string;
  created_at: string;
  extraction_status: string;
  ai_extraction_status: AiExtractionStatus;
  ai_extraction_error: string | null;
  is_active: boolean;
  summary_preview: string | null;
  summary_created_at: string | null;
  score_total: number | null;
  score_status: string | null;
  score_template_name: string | null;
  score_created_at: string | null;
}

export interface ResumeLibraryResponse {
  items: ResumeLibraryItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface SavedFilterCreate {
  name: string;
  filters: CandidateSearchRequest;
}

export interface SavedFilter {
  saved_filter_id: string;
  name: string;
  filters: CandidateSearchRequest;
  created_at: string;
  updated_at: string;
}

export interface ScoreDimensionInput {
  key: string;
  label: string;
  weight: number;
  max_raw_score?: number;
  guidance?: string | null;
}

export interface ScoreTemplateCreate {
  name: string;
  description?: string | null;
  dimensions: ScoreDimensionInput[];
}

export interface ScoreTemplate {
  template_id: string;
  name: string;
  description: string | null;
  version: number;
  dimensions: ScoreDimensionInput[];
}

export interface ResumeScoreDimension {
  key: string;
  label: string;
  weight: number;
  max_raw_score: number;
  ai_raw_score: number;
  final_raw_score: number;
  /** Final weighted contribution; kept for compatibility with earlier API responses. */
  weighted_score: number;
  ai_weighted_score: number;
  final_weighted_score: number;
  rationale: string;
  fact_ids: string[];
  fact_evidence: ResumeScoreFactEvidence[];
  evidence_state: "grounded" | "insufficient_information";
  uncertainties: string[];
  manual_reason: string | null;
  adjusted_at: string | null;
  manual_adjustment: ResumeScoreManualAdjustment | null;
}

export interface ResumeScoreFactEvidence {
  fact_id: string;
  fact_type: "education" | "experience" | "skill" | "unknown";
  summary: string;
  evidence_block_ids: string[];
}

export interface ResumeScoreManualAdjustment {
  raw_score: number;
  reason: string;
  actor: string;
  adjusted_at: string;
}

export interface ResumeScoreRiskFlag {
  message: string;
  fact_ids: string[];
  fact_evidence: ResumeScoreFactEvidence[];
}

export interface ResumeScoreAnalysis {
  schema_version: string | null;
  overall_summary: string;
  risk_flags: ResumeScoreRiskFlag[];
  needs_human_review: boolean;
}

export interface ResumeScoreAuditEntry {
  audit_id: string;
  action: string;
  actor: string;
  reason: string | null;
  dimension_key: string | null;
  ai_raw_score: number | null;
  previous_final_raw_score: number | null;
  final_raw_score: number | null;
  facts_version: number | null;
  template_version: number | null;
  created_at: string;
}

export interface ResumeScore {
  score_id: string;
  resume_id: string;
  fact_snapshot_id: string | null;
  template_id: string;
  template_name: string | null;
  template_description: string | null;
  facts_version: number;
  template_version: number;
  fact_snapshot_created_at: string | null;
  is_current_facts_version: boolean;
  is_current_template_version: boolean;
  total_score: number;
  ai_total_score: number | null;
  dimension_scores: ResumeScoreDimension[];
  analysis: ResumeScoreAnalysis;
  audit_trail: ResumeScoreAuditEntry[];
  status: string;
  model_name: string | null;
  created_at: string;
}

export interface ResumeScoreCreate {
  template_id: string;
}

export interface ResumeScoreOverride {
  raw_score: number;
  reason: string;
}

export interface ResumeSummary {
  summary_id: string;
  resume_id: string;
  fact_snapshot_id: string | null;
  facts_version: number;
  content: JsonObject;
  source: string;
  supersedes_id: string | null;
  is_current: boolean;
  status: string;
  model_name: string | null;
  created_at: string;
}

export interface ResumeSummaryManualCreate {
  content: Record<string, string>;
}

export interface JobRequirements {
  must_have?: string[];
  preferred?: string[];
}

/**
 * AI-generated role description used by the authoring flow before a role is
 * enabled for matching. Requirements are kept alongside the generated JD so
 * the final save can create a match-ready job in one request.
 */
export interface JobDescriptionGeneration {
  title: string;
  jd_text: string;
  requirements?: JobRequirements;
}

export interface JobDescriptionGenerateInput {
  title: string;
  brief: string;
}

/** A source JD published exactly as supplied, without any AI request. */
export interface OriginalJobPublishInput {
  title: string;
  jd_text: string;
}

export interface JobCreate {
  title: string;
  jd_text: string;
  requirements?: JobRequirements;
}

export interface JobClause {
  clause_id: string;
  ordinal: number;
  text: string;
}

export interface JobRequirementInput {
  requirement_key?: string | null;
  priority: JobRequirementPriority;
  category: JobRequirementCategory;
  raw_requirement: string;
  terms?: string[];
  minimum_months?: number | null;
  clause_ids: string[];
}

export interface JobRequirement {
  requirement_id: string;
  requirement_key: string;
  priority: JobRequirementPriority;
  category: JobRequirementCategory;
  raw_requirement: string;
  terms: string[];
  minimum_months: number | null;
  weight: number;
  clause_ids: string[];
  sort_order: number;
}

export interface JobVersion {
  job_version_id: string;
  job_id: string;
  version: number;
  title: string;
  raw_text: string;
  status: "draft" | "confirmed" | "archived";
  created_at: string;
  confirmed_at: string | null;
  clauses: JobClause[];
  requirements: JobRequirement[];
}

export interface JobVersionRequirementsUpdate {
  title: string;
  requirements?: JobRequirementInput[];
}

export interface JobMatchCreate {
  job_version_id: string;
}

export interface JobMatchBatch {
  batch_id: string;
  job_version_id: string;
  status: string;
  total_count: number;
  completed_count: number;
  failed_count: number;
  requested_at: string;
  started_at: string | null;
  completed_at: string | null;
  last_error: string | null;
}

export interface JobMatchBatchItem {
  item_id: string;
  resume_id: string;
  candidate_id: string;
  candidate_display_name: string | null;
  facts_version: number;
  status: string;
  attempt_count: number;
  last_error: string | null;
  job_match_id: string | null;
  completed_at: string | null;
  updated_at: string;
}

export interface JobMatchRequirementResult {
  requirement_id: string;
  requirement_key: string;
  priority: JobRequirementPriority;
  requirement_text: string;
  clause_ids: string[];
  outcome: JobMatchOutcome;
  reason: string;
  fact_ids: string[];
  missing_or_uncertain: string | null;
  score_contribution: number;
}

export interface JobMatch {
  match_id: string;
  job_id: string;
  job_version_id: string | null;
  resume_id: string;
  candidate_id: string;
  candidate_display_name: string | null;
  fact_snapshot_id: string | null;
  facts_version: number;
  job_version: number;
  total_score: number;
  must_have_passed: boolean | null;
  evidence_coverage: number | null;
  hard_requirement_status: string | null;
  analysis: JsonObject;
  requirement_results: JobMatchRequirementResult[];
  status: string;
  model_name: string | null;
  created_at: string;
}
