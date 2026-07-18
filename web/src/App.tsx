import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ChangeEvent,
  type DragEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  api,
  isApiError,
} from "./api";
import type {
  AiExtractionStatus,
  CandidateSearchItem,
  CandidateSearchRequest,
  CandidateSearchResponse,
  DegreeLevel,
  JobMatchBatch,
  JobMatch,
  JobRequirement,
  JobVersion,
  MailboxConfig,
  MailboxImportHistory,
  ResumeDetail,
  ResumeLibraryItem,
  ResumeLibraryResponse,
  ResumeReviewDetail,
  ResumeScore,
  ResumeSummary,
  ResumeUploadResponse,
  RecruitingAgentAction,
  RecruitingAgentCandidate,
  RecruitingAgentTurn,
  RecruitingAgentToolTrace,
  SavedFilter,
  ScoreDimensionInput,
  ScoreTemplate,
} from "./types";
import { Icon, type IconName } from "./icons";

type View = "library" | "filter" | "upload" | "inbox" | "score" | "match";
type DrawerTab = "original" | "summary";
type SchoolFilter = "any" | "yes" | "no";
type ToastKind = "success" | "error";

interface FilterDraft {
  school: SchoolFilter;
  minEmploymentMonths: number;
  degrees: DegreeLevel[];
  schoolName: string;
  major: string;
  company: string;
  title: string;
  skills: string[];
  keywords: string[];
}

interface SelectedResume {
  resumeId: string;
  candidateId: string;
  candidateName: string;
}

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

interface TemplateDraftDimension extends ScoreDimensionInput {
  id: string;
}

const emptySearch: CandidateSearchResponse = {
  items: [],
  next_cursor: null,
  needs_review_count: 0,
};

const defaultFilterDraft: FilterDraft = {
  school: "any",
  minEmploymentMonths: 0,
  degrees: [],
  schoolName: "",
  major: "",
  company: "",
  title: "",
  skills: [],
  keywords: [],
};

/**
 * Each PDF is parsed synchronously by the current API. Keeping a queue avoids
 * competing writes in the local SQLite setup, while still letting a recruiter
 * add a whole folder of resumes in one action.
 */
const BATCH_UPLOAD_CONCURRENCY = 1;
const MAX_BATCH_FILES = 100;
const AI_STATUS_POLL_INTERVAL_MS = 2_500;

function aiExtractionIsInProgress(
  status: AiExtractionStatus | undefined,
): boolean {
  return status === "queued" || status === "running";
}

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
  { value: "associate", label: "大专" },
  { value: "bachelor", label: "本科" },
  { value: "master", label: "硕士" },
  { value: "doctor", label: "博士" },
];

const degreeLabels: Record<DegreeLevel, string> = {
  unknown: "未知",
  associate: "大专",
  bachelor: "本科",
  master: "硕士",
  doctor: "博士",
};

const defaultTemplateDimensions: TemplateDraftDimension[] = [
  {
    id: "skill_fit",
    key: "skill_fit",
    label: "技能匹配",
    weight: 40,
    max_raw_score: 100,
    guidance: "重点看核心技术栈、工具与岗位场景的可验证匹配。",
  },
  {
    id: "experience_depth",
    key: "experience_depth",
    label: "经历深度",
    weight: 35,
    max_raw_score: 100,
    guidance: "重点看工作年限、职责范围、成果与复杂度。",
  },
  {
    id: "education_basis",
    key: "education_basis",
    label: "教育背景",
    weight: 25,
    max_raw_score: 100,
    guidance: "重点看学历、专业及必要的院校条件。",
  },
];

const navigation: Array<{ view: View; label: string; icon: IconName }> = [
  { view: "library", label: "简历库", icon: "folder" },
  { view: "filter", label: "筛选工作台", icon: "filter" },
  { view: "upload", label: "上传简历", icon: "upload" },
  { view: "inbox", label: "邮箱入库", icon: "inbox" },
  { view: "score", label: "评分规则", icon: "layers" },
  { view: "match", label: "岗位匹配", icon: "match" },
];

function freshDefaultFilter(): FilterDraft {
  return {
    ...defaultFilterDraft,
    degrees: [],
    skills: [],
    keywords: [],
  };
}

function humanizeError(error: unknown): string {
  if (isApiError(error)) {
    const messages: Record<string, string> = {
      invalid_login_credentials: "管理口令不正确，请重试。",
      invalid_admin_token: "管理口令无效。请在右上角连接配置中更新后重试。",
      server_missing_admin_token: "服务器尚未配置管理口令，暂时无法访问。",
      deepseek_api_key_not_configured:
        "AI 服务尚未配置。请先在服务器环境变量中配置后重试。",
      resume_has_no_native_text_for_ai_extraction:
        "这份简历没有足够的可提取文字，暂时不能由 AI 提取。",
      resume_source_text_unavailable:
        "这份简历没有可用的提取文字，暂时不能由 AI 提取。",
      completed_resume_cannot_be_reextracted:
        "这份简历已启用，不能被后台 AI 任务覆盖。",
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
      mailbox_password_required: "首次配置需要填写邮箱授权码。",
      mailbox_credentials_unavailable: "邮箱授权码无法读取，请重新保存后再同步。",
      mailbox_connection_failed: "无法连接邮箱，请检查 IMAP 地址、端口和授权码。",
      mailbox_select_failed: "无法打开指定的邮箱文件夹。",
      mailbox_search_failed: "无法检索邮箱中的附件。",
      mailbox_sync_failed: "邮箱入库暂时异常，请稍后重试。",
      score_template_not_found: "评分规则不存在，请重新选择。",
      job_version_not_found: "岗位版本不存在，请重新创建。",
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

const SUPPORTED_RESUME_EXTENSIONS = new Set([
  ".pdf",
  ".doc",
  ".docx",
  ".png",
  ".jpg",
  ".jpeg",
  ".xls",
  ".xlsx",
  ".html",
  ".htm",
]);

function resumeFileExtension(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot >= 0 ? filename.slice(dot).toLowerCase() : "";
}

function isSupportedResumeFile(file: File): boolean {
  return SUPPORTED_RESUME_EXTENSIONS.has(resumeFileExtension(file.name));
}

function resumeFileTypeLabel(filename: string): string {
  const extension = resumeFileExtension(filename);
  if (extension === ".pdf") return "PDF";
  if (extension === ".doc" || extension === ".docx") return "Word";
  if (extension === ".xls" || extension === ".xlsx") return "Excel";
  if (extension === ".png" || extension === ".jpg" || extension === ".jpeg") return "图片";
  if (extension === ".html" || extension === ".htm") return "HTML";
  return "文件";
}

function canPreviewInline(filename: string): boolean {
  const extension = resumeFileExtension(filename);
  return [".pdf", ".png", ".jpg", ".jpeg", ".html", ".htm"].includes(extension);
}

function fileFingerprint(file: File): string {
  return `${file.name.toLocaleLowerCase()}-${file.size}-${file.lastModified}`;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.ceil(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
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

function clampMonths(value: number): number {
  return Math.max(0, Math.min(240, Math.round(value / 12) * 12));
}

function formatMonths(months: number): string {
  if (months <= 0) return "未设门槛";
  const years = Math.floor(months / 12);
  const rest = months % 12;
  return rest ? `${years} 年 ${rest} 个月` : `${years} 年`;
}

function formatLibraryDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function draftToSearchRequest(
  draft: FilterDraft,
  cursor: string | null = null,
): CandidateSearchRequest {
  const request: CandidateSearchRequest = {
    limit: 50,
    cursor,
  };

  if (draft.school === "yes") request.is_985_211 = true;
  if (draft.school === "no") request.is_985_211 = false;
  if (draft.minEmploymentMonths > 0) {
    request.min_employment_months = draft.minEmploymentMonths;
  }
  if (draft.degrees.length || draft.schoolName.trim() || draft.major.trim()) {
    request.education_any_of = [
      {
        degree_in: draft.degrees,
        school_name_contains: draft.schoolName.trim()
          ? [draft.schoolName.trim()]
          : [],
        major_contains: draft.major.trim() ? [draft.major.trim()] : [],
      },
    ];
  }
  if (draft.company.trim() || draft.title.trim()) {
    request.experience_any_of = [
      {
        experience_types: ["employment", "internship"],
        organization_name_contains: draft.company.trim()
          ? [draft.company.trim()]
          : [],
        title_contains: draft.title.trim() ? [draft.title.trim()] : [],
      },
    ];
  }
  if (draft.skills.length) request.skills_all_of = draft.skills;
  if (draft.keywords.length) request.keywords_all_of = draft.keywords;
  return request;
}

function searchRequestToDraft(request: CandidateSearchRequest): FilterDraft {
  const education = request.education_any_of?.[0];
  const experience = request.experience_any_of?.[0];
  return {
    school:
      request.is_985_211 === true
        ? "yes"
        : request.is_985_211 === false
          ? "no"
          : "any",
    minEmploymentMonths: request.min_employment_months ?? 0,
    degrees: education?.degree_in ?? [],
    schoolName: education?.school_name_contains?.[0] ?? "",
    major: education?.major_contains?.[0] ?? "",
    company: experience?.organization_name_contains?.[0] ?? "",
    title: experience?.title_contains?.[0] ?? "",
    skills: request.skills_all_of ?? [],
    keywords: request.keywords_all_of ?? [],
  };
}

function App() {
  const [view, setView] = useState<View>("library");
  const [filterDraft, setFilterDraft] =
    useState<FilterDraft>(freshDefaultFilter);
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
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [summaries, setSummaries] = useState<ResumeSummary[]>([]);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [libraryRefreshToken, setLibraryRefreshToken] = useState(0);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [globalQuery, setGlobalQuery] = useState("");
  const [authState, setAuthState] = useState<
    "checking" | "authenticated" | "unauthenticated"
  >("checking");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loginLoading, setLoginLoading] = useState(false);
  const reviewRequestRef = useRef(0);
  const summaryRequestRef = useRef(0);

  const selectedResumeId = selectedResume?.resumeId ?? null;

  const notify = useCallback((kind: ToastKind, message: string) => {
    const id = Date.now() + Math.round(Math.random() * 1000);
    setToasts((current) => [...current, { id, kind, message }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 5200);
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
    ) => {
      setSearching(true);
      try {
        const response = await api.searchCandidates(
          draftToSearchRequest(draft, cursor),
        );
        setSearch((current) => ({
          ...response,
          items: append
            ? [...current.items, ...response.items]
            : response.items,
        }));
      } catch (error) {
        notify("error", humanizeError(error));
      } finally {
        setSearching(false);
      }
    },
    [notify],
  );

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

  useEffect(() => {
    void api
      .getAuthSession()
      .then((session) =>
        setAuthState(session.authenticated ? "authenticated" : "unauthenticated"),
      )
      .catch(() => setAuthState("unauthenticated"));
  }, []);

  useEffect(() => {
    if (authState !== "authenticated") return;
    void runSearch(defaultFilterDraft);
    void refreshSavedFilters();
  }, [authState, refreshSavedFilters, runSearch]);

  useEffect(() => {
    if (!drawerOpen || drawerTab !== "summary" || !selectedResumeId) return;
    void loadSummaries(selectedResumeId);
  }, [drawerOpen, drawerTab, loadSummaries, selectedResumeId]);

  useEffect(() => {
    setSummaries([]);
  }, [selectedResumeId]);

  useEffect(() => {
    if (!drawerOpen || drawerTab !== "original" || !selectedResumeId) {
      setPdfUrl(null);
      setPdfLoading(false);
      return;
    }
    let cancelled = false;
    let revoke: (() => void) | undefined;
    setPdfLoading(true);
    setPdfError(null);
    setPdfUrl(null);
    void api
      .getPdfObjectUrl(selectedResumeId)
      .then((resource) => {
        if (cancelled) {
          resource.revoke();
          return;
        }
        revoke = resource.revoke;
        setPdfUrl(resource.url);
      })
      .catch((error) => {
        if (!cancelled) setPdfError(humanizeError(error));
      })
      .finally(() => {
        if (!cancelled) setPdfLoading(false);
      });
    return () => {
      cancelled = true;
      revoke?.();
    };
  }, [drawerOpen, drawerTab, selectedResumeId]);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setDrawerOpen(false);
      setAgentOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, []);

  const openCandidate = useCallback(
    (item: CandidateSearchItem) => {
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
      setView("library");
      setLibraryRefreshToken((current) => current + 1);
      void refreshReview(resumeId);
    },
    [refreshReview],
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

  const scoreLibraryResume = useCallback((item: ResumeLibraryItem) => {
    summaryRequestRef.current += 1;
    setSelectedResume({
      resumeId: item.resume_id,
      candidateId: item.candidate_id,
      candidateName: item.display_name?.trim() || "未命名候选人",
    });
    setDrawerOpen(false);
    setView("score");
  }, []);

  const applyFilter = async () => {
    await runSearch(filterDraft);
  };

  const resetFilter = async () => {
    const clean = freshDefaultFilter();
    setFilterDraft(clean);
    await runSearch(clean);
  };

  const saveCurrentFilter = async (name: string) => {
    const normalized = name.trim();
    if (!normalized) {
      notify("error", "请为这组筛选条件填写一个名称。");
      return;
    }
    try {
      await api.createSavedFilter({
        name: normalized,
        filters: draftToSearchRequest(filterDraft),
      });
      await refreshSavedFilters();
      notify("success", `已保存“${normalized}”。`);
    } catch (error) {
      notify("error", humanizeError(error));
    }
  };

  const applySavedFilter = (filter: SavedFilter) => {
    const next = searchRequestToDraft(filter.filters);
    setFilterDraft(next);
    void runSearch(next);
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
        ...current.filter((item) => item.summary_id !== summary.summary_id),
      ]);
      setLibraryRefreshToken((current) => current + 1);
      notify("success", "AI 简历总结已生成。");
    } catch (error) {
      notify("error", humanizeError(error));
    } finally {
      setSummaryLoading(false);
    }
  };

  const handleGlobalSearch = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter") return;
    const terms = globalQuery
      .split(/[、,，\s]+/)
      .map((term) => term.trim())
      .filter(Boolean);
    const next = { ...filterDraft, keywords: terms };
    setFilterDraft(next);
    setView("filter");
    void runSearch(next);
  };

  const login = async (password: string) => {
    setLoginError(null);
    setLoginLoading(true);
    try {
      const session = await api.login(password);
      setAuthState(session.authenticated ? "authenticated" : "unauthenticated");
    } catch (error) {
      setLoginError(humanizeError(error));
    } finally {
      setLoginLoading(false);
    }
  };

  const logout = async () => {
    await api.logout();
    setSelectedResume(null);
    setDrawerOpen(false);
    setAuthState("unauthenticated");
  };

  if (authState !== "authenticated") {
    return (
      <LoginPage
        error={loginError}
        loading={loginLoading || authState === "checking"}
        onLogin={login}
      />
    );
  }

  return (
    <div className="app-shell">
      <SideRail activeView={view} inert={drawerOpen || agentOpen} onChangeView={setView} />
      <div className="app-area" inert={drawerOpen || agentOpen}>
        <Topbar
          globalQuery={globalQuery}
          onGlobalQueryChange={setGlobalQuery}
          onGlobalSearchKeyDown={handleGlobalSearch}
          onOpenAgent={() => {
            setDrawerOpen(false);
            setAgentOpen(true);
          }}
          onLogout={() => void logout()}
          onNewUpload={() => setView("upload")}
        />
        <main className="main-content" id="main-content">
          {view === "library" && (
            <ResumeLibraryPage
              refreshToken={libraryRefreshToken}
              selectedResumeId={selectedResumeId}
              onOpenResume={openLibraryResume}
              onScoreResume={scoreLibraryResume}
              onUpload={() => setView("upload")}
            />
          )}
          {view === "filter" && (
            <FilterWorkspace
              draft={filterDraft}
              onDraftChange={setFilterDraft}
              savedFilters={savedFilters}
              search={search}
              searching={searching}
              selectedResumeId={selectedResumeId}
              onApply={applyFilter}
              onReset={resetFilter}
              onSave={saveCurrentFilter}
              onApplySaved={applySavedFilter}
              onDeleteSaved={deleteSavedFilter}
              onOpenCandidate={openCandidate}
              onLoadMore={() =>
                void runSearch(filterDraft, true, search.next_cursor)
              }
              onUpload={() => setView("upload")}
            />
          )}
          <div hidden={view !== "upload"}>
            <UploadPage onComplete={openUploadedResume} notify={notify} />
          </div>
          {view === "inbox" && (
            <MailboxPage
              notify={notify}
              onImported={() => setLibraryRefreshToken((current) => current + 1)}
            />
          )}
          {view === "score" && (
            <ScorePage
              selected={selectedResume}
              notify={notify}
              onScoreCreated={() =>
                setLibraryRefreshToken((current) => current + 1)
              }
            />
          )}
          {view === "match" && (
            <MatchPage
              selected={selectedResume}
              notify={notify}
              onOpenMatchedResume={openMatchedResume}
            />
          )}
        </main>
      </div>

      <div
        aria-hidden="true"
        className={`drawer-scrim${drawerOpen || agentOpen ? " is-open" : ""}`}
        onClick={() => {
          setDrawerOpen(false);
          setAgentOpen(false);
        }}
      />
      <CandidateDrawer
        candidate={selectedResume}
        drawerTab={drawerTab}
        isOpen={drawerOpen}
        pdfError={pdfError}
        pdfLoading={pdfLoading}
        pdfUrl={pdfUrl}
        review={review}
        reviewLoading={reviewLoading}
        summaries={summaries}
        summaryLoading={summaryLoading}
        onClose={() => setDrawerOpen(false)}
        onGenerateSummary={() => void generateSummary()}
        onTabChange={setDrawerTab}
      />
      <RecruitingAgentDrawer
        isOpen={agentOpen}
        selectedResume={selectedResume}
        onClose={() => setAgentOpen(false)}
        onOpenMatchWorkspace={() => {
          setAgentOpen(false);
          setView("match");
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
  onLogin: (password: string) => Promise<void>;
}) {
  const [password, setPassword] = useState("");
  return (
    <main className="login-page">
      <form
        className="login-panel"
        onSubmit={(event) => {
          event.preventDefault();
          if (password.trim()) void onLogin(password);
        }}
      >
        <div className="login-mark" aria-hidden="true" />
        <p className="login-kicker">GREATSELL AI</p>
        <h1>简历筛选工作台</h1>
        <p className="login-description">
          此工作台包含候选人简历与评估结果，请使用管理口令登录。
        </p>
        <div className="field-stack">
          <label className="field-label" htmlFor="login-password">
            管理口令
          </label>
          <input
            autoComplete="current-password"
            className="field"
            id="login-password"
            onChange={(event) => setPassword(event.target.value)}
            placeholder="输入管理口令"
            type="password"
            value={password}
          />
        </div>
        {error && <p className="login-error" role="alert">{error}</p>}
        <button
          className="button button-primary login-submit"
          disabled={loading || !password.trim()}
          type="submit"
        >
          {loading ? <><i className="spinner" />正在验证</> : "登录工作台"}
        </button>
      </form>
    </main>
  );
}

function SideRail({
  activeView,
  onChangeView,
  inert,
}: {
  activeView: View;
  onChangeView: (view: View) => void;
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
            <span className="rail-tooltip">{item.label}</span>
          </button>
        ))}
      </nav>
      <div className="rail-bottom">
        <button aria-label="工作记录" className="rail-item" type="button">
          <Icon name="history" size={18} />
          <span className="rail-tooltip">工作记录</span>
        </button>
        <button aria-label="设置" className="rail-item" type="button">
          <Icon name="gear" size={18} />
          <span className="rail-tooltip">设置</span>
        </button>
      </div>
    </aside>
  );
}

function Topbar({
  globalQuery,
  onGlobalQueryChange,
  onGlobalSearchKeyDown,
  onOpenAgent,
  onLogout,
  onNewUpload,
}: {
  globalQuery: string;
  onGlobalQueryChange: (value: string) => void;
  onGlobalSearchKeyDown: (event: ReactKeyboardEvent<HTMLInputElement>) => void;
  onOpenAgent: () => void;
  onLogout: () => void;
  onNewUpload: () => void;
}) {
  return (
    <header className="topbar">
      <p className="topbar-title">
        AI 简历筛选 <span>/ 工作台</span>
      </p>
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
        <button
          className="button button-agent"
          onClick={onOpenAgent}
          type="button"
        >
          <Icon name="spark" size={16} />
          招聘助手
        </button>
        <button
          className="button button-ghost"
          onClick={onNewUpload}
          type="button"
        >
          <Icon name="upload" size={16} />
          上传简历
        </button>
        <button
          className="button button-ghost"
          onClick={onLogout}
          type="button"
        >
          退出登录
        </button>
      </div>
    </header>
  );
}

interface AgentChatMessage {
  id: number;
  role: "assistant" | "user";
  content: string;
  candidates?: RecruitingAgentCandidate[];
  actions?: RecruitingAgentAction[];
  toolTrace?: RecruitingAgentToolTrace[];
  failure?: boolean;
  retryMessage?: string;
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

function RecruitingAgentDrawer({
  isOpen,
  selectedResume,
  onClose,
  onOpenMatchWorkspace,
  onOpenResume,
}: {
  isOpen: boolean;
  selectedResume: SelectedResume | null;
  onClose: () => void;
  onOpenMatchWorkspace: () => void;
  onOpenResume: (candidate: RecruitingAgentCandidate) => void;
}) {
  const [input, setInput] = useState("");
  const [jobs, setJobs] = useState<JobVersion[]>([]);
  const [jobVersionId, setJobVersionId] = useState("");
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<AgentChatMessage[]>([
    {
      id: 1,
      role: "assistant",
      content:
        "我是招聘助手。可以按条件筛选简历、为已确认 JD 启动批量匹配，或解释当前候选人的匹配分数。",
    },
  ]);

  useEffect(() => {
    if (!isOpen) return;
    void api
      .listConfirmedJobVersions()
      .then((items) => {
        setJobs(items);
        setJobVersionId((current) =>
          current && items.some((item) => item.job_version_id === current)
            ? current
            : (items[0]?.job_version_id ?? ""),
        );
      })
      .catch(() => setJobs([]));
  }, [isOpen]);

  const addAssistantReply = (turn: RecruitingAgentTurn) => {
    setMessages((current) => [
      ...current,
      {
        id: Date.now() + 1,
        role: "assistant",
        content: turn.message,
        candidates: turn.candidates,
        actions: turn.actions,
        toolTrace: turn.tool_trace,
      },
    ]);
    if (turn.job_version_id) setJobVersionId(turn.job_version_id);
  };

  const send = async (raw: string) => {
    const message = raw.trim();
    if (!message || loading) return;
    setInput("");
    setMessages((current) => [
      ...current,
      { id: Date.now(), role: "user", content: message },
    ]);
    setLoading(true);
    try {
      const turn = await api.runRecruitingAgentTurn({
        message,
        job_version_id: jobVersionId || null,
        resume_id: selectedResume?.resumeId ?? null,
      });
      addAssistantReply(turn);
    } catch (error) {
      const failureMessage = humanizeAgentError(error);
      setMessages((current) => [
        ...current,
        {
          id: Date.now() + 1,
          role: "assistant",
          content: failureMessage,
          failure: true,
          retryMessage: isRetryableAgentError(error) ? message : undefined,
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
        <button aria-label="关闭招聘助手" className="icon-button" onClick={onClose} type="button">
          <Icon name="close" size={18} />
        </button>
      </header>
      <div className="agent-context">
        <div className="select-wrap">
          <label className="sr-only" htmlFor="agent-job-version">当前 JD</label>
          <select
            className="select-field"
            id="agent-job-version"
            onChange={(event) => setJobVersionId(event.target.value)}
            value={jobVersionId}
          >
            <option value="">自动选择最近确认的 JD</option>
            {jobs.map((item) => (
              <option key={item.job_version_id} value={item.job_version_id}>
                {item.title} · v{item.version}
              </option>
            ))}
          </select>
          <Icon name="chevron-down" size={15} />
        </div>
        <span className="agent-context-note">
          {selectedResume ? `当前候选人：${selectedResume.candidateName}` : "未选择候选人"}
        </span>
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
            {item.retryMessage && (
              <div className="agent-retry-row">
                <button
                  className="button button-ghost agent-retry-button"
                  disabled={loading}
                  onClick={() => void send(item.retryMessage!)}
                  type="button"
                >
                  <Icon name="refresh" size={15} />
                  重新发送
                </button>
              </div>
            )}
            {!!item.toolTrace?.length && (
              <div className="agent-tool-trace">
                {item.toolTrace.map((trace, index) => (
                  <span key={`${trace.tool}-${index}`}>已调用：{trace.summary}</span>
                ))}
              </div>
            )}
            {!!item.candidates?.length && (
              <div className="agent-candidate-list">
                {item.candidates.map((candidate) => (
                  <button
                    className="agent-candidate-row"
                    key={candidate.resume_id}
                    onClick={() => onOpenResume(candidate)}
                    type="button"
                  >
                    <span>
                      <strong>{candidate.display_name?.trim() || "未命名候选人"}</strong>
                      <small>{candidate.detail}</small>
                    </span>
                    {candidate.score !== null && <b>{candidate.score.toFixed(1)}</b>}
                    <Icon name="chevron-right" size={16} />
                  </button>
                ))}
              </div>
            )}
            {item.actions?.some((action) => action.action === "open_match_workspace") && (
              <button className="button button-ghost agent-workspace-button" onClick={onOpenMatchWorkspace} type="button">
                <Icon name="match" size={15} />
                打开 JD 匹配工作区
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
        <div className="agent-suggestions" aria-label="常用提问">
          {["找 985/211、3 年以上的候选人", "为当前 JD 批量匹配", "查看当前 JD 排行榜", "解释当前候选人的分数"].map((prompt) => (
            <button disabled={loading} key={prompt} onClick={() => void send(prompt)} type="button">
              {prompt}
            </button>
          ))}
        </div>
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
            placeholder="例如：找 985/211、3 年以上 Python 的候选人"
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

function FilterWorkspace({
  draft,
  onDraftChange,
  savedFilters,
  search,
  searching,
  selectedResumeId,
  onApply,
  onReset,
  onSave,
  onApplySaved,
  onDeleteSaved,
  onOpenCandidate,
  onLoadMore,
  onUpload,
}: {
  draft: FilterDraft;
  onDraftChange: (draft: FilterDraft) => void;
  savedFilters: SavedFilter[];
  search: CandidateSearchResponse;
  searching: boolean;
  selectedResumeId: string | null;
  onApply: () => void;
  onReset: () => void;
  onSave: (name: string) => Promise<void>;
  onApplySaved: (filter: SavedFilter) => void;
  onDeleteSaved: (filter: SavedFilter) => Promise<void>;
  onOpenCandidate: (item: CandidateSearchItem) => void;
  onLoadMore: () => void;
  onUpload: () => void;
}) {
  return (
    <div className="filter-workspace">
      <FilterPanel
        draft={draft}
        onApply={onApply}
        onApplySaved={onApplySaved}
        onDeleteSaved={onDeleteSaved}
        onDraftChange={onDraftChange}
        onReset={onReset}
        onSave={onSave}
        savedFilters={savedFilters}
      />
      <ResultsPane
        onLoadMore={onLoadMore}
        onOpenCandidate={onOpenCandidate}
        onUpload={onUpload}
        search={search}
        searching={searching}
        selectedResumeId={selectedResumeId}
      />
    </div>
  );
}

function FilterPanel({
  draft,
  onDraftChange,
  savedFilters,
  onApply,
  onReset,
  onSave,
  onApplySaved,
  onDeleteSaved,
}: {
  draft: FilterDraft;
  onDraftChange: (draft: FilterDraft) => void;
  savedFilters: SavedFilter[];
  onApply: () => void;
  onReset: () => void;
  onSave: (name: string) => Promise<void>;
  onApplySaved: (filter: SavedFilter) => void;
  onDeleteSaved: (filter: SavedFilter) => Promise<void>;
}) {
  const [selectedSavedId, setSelectedSavedId] = useState("");
  const [saveName, setSaveName] = useState("");
  const [saving, setSaving] = useState(false);

  const update = (patch: Partial<FilterDraft>) =>
    onDraftChange({ ...draft, ...patch });
  const applySaved = (id: string) => {
    setSelectedSavedId(id);
    const saved = savedFilters.find((item) => item.saved_filter_id === id);
    if (saved) onApplySaved(saved);
  };

  const save = async () => {
    setSaving(true);
    try {
      await onSave(saveName);
      setSaveName("");
    } finally {
      setSaving(false);
    }
  };

  return (
    <aside className="filter-panel" aria-label="筛选条件">
      <div className="filter-panel-header">
        <h2 className="filter-panel-title">筛选条件</h2>
        <button
          className="text-button"
          onClick={() => void onReset()}
          type="button"
        >
          清空
        </button>
      </div>
      <div className="filter-scroll">
        <section className="filter-section">
          <div className="filter-section-heading">
            <h3>已保存的筛选</h3>
            <span>{savedFilters.length} 组</span>
          </div>
          <div className="saved-filter-row">
            <div className="select-wrap" style={{ flex: 1 }}>
              <label className="sr-only" htmlFor="saved-filter">
                选择已保存的筛选
              </label>
              <select
                className="select-field"
                id="saved-filter"
                onChange={(event) => applySaved(event.target.value)}
                value={selectedSavedId}
              >
                <option value="">选择一组筛选</option>
                {savedFilters.map((item) => (
                  <option
                    key={item.saved_filter_id}
                    value={item.saved_filter_id}
                  >
                    {item.name}
                  </option>
                ))}
              </select>
              <Icon name="chevron-down" size={16} />
            </div>
            {selectedSavedId && (
              <button
                aria-label="删除当前保存的筛选"
                className="icon-button"
                onClick={() => {
                  const item = savedFilters.find(
                    (filter) => filter.saved_filter_id === selectedSavedId,
                  );
                  if (!item) return;
                  void onDeleteSaved(item).then(() => setSelectedSavedId(""));
                }}
                type="button"
              >
                <Icon name="close" size={16} />
              </button>
            )}
          </div>
          <div className="saved-filter-row">
            <label className="sr-only" htmlFor="save-filter-name">
              筛选名称
            </label>
            <input
              className="field"
              id="save-filter-name"
              maxLength={120}
              onChange={(event) => setSaveName(event.target.value)}
              placeholder="为当前条件命名"
              value={saveName}
            />
            <button
              className="button"
              disabled={saving}
              onClick={() => void save()}
              type="button"
            >
              保存
            </button>
          </div>
        </section>

        <section className="filter-section">
          <div className="filter-section-heading">
            <h3>学历与院校</h3>
            <span>精确筛选</span>
          </div>
          <div className="field-stack">
            <label className="field-label">985 / 211</label>
            <div
              className="choice-grid"
              role="radiogroup"
              aria-label="985 / 211 条件"
            >
              {(
                [
                  ["any", "不限"],
                  ["yes", "是"],
                  ["no", "否"],
                ] as Array<[SchoolFilter, string]>
              ).map(([value, label]) => (
                <label className="choice-row" key={value}>
                  <input
                    checked={draft.school === value}
                    name="school-filter"
                    onChange={() => update({ school: value })}
                    type="radio"
                  />
                  {label}
                </label>
              ))}
            </div>
          </div>
          <div className="choice-grid" aria-label="学历条件">
            {degreeOptions.map((option) => (
              <label className="choice-row" key={option.value}>
                <input
                  checked={draft.degrees.includes(option.value)}
                  onChange={() =>
                    update({
                      degrees: draft.degrees.includes(option.value)
                        ? draft.degrees.filter(
                            (degree) => degree !== option.value,
                          )
                        : [...draft.degrees, option.value],
                    })
                  }
                  type="checkbox"
                />
                {option.label}
              </label>
            ))}
          </div>
          <div className="field-stack">
            <label className="field-label" htmlFor="school-name">
              院校名称
            </label>
            <input
              className="field"
              id="school-name"
              onChange={(event) => update({ schoolName: event.target.value })}
              placeholder="例如：清华大学"
              value={draft.schoolName}
            />
          </div>
          <div className="field-stack">
            <label className="field-label" htmlFor="major-name">
              专业方向
            </label>
            <input
              className="field"
              id="major-name"
              onChange={(event) => update({ major: event.target.value })}
              placeholder="例如：计算机科学"
              value={draft.major}
            />
          </div>
        </section>

        <section className="filter-section">
          <div className="filter-section-heading">
            <h3>工作经历</h3>
            <span>{formatMonths(draft.minEmploymentMonths)}</span>
          </div>
          <div className="field-stack">
            <label className="field-label" htmlFor="min-experience">
              最低正式工作年限
            </label>
            <input
              className="range-input"
              id="min-experience"
              max="240"
              min="0"
              onChange={(event) =>
                update({
                  minEmploymentMonths: clampMonths(Number(event.target.value)),
                })
              }
              step="12"
              type="range"
              value={draft.minEmploymentMonths}
            />
            <div className="range-values">
              <span>不限</span>
              <span>20 年</span>
            </div>
          </div>
          <div className="field-stack">
            <label className="field-label" htmlFor="company-name">
              公司 / 组织
            </label>
            <input
              className="field"
              id="company-name"
              onChange={(event) => update({ company: event.target.value })}
              placeholder="例如：字节跳动"
              value={draft.company}
            />
          </div>
          <div className="field-stack">
            <label className="field-label" htmlFor="role-name">
              职位名称
            </label>
            <input
              className="field"
              id="role-name"
              onChange={(event) => update({ title: event.target.value })}
              placeholder="例如：后端工程师"
              value={draft.title}
            />
          </div>
        </section>

        <section className="filter-section">
          <div className="filter-section-heading">
            <h3>技能与原文</h3>
            <span>全部满足</span>
          </div>
          <ChipInput
            label="核心技能"
            onChange={(skills) => update({ skills })}
            placeholder="输入技能后按 Enter"
            values={draft.skills}
          />
          <ChipInput
            label="原文关键词"
            onChange={(keywords) => update({ keywords })}
            placeholder="输入关键词后按 Enter"
            values={draft.keywords}
          />
        </section>
      </div>
      <div className="filter-actions">
        <button
          className="button button-primary"
          onClick={() => void onApply()}
          type="button"
        >
          <Icon name="filter" size={16} />
          应用筛选条件
        </button>
        <button
          className="button button-ghost"
          onClick={() => void onReset()}
          type="button"
        >
          恢复默认条件
        </button>
      </div>
    </aside>
  );
}

function ChipInput({
  label,
  values,
  onChange,
  placeholder,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder: string;
}) {
  const [value, setValue] = useState("");
  const add = () => {
    const normalized = value.trim();
    if (
      !normalized ||
      values.some(
        (item) => item.toLocaleLowerCase() === normalized.toLocaleLowerCase(),
      )
    )
      return;
    onChange([...values, normalized]);
    setValue("");
  };
  return (
    <div className="field-stack">
      <label className="field-label">{label}</label>
      <div className="chip-input">
        {values.map((item) => (
          <span className="filter-chip" key={item}>
            {item}
            <button
              aria-label={`移除 ${item}`}
              onClick={() =>
                onChange(values.filter((valueItem) => valueItem !== item))
              }
              type="button"
            >
              <Icon name="close" size={12} />
            </button>
          </span>
        ))}
        <input
          onBlur={add}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (
              event.key === "Enter" ||
              event.key === "," ||
              event.key === "，"
            ) {
              event.preventDefault();
              add();
            }
          }}
          placeholder={values.length ? "继续添加" : placeholder}
          value={value}
        />
      </div>
    </div>
  );
}

function ResultsPane({
  search,
  searching,
  selectedResumeId,
  onOpenCandidate,
  onLoadMore,
  onUpload,
}: {
  search: CandidateSearchResponse;
  searching: boolean;
  selectedResumeId: string | null;
  onOpenCandidate: (item: CandidateSearchItem) => void;
  onLoadMore: () => void;
  onUpload: () => void;
}) {
  return (
    <section className="results-pane" aria-label="候选人结果">
      <header className="results-header">
        <div className="results-summary">
          <h1>候选人结果</h1>
          <p>
            {search.items.length
              ? `当前已加载 ${search.items.length} 位候选人`
              : "仅显示已完成 AI 提取并启用的简历"}
          </p>
        </div>
        <div className="results-toolbar">
          {search.needs_review_count > 0 && (
            <span className="status-pill">
              待处理 {search.needs_review_count}
            </span>
          )}
          <button className="button" onClick={onUpload} type="button">
            <Icon name="upload" size={16} />
            上传简历
          </button>
        </div>
      </header>
      <div className="table-scroll">
        {searching && !search.items.length ? (
          <TableSkeleton />
        ) : search.items.length ? (
          <table className="candidate-table">
            <thead>
              <tr>
                <th scope="col">候选人</th>
                <th scope="col">985 / 211</th>
                <th scope="col">最高学历</th>
                <th scope="col">正式工作年限</th>
                <th scope="col">命中证据</th>
                <th scope="col" aria-label="查看详情" />
              </tr>
            </thead>
            <tbody>
              {search.items.map((item) => (
                <tr
                  aria-label={`打开 ${item.display_name ?? "未命名候选人"} 的简历详情`}
                  className={
                    selectedResumeId === item.resume_id ? "is-selected" : ""
                  }
                  key={item.resume_id}
                  onClick={() => onOpenCandidate(item)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onOpenCandidate(item);
                    }
                  }}
                  tabIndex={0}
                >
                  <td>
                    <div className="candidate-person">
                      <span className="candidate-name">
                        {item.display_name?.trim() || "未命名候选人"}
                      </span>
                      <span className="candidate-meta">
                        Resume #{item.resume_id.slice(0, 8)}
                      </span>
                    </div>
                  </td>
                  <td>
                    {item.is_985_211 ? (
                      <span className="school-mark">
                        <Icon name="check" size={13} />是
                      </span>
                    ) : (
                      <span className="candidate-meta">否</span>
                    )}
                  </td>
                  <td>
                    <span className="degree-label">
                      {item.highest_degree
                        ? degreeLabels[item.highest_degree]
                        : "未知"}
                    </span>
                  </td>
                  <td>{formatMonths(item.employment_months)}</td>
                  <td>
                    <div className="match-tags">
                      {item.matched_evidence.length ? (
                        item.matched_evidence
                          .slice(0, 3)
                          .map((evidence, index) => (
                            <span
                              className="tag"
                              key={`${evidence.filter_key}-${index}`}
                              title={evidence.label}
                            >
                              {evidence.label}
                            </span>
                          ))
                      ) : (
                        <span className="candidate-meta">无附加条件</span>
                      )}
                    </div>
                  </td>
                  <td>
                    <Icon name="chevron-right" size={18} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty-state">
            <div className="empty-state-inner">
              <span className="empty-glyph">
                <Icon name="search" size={24} />
              </span>
              <h2>没有符合条件的已启用简历</h2>
              <p>
                调整筛选条件，或上传一份简历。AI
                提取完成后，它会自动进入筛选库。
              </p>
              <button
                className="button button-primary"
                onClick={onUpload}
                type="button"
              >
                <Icon name="upload" size={16} />
                上传简历
              </button>
            </div>
          </div>
        )}
      </div>
      <footer className="results-footer">
        <span>
          {searching ? (
            <span className="loading-line">
              <i className="spinner" />
              正在查询候选人…
            </span>
          ) : (
            `${search.items.length} 位候选人`
          )}
        </span>
        {search.next_cursor && (
          <button
            className="button button-ghost"
            disabled={searching}
            onClick={onLoadMore}
            type="button"
          >
            加载更多 <Icon name="arrow-right" size={16} />
          </button>
        )}
      </footer>
    </section>
  );
}

const RESUME_LIBRARY_PAGE_SIZE = 50;

function resumeLibraryStatus(item: ResumeLibraryItem): {
  label: string;
  tone: "ready" | "progress" | "attention" | "waiting";
} {
  if (item.is_active && item.extraction_status === "ready") {
    return { label: "已启用", tone: "ready" };
  }
  if (item.ai_extraction_status === "running") {
    return { label: "AI 提取中", tone: "progress" };
  }
  if (item.ai_extraction_status === "queued") {
    return { label: "等待 AI 提取", tone: "waiting" };
  }
  if (
    item.ai_extraction_status === "needs_attention" ||
    item.extraction_status === "failed"
  ) {
    return { label: "需要处理", tone: "attention" };
  }
  if (item.ai_extraction_status === "unavailable") {
    return { label: "等待 AI 服务", tone: "attention" };
  }
  return { label: "等待启用", tone: "waiting" };
}

function ResumeLibraryPage({
  selectedResumeId,
  refreshToken,
  onOpenResume,
  onScoreResume,
  onUpload,
}: {
  selectedResumeId: string | null;
  refreshToken: number;
  onOpenResume: (item: ResumeLibraryItem) => void;
  onScoreResume: (item: ResumeLibraryItem) => void;
  onUpload: () => void;
}) {
  const [library, setLibrary] = useState<ResumeLibraryResponse | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadLibrary = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setLibrary(await api.listResumeLibrary(page, RESUME_LIBRARY_PAGE_SIZE));
    } catch (loadError) {
      setError(humanizeError(loadError));
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    void loadLibrary();
  }, [loadLibrary, refreshToken]);

  useEffect(() => {
    if (
      !library?.items.some((item) =>
        aiExtractionIsInProgress(item.ai_extraction_status),
      )
    )
      return undefined;
    const interval = window.setInterval(() => {
      void loadLibrary();
    }, AI_STATUS_POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [library, loadLibrary]);

  const items = library?.items ?? [];
  const total = library?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / RESUME_LIBRARY_PAGE_SIZE));
  const canPageBack = page > 1;
  const canPageForward = page < totalPages;

  return (
    <div className="page-frame resume-library-page">
      <header className="page-heading">
        <div>
          <h1>简历库</h1>
          <p>
            每份已上传的 PDF 都会保留在这里；查看 AI 总结、AI 评分和原始简历。
          </p>
        </div>
        <div className="resume-library-actions">
          <button
            className="button"
            disabled={loading}
            onClick={() => void loadLibrary()}
            type="button"
          >
            {loading ? (
              <i className="spinner" />
            ) : (
              <Icon name="refresh" size={16} />
            )}
            刷新
          </button>
          <button
            className="button button-primary"
            onClick={onUpload}
            type="button"
          >
            <Icon name="upload" size={16} />
            上传简历
          </button>
        </div>
      </header>

      {error && (
        <p className="library-error" role="status">
          {error}
        </p>
      )}

      <section aria-label="简历库列表" className="library-table-frame">
        {loading && !library ? (
          <TableSkeleton />
        ) : items.length ? (
          <div className="table-scroll">
            <table className="candidate-table library-table">
              <thead>
                <tr>
                  <th scope="col">候选人 / 原始文件</th>
                  <th scope="col">AI 总结</th>
                  <th scope="col">AI 评分</th>
                  <th scope="col">状态</th>
                  <th scope="col">上传时间</th>
                  <th aria-label="查看简历" scope="col" />
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const status = resumeLibraryStatus(item);
                  return (
                    <tr
                      aria-label={`打开 ${item.display_name?.trim() || "未命名候选人"} 的 AI 总结和原始简历`}
                      className={
                        selectedResumeId === item.resume_id ? "is-selected" : ""
                      }
                      key={item.resume_id}
                      onClick={() => onOpenResume(item)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onOpenResume(item);
                        }
                      }}
                      tabIndex={0}
                    >
                      <td>
                        <div className="candidate-person">
                          <span className="candidate-name">
                            {item.display_name?.trim() || "未命名候选人"}
                          </span>
                          <span
                            className="candidate-meta"
                            title={item.original_filename}
                          >
                            {item.original_filename}
                          </span>
                        </div>
                      </td>
                      <td className="library-summary-cell">
                        {item.summary_preview ? (
                          <p
                            className="library-summary-preview"
                            title={item.summary_preview}
                          >
                            {item.summary_preview}
                          </p>
                        ) : (
                          <span className="library-empty-copy">
                            {item.is_active
                              ? "尚未生成，打开后可生成"
                              : "完成提取后可生成"}
                          </span>
                        )}
                      </td>
                      <td>
                        {item.score_total !== null ? (
                          <div
                            className="library-score"
                            title={item.score_template_name ?? undefined}
                          >
                            <strong>{item.score_total.toFixed(1)}</strong>
                            <span>/ 100</span>
                            {item.score_template_name && (
                              <small>{item.score_template_name}</small>
                            )}
                          </div>
                        ) : item.is_active ? (
                          <button
                            className="text-button library-score-action"
                            onClick={(event) => {
                              event.stopPropagation();
                              onScoreResume(item);
                            }}
                            type="button"
                          >
                            去评分 <Icon name="arrow-right" size={14} />
                          </button>
                        ) : (
                          <span className="library-empty-copy">
                            完成提取后可评分
                          </span>
                        )}
                      </td>
                      <td>
                        <span
                          className={`library-status is-${status.tone}`}
                          title={item.ai_extraction_error ?? undefined}
                        >
                          {status.label}
                        </span>
                      </td>
                      <td>
                        <span className="candidate-meta">
                          {formatLibraryDate(item.created_at)}
                        </span>
                      </td>
                      <td>
                        <Icon name="chevron-right" size={18} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state">
            <div className="empty-state-inner">
              <span className="empty-glyph">
                <Icon name="folder" size={24} />
              </span>
              <h2>简历库还是空的</h2>
              <p>
                上传简历后，它会立即出现在这里；AI 提取、总结和评分会逐步更新。
              </p>
              <button
                className="button button-primary"
                onClick={onUpload}
                type="button"
              >
                <Icon name="upload" size={16} />
                上传简历
              </button>
            </div>
          </div>
        )}
      </section>

      <footer className="library-table-footer">
        <span>
          {loading && library ? (
            <span className="loading-line">
              <i className="spinner" />
              正在更新简历库…
            </span>
          ) : (
            `共 ${total} 份简历`
          )}
        </span>
        {totalPages > 1 && (
          <div className="pagination">
            <button
              className="button button-ghost"
              disabled={!canPageBack || loading}
              onClick={() => setPage((current) => current - 1)}
              type="button"
            >
              上一页
            </button>
            <span>
              第 {page} / {totalPages} 页
            </span>
            <button
              className="button button-ghost"
              disabled={!canPageForward || loading}
              onClick={() => setPage((current) => current + 1)}
              type="button"
            >
              下一页
            </button>
          </div>
        )}
      </footer>
    </div>
  );
}

function TableSkeleton() {
  return (
    <div className="empty-state">
      <div className="empty-state-inner">
        <div
          className="skeleton"
          style={{ width: "3.75rem", height: "3.75rem", borderRadius: "50%" }}
        />
        <div className="skeleton" style={{ width: "13rem", height: "1rem" }} />
        <div
          className="skeleton"
          style={{ width: "18rem", height: "0.875rem" }}
        />
      </div>
    </div>
  );
}

function CandidateDrawer({
  candidate,
  review,
  reviewLoading,
  isOpen,
  drawerTab,
  onTabChange,
  onClose,
  pdfUrl,
  pdfLoading,
  pdfError,
  summaries,
  summaryLoading,
  onGenerateSummary,
}: {
  candidate: SelectedResume | null;
  review: ResumeReviewDetail | null;
  reviewLoading: boolean;
  isOpen: boolean;
  drawerTab: DrawerTab;
  onTabChange: (tab: DrawerTab) => void;
  onClose: () => void;
  pdfUrl: string | null;
  pdfLoading: boolean;
  pdfError: string | null;
  summaries: ResumeSummary[];
  summaryLoading: boolean;
  onGenerateSummary: () => void;
}) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const currentSummary =
    summaries.find((item) => item.is_current) ?? summaries[0] ?? null;
  useEffect(() => {
    if (!isOpen) return;
    const frame = window.requestAnimationFrame(() =>
      closeButtonRef.current?.focus(),
    );
    return () => window.cancelAnimationFrame(frame);
  }, [isOpen]);
  const downloadPdf = () => {
    if (!pdfUrl || !review) return;
    const link = document.createElement("a");
    link.href = pdfUrl;
    link.download = review.original_filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  };
  return (
    <aside
      aria-label={
        candidate ? `${candidate.candidateName} 的简历详情` : "简历详情"
      }
      aria-modal="true"
      className={`candidate-drawer${isOpen ? " is-open" : ""}`}
      inert={!isOpen}
      role="dialog"
    >
      <header className="drawer-header">
        <div className="drawer-title-wrap">
          <h2>
            {candidate?.candidateName ?? "候选人详情"}
            {review?.is_active && <span className="tiny-badge">已启用</span>}
          </h2>
          <p>{review ? review.original_filename : "正在读取简历详情…"}</p>
        </div>
        <div className="drawer-actions">
          {pdfUrl && drawerTab === "original" && (
            <button className="button" onClick={downloadPdf} type="button">
              <Icon name="download" size={16} />
              下载原始文件
            </button>
          )}
          <button
            aria-label="关闭简历详情"
            className="icon-button"
            onClick={onClose}
            ref={closeButtonRef}
            type="button"
          >
            <Icon name="close" size={19} />
          </button>
        </div>
      </header>
      <div className="drawer-body">
        <div aria-label="详情标签" className="tabs" role="tablist">
          {(
            [
              ["original", "原始文件"],
              ["summary", "AI 总结"],
            ] as Array<[DrawerTab, string]>
          ).map(([tab, label]) => (
            <button
              aria-selected={drawerTab === tab}
              className={`tab${drawerTab === tab ? " is-active" : ""}`}
              key={tab}
              onClick={() => onTabChange(tab)}
              role="tab"
              type="button"
            >
              {label}
            </button>
          ))}
        </div>
        <div className="drawer-content">
          {reviewLoading && !review ? (
            <TableSkeleton />
          ) : drawerTab === "original" ? (
            <OriginalDocumentTab
              error={pdfError}
              loading={pdfLoading}
              pdfUrl={pdfUrl}
              review={review}
            />
          ) : (
            <DrawerSummary
              currentSummary={currentSummary}
              loading={summaryLoading}
              onGenerate={onGenerateSummary}
            />
          )}
        </div>
      </div>
    </aside>
  );
}

function OriginalDocumentTab({
  review,
  pdfUrl,
  loading,
  error,
}: {
  review: ResumeReviewDetail | null;
  pdfUrl: string | null;
  loading: boolean;
  error: string | null;
}) {
  const pageCount = Math.min(review?.source_page_count ?? 1, 4);
  const filename = review?.original_filename ?? "";
  const canPreview = canPreviewInline(filename);
  const isImage = [".png", ".jpg", ".jpeg"].includes(
    resumeFileExtension(filename),
  );
  return (
    <div className="pdf-viewer">
      <div className="pdf-thumbnails" aria-label="原始文件页码">
        {Array.from({ length: pageCount }, (_, index) => (
          <div
            className={`pdf-thumb${index === 0 ? " is-current" : ""}`}
            key={index}
          >
            {index + 1}
          </div>
        ))}
      </div>
      <div className="pdf-canvas">
        {loading ? (
          <div className="pdf-loading">
            <span className="loading-line">
              <i className="spinner" />
              正在载入受保护的原始文件…
            </span>
          </div>
        ) : error ? (
          <div className="empty-state">
            <div className="empty-state-inner">
              <span className="empty-glyph">
                <Icon name="document" size={23} />
              </span>
              <h2>无法载入原始文件</h2>
              <p>{error}</p>
            </div>
          </div>
        ) : pdfUrl && canPreview ? (
          isImage ? (
            <img
              alt={filename ? `${filename} 原始图片` : "原始图片"}
              className="original-image-preview"
              src={pdfUrl}
            />
          ) : (
            <iframe
              sandbox={resumeFileExtension(filename) === ".html" || resumeFileExtension(filename) === ".htm" ? "" : undefined}
              src={pdfUrl}
              title={filename ? `${filename} 原始文件` : "原始文件"}
            />
          )
        ) : pdfUrl ? (
          <div className="empty-state">
            <div className="empty-state-inner">
              <span className="empty-glyph"><Icon name="document" size={23} /></span>
              <h2>{resumeFileTypeLabel(filename)} 原件可下载</h2>
              <p>浏览器不能安全预览此格式。请使用右上角“下载原始文件”查看。</p>
            </div>
          </div>
        ) : (
          <div className="pdf-loading">
            选择一份简历后会在这里显示原始文件。
          </div>
        )}
      </div>
    </div>
  );
}

function DrawerSummary({
  currentSummary,
  loading,
  onGenerate,
}: {
  currentSummary: ResumeSummary | null;
  loading: boolean;
  onGenerate: () => void;
}) {
  if (loading) return <TableSkeleton />;
  if (!currentSummary) {
    return (
      <div className="empty-state">
        <div className="empty-state-inner">
          <span className="empty-glyph">
            <Icon name="spark" size={23} />
          </span>
          <h2>还没有 AI 总结</h2>
          <p>生成后会保存在这份简历中，之后可随时回看。</p>
          <button
            className="button button-primary"
            onClick={onGenerate}
            type="button"
          >
            <Icon name="spark" size={16} />
            生成 AI 总结
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="detail-summary">
      <div className="panel-heading">
        <div>
          <h2>当前总结</h2>
          <p>
            {currentSummary.source === "manual" ? "人工版本" : "AI 版本"} ·
            生成于 {formatLibraryDate(currentSummary.created_at)}
          </p>
        </div>
        <button className="button" onClick={onGenerate} type="button">
          <Icon name="refresh" size={15} />
          重新生成
        </button>
      </div>
      <SummaryContent content={currentSummary.content} />
    </div>
  );
}

function SummaryContent({ content }: { content: Record<string, unknown> }) {
  const sectionLabels: Record<string, string> = {
    candidate_positioning: "候选人定位",
    education_background: "教育背景",
    work_and_internship: "工作与实习",
    core_skills: "核心技能",
    representative_projects: "代表项目",
    strengths: "优势亮点",
    verification_items: "建议核验",
  };
  const source =
    content.sections &&
    typeof content.sections === "object" &&
    !Array.isArray(content.sections)
      ? (content.sections as Record<string, unknown>)
      : content;
  const entries = Object.entries(source)
    .filter(([key]) => key !== "schema_version")
    .flatMap(([key, value]) => {
      const rendered =
        typeof value === "string"
          ? value.trim()
          : value &&
              typeof value === "object" &&
              !Array.isArray(value) &&
              typeof (value as Record<string, unknown>).content === "string"
            ? ((value as Record<string, unknown>).content as string).trim()
            : "";
      return rendered
        ? [
            {
              key,
              label: sectionLabels[key] ?? key.replace(/_/g, " "),
              rendered,
            },
          ]
        : [];
    });
  return (
    <article className="summary-card">
      {entries.length ? (
        <dl>
          {entries.flatMap((section) => [
            <dt key={`${section.key}-dt`}>{section.label}</dt>,
            <dd key={`${section.key}-dd`}>{section.rendered}</dd>,
          ])}
        </dl>
      ) : (
        <p className="candidate-meta">AI 没有返回可展示的总结内容。</p>
      )}
    </article>
  );
}

function MailboxPage({
  notify,
  onImported,
}: {
  notify: (kind: ToastKind, message: string) => void;
  onImported: () => void;
}) {
  const [config, setConfig] = useState<MailboxConfig | null>(null);
  const [history, setHistory] = useState<MailboxImportHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [imapHost, setImapHost] = useState("imap.feishu.cn");
  const [imapPort, setImapPort] = useState("993");
  const [emailAddress, setEmailAddress] = useState("");
  const [mailbox, setMailbox] = useState("INBOX");
  const [password, setPassword] = useState("");
  const [enabled, setEnabled] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextConfig, nextHistory] = await Promise.all([
        api.getMailboxConfig(),
        api.listMailboxImports(),
      ]);
      setConfig(nextConfig);
      setHistory(nextHistory);
      if (nextConfig.configured) {
        setImapHost(nextConfig.imap_host || "imap.feishu.cn");
        setImapPort(String(nextConfig.imap_port || 993));
        setEmailAddress(nextConfig.email_address || "");
        setMailbox(nextConfig.mailbox || "INBOX");
        setEnabled(nextConfig.enabled);
      }
    } catch (error) {
      notify("error", humanizeError(error));
    } finally {
      setLoading(false);
    }
  }, [notify]);

  useEffect(() => { void load(); }, [load]);

  const save = async () => {
    if (!imapHost.trim() || !emailAddress.trim()) {
      notify("error", "请填写 IMAP 地址和接收简历的邮箱。");
      return;
    }
    if (!config?.password_configured && !password) {
      notify("error", "首次配置需要填写邮箱授权码。");
      return;
    }
    setSaving(true);
    try {
      const saved = await api.saveMailboxConfig({
        imap_host: imapHost.trim(),
        imap_port: Number(imapPort) || 993,
        email_address: emailAddress.trim(),
        mailbox: mailbox.trim() || "INBOX",
        ...(password ? { password } : {}),
        enabled,
      });
      setConfig(saved);
      setPassword("");
      notify("success", "邮箱配置已保存。授权码不会在页面中回显。");
    } catch (error) {
      notify("error", humanizeError(error));
    } finally {
      setSaving(false);
    }
  };

  const sync = async () => {
    setSyncing(true);
    try {
      const result = await api.syncMailbox();
      notify(
        "success",
        `本次入库 ${result.imported_count} 份，重复跳过 ${result.duplicate_count} 份。`,
      );
      if (result.imported_count) onImported();
      await load();
    } catch (error) {
      notify("error", humanizeError(error));
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="page-frame mailbox-page">
      <header className="page-heading">
        <div>
          <h1>邮箱附件入库</h1>
          <p>从指定邮箱的附件中接收简历，沿用相同的文件保存、文字提取和 AI 入库流程。</p>
        </div>
        <button className="button button-primary" disabled={!config?.configured || syncing} onClick={() => void sync()} type="button">
          {syncing ? <><i className="spinner" />正在同步</> : <><Icon name="refresh" size={16} />立即同步</>}
        </button>
      </header>
      <div className="page-layout mailbox-layout">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>收件邮箱</h2>
              <p>保存后后台每 10 分钟同步一次，点击“立即同步”可手动拉取。</p>
            </div>
            {config?.configured && (
              <span className={`status-pill${enabled ? " is-success" : ""}`}>
                {enabled ? "已启用" : "已暂停"}
              </span>
            )}
          </div>
          {loading ? <TableSkeleton /> : (
            <div className="form-grid">
              <div className="field-stack">
                <label className="field-label" htmlFor="imap-host">IMAP 地址</label>
                <input className="field" id="imap-host" onChange={(event) => setImapHost(event.target.value)} value={imapHost} />
              </div>
              <div className="field-stack">
                <label className="field-label" htmlFor="imap-port">端口</label>
                <input className="field" id="imap-port" inputMode="numeric" onChange={(event) => setImapPort(event.target.value)} value={imapPort} />
              </div>
              <div className="field-stack span-full">
                <label className="field-label" htmlFor="imap-address">接收简历的邮箱</label>
                <input autoComplete="email" className="field" id="imap-address" onChange={(event) => setEmailAddress(event.target.value)} type="email" value={emailAddress} />
              </div>
              <div className="field-stack">
                <label className="field-label" htmlFor="imap-folder">邮箱文件夹</label>
                <input className="field" id="imap-folder" onChange={(event) => setMailbox(event.target.value)} value={mailbox} />
              </div>
              <div className="field-stack">
                <label className="field-label" htmlFor="imap-password">邮箱授权码</label>
                <input autoComplete="new-password" className="field" id="imap-password" onChange={(event) => setPassword(event.target.value)} placeholder={config?.password_configured ? "留空则保持原授权码" : "首次保存必填"} type="password" value={password} />
              </div>
              <label className="choice-row span-full">
                <input checked={enabled} onChange={(event) => setEnabled(event.target.checked)} type="checkbox" />
                启用后台定时同步
              </label>
            </div>
          )}
          <div className="review-actions">
            <button className="button button-primary" disabled={loading || saving} onClick={() => void save()} type="button">
              {saving ? <><i className="spinner" />正在保存</> : <><Icon name="check" size={16} />保存邮箱配置</>}
            </button>
          </div>
        </section>
        <aside className="panel mailbox-status-panel">
          <div className="panel-heading"><div><h2>同步状态</h2><p>重复邮件和重复附件不会再次入库。</p></div></div>
          <div className="fact-list">
            <div className="fact-row"><strong>最近同步</strong><span>{config?.last_synced_at ? formatLibraryDate(config.last_synced_at) : "尚未同步"}</span></div>
            <div className="fact-row"><strong>累计记录</strong><span>{history?.total ?? 0} 条</span></div>
            <div className="fact-row"><strong>支持格式</strong><span>PDF、Word、图片、Excel、HTML</span></div>
            {config?.last_sync_error && <div className="fact-row"><strong>最近异常</strong><span>{config.last_sync_error}</span></div>}
          </div>
        </aside>
      </div>
      <section className="panel mailbox-history">
        <div className="panel-heading"><div><h2>最近入库记录</h2><p>只记录附件处理结果，不在这里展示邮件正文。</p></div></div>
        {loading ? <TableSkeleton /> : history?.items.length ? (
          <div className="table-scroll"><table className="candidate-table"><thead><tr><th scope="col">附件</th><th scope="col">结果</th><th scope="col">时间</th></tr></thead><tbody>{history.items.map((item, index) => <tr key={`${item.attachment_filename}-${item.created_at}-${index}`}><td><strong>{item.attachment_filename}</strong></td><td><span className="status-pill">{item.status === "imported" ? "已入库" : item.status === "skipped" ? "已跳过" : "处理失败"}</span>{item.error && <small>{item.error}</small>}</td><td>{formatLibraryDate(item.created_at)}</td></tr>)}</tbody></table></div>
        ) : <div className="empty-state"><div className="empty-state-inner"><span className="empty-glyph"><Icon name="inbox" size={23} /></span><h2>还没有附件入库记录</h2><p>保存邮箱配置后，点击“立即同步”即可开始入库。</p></div></div>}
      </section>
    </div>
  );
}

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
                <span>只允许 PDF，页面数与文件质量会被单独检查。</span>
              </div>
            </li>
            <li>
              <span className="workflow-step">2</span>
              <div>
                <strong>AI 识别姓名与结构化事实</strong>
                <span>
                  基于 PDF
                  原生文字识别候选人姓名、教育、经历和技能；姓名不明确时保留为未命名候选人。
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

function ScorePage({
  selected,
  notify,
  onScoreCreated,
}: {
  selected: SelectedResume | null;
  notify: (kind: ToastKind, message: string) => void;
  onScoreCreated: () => void;
}) {
  const [templates, setTemplates] = useState<ScoreTemplate[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [templateName, setTemplateName] = useState("通用候选人评分");
  const [dimensions, setDimensions] = useState<TemplateDraftDimension[]>(() =>
    defaultTemplateDimensions.map((item) => ({ ...item })),
  );
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [scoring, setScoring] = useState(false);
  const [score, setScore] = useState<ResumeScore | null>(null);

  const loadTemplates = useCallback(async () => {
    setLoadingTemplates(true);
    try {
      const response = await api.listScoreTemplates();
      setTemplates(response);
      setTemplateId((current) => current || response[0]?.template_id || "");
    } catch (error) {
      notify("error", humanizeError(error));
    } finally {
      setLoadingTemplates(false);
    }
  }, [notify]);

  useEffect(() => {
    void loadTemplates();
  }, [loadTemplates]);

  const totalWeight = dimensions.reduce(
    (total, item) => total + Number(item.weight || 0),
    0,
  );
  const updateDimension = (
    id: string,
    patch: Partial<TemplateDraftDimension>,
  ) =>
    setDimensions((current) =>
      current.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    );
  const saveTemplate = async () => {
    if (!templateName.trim()) {
      notify("error", "请填写评分规则名称。");
      return;
    }
    if (totalWeight !== 100) {
      notify("error", `评分权重当前为 ${totalWeight}，必须恰好为 100。`);
      return;
    }
    if (
      dimensions.some(
        (item) =>
          !/^[a-z][a-z0-9_]{1,63}$/.test(item.key) || !item.label.trim(),
      )
    ) {
      notify("error", "每个维度都需要合法英文 key 和显示名称。");
      return;
    }
    setSavingTemplate(true);
    try {
      const created = await api.createScoreTemplate({
        name: templateName.trim(),
        dimensions: dimensions.map(({ id: _id, ...item }) => item),
      });
      setTemplates((current) => [created, ...current]);
      setTemplateId(created.template_id);
      notify("success", `评分规则“${created.name}”已创建。`);
    } catch (error) {
      notify("error", humanizeError(error));
    } finally {
      setSavingTemplate(false);
    }
  };
  const runScore = async () => {
    if (!selected) {
      notify("error", "请先在简历库打开一份简历。");
      return;
    }
    if (!templateId) {
      notify("error", "请先选择或创建一套评分规则。");
      return;
    }
    setScoring(true);
    try {
      const response = await api.createScore(selected.resumeId, {
        template_id: templateId,
      });
      setScore(response);
      onScoreCreated();
      notify("success", "AI 评分已完成。");
    } catch (error) {
      notify("error", humanizeError(error));
    } finally {
      setScoring(false);
    }
  };

  return (
    <div className="page-frame">
      <header className="page-heading">
        <div>
          <h1>评分规则</h1>
          <p>你设定维度和权重；AI 会基于这份简历给出可追溯的评分结果。</p>
        </div>
        {selected ? (
          <span className="status-pill">
            当前简历：{selected.candidateName}
          </span>
        ) : (
          <span className="status-pill">尚未选择简历</span>
        )}
      </header>
      <div className="page-layout">
        <div>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>新建评分规则</h2>
                <p>权重总和必须为 100；建议将最影响岗位成功的条件权重拉高。</p>
              </div>
              <button
                className="button"
                disabled={loadingTemplates}
                onClick={() => void loadTemplates()}
                type="button"
              >
                <Icon name="refresh" size={15} />
                刷新规则
              </button>
            </div>
            <div className="form-grid">
              <div className="field-stack span-full">
                <label className="field-label" htmlFor="template-name">
                  规则名称
                </label>
                <input
                  className="field"
                  id="template-name"
                  onChange={(event) => setTemplateName(event.target.value)}
                  value={templateName}
                />
              </div>
            </div>
            <div className="model-list">
              {dimensions.map((dimension) => (
                <div className="model-row" key={dimension.id}>
                  <div>
                    <label
                      className="sr-only"
                      htmlFor={`dimension-label-${dimension.id}`}
                    >
                      维度名称
                    </label>
                    <input
                      className="field"
                      id={`dimension-label-${dimension.id}`}
                      onChange={(event) =>
                        updateDimension(dimension.id, {
                          label: event.target.value,
                        })
                      }
                      value={dimension.label}
                    />
                    <label
                      className="sr-only"
                      htmlFor={`dimension-key-${dimension.id}`}
                    >
                      维度 key
                    </label>
                    <input
                      className="field"
                      id={`dimension-key-${dimension.id}`}
                      onChange={(event) =>
                        updateDimension(dimension.id, {
                          key: event.target.value
                            .replace(/\s+/g, "_")
                            .toLowerCase(),
                        })
                      }
                      placeholder="english_key"
                      value={dimension.key}
                    />
                  </div>
                  <div>
                    <label
                      className="sr-only"
                      htmlFor={`dimension-weight-${dimension.id}`}
                    >
                      权重
                    </label>
                    <input
                      className="field"
                      id={`dimension-weight-${dimension.id}`}
                      max="100"
                      min="0"
                      onChange={(event) =>
                        updateDimension(dimension.id, {
                          weight: Number(event.target.value),
                        })
                      }
                      type="number"
                      value={dimension.weight}
                    />
                  </div>
                  <button
                    aria-label={`删除 ${dimension.label}`}
                    className="icon-button"
                    disabled={dimensions.length <= 1}
                    onClick={() =>
                      setDimensions((current) =>
                        current.filter((item) => item.id !== dimension.id),
                      )
                    }
                    type="button"
                  >
                    <Icon name="close" size={16} />
                  </button>
                </div>
              ))}
            </div>
            <div className="review-actions">
              <button
                className="button button-ghost"
                onClick={() =>
                  setDimensions((current) => [
                    ...current,
                    {
                      id: `dimension-${Date.now()}`,
                      key: "new_dimension",
                      label: "新评分维度",
                      weight: 0,
                      max_raw_score: 100,
                      guidance: "",
                    },
                  ])
                }
                type="button"
              >
                <Icon name="plus" size={15} />
                添加维度
              </button>
              <button
                className="button button-primary"
                disabled={savingTemplate}
                onClick={() => void saveTemplate()}
                type="button"
              >
                {savingTemplate ? (
                  <>
                    <i className="spinner" />
                    正在创建…
                  </>
                ) : (
                  <>
                    <Icon name="layers" size={16} />
                    创建评分规则
                  </>
                )}
              </button>
            </div>
            <div className="weight-total">
              <span>当前权重总和</span>
              <strong>{totalWeight} / 100</strong>
            </div>
          </section>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>运行 AI 评分</h2>
                <p>每次运行都会保留结果；更新规则后可重新评分。</p>
              </div>
            </div>
            <div className="field-stack">
              <label className="field-label" htmlFor="score-template">
                选择评分规则
              </label>
              <div className="select-wrap">
                <select
                  className="select-field"
                  id="score-template"
                  onChange={(event) => setTemplateId(event.target.value)}
                  value={templateId}
                >
                  <option value="">选择评分规则</option>
                  {templates.map((template) => (
                    <option
                      key={template.template_id}
                      value={template.template_id}
                    >
                      {template.name} · v{template.version}
                    </option>
                  ))}
                </select>
                <Icon name="chevron-down" size={16} />
              </div>
            </div>
            <div className="review-actions">
              <button
                className="button button-primary"
                disabled={!selected || !templateId || scoring}
                onClick={() => void runScore()}
                type="button"
              >
                {scoring ? (
                  <>
                    <i className="spinner" />
                    AI 正在评分…
                  </>
                ) : (
                  <>
                    <Icon name="spark" size={16} />
                    对当前简历评分
                  </>
                )}
              </button>
            </div>
          </section>
          {score && <ScoreResult score={score} />}
        </div>
        <aside className="panel">
          <div className="panel-heading">
            <div>
              <h2>现有规则</h2>
              <p>创建后可以作为任意候选人的评分基准。</p>
            </div>
          </div>
          <div className="fact-list">
            {templates.length ? (
              templates.map((template) => (
                <button
                  className="fact-row"
                  key={template.template_id}
                  onClick={() => setTemplateId(template.template_id)}
                  type="button"
                >
                  <strong>
                    {template.name} · v{template.version}
                  </strong>
                  <span>
                    {template.dimensions
                      .map((item) => `${item.label} ${item.weight}%`)
                      .join(" · ")}
                  </span>
                </button>
              ))
            ) : (
              <p className="candidate-meta">还没有可用评分规则。</p>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

function ScoreResult({ score }: { score: ResumeScore }) {
  const scoreStyle = {
    "--score": Math.max(0, Math.min(100, score.total_score)),
  } as CSSProperties;
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>本次评分</h2>
          <p>
            规则版本 {score.template_version} · {score.status}
          </p>
        </div>
      </div>
      <div className="score-result">
        <div
          aria-label={`综合评分 ${score.total_score}`}
          className="score-number"
          data-value={score.total_score.toFixed(1)}
          style={scoreStyle}
        >
          <span>{score.total_score.toFixed(1)}</span>
        </div>
        <div className="score-dimension-list">
          {score.dimension_scores.map((dimension) => (
            <div className="score-dimension" key={dimension.key}>
              <span>{dimension.label}</span>
              <div className="score-bar">
                <i
                  style={{
                    width: `${Math.max(0, Math.min(100, dimension.final_raw_score))}%`,
                  }}
                />
              </div>
              <strong>{dimension.final_raw_score.toFixed(0)}</strong>
            </div>
          ))}
          <div className="evidence-item">
            <b>AI 分析</b>
            {typeof score.analysis.overall_summary === "string"
              ? score.analysis.overall_summary
              : "评分已生成。请结合各维度依据完成判断。"}
          </div>
        </div>
      </div>
    </section>
  );
}

function MatchPage({
  selected,
  notify,
  onOpenMatchedResume,
}: {
  selected: SelectedResume | null;
  notify: (kind: ToastKind, message: string) => void;
  onOpenMatchedResume: (match: JobMatch) => void;
}) {
  const [title, setTitle] = useState("高级后端开发工程师");
  const [jdText, setJdText] = useState("");
  const [jobVersion, setJobVersion] = useState<JobVersion | null>(null);
  const [confirmedJobVersions, setConfirmedJobVersions] = useState<JobVersion[]>([]);
  const [requirements, setRequirements] = useState<JobRequirement[]>([]);
  const [loading, setLoading] = useState(false);
  const [match, setMatch] = useState<JobMatch | null>(null);
  const [matchBatch, setMatchBatch] = useState<JobMatchBatch | null>(null);
  const [jobMatches, setJobMatches] = useState<JobMatch[]>([]);
  const [matchesLoading, setMatchesLoading] = useState(false);
  const selectJobVersion = (next: JobVersion) => {
    setJobVersion(next);
    setRequirements(next.requirements);
    setTitle(next.title);
    setJdText(next.raw_text);
    setMatch(null);
    setMatchBatch(null);
  };
  const createJob = async () => {
    if (!title.trim() || !jdText.trim()) {
      notify("error", "请填写岗位名称和完整 JD 后再创建岗位。");
      return;
    }
    setLoading(true);
    try {
      const created = await api.createJob({
        title: title.trim(),
        jd_text: jdText.trim(),
      });
      const extracted = await api.extractJobRequirements(created.job_version_id);
      const confirmed = await api.confirmJobVersion(extracted.job_version_id);
      selectJobVersion(confirmed);
      setConfirmedJobVersions((current) => [
        confirmed,
        ...current.filter((item) => item.job_version_id !== confirmed.job_version_id),
      ]);
      notify(
        "success",
        "岗位草稿已创建。下一步可让 AI 提取要求，随后人工确认。",
      );
    } catch (error) {
      notify("error", humanizeError(error));
    } finally {
      setLoading(false);
    }
  };
  const extractRequirements = async () => {
    if (!jobVersion) return;
    setLoading(true);
    try {
      const response = await api.extractJobRequirements(
        jobVersion.job_version_id,
      );
      setJobVersion(response);
      setRequirements(response.requirements);
      notify("success", "AI 已从 JD 中提取要求。请检查后保存或确认。");
    } catch (error) {
      notify("error", humanizeError(error));
    } finally {
      setLoading(false);
    }
  };
  const saveRequirements = async () => {
    if (!jobVersion) return;
    setLoading(true);
    try {
      const response = await api.updateJobRequirements(
        jobVersion.job_version_id,
        {
          title: title.trim(),
          requirements: requirements.map((item) => ({
            requirement_key: item.requirement_key,
            priority: item.priority,
            category: item.category,
            raw_requirement: item.raw_requirement,
            terms: item.terms,
            minimum_months: item.minimum_months,
            clause_ids: item.clause_ids,
          })),
        },
      );
      setJobVersion(response);
      setRequirements(response.requirements);
      notify("success", "岗位要求已保存为可确认草稿。");
    } catch (error) {
      notify("error", humanizeError(error));
    } finally {
      setLoading(false);
    }
  };
  const confirmJob = async () => {
    if (!jobVersion) return;
    setLoading(true);
    try {
      const response = await api.confirmJobVersion(jobVersion.job_version_id);
      setJobVersion(response);
      setRequirements(response.requirements);
      notify("success", "岗位要求已确认，可以开始匹配。");
    } catch (error) {
      notify("error", humanizeError(error));
    } finally {
      setLoading(false);
    }
  };
  const runMatch = async () => {
    if (!selected) {
      notify("error", "请先在筛选工作台打开一份已启用简历。");
      return;
    }
    if (!jobVersion || jobVersion.status !== "confirmed") {
      notify("error", "请先确认岗位要求，再运行匹配。");
      return;
    }
    setLoading(true);
    try {
      const response = await api.runJobMatch(selected.resumeId, {
        job_version_id: jobVersion.job_version_id,
      });
      setMatch(response);
      setJobMatches((current) => [
        response,
        ...current.filter((item) => item.resume_id !== response.resume_id),
      ]);
      notify("success", "岗位匹配已完成，结果已绑定岗位与简历的事实版本。");
    } catch (error) {
      notify("error", humanizeError(error));
    } finally {
      setLoading(false);
    }
  };
  const runAllMatches = async () => {
    if (!jobVersion || jobVersion.status !== "confirmed") {
      notify("error", "请先确认岗位要求，再批量匹配简历。");
      return;
    }
    setLoading(true);
    try {
      const response = await api.enqueueAllJobMatches(
        jobVersion.job_version_id,
      );
      setMatchBatch(response);
      notify(
        "success",
        `已将 ${response.total_count} 份简历加入岗位匹配队列。`,
      );
    } catch (error) {
      notify("error", humanizeError(error));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    if (!matchBatch || ["completed", "partial"].includes(matchBatch.status))
      return;
    let cancelled = false;
    const refresh = async () => {
      try {
        const next = await api.getJobMatchBatch(matchBatch.batch_id);
        if (!cancelled) setMatchBatch(next);
      } catch {
        // Keep the last durable status visible; the next manual action can retry.
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [matchBatch?.batch_id, matchBatch?.status]);
  useEffect(() => {
    let cancelled = false;
    void api
      .listConfirmedJobVersions()
      .then((versions) => {
        if (cancelled) return;
        setConfirmedJobVersions(versions);
        if (versions[0]) selectJobVersion(versions[0]);
      })
      .catch(() => {
        // A new workspace has no confirmed JD yet. The creation form remains usable.
      });
    return () => {
      cancelled = true;
    };
  }, []);
  useEffect(() => {
    if (!jobVersion || jobVersion.status !== "confirmed") {
      setJobMatches([]);
      return;
    }
    let cancelled = false;
    setMatchesLoading(true);
    void api
      .listJobVersionMatches(jobVersion.job_version_id)
      .then((items) => {
        if (!cancelled) setJobMatches(items);
      })
      .catch((error) => {
        if (!cancelled) notify("error", humanizeError(error));
      })
      .finally(() => {
        if (!cancelled) setMatchesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [jobVersion?.job_version_id, jobVersion?.status, matchBatch?.completed_count, notify]);
  const updateRequirement = (index: number, patch: Partial<JobRequirement>) =>
    setRequirements((current) =>
      current.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...patch } : item,
      ),
    );
  const firstClauseId = jobVersion?.clauses[0]?.clause_id ?? "";
  return (
    <div className="page-frame">
      <header className="page-heading">
        <div>
          <h1>岗位 JD 匹配</h1>
          <p>
            把 JD 转成可确认要求后，再让 AI
            对已核验的简历事实逐项比对。不会用未验证原文直接下结论。
          </p>
        </div>
        {selected ? (
          <span className="status-pill">候选人：{selected.candidateName}</span>
        ) : (
          <span className="status-pill">尚未选择候选人</span>
        )}
      </header>
      <div className="page-layout">
        <div>
          <section className="panel">
            {confirmedJobVersions.length > 0 && (
              <div className="jd-switcher">
                <div>
                  <span className="field-label">已保存的岗位 JD</span>
                  <p>切换后将显示该岗位自己的候选人匹配结果。</p>
                </div>
                <div className="select-wrap jd-switcher-select">
                  <select
                    aria-label="切换已保存的岗位 JD"
                    className="select-field"
                    onChange={(event) => {
                      const next = confirmedJobVersions.find(
                        (item) => item.job_version_id === event.target.value,
                      );
                      if (next) selectJobVersion(next);
                    }}
                    value={jobVersion?.job_version_id ?? ""}
                  >
                    {confirmedJobVersions.map((item) => (
                      <option key={item.job_version_id} value={item.job_version_id}>
                        {item.title} · v{item.version}
                      </option>
                    ))}
                  </select>
                  <Icon name="chevron-down" size={15} />
                </div>
              </div>
            )}
            <div className="jd-steps">
              <span
                className={`jd-step${!jobVersion ? " is-current" : " is-done"}`}
              >
                1 创建 JD
              </span>
              <span
                className={`jd-step${jobVersion && jobVersion.status === "draft" ? " is-current" : jobVersion?.status === "confirmed" ? " is-done" : ""}`}
              >
                2 核验要求
              </span>
              <span
                className={`jd-step${jobVersion?.status === "confirmed" ? " is-current" : ""}`}
              >
                3 匹配候选人
              </span>
            </div>
            <div className="form-grid">
              <div className="field-stack span-full">
                <label className="field-label" htmlFor="job-title">
                  岗位名称
                </label>
                <input
                  className="field"
                  id="job-title"
                  onChange={(event) => setTitle(event.target.value)}
                  value={title}
                />
              </div>
              <div className="field-stack span-full">
                <label className="field-label" htmlFor="job-text">
                  岗位 JD
                </label>
                <textarea
                  className="textarea-field"
                  id="job-text"
                  onChange={(event) => setJdText(event.target.value)}
                  placeholder="粘贴完整岗位描述、职责与任职要求"
                  value={jdText}
                />
              </div>
            </div>
            <div className="review-actions">
              <button
                className="button button-primary"
                disabled={loading}
                onClick={() => void createJob()}
                type="button"
              >
                {loading && !jobVersion ? (
                  <>
                    <i className="spinner" />
                    正在创建…
                  </>
                ) : (
                  <>
                    <Icon name="briefcase" size={16} />
                    创建岗位草稿
                  </>
                )}
              </button>
            </div>
          </section>
          {jobVersion && (
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <h2>可核验的岗位要求</h2>
                  <p>
                    {jobVersion.status === "confirmed"
                      ? "已确认，可运行匹配。"
                      : "草稿状态：允许修改；确认后会冻结此版本。"}
                  </p>
                </div>
                {jobVersion.status === "draft" && (
                  <button
                    className="button"
                    disabled={loading}
                    onClick={() => void extractRequirements()}
                    type="button"
                  >
                    <Icon name="spark" size={16} />
                    AI 提取要求
                  </button>
                )}
              </div>
              <div className="requirements-list">
                {requirements.map((item, index) => (
                  <RequirementEditor
                    item={item}
                    key={item.requirement_key}
                    onDelete={() =>
                      setRequirements((current) =>
                        current.filter((_, itemIndex) => itemIndex !== index),
                      )
                    }
                    onUpdate={(patch) => updateRequirement(index, patch)}
                    readOnly={jobVersion.status !== "draft"}
                  />
                ))}
                {!requirements.length && (
                  <p className="candidate-meta">
                    尚未提取要求。可以先使用 AI 提取，再逐条人工检查。
                  </p>
                )}
              </div>
              {jobVersion.status === "draft" && (
                <div className="review-actions">
                  <button
                    className="button button-ghost"
                    onClick={() =>
                      setRequirements((current) => [
                        ...current,
                        {
                          requirement_id: `local-${Date.now()}`,
                          requirement_key: `requirement_${current.length + 1}`,
                          priority: "must_have",
                          category: "other",
                          raw_requirement: "",
                          terms: [],
                          minimum_months: null,
                          weight: 0,
                          clause_ids: firstClauseId ? [firstClauseId] : [],
                          sort_order: current.length,
                        },
                      ])
                    }
                    type="button"
                  >
                    <Icon name="plus" size={15} />
                    添加要求
                  </button>
                  <button
                    className="button"
                    disabled={loading}
                    onClick={() => void saveRequirements()}
                    type="button"
                  >
                    保存要求草稿
                  </button>
                  <button
                    className="button button-primary"
                    disabled={loading || !requirements.length}
                    onClick={() => void confirmJob()}
                    type="button"
                  >
                    <Icon name="check" size={16} />
                    确认岗位要求
                  </button>
                </div>
              )}
            </section>
          )}
          {match && <MatchResult match={match} />}
          {jobVersion?.status === "confirmed" && (
            <MatchLeaderboard
              loading={matchesLoading}
              matches={jobMatches}
              onOpenResume={onOpenMatchedResume}
            />
          )}
        </div>
        <aside className="panel">
          <div className="panel-heading">
            <div>
              <h2>匹配操作</h2>
              <p>仅可对确认后的岗位版本运行。</p>
            </div>
          </div>
          <div className="fact-list">
            <div className="fact-row">
              <strong>岗位版本</strong>
              <span>
                {jobVersion
                  ? `v${jobVersion.version} · ${jobVersion.status}`
                  : "尚未创建"}
              </span>
            </div>
            <div className="fact-row">
              <strong>当前候选人</strong>
              <span>{selected?.candidateName ?? "请先从筛选结果打开"}</span>
            </div>
          </div>
          {matchBatch && (
            <div className="fact-row">
              <strong>AI 批量进度</strong>
              <span>
                {matchBatch.completed_count + matchBatch.failed_count} / {matchBatch.total_count}
                {matchBatch.failed_count ? ` · 失败 ${matchBatch.failed_count}` : ""}
              </span>
            </div>
          )}
          <div className="review-actions">
            <button
              className="button"
              disabled={jobVersion?.status !== "confirmed" || loading}
              onClick={() => void runAllMatches()}
              type="button"
            >
              <Icon name="spark" size={16} />
              批量匹配全部简历
            </button>
            <button
              className="button button-primary"
              disabled={
                !selected || jobVersion?.status !== "confirmed" || loading
              }
              onClick={() => void runMatch()}
              type="button"
            >
              {loading && jobVersion?.status === "confirmed" ? (
                <>
                  <i className="spinner" />
                  正在匹配…
                </>
              ) : (
                <>
                  <Icon name="match" size={16} />
                  运行岗位匹配
                </>
              )}
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
}

function RequirementEditor({
  item,
  onUpdate,
  onDelete,
  readOnly,
}: {
  item: JobRequirement;
  onUpdate: (patch: Partial<JobRequirement>) => void;
  onDelete: () => void;
  readOnly: boolean;
}) {
  return (
    <div className="requirement-row">
      <div className="select-wrap">
        <select
          className="select-field"
          disabled={readOnly}
          onChange={(event) =>
            onUpdate({
              priority: event.target.value as JobRequirement["priority"],
            })
          }
          value={item.priority}
        >
          <option value="must_have">必须满足</option>
          <option value="preferred">优先满足</option>
        </select>
        <Icon name="chevron-down" size={15} />
      </div>
      <input
        aria-label="岗位要求内容"
        className="field"
        disabled={readOnly}
        onChange={(event) => onUpdate({ raw_requirement: event.target.value })}
        placeholder="填写岗位要求"
        value={item.raw_requirement}
      />
      {readOnly ? (
        <span
          className={
            item.priority === "must_have"
              ? "priority-must"
              : "priority-preferred"
          }
        >
          {item.priority === "must_have" ? "必须" : "优先"}
        </span>
      ) : (
        <button
          aria-label="删除岗位要求"
          className="icon-button"
          onClick={onDelete}
          type="button"
        >
          <Icon name="close" size={15} />
        </button>
      )}
    </div>
  );
}

function MatchResult({ match }: { match: JobMatch }) {
  const scoreStyle = {
    "--score": Math.max(0, Math.min(100, match.total_score)),
  } as CSSProperties;
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>匹配结果</h2>
          <p>
            岗位版本 {match.job_version} · 简历事实版本 {match.facts_version} ·{" "}
            {match.hard_requirement_status ?? "待检查硬性要求"}
          </p>
        </div>
      </div>
      <div className="score-result">
        <div
          aria-label={`岗位匹配度 ${match.total_score}`}
          className="score-number"
          data-value={match.total_score.toFixed(1)}
          style={scoreStyle}
        >
          <span>{match.total_score.toFixed(1)}</span>
        </div>
        <div className="requirements-list">
          {match.requirement_results.map((item) => (
            <div className="requirement-row" key={item.requirement_id}>
              <span className={`outcome-${item.outcome.replace("_", "-")}`}>
                {item.outcome === "met"
                  ? "已满足"
                  : item.outcome === "partial"
                    ? "部分满足"
                    : item.outcome === "not_met"
                      ? "未满足"
                      : "待确认"}
              </span>
              <p>
                <b>{item.requirement_text}</b>
                <br />
                {item.reason}
                {item.missing_or_uncertain
                  ? ` · ${item.missing_or_uncertain}`
                  : ""}
              </p>
              <span
                className={
                  item.priority === "must_have"
                    ? "priority-must"
                    : "priority-preferred"
                }
              >
                {item.priority === "must_have" ? "必须" : "优先"}
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function MatchLeaderboard({
  matches,
  loading,
  onOpenResume,
}: {
  matches: JobMatch[];
  loading: boolean;
  onOpenResume: (match: JobMatch) => void;
}) {
  const latestByResume = new Map<string, JobMatch>();
  for (const match of matches) {
    if (!latestByResume.has(match.resume_id)) latestByResume.set(match.resume_id, match);
  }
  const ranked = [...latestByResume.values()].sort((left, right) => right.total_score - left.total_score);
  const hardLabel: Record<string, string> = {
    pass: "硬条件通过",
    unmet: "硬条件未满足",
    information_insufficient: "硬条件信息不足",
    not_applicable: "无硬条件",
  };
  return (
    <section className="panel match-leaderboard">
      <div className="panel-heading">
        <div>
          <h2>候选人匹配排序</h2>
          <p>按当前 JD 的 AI 匹配度排序，每一项判断都可追溯到简历事实。</p>
        </div>
        <span className="status-pill">{ranked.length} 份已完成</span>
      </div>
      {loading ? (
        <TableSkeleton />
      ) : ranked.length ? (
        <div className="table-scroll">
          <table className="candidate-table match-table">
            <thead>
              <tr>
                <th scope="col">排名</th>
                <th scope="col">候选人</th>
                <th scope="col">匹配度</th>
                <th scope="col">硬条件</th>
                <th scope="col">匹配概览</th>
                <th scope="col" aria-label="操作" />
              </tr>
            </thead>
            <tbody>
              {ranked.map((item, index) => {
                const met = item.requirement_results.filter((result) => result.outcome === "met").length;
                const partial = item.requirement_results.filter((result) => result.outcome === "partial").length;
                const unknown = item.requirement_results.filter((result) => result.outcome === "unknown").length;
                return (
                  <tr key={item.match_id}>
                    <td className="match-rank">{index + 1}</td>
                    <td>
                      <strong>{item.candidate_display_name?.trim() || "未命名候选人"}</strong>
                      <small>简历事实 v{item.facts_version}</small>
                    </td>
                    <td>
                      <span className="match-score">{item.total_score.toFixed(1)}</span>
                    </td>
                    <td>
                      <span className={`match-hard-status is-${item.hard_requirement_status ?? "unknown"}`}>
                        {hardLabel[item.hard_requirement_status ?? ""] ?? "待确认"}
                      </span>
                    </td>
                    <td className="match-overview">
                      <span>满足 {met}</span>
                      <span>部分满足 {partial}</span>
                      {unknown > 0 && <span>信息不足 {unknown}</span>}
                    </td>
                    <td>
                      <button className="button button-ghost match-open-button" onClick={() => onOpenResume(item)} type="button">
                        <Icon name="document" size={15} />
                        查看简历
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty-state match-empty-state">
          <div className="empty-state-inner">
            <span className="empty-glyph"><Icon name="match" size={23} /></span>
            <h2>尚未生成匹配结果</h2>
            <p>确认 JD 后，点击“批量匹配全部简历”即可在此查看排序结果。</p>
          </div>
        </div>
      )}
    </section>
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
