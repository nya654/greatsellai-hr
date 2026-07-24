import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  api,
  isApiError,
} from "./api";
import {
  LandingPage,
  ROOT_WORKSPACE_BASE_PATH,
} from "./landing";
import type {
  AiExtractionStatus,
  AuthLoginInput,
  AuthRegistrationInput,
  AuthSession,
  CandidateSearchDisplayFieldKey,
  CandidateDataAuditEvent,
  CandidateDataDeletionBatch,
  CandidateDataDeletionReason,
  CandidateDataExport,
  CandidateDataRetentionCleanupRun,
  CandidateDataRetentionMode,
  CandidateDataRetentionPolicy,
  CandidateDataRetentionPreview,
  CandidateSearchItem,
  CandidateSearchRequest,
  CandidateSearchResponse,
  AwardLevel,
  DegreeLevel,
  ExperienceType,
  FilterOptions,
  InstitutionClassification,
  InstitutionTier,
  LanguageCredentialCode,
  LeadershipContext,
  PresenceStatus,
  ScholarshipLevel,
  JobMatch,
  JobVersion,
  ResumeDetail,
  ResumeLibraryItem,
  ResumeReviewDetail,
  ResumeScore,
  ResumeSummary,
  ResumeUploadResponse,
  RegistrationOffer,
  RecruitingAgentAction,
  RecruitingAgentCandidate,
  RecruitingAgentSearchSummary,
  RecruitingAgentTurn,
  SavedFilter,
  ScoreTemplate,
  TalentSearchHardFilters,
  TalentSearchProfile,
  TalentSearchProfileMatchResult,
  TalentSearchRun,
  TrialAccess,
} from "./types";
import { Icon, type IconName } from "./icons";
import { TableSkeleton } from "./backoffice/ui/TableSkeleton";
import { BackofficeButton } from "./backoffice/ui/BackofficeButton";
import {
  AI_STATUS_POLL_INTERVAL_MS,
  aiExtractionIsInProgress,
} from "./backoffice/utils/ai-extraction";
import { formatFileSize, formatLibraryDate } from "./backoffice/utils/formatters";
import {
  hasSourceTextQualityIssue,
  hasSupersededReparseVersion,
} from "./backoffice/utils/resume-source-quality";
import {
  canPreviewInline,
  isSupportedResumeFile,
  resumeFileExtension,
  resumeFileTypeLabel,
} from "./backoffice/utils/resume-file";
import { MailboxPage } from "./features/mailbox/MailboxPage";
import { mailboxImportErrorMessages } from "./features/mailbox/mailbox-model";
import { ResumeLibraryPage } from "./features/library/ResumeLibraryPage";
import { CandidateDrawer } from "./features/candidate-drawer/CandidateDrawer";
import { FilterWorkspace } from "./features/filter/FilterWorkspace";
import { ScoreWorkspace } from "./features/scoring/ScoreWorkspace";
import { MatchWorkspace } from "./features/job-match/MatchWorkspace";
import {
  degreeLabels,
  experienceTypeOptions,
  formatDuration,
  institutionClassificationLabel,
  institutionClassificationLabels,
  institutionClassificationOptions,
  sortInstitutionClassifications,
  type FilterDraft,
} from "./features/filter/filter-model";
import type {
  CandidateDrawerTab as DrawerTab,
  SelectedResume,
} from "./features/candidate-drawer/candidate-drawer-types";

const AdminApp = lazy(() => import("./admin/AdminApp"));
const BackofficeUiProvider = lazy(() =>
  import("./backoffice/BackofficeUiProvider").then(({ BackofficeUiProvider: Provider }) => ({
    default: Provider,
  })),
);

type View = "library" | "filter" | "upload" | "score" | "match" | "settings";
type MainWorkspaceView = Exclude<View, "settings">;
type SettingsSection = "mailbox" | "data";
type ToastKind = "success" | "error";
type AuthRoute = "login" | "register" | "forgot-password" | "reset-password" | "verify-email";
type AppSurface =
  | { kind: "landing" }
  | { kind: "platform" }
  | { kind: "workspace"; authRoute: AuthRoute | null };

interface ToastMessage {
  id: number;
  kind: ToastKind;
  message: string;
}

type UploadStatus =
  "queued" | "uploading" | "extracting" | "success" | "attention" | "error";

interface UploadQueueItem {
  id: string;
  file: File;
  status: UploadStatus;
  idempotencyKey: string;
  response?: ResumeUploadResponse;
  error?: string;
  retryable?: boolean;
}

const emptySearch: CandidateSearchResponse = {
  items: [],
  next_cursor: null,
  needs_review_count: 0,
  total_count: 0,
};

const fallbackRegistrationOffer: RegistrationOffer = {
  plan_code: "advanced",
  plan_name: "进阶版",
  trial_days: 30,
  llm_call_limit: 1000,
};

const wholeNumberFormatter = new Intl.NumberFormat("zh-CN", {
  maximumFractionDigits: 0,
});

function formatWholeNumber(value: number): string {
  return wholeNumberFormatter.format(Math.max(0, Math.trunc(value)));
}

function accountAvatarInitials(displayName: string | null): string | null {
  const normalizedName = displayName?.trim();
  if (!normalizedName) return null;

  const hanCharacters = Array.from(normalizedName).filter((character) =>
    /[\u3400-\u9fff]/.test(character),
  );
  if (hanCharacters.length > 0) return hanCharacters.slice(0, 2).join("");

  const words = normalizedName.split(/\s+/).filter(Boolean);
  const initials = words
    .slice(0, 2)
    .map((word) => Array.from(word)[0]?.toUpperCase() ?? "")
    .join("");
  return initials || null;
}

const defaultFilterDraft: FilterDraft = {
  minEmploymentMonths: 0,
  minEmploymentOrInternshipMonths: 0,
  degrees: [],
  institutionClassifications: [],
  graduationStatus: "any",
  freshGraduateStartMonth: `${new Date().getFullYear()}-01`,
  freshGraduateEndMonth: `${new Date().getFullYear() + 1}-12`,
  schoolName: "",
  major: "",
  minAverageScore: "",
  minGpaPercent: "",
  maxRankPosition: "",
  maxRankPercent: "",
  experienceTypes: [],
  experienceName: "",
  company: "",
  title: "",
  experienceAwardLevels: [],
  experienceAwardResult: "",
  skills: [],
  skillCategories: [],
  skillsMode: "all",
  languageCredentials: [],
  languageScores: {},
  customLanguageName: "",
  scholarshipStatus: "any",
  scholarshipName: "",
  scholarshipLevels: [],
  competitionStatus: "any",
  competitionAwardStatus: "any",
  leadershipContexts: [],
  leadershipRoles: [],
  keywords: [],
  keywordsMode: "broad",
};

/**
 * Each supported resume file is normalized by the API. Keeping a queue avoids
 * competing writes while still letting a recruiter add a whole folder in one action.
 */
const BATCH_UPLOAD_CONCURRENCY = 1;
const MAX_BATCH_FILES = 100;

function aiExtractionStatusLabel(status: AiExtractionStatus): string {
  switch (status) {
    case "queued":
      return "已排队";
    case "running":
      return "提取中";
    case "completed":
      return "已完成，已启用";
    case "needs_attention":
      return "需要处理";
    case "unavailable":
      return "等待服务配置";
  }
}

function uploadStatusFromResponse(
  response: ResumeUploadResponse,
): UploadStatus {
  if (response.extraction_status === "failed") return "attention";
  if (response.ai_extraction_status === "completed") return "success";
  if (
    response.ai_extraction_status === "needs_attention" ||
    response.ai_extraction_status === "unavailable"
  )
    return "attention";
  return "extracting";
}

function withLatestAiExtractionStatus(
  uploaded: ResumeUploadResponse,
  detail: ResumeDetail,
): ResumeUploadResponse {
  return {
    ...uploaded,
    extraction_status: detail.extraction_status,
    ai_extraction_status: detail.ai_extraction_status,
    ai_extraction_error: detail.ai_extraction_error,
    source_page_count: detail.source_page_count,
    parsed_page_count: detail.parsed_page_count,
    quality_flags: detail.quality_flags,
  };
}

const degreeOptions: Array<{ value: DegreeLevel; label: string }> = [
  { value: "doctor", label: "博士" },
  { value: "master", label: "硕士" },
  { value: "bachelor", label: "本科" },
  { value: "associate", label: "大专" },
  { value: "high_school", label: "高中" },
  { value: "vocational_or_below", label: "中专/职高及以下" },
];

const legacyInstitutionTierLabels: Record<InstitutionTier, string> = {
  ...institutionClassificationLabels,
  "211": "211",
  "985": "985",
  double_first_class: "双一流",
  key_undergraduate: "重本",
  first_tier: "一本",
  second_tier: "二本",
  regular_undergraduate: "普通本科",
  private_undergraduate: "民办本科",
  higher_vocational: "高职/高专",
  overseas: "海外院校",
};

/**
 * A small subset of historical tiers is semantically identical to a new
 * classification. Everything else must be reselected rather than widened.
 */
const legacyTierClassificationMap: Partial<
  Record<InstitutionTier, InstitutionClassification[]>
> = {
  "985": ["985"],
  // The product now defines 211 as 211-only. A legacy saved "211" condition
  // therefore adopts the explicit new meaning instead of silently widening
  // back to 985 candidates.
  "211": ["211"],
  regular_undergraduate: ["undergraduate"],
  higher_vocational: ["associate"],
  overseas: ["overseas"],
};

const fallbackFilterOptions: FilterOptions = {
  schema_version: "filter-options.v2.fallback",
  degrees: degreeOptions,
  institution_classifications: institutionClassificationOptions,
  institution_tiers: [],
  experience_types: experienceTypeOptions,
  skill_categories: [
    { value: "software", label: "编程与开发" },
    { value: "data_ai", label: "数据与 AI" },
    { value: "product_project", label: "产品与项目" },
    { value: "design_content", label: "设计与内容" },
    { value: "marketing_ecommerce_operations", label: "市场、电商与运营" },
    { value: "sales_customer_service", label: "销售与客户服务" },
    { value: "supply_chain_logistics", label: "供应链与物流" },
    { value: "finance_legal_hr", label: "财务、法务与人力资源" },
    { value: "office_collaboration", label: "办公与协作工具" },
    { value: "industry_professional", label: "行业专业技能" },
  ],
  leadership_contexts: [
    { value: "class", label: "班级" },
    { value: "student_org", label: "学生会/校内组织" },
    { value: "club", label: "社团" },
    { value: "project_team", label: "项目组" },
    { value: "company", label: "公司" },
  ],
  award_levels: [
    { value: "national", label: "国家级" },
    { value: "provincial", label: "省级" },
    { value: "school", label: "校级" },
    { value: "department", label: "院系级" },
    { value: "other", label: "其他明确级别" },
  ],
  scholarship_levels: [
    { value: "national", label: "国家级" },
    { value: "provincial", label: "省级" },
    { value: "school", label: "校级" },
    { value: "department", label: "院系级" },
    { value: "enterprise", label: "企业/社会奖学金" },
    { value: "other", label: "其他明确级别" },
  ],
  language_credentials: [
    { value: "cet4", label: "大学英语四级（CET-4）" },
    { value: "cet6", label: "大学英语六级（CET-6）" },
    { value: "ielts", label: "雅思（IELTS）" },
    { value: "toefl", label: "托福（TOEFL）" },
    { value: "tem4", label: "英语专业四级（TEM-4）" },
    { value: "tem8", label: "英语专业八级（TEM-8）" },
    { value: "bec", label: "剑桥商务英语（BEC）" },
    { value: "toeic", label: "托业（TOEIC）" },
    { value: "custom", label: "其他英语证书（自定义填写）" },
  ],
  graduation_statuses: [
    { value: "any", label: "不限" },
    { value: "fresh", label: "应届" },
    { value: "previous", label: "往届" },
  ],
  presence_statuses: [
    { value: "any", label: "不限" },
    { value: "present", label: "有明确记录" },
    { value: "unknown", label: "未知" },
  ],
  keyword_modes: [
    { value: "broad", label: "泛匹配" },
    { value: "precise", label: "精准匹配" },
  ],
};


const navigation: Array<{ view: MainWorkspaceView; label: string; icon: IconName }> = [
  { view: "library", label: "简历库", icon: "folder" },
  { view: "filter", label: "筛选工作台", icon: "filter" },
  { view: "upload", label: "上传简历", icon: "upload" },
  { view: "score", label: "评分模板", icon: "layers" },
  { view: "match", label: "招聘详情", icon: "match" },
];

function settingsSectionFromHash(hash: string): SettingsSection | null {
  const value = hash
    .replace(/^#/, "")
    .trim()
    .replace(/^\/+|\/+$/g, "")
    .toLowerCase();

  if (value === "settings/mailbox" || value === "inbox") return "mailbox";
  if (value === "settings/data" || value === "data") return "data";
  return null;
}

function settingsHash(section: SettingsSection): string {
  return `#settings/${section}`;
}

const AUTO_FILTER_SEARCH_DELAY_MS = 350;

function freshDefaultFilter(): FilterDraft {
  return {
    ...defaultFilterDraft,
    degrees: [],
    institutionClassifications: [],
    experienceTypes: [],
    experienceAwardLevels: [],
    skills: [],
    skillCategories: [],
    languageCredentials: [],
    languageScores: {},
    scholarshipLevels: [],
    leadershipContexts: [],
    leadershipRoles: [],
    keywords: [],
  };
}

/**
 * The result table must describe the request that produced the rows, rather
 * than the controls a recruiter may be editing for their next search.  Keep a
 * shallow object copy plus copies of every mutable collection so the applied
 * request remains stable while the left-hand form changes.
 */
function snapshotFilterDraft(draft: FilterDraft): FilterDraft {
  return {
    ...draft,
    degrees: [...draft.degrees],
    institutionClassifications: [...draft.institutionClassifications],
    experienceTypes: [...draft.experienceTypes],
    experienceAwardLevels: [...draft.experienceAwardLevels],
    skills: [...draft.skills],
    skillCategories: [...draft.skillCategories],
    languageCredentials: [...draft.languageCredentials],
    languageScores: { ...draft.languageScores },
    scholarshipLevels: [...draft.scholarshipLevels],
    leadershipContexts: [...draft.leadershipContexts],
    leadershipRoles: [...draft.leadershipRoles],
    keywords: [...draft.keywords],
  };
}

function humanizeError(error: unknown): string {
  if (isApiError(error)) {
    const messages: Record<string, string> = {
      invalid_login_credentials: "邮箱或密码不正确，请重试。",
      email_already_registered: "该邮箱已注册，请直接登录或找回密码。",
      email_delivery_not_configured: "注册邮件服务正在配置中，请稍后再试。",
      registration_rate_limit_exceeded: "当前注册请求较多，请稍后再试。",
      email_verification_required: "请先完成工作邮箱验证后再进入工作台。",
      email_verification_invalid_or_expired: "这条验证链接无效或已过期，请重新发送验证邮件。",
      email_verification_account_mismatch: "当前浏览器已登录其他工作区，请先退出后再打开验证链接。",
      email_verification_resend_too_soon: "验证邮件刚刚发送，请稍候一分钟后再试。",
      email_verification_resend_limit_reached: "今天的验证邮件发送次数已达到上限，请明天再试。",
      invalid_registration_input: "请检查企业名称、姓名、邮箱和密码后重试。",
      password_too_short: "密码至少需要 8 个字符。",
      password_reset_invalid_or_expired: "这条重置链接无效、已过期或已被使用。请重新申请新的链接。",
      trial_expired: "试用期已结束。数据已保留，请联系 GreatSell AI 团队继续使用。",
      trial_llm_call_quota_exhausted:
        "本工作区的 1,000 次试用大模型调用已用完。数据仍会保留，请联系 GreatSell AI 团队继续使用。",
      organization_access_suspended: "当前工作区暂不可用，请联系 GreatSell AI 团队。",
      invalid_admin_token: "管理口令无效。请在右上角连接配置中更新后重试。",
      server_missing_admin_token: "服务器尚未配置管理口令，暂时无法访问。",
      deepseek_api_key_not_configured:
        "AI 服务尚未配置。请先在服务器环境变量中配置后重试。",
      talent_search_profile_not_found: "这份人才画像已不存在或无法访问。",
      talent_search_run_not_found: "这次找人记录已不存在或无法访问。",
      talent_search_profile_not_draft: "这份画像已不是可确认草案，请刷新后查看当前版本。",
      talent_search_profile_not_confirmed: "请先确认你当前看到的人才画像，再开始找人。",
      talent_search_profile_revision_not_current:
        "人才画像已在其他位置更新。请刷新并确认最新草案后再操作。",
      talent_search_profile_revision_superseded:
        "这版画像已被新的草案替代，请查看最新版本。",
      talent_search_profile_revision_missing: "人才画像版本不完整，请重新生成一版草案。",
      talent_search_profile_invalid_cursor: "候选人列表位置已失效，请点击刷新重新查看。",
      talent_search_profile_match_target_invalid:
        "这份画像的核验配置异常，请重新生成并确认后再找人。",
      talent_search_profile_provider_failed:
        "AI 人才画像暂时不可用，请稍后重新生成。",
      talent_search_profile_response_truncated:
        "本次需求较长，AI 未能完整生成画像。请精简后重试。",
      talent_search_profile_service_unavailable:
        "人才画像服务暂时不可用，请稍后重试。",
      resume_has_no_native_text_for_ai_extraction:
        "这份简历没有足够的可提取文字，暂时不能由 AI 提取。",
      resume_source_text_unavailable:
        "这份简历没有可用的提取文字，暂时不能由 AI 提取。",
      resume_source_text_unreliable:
        "这份简历的提取文本待校正，暂不能用于筛选、评分、总结或 JD 匹配。",
      completed_resume_cannot_be_reextracted:
        "这份简历已启用，不能被后台 AI 任务覆盖。",
      resume_must_be_active_and_ready_for_source_reparse:
        "当前版本尚未准备完成，暂时不能创建新的解析版本。",
      source_resume_ai_extraction_already_running:
        "当前版本仍在 AI 提取中，请完成后再创建新的解析版本。",
      source_resume_reparse_already_running:
        "这份简历已经在创建新的解析版本，请稍后刷新。",
      resume_original_hash_mismatch:
        "原始文件校验未通过，暂时不能重新解析。请重新上传原件。",
      resume_original_file_not_found:
        "找不到这份简历的原始文件。请重新上传该文件。",
      content_type_not_supported: "仅支持 PDF、Word、图片、Excel 和 HTML 简历文件。",
      unsupported_document_type: "仅支持 PDF、Word、图片、Excel 和 HTML 简历文件。",
      file_too_large: "简历文件过大，请压缩后再上传。",
      empty_upload: "这份简历是空文件。请重新选择原始文件后上传。",
      not_a_pdf: "文件内容不是有效的 PDF。请重新导出后上传。",
      database_conflict: "该简历与正在处理的请求冲突。请稍后重试。",
      invalid_idempotency_key: "上传请求标识无效。请重新选择该简历后重试。",
      idempotency_key_reused_with_different_pdf:
        "该简历的重试标识已被其他文件使用。请重新选择文件后上传。",
      resume_not_found: "这份简历已不存在或无法访问。",
      mailbox_not_configured: "请先保存邮箱配置。",
      mailbox_config_not_found: "这个收件通道已不存在或无法访问。",
      mailbox_display_name_required: "请为这个收件通道填写名称。",
      mailbox_duplicate_display_name: "该收件通道名称已被使用，请换一个名称。",
      mailbox_source_identity_locked:
        "该通道已有附件记录，不能改为其他邮箱。请新建一个收件通道。",
      mailbox_legacy_endpoint_ambiguous: "当前工作区已有多个收件通道，请刷新页面后重试。",
      mailbox_sync_in_progress: "这个收件通道正在同步，请稍后刷新查看结果。",
      mailbox_sync_claim_failed: "这个收件通道暂时无法开始同步，请稍后重试。",
      mailbox_config_archived: "这个收件通道已归档，不能继续同步。",
      mailbox_source_epoch_changed:
        "邮箱来源标识已变化，系统已暂停该通道。请归档后新建收件通道。",
      mailbox_password_required: "首次配置需要填写邮箱授权码。",
      mailbox_credentials_unavailable: "邮箱授权码无法读取，请重新保存后再同步。",
      mailbox_connection_failed: "无法连接邮箱，请检查 IMAP 地址、端口和授权码。",
      mailbox_select_failed: "无法打开指定的邮箱文件夹。",
      mailbox_status_failed: "无法读取邮箱当前位置，请检查文件夹设置后重试。",
      mailbox_search_failed: "无法检索邮箱中的附件。",
      mailbox_sync_failed: "邮箱入库暂时异常，请稍后重试。",
      mailbox_retention_policy_invalid: "内容保留策略无效，请重新选择后保存。",
      mailbox_retention_run_not_found: "这条清理记录已不存在或无法访问。",
      organization_admin_required: "仅工作区管理员可以修改保留策略或执行清理。",
      candidate_data_file_access_purpose_invalid: "原件访问方式无效，请重新发起查看或下载。",
      candidate_data_file_access_not_found: "这次原件访问已失效，请重新发起查看或下载。",
      candidate_data_session_nonce_missing: "当前登录会话已更新，请刷新页面后重新操作。",
      candidate_data_deletion_batch_not_found: "这条删除记录已不存在或无法访问。",
      candidate_data_deletion_batch_not_restorable: "这条删除记录当前不能恢复。",
      candidate_data_recovery_window_closed: "恢复期限已结束，原始数据已进入清理流程。",
      candidate_data_retention_policy_invalid: "保留策略参数无效，请检查后重试。",
      candidate_data_retention_preview_stale: "预览结果已过期，请重新预览后再保存策略。",
      candidate_data_export_not_found: "这项导出任务已不存在或无法访问。",
      candidate_data_export_not_cancellable: "这项导出任务当前不能取消。",
      candidate_data_export_download_not_found: "导出文件不可用或已过期，请重新创建导出。",
      candidate_data_export_candidate_selection_invalid: "请选择一位或多位可访问的候选人后再导出。",
      candidate_data_export_snapshot_unavailable: "导出所需的候选人快照已不可用，请重新创建导出。",
      candidate_data_export_original_unavailable: "部分原始文件不可用，无法创建包含原件的导出。",
      candidate_data_export_original_bytes_exceeded: "原始文件总量超过本次导出上限，请改为不含原件导出。",
      ...mailboxImportErrorMessages,
      score_template_not_found: "评分模板不存在，请重新选择。",
      resume_score_batch_not_found: "评分任务不存在或已不可访问。",
      job_version_not_found: "岗位版本不存在，请重新创建。",
      jd_generation_response_truncated:
        "岗位需求较长，AI 未能完整生成 JD。请精简后重试。",
      jd_generation_provider_failed:
        "AI 生成 JD 暂时不可用，请稍后重试。",
      jd_generation_service_unavailable:
        "AI 生成 JD 服务暂时不可用，请稍后重试。",
      jd_requirements_response_truncated:
        "JD 较长，AI 未能完整整理匹配条件。请稍后重试。",
      jd_requirements_provider_failed:
        "AI 整理 JD 条件暂时不可用，请稍后重试。",
    };
    const message = messages[error.message];
    if (message) return message;
    if (error.status >= 500) return "服务暂时不可用，请稍后重试。";
    return `操作没有完成：${error.message}`;
  }
  return "操作没有完成。请检查网络后重试。";
}

function humanizeAgentError(error: unknown): string {
  if (isApiError(error)) {
    const messages: Record<string, string> = {
      agent_model_not_configured: "招聘助手尚未配置 AI 服务。",
      agent_model_timeout: "招聘助手响应超时，请稍后重试。",
      agent_model_network_error: "招聘助手暂时无法连接 AI 服务，请稍后重试。",
      agent_service_unavailable: "招聘助手暂时不可用，请稍后重试。",
      agent_model_invalid_response: "招聘助手暂时没有返回有效结果，请重新发送。",
      agent_model_empty_response: "招聘助手暂时没有返回有效结果，请重新发送。",
      agent_model_missing_final_answer: "招聘助手暂时没有完成回答，请重新发送。",
      agent_model_invalid_tool_calls: "招聘助手的工具调用异常，请重新发送。",
      agent_model_tool_loop_limit: "招聘助手本次处理步骤过多，请换一种说法后重试。",
    };
    if (messages[error.message]) return messages[error.message];
    if (error.message.startsWith("agent_model_http_")) {
      return error.message === "agent_model_http_429"
        ? "招聘助手请求过于频繁，请稍后重试。"
        : "招聘助手暂时不可用，请稍后重试。";
    }
  }
  return humanizeError(error);
}

function isRetryableAgentError(error: unknown): boolean {
  if (!isApiError(error)) return true;
  return error.status === 408 || error.status === 429 || error.status >= 500;
}

function fileFingerprint(file: File): string {
  return `${file.name.toLocaleLowerCase()}-${file.size}-${file.lastModified}`;
}

function createUploadIdempotencyKey(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return `upload-${Date.now()}-${Math.random().toString(36).slice(2, 14)}`;
}

function isRetryableUploadError(error: unknown): boolean {
  if (!isApiError(error)) return true;
  return error.status === 408 || error.status === 429 || error.status >= 500;
}

function draftToSearchRequest(
  draft: FilterDraft,
  cursor: string | null = null,
  scoreTemplateId: string | null = null,
): CandidateSearchRequest {
  const request: CandidateSearchRequest = {
    schema_version: "candidate_filter.v2",
    limit: 50,
    cursor,
  };

  if (draft.minEmploymentMonths > 0) {
    request.min_employment_months = draft.minEmploymentMonths;
  }
  if (draft.minEmploymentOrInternshipMonths > 0) {
    request.min_employment_or_internship_months =
      draft.minEmploymentOrInternshipMonths;
  }
  if (draft.degrees.length) request.highest_degree_in = draft.degrees;
  if (draft.graduationStatus !== "any") {
    request.graduation_status = draft.graduationStatus;
    request.fresh_graduate_start_month =
      draft.freshGraduateStartMonth || defaultFilterDraft.freshGraduateStartMonth;
    request.fresh_graduate_end_month =
      draft.freshGraduateEndMonth || defaultFilterDraft.freshGraduateEndMonth;
  }
  if (
    draft.institutionClassifications.length ||
    draft.schoolName.trim() ||
    draft.major.trim() ||
    draft.minAverageScore ||
    draft.minGpaPercent ||
    draft.maxRankPosition ||
    draft.maxRankPercent
  ) {
    request.education_any_of = [
      {
        school_name_contains: draft.schoolName.trim()
          ? [draft.schoolName.trim()]
          : [],
        major_contains: draft.major.trim() ? [draft.major.trim()] : [],
        institution_classifications_any_of: draft.institutionClassifications,
        min_average_score: draft.minAverageScore
          ? Number(draft.minAverageScore)
          : null,
        min_gpa_percent: draft.minGpaPercent
          ? Number(draft.minGpaPercent)
          : null,
        max_rank_position: draft.maxRankPosition
          ? Number(draft.maxRankPosition)
          : null,
        max_rank_percent: draft.maxRankPercent
          ? Number(draft.maxRankPercent)
          : null,
      },
    ];
  }
  if (
    draft.experienceTypes.length ||
    draft.experienceName.trim() ||
    draft.company.trim() ||
    draft.title.trim() ||
    draft.experienceAwardLevels.length ||
    draft.experienceAwardResult.trim()
  ) {
    request.experience_any_of = [
      {
        experience_types: draft.experienceTypes.length
          ? draft.experienceTypes
          : experienceTypeOptions.map((option) => option.value),
        experience_name_contains: draft.experienceName.trim()
          ? [draft.experienceName.trim()]
          : [],
        organization_name_contains: draft.company.trim()
          ? [draft.company.trim()]
          : [],
        title_contains: draft.title.trim() ? [draft.title.trim()] : [],
        award_levels_any_of: draft.experienceAwardLevels,
        award_result_contains: draft.experienceAwardResult.trim()
          ? [draft.experienceAwardResult.trim()]
          : [],
      },
    ];
  }
  if (draft.skillCategories.length) {
    request.skill_categories_any_of = draft.skillCategories;
  }
  if (draft.skills.length) {
    if (draft.skillsMode === "all") request.skills_all_of = draft.skills;
    else request.skills_any_of = draft.skills;
  }
  const validLanguageCredentials = draft.languageCredentials.filter(
    (code) => code !== "custom" || Boolean(draft.customLanguageName.trim()),
  );
  if (validLanguageCredentials.length) {
    request.language_credentials_any_of = validLanguageCredentials.map(
      (credential_code) => ({
        credential_code,
        custom_name_contains:
          credential_code === "custom"
            ? draft.customLanguageName.trim()
            : null,
        min_score: draft.languageScores[credential_code]
          ? Number(draft.languageScores[credential_code])
          : null,
      }),
    );
  }
  if (draft.scholarshipStatus !== "any" || draft.scholarshipName.trim()) {
    request.scholarship_status = draft.scholarshipStatus;
    request.scholarship_name_contains =
      draft.scholarshipStatus === "present" && draft.scholarshipName.trim()
      ? [draft.scholarshipName.trim()]
      : [];
    request.scholarship_levels_any_of =
      draft.scholarshipStatus === "present" ? draft.scholarshipLevels : [];
  }
  if (draft.competitionStatus !== "any") {
    request.competition_status = draft.competitionStatus;
  }
  if (draft.competitionAwardStatus !== "any") {
    request.competition_award_status = draft.competitionAwardStatus;
  }
  if (draft.leadershipContexts.length || draft.leadershipRoles.length) {
    request.leadership_any_of = [
      {
        contexts_any_of: draft.leadershipContexts,
        roles_any_of: draft.leadershipRoles,
      },
    ];
  }
  if (draft.keywords.length) {
    request.keywords = draft.keywords;
    request.keyword_match_mode = draft.keywordsMode;
  }
  if (scoreTemplateId) request.score_template_id = scoreTemplateId;
  return request;
}

type SavedFilterDraftResult =
  | { draft: FilterDraft; error: null }
  | { draft: null; error: string };

function savedInstitutionClassifications(
  request: CandidateSearchRequest,
): { classifications: InstitutionClassification[]; error: string | null } {
  const education = request.education_any_of?.[0];
  const currentClassifications =
    education?.institution_classifications_any_of ?? [];
  const legacyTiers = education?.institution_tiers_any_of ?? [];

  if (request.is_985_211 === false) {
    return {
      classifications: [],
      error: "该历史筛选含有已下线的“非 985/211”条件，无法无损迁移。请重新设置院校类型后保存。",
    };
  }

  const unsupportedTiers = legacyTiers.filter(
    (tier) => !legacyTierClassificationMap[tier],
  );
  if (unsupportedTiers.length) {
    return {
      classifications: [],
      error: `该历史筛选包含已下线的院校层级（${unsupportedTiers
        .map((tier) => legacyInstitutionTierLabels[tier])
        .join("、")}），无法无损迁移。请重新设置院校类型后保存。`,
    };
  }

  if (currentClassifications.length) {
    if (legacyTiers.length) {
      return {
        classifications: [],
        error: "该历史筛选同时包含新旧院校条件，无法无损迁移。请重新设置院校类型后保存。",
      };
    }
    if (
      request.is_985_211 === true &&
      currentClassifications.some(
        (classification) => classification !== "985" && classification !== "211",
      )
    ) {
      return {
        classifications: [],
        error: "该历史筛选同时包含旧版 985/211 与其他院校条件，无法无损迁移。请重新设置院校类型后保存。",
      };
    }
    return {
      classifications: sortInstitutionClassifications(currentClassifications),
      error: null,
    };
  }

  if (request.is_985_211 === true && legacyTiers.some(
    (tier) => tier !== "985" && tier !== "211",
  )) {
    return {
      classifications: [],
      error: "该历史筛选同时包含旧版 985/211 与其他院校条件，无法无损迁移。请重新设置院校类型后保存。",
    };
  }

  // A saved tier and the old top-level flag were combined with AND. When a
  // tier is present it is therefore more specific than the old aggregate flag.
  const classifications = legacyTiers.length
    ? legacyTiers.flatMap((tier) => legacyTierClassificationMap[tier] ?? [])
    : request.is_985_211 === true
      ? (["985", "211"] as InstitutionClassification[])
      : [];
  return {
    classifications: sortInstitutionClassifications(classifications),
    error: null,
  };
}

function searchRequestToDraft(
  request: CandidateSearchRequest,
): SavedFilterDraftResult {
  const education = request.education_any_of?.[0];
  const experience = request.experience_any_of?.[0];
  const savedDegrees = request.highest_degree_in ?? education?.degree_in ?? [];
  const institutionMigration = savedInstitutionClassifications(request);
  if (institutionMigration.error) {
    return { draft: null, error: institutionMigration.error };
  }
  return {
    draft: {
      minEmploymentMonths: request.min_employment_months ?? 0,
      minEmploymentOrInternshipMonths:
        request.min_employment_or_internship_months ?? 0,
      degrees: savedDegrees.filter((degree) => degree !== "unknown"),
      institutionClassifications: institutionMigration.classifications,
      graduationStatus: request.graduation_status ?? "any",
      freshGraduateStartMonth:
        request.fresh_graduate_start_month ?? defaultFilterDraft.freshGraduateStartMonth,
      freshGraduateEndMonth:
        request.fresh_graduate_end_month ?? defaultFilterDraft.freshGraduateEndMonth,
      schoolName: education?.school_name_contains?.[0] ?? "",
      major: education?.major_contains?.[0] ?? "",
      minAverageScore: education?.min_average_score?.toString() ?? "",
      minGpaPercent: education?.min_gpa_percent?.toString() ?? "",
      maxRankPosition: education?.max_rank_position?.toString() ?? "",
      maxRankPercent: education?.max_rank_percent?.toString() ?? "",
      experienceTypes: experience?.experience_types ?? [],
      experienceName: experience?.experience_name_contains?.[0] ?? "",
      company: experience?.organization_name_contains?.[0] ?? "",
      title: experience?.title_contains?.[0] ?? "",
      experienceAwardLevels: experience?.award_levels_any_of ?? [],
      experienceAwardResult: experience?.award_result_contains?.[0] ?? "",
      skills: request.skills_all_of ?? request.skills_any_of ?? [],
      skillCategories: request.skill_categories_any_of ?? [],
      skillsMode: request.skills_any_of?.length ? "any" : "all",
      languageCredentials:
        request.language_credentials_any_of?.map((item) => item.credential_code) ?? [],
      languageScores: Object.fromEntries(
        (request.language_credentials_any_of ?? [])
          .filter((item) => item.min_score != null)
          .map((item) => [item.credential_code, String(item.min_score)]),
      ),
      customLanguageName:
        request.language_credentials_any_of?.find(
          (item) => item.credential_code === "custom",
        )?.custom_name_contains ?? "",
      scholarshipStatus: request.scholarship_status ?? "any",
      scholarshipName: request.scholarship_name_contains?.[0] ?? "",
      scholarshipLevels: request.scholarship_levels_any_of ?? [],
      competitionStatus: request.competition_status ?? "any",
      competitionAwardStatus: request.competition_award_status ?? "any",
      leadershipContexts: request.leadership_any_of?.[0]?.contexts_any_of ?? [],
      leadershipRoles: request.leadership_any_of?.[0]?.roles_any_of ?? [],
      keywords: request.keywords ?? request.keywords_all_of ?? request.keywords_any_of ?? [],
      keywordsMode:
        request.keyword_match_mode ??
        (request.keywords_all_of?.length ? "precise" : "broad"),
    },
    error: null,
  };
}

function isLocalDevelopmentHost(hostname: string) {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

function isRootMarketingHost(hostname: string) {
  return hostname === "greatsellai.net";
}

const HR_WORKSPACE_BASE_PATH = "/workspace";

function workspaceHref(path = "") {
  const normalizedPath = path && !path.startsWith("/") ? `/${path}` : path;
  const { hostname, pathname } = window.location;
  const isCompatibilityWorkspace =
    pathname === ROOT_WORKSPACE_BASE_PATH ||
    pathname.startsWith(`${ROOT_WORKSPACE_BASE_PATH}/`);

  if (isCompatibilityWorkspace) {
    return `${ROOT_WORKSPACE_BASE_PATH}${normalizedPath}` || ROOT_WORKSPACE_BASE_PATH;
  }

  // The public root site is intentionally a separate marketing surface. Its
  // calls to action always cross to the dedicated HR application origin, so
  // the root domain never needs to expose the authenticated HR API.
  if (window.location.hostname === "hr.greatsellai.net") {
    if (["/login", "/register", "/forgot-password", "/reset-password"].includes(normalizedPath)) {
      return normalizedPath;
    }
    return `${HR_WORKSPACE_BASE_PATH}${normalizedPath}` || HR_WORKSPACE_BASE_PATH;
  }

  if (isRootMarketingHost(hostname)) {
    return `https://hr.greatsellai.net${normalizedPath || "/"}`;
  }

  return normalizedPath || "/";
}

function platformHref() {
  const { pathname } = window.location;
  return pathname === ROOT_WORKSPACE_BASE_PATH ||
    pathname.startsWith(`${ROOT_WORKSPACE_BASE_PATH}/`)
    ? `${ROOT_WORKSPACE_BASE_PATH}/platform`
    : "/platform";
}

function authRouteFromPath(pathname: string): AuthRoute | null {
  const normalized = pathname.replace(/\/+$/, "") || "/";
  if (normalized === "/login") return "login";
  if (normalized === "/register") return "register";
  if (normalized === "/forgot-password") return "forgot-password";
  if (normalized === "/reset-password") return "reset-password";
  if (normalized === "/verify-email") return "verify-email";
  return null;
}

function resolveAppSurface(): AppSurface {
  const { hostname, pathname } = window.location;
  const compatibilityPlatformPath = `${ROOT_WORKSPACE_BASE_PATH}/platform`;
  const isPrimaryPlatformPath =
    pathname === "/platform" || pathname.startsWith("/platform/");
  const isCompatibilityPlatformPath =
    pathname === compatibilityPlatformPath ||
    pathname.startsWith(`${compatibilityPlatformPath}/`);
  if (
    isCompatibilityPlatformPath ||
    (
      isPrimaryPlatformPath &&
      (hostname === "hr.greatsellai.net" || isLocalDevelopmentHost(hostname))
    )
  ) {
    return { kind: "platform" };
  }
  const isWorkspacePath =
    pathname === ROOT_WORKSPACE_BASE_PATH ||
    pathname.startsWith(`${ROOT_WORKSPACE_BASE_PATH}/`);

  if (isWorkspacePath) {
    const nestedPath = pathname.slice(ROOT_WORKSPACE_BASE_PATH.length).replace(/\/+$/, "") || "/";
    return { kind: "workspace", authRoute: authRouteFromPath(nestedPath) };
  }

  if (hostname === "hr.greatsellai.net") {
    if (pathname === "/" || pathname === "") return { kind: "landing" };
    const nestedPath = pathname.startsWith(HR_WORKSPACE_BASE_PATH)
      ? pathname.slice(HR_WORKSPACE_BASE_PATH.length)
      : pathname;
    return { kind: "workspace", authRoute: authRouteFromPath(nestedPath) };
  }

  if (isLocalDevelopmentHost(hostname)) {
    return { kind: "workspace", authRoute: authRouteFromPath(pathname) };
  }

  return { kind: "landing" };
}

function ExternalRedirect({ href }: { href: string }) {
  useEffect(() => {
    window.location.replace(href);
  }, [href]);

  return (
    <main className="login-page" aria-live="polite">
      <div className="login-panel login-redirect-panel">
        <i className="spinner" /> 正在前往登录系统…
      </div>
    </main>
  );
}

function App() {
  const [surface, setSurface] = useState<AppSurface>(resolveAppSurface);

  useEffect(() => {
    const syncSurface = () => setSurface(resolveAppSurface());
    window.addEventListener("popstate", syncSurface);
    return () => window.removeEventListener("popstate", syncSurface);
  }, []);

  if (surface.kind === "landing") {
    return (
      <LandingPage
        loginHref={workspaceHref("/login")}
        registerHref={workspaceHref("/register")}
      />
    );
  }

  if (surface.kind === "platform") {
    return (
      <Suspense
        fallback={(
          <main className="login-page" aria-live="polite">
            <div className="login-panel login-redirect-panel">
              <i className="spinner" /> 正在打开平台管理…
            </div>
          </main>
        )}
      >
        <AdminApp />
      </Suspense>
    );
  }

  return (
    <Suspense
      fallback={(
        <main className="login-page" aria-live="polite">
          <div className="login-panel login-redirect-panel">
            <i className="spinner" /> 正在打开招聘工作台…
          </div>
        </main>
      )}
    >
      <BackofficeUiProvider>
        <WorkspaceApp authRoute={surface.authRoute} />
      </BackofficeUiProvider>
    </Suspense>
  );
}

function WorkspaceApp({ authRoute }: { authRoute: AuthRoute | null }) {
  const [view, setView] = useState<View>(() =>
    settingsSectionFromHash(window.location.hash) ? "settings" : "library",
  );
  const [settingsSection, setSettingsSection] = useState<SettingsSection>(
    () => settingsSectionFromHash(window.location.hash) ?? "mailbox",
  );
  const [filterDraft, setFilterDraft] =
    useState<FilterDraft>(freshDefaultFilter);
  const [appliedFilter, setAppliedFilter] =
    useState<FilterDraft>(freshDefaultFilter);
  const [filterOptions, setFilterOptions] = useState<FilterOptions>(
    fallbackFilterOptions,
  );
  const [scoreTemplates, setScoreTemplates] = useState<ScoreTemplate[]>([]);
  const [scoreTemplateId, setScoreTemplateId] = useState<string | null>(null);
  const [search, setSearch] = useState<CandidateSearchResponse>(emptySearch);
  const [searching, setSearching] = useState(false);
  const [savedFilters, setSavedFilters] = useState<SavedFilter[]>([]);
  const [selectedResume, setSelectedResume] = useState<SelectedResume | null>(
    null,
  );
  const [review, setReview] = useState<ResumeReviewDetail | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [agentOpen, setAgentOpen] = useState(false);
  const [drawerTab, setDrawerTab] = useState<DrawerTab>("original");
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [pdfDownloadLoading, setPdfDownloadLoading] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [summaries, setSummaries] = useState<ResumeSummary[]>([]);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [drawerScores, setDrawerScores] = useState<ResumeScore[]>([]);
  const [drawerScoreLoading, setDrawerScoreLoading] = useState(false);
  const [drawerScoreError, setDrawerScoreError] = useState<string | null>(null);
  const [reparsingSource, setReparsingSource] = useState(false);
  const [enrichingFacts, setEnrichingFacts] = useState(false);
  const [libraryRefreshToken, setLibraryRefreshToken] = useState(0);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [globalQuery, setGlobalQuery] = useState("");
  const [authState, setAuthState] = useState<
    "checking" | "authenticated" | "unauthenticated"
  >("checking");
  const [authSession, setAuthSession] = useState<AuthSession | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authLoading, setAuthLoading] = useState(false);
  const filterDraftRef = useRef(filterDraft);
  const appliedFilterRef = useRef(appliedFilter);
  const scoreTemplateIdRef = useRef<string | null>(null);
  const searchRequestRef = useRef(0);
  const scheduledFilterSearchRef = useRef<number | null>(null);
  const reviewRequestRef = useRef(0);
  const summaryRequestRef = useRef(0);
  const drawerScoreRequestRef = useRef(0);
  const originalFileRequestRef = useRef(0);
  const originalFileRevokeRef = useRef<(() => void) | null>(null);
  const agentTriggerRef = useRef<HTMLButtonElement | null>(null);

  const canManageMailbox =
    authSession?.role === "admin" &&
    authSession.plan?.feature_flags.mailbox_import === true;
  const canManageCandidateData = authSession?.role === "admin";
  const canManageSettings = canManageMailbox || canManageCandidateData;
  const canGenerateAiJd =
    authSession?.role === "admin" &&
    authSession.plan?.feature_flags.ai_jd_generation === true;

  const updateSettingsHash = useCallback(
    (section: SettingsSection | null, replace = false) => {
      const nextHash = section ? settingsHash(section) : "";
      if (window.location.hash === nextHash) return;
      const nextLocation = `${window.location.pathname}${window.location.search}${nextHash}`;
      if (replace) {
        window.history.replaceState(window.history.state, "", nextLocation);
      } else {
        window.history.pushState(window.history.state, "", nextLocation);
      }
    },
    [],
  );

  const navigateToView = useCallback(
    (nextView: MainWorkspaceView) => {
      setView(nextView);
      updateSettingsHash(null);
    },
    [updateSettingsHash],
  );

  const openSettings = useCallback(
    (section: SettingsSection) => {
      setSettingsSection(section);
      setView("settings");
      updateSettingsHash(section);
    },
    [updateSettingsHash],
  );

  const closeAgent = useCallback(() => {
    setAgentOpen(false);
    window.requestAnimationFrame(() => agentTriggerRef.current?.focus());
  }, []);

  const replaceFilterDraft = useCallback((next: FilterDraft) => {
    filterDraftRef.current = next;
    setFilterDraft(next);
  }, []);

  const cancelScheduledFilterSearch = useCallback(() => {
    if (scheduledFilterSearchRef.current === null) return;
    window.clearTimeout(scheduledFilterSearchRef.current);
    scheduledFilterSearchRef.current = null;
  }, []);

  const replaceAppliedFilter = useCallback((next: FilterDraft) => {
    const snapshot = snapshotFilterDraft(next);
    appliedFilterRef.current = snapshot;
    setAppliedFilter(snapshot);
  }, []);

  const replaceScoreTemplateId = useCallback((next: string | null) => {
    scoreTemplateIdRef.current = next;
    setScoreTemplateId(next);
  }, []);

  const selectedResumeId = selectedResume?.resumeId ?? null;

  const releaseOriginalFile = useCallback((clearError = true) => {
    originalFileRequestRef.current += 1;
    originalFileRevokeRef.current?.();
    originalFileRevokeRef.current = null;
    setPdfUrl(null);
    setPdfLoading(false);
    if (clearError) setPdfError(null);
  }, []);

  useEffect(() => {
    const titles: Record<AuthRoute, string> = {
      login: "登录｜GreatSell AI 招聘工具",
      register: "免费试用｜GreatSell AI 招聘工具",
      "forgot-password": "找回密码｜GreatSell AI 招聘工具",
      "reset-password": "设置新密码｜GreatSell AI 招聘工具",
      "verify-email": "验证邮箱｜GreatSell AI 招聘工具",
    };
    document.title = authRoute ? titles[authRoute] : "招聘工作台｜GreatSell AI";
  }, [authRoute]);

  const notify = useCallback((kind: ToastKind, message: string) => {
    const id = Date.now() + Math.round(Math.random() * 1000);
    setToasts((current) => [...current, { id, kind, message }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 5200);
  }, []);

  const refreshLibraryScores = useCallback(() => {
    setLibraryRefreshToken((current) => current + 1);
  }, []);

  const applyAuthSession = useCallback((session: AuthSession) => {
    setAuthSession(session);
    setAuthState(session.authenticated ? "authenticated" : "unauthenticated");
  }, []);

  // The verification email can be opened in another browser or device. The
  // registration tab keeps its own signed session, so polling the current
  // session is enough to learn that the user record was verified elsewhere.
  const refreshAuthSession = useCallback(async (): Promise<AuthSession | null> => {
    try {
      const session = await api.getAuthSession();
      applyAuthSession(session);
      return session;
    } catch {
      // A transient refresh failure must not log out a person who is simply
      // waiting for their verification email. The initial session bootstrap
      // below still handles a genuine unauthenticated start safely.
      return null;
    }
  }, [applyAuthSession]);

  const refreshSavedFilters = useCallback(async () => {
    try {
      setSavedFilters(await api.listSavedFilters());
    } catch (error) {
      notify("error", humanizeError(error));
    }
  }, [notify]);

  const runSearch = useCallback(
    async (
      draft: FilterDraft,
      append = false,
      cursor: string | null = null,
      selectedScoreTemplateId: string | null = scoreTemplateIdRef.current,
    ) => {
      const requestId = ++searchRequestRef.current;
      setSearching(true);
      try {
        const response = await api.searchCandidates(
          draftToSearchRequest(draft, cursor, selectedScoreTemplateId),
        );
        if (requestId !== searchRequestRef.current) return;
        setSearch((current) => ({
          ...response,
          items: append
            ? [...current.items, ...response.items]
            : response.items,
        }));
        if (!append) replaceAppliedFilter(draft);
      } catch (error) {
        if (requestId === searchRequestRef.current) {
          notify("error", humanizeError(error));
        }
      } finally {
        if (requestId === searchRequestRef.current) setSearching(false);
      }
    },
    [notify, replaceAppliedFilter],
  );

  const updateFilterDraft = useCallback(
    (next: FilterDraft, timing: "immediate" | "debounced" = "immediate") => {
      replaceFilterDraft(next);
      cancelScheduledFilterSearch();
      if (timing === "immediate") {
        void runSearch(next);
        return;
      }

      // Invalidate an in-flight result while the recruiter keeps typing, so
      // an older request cannot briefly present rows for stale conditions.
      searchRequestRef.current += 1;
      setSearching(true);
      scheduledFilterSearchRef.current = window.setTimeout(() => {
        scheduledFilterSearchRef.current = null;
        void runSearch(next);
      }, AUTO_FILTER_SEARCH_DELAY_MS);
    },
    [cancelScheduledFilterSearch, replaceFilterDraft, runSearch],
  );

  useEffect(
    () => () => cancelScheduledFilterSearch(),
    [cancelScheduledFilterSearch],
  );

  const registerScoreTemplate = useCallback(
    (template: ScoreTemplate) => {
      setScoreTemplates((current) => [
        template,
        ...current.filter((item) => item.template_id !== template.template_id),
      ]);
      replaceScoreTemplateId(template.template_id);
      void runSearch(
        appliedFilterRef.current,
        false,
        null,
        template.template_id,
      );
    },
    [replaceScoreTemplateId, runSearch],
  );

  const handleScoreCreated = useCallback(() => {
    refreshLibraryScores();
    void runSearch(appliedFilterRef.current);
  }, [refreshLibraryScores, runSearch]);

  const refreshReview = useCallback(
    async (resumeId: string) => {
      const requestId = ++reviewRequestRef.current;
      setReviewLoading(true);
      try {
        const detail = await api.getReview(resumeId);
        if (requestId === reviewRequestRef.current) {
          setReview(detail);
          setSelectedResume((current) => {
            if (!current || current.resumeId !== detail.resume_id)
              return current;
            return {
              ...current,
              candidateName:
                detail.candidate_display_name?.trim() || "未命名候选人",
            };
          });
        }
      } catch (error) {
        if (requestId === reviewRequestRef.current) {
          setReview(null);
          notify("error", humanizeError(error));
        }
      } finally {
        if (requestId === reviewRequestRef.current) setReviewLoading(false);
      }
    },
    [notify],
  );

  const loadSummaries = useCallback(
    async (resumeId: string) => {
      const requestId = ++summaryRequestRef.current;
      setSummaryLoading(true);
      try {
        const response = await api.listSummaries(resumeId);
        if (requestId === summaryRequestRef.current) setSummaries(response);
      } catch (error) {
        if (requestId === summaryRequestRef.current) {
          setSummaries([]);
          notify("error", humanizeError(error));
        }
      } finally {
        if (requestId === summaryRequestRef.current) setSummaryLoading(false);
      }
    },
    [notify],
  );

  const loadDrawerScores = useCallback(
    async (resumeId: string) => {
      const requestId = ++drawerScoreRequestRef.current;
      setDrawerScoreLoading(true);
      setDrawerScoreError(null);
      try {
        const response = await api.listScores(resumeId);
        if (requestId === drawerScoreRequestRef.current) {
          setDrawerScores(response);
        }
      } catch (error) {
        if (requestId === drawerScoreRequestRef.current) {
          setDrawerScores([]);
          setDrawerScoreError(humanizeError(error));
        }
      } finally {
        if (requestId === drawerScoreRequestRef.current) {
          setDrawerScoreLoading(false);
        }
      }
    },
    [],
  );

  useEffect(() => {
    void api
      .getAuthSession()
      .then((session) => {
        applyAuthSession(session);
      })
      .catch(() => {
        setAuthSession(null);
        setAuthState("unauthenticated");
      });
  }, [applyAuthSession]);

  // Large-model usage can change in a background worker, an Agent turn, or a
  // second browser tab. Refresh the small server-owned trial snapshot while
  // the workspace is open so the visible allowance does not drift for long.
  useEffect(() => {
    if (
      authState !== "authenticated" ||
      authRoute ||
      authSession?.email_verification_required ||
      authSession?.trial?.plan_status !== "trial"
    ) {
      return;
    }
    const refreshOnFocus = () => {
      if (document.visibilityState === "visible") void refreshAuthSession();
    };
    const intervalId = window.setInterval(refreshOnFocus, 60_000);
    window.addEventListener("focus", refreshOnFocus);
    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("focus", refreshOnFocus);
    };
  }, [
    authRoute,
    authSession?.email_verification_required,
    authSession?.trial?.plan_status,
    authState,
    refreshAuthSession,
  ]);

  useEffect(() => {
    if (
      authState !== "authenticated" ||
      authRoute ||
      authSession?.email_verification_required
    )
      return;
    void runSearch(defaultFilterDraft);
    void refreshSavedFilters();
    void api.getFilterOptions().then((options) => {
      setFilterOptions({
        ...fallbackFilterOptions,
        ...options,
        institution_classifications:
          options.institution_classifications?.length
            ? options.institution_classifications
            : fallbackFilterOptions.institution_classifications,
      });
    }).catch(() => {
      setFilterOptions(fallbackFilterOptions);
    });
    void api.listScoreTemplates().then((templates) => {
      setScoreTemplates(templates);
      const defaultTemplateId = templates[0]?.template_id ?? null;
      replaceScoreTemplateId(defaultTemplateId);
      if (defaultTemplateId) {
        void runSearch(
          appliedFilterRef.current,
          false,
          null,
          defaultTemplateId,
        );
      }
    }).catch(() => {
      setScoreTemplates([]);
      replaceScoreTemplateId(null);
    });
  }, [
    authRoute,
    authSession?.email_verification_required,
    authState,
    refreshSavedFilters,
    replaceScoreTemplateId,
    runSearch,
  ]);

  useEffect(() => {
    if (
      authState === "authenticated" &&
      authRoute &&
      authRoute !== "verify-email" &&
      !authSession?.email_verification_required
    ) {
      window.location.replace(workspaceHref());
    }
  }, [authRoute, authSession?.email_verification_required, authState]);

  useEffect(() => {
    if (
      !drawerOpen ||
      drawerTab !== "summary" ||
      !selectedResumeId ||
      !review ||
      review.resume_id !== selectedResumeId
    )
      return;
    if (hasSourceTextQualityIssue(review.quality_flags)) {
      setSummaries([]);
      return;
    }
    void loadSummaries(selectedResumeId);
  }, [drawerOpen, drawerTab, loadSummaries, review, selectedResumeId]);

  useEffect(() => {
    if (
      !drawerOpen ||
      drawerTab !== "score" ||
      !selectedResumeId ||
      !review ||
      review.resume_id !== selectedResumeId
    ) {
      return;
    }
    if (
      hasSourceTextQualityIssue(review.quality_flags) ||
      hasSupersededReparseVersion(review.quality_flags)
    ) {
      setDrawerScores([]);
      setDrawerScoreError(null);
      return;
    }
    void loadDrawerScores(selectedResumeId);
  }, [drawerOpen, drawerTab, loadDrawerScores, review, selectedResumeId]);

  useEffect(() => {
    drawerScoreRequestRef.current += 1;
    setSummaries([]);
    setDrawerScores([]);
    setDrawerScoreError(null);
    setDrawerScoreLoading(false);
  }, [selectedResumeId]);

  /**
   * Keep protected originals scoped to the active original-file tab. Opening
   * that tab creates a fresh, audited view grant; switching away, closing the
   * drawer, or selecting another resume invalidates the local object URL and
   * any in-flight request.
   */
  useEffect(() => {
    releaseOriginalFile();
  }, [drawerOpen, drawerTab, releaseOriginalFile, selectedResumeId]);

  useEffect(
    () => () => {
      originalFileRequestRef.current += 1;
      originalFileRevokeRef.current?.();
      originalFileRevokeRef.current = null;
    },
    [],
  );

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (agentOpen) {
        event.preventDefault();
        closeAgent();
        return;
      }
      setDrawerOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [agentOpen, closeAgent]);

  useEffect(() => {
    const syncSettingsFromHash = () => {
      const section = settingsSectionFromHash(window.location.hash);
      if (!section) {
        setView((current) => current === "settings" ? "library" : current);
        return;
      }
      setSettingsSection(section);
      setView("settings");
      updateSettingsHash(section, true);
    };

    syncSettingsFromHash();
    window.addEventListener("hashchange", syncSettingsFromHash);
    window.addEventListener("popstate", syncSettingsFromHash);
    return () => {
      window.removeEventListener("hashchange", syncSettingsFromHash);
      window.removeEventListener("popstate", syncSettingsFromHash);
    };
  }, [updateSettingsHash]);

  useEffect(() => {
    if (!authSession || view !== "settings") return;
    const sectionAllowed =
      (settingsSection === "mailbox" && canManageMailbox) ||
      (settingsSection === "data" && canManageCandidateData);
    if (sectionAllowed) return;

    const fallbackSection = canManageMailbox
      ? "mailbox"
      : canManageCandidateData
        ? "data"
        : null;
    if (!fallbackSection) {
      setView("library");
      updateSettingsHash(null, true);
      return;
    }
    setSettingsSection(fallbackSection);
    updateSettingsHash(fallbackSection, true);
  }, [
    authSession,
    canManageCandidateData,
    canManageMailbox,
    settingsSection,
    updateSettingsHash,
    view,
  ]);

  const openCandidate = useCallback(
    (item: CandidateSearchItem, tab: DrawerTab = "summary") => {
      summaryRequestRef.current += 1;
      setReview(null);
      setSummaries([]);
      setSelectedResume({
        resumeId: item.resume_id,
        candidateId: item.candidate_id,
        candidateName: item.display_name?.trim() || "未命名候选人",
      });
      setDrawerTab(tab);
      setDrawerOpen(true);
      void refreshReview(item.resume_id);
    },
    [refreshReview],
  );

  const openUploadedResume = useCallback(
    (resumeId: string, candidateId: string) => {
      summaryRequestRef.current += 1;
      setReview(null);
      setSummaries([]);
      setSelectedResume({
        resumeId,
        candidateId,
        candidateName: "未命名候选人",
      });
      setDrawerTab("summary");
      setDrawerOpen(true);
      navigateToView("library");
      setLibraryRefreshToken((current) => current + 1);
      void refreshReview(resumeId);
    },
    [navigateToView, refreshReview],
  );

  const openLibraryResume = useCallback(
    (item: ResumeLibraryItem) => {
      summaryRequestRef.current += 1;
      setReview(null);
      setSummaries([]);
      setSelectedResume({
        resumeId: item.resume_id,
        candidateId: item.candidate_id,
        candidateName: item.display_name?.trim() || "未命名候选人",
      });
      setDrawerTab("summary");
      setDrawerOpen(true);
      void refreshReview(item.resume_id);
    },
    [refreshReview],
  );

  const openMatchedResume = useCallback(
    (match: JobMatch) => {
      summaryRequestRef.current += 1;
      setReview(null);
      setSummaries([]);
      setSelectedResume({
        resumeId: match.resume_id,
        candidateId: match.candidate_id,
        candidateName: match.candidate_display_name?.trim() || "未命名候选人",
      });
      setDrawerTab("summary");
      setDrawerOpen(true);
      void refreshReview(match.resume_id);
    },
    [refreshReview],
  );

  const openAgentResume = useCallback(
    (item: RecruitingAgentCandidate) => {
      summaryRequestRef.current += 1;
      setReview(null);
      setSummaries([]);
      setSelectedResume({
        resumeId: item.resume_id,
        candidateId: item.candidate_id,
        candidateName: item.display_name?.trim() || "未命名候选人",
      });
      setAgentOpen(false);
      setDrawerTab("summary");
      setDrawerOpen(true);
      void refreshReview(item.resume_id);
    },
    [refreshReview],
  );

  const previewOriginalFile = useCallback(async () => {
    if (!selectedResumeId || pdfLoading) return;
    const requestId = ++originalFileRequestRef.current;
    originalFileRevokeRef.current?.();
    originalFileRevokeRef.current = null;
    setPdfUrl(null);
    setPdfError(null);
    setPdfLoading(true);
    try {
      const access = await api.requestResumeOriginalFileAccess(
        selectedResumeId,
        "view",
      );
      const resource = await api.getAuthorizedFileObjectUrl(access.access_url);
      if (requestId !== originalFileRequestRef.current) {
        resource.revoke();
        return;
      }
      originalFileRevokeRef.current = resource.revoke;
      setPdfUrl(resource.url);
    } catch (error) {
      if (requestId === originalFileRequestRef.current) {
        setPdfError(humanizeError(error));
      }
    } finally {
      if (requestId === originalFileRequestRef.current) setPdfLoading(false);
    }
  }, [pdfLoading, selectedResumeId]);

  useEffect(() => {
    if (
      !drawerOpen ||
      drawerTab !== "original" ||
      !selectedResumeId ||
      !review ||
      review.resume_id !== selectedResumeId ||
      !canPreviewInline(review.original_filename) ||
      pdfUrl ||
      pdfLoading ||
      pdfError
    ) {
      return;
    }
    // Opening the original-file tab is an intentional view action. Request a
    // short-lived, audited grant and render the protected object URL directly.
    void previewOriginalFile();
  }, [
    drawerOpen,
    drawerTab,
    pdfError,
    pdfLoading,
    pdfUrl,
    previewOriginalFile,
    review,
    selectedResumeId,
  ]);

  const downloadOriginalFile = useCallback(async () => {
    if (!selectedResumeId || pdfDownloadLoading) return;
    setPdfDownloadLoading(true);
    try {
      const access = await api.requestResumeOriginalFileAccess(
        selectedResumeId,
        "download",
      );
      const blob = await api.getAuthorizedFileBlob(access.access_url);
      const downloadUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = downloadUrl;
      link.download = review?.original_filename || "resume";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 0);
      notify("success", "已开始下载原始文件，系统已记录本次访问。");
    } catch (error) {
      notify("error", humanizeError(error));
    } finally {
      setPdfDownloadLoading(false);
    }
  }, [notify, pdfDownloadLoading, review?.original_filename, selectedResumeId]);

  const resetFilter = async () => {
    cancelScheduledFilterSearch();
    const clean = freshDefaultFilter();
    replaceFilterDraft(clean);
    await runSearch(clean);
  };

  const changeScoreTemplate = useCallback(
    (nextTemplateId: string | null) => {
      replaceScoreTemplateId(nextTemplateId);
      void runSearch(
        appliedFilterRef.current,
        false,
        null,
        nextTemplateId,
      );
    },
    [replaceScoreTemplateId, runSearch],
  );

  const saveCurrentFilter = async (name: string) => {
    const normalized = name.trim();
    if (!normalized) {
      notify("error", "请为这组筛选条件填写一个名称。");
      return;
    }
    try {
      await api.createSavedFilter({
        name: normalized,
        filters: draftToSearchRequest(filterDraftRef.current),
      });
      await refreshSavedFilters();
      notify("success", `已保存“${normalized}”。`);
    } catch (error) {
      notify("error", humanizeError(error));
    }
  };

  const applySavedFilter = (filter: SavedFilter): boolean => {
    const result = searchRequestToDraft(filter.filters);
    if (!result.draft) {
      notify("error", result.error);
      return false;
    }
    cancelScheduledFilterSearch();
    replaceFilterDraft(result.draft);
    void runSearch(result.draft);
    return true;
  };

  const deleteSavedFilter = async (filter: SavedFilter) => {
    try {
      await api.deleteSavedFilter(filter.saved_filter_id);
      await refreshSavedFilters();
      notify("success", `已删除“${filter.name}”。`);
    } catch (error) {
      notify("error", humanizeError(error));
    }
  };

  const generateSummary = async () => {
    if (!selectedResumeId) {
      notify("error", "请先从筛选结果中打开一份简历。");
      return;
    }
    setSummaryLoading(true);
    try {
      const summary = await api.generateSummary(selectedResumeId);
      setSummaries((current) => [
        summary,
        ...current
          .filter((item) => item.summary_id !== summary.summary_id)
          .map((item) => ({ ...item, is_current: false })),
      ]);
      setLibraryRefreshToken((current) => current + 1);
      notify("success", "AI 简历总结已生成。");
    } catch (error) {
      notify("error", humanizeError(error));
    } finally {
      setSummaryLoading(false);
    }
  };

  const createManualSummary = async (
    summaryId: string,
    content: Record<string, string>,
  ) => {
    try {
      const summary = await api.createManualSummaryVersion(summaryId, {
        content,
      });
      setSummaries((current) => [
        summary,
        ...current
          .filter((item) => item.summary_id !== summary.summary_id)
          .map((item) => ({ ...item, is_current: false })),
      ]);
      setLibraryRefreshToken((current) => current + 1);
      notify("success", "人工总结已保存为新的可追溯版本。");
    } catch (error) {
      notify("error", humanizeError(error));
      throw error;
    }
  };

  const reparseSelectedSource = useCallback(async () => {
    if (!selectedResumeId || reparsingSource) return;
    setReparsingSource(true);
    try {
      const parsed = await api.reparseSource(selectedResumeId);
      summaryRequestRef.current += 1;
      setReview(null);
      setSummaries([]);
      setSelectedResume((current) => ({
        resumeId: parsed.resume_id,
        candidateId: parsed.candidate_id,
        candidateName:
          parsed.candidate_display_name?.trim() ||
          current?.candidateName ||
          "未命名候选人",
      }));
      setDrawerTab("original");
      setLibraryRefreshToken((current) => current + 1);
      await refreshReview(parsed.resume_id);
      notify(
        "success",
        "已创建新的解析版本，正在基于原件重新提取。原版本会保留，不会被覆盖。",
      );
    } catch (error) {
      notify("error", humanizeError(error));
    } finally {
      setReparsingSource(false);
    }
  }, [notify, refreshReview, reparsingSource, selectedResumeId]);

  const enrichSelectedFacts = useCallback(async () => {
    if (!selectedResumeId || enrichingFacts) return;
    setEnrichingFacts(true);
    try {
      await api.enrichFilterFacts(selectedResumeId);
      await refreshReview(selectedResumeId);
      notify("success", "已提交高级筛选事实补充任务，旧事实会保留。完成后可刷新查看。");
    } catch (error) {
      notify("error", humanizeError(error));
    } finally {
      setEnrichingFacts(false);
    }
  }, [enrichingFacts, notify, refreshReview, selectedResumeId]);

  const deleteSelectedResumeData = useCallback(
    async (): Promise<void> => {
      if (!selectedResumeId) throw new Error("resume_not_found");
      try {
        const response = await api.deleteResumeCandidateData(selectedResumeId, {
          reason: "other",
          other_note: "simple_resume_delete",
        });
        releaseOriginalFile();
        summaryRequestRef.current += 1;
        setReview(null);
        setSummaries([]);
        setSelectedResume(null);
        setDrawerOpen(false);
        setLibraryRefreshToken((current) => current + 1);
        notify(
          "success",
          `当前简历版本已移出工作台，可在 ${formatLibraryDate(response.recovery_deadline_at)} 前恢复。`,
        );
      } catch (error) {
        notify("error", humanizeError(error));
        throw error;
      }
    },
    [notify, releaseOriginalFile, selectedResumeId],
  );

  const handleGlobalSearch = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter") return;
    const terms = globalQuery
      .split(/[、,，\s]+/)
      .map((term) => term.trim())
      .filter(Boolean);
    const next = { ...filterDraftRef.current, keywords: terms };
    cancelScheduledFilterSearch();
    replaceFilterDraft(next);
    navigateToView("filter");
    void runSearch(next);
  };

  const establishSession = (session: AuthSession) => {
    applyAuthSession(session);
    if (session.authenticated) {
      const nextPath = new URLSearchParams(window.location.search).get("next");
      if (
        nextPath &&
        (
          nextPath === "/platform" ||
          nextPath.startsWith("/platform/") ||
          nextPath === `${ROOT_WORKSPACE_BASE_PATH}/platform` ||
          nextPath.startsWith(`${ROOT_WORKSPACE_BASE_PATH}/platform/`)
        ) &&
        session.is_platform_admin
      ) {
        window.location.assign(nextPath);
        return session;
      }
      window.location.assign(
        workspaceHref(session.email_verification_required ? "/verify-email" : ""),
      );
    }
    return session;
  };

  const login = async (input: AuthLoginInput | string) => {
    setAuthError(null);
    setAuthLoading(true);
    try {
      return establishSession(await api.login(input));
    } catch (error) {
      setAuthError(humanizeError(error));
      return null;
    } finally {
      setAuthLoading(false);
    }
  };

  const register = async (input: AuthRegistrationInput) => {
    setAuthError(null);
    setAuthLoading(true);
    try {
      return establishSession(await api.register(input));
    } catch (error) {
      setAuthError(humanizeError(error));
      return null;
    } finally {
      setAuthLoading(false);
    }
  };

  const requestPasswordReset = async (email: string) => {
    setAuthError(null);
    setAuthLoading(true);
    try {
      return await api.requestPasswordReset(email);
    } catch (error) {
      setAuthError(humanizeError(error));
      return null;
    } finally {
      setAuthLoading(false);
    }
  };

  const completePasswordReset = async (token: string, password: string) => {
    setAuthError(null);
    setAuthLoading(true);
    try {
      await api.completePasswordReset({ token, password });
      return true;
    } catch (error) {
      setAuthError(humanizeError(error));
      return false;
    } finally {
      setAuthLoading(false);
    }
  };

  const completeEmailVerification = async (token: string) => {
    setAuthError(null);
    setAuthLoading(true);
    try {
      // Keep the verification-link tab on its explicit confirmation page.
      // The registration tab polls its own session and is the one that enters
      // the workspace after this server-side verification succeeds.
      const session = await api.completeEmailVerification(token);
      applyAuthSession(session);
      return session;
    } catch (error) {
      setAuthError(humanizeError(error));
      return null;
    } finally {
      setAuthLoading(false);
    }
  };

  const resendEmailVerification = async () => {
    setAuthError(null);
    setAuthLoading(true);
    try {
      return await api.resendEmailVerification();
    } catch (error) {
      setAuthError(humanizeError(error));
      return null;
    } finally {
      setAuthLoading(false);
    }
  };

  const logout = async () => {
    await api.logout();
    setSelectedResume(null);
    setDrawerOpen(false);
    setAuthSession(null);
    setAuthState("unauthenticated");
    window.location.assign(workspaceHref("/login"));
  };

  if (authState === "checking") {
    return (
      <main className="login-page" aria-live="polite">
        <div className="login-panel login-redirect-panel">
          <i className="spinner" /> 正在验证登录状态…
        </div>
      </main>
    );
  }

  if (authState !== "authenticated" && !authRoute) {
    return <ExternalRedirect href={workspaceHref("/login")} />;
  }

  // A recovery link may be opened in a browser that still has an unrelated
  // workspace session.  It must remain usable instead of silently dropping
  // the recipient into that workspace.
  if (authRoute === "reset-password") {
    return (
      <ResetPasswordPage
        error={authError}
        loading={authLoading}
        onComplete={completePasswordReset}
      />
    );
  }

  if (authRoute === "verify-email" || authSession?.email_verification_required) {
    return (
      <EmailVerificationPage
        error={authError}
        loading={authLoading}
        session={authSession}
        onComplete={completeEmailVerification}
        onRefreshSession={refreshAuthSession}
        onResend={resendEmailVerification}
      />
    );
  }

  if (authState !== "authenticated") {
    if (authRoute === "register") {
      return <RegistrationPage error={authError} loading={authLoading} onRegister={register} />;
    }
    if (authRoute === "forgot-password") {
      return <ForgotPasswordPage error={authError} loading={authLoading} onRequest={requestPasswordReset} />;
    }
    return (
      <LoginPage
        error={authError}
        loading={authLoading}
        onLogin={login}
      />
    );
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <SideRail
        activeView={view}
        canManageSettings={canManageSettings}
        inert={drawerOpen || agentOpen}
        onChangeView={navigateToView}
        onOpenSettings={() => openSettings(canManageMailbox ? "mailbox" : "data")}
      />
      <div className="app-area" inert={drawerOpen || agentOpen}>
      <Topbar
        globalQuery={globalQuery}
        onGlobalQueryChange={setGlobalQuery}
        onGlobalSearchKeyDown={handleGlobalSearch}
        onOpenAgent={() => {
            setDrawerOpen(false);
            setAgentOpen(true);
          }}
          agentTriggerRef={agentTriggerRef}
          canManageSettings={canManageSettings}
          onAccountMenuOpen={() => {
            void refreshAuthSession();
          }}
          onLogout={() => void logout()}
          onNewUpload={() => navigateToView("upload")}
          onOpenSettings={() => openSettings(canManageMailbox ? "mailbox" : "data")}
          organizationName={authSession?.organization?.name ?? null}
          platformAdmin={authSession?.is_platform_admin ?? false}
          planName={authSession?.plan?.name ?? null}
          role={authSession?.role ?? null}
          trial={authSession?.trial ?? null}
          userDisplayName={authSession?.user?.display_name ?? null}
          userEmail={authSession?.user?.email ?? null}
        />
        <TrialStatusBanner trial={authSession?.trial ?? null} />
        <main className="main-content" id="main-content">
          {view === "library" && (
            <ResumeLibraryPage
              formatError={humanizeError}
              refreshToken={libraryRefreshToken}
              selectedResumeId={selectedResumeId}
              onOpenResume={openLibraryResume}
              onUpload={() => navigateToView("upload")}
            />
          )}
          {view === "filter" && (
            <FilterWorkspace
              appliedDraft={appliedFilter}
              draft={filterDraft}
              filterOptions={filterOptions}
              onDraftChange={updateFilterDraft}
              savedFilters={savedFilters}
              search={search}
              searching={searching}
              selectedResumeId={selectedResumeId}
              onReset={resetFilter}
              onSave={saveCurrentFilter}
              onApplySaved={applySavedFilter}
              onDeleteSaved={deleteSavedFilter}
              onOpenCandidate={openCandidate}
              onScoreTemplateChange={changeScoreTemplate}
              onLoadMore={() =>
                void runSearch(appliedFilterRef.current, true, search.next_cursor)
              }
              onUpload={() => navigateToView("upload")}
              scoreTemplateId={scoreTemplateId}
              scoreTemplates={scoreTemplates}
            />
          )}
          <div hidden={view !== "upload"}>
            <UploadPage onComplete={openUploadedResume} notify={notify} />
          </div>
          {view === "score" && (
            <ScoreWorkspace
              formatError={humanizeError}
              notify={notify}
              onScoreCreated={handleScoreCreated}
              onTemplateCreated={registerScoreTemplate}
            />
          )}
          {view === "match" && (
            <MatchWorkspace
              canGenerateAiJd={canGenerateAiJd}
              formatError={humanizeError}
              notify={notify}
              onOpenMatchedResume={openMatchedResume}
            />
          )}
          {view === "settings" && canManageSettings && (
            <WorkspaceSettingsPage
              activeSection={settingsSection}
              canManageCandidateData={canManageCandidateData}
              canManageMailbox={canManageMailbox}
              notify={notify}
              onImported={() => setLibraryRefreshToken((current) => current + 1)}
              onOpenLibrary={() => navigateToView("library")}
              onSelectSection={openSettings}
              role={authSession?.role ?? null}
            />
          )}
        </main>
      </div>

      <div
        aria-hidden="true"
        className={`drawer-scrim${drawerOpen || agentOpen ? " is-open" : ""}`}
        onClick={() => {
          if (agentOpen) closeAgent();
          else setDrawerOpen(false);
        }}
      />
      <CandidateDrawer
        candidate={selectedResume}
        drawerTab={drawerTab}
        isOpen={drawerOpen}
        pdfError={pdfError}
        pdfDownloadLoading={pdfDownloadLoading}
        pdfLoading={pdfLoading}
        pdfUrl={pdfUrl}
        review={review}
        reviewLoading={reviewLoading}
        scoreError={drawerScoreError}
        scoreLoading={drawerScoreLoading}
        scores={drawerScores}
        languageCredentialOptions={filterOptions.language_credentials}
        summaries={summaries}
        summaryLoading={summaryLoading}
        onClose={() => setDrawerOpen(false)}
        onCreateManualSummary={createManualSummary}
        onDeleteResume={deleteSelectedResumeData}
        onDownloadOriginal={downloadOriginalFile}
        onGenerateSummary={() => void generateSummary()}
        onReparseSource={() => void reparseSelectedSource()}
        onEnrichFacts={() => void enrichSelectedFacts()}
        onPreviewOriginal={() => void previewOriginalFile()}
        onRefreshScores={() => {
          if (selectedResumeId) void loadDrawerScores(selectedResumeId);
        }}
        enrichingFacts={enrichingFacts}
        onTabChange={setDrawerTab}
        reparsingSource={reparsingSource}
        canManageCandidateData={canManageCandidateData}
      />
      <RecruitingAgentDrawer
        isOpen={agentOpen}
        onClose={closeAgent}
        onOpenMatchWorkspace={() => {
          setAgentOpen(false);
          navigateToView("match");
        }}
        onOpenScoreWorkspace={() => {
          setAgentOpen(false);
          navigateToView("score");
        }}
        onOpenMailboxSettings={() => {
          setAgentOpen(false);
          openSettings("mailbox");
        }}
        onOpenResume={openAgentResume}
      />

      <ToastRegion
        toasts={toasts}
        onDismiss={(id) =>
          setToasts((current) => current.filter((toast) => toast.id !== id))
        }
      />
    </div>
  );
}

function LoginPage({
  error,
  loading,
  onLogin,
}: {
  error: string | null;
  loading: boolean;
  onLogin: (input: AuthLoginInput | string) => Promise<AuthSession | null>;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [legacyMode, setLegacyMode] = useState(false);
  const canSubmit = legacyMode ? Boolean(password) : Boolean(email.trim() && password);
  return (
    <AuthPageLayout
      description="进入只属于你所在团队的招聘工作区。候选人、岗位、评分和原始文件按工作区分别管理。"
      eyebrow="GREATSELL AI · 招聘工具"
      title="登录招聘工作台"
    >
      <form
        className="auth-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (legacyMode && password) {
            void onLogin(password);
          } else if (email.trim() && password) {
            void onLogin({ email: email.trim(), password });
          }
        }}
      >
        {!legacyMode && (
          <div className="field-stack">
            <label className="field-label" htmlFor="login-email">
              工作邮箱
            </label>
            <input
              autoComplete="email"
              className="field"
              id="login-email"
              inputMode="email"
              onChange={(event) => setEmail(event.target.value)}
              placeholder="name@company.com"
              required
              type="email"
              value={email}
            />
          </div>
        )}
        <div className="field-stack">
          <div className="auth-field-heading">
            <label className="field-label" htmlFor={legacyMode ? "legacy-login-password" : "login-password"}>
              {legacyMode ? "旧管理口令" : "密码"}
            </label>
            {!legacyMode && <a className="auth-inline-link" href={workspaceHref("/forgot-password")}>忘记密码</a>}
          </div>
          <input
            autoComplete="current-password"
            className="field"
            id={legacyMode ? "legacy-login-password" : "login-password"}
            onChange={(event) => setPassword(event.target.value)}
            placeholder={legacyMode ? "输入旧管理口令" : "输入密码"}
            required
            type="password"
            value={password}
          />
        </div>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button
          className="button button-primary auth-submit"
          disabled={loading || !canSubmit}
          type="submit"
        >
          {loading ? <><i className="spinner" />正在登录</> : legacyMode ? "使用口令登录" : "登录工作台"}
        </button>
        <div className="auth-mode-row">
          <span>{legacyMode ? "正在使用旧版工作区兼容登录" : "旧版工作区管理员？"}</span>
          <button
            aria-pressed={legacyMode}
            className="auth-mode-switch"
            onClick={() => setLegacyMode((current) => !current)}
            type="button"
          >
            {legacyMode ? "改用邮箱登录" : "使用旧管理口令"}
          </button>
        </div>
        <p className="auth-footer-copy">
          还没有团队工作区？<a href={workspaceHref("/register")}>免费试用 30 天</a>
        </p>
        <p className="auth-legacy-note">
          旧管理口令仅用于迁移中的原工作区，本次提交后不会写入浏览器本地存储。
        </p>
      </form>
    </AuthPageLayout>
  );
}

function RegistrationPage({
  error,
  loading,
  onRegister,
}: {
  error: string | null;
  loading: boolean;
  onRegister: (input: AuthRegistrationInput) => Promise<AuthSession | null>;
}) {
  const [organizationName, setOrganizationName] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [registrationOffer, setRegistrationOffer] = useState<RegistrationOffer>(
    fallbackRegistrationOffer,
  );
  const [offerLoading, setOfferLoading] = useState(true);

  useEffect(() => {
    let active = true;
    void api
      .getRegistrationOffer()
      .then((offer) => {
        if (active) setRegistrationOffer(offer);
      })
      // Public offer details are helpful, never a reason to block signup.
      .catch(() => undefined)
      .finally(() => {
        if (active) setOfferLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const submit = async () => {
    setFormError(null);
    if (password !== confirmation) {
      setFormError("两次输入的密码不一致，请重新确认。");
      return;
    }
    const session = await onRegister({
      organization_name: organizationName.trim(),
      full_name: fullName.trim(),
      email: email.trim(),
      password,
    });
    if (session?.email_verification_required) setSubmitted(true);
  };

  return (
    <AuthPageLayout
      description="注册后即可使用大卖数智 AI 招聘工作台。上传简历，快速筛选、统一评分并查看 JD 匹配依据，把时间留给真正需要你判断的人。"
      eyebrow={offerLoading
        ? "30 天免费体验，含 1,000 次大模型调用"
        : `${registrationOffer.trial_days} 天${registrationOffer.plan_name}免费体验，含 ${formatWholeNumber(registrationOffer.llm_call_limit)} 次大模型调用`}
      title="让招聘判断，从第一份简历开始更快"
      variant="registration"
    >
      {submitted ? (
        <div aria-live="polite" className="auth-success-state">
          <span className="auth-success-icon"><Icon name="check" size={20} /></span>
          <h2>验证邮箱，马上进入工作台</h2>
          <p>验证邮件已发送到你填写的工作邮箱。点击邮件中的链接，即可开始上传第一份简历。</p>
          <a className="button button-primary auth-submit" href={workspaceHref("/verify-email")}>我已完成邮箱验证</a>
        </div>
      ) : (
        <div className="auth-registration">
          <div className="auth-registration-heading">
            <p>免费创建团队工作台</p>
            <h2>开始 {registrationOffer.trial_days} 天{registrationOffer.plan_name}体验</h2>
            <span>试用期内最多 {formatWholeNumber(registrationOffer.llm_call_limit)} 次大模型调用，简历提取、评分、JD 处理和招聘助手统一计入。</span>
          </div>
          <form
            className="auth-form auth-registration-form"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <div className="auth-form-grid">
              <div className="field-stack auth-form-span-2">
                <label className="field-label" htmlFor="register-organization">公司 / 团队名称</label>
                <input autoComplete="organization" className="field" id="register-organization" onChange={(event) => setOrganizationName(event.target.value)} placeholder="例如：大卖数智 AI 部" required value={organizationName} />
              </div>
              <div className="field-stack">
                <label className="field-label" htmlFor="register-name">姓名</label>
                <input autoComplete="name" className="field" id="register-name" onChange={(event) => setFullName(event.target.value)} placeholder="请输入你的姓名" required value={fullName} />
              </div>
              <div className="field-stack">
                <label className="field-label" htmlFor="register-email">工作邮箱</label>
                <input autoComplete="email" className="field" id="register-email" inputMode="email" onChange={(event) => setEmail(event.target.value)} placeholder="name@company.com" required type="email" value={email} />
              </div>
              <div className="field-stack">
                <label className="field-label" htmlFor="register-password">设置登录密码</label>
                <input autoComplete="new-password" className="field" id="register-password" minLength={8} onChange={(event) => setPassword(event.target.value)} placeholder="至少 8 个字符" required type="password" value={password} />
              </div>
              <div className="field-stack">
                <label className="field-label" htmlFor="register-password-confirmation">再次输入密码</label>
                <input aria-describedby={formError ? "register-password-error" : undefined} aria-invalid={Boolean(formError)} autoComplete="new-password" className="field" id="register-password-confirmation" minLength={8} onChange={(event) => setConfirmation(event.target.value)} placeholder="请再次输入" required type="password" value={confirmation} />
              </div>
            </div>
            {(formError || error) && <p className="auth-error" id="register-password-error" role="alert">{formError || error}</p>}
            <p className="auth-consent">提交后，我们会向你的工作邮箱发送验证邮件。完成验证即可进入工作台。</p>
            <button className="button button-primary auth-submit" disabled={loading || !organizationName.trim() || !fullName.trim() || !email.trim() || password.length < 8 || !confirmation} type="submit">
              {loading ? <><i className="spinner" />正在创建工作台</> : `免费开启 ${registrationOffer.trial_days} 天体验`}
            </button>
            <p className="auth-footer-copy">已有团队账号？<a href={workspaceHref("/login")}>立即登录</a></p>
          </form>
        </div>
      )}
    </AuthPageLayout>
  );
}

function EmailVerificationPage({
  error,
  loading,
  session,
  onComplete,
  onRefreshSession,
  onResend,
}: {
  error: string | null;
  loading: boolean;
  session: AuthSession | null;
  onComplete: (token: string) => Promise<AuthSession | null>;
  onRefreshSession: () => Promise<AuthSession | null>;
  onResend: () => Promise<{ accepted: boolean; delivery_available: boolean } | null>;
}) {
  const token = new URLSearchParams(window.location.search).get("token");
  const completionStarted = useRef(false);
  const [verificationState, setVerificationState] = useState<
    "waiting" | "verifying" | "verified" | "failed"
  >(token ? "verifying" : "waiting");
  const [resendState, setResendState] = useState<"idle" | "sent" | "unavailable">("idle");
  const email = session?.user?.email ?? null;
  const canResend = Boolean(session?.authenticated && session.email_verification_required);
  const isWaitingForVerification = Boolean(
    !token && session?.authenticated && session.email_verification_required,
  );
  const verificationSucceeded = Boolean(token && verificationState === "verified");
  const verificationInProgress = Boolean(token && verificationState === "verifying");

  useEffect(() => {
    if (!token || completionStarted.current) return;
    completionStarted.current = true;
    setVerificationState("verifying");
    void onComplete(token).then((result) => {
      setVerificationState(
        result?.authenticated && !result.email_verification_required
          ? "verified"
          : "failed",
      );
    });
  }, [onComplete, token]);

  useEffect(() => {
    if (!isWaitingForVerification) return;

    let active = true;
    let refreshing = false;
    const refresh = async () => {
      if (refreshing) return;
      refreshing = true;
      try {
        await onRefreshSession();
      } finally {
        refreshing = false;
      }
    };
    const refreshOnFocus = () => {
      if (active) void refresh();
    };

    void refresh();
    const intervalId = window.setInterval(refresh, 3_000);
    window.addEventListener("focus", refreshOnFocus);
    return () => {
      active = false;
      window.clearInterval(intervalId);
      window.removeEventListener("focus", refreshOnFocus);
    };
  }, [isWaitingForVerification, onRefreshSession]);

  useEffect(() => {
    if (!token && session?.authenticated && !session.email_verification_required) {
      // This is the original registration tab. It is the only page that
      // automatically enters the workspace after a successful email check.
      window.location.replace(workspaceHref());
    }
  }, [session?.authenticated, session?.email_verification_required, token]);

  const maskedEmail = email
    ? email.replace(/^(.{1,2}).*(@.*)$/, "$1•••$2")
    : null;

  return (
    <AuthPageLayout
      description="验证工作邮箱后即可进入你的独立招聘工作区。候选人、简历、岗位和 AI 结论始终按工作区隔离。"
      eyebrow="账户验证"
      title={
        verificationSucceeded
          ? "邮箱验证成功"
          : token
            ? verificationInProgress
              ? "正在验证邮箱"
              : "邮箱验证未完成"
            : "请验证工作邮箱"
      }
    >
      <div aria-live="polite" className="auth-success-state">
        <span className="auth-success-icon">
          <Icon name={verificationSucceeded ? "check" : "inbox"} size={20} />
        </span>
        <h2>
          {verificationSucceeded
            ? "邮箱已验证"
            : token
              ? verificationInProgress
                ? "正在确认你的邮箱"
                : "验证链接未完成验证"
              : "请查收验证邮件"}
        </h2>
        {verificationSucceeded ? (
          <p>验证已经完成。请返回发起注册的页面，系统会自动进入工作台；你可以直接关闭此页面。</p>
        ) : token ? (
          <p>
            {loading || verificationInProgress
              ? "请稍候，正在安全地验证这条链接。"
              : "验证链接无效或已失效时，你可以登录后重新发送邮件。"}
          </p>
        ) : (
          <p>
            {maskedEmail
              ? `请查看 ${maskedEmail} 的收件箱，并在 24 小时内打开验证链接。`
              : "请登录注册邮箱后打开验证链接，完成后即可进入工作台。"}
          </p>
        )}
        {isWaitingForVerification && (
          <p className="auth-footer-copy" role="status">
            验证完成后，本页面会自动进入工作台。
          </p>
        )}
        {error && <p className="auth-error" role="alert">{error}</p>}
        {canResend && !token && (
          <button
            className="button button-primary auth-submit"
            disabled={loading || resendState === "sent"}
            onClick={() => {
              void onResend().then((result) => {
                if (result?.accepted) {
                  setResendState(result.delivery_available ? "sent" : "unavailable");
                }
              });
            }}
            type="button"
          >
            {loading ? <><i className="spinner" />正在发送</> : resendState === "sent" ? "验证邮件已重新发送" : "重新发送验证邮件"}
          </button>
        )}
        {resendState === "unavailable" && (
          <p className="auth-error" role="status">暂时无法发送验证邮件，请稍后重试。</p>
        )}
        {!canResend && !token && (
          <a className="button button-primary auth-submit" href={workspaceHref("/login")}>返回登录</a>
        )}
        {token && !verificationSucceeded && !loading && (
          <a className="button button-primary auth-submit" href={workspaceHref("/login")}>返回登录</a>
        )}
        <p className="auth-footer-copy">
          验证前不会开放候选人或简历数据访问。
        </p>
      </div>
    </AuthPageLayout>
  );
}

function ForgotPasswordPage({
  error,
  loading,
  onRequest,
}: {
  error: string | null;
  loading: boolean;
  onRequest: (email: string) => Promise<{ accepted: boolean; delivery_available: boolean } | null>;
}) {
  const [email, setEmail] = useState("");
  const [result, setResult] = useState<{ deliveryAvailable: boolean } | null>(null);

  return (
    <AuthPageLayout
      description="我们不会在此页面显示邮箱是否已注册。重置链接仅发送给有效且可用的账号。"
      eyebrow="账户协助"
      title="找回登录密码"
    >
      {result ? (
        <div aria-live="polite" className="auth-success-state">
          <span className="auth-success-icon"><Icon name={result.deliveryAvailable ? "check" : "user"} size={20} /></span>
          <h2>{result.deliveryAvailable ? "请查看邮箱" : "请联系管理员"}</h2>
          <p>{result.deliveryAvailable ? "若该邮箱对应可用账号，我们已发送重置密码的后续指引。" : "当前团队暂未启用邮件重置，请联系管理员协助重置密码。"}</p>
          <a className="button button-primary auth-submit" href={workspaceHref("/login")}>返回登录</a>
        </div>
      ) : (
        <form
          className="auth-form"
          onSubmit={(event) => {
            event.preventDefault();
            void onRequest(email.trim()).then((response) => {
              if (response?.accepted) setResult({ deliveryAvailable: response.delivery_available });
            });
          }}
        >
          <div className="field-stack">
            <label className="field-label" htmlFor="reset-email">工作邮箱</label>
            <input autoComplete="email" className="field" id="reset-email" inputMode="email" onChange={(event) => setEmail(event.target.value)} placeholder="name@company.com" required type="email" value={email} />
            <p className="field-help">为保护账户安全，提交后的提示不会披露该邮箱是否已注册。</p>
          </div>
          {error && <p className="auth-error" role="alert">{error}</p>}
          <button className="button button-primary auth-submit" disabled={loading || !email.trim()} type="submit">
            {loading ? <><i className="spinner" />正在提交</> : "获取重置指引"}
          </button>
          <p className="auth-footer-copy"><a href={workspaceHref("/login")}>返回登录</a></p>
        </form>
      )}
    </AuthPageLayout>
  );
}

function ResetPasswordPage({
  error,
  loading,
  onComplete,
}: {
  error: string | null;
  loading: boolean;
  onComplete: (token: string, password: string) => Promise<boolean>;
}) {
  const token = new URLSearchParams(window.location.search).get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [completed, setCompleted] = useState(false);

  const submit = async () => {
    setFormError(null);
    if (!token) {
      setFormError("缺少重置链接。请重新申请一封重置邮件。");
      return;
    }
    if (password !== confirmation) {
      setFormError("两次输入的密码不一致，请重新确认。");
      return;
    }
    if (await onComplete(token, password)) {
      setCompleted(true);
    }
  };

  return (
    <AuthPageLayout
      description="设置新密码后，旧密码将立即失效。为安全起见，重置链接只能使用一次。"
      eyebrow="账户协助"
      title="设置新的登录密码"
    >
      {completed ? (
        <div aria-live="polite" className="auth-success-state">
          <span className="auth-success-icon"><Icon name="check" size={20} /></span>
          <h2>新密码已设置</h2>
          <p>请使用新密码登录你的招聘工作台。</p>
          <a className="button button-primary auth-submit" href={workspaceHref("/login")}>前往登录</a>
        </div>
      ) : (
        <form
          className="auth-form"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <div className="field-stack">
            <label className="field-label" htmlFor="reset-password">新密码</label>
            <input
              autoComplete="new-password"
              className="field"
              id="reset-password"
              minLength={8}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="至少 8 个字符"
              required
              type="password"
              value={password}
            />
          </div>
          <div className="field-stack">
            <label className="field-label" htmlFor="reset-password-confirmation">再次输入新密码</label>
            <input
              aria-describedby={formError || error ? "reset-password-error" : undefined}
              aria-invalid={Boolean(formError || error)}
              autoComplete="new-password"
              className="field"
              id="reset-password-confirmation"
              minLength={8}
              onChange={(event) => setConfirmation(event.target.value)}
              placeholder="请再次输入"
              required
              type="password"
              value={confirmation}
            />
          </div>
          {(formError || error) && <p className="auth-error" id="reset-password-error" role="alert">{formError || error}</p>}
          <button
            className="button button-primary auth-submit"
            disabled={loading || !token || password.length < 8 || !confirmation}
            type="submit"
          >
            {loading ? <><i className="spinner" />正在保存</> : "保存新密码"}
          </button>
          <p className="auth-footer-copy"><a href={workspaceHref("/forgot-password")}>重新申请重置链接</a></p>
        </form>
      )}
    </AuthPageLayout>
  );
}

function AuthPageLayout({
  children,
  description,
  eyebrow,
  title,
  variant = "default",
}: {
  children: ReactNode;
  description: string;
  eyebrow: string;
  title: string;
  variant?: "default" | "registration";
}) {
  const isRegistration = variant === "registration";
  return (
    <main className={`auth-page${isRegistration ? " auth-page-registration" : ""}`}>
      <div className="auth-shell">
        <section className="auth-introduction" aria-labelledby="auth-page-title">
          <a className="auth-brand" href={workspaceHref("/")} aria-label="大卖数智首页">
            <img alt="大卖数智 GreatSell AI" src="/brand/greatsell-logo-cn-white.png" />
          </a>
          <div aria-hidden="true" className="auth-mark" />
          <p className="auth-kicker">{eyebrow}</p>
          <h1 id="auth-page-title">{title}</h1>
          <p>{description}</p>
          <ul className="auth-assurance-list">
            {isRegistration ? (
              <>
                <li><Icon name="spark" size={17} /><span>免费体验进阶版已开放能力，先使用再决定</span></li>
                <li><Icon name="layers" size={17} /><span>简历、岗位与候选人资料仅限你的团队访问</span></li>
                <li><Icon name="user" size={17} /><span>AI 先整理判断依据，是否推进始终由 HR 决定</span></li>
              </>
            ) : (
              <>
                <li><Icon name="layers" size={17} /><span>团队资料集中管理，仅限已授权成员访问</span></li>
                <li><Icon name="briefcase" size={17} /><span>从筛选、评分到 JD 匹配，在同一个工作台完成</span></li>
                <li><Icon name="user" size={17} /><span>AI 提供判断依据，最终决定始终属于招聘团队</span></li>
              </>
            )}
          </ul>
        </section>
        <section className="auth-panel" aria-label={title}>
          {children}
        </section>
      </div>
    </main>
  );
}

function TrialStatusBanner({ trial }: { trial: TrialAccess | null }) {
  if (!trial) return null;
  const isExpired = trial.plan_status === "expired" || !trial.access_enabled;
  const isTrial = trial.plan_status === "trial";
  const llmCallRemaining =
    typeof trial.llm_call_remaining === "number"
      ? Math.max(0, trial.llm_call_remaining)
      : null;
  const isQuotaExhausted = isTrial && llmCallRemaining === 0;
  if (!isExpired && !isQuotaExhausted) return null;
  return (
    <section className={`trial-banner${isExpired ? " is-expired" : " is-quota-exhausted"}`} role="alert">
      <div>
        <strong>
          {isExpired ? "试用期已结束" : "试用 AI 调用额度已用完"}
        </strong>
        <p>
          {isExpired
            ? "你的工作区数据已保留。续费入口开放前，请联系 GreatSell AI 团队继续使用。"
            : "你仍可查看和管理已有数据。继续使用 AI 功能请联系 GreatSell AI 团队。"}
        </p>
      </div>
      <span>{isExpired ? "数据已保留" : "AI 调用已暂停"}</span>
    </section>
  );
}

function SideRail({
  activeView,
  canManageSettings,
  onChangeView,
  onOpenSettings,
  inert,
}: {
  activeView: View;
  canManageSettings: boolean;
  onChangeView: (view: MainWorkspaceView) => void;
  onOpenSettings: () => void;
  inert: boolean;
}) {
  return (
    <aside aria-label="主导航" className="side-rail" inert={inert}>
      <div aria-label="AI 简历筛选工作台" className="rail-mark" role="img" />
      <nav className="rail-nav">
        {navigation.map((item) => (
            <button
              aria-current={activeView === item.view ? "page" : undefined}
              aria-label={item.label}
              className={`rail-item${activeView === item.view ? " is-active" : ""}`}
              key={item.view}
              onClick={() => onChangeView(item.view)}
              type="button"
            >
              <Icon name={item.icon} size={19} />
              <span className="rail-label">{item.label}</span>
              <span className="rail-tooltip">{item.label}</span>
            </button>
          ))}
      </nav>
      <div className="rail-bottom">
        {canManageSettings && (
          <button
            aria-current={activeView === "settings" ? "page" : undefined}
            aria-label="设置"
            className={`rail-item${activeView === "settings" ? " is-active" : ""}`}
            onClick={onOpenSettings}
            type="button"
          >
            <Icon name="gear" size={18} />
            <span className="rail-label">设置</span>
            <span className="rail-tooltip">设置</span>
          </button>
        )}
      </div>
    </aside>
  );
}

function Topbar({
  globalQuery,
  onGlobalQueryChange,
  onGlobalSearchKeyDown,
  onOpenAgent,
  agentTriggerRef,
  canManageSettings,
  onAccountMenuOpen,
  onLogout,
  onNewUpload,
  onOpenSettings,
  organizationName,
  platformAdmin,
  planName,
  role,
  trial,
  userDisplayName,
  userEmail,
}: {
  globalQuery: string;
  onGlobalQueryChange: (value: string) => void;
  onGlobalSearchKeyDown: (event: ReactKeyboardEvent<HTMLInputElement>) => void;
  onOpenAgent: () => void;
  agentTriggerRef: RefObject<HTMLButtonElement | null>;
  canManageSettings: boolean;
  onAccountMenuOpen: () => void;
  onLogout: () => void;
  onNewUpload: () => void;
  onOpenSettings: () => void;
  organizationName: string | null;
  platformAdmin: boolean;
  planName: string | null;
  role: "admin" | "recruiter" | null;
  trial: TrialAccess | null;
  userDisplayName: string | null;
  userEmail: string | null;
}) {
  const trialDays = trial?.trial_days_remaining;
  const roleLabel = role === "admin" ? "管理员" : role === "recruiter" ? "招聘官" : null;
  const trialLabel =
    trial?.plan_status === "trial" && typeof trialDays === "number"
      ? `试用 ${Math.max(0, trialDays)} 天`
      : trial?.plan_status === "expired"
        ? "试用已到期"
        : null;
  const trialLlmCallRemaining =
    trial?.plan_status === "trial" && typeof trial.llm_call_remaining === "number"
      ? Math.max(0, trial.llm_call_remaining)
      : null;
  return (
    <header className="topbar">
      <div className="topbar-title-wrap">
        <p className="topbar-title">
          AI 简历筛选 <span>/ 工作台</span>
        </p>
        {(organizationName || roleLabel || planName) && (
          <p className="topbar-workspace" title={organizationName ?? undefined}>
            <span>{organizationName || "我的工作区"}</span>
            {roleLabel && <small>{roleLabel}</small>}
            {planName && <small>{planName}</small>}
          </p>
        )}
      </div>
      <label className="topbar-search">
        <Icon name="search" size={17} />
        <span className="sr-only">全局检索简历关键词</span>
        <input
          onChange={(event) => onGlobalQueryChange(event.target.value)}
          onKeyDown={onGlobalSearchKeyDown}
          placeholder="输入技能或关键词，按 Enter 筛选"
          value={globalQuery}
        />
      </label>
      <div className="topbar-actions">
        {trialLabel && <span className={`topbar-trial${trial?.plan_status === "expired" ? " is-expired" : ""}`}>{trialLabel}</span>}
        <button
          aria-label="招聘助手"
          className="button button-agent"
          onClick={onOpenAgent}
          ref={agentTriggerRef}
          type="button"
        >
          <Icon name="spark" size={16} />
          <span className="topbar-action-label">招聘助手</span>
        </button>
        <BackofficeButton
          aria-label="上传简历"
          icon={<Icon name="upload" size={16} />}
          onClick={onNewUpload}
        >
          <span className="topbar-action-label">上传简历</span>
        </BackofficeButton>
        <AccountMenu
          canManageSettings={canManageSettings}
          onOpen={onAccountMenuOpen}
          onOpenSettings={onOpenSettings}
          onLogout={onLogout}
          organizationName={organizationName}
          platformAdmin={platformAdmin}
          planName={planName}
          role={role}
          trial={trial}
          trialLlmCallRemaining={trialLlmCallRemaining}
          userDisplayName={userDisplayName}
          userEmail={userEmail}
        />
      </div>
    </header>
  );
}

function AccountMenu({
  canManageSettings,
  onOpen,
  onOpenSettings,
  onLogout,
  organizationName,
  platformAdmin,
  planName,
  role,
  trial,
  trialLlmCallRemaining,
  userDisplayName,
  userEmail,
}: {
  canManageSettings: boolean;
  onOpen: () => void;
  onOpenSettings: () => void;
  onLogout: () => void;
  organizationName: string | null;
  platformAdmin: boolean;
  planName: string | null;
  role: "admin" | "recruiter" | null;
  trial: TrialAccess | null;
  trialLlmCallRemaining: number | null;
  userDisplayName: string | null;
  userEmail: string | null;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [isPinned, setIsPinned] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const hoverCloseTimerRef = useRef<number | null>(null);
  const avatarInitials = accountAvatarInitials(userDisplayName);
  const roleLabel = role === "admin" ? "管理员" : role === "recruiter" ? "招聘官" : null;
  const displayName = userDisplayName?.trim() || "当前用户";
  const llmCallLimit =
    typeof trial?.llm_call_limit === "number" ? Math.max(0, trial.llm_call_limit) : null;
  const llmCallUsed =
    typeof trial?.llm_call_used === "number" ? Math.max(0, trial.llm_call_used) : null;
  const hasLlmCallUsage =
    llmCallLimit !== null &&
    llmCallUsed !== null &&
    trialLlmCallRemaining !== null;
  const trialDays =
    trial?.plan_status === "trial" && typeof trial.trial_days_remaining === "number"
      ? Math.max(0, trial.trial_days_remaining)
      : null;
  const triggerLabel = `账户菜单：${displayName}`;

  const cancelHoverClose = () => {
    if (hoverCloseTimerRef.current === null) return;
    window.clearTimeout(hoverCloseTimerRef.current);
    hoverCloseTimerRef.current = null;
  };

  const closeMenu = (restoreFocus = false) => {
    cancelHoverClose();
    setIsOpen(false);
    setIsPinned(false);
    if (restoreFocus) {
      window.requestAnimationFrame(() => triggerRef.current?.focus());
    }
  };

  const openMenu = () => {
    cancelHoverClose();
    if (!isOpen) onOpen();
    setIsOpen(true);
  };

  const scheduleHoverClose = () => {
    if (isPinned) return;
    cancelHoverClose();
    hoverCloseTimerRef.current = window.setTimeout(() => {
      hoverCloseTimerRef.current = null;
      setIsOpen(false);
      setIsPinned(false);
    }, 180);
  };

  useEffect(() => {
    if (!isOpen) return;

    const closeFromOutside = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && rootRef.current?.contains(target)) return;
      cancelHoverClose();
      setIsOpen(false);
      setIsPinned(false);
    };
    const closeFromEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      cancelHoverClose();
      setIsOpen(false);
      setIsPinned(false);
      window.requestAnimationFrame(() => triggerRef.current?.focus());
    };

    document.addEventListener("pointerdown", closeFromOutside);
    document.addEventListener("keydown", closeFromEscape);
    return () => {
      document.removeEventListener("pointerdown", closeFromOutside);
      document.removeEventListener("keydown", closeFromEscape);
    };
  }, [isOpen]);

  useEffect(() => () => cancelHoverClose(), []);

  const toggleMenu = () => {
    if (!isOpen) {
      onOpen();
      setIsOpen(true);
      setIsPinned(true);
      return;
    }
    if (isPinned) {
      closeMenu(true);
      return;
    }
    setIsPinned(true);
  };

  return (
    <div
      className="account-menu"
      onBlur={(event) => {
        const nextFocused = event.relatedTarget;
        if (nextFocused instanceof Node && rootRef.current?.contains(nextFocused)) return;
        cancelHoverClose();
        setIsOpen(false);
        setIsPinned(false);
      }}
      onMouseEnter={openMenu}
      onMouseLeave={scheduleHoverClose}
      ref={rootRef}
    >
      <button
        aria-controls="account-menu-popover"
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        aria-label={triggerLabel}
        className="account-menu-trigger"
        onClick={toggleMenu}
        ref={triggerRef}
        type="button"
      >
        <span className={`account-avatar${avatarInitials ? "" : " is-icon"}`} aria-hidden="true">
          {avatarInitials ?? <Icon name="user" size={17} />}
        </span>
        <Icon className="account-menu-chevron" name="chevron-down" size={15} />
      </button>
      {isOpen && (
        <section
          aria-label="账户菜单"
          className="account-menu-popover"
          id="account-menu-popover"
          role="dialog"
        >
          <div className="account-menu-profile">
            <span className={`account-avatar account-menu-profile-avatar${avatarInitials ? "" : " is-icon"}`} aria-hidden="true">
              {avatarInitials ?? <Icon name="user" size={18} />}
            </span>
            <div>
              <strong>{displayName}</strong>
              {userEmail && <p>{userEmail}</p>}
            </div>
          </div>
          {(organizationName || roleLabel || planName) && (
            <p className="account-menu-context">
              {[roleLabel, organizationName, planName].filter(Boolean).join(" · ")}
            </p>
          )}
          {trial?.plan_status === "trial" && (
            <section className="account-menu-allowance" aria-label="试用状态">
              <span>试用状态</span>
              {hasLlmCallUsage ? (
                <strong>
                  AI 调用已用 {formatWholeNumber(llmCallUsed)} / {formatWholeNumber(llmCallLimit)}，剩余 {formatWholeNumber(trialLlmCallRemaining)} 次
                </strong>
              ) : (
                <strong>AI 调用额度正在同步</strong>
              )}
              {trialDays !== null && <small>试用还剩 {trialDays} 天</small>}
            </section>
          )}
          {trial?.plan_status === "expired" && (
            <section className="account-menu-allowance is-expired" aria-label="试用状态">
              <span>试用状态</span>
              <strong>试用已到期</strong>
            </section>
          )}
          <div className="account-menu-actions">
            {canManageSettings && (
              <button
                className="account-menu-action"
                onClick={() => {
                  closeMenu();
                  onOpenSettings();
                }}
                type="button"
              >
                <Icon name="gear" size={16} />
                工作区设置
              </button>
            )}
            {platformAdmin && (
              <a className="account-menu-action" href={platformHref()} onClick={() => closeMenu()}>
                <Icon name="layers" size={16} />
                平台管理
              </a>
            )}
            <button
              className="account-menu-action is-danger"
              onClick={() => {
                closeMenu();
                onLogout();
              }}
              type="button"
            >
              <Icon name="arrow-right" size={16} />
              退出登录
            </button>
          </div>
        </section>
      )}
    </div>
  );
}

type AgentComposerContext = "assistant" | "new_profile" | "refine_profile";

interface AgentSendSnapshot {
  composerContext: AgentComposerContext;
  activeTalentProfile: {
    profileId: string;
    revisionId: string;
  } | null;
  jobVersionId: string;
}

interface AgentRetry {
  message: string;
  snapshot: AgentSendSnapshot;
}

interface AgentChatMessage {
  id: number;
  role: "assistant" | "user";
  content: string;
  candidates?: RecruitingAgentCandidate[];
  actions?: RecruitingAgentAction[];
  searchSummary?: RecruitingAgentSearchSummary | null;
  talentProfile?: TalentSearchProfile;
  talentRun?: TalentSearchRun;
  failure?: boolean;
  retry?: AgentRetry;
}

function agentMarkdownUrlTransform(url: string): string {
  const normalized = defaultUrlTransform(url);
  return /^(?:https?:|mailto:)/i.test(normalized) ? normalized : "";
}

function AgentMarkdown({ content }: { content: string }) {
  return (
    <div className="agent-markdown">
      <ReactMarkdown
        components={{
          a({ children, href, node: _node, ...props }) {
            if (!href) return <>{children}</>;
            return (
              <a
                {...props}
                href={href}
                rel="noopener noreferrer"
                target="_blank"
              >
                {children}
              </a>
            );
          },
        }}
        disallowedElements={["img"]}
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={agentMarkdownUrlTransform}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function AgentSearchSummaryPanel({
  summary,
}: {
  summary: RecruitingAgentSearchSummary;
}) {
  const hasVerificationSplit = summary.unconfirmed_count !== null;
  return (
    <section className="agent-search-summary" aria-label="候选人检索结果">
      <div className="agent-search-summary-heading">
        <span>检索结果</span>
        <small>已基于当前工作区简历完成检索</small>
      </div>
      <div className="agent-search-summary-metrics">
        <div>
          <strong>{summary.confirmed_count}</strong>
          <span>{hasVerificationSplit ? "已确认" : "符合条件"}</span>
        </div>
        {hasVerificationSplit && (
          <div className="is-unconfirmed">
            <strong>{summary.unconfirmed_count}</strong>
            <span>未确认</span>
          </div>
        )}
      </div>
      {summary.confirmation_basis && (
        <p className="agent-search-summary-note">{summary.confirmation_basis}</p>
      )}
      {summary.displayed_count < summary.confirmed_count && (
        <p className="agent-search-summary-note">
          当前展示前 {summary.displayed_count} 位候选人。
        </p>
      )}
    </section>
  );
}

function AgentCandidateCard({
  candidate,
  onOpen,
}: {
  candidate: RecruitingAgentCandidate;
  onOpen: () => void;
}) {
  const verificationEvidence = candidate.verification_evidence ?? [];
  const confirmationLabel =
    candidate.verification_status === "confirmed" ? "已确认" : "未确认";
  return (
    <article className="agent-candidate-card">
      <div className="agent-candidate-card-heading">
        <div>
          <strong>{candidate.display_name?.trim() || "未命名候选人"}</strong>
          <small>{candidate.detail}</small>
        </div>
        <div className="agent-candidate-card-actions">
          {candidate.score !== null && <b>{candidate.score.toFixed(1)}</b>}
          <button
            aria-label={`查看${candidate.display_name?.trim() || "候选人"}详情`}
            className="icon-button agent-candidate-open"
            onClick={onOpen}
            type="button"
          >
            <Icon name="chevron-right" size={16} />
          </button>
        </div>
      </div>
      {candidate.verification_status && (
        <div className="agent-verification">
          <span
            className={`agent-verification-status is-${candidate.verification_status}`}
          >
            {confirmationLabel}
          </span>
          {verificationEvidence.length ? (
            <ul className="agent-verification-evidence" aria-label="简历依据">
              {verificationEvidence.map((evidence) => (
                <li key={`${evidence.source}-${evidence.label}`}>
                  <span>
                    {evidence.source === "resume_text" ? "简历原文" : "已提取事实"}
                  </span>
                  {evidence.label}
                </li>
              ))}
            </ul>
          ) : (
            <small>简历未明确提及或当前信息无法识别。</small>
          )}
        </div>
      )}
    </article>
  );
}

function talentProfileHardFilterLabels(filters: TalentSearchHardFilters): string[] {
  const labels: string[] = [];
  if (filters.institution_classifications_any_of.length) {
    const institutionLabels: Record<InstitutionClassification, string> = {
      "985": "985",
      "211": "211",
      undergraduate: "本科院校",
      associate: "大专院校",
      secondary_vocational: "中专院校",
      overseas: "海外院校",
    };
    labels.push(
      `院校类型：${filters.institution_classifications_any_of
        .map((value) => institutionLabels[value])
        .join(" / ")}（任一）`,
    );
  }
  if (filters.education_degree_in.length) {
    labels.push(
      `教育经历：含${filters.education_degree_in.map((value) => degreeLabels[value]).join(" / ")}（任一）`,
    );
  }
  if (filters.highest_degree_in.length) {
    labels.push(
      `最高学历：${filters.highest_degree_in.map((value) => degreeLabels[value]).join(" / ")}（任一）`,
    );
  }
  if (filters.graduation_status !== "any") {
    const graduationLabel = filters.graduation_status === "fresh" ? "应届" : "往届";
    labels.push(
      `毕业：${graduationLabel}${filters.fresh_graduate_start_month && filters.fresh_graduate_end_month ? ` ${filters.fresh_graduate_start_month} 至 ${filters.fresh_graduate_end_month}` : ""}`,
    );
  }
  if (filters.min_employment_months !== null) {
    labels.push(`正式工作不少于 ${Math.round(filters.min_employment_months / 12 * 10) / 10} 年`);
  }
  if (filters.min_employment_or_internship_months !== null) {
    labels.push(`工作加实习不少于 ${Math.round(filters.min_employment_or_internship_months / 12 * 10) / 10} 年`);
  }
  if (filters.experience_types_all_of.length) {
    labels.push(
      `经历：${filters.experience_types_all_of
        .map((value) => experienceTypeOptions.find((item) => item.value === value)?.label || value)
        .join(" + ")}（全部）`,
    );
  }
  if (filters.skills_all_of.length) {
    labels.push(`精确技能：${filters.skills_all_of.join("、")}（全部）`);
  }
  if (filters.language_credentials_all_of.length) {
    labels.push(
      `证书：${filters.language_credentials_all_of
        .map((item) => item.custom_name_contains || item.credential_code.toUpperCase())
        .join("、")}（全部）`,
    );
  }
  return labels;
}

function profileCandidateAsAgentCandidate(item: CandidateSearchItem): RecruitingAgentCandidate {
  const experience = [item.latest_experience_organization, item.latest_experience_title]
    .filter(Boolean)
    .join(" · ");
  return {
    candidate_id: item.candidate_id,
    resume_id: item.resume_id,
    display_name: item.display_name,
    detail: experience || degreeLabels[item.highest_degree ?? "unknown"],
    // A library score and a profile-match score are different measurements.
    // Never show the former as an unlabeled number in the profile workflow.
    score: null,
    verification_status: null,
    verification_evidence: [],
  };
}

function talentProfileLaneLabel(lane: TalentSearchProfileMatchResult["match_lane"]): string {
  if (lane === "recommended") return "证据充分";
  if (lane === "pending") return "待核实";
  return "存在缺口";
}

function talentProfileOutcomeLabel(
  outcome: TalentSearchProfileMatchResult["requirement_results"][number]["outcome"],
): string {
  if (outcome === "met") return "已支持";
  if (outcome === "partial") return "部分支持";
  if (outcome === "unknown") return "待核实";
  return "存在缺口";
}

function TalentProfileMatchCard({
  match,
  onOpen,
}: {
  match: TalentSearchProfileMatchResult;
  onOpen: () => void;
}) {
  const confidence = match.match_confidence === null
    ? "—"
    : `${Math.round(match.match_confidence * 100)}%`;
  const needsVerification = match.requirement_results.filter(
    (item) => item.outcome === "unknown" || item.outcome === "partial",
  );
  return (
    <article className="talent-profile-match-card">
      <div className="talent-profile-match-heading">
        <div>
          <strong>{match.candidate_display_name?.trim() || "未命名候选人"}</strong>
          <small>{talentProfileLaneLabel(match.match_lane)}</small>
        </div>
        <div className="talent-profile-match-metrics" aria-label="画像匹配指标">
          <span><b>{match.match_score.toFixed(1)}</b>匹配度</span>
          <span><b>{confidence}</b>可信度</span>
          <button
            aria-label={`查看${match.candidate_display_name?.trim() || "候选人"}详情`}
            className="icon-button agent-candidate-open"
            onClick={onOpen}
            type="button"
          >
            <Icon name="chevron-right" size={16} />
          </button>
        </div>
      </div>
      {!!match.requirement_results.length && (
        <ul className="talent-profile-match-requirements" aria-label="画像核验依据">
          {match.requirement_results.map((item) => (
            <li key={item.requirement_id}>
              <span className={`is-${item.outcome}`}>{talentProfileOutcomeLabel(item.outcome)}</span>
              <div>
                <strong>{item.requirement_text}</strong>
                <small>{item.reason}</small>
              </div>
            </li>
          ))}
        </ul>
      )}
      {!!needsVerification.length && (
        <p className="talent-profile-match-note">
          待核实：{needsVerification.map((item) => item.requirement_text).join("；")}
        </p>
      )}
    </article>
  );
}

function TalentSearchRunPanel({
  run,
  onOpenCandidate,
  onRefresh,
  onLoadMore,
  onAdjustConditions,
  loading,
}: {
  run: TalentSearchRun;
  onOpenCandidate: (candidate: RecruitingAgentCandidate) => void;
  onRefresh: () => void;
  onLoadMore: () => void;
  onAdjustConditions: () => void;
  loading: boolean;
}) {
  const isProcessing = run.status === "queued" || run.status === "running";
  const isHardFilterRecall = run.result_mode === "hard_filter_recall";
  const statusLabel = isHardFilterRecall
    ? "硬筛已命中候选人"
    : (run.status === "queued"
      ? "已排队，等待 AI 核验"
      : run.status === "running"
        ? "正在依据简历事实核验"
        : run.status === "partial"
          ? "部分候选人的 AI 核验未完成"
          : "已完成依据简历事实的核验")
  const hasSemanticResults = run.match_results.length > 0;
  const shouldShowRecall = isHardFilterRecall || !hasSemanticResults;
  const appliedHardFilters = talentProfileHardFilterLabels(run.applied_hard_filters);
  const diagnostics = run.recall_diagnostics;
  return (
    <section className="talent-profile-run" aria-label="人才画像找人结果">
      <div className="talent-profile-run-heading">
        <div>
          <strong>{statusLabel}</strong>
          <small>
            严格召回 {run.total_recalled_count} 位候选人
            {isHardFilterRecall
              ? "；本次只有明确硬条件，无需 AI 语义核验。"
              : run.job_match_batch_id
                ? `；已完成 ${run.match_completed_count}/${run.match_total_count} 位 AI 核验。`
                : "；当前没有候选人进入 AI 核验。"}
          </small>
        </div>
        <button
          className="button button-ghost talent-profile-refresh"
          disabled={loading}
          onClick={onRefresh}
          type="button"
        >
          <Icon name="refresh" size={14} />刷新
        </button>
      </div>
      {(isProcessing || run.status === "partial") && (
        <p className="talent-profile-run-note">
          待核实不代表不符合，系统不会自动拒绝或录用候选人。
        </p>
      )}
      {hasSemanticResults && (
        <div className="talent-profile-match-list">
          {run.match_results.map((match) => (
            <TalentProfileMatchCard
              key={match.match_id}
              match={match}
              onOpen={() => onOpenCandidate({
                candidate_id: match.candidate_id,
                resume_id: match.resume_id,
                display_name: match.candidate_display_name,
                detail: "AI 人才画像核验结果",
                score: null,
                verification_status: null,
                verification_evidence: [],
              })}
            />
          ))}
        </div>
      )}
      {shouldShowRecall && !!run.candidate_recall.items.length && (
        <div className="agent-candidate-list">
          {run.candidate_recall.items.map((item) => {
            const candidate = profileCandidateAsAgentCandidate(item);
            return (
              <AgentCandidateCard
                candidate={candidate}
                key={candidate.resume_id}
                onOpen={() => onOpenCandidate(candidate)}
              />
            );
          })}
        </div>
      )}
      {!run.candidate_recall.items.length && !isProcessing && !hasSemanticResults && (
        <section className="talent-profile-zero-state" aria-label="零结果说明">
          <strong>
            {diagnostics?.eligible_resume_count === 0
              ? "当前工作区没有可筛选的简历"
              : "没有候选人同时满足本次严格条件"}
          </strong>
          {!!appliedHardFilters.length && (
            <div className="talent-profile-chips" aria-label="本次已应用条件">
              {appliedHardFilters.map((label) => <small key={label}>{label}</small>)}
            </div>
          )}
          {diagnostics && (
            <div className="talent-profile-recall-diagnostics">
              <p>
                可筛选简历 {diagnostics.eligible_resume_count} 份
                {diagnostics.needs_review_count > 0
                  ? `；另有 ${diagnostics.needs_review_count} 份待处理，未计入本次筛选。`
                  : "。"}
              </p>
              {!!diagnostics.steps.length && (
                <ol>
                  {diagnostics.steps.map((step) => (
                    <li key={step.key}>
                      <span>{step.label}</span>
                      <b>筛掉 {step.removed_count}，剩余 {step.remaining_count}</b>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
          <small>
            重点核验和优先项不会作为严格条件排除候选人；缺少简历证据会在后续核验中标为待核实。
          </small>
          <button
            className="button button-ghost talent-profile-adjust"
            disabled={loading}
            onClick={onAdjustConditions}
            type="button"
          >
            调整条件
          </button>
        </section>
      )}
      {!isProcessing && run.status === "partial" && !hasSemanticResults && (
        <p className="talent-profile-run-note">当前未生成可用的 AI 核验结论，请稍后刷新查看失败项。</p>
      )}
      {run.candidate_recall.next_cursor && shouldShowRecall && (
        <button className="button button-ghost talent-profile-load-more" disabled={loading} onClick={onLoadMore} type="button">
          加载更多已召回候选人
        </button>
      )}
    </section>
  );
}

function TalentSearchProfileCard({
  profile,
  run,
  onSupplement,
  onRegenerate,
  onConfirm,
  onStart,
  onRefreshRun,
  onLoadMoreRecall,
  onAdjustConditions,
  onOpenCandidate,
  loading,
}: {
  profile: TalentSearchProfile;
  run?: TalentSearchRun;
  onSupplement: () => void;
  onRegenerate: () => void;
  onConfirm: () => void;
  onStart: () => void;
  onRefreshRun: () => void;
  onLoadMoreRecall: () => void;
  onAdjustConditions: () => void;
  onOpenCandidate: (candidate: RecruitingAgentCandidate) => void;
  loading: boolean;
}) {
  const revision = profile.current_revision;
  const hardFilters = talentProfileHardFilterLabels(revision.hard_filters);
  const confirmed = profile.status === "confirmed" && revision.status === "confirmed";
  return (
    <section className="talent-profile-card" aria-label="AI 人才画像">
      <div className="talent-profile-card-heading">
        <div>
          <span>AI 人才画像</span>
          <strong>{revision.title}</strong>
        </div>
        <small className={`talent-profile-status is-${confirmed ? "confirmed" : "draft"}`}>
          {confirmed ? "已确认" : "待确认"}
        </small>
      </div>
      <p className="talent-profile-summary">{revision.summary}</p>
      <div className="talent-profile-meta">
        <span>{profile.source_type === "job" ? "来源：已保存 JD" : "来源：HR 描述"}</span>
        <span>版本 {revision.revision_number}</span>
      </div>
      {!!hardFilters.length && (
        <div className="talent-profile-section">
          <span>硬条件</span>
          <div className="talent-profile-chips">
            {hardFilters.map((label) => <small key={label}>{label}</small>)}
          </div>
          <small className="talent-profile-filter-note">
            院校类型内满足任一即可；它与学历、年限、经历、精确技能等其他硬条件同时生效。
          </small>
        </div>
      )}
      {!!revision.verification_requirements.length && (
        <div className="talent-profile-section">
          <span>重点核验</span>
          <ul className="talent-profile-requirements">
            {revision.verification_requirements.map((item) => (
              <li key={item.key}>
                <strong>{item.label}</strong>
                <small>{item.evidence_hint}</small>
              </li>
            ))}
          </ul>
        </div>
      )}
      {!!revision.preferred_requirements.length && (
        <div className="talent-profile-section">
          <span>优先项</span>
          <ul className="talent-profile-requirements">
            {revision.preferred_requirements.map((item) => (
              <li key={item.key}>
                <strong>{item.label}</strong>
                <small>{item.evidence_hint}</small>
              </li>
            ))}
          </ul>
        </div>
      )}
      {!!revision.aliases.length && (
        <div className="talent-profile-section">
          <span>可识别表达</span>
          <div className="talent-profile-chips is-muted">
            {revision.aliases.map((alias) => <small key={alias}>{alias}</small>)}
          </div>
        </div>
      )}
      {!!revision.clarifying_questions.length && !confirmed && (
        <div className="talent-profile-question">
          <Icon name="spark" size={14} />
          <span>{revision.clarifying_questions.join("；")}</span>
        </div>
      )}
      <div className="talent-profile-actions">
        <button
          className="button button-ghost"
          disabled={loading}
          onClick={onSupplement}
          type="button"
        >
          补充条件
        </button>
        {!confirmed && (
          <button
            className="button button-ghost"
            disabled={loading}
            onClick={onRegenerate}
            type="button"
          >
            <Icon name="refresh" size={14} />重新生成
          </button>
        )}
        {confirmed && !run ? (
          <button className="button button-primary" disabled={loading} onClick={onStart} type="button">
            <Icon name="match" size={15} />开始找人
          </button>
        ) : !confirmed ? (
          <button className="button button-primary" disabled={loading} onClick={onConfirm} type="button">
            <Icon name="check" size={15} />确认画像
          </button>
        ) : null}
      </div>
      {run && (
        <TalentSearchRunPanel
          loading={loading}
          onOpenCandidate={onOpenCandidate}
          onLoadMore={onLoadMoreRecall}
          onRefresh={onRefreshRun}
          onAdjustConditions={onAdjustConditions}
          run={run}
        />
      )}
    </section>
  );
}

function RecruitingAgentDrawer({
  isOpen,
  onClose,
  onOpenMatchWorkspace,
  onOpenScoreWorkspace,
  onOpenMailboxSettings,
  onOpenResume,
}: {
  isOpen: boolean;
  onClose: () => void;
  onOpenMatchWorkspace: () => void;
  onOpenScoreWorkspace: () => void;
  onOpenMailboxSettings: () => void;
  onOpenResume: (candidate: RecruitingAgentCandidate) => void;
}) {
  const [input, setInput] = useState("");
  const [jobs, setJobs] = useState<JobVersion[]>([]);
  const [jobVersionId, setJobVersionId] = useState("");
  const [composerContext, setComposerContext] = useState<AgentComposerContext>("assistant");
  const [activeTalentProfile, setActiveTalentProfile] = useState<{
    profileId: string;
    revisionId: string;
  } | null>(null);
  const [recentTalentProfiles, setRecentTalentProfiles] = useState<TalentSearchProfile[]>([]);
  const [loading, setLoading] = useState(false);
  const drawerRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const composerInputRef = useRef<HTMLTextAreaElement | null>(null);
  const [messages, setMessages] = useState<AgentChatMessage[]>([
    {
      id: 1,
      role: "assistant",
      content:
        "我是招聘助手。可以在当前工作区筛选简历、处理 JD 匹配、查看排行榜，并按已有评分规则发起全量评分。需要发起一轮主动找人时，点击“新建人才画像”；我会先整理条件，等你确认后才开始找人。",
    },
  ]);

  useEffect(() => {
    if (!isOpen) return;
    void api
      .listConfirmedJobVersions()
      .then((items) => {
        const matchableJobs = items.filter(
          (item) => item.requirements.length > 0,
        );
        setJobs(items);
        setJobVersionId((current) =>
          current &&
          items.some((item) => item.job_version_id === current)
            ? current
            : (matchableJobs[0]?.job_version_id ?? items[0]?.job_version_id ?? ""),
        );
      })
      .catch(() => setJobs([]));
    void api
      .listTalentSearchProfiles()
      .then((response) => setRecentTalentProfiles(response.items))
      .catch(() => setRecentTalentProfiles([]));
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const frame = window.requestAnimationFrame(() => closeButtonRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [isOpen]);

  const trapFocus = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key !== "Tab") return;
    const drawer = drawerRef.current;
    if (!drawer) return;
    const focusable = Array.from(
      drawer.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((element) => !element.hidden && element.getAttribute("aria-hidden") !== "true");
    if (!focusable.length) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const addAssistantReply = (turn: RecruitingAgentTurn) => {
    setMessages((current) => [
      ...current,
      {
        id: Date.now() + 1,
        role: "assistant",
        content: turn.message,
        candidates: turn.candidates,
        actions: turn.actions,
        searchSummary: turn.search_summary,
      },
    ]);
    if (turn.job_version_id) setJobVersionId(turn.job_version_id);
  };

  const updateTalentProfileMessage = (
    profile: TalentSearchProfile,
    run?: TalentSearchRun,
  ) => {
    setMessages((current) => current.map((item) => (
      item.talentProfile?.profile_id === profile.profile_id
        ? { ...item, talentProfile: profile, talentRun: run }
        : item
    )));
  };

  const appendTalentProfileReply = (profile: TalentSearchProfile, content: string) => {
    setMessages((current) => [
      ...current,
      {
        id: Date.now() + 1,
        role: "assistant",
        content,
        talentProfile: profile,
      },
    ]);
  };

  const rememberTalentProfile = (profile: TalentSearchProfile) => {
    setRecentTalentProfiles((current) => [
      profile,
      ...current.filter((item) => item.profile_id !== profile.profile_id),
    ].slice(0, 12));
  };

  const addTalentProfileFailure = (error: unknown) => {
    setMessages((current) => [
      ...current,
      {
        id: Date.now() + 1,
        role: "assistant",
        content: humanizeError(error),
        failure: true,
      },
    ]);
  };

  const prepareTalentProfileRefinement = (profile: TalentSearchProfile) => {
    setActiveTalentProfile({
      profileId: profile.profile_id,
      revisionId: profile.current_revision.revision_id,
    });
    setComposerContext("refine_profile");
    setInput("");
    window.requestAnimationFrame(() => composerInputRef.current?.focus());
  };

  const startNewTalentProfile = () => {
    if (loading) return;
    setActiveTalentProfile(null);
    setComposerContext("new_profile");
    setInput("");
    window.requestAnimationFrame(() => composerInputRef.current?.focus());
  };

  const returnToAssistant = () => {
    setComposerContext("assistant");
    setInput("");
    window.requestAnimationFrame(() => composerInputRef.current?.focus());
  };

  const regenerateTalentProfile = async (profile: TalentSearchProfile) => {
    if (loading) return;
    setLoading(true);
    try {
      const next = await api.refineTalentSearchProfile(profile.profile_id, {
        revision_id: profile.current_revision.revision_id,
        message: "请保留原始招聘目标，重新梳理一版人才画像。删去不明确的硬条件，并给出需要 HR 核验的重点。",
      });
      setActiveTalentProfile({
        profileId: next.profile_id,
        revisionId: next.current_revision.revision_id,
      });
      rememberTalentProfile(next);
      setComposerContext("refine_profile");
      updateTalentProfileMessage(next);
    } catch (error) {
      addTalentProfileFailure(error);
    } finally {
      setLoading(false);
    }
  };

  const confirmTalentProfile = async (profile: TalentSearchProfile) => {
    if (loading) return;
    setLoading(true);
    try {
      const confirmed = await api.confirmTalentSearchProfile(profile.profile_id, {
        revision_id: profile.current_revision.revision_id,
      });
      setActiveTalentProfile({
        profileId: confirmed.profile_id,
        revisionId: confirmed.current_revision.revision_id,
      });
      rememberTalentProfile(confirmed);
      setComposerContext("assistant");
      updateTalentProfileMessage(confirmed);
    } catch (error) {
      addTalentProfileFailure(error);
    } finally {
      setLoading(false);
    }
  };

  const startTalentProfileSearch = async (profile: TalentSearchProfile) => {
    if (loading) return;
    setLoading(true);
    try {
      const run = await api.startTalentSearchProfileRun(profile.profile_id, {
        revision_id: profile.current_revision.revision_id,
        limit: 20,
      });
      setComposerContext("assistant");
      updateTalentProfileMessage(profile, run);
    } catch (error) {
      addTalentProfileFailure(error);
    } finally {
      setLoading(false);
    }
  };

  const refreshTalentProfileRun = async (profile: TalentSearchProfile, run: TalentSearchRun) => {
    if (loading) return;
    setLoading(true);
    try {
      const refreshed = await api.getTalentSearchProfileRun(profile.profile_id, run.run_id, { limit: 20 });
      updateTalentProfileMessage(profile, refreshed);
    } catch (error) {
      addTalentProfileFailure(error);
    } finally {
      setLoading(false);
    }
  };

  const loadMoreTalentProfileRecall = async (
    profile: TalentSearchProfile,
    run: TalentSearchRun,
  ) => {
    const cursor = run.candidate_recall.next_cursor;
    if (loading || !cursor) return;
    setLoading(true);
    try {
      const next = await api.getTalentSearchProfileRun(profile.profile_id, run.run_id, {
        limit: 20,
        cursor,
      });
      const seen = new Set(run.candidate_recall.items.map((item) => item.resume_id));
      updateTalentProfileMessage(profile, {
        ...next,
        candidate_recall: {
          ...next.candidate_recall,
          items: [
            ...run.candidate_recall.items,
            ...next.candidate_recall.items.filter((item) => !seen.has(item.resume_id)),
          ],
        },
      });
    } catch (error) {
      addTalentProfileFailure(error);
    } finally {
      setLoading(false);
    }
  };

  const resumeTalentProfile = async (profileId: string) => {
    if (loading) return;
    setLoading(true);
    try {
      const profile = await api.getTalentSearchProfile(profileId);
      setComposerContext(profile.status === "confirmed" ? "assistant" : "refine_profile");
      setActiveTalentProfile({
        profileId: profile.profile_id,
        revisionId: profile.current_revision.revision_id,
      });
      rememberTalentProfile(profile);
      appendTalentProfileReply(
        profile,
        profile.status === "confirmed"
          ? "已恢复这份已确认的人才画像。可查看本次找人结果，或补充条件后形成新草案。"
          : "已恢复这份人才画像草案。请确认，或继续补充条件。",
      );
    } catch (error) {
      addTalentProfileFailure(error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!isOpen || loading) return undefined;
    const pending = messages.find((item) => (
      item.talentProfile
      && item.talentRun
      && (item.talentRun.status === "queued" || item.talentRun.status === "running")
    ));
    if (!pending?.talentProfile || !pending.talentRun) return undefined;
    const timer = window.setTimeout(() => {
      void api.getTalentSearchProfileRun(
        pending.talentProfile!.profile_id,
        pending.talentRun!.run_id,
        { limit: 20 },
      ).then((refreshed) => {
        updateTalentProfileMessage(pending.talentProfile!, refreshed);
      }).catch(() => {
        // A transient poll failure should not flood the recruiter chat. The
        // visible refresh button remains available for an explicit retry.
      });
    }, 4_000);
    return () => window.clearTimeout(timer);
  }, [isOpen, loading, messages]);

  const send = async (
    raw: string,
    snapshot?: AgentSendSnapshot,
    options?: { clearComposer?: boolean },
  ) => {
    const message = raw.trim();
    if (!message || loading) return;
    const request = snapshot ?? {
      composerContext,
      activeTalentProfile,
      jobVersionId,
    };
    const isProfileWorkflow = request.composerContext === "new_profile"
      || (request.composerContext === "refine_profile" && request.activeTalentProfile !== null);
    const isRefinement = request.composerContext === "refine_profile"
      && request.activeTalentProfile !== null;
    if (options?.clearComposer !== false) setInput("");
    setMessages((current) => [
      ...current,
      { id: Date.now(), role: "user", content: message },
    ]);
    setLoading(true);
    try {
      if (isProfileWorkflow) {
        const profile = isRefinement && request.activeTalentProfile
          ? await api.refineTalentSearchProfile(request.activeTalentProfile.profileId, {
            revision_id: request.activeTalentProfile.revisionId,
            message,
          })
          : await api.generateTalentSearchProfile({
            message,
            job_version_id: request.jobVersionId || null,
          });
        setActiveTalentProfile({
          profileId: profile.profile_id,
          revisionId: profile.current_revision.revision_id,
        });
        rememberTalentProfile(profile);
        setComposerContext("refine_profile");
        appendTalentProfileReply(
          profile,
          isRefinement
            ? "我已根据你的补充更新人才画像。请确认，或继续补充条件。"
            : "我先整理了一版人才画像草稿。请看硬条件和重点核验项，还想补什么吗？确认后才会开始找人。",
        );
      } else {
        // Source-only JDs are intentionally usable as input for an AI talent
        // profile, but the existing conversational assistant only understands
        // confirmed, matchable JD versions. Do not turn selecting an original
        // publication into a generic server error in the normal chat mode.
        const selectedMatchableJob = jobs.some(
          (job) => job.job_version_id === request.jobVersionId && job.requirements.length > 0,
        );
        const turn = await api.runRecruitingAgentTurn({
          message,
          job_version_id: selectedMatchableJob ? request.jobVersionId : null,
        });
        addAssistantReply(turn);
      }
    } catch (error) {
      const failureMessage = isProfileWorkflow ? humanizeError(error) : humanizeAgentError(error);
      setMessages((current) => [
        ...current,
        {
          id: Date.now() + 1,
          role: "assistant",
          content: failureMessage,
          failure: true,
          retry: isRetryableAgentError(error) ? { message, snapshot: request } : undefined,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <aside
      aria-label="招聘助手"
      aria-modal="true"
      className={`recruiting-agent-drawer${isOpen ? " is-open" : ""}`}
      inert={!isOpen}
      onKeyDown={trapFocus}
      ref={drawerRef}
      role="dialog"
    >
      <header className="agent-header">
        <div className="agent-title-wrap">
          <span className="agent-mark"><Icon name="spark" size={17} /></span>
          <div>
            <h2>招聘助手</h2>
            <p>工具执行，结论可追溯</p>
          </div>
        </div>
        <button
          aria-label="关闭招聘助手"
          className="icon-button"
          onClick={onClose}
          ref={closeButtonRef}
          type="button"
        >
          <Icon name="close" size={18} />
        </button>
      </header>
      <div className="agent-context">
        <div className="agent-context-actions">
          <button
            className="button button-ghost agent-new-profile-button"
            disabled={loading}
            onClick={startNewTalentProfile}
            type="button"
          >
            <Icon name="spark" size={14} />新建人才画像
          </button>
        </div>
        {composerContext !== "assistant" && (
          <div className="agent-profile-context" role="status">
            <span>
              {composerContext === "new_profile"
                ? "正在新建人才画像：先给出可确认草案，不会直接检索候选人。"
                : "正在补充当前人才画像：发送后会生成新草案，不会直接检索候选人。"}
            </span>
            <button className="text-button" onClick={returnToAssistant} type="button">
              返回助手
            </button>
          </div>
        )}
        <div className="select-wrap">
          <label className="sr-only" htmlFor="agent-job-version">关联 JD</label>
          <select
            className="select-field"
            id="agent-job-version"
            onChange={(event) => setJobVersionId(event.target.value)}
            value={jobVersionId}
          >
            <option value="">不关联 JD</option>
            {jobs.map((item) => (
              <option key={item.job_version_id} value={item.job_version_id}>
                {item.title} · v{item.version}{item.requirements.length ? "" : " · 原版"}
              </option>
            ))}
          </select>
          <Icon name="chevron-down" size={15} />
        </div>
        {!!recentTalentProfiles.length && (
          <div className="agent-profile-history" aria-label="继续已保存的人才画像">
            <span>继续已保存画像</span>
            <div>
              {recentTalentProfiles.slice(0, 4).map((profile) => (
                <button
                  className="button button-ghost"
                  disabled={loading}
                  key={profile.profile_id}
                  onClick={() => void resumeTalentProfile(profile.profile_id)}
                  type="button"
                >
                  {profile.current_revision.title}
                  <small>{profile.status === "confirmed" ? "已确认" : "草案"}</small>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className="agent-conversation" aria-live="polite">
        {messages.map((item) => (
          <article
            className={`agent-message is-${item.role}${item.failure ? " is-error" : ""}`}
            key={item.id}
          >
            {item.role === "assistant" ? (
              <AgentMarkdown content={item.content} />
            ) : (
              <p>{item.content}</p>
            )}
            {item.retry && (
              <div className="agent-retry-row">
                <button
                  className="button button-ghost agent-retry-button"
                  disabled={loading}
                  onClick={() => void send(
                    item.retry!.message,
                    item.retry!.snapshot,
                    { clearComposer: false },
                  )}
                  type="button"
                >
                  <Icon name="refresh" size={15} />
                  重新发送
                </button>
              </div>
            )}
            {item.searchSummary && <AgentSearchSummaryPanel summary={item.searchSummary} />}
            {item.talentProfile && (
              <TalentSearchProfileCard
                loading={loading}
                onConfirm={() => void confirmTalentProfile(item.talentProfile!)}
                onOpenCandidate={onOpenResume}
                onLoadMoreRecall={() => {
                  if (item.talentRun) {
                    void loadMoreTalentProfileRecall(item.talentProfile!, item.talentRun);
                  }
                }}
                onRefreshRun={() => {
                  if (item.talentRun) {
                    void refreshTalentProfileRun(item.talentProfile!, item.talentRun);
                  }
                }}
                onRegenerate={() => void regenerateTalentProfile(item.talentProfile!)}
                onStart={() => void startTalentProfileSearch(item.talentProfile!)}
                onSupplement={() => prepareTalentProfileRefinement(item.talentProfile!)}
                onAdjustConditions={() => prepareTalentProfileRefinement(item.talentProfile!)}
                profile={item.talentProfile}
                run={item.talentRun}
              />
            )}
            {!!item.candidates?.length && (
              <div className="agent-candidate-list">
                {item.candidates.map((candidate) => (
                  <AgentCandidateCard
                    key={candidate.resume_id}
                    candidate={candidate}
                    onOpen={() => onOpenResume(candidate)}
                  />
                ))}
              </div>
            )}
            {item.actions?.some((action) => action.action === "open_match_workspace") && (
              <button className="button button-ghost agent-workspace-button" onClick={onOpenMatchWorkspace} type="button">
                <Icon name="match" size={15} />
                打开 JD 匹配工作区
              </button>
            )}
            {item.actions?.some((action) => action.action === "open_score_workspace") && (
              <button className="button button-ghost agent-workspace-button" onClick={onOpenScoreWorkspace} type="button">
                <Icon name="layers" size={15} />
                打开评分工作台
              </button>
            )}
            {item.actions?.some((action) => action.action === "open_mailbox_workspace") && (
              <button className="button button-ghost agent-workspace-button" onClick={onOpenMailboxSettings} type="button">
                <Icon name="inbox" size={15} />
                打开收件邮箱设置
              </button>
            )}
          </article>
        ))}
        {loading && (
          <article className="agent-message is-assistant agent-loading">
            <i className="spinner" /> 正在调用招聘工具…
          </article>
        )}
      </div>
      <div className="agent-composer">
        {composerContext !== "assistant" && (
          <p className="agent-profile-context-note">
            {composerContext === "new_profile"
              ? "我会先整理可确认的人才画像；发送后不会直接检索候选人。"
              : "这条消息会更新当前人才画像；发送后不会直接检索候选人。"}
          </p>
        )}
        <form
          className="agent-input-row"
          onSubmit={(event) => {
            event.preventDefault();
            void send(input);
          }}
        >
          <label className="sr-only" htmlFor="agent-message">向招聘助手提问</label>
          <textarea
            id="agent-message"
            onChange={(event) => setInput(event.target.value)}
            placeholder={composerContext === "new_profile"
              ? "描述你想找的人，例如：需要有 LangChain 项目经验的本科毕业工程师"
              : composerContext === "refine_profile"
                ? "补充或调整条件，例如：正式工作和实习都要有，项目中重点看 RAG 落地"
                : "例如：找 985 或 211 院校、3 年以上 Python 的候选人；或点击“新建人才画像”发起一轮找人"}
            ref={composerInputRef}
            rows={2}
            value={input}
          />
          <button aria-label="发送提问" className="button button-primary" disabled={loading || !input.trim()} type="submit">
            <Icon name="arrow-right" size={17} />
          </button>
        </form>
      </div>
    </aside>
  );
}

function candidateDataDeletionReasonLabel(reason: CandidateDataDeletionReason): string {
  return candidateDataDeletionReasonOptions.find((option) => option.value === reason)?.label
    ?? "系统保留策略";
}

function candidateDataExportStatusLabel(status: string): string {
  switch (status) {
    case "queued": return "等待导出";
    case "running": return "正在导出";
    case "completed": return "可下载";
    case "retryable_failed": return "等待重试";
    case "failed": return "导出失败";
    case "cancelled": return "已取消";
    case "revoked": return "已撤销";
    case "expired": return "已过期";
    default: return status;
  }
}

function candidateDataExportStatusClass(status: string): string {
  if (status === "completed") return "is-success";
  if (status === "failed" || status === "revoked" || status === "expired") return "is-error";
  if (status === "retryable_failed") return "is-warning";
  return "is-progress";
}

function candidateDataRetentionRunStatusLabel(status: string): string {
  switch (status) {
    case "completed": return "已完成";
    case "completed_with_errors": return "完成但有异常";
    case "failed": return "清理失败";
    case "running": return "正在处理";
    default: return status;
  }
}

function candidateDataAuditActionLabel(event: CandidateDataAuditEvent): string {
  const labels: Record<string, string> = {
    resume_original_view_authorized: "已授权查看原文件",
    resume_original_download_authorized: "已授权下载原文件",
    resume_delete_requested: "已请求删除当前简历",
    candidate_delete_requested: "已请求删除候选人资料",
    resume_restored: "已恢复简历",
    candidate_restored: "已恢复候选人资料",
    retention_policy_changed: "已更新保留策略",
    retention_cleanup_completed: "已执行到期清理",
    candidate_data_export_requested: "已创建资料导出",
    candidate_data_export_cancelled: "已取消资料导出",
    candidate_data_export_download_authorized: "已授权下载导出文件",
  };
  return labels[event.action] ?? event.action;
}

function CandidateDataLifecyclePage({
  notify,
  onOpenLibrary,
  embedded = false,
}: {
  notify: (kind: ToastKind, message: string) => void;
  onOpenLibrary: () => void;
  embedded?: boolean;
}) {
  const pageClassName = `candidate-data-page${embedded ? " is-embedded" : " page-frame"}`;
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [policy, setPolicy] = useState<CandidateDataRetentionPolicy | null>(null);
  const [retentionMode, setRetentionMode] = useState<CandidateDataRetentionMode>("manual");
  const [retentionDays, setRetentionDays] = useState("365");
  const [preview, setPreview] = useState<CandidateDataRetentionPreview | null>(null);
  const [runs, setRuns] = useState<CandidateDataRetentionCleanupRun[]>([]);
  const [deletions, setDeletions] = useState<CandidateDataDeletionBatch[]>([]);
  const [exports, setExports] = useState<CandidateDataExport[]>([]);
  const [auditEvents, setAuditEvents] = useState<CandidateDataAuditEvent[]>([]);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const [restoringBatchId, setRestoringBatchId] = useState<string | null>(null);
  const [cancellingExportId, setCancellingExportId] = useState<string | null>(null);
  const [downloadingExportId, setDownloadingExportId] = useState<string | null>(null);

  const load = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    else setRefreshing(true);
    setError(null);
    try {
      const [nextPolicy, nextRuns, nextDeletions, nextExports, nextAuditEvents] = await Promise.all([
        api.getCandidateDataRetentionPolicy(),
        api.listCandidateDataRetentionCleanupRuns(),
        api.listCandidateDataDeletions(),
        api.listCandidateDataExports(),
        api.listCandidateDataAuditEvents(30),
      ]);
      setPolicy(nextPolicy);
      setRetentionMode(nextPolicy.mode);
      setRetentionDays(nextPolicy.retention_days ? String(nextPolicy.retention_days) : "365");
      setRuns(nextRuns.items);
      setDeletions(nextDeletions.items);
      setExports(nextExports.items);
      setAuditEvents(nextAuditEvents.items);
    } catch (loadError) {
      const message = humanizeError(loadError);
      setError(message);
      if (!showLoading) notify("error", message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const normalizedRetentionDays = Number.parseInt(retentionDays, 10);
  const validRetentionDays = Number.isInteger(normalizedRetentionDays)
    && normalizedRetentionDays >= 30
    && normalizedRetentionDays <= 3650;
  const previewMatchesPolicy = Boolean(
    preview
    && policy
    && preview.retention_days === normalizedRetentionDays
    && preview.policy_version === policy.version,
  );

  const previewRetention = async () => {
    if (!validRetentionDays || previewing) return;
    setPreviewing(true);
    try {
      setPreview(await api.previewCandidateDataRetention(normalizedRetentionDays));
    } catch (previewError) {
      notify("error", humanizeError(previewError));
    } finally {
      setPreviewing(false);
    }
  };

  const saveRetentionPolicy = async () => {
    if (savingPolicy) return;
    if (retentionMode === "automatic" && (!validRetentionDays || !previewMatchesPolicy || !preview)) {
      notify("error", "请先预览当前天数对应的清理范围，再启用自动清理。");
      return;
    }
    setSavingPolicy(true);
    try {
      const saved = await api.updateCandidateDataRetentionPolicy(
        retentionMode === "automatic"
          ? {
            mode: "automatic",
            retention_days: normalizedRetentionDays,
            preview_token: preview!.preview_token,
          }
          : { mode: "manual" },
      );
      setPolicy(saved);
      setRetentionMode(saved.mode);
      setRetentionDays(saved.retention_days ? String(saved.retention_days) : "365");
      setPreview(null);
      notify("success", saved.mode === "automatic" ? "已启用候选人资料自动保留策略。" : "已改为手动保留，系统不会按期限自动删除候选人资料。");
      await load(false);
    } catch (saveError) {
      notify("error", humanizeError(saveError));
    } finally {
      setSavingPolicy(false);
    }
  };

  const runRetentionCleanup = async () => {
    if (cleaning) return;
    setCleaning(true);
    try {
      const run = await api.runCandidateDataRetentionCleanup();
      setRuns((current) => [run, ...current.filter((item) => item.run_id !== run.run_id)]);
      notify(
        "success",
        run.queued_count
          ? `已将 ${run.queued_count} 位到期候选人加入可恢复删除流程。`
          : "本次没有符合条件的候选人需要进入删除流程。",
      );
      await load(false);
    } catch (cleanupError) {
      notify("error", humanizeError(cleanupError));
    } finally {
      setCleaning(false);
    }
  };

  const restoreDeletion = async (deletion: CandidateDataDeletionBatch) => {
    if (restoringBatchId) return;
    setRestoringBatchId(deletion.deletion_batch_id);
    try {
      const restored = await api.restoreCandidateDataDeletion(deletion.deletion_batch_id);
      notify(
        "success",
        `已恢复 ${restored.restored_candidate_count} 位候选人和 ${restored.restored_resume_count} 份简历。`,
      );
      await load(false);
    } catch (restoreError) {
      notify("error", humanizeError(restoreError));
    } finally {
      setRestoringBatchId(null);
    }
  };

  const cancelExport = async (item: CandidateDataExport) => {
    if (cancellingExportId) return;
    setCancellingExportId(item.export_id);
    try {
      const updated = await api.cancelCandidateDataExport(item.export_id);
      setExports((current) => current.map((entry) => entry.export_id === updated.export_id ? updated : entry));
      notify("success", "导出任务已取消，已撤销其下载权限。");
      await load(false);
    } catch (cancelError) {
      notify("error", humanizeError(cancelError));
    } finally {
      setCancellingExportId(null);
    }
  };

  const downloadExport = async (item: CandidateDataExport) => {
    if (downloadingExportId || item.status !== "completed") return;
    setDownloadingExportId(item.export_id);
    try {
      const access = await api.requestCandidateDataExportDownload(item.export_id);
      const blob = await api.getAuthorizedFileBlob(access.access_url);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `candidate-data-export-${item.export_id.slice(0, 8)}.zip`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      notify("success", "已开始下载导出文件，系统已记录本次访问。");
      await load(false);
    } catch (downloadError) {
      notify("error", humanizeError(downloadError));
    } finally {
      setDownloadingExportId(null);
    }
  };

  if (loading && !policy) {
    return <div className={pageClassName}><TableSkeleton /></div>;
  }

  return (
    <div className={pageClassName}>
      <header className="page-heading">
        <div>
          {embedded ? <h2>候选人数据与保留</h2> : <h1>数据保留与恢复</h1>}
          <p>在工作区内管理候选人资料的保留期限、可恢复删除、导出文件和原件访问记录。所有清理操作先进入恢复期，不会直接做出招聘结论。</p>
        </div>
        <div className="candidate-data-page-actions">
          <button className="button" disabled={refreshing} onClick={() => void load(false)} type="button">
            {refreshing ? <><i className="spinner" />正在刷新</> : <><Icon name="refresh" size={16} />刷新记录</>}
          </button>
          <button className="button button-ghost" onClick={onOpenLibrary} type="button">返回简历库</button>
        </div>
      </header>

      {error && <p className="library-error" role="status">{error}</p>}

      <div className="candidate-data-layout">
        <div className="candidate-data-main-column">
          <section className="panel candidate-data-retention-panel">
            <div className="panel-heading">
              <div>
                <h2>候选人资料保留策略</h2>
                <p>自动清理只处理到期且未被保留标记的候选人，先进入可恢复删除流程。</p>
              </div>
              <span className={`status-pill${retentionMode === "automatic" ? " is-warning" : ""}`}>{retentionMode === "automatic" ? "自动保留" : "手动保留"}</span>
            </div>
            <fieldset className="candidate-data-retention-form" disabled={savingPolicy || previewing}>
              <div className="candidate-data-retention-options" role="radiogroup" aria-label="候选人资料保留方式">
                <label className="choice-row candidate-data-retention-option">
                  <input checked={retentionMode === "manual"} name="candidate-data-retention-mode" onChange={() => { setRetentionMode("manual"); setPreview(null); }} type="radio" />
                  <span><strong>手动保留</strong><small>不会按期限自动删除候选人资料。</small></span>
                </label>
                <label className="choice-row candidate-data-retention-option">
                  <input checked={retentionMode === "automatic"} name="candidate-data-retention-mode" onChange={() => setRetentionMode("automatic")} type="radio" />
                  <span><strong>自动保留</strong><small>到期候选人进入可恢复删除流程，恢复期结束后才清理。</small></span>
                </label>
              </div>
              {retentionMode === "automatic" && (
                <label className="field-stack candidate-data-retention-days" htmlFor="candidate-data-retention-days">
                  <span className="field-label">资料保留天数</span>
                  <input className="field" id="candidate-data-retention-days" inputMode="numeric" max="3650" min="30" onChange={(event) => { setRetentionDays(event.target.value); setPreview(null); }} type="number" value={retentionDays} />
                  <span className="field-help">可设置 30 至 3650 天。保存前必须先预览本次影响范围。</span>
                </label>
              )}
            </fieldset>
            {retentionMode === "automatic" && preview && (
              <section className="candidate-data-retention-preview" aria-live="polite">
                <div>
                  <strong>{previewMatchesPolicy ? "当前预览可用于保存" : "预览已过期，请重新计算"}</strong>
                  <p>计算于 {formatLibraryDate(preview.calculated_at)}，不会删除任何数据。</p>
                </div>
                <div className="candidate-data-retention-preview-stats">
                  <span><strong>{preview.eligible_candidate_count}</strong> 位候选人可能到期</span>
                  <span><strong>{preview.eligible_resume_count}</strong> 份简历关联</span>
                  <span><strong>{preview.held_candidate_count}</strong> 位被保留标记跳过</span>
                </div>
              </section>
            )}
            <div className="review-actions candidate-data-retention-actions">
              {retentionMode === "automatic" && (
                <button className="button" disabled={!validRetentionDays || previewing} onClick={() => void previewRetention()} type="button">
                  {previewing ? <><i className="spinner" />正在预览</> : <><Icon name="search" size={16} />预览清理范围</>}
                </button>
              )}
              <button className="button button-primary" disabled={savingPolicy || (retentionMode === "automatic" && !previewMatchesPolicy)} onClick={() => void saveRetentionPolicy()} type="button">
                {savingPolicy ? <><i className="spinner" />正在保存</> : <><Icon name="check" size={16} />保存保留策略</>}
              </button>
              <button className="button button-danger-ghost" disabled={cleaning || policy?.mode !== "automatic"} onClick={() => void runRetentionCleanup()} type="button">
                {cleaning ? <><i className="spinner" />正在执行</> : "立即执行到期清理"}
              </button>
            </div>
          </section>

          <section className="panel candidate-data-recovery-panel">
            <div className="panel-heading">
              <div>
                <h2>可恢复删除</h2>
                <p>此处仅显示删除批次与数量，不重新展示已删除候选人的姓名或原始文件名。</p>
              </div>
              <span className="status-pill">{deletions.length} 条记录</span>
            </div>
            {deletions.length ? (
              <div className="table-scroll">
                <table className="candidate-table candidate-data-table">
                  <thead><tr><th scope="col">范围</th><th scope="col">原因</th><th scope="col">影响</th><th scope="col">恢复截止</th><th scope="col">状态</th><th scope="col" aria-label="恢复操作" /></tr></thead>
                  <tbody>
                    {deletions.map((item) => (
                      <tr key={item.deletion_batch_id}>
                        <td>{item.trigger_type === "manual_resume" ? "单份简历" : "候选人资料"}</td>
                        <td>{candidateDataDeletionReasonLabel(item.reason)}</td>
                        <td>{item.affected_candidate_count} 位候选人 · {item.affected_resume_count} 份简历</td>
                        <td>{formatLibraryDate(item.recovery_deadline_at)}</td>
                        <td><span className={`status-pill${item.restorable ? " is-warning" : ""}`}>{item.restorable ? "可恢复" : item.status === "restored" ? "已恢复" : "已进入清理"}</span></td>
                        <td>
                          {item.restorable && (
                            <button className="button button-ghost candidate-data-inline-action" disabled={restoringBatchId === item.deletion_batch_id} onClick={() => void restoreDeletion(item)} type="button">
                              {restoringBatchId === item.deletion_batch_id ? <><i className="spinner" />正在恢复</> : "恢复"}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <CandidateDataEmptyState title="没有可恢复删除记录" description="从候选人抽屉删除资料后，恢复期限内的批次会显示在这里。" />}
          </section>

          <section className="panel candidate-data-export-panel">
            <div className="panel-heading">
              <div>
                <h2>资料导出</h2>
                <p>导出文件仅在到期前可下载。候选人资料被删除后，相关导出会立即撤销。</p>
              </div>
              <span className="status-pill">{exports.length} 项任务</span>
            </div>
            {exports.length ? (
              <div className="table-scroll">
                <table className="candidate-table candidate-data-table">
                  <thead><tr><th scope="col">内容</th><th scope="col">创建时间</th><th scope="col">有效期</th><th scope="col">状态</th><th scope="col" aria-label="导出操作" /></tr></thead>
                  <tbody>
                    {exports.map((item) => (
                      <tr key={item.export_id}>
                        <td>{item.item_count} 位候选人{item.include_originals ? " · 含原始文件" : " · 不含原始文件"}</td>
                        <td>{formatLibraryDate(item.requested_at)}</td>
                        <td>{item.expires_at ? formatLibraryDate(item.expires_at) : "—"}</td>
                        <td><span className={`status-pill ${candidateDataExportStatusClass(item.status)}`}>{candidateDataExportStatusLabel(item.status)}</span>{item.error_code && <small className="candidate-data-error-code">{item.error_code}</small>}</td>
                        <td className="candidate-data-export-actions">
                          {item.status === "completed" && <button className="button button-ghost candidate-data-inline-action" disabled={downloadingExportId === item.export_id} onClick={() => void downloadExport(item)} type="button">{downloadingExportId === item.export_id ? <><i className="spinner" />正在准备</> : <><Icon name="download" size={15} />下载</>}</button>}
                          {["queued", "running", "retryable_failed"].includes(item.status) && <button className="button button-ghost candidate-data-inline-action" disabled={cancellingExportId === item.export_id} onClick={() => void cancelExport(item)} type="button">{cancellingExportId === item.export_id ? <><i className="spinner" />正在取消</> : "取消"}</button>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <CandidateDataEmptyState title="还没有资料导出" description="在候选人抽屉中创建导出后，可在这里查看进度并下载。" />}
          </section>
        </div>

        <aside className="candidate-data-side-column">
          <section className="panel candidate-data-audit-panel">
            <div className="panel-heading">
              <div>
                <h2>访问与操作审计</h2>
                <p>查看、下载原件与导出文件均会记录在此。</p>
              </div>
            </div>
            {auditEvents.length ? (
              <ol className="candidate-data-audit-list">
                {auditEvents.map((event) => (
                  <li key={event.event_id}>
                    <strong>{candidateDataAuditActionLabel(event)}</strong>
                    <span>{formatLibraryDate(event.created_at)}</span>
                    {event.reason_code && <small>{candidateDataDeletionReasonLabel(event.reason_code as CandidateDataDeletionReason)}</small>}
                  </li>
                ))}
              </ol>
            ) : <CandidateDataEmptyState title="暂无审计记录" description="后续的原件访问、导出和删除操作会显示在这里。" />}
          </section>

          <section className="panel candidate-data-cleanup-history">
            <div className="panel-heading">
              <div><h2>到期清理记录</h2><p>系统只将符合策略的数据加入可恢复删除流程。</p></div>
            </div>
            {runs.length ? (
              <ol className="candidate-data-cleanup-list">
                {runs.map((run) => (
                  <li key={run.run_id}>
                    <div><strong>{candidateDataRetentionRunStatusLabel(run.status)}</strong><span>{formatLibraryDate(run.finished_at ?? run.started_at)}</span></div>
                    <small>扫描 {run.scanned_count}，加入删除 {run.queued_count}{run.skipped_hold_count ? `，保留跳过 ${run.skipped_hold_count}` : ""}{run.failed_count ? `，异常 ${run.failed_count}` : ""}</small>
                  </li>
                ))}
              </ol>
            ) : <CandidateDataEmptyState title="尚未执行到期清理" description="启用自动保留后，可先预览再手动执行首次清理。" />}
          </section>
        </aside>
      </div>
    </div>
  );
}

function CandidateDataEmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="candidate-data-empty">
      <strong>{title}</strong>
      <span>{description}</span>
    </div>
  );
}

function WorkspaceSettingsPage({
  activeSection,
  canManageCandidateData,
  canManageMailbox,
  notify,
  onImported,
  onOpenLibrary,
  onSelectSection,
  role,
}: {
  activeSection: SettingsSection;
  canManageCandidateData: boolean;
  canManageMailbox: boolean;
  notify: (kind: ToastKind, message: string) => void;
  onImported: () => void;
  onOpenLibrary: () => void;
  onSelectSection: (section: SettingsSection) => void;
  role: "admin" | "recruiter" | null;
}) {
  const sections: Array<{
    id: SettingsSection;
    label: string;
    description: string;
    icon: IconName;
  }> = [];

  if (canManageMailbox) {
    sections.push({
      id: "mailbox",
      label: "收件邮箱",
      description: "管理收件通道、同步和附件入库保留。",
      icon: "inbox",
    });
  }
  if (canManageCandidateData) {
    sections.push({
      id: "data",
      label: "候选人数据与保留",
      description: "管理资料保留、导出、删除和访问记录。",
      icon: "gear",
    });
  }

  const currentSection = sections.some((section) => section.id === activeSection)
    ? activeSection
    : sections[0]?.id;
  if (!currentSection) return null;

  return (
    <div className="page-frame settings-page">
      <header className="page-heading">
        <div>
          <h1>设置</h1>
          <p>管理当前工作区的收件通道，以及候选人资料的保留和访问规则。</p>
        </div>
      </header>
      <div className="settings-layout">
        <nav aria-label="设置分类" className="panel settings-navigation">
          <p className="settings-navigation-label">工作区设置</p>
          <div aria-orientation="vertical" className="settings-navigation-list" role="tablist">
            {sections.map((section) => {
              const selected = section.id === currentSection;
              return (
                <button
                  aria-controls={`settings-panel-${section.id}`}
                  aria-label={section.label}
                  aria-selected={selected}
                  className={`settings-navigation-item${selected ? " is-active" : ""}`}
                  id={`settings-tab-${section.id}`}
                  key={section.id}
                  onClick={() => onSelectSection(section.id)}
                  role="tab"
                  type="button"
                >
                  <span className="settings-navigation-icon"><Icon name={section.icon} size={17} /></span>
                  <span>
                    <strong>{section.label}</strong>
                    <small>{section.description}</small>
                  </span>
                </button>
              );
            })}
          </div>
        </nav>
        <section
          aria-labelledby={`settings-tab-${currentSection}`}
          className="settings-content"
          id={`settings-panel-${currentSection}`}
          role="tabpanel"
          tabIndex={-1}
        >
          {currentSection === "mailbox" ? (
            <MailboxPage
              embedded
              humanizeError={humanizeError}
              notify={notify}
              onImported={onImported}
              role={role}
            />
          ) : (
            <CandidateDataLifecyclePage
              embedded
              notify={notify}
              onOpenLibrary={onOpenLibrary}
            />
          )}
        </section>
      </div>
    </div>
  );
}


const candidateDataDeletionReasonOptions: Array<{
  value: CandidateDataDeletionReason;
  label: string;
}> = [
  { value: "candidate_request", label: "候选人提出删除" },
  { value: "recruitment_closed", label: "招聘流程结束" },
  { value: "duplicate", label: "重复资料" },
  { value: "other", label: "其他原因" },
];



function UploadPage({
  onComplete,
  notify,
}: {
  onComplete: (resumeId: string, candidateId: string) => void;
  notify: (kind: ToastKind, message: string) => void;
}) {
  const [uploads, setUploads] = useState<UploadQueueItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const uploadLockRef = useRef(false);
  const dragDepthRef = useRef(0);

  const queuedUploads = uploads.filter((item) => item.status === "queued");
  const failedUploads = uploads.filter((item) => item.status === "error");
  const retryableFailedUploads = failedUploads.filter(
    (item) => item.retryable !== false,
  );
  const completedUploads = uploads.filter((item) => item.status === "success");
  const resolvedUploads = uploads.filter(
    (item) => item.status === "success" || item.status === "attention",
  );
  const attentionUploads = uploads.filter(
    (item) => item.status === "attention",
  );
  const extractingUploads = uploads.filter(
    (item) => item.status === "extracting",
  );

  const updateUpload = (uploadId: string, patch: Partial<UploadQueueItem>) => {
    setUploads((current) =>
      current.map((item) =>
        item.id === uploadId ? { ...item, ...patch } : item,
      ),
    );
  };

  useEffect(() => {
    const resumeIds = uploads
      .filter(
        (item) =>
          item.response &&
          aiExtractionIsInProgress(item.response.ai_extraction_status),
      )
      .map((item) => item.response!.resume_id);
    if (!resumeIds.length) return undefined;

    let cancelled = false;
    const refreshAiStatuses = async () => {
      const details = await Promise.all(
        resumeIds.map(async (resumeId) => {
          try {
            return await api.getResume(resumeId);
          } catch {
            // A transient polling failure must not turn a saved resume into an
            // upload failure. The worker will continue independently.
            return null;
          }
        }),
      );
      if (cancelled) return;
      const byResumeId = new Map(
        details
          .filter((detail): detail is ResumeDetail => detail !== null)
          .map((detail) => [detail.resume_id, detail]),
      );
      if (!byResumeId.size) return;
      setUploads((current) =>
        current.map((item) => {
          if (!item.response) return item;
          const detail = byResumeId.get(item.response.resume_id);
          if (!detail) return item;
          const response = withLatestAiExtractionStatus(item.response, detail);
          const status = uploadStatusFromResponse(response);
          if (
            item.status === status &&
            item.response.extraction_status === response.extraction_status &&
            item.response.ai_extraction_status ===
              response.ai_extraction_status &&
            item.response.ai_extraction_error === response.ai_extraction_error
          )
            return item;
          return { ...item, response, status, error: undefined };
        }),
      );
    };

    void refreshAiStatuses();
    const interval = window.setInterval(() => {
      void refreshAiStatuses();
    }, AI_STATUS_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [uploads]);

  const addFiles = (selectedFiles: FileList | File[]) => {
    if (uploading) return;
    const incoming = Array.from(selectedFiles);
    if (!incoming.length) return;

    const supportedFiles = incoming.filter(isSupportedResumeFile);
    const knownFiles = new Set(
      uploads.map((item) => fileFingerprint(item.file)),
    );
    const uniqueFiles = supportedFiles.filter((file) => {
      const fingerprint = fileFingerprint(file);
      if (knownFiles.has(fingerprint)) return false;
      knownFiles.add(fingerprint);
      return true;
    });
    const remainingSlots = Math.max(0, MAX_BATCH_FILES - uploads.length);
    const acceptedFiles = uniqueFiles.slice(0, remainingSlots);
    const invalidCount = incoming.length - supportedFiles.length;
    const duplicateCount = supportedFiles.length - uniqueFiles.length;
    const capacityCount = uniqueFiles.length - acceptedFiles.length;

    if (!acceptedFiles.length) {
      const reason = invalidCount
        ? "所选文件不在支持格式内。"
        : duplicateCount
          ? "这些简历已在当前队列中。"
          : `一次最多处理 ${MAX_BATCH_FILES} 份简历。`;
      notify("error", `没有加入新文件：${reason}`);
      return;
    }

    const timestamp = Date.now();
    setUploads((current) => [
      ...current,
      ...acceptedFiles.map((file, index) => ({
        id: `upload-${timestamp}-${index}-${fileFingerprint(file)}`,
        file,
        status: "queued" as const,
        idempotencyKey: createUploadIdempotencyKey(),
      })),
    ]);
    notify(
      "success",
      acceptedFiles.length === 1
        ? "已加入 1 份简历，等待上传。"
        : `已加入 ${acceptedFiles.length} 份简历，等待上传。`,
    );

    const exclusions: string[] = [];
    if (invalidCount) exclusions.push(`${invalidCount} 个不支持的文件`);
    if (duplicateCount) exclusions.push(`${duplicateCount} 份重复简历`);
    if (capacityCount) exclusions.push(`${capacityCount} 份超过本次上限`);
    if (exclusions.length)
      notify("error", `未加入：${exclusions.join("、")}。`);
  };

  const handleInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    if (event.currentTarget.files) addFiles(event.currentTarget.files);
    event.currentTarget.value = "";
  };

  const handleDragEnter = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (uploading) return;
    dragDepthRef.current += 1;
    setDragging(true);
  };

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (uploading) return;
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (!dragDepthRef.current) setDragging(false);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragDepthRef.current = 0;
    setDragging(false);
    if (!uploading) addFiles(event.dataTransfer.files);
  };

  const runUploads = async (targets: UploadQueueItem[]) => {
    if (!targets.length) {
      notify("error", "请先选择至少一份简历。");
      return;
    }
    if (uploadLockRef.current) return;

    uploadLockRef.current = true;
    setUploading(true);
    let nextIndex = 0;
    let succeeded = 0;
    let failed = 0;

    const worker = async () => {
      while (nextIndex < targets.length) {
        const item = targets[nextIndex++];
        updateUpload(item.id, {
          status: "uploading",
          error: undefined,
          retryable: undefined,
        });
        try {
          const response = await api.uploadResume(item.file, {
            idempotencyKey: item.idempotencyKey,
          });
          succeeded += 1;
          updateUpload(item.id, {
            status: uploadStatusFromResponse(response),
            response,
            error: undefined,
          });
        } catch (error) {
          failed += 1;
          updateUpload(item.id, {
            status: "error",
            error: humanizeError(error),
            retryable: isRetryableUploadError(error),
          });
        }
      }
    };

    try {
      await Promise.all(
        Array.from(
          { length: Math.min(BATCH_UPLOAD_CONCURRENCY, targets.length) },
          worker,
        ),
      );
    } finally {
      uploadLockRef.current = false;
      setUploading(false);
    }

    if (succeeded) {
      notify(
        "success",
        succeeded === 1
          ? "简历已保存，AI 正在提取候选人姓名和结构化事实。"
          : `${succeeded} 份简历已保存，AI 正在按队列提取候选人姓名和结构化事实。`,
      );
    }
    if (failed) {
      notify(
        "error",
        failed === 1
          ? "1 份简历上传失败。请查看原因后重试。"
          : `${failed} 份简历上传失败。其余文件未受影响。`,
      );
    }
  };

  const openSuccessfulUpload = (item: UploadQueueItem) => {
    if (!item.response) return;
    onComplete(item.response.resume_id, item.response.candidate_id);
  };

  const statusText = (item: UploadQueueItem): string => {
    if (item.status === "queued") return "等待上传";
    if (item.status === "uploading") return "正在保存原件并提取文字";
    if (item.status === "extracting") {
      return item.response?.ai_extraction_status === "running"
        ? "AI 正在提取候选人姓名、教育、经历和技能"
        : "原件已保存，AI 正在排队提取候选人姓名和结构化事实";
    }
    if (item.status === "attention") {
      if (
        item.response?.extraction_status === "failed" ||
        !item.response?.parsed_page_count
      ) {
        return "原件已保存，但未读取到可用文字，暂不能 AI 提取";
      }
      if (item.response?.ai_extraction_status === "unavailable") {
        return "原件和文字已保存，等待服务器配置 AI 服务";
      }
      return "原件和文字已保存，但 AI 提取需要处理；可查看原件并重新上传。";
    }
    if (item.status === "success") {
      return item.response?.quality_flags.length
        ? "AI 已提取并启用，存在解析提示"
        : "AI 已提取并已进入筛选库";
    }
    return item.error || "上传没有完成，请重试。";
  };

  return (
    <div className="page-frame">
      <header className="page-heading">
        <div>
          <h1>批量上传简历</h1>
          <p>
            上传后会逐份保存原件、提取原生文字，并由 AI
            自动识别候选人姓名、教育、经历和技能。姓名无法可靠识别时，将保留为“未命名候选人”。
          </p>
        </div>
      </header>
      <div className="page-layout">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>添加候选人简历</h2>
              <p>
                可拖入多份简历或一次选择多个文件。支持 PDF、Word、图片、Excel 和 HTML。候选人姓名仅由 AI
                从简历原文识别，文件名只用于区分上传文件。
              </p>
            </div>
          </div>
          <div className="form-grid">
            <div className="span-full">
              <div
                aria-busy={uploading}
                aria-describedby="upload-dropzone-help"
                aria-label="批量简历上传区域"
                className={`dropzone${dragging ? " is-dragging" : ""}${uploading ? " is-disabled" : ""}`}
                onDragEnter={handleDragEnter}
                onDragLeave={handleDragLeave}
                onDragOver={(event) => event.preventDefault()}
                onDrop={handleDrop}
              >
                <input
                  accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.xls,.xlsx,.html,.htm,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,image/png,image/jpeg,text/html"
                  disabled={uploading}
                  multiple
                  onChange={handleInputChange}
                  ref={inputRef}
                  tabIndex={-1}
                  type="file"
                />
                <div className="dropzone-inner">
                  <span className="dropzone-icon">
                    <Icon name="upload" size={25} />
                  </span>
                  <h2>
                    {uploading
                      ? `正在保存并入队：已完成 ${completedUploads.length} / ${uploads.length}`
                      : extractingUploads.length
                        ? `AI 正在处理 ${extractingUploads.length} 份简历`
                        : uploads.length
                          ? `已加入 ${uploads.length} 份简历`
                          : "拖入简历，或点击选择文件"}
                  </h2>
                  <p id="upload-dropzone-help">
                    支持 PDF、Word、图片、Excel 和 HTML。每份会单独校验、保存，并由 AI
                    从原文识别候选人姓名和结构化事实；姓名不清晰时不会使用文件名代替。
                  </p>
                  <button
                    className="button"
                    disabled={uploading}
                    onClick={() => inputRef.current?.click()}
                    type="button"
                  >
                    选择简历文件
                  </button>
                </div>
              </div>
              {uploads.length > 0 && (
                <div className="upload-queue">
                  <div className="upload-queue-header" aria-live="polite">
                    <div>
                      <strong>上传队列</strong>
                      <span>
                        {uploads.length} 份文件 · AI 处理中{" "}
                        {extractingUploads.length} · 已启用{" "}
                        {completedUploads.length} · 需处理{" "}
                        {attentionUploads.length} · 失败 {failedUploads.length}
                      </span>
                    </div>
                    {resolvedUploads.length > 0 && (
                      <button
                        className="text-button"
                        disabled={uploading}
                        onClick={() =>
                          setUploads((current) =>
                            current.filter(
                              (item) =>
                                item.status !== "success" &&
                                item.status !== "attention",
                            ),
                          )
                        }
                        type="button"
                      >
                        清除已完成
                      </button>
                    )}
                  </div>
                  <ul>
                    {uploads.map((item) => (
                      <li
                        className={`upload-file-card is-${item.status}`}
                        key={item.id}
                        role={item.status === "error" ? "alert" : undefined}
                      >
                        <Icon name="document" size={22} />
                        <div className="upload-file-main">
                          <strong title={item.file.name}>
                            {item.file.name}
                          </strong>
                          <span>
                            {formatFileSize(item.file.size)} · {resumeFileTypeLabel(item.file.name)} ·{" "}
                            {statusText(item)}
                          </span>
                        </div>
                        <div className="upload-row-actions">
                          {(item.status === "uploading" ||
                            item.status === "extracting") && (
                            <i
                              aria-label={
                                item.status === "uploading"
                                  ? "正在上传并解析"
                                  : "AI 正在提取"
                              }
                              className="spinner"
                            />
                          )}
                          {item.status === "error" &&
                            item.retryable !== false && (
                              <button
                                className="button button-ghost upload-row-button"
                                disabled={uploading}
                                onClick={() => void runUploads([item])}
                                type="button"
                              >
                                重新上传
                              </button>
                            )}
                          {item.response &&
                            item.status !== "queued" &&
                            item.status !== "uploading" && (
                              <button
                                className="button button-ghost upload-row-button"
                                onClick={() => openSuccessfulUpload(item)}
                                type="button"
                              >
                                {item.status === "extracting"
                                  ? "查看状态"
                                  : "查看简历"}
                              </button>
                            )}
                          {item.status !== "uploading" && (
                            <button
                              aria-label={`移除 ${item.file.name}`}
                              className="icon-button"
                              disabled={uploading}
                              onClick={() =>
                                setUploads((current) =>
                                  current.filter(
                                    (entry) => entry.id !== item.id,
                                  ),
                                )
                              }
                              type="button"
                            >
                              <Icon name="close" size={16} />
                            </button>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
          <div className="review-actions upload-actions">
            {(uploading || queuedUploads.length > 0) && (
              <button
                className="button button-primary"
                disabled={!queuedUploads.length || uploading}
                onClick={() => void runUploads(queuedUploads)}
                type="button"
              >
                {uploading ? (
                  <>
                    <i className="spinner" />
                    正在按队列上传…
                  </>
                ) : (
                  <>
                    <Icon name="upload" size={16} />
                    上传 {queuedUploads.length} 份并自动提取
                  </>
                )}
              </button>
            )}
            {retryableFailedUploads.length > 0 && (
              <button
                className="button"
                disabled={uploading}
                onClick={() => void runUploads(retryableFailedUploads)}
                type="button"
              >
                重新上传失败项（{retryableFailedUploads.length}）
              </button>
            )}
          </div>
        </section>
        <aside className="panel">
          <div className="panel-heading">
            <div>
              <h2>批量处理路径</h2>
              <p>每一份简历独立处理，便于定位问题与补传。</p>
            </div>
          </div>
          <ol className="workflow-list">
            <li>
              <span className="workflow-step">1</span>
              <div>
                <strong>逐份保存原始文件</strong>
              <span>支持 PDF、Word、图片、Excel 和 HTML，文件质量会单独检查。</span>
              </div>
            </li>
            <li>
              <span className="workflow-step">2</span>
              <div>
                <strong>AI 识别姓名与结构化事实</strong>
                <span>
                  基于可提取的原文识别候选人姓名、教育、经历和技能；姓名不明确时保留为未命名候选人。
                </span>
              </div>
            </li>
            <li>
              <span className="workflow-step">3</span>
              <div>
                <strong>通过证据校验后自动启用</strong>
                <span>
                  AI 提取结果会直接进入筛选库；异常简历保留原件与失败状态。
                </span>
              </div>
            </li>
          </ol>
        </aside>
      </div>
    </div>
  );
}



function CandidateRequired({
  title,
  description,
  actionLabel,
  onAction,
}: {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div className="page-frame">
      <section className="panel">
        <div className="empty-state">
          <div className="empty-state-inner">
            <span className="empty-glyph">
              <Icon name="user" size={23} />
            </span>
            <h2>{title}需要一份当前简历</h2>
            <p>{description}</p>
            {onAction && (
              <button
                className="button button-primary"
                onClick={onAction}
                type="button"
              >
                <Icon name="filter" size={16} />
                {actionLabel ?? "前往筛选工作台"}
              </button>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

function ToastRegion({
  toasts,
  onDismiss,
}: {
  toasts: ToastMessage[];
  onDismiss: (id: number) => void;
}) {
  return (
    <div aria-live="polite" className="toast-region">
      {toasts.map((toast) => (
        <div className={`toast is-${toast.kind}`} key={toast.id} role="status">
          <Icon name={toast.kind === "success" ? "check" : "close"} size={18} />
          <span>{toast.message}</span>
          <button
            aria-label="关闭提示"
            className="icon-button"
            onClick={() => onDismiss(toast.id)}
            type="button"
          >
            <Icon name="close" size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}

export default App;
