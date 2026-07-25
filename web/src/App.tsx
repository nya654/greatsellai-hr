import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
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
  CandidateSearchDisplayFieldKey,
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
  ResumeLibraryItem,
  ResumeReviewDetail,
  ResumeScore,
  ResumeSummary,
  RecruitingAgentCandidate,
  SavedFilter,
  ScoreTemplate,
} from "./types";
import { formatLibraryDate } from "./backoffice/utils/formatters";
import {
  hasSourceTextQualityIssue,
  hasSupersededReparseVersion,
} from "./backoffice/utils/resume-source-quality";
import {
  canPreviewInline,
  resumeFileExtension,
} from "./backoffice/utils/resume-file";
import { mailboxImportErrorMessages } from "./features/mailbox/mailbox-model";
import { ResumeLibraryPage } from "./features/library/ResumeLibraryPage";
import { CandidateDrawer } from "./features/candidate-drawer/CandidateDrawer";
import { FilterWorkspace } from "./features/filter/FilterWorkspace";
import { ScoreWorkspace } from "./features/scoring/ScoreWorkspace";
import { MatchWorkspace } from "./features/job-match/MatchWorkspace";
import { RecruitingAgentDrawer } from "./features/recruiting-agent/RecruitingAgentDrawer";
import { UploadPage } from "./features/upload/UploadPage";
import { WorkspaceSettingsPage } from "./features/workspace-settings/WorkspaceSettingsPage";
import {
  SideRail,
  Topbar,
  TrialStatusBanner,
} from "./features/workspace-shell/WorkspaceChrome";
import {
  CandidateRequired,
  ToastRegion,
} from "./features/workspace-shell/WorkspaceFeedback";
import { useWorkspaceAuth } from "./features/auth/useWorkspaceAuth";
import {
  EmailVerificationPage,
  ForgotPasswordPage,
  LoginPage,
  RegistrationPage,
  ResetPasswordPage,
} from "./features/auth/AuthPages";
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

const emptySearch: CandidateSearchResponse = {
  items: [],
  next_cursor: null,
  needs_review_count: 0,
  total_count: 0,
};

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

  const clearWorkspaceAfterLogout = useCallback(() => {
    setSelectedResume(null);
    setDrawerOpen(false);
  }, []);
  const {
    authError,
    authLoading,
    authSession,
    authState,
    completeEmailVerification,
    completePasswordReset,
    login,
    logout,
    refreshAuthSession,
    register,
    requestPasswordReset,
    resendEmailVerification,
  } = useWorkspaceAuth({
    authRoute,
    formatError: humanizeError,
    onLogoutCleanup: clearWorkspaceAfterLogout,
    rootWorkspaceBasePath: ROOT_WORKSPACE_BASE_PATH,
    workspaceHref,
  });

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
        workspaceHref={workspaceHref}
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
        workspaceHref={workspaceHref}
      />
    );
  }

  if (authState !== "authenticated") {
    if (authRoute === "register") {
      return (
        <RegistrationPage
          error={authError}
          loading={authLoading}
          onRegister={register}
          workspaceHref={workspaceHref}
        />
      );
    }
    if (authRoute === "forgot-password") {
      return (
        <ForgotPasswordPage
          error={authError}
          loading={authLoading}
          onRequest={requestPasswordReset}
          workspaceHref={workspaceHref}
        />
      );
    }
    return (
      <LoginPage
        error={authError}
        loading={authLoading}
        onLogin={login}
        workspaceHref={workspaceHref}
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
          platformAdminHref={platformHref()}
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
            <UploadPage
              formatError={humanizeError}
              notify={notify}
              onComplete={openUploadedResume}
            />
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
              formatError={humanizeError}
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
        formatError={humanizeError}
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


export default App;
