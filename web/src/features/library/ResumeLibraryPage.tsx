import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { Icon } from "../../icons";
import {
  RESUME_EXTRACTION_FAILED_LABEL,
  resumeExtractionStatusMessage,
} from "../../resume-extraction-user-messages";
import { BackofficeButton } from "../../backoffice/ui/BackofficeButton";
import { BackofficeSelect } from "../../backoffice/ui/BackofficeSelect";
import { TableSkeleton } from "../../backoffice/ui/TableSkeleton";
import {
  AI_STATUS_POLL_INTERVAL_MS,
  aiExtractionIsInProgress,
  aiSummaryIsInProgress,
  scoreTaskIsInProgress,
} from "../../backoffice/utils/ai-extraction";
import { formatLibraryDate } from "../../backoffice/utils/formatters";
import {
  hasSourceTextQualityIssue,
  hasSupersededReparseVersion,
} from "../../backoffice/utils/resume-source-quality";
import { degreeLabels, formatDuration } from "../filter/filter-model";
import type {
  MailboxConfig,
  ResumeAnalysisWaitEstimate,
  ResumeLibraryItem,
  ResumeLibraryResponse,
  ResumeLibraryStatusFilter,
} from "../../types";
import "./resume-library.css";

const SemiTabs = lazy(() => import("@douyinfe/semi-ui-19/lib/es/tabs"));
const SemiTabPane = lazy(() => import("@douyinfe/semi-ui-19/lib/es/tabs/TabPane"));
const SemiCheckbox = lazy(() => import("@douyinfe/semi-ui-19/lib/es/checkbox/checkbox"));

const DEFAULT_RESUME_LIBRARY_PAGE_SIZE = 50;
const RESUME_LIBRARY_PAGE_SIZE_OPTIONS = [25, 50, 100];
const RESUME_LIBRARY_PAGE_SIZE_SELECT_OPTIONS = RESUME_LIBRARY_PAGE_SIZE_OPTIONS.map(
  (pageSize) => ({ label: `${pageSize} 条`, value: String(pageSize) }),
);

/** Sentinel tab key for the unfiltered view. */
const ALL_RESUMES_TAB = "all";

interface ResumeLibraryPageProps {
  formatError: (error: unknown) => string;
  onOpenResume: (item: ResumeLibraryItem) => void;
  onUpload: () => void;
  refreshToken: number;
  selectedResumeId: string | null;
  /** Refresh other candidate-facing surfaces after a private bookmark changes. */
  onFavoriteChanged?: () => void;
  /** Transient feedback region for one-click retry outcomes. */
  notify: (kind: "success" | "error", message: string) => void;
}

type AnalysisPhase = "source_reading" | "resume_analysis" | "name_completion";
type AnalysisWaitState = "queued" | "running";

const ANALYSIS_ACTIVITY_ROTATE_INTERVAL_MS = 2_800;

const ANALYSIS_PHASE_DETAILS: Record<
  AnalysisPhase,
  {
    step: string;
    label: string;
    waitingLabel: string;
    runningLabel: string;
    queuedActivity: string;
    runningActivities: readonly string[];
  }
> = {
  source_reading: {
    step: "第 1 步 / 3",
    label: "读取简历原文件",
    waitingLabel: "等待读取原文件",
    runningLabel: "AI 正在读取原文件",
    queuedActivity: "已进入队列，准备读取简历原文件",
    runningActivities: [
      "正在读取简历原文件",
      "正在识别文本与版式",
      "正在整理可读内容",
    ],
  },
  resume_analysis: {
    step: "第 2 步 / 3",
    label: "提取简历信息",
    waitingLabel: "等待 AI 分析",
    runningLabel: "AI 正在提取信息",
    queuedActivity: "已进入队列，准备提取简历信息",
    runningActivities: [
      "正在提取姓名",
      "正在提取项目经历",
      "正在提取教育与学历",
      "正在提取应届信息",
      "正在提取工作经历",
      "正在提取核心技能",
    ],
  },
  name_completion: {
    step: "第 3 步 / 3",
    label: "补全候选人姓名",
    waitingLabel: "等待补全姓名",
    runningLabel: "AI 正在补全姓名",
    queuedActivity: "已进入队列，准备补全候选人姓名",
    runningActivities: [
      "正在提取姓名",
      "正在核对简历原文",
      "正在补全候选人姓名",
    ],
  },
};

function analysisPhase(
  estimate: ResumeAnalysisWaitEstimate,
): AnalysisPhase {
  if (estimate.phase) return estimate.phase;
  return estimate.target === "candidate_name"
    ? "name_completion"
    : "resume_analysis";
}

function analysisWaitState(
  estimate: ResumeAnalysisWaitEstimate,
): AnalysisWaitState {
  return estimate.state === "running" ? "running" : "queued";
}

function analysisPhaseDetails(estimate: ResumeAnalysisWaitEstimate) {
  return ANALYSIS_PHASE_DETAILS[analysisPhase(estimate)];
}

function stableTextOffset(value: string): number {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
  }
  return hash;
}

function analysisActivityCopy(
  estimate: ResumeAnalysisWaitEstimate,
  resumeId: string,
  activityTick: number,
): string {
  const details = analysisPhaseDetails(estimate);
  if (analysisWaitState(estimate) !== "running") {
    return details.queuedActivity;
  }
  const messages = details.runningActivities;
  return messages[(stableTextOffset(resumeId) + activityTick) % messages.length];
}

function analysisActivityAriaLabel(estimate: ResumeAnalysisWaitEstimate): string {
  const details = analysisPhaseDetails(estimate);
  const state = analysisWaitState(estimate) === "running"
    ? details.runningLabel
    : details.waitingLabel;
  return `${details.step}，${state}。${waitEstimateLabel(estimate)}`;
}

function resumeLibraryStatus(item: ResumeLibraryItem): {
  label: string;
  tone: "ready" | "progress" | "attention" | "waiting";
} {
  if (hasSourceTextQualityIssue(item.quality_flags)) {
    return { label: RESUME_EXTRACTION_FAILED_LABEL, tone: "attention" };
  }
  if (hasSupersededReparseVersion(item.quality_flags)) {
    return { label: "当前版本已更新", tone: "attention" };
  }
  if (item.analysis_wait_estimate) {
    const details = analysisPhaseDetails(item.analysis_wait_estimate);
    return analysisWaitState(item.analysis_wait_estimate) === "running"
      ? { label: details.runningLabel, tone: "progress" }
      : { label: details.waitingLabel, tone: "waiting" };
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
    return {
      label: item.ai_extraction_error?.startsWith("tencent_ocr_") ||
        item.ai_extraction_error?.startsWith("document_extraction_") ||
        item.ai_extraction_error?.startsWith("office_conversion_") ||
        item.ai_extraction_error?.startsWith("spreadsheet_conversion_")
        ? "服务暂时不可用"
        : "需要处理",
      tone: "attention",
    };
  }
  if (item.ai_extraction_status === "unavailable") {
    return { label: "等待 AI 服务", tone: "attention" };
  }
  if (
    !item.display_name?.trim() &&
    item.candidate_name_extraction_status === "running"
  ) {
    return { label: "AI 正在识别姓名", tone: "progress" };
  }
  if (
    !item.display_name?.trim() &&
    item.candidate_name_extraction_status === "queued"
  ) {
    return { label: "等待识别姓名", tone: "waiting" };
  }
  if (item.is_active && item.extraction_status === "ready") {
    if (aiSummaryIsInProgress(item.ai_summary_status)) {
      return { label: "AI 总结生成中", tone: "progress" };
    }
    if (item.ai_summary_status === "failed") {
      return { label: "总结待重试", tone: "attention" };
    }
    if (item.ai_summary_status === "unavailable") {
      return { label: "总结暂不可用", tone: "attention" };
    }
    return { label: "已启用", tone: "ready" };
  }
  return { label: "等待启用", tone: "waiting" };
}

/**
 * The server owns the status-tab classification: the response carries
 * whole-library ``status_counts`` / ``all_total`` so the badges stay stable
 * no matter which page or filter is active. A healthy active resume belongs
 * to no tab.
 */

/** Whether one-click retry has any branch to dispatch for this row. */
function isRowRetryable(item: ResumeLibraryItem): boolean {
  const readyForProcessing = item.is_active && item.extraction_status === "ready";
  // First-time summary/score: a ready resume with a missing result is retryable.
  const missingScore = readyForProcessing && item.score_status == null;
  const missingSummary = readyForProcessing && item.ai_summary_status == null;
  return Boolean(
    item.score_retryable ||
      item.ai_summary_status === "failed" ||
      item.ai_summary_status === "unavailable" ||
      item.ai_extraction_status === "needs_attention" ||
      item.ai_extraction_status === "unavailable" ||
      item.extraction_status === "failed" ||
      missingScore ||
      missingSummary,
  );
}

interface LibraryStatusTab {
  key: ResumeLibraryStatusFilter | typeof ALL_RESUMES_TAB;
  label: string;
  count: number;
}

const STATUS_TAB_DEFINITIONS: ReadonlyArray<{
  key: LibraryStatusTab["key"];
  label: string;
}> = [
  { key: ALL_RESUMES_TAB, label: "全部" },
  { key: "processing", label: "处理中" },
  { key: "attention", label: "需处理" },
  { key: "unscored", label: "待评分" },
  { key: "summary_pending", label: "待总结" },
];

function waitEstimateLabel(estimate: ResumeAnalysisWaitEstimate): string {
  const minimum = Math.max(0, estimate.estimated_min_seconds);
  const maximum = Math.max(minimum, estimate.estimated_max_seconds);
  if (maximum < 60) return "预计少于 1 分钟";
  const minimumMinutes = Math.max(1, Math.floor(minimum / 60));
  const maximumMinutes = Math.max(minimumMinutes, Math.ceil(maximum / 60));
  if (minimumMinutes === maximumMinutes) {
    return `预计约 ${maximumMinutes} 分钟`;
  }
  return `预计 ${minimumMinutes}–${maximumMinutes} 分钟`;
}

function waitEstimateHint(estimate: ResumeAnalysisWaitEstimate): string {
  const target = estimate.target === "candidate_name" ? "姓名识别" : "简历分析";
  const basis = estimate.confidence === "observed"
    ? "根据当前工作区队列和近期同类任务耗时估算。"
    : "当前工作区历史样本较少，先按安全范围估算。";
  return `${target}${basis}该估算时长会随队列情况自动更新。`;
}

function AnalysisActivity({
  estimate,
  resumeId,
  activityTick,
}: {
  estimate: ResumeAnalysisWaitEstimate;
  resumeId: string;
  activityTick: number;
}) {
  const details = analysisPhaseDetails(estimate);
  const state = analysisWaitState(estimate);
  const activity = analysisActivityCopy(estimate, resumeId, activityTick);

  return (
    <span
      aria-label={analysisActivityAriaLabel(estimate)}
      className={`library-ai-activity is-${state}`}
      role="status"
      title={`${analysisActivityAriaLabel(estimate)} ${waitEstimateHint(estimate)}`}
    >
      <span aria-hidden="true" className="library-ai-orb">
        <span className="library-ai-orb-label">AI</span>
      </span>
      <span aria-hidden="true" className="library-ai-activity-copy">
        <span className="library-ai-activity-phase">
          {details.step} · {details.label}
        </span>
        <span className="library-ai-activity-detail">
          {activity}
        </span>
        <span className="library-ai-activity-eta">
          {waitEstimateLabel(estimate)}
        </span>
      </span>
    </span>
  );
}

function summaryStatusLabel(item: ResumeLibraryItem): string {
  if (aiSummaryIsInProgress(item.ai_summary_status)) {
    return "AI 总结生成中";
  }
  if (item.ai_summary_status === "failed") {
    return "AI 总结生成失败，打开后可重试";
  }
  if (item.ai_summary_status === "unavailable") {
    return "AI 总结暂时不可用，稍后可重试";
  }
  if (item.ai_summary_status === "succeeded") {
    return "AI 总结已生成，正在加载";
  }
  return item.is_active
    ? "等待 AI 自动生成总结"
    : "候选人信息提取完成后自动生成";
}

function resumeLibraryScoreNotice(status: string | null): string | null {
  switch (status) {
    case "overridden":
      return "含人工调整";
    case "needs_review":
      return "建议复核";
    case "succeeded":
      return null;
    default:
      return "评分待更新";
  }
}

function graduationProfileLabel(graduationMonth: string | null): string {
  const match = /^(\d{4})-(?:0[1-9]|1[0-2])$/.exec(
    graduationMonth?.trim() ?? "",
  );
  if (!match) return "毕业时间待核实";

  const graduationYear = Number(match[1]);
  const currentYear = new Date().getFullYear();
  if (graduationYear > currentYear) return `${graduationYear}届（在读）`;
  if (graduationYear === currentYear) return `${graduationYear}届`;
  return `${graduationYear}年毕业`;
}

function workExperienceLabel(months: number): string {
  const normalizedMonths = Number.isFinite(months)
    ? Math.max(0, Math.trunc(months))
    : 0;
  if (normalizedMonths === 0) return "暂无工作经验";
  return `${formatDuration(normalizedMonths)}工作经验`;
}

function candidateProfileText(item: ResumeLibraryItem): string {
  const degree = item.highest_degree;
  const hasProfileFacts = Boolean(
    item.graduation_month ||
      item.education_school?.trim() ||
      (degree && degree !== "unknown") ||
      item.employment_or_internship_months > 0,
  );
  if (!hasProfileFacts) {
    return item.ai_extraction_status === "queued" ||
      item.ai_extraction_status === "running"
      ? "候选人信息提取中"
      : "候选人信息待核实";
  }

  return [
    graduationProfileLabel(item.graduation_month),
    workExperienceLabel(item.employment_or_internship_months),
    item.education_school?.trim() || "学校待核实",
    degree && degree !== "unknown" ? degreeLabels[degree] : "学历待核实",
  ].join(" · ");
}

export function ResumeLibraryPage({
  formatError,
  notify,
  selectedResumeId,
  refreshToken,
  onOpenResume,
  onUpload,
  onFavoriteChanged,
}: ResumeLibraryPageProps) {
  const [library, setLibrary] = useState<ResumeLibraryResponse | null>(null);
  const [mailboxSources, setMailboxSources] = useState<MailboxConfig[]>([]);
  const [sourceMailboxId, setSourceMailboxId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<ResumeLibraryStatusFilter | null>(null);
  const [selectedResumeIds, setSelectedResumeIds] = useState<ReadonlySet<string>>(
    new Set(),
  );
  const [selectAllInLibrary, setSelectAllInLibrary] = useState(false);
  const [batchRetrying, setBatchRetrying] = useState(false);
  const [retryingResumeId, setRetryingResumeId] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_RESUME_LIBRARY_PAGE_SIZE);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [analysisActivityTick, setAnalysisActivityTick] = useState(0);
  const [reduceMotion, setReduceMotion] = useState(false);
  const [favoriteActionCandidateId, setFavoriteActionCandidateId] = useState<
    string | null
  >(null);
  const latestLibraryRequestIdRef = useRef(0);
  const hasRunningAnalysis = Boolean(
    library?.items.some(
      (item) =>
        item.analysis_wait_estimate &&
        analysisWaitState(item.analysis_wait_estimate) === "running",
    ),
  );

  const loadLibrary = useCallback(async () => {
    const requestId = ++latestLibraryRequestIdRef.current;
    setLoading(true);
    setError(null);
    try {
      const nextLibrary = await api.listResumeLibrary(
        page,
        pageSize,
        sourceMailboxId,
        statusFilter,
      );
      if (requestId === latestLibraryRequestIdRef.current) {
        setLibrary(nextLibrary);
      }
    } catch (loadError) {
      if (requestId === latestLibraryRequestIdRef.current) {
        setError(formatError(loadError));
      }
    } finally {
      if (requestId === latestLibraryRequestIdRef.current) {
        setLoading(false);
      }
    }
  }, [formatError, page, pageSize, sourceMailboxId, statusFilter]);

  useEffect(() => {
    void loadLibrary();
  }, [loadLibrary, refreshToken]);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const syncPreference = () => setReduceMotion(media.matches);
    syncPreference();
    media.addEventListener("change", syncPreference);
    return () => media.removeEventListener("change", syncPreference);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void api.listMailboxConfigs(true)
      .then((response) => {
        if (!cancelled) setMailboxSources(response.items);
      })
      // The library remains usable when the current plan cannot use mailbox
      // ingestion. In that case there is simply no source-specific filter.
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (
      !library?.items.some((item) =>
        aiExtractionIsInProgress(item.ai_extraction_status) ||
        aiExtractionIsInProgress(item.candidate_name_extraction_status) ||
        aiSummaryIsInProgress(item.ai_summary_status) ||
        scoreTaskIsInProgress(item.score_task_state),
      )
    ) {
      return undefined;
    }
    const interval = window.setInterval(() => {
      void loadLibrary();
    }, AI_STATUS_POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [library, loadLibrary]);

  useEffect(() => {
    if (reduceMotion || !hasRunningAnalysis) return undefined;
    const interval = window.setInterval(() => {
      setAnalysisActivityTick((current) => current + 1);
    }, ANALYSIS_ACTIVITY_ROTATE_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [hasRunningAnalysis, reduceMotion]);

  const toggleFavorite = useCallback(
    async (item: ResumeLibraryItem) => {
      if (favoriteActionCandidateId === item.candidate_id) return;
      setFavoriteActionCandidateId(item.candidate_id);
      setError(null);
      try {
        const nextState = item.is_favorited
          ? (await api.unfavoriteCandidate(item.candidate_id), false)
          : (await api.favoriteCandidate(item.candidate_id)).is_favorited;
        setLibrary((current) =>
          current
            ? {
                ...current,
                items: current.items.map((entry) =>
                  entry.candidate_id === item.candidate_id
                    ? { ...entry, is_favorited: nextState }
                    : entry,
                ),
              }
            : current,
        );
        onFavoriteChanged?.();
      } catch (favoriteError) {
        setError(formatError(favoriteError));
      } finally {
        setFavoriteActionCandidateId(null);
      }
    },
    [favoriteActionCandidateId, formatError, onFavoriteChanged],
  );

  const items = library?.items ?? [];
  const total = library?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const canPageBack = page > 1;
  const canPageForward = page < totalPages;
  const statusTabs: LibraryStatusTab[] = STATUS_TAB_DEFINITIONS.map((tab) => {
    const count =
      tab.key === ALL_RESUMES_TAB
        ? library?.all_total ?? total
        : library?.status_counts?.[tab.key] ?? 0;
    return { ...tab, count };
  });
  const pageResumeIds = items.map((item) => item.resume_id);
  const allOnPageSelected = pageResumeIds.length > 0 && pageResumeIds.every(
    (resumeId) => selectedResumeIds.has(resumeId),
  );
  const someOnPageSelected = pageResumeIds.some((resumeId) =>
    selectedResumeIds.has(resumeId),
  );
  const firstItemIndex = total ? (page - 1) * pageSize + 1 : 0;
  const lastItemIndex = Math.min(page * pageSize, total);

  const toggleRowSelection = useCallback(
    (item: ResumeLibraryItem, checked: boolean | undefined) => {
      setSelectedResumeIds((current) => {
        const next = new Set(current);
        if (checked) next.add(item.resume_id);
        else next.delete(item.resume_id);
        return next;
      });
    },
    [],
  );

  const toggleSelectAllInLibrary = useCallback((checked: boolean | undefined) => {
    const next = Boolean(checked);
    setSelectAllInLibrary(next);
    if (next) setSelectedResumeIds(new Set());
  }, []);

  const handleStatusTabChange = useCallback((key: string) => {
    const next =
      key === ALL_RESUMES_TAB ? null : (key as ResumeLibraryStatusFilter);
    setStatusFilter(next);
    setPage(1);
  }, []);

  const retrySelected = useCallback(async () => {
    if (batchRetrying) return;
    const ids = [...selectedResumeIds];
    if (!selectAllInLibrary && !ids.length) return;
    setBatchRetrying(true);
    setError(null);
    try {
      const result = selectAllInLibrary
        ? await api.retryResumesAll()
        : await api.retryResumesFailed(ids);
      notify(
        "success",
        `已重试 ${result.queued_count}，跳过 ${result.skipped_count}`,
      );
      setSelectAllInLibrary(false);
      setSelectedResumeIds(new Set());
      void loadLibrary();
    } catch (retryError) {
      setError(formatError(retryError));
    } finally {
      setBatchRetrying(false);
    }
  }, [
    batchRetrying,
    formatError,
    loadLibrary,
    notify,
    selectAllInLibrary,
    selectedResumeIds,
  ]);

  const retryResume = useCallback(
    async (item: ResumeLibraryItem) => {
      if (retryingResumeId === item.resume_id) return;
      setRetryingResumeId(item.resume_id);
      setError(null);
      try {
        const result = await api.retryResumeFailed(item.resume_id);
        notify(
          "success",
          result.queued.length
            ? "已重新加入处理队列"
            : "该简历当前没有可重试的失败环节",
        );
        setSelectedResumeIds((current) => {
          if (!current.has(item.resume_id)) return current;
          const next = new Set(current);
          next.delete(item.resume_id);
          return next;
        });
        void loadLibrary();
      } catch (retryError) {
        setError(formatError(retryError));
      } finally {
        setRetryingResumeId(null);
      }
    },
    [formatError, loadLibrary, notify, retryingResumeId],
  );

  const mailboxOptions = [
    { label: "全部来源", value: "" },
    ...mailboxSources.map((mailbox) => ({
      label: mailbox.archived_at
        ? `${mailbox.display_name}（已归档）`
        : mailbox.display_name,
      value: mailbox.mailbox_id,
    })),
  ];

  return (
    <div className="page-frame resume-library-page">
      <header className="page-heading">
        <div>
          <h1>简历库</h1>
        </div>
        <div className="resume-library-actions">
          {mailboxSources.length ? (
            <div className="resume-library-source-filter">
              <label className="sr-only" id="resume-library-source-label">
                按收件通道筛选
              </label>
              <BackofficeSelect
                ariaLabelledBy="resume-library-source-label"
                id="resume-library-source"
                onChange={(mailboxId) => {
                  setPage(1);
                  setSourceMailboxId(mailboxId || null);
                }}
                options={mailboxOptions}
                value={sourceMailboxId ?? ""}
              />
            </div>
          ) : null}
          {(selectAllInLibrary || selectedResumeIds.size > 0) && (
            <BackofficeButton
              disabled={batchRetrying}
              icon={batchRetrying ? undefined : <Icon name="refresh" size={16} />}
              loading={batchRetrying}
              onClick={() => void retrySelected()}
              tone="primary"
            >
              {selectAllInLibrary
                ? `重试全部（${library?.all_total ?? 0}）`
                : `重试所选（${selectedResumeIds.size}）`}
            </BackofficeButton>
          )}
          <BackofficeButton
            disabled={loading}
            icon={loading ? undefined : <Icon name="refresh" size={16} />}
            loading={loading}
            onClick={() => void loadLibrary()}
          >
            刷新
          </BackofficeButton>
          <BackofficeButton
            icon={<Icon name="upload" size={16} />}
            onClick={onUpload}
            tone="primary"
          >
            上传简历
          </BackofficeButton>
        </div>
      </header>

      {library && (
        <Suspense fallback={<p className="library-status-tabs-loading">正在加载状态筛选…</p>}>
          <SemiTabs
            activeKey={statusFilter ?? ALL_RESUMES_TAB}
            aria-label="按状态筛选简历"
            className="library-status-tabs"
            onChange={handleStatusTabChange}
            type="button"
          >
            {statusTabs.map((tab) => (
              <SemiTabPane
                itemKey={tab.key}
                key={tab.key}
                tab={(
                  <span className="library-status-tab">
                    {tab.label}
                    <span className="library-status-tab-count">{tab.count}</span>
                  </span>
                )}
              />
            ))}
          </SemiTabs>
        </Suspense>
      )}

      {error && (
        <p className="library-error" role="status">
          {error}
        </p>
      )}

      <section aria-label="简历库列表" className="library-table-frame">
        <Suspense fallback={<TableSkeleton />}>
          {loading && !library ? (
            <TableSkeleton />
          ) : items.length ? (
            <div
              aria-label="简历库列表，可横向滚动查看全部字段"
              className="table-scroll"
              role="region"
              tabIndex={0}
            >
              <table className="candidate-table library-table">
                <thead>
                  <tr>
                    <th aria-label="选择简历" className="library-check-cell" scope="col">
                      <SemiCheckbox
                        aria-label="选择全部简历（含所有页）"
                        checked={selectAllInLibrary || allOnPageSelected}
                        indeterminate={
                          !selectAllInLibrary &&
                          someOnPageSelected &&
                          !allOnPageSelected
                        }
                        onChange={(event) =>
                          toggleSelectAllInLibrary(event.target.checked)
                        }
                      />
                    </th>
                    <th scope="col">候选人</th>
                    <th scope="col">AI 总结</th>
                    <th scope="col">AI 评分</th>
                    <th scope="col">上传时间</th>
                    <th aria-label="操作" scope="col" />
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => {
                    const status = resumeLibraryStatus(item);
                    const sourceTextIssue = hasSourceTextQualityIssue(
                      item.quality_flags,
                    );
                    const supersededReparse = hasSupersededReparseVersion(
                      item.quality_flags,
                    );
                    const scoreNotice = resumeLibraryScoreNotice(
                      item.score_status,
                    );
                    const candidateProfile = candidateProfileText(item);
                    const favoriteUpdating =
                      favoriteActionCandidateId === item.candidate_id;
                    const retryable = isRowRetryable(item);
                    const rowRetrying = retryingResumeId === item.resume_id;
                    return (
                      <tr
                        className={[
                          selectedResumeId === item.resume_id ? "is-selected" : "",
                          sourceTextIssue ? "has-source-quality-issue" : "",
                          supersededReparse ? "has-superseded-reparse" : "",
                        ]
                          .filter(Boolean)
                          .join(" ")}
                        key={item.resume_id}
                        onClick={() => onOpenResume(item)}
                      >
                        <td
                          className="library-check-cell"
                          onClick={(event) => event.stopPropagation()}
                        >
                          <SemiCheckbox
                            aria-label={`选择 ${item.display_name?.trim() || "未命名候选人"}`}
                            checked={
                              selectAllInLibrary ||
                              selectedResumeIds.has(item.resume_id)
                            }
                            disabled={rowRetrying || selectAllInLibrary}
                            onChange={(event) =>
                              toggleRowSelection(item, event.target.checked)
                            }
                          />
                        </td>
                        <td className="library-candidate-cell">
                          <div className="candidate-person">
                          <span className="candidate-name">
                            {item.display_name?.trim() || "未命名候选人"}
                          </span>
                          <span
                            className="candidate-meta library-candidate-profile"
                            title={candidateProfile}
                          >
                            {candidateProfile}
                          </span>
                          <button
                            aria-busy={favoriteUpdating}
                            aria-label={
                              item.is_favorited
                                ? `取消收藏 ${item.display_name?.trim() || "未命名候选人"}`
                                : `收藏 ${item.display_name?.trim() || "未命名候选人"}`
                            }
                            aria-pressed={item.is_favorited}
                            className={`library-favorite-button${item.is_favorited ? " is-favorited" : ""}`}
                            disabled={favoriteUpdating}
                            onClick={(event) => {
                              event.stopPropagation();
                              void toggleFavorite(item);
                            }}
                            type="button"
                          >
                            {favoriteUpdating ? (
                              <i className="spinner" />
                            ) : (
                              <Icon name="bookmark" size={14} />
                            )}
                            {item.is_favorited ? "已收藏" : "收藏"}
                          </button>
                          {item.analysis_wait_estimate &&
                          !sourceTextIssue &&
                          !supersededReparse ? (
                            <AnalysisActivity
                              activityTick={analysisActivityTick}
                              estimate={item.analysis_wait_estimate}
                              resumeId={item.resume_id}
                            />
                          ) : status.tone !== "ready" ? (
                            <div className="library-processing-meta">
                              <span
                                className={`library-status is-${status.tone}`}
                                title={
                                  sourceTextIssue
                                    ? `${RESUME_EXTRACTION_FAILED_LABEL}。请重新解析原文件后重试。`
                                    : supersededReparse
                                      ? "候选人已有更新版本，此解析版本不会被启用。"
                                      : resumeExtractionStatusMessage(
                                        item.ai_extraction_error,
                                      )
                                }
                              >
                                {status.label}
                              </span>
                            </div>
                          ) : null}
                          {(item.source_mailbox_label || item.source_tags.length > 0) && (
                            <div className="library-source-provenance">
                              {item.source_mailbox_label && (
                                <span className="candidate-meta library-source-label">
                                  收件通道 · {item.source_mailbox_label}
                                </span>
                              )}
                              {item.source_tags.length > 0 && (
                                <div
                                  aria-label={`投递渠道：${item.source_tags.map((tag) => tag.display_name).join("、")}`}
                                  className="library-source-tags"
                                  title={`投递渠道：${item.source_tags.map((tag) => tag.display_name).join("、")}`}
                                >
                                  {item.source_tags.slice(0, 2).map((tag) => (
                                    <span className="tag" key={tag.source_tag_id}>{tag.display_name}</span>
                                  ))}
                                  {item.source_tags.length > 2 && (
                                    <span className="library-source-tags-more">+{item.source_tags.length - 2}</span>
                                  )}
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      </td>
                      <td className="library-summary-cell">
                        {sourceTextIssue ? (
                          <span className="library-quality-copy">
                            {RESUME_EXTRACTION_FAILED_LABEL}
                          </span>
                        ) : supersededReparse ? (
                          <span className="library-quality-copy">
                            此解析版本已过期，不展示旧结论。
                          </span>
                        ) : item.summary_preview ? (
                          <p
                            className="library-summary-preview"
                            title={item.summary_preview}
                          >
                            {item.summary_preview}
                          </p>
                        ) : (
                          <span
                            className={`library-summary-status${
                              item.ai_summary_status === "failed" ||
                              item.ai_summary_status === "unavailable"
                                ? " is-attention"
                                : ""
                            }`}
                            title={item.ai_summary_error ?? undefined}
                          >
                            {aiSummaryIsInProgress(item.ai_summary_status) && (
                              <i aria-hidden="true" className="spinner" />
                            )}
                            {summaryStatusLabel(item)}
                          </span>
                        )}
                      </td>
                      <td>
                        {sourceTextIssue ? (
                          <span className="library-quality-copy">
                            请先打开并重新解析
                          </span>
                        ) : supersededReparse ? (
                          <span className="library-quality-copy">
                            请使用候选人的当前版本
                          </span>
                        ) : item.score_total !== null ? (
                          <div
                            className="library-score"
                            title={item.score_template_name ?? "评分模板"}
                          >
                            <strong>{item.score_total.toFixed(1)}</strong>
                            <span>/ 100</span>
                            {scoreNotice && <small>{scoreNotice}</small>}
                          </div>
                        ) : scoreTaskIsInProgress(item.score_task_state) ? (
                          <div
                            className="library-score-activity"
                            role="status"
                            aria-label="正在生成 AI 评分"
                          >
                            <span
                              className="library-score-activity-dot"
                              aria-hidden="true"
                            />
                            <span className="library-score-activity-copy">
                              评分生成中…
                            </span>
                          </div>
                        ) : item.is_active ? (
                          <span className="library-empty-copy">
                            尚无通用评分
                          </span>
                        ) : (
                          <span className="library-empty-copy">
                            完成提取后可评分
                          </span>
                        )}
                      </td>
                      <td>
                        <span className="candidate-meta">
                          {formatLibraryDate(item.created_at)}
                        </span>
                      </td>
                      <td className="library-open-cell">
                        {retryable && (
                          <button
                            aria-label={`重试 ${item.display_name?.trim() || "未命名候选人"} 的失败环节`}
                            className="library-retry-button"
                            disabled={rowRetrying}
                            onClick={(event) => {
                              event.stopPropagation();
                              void retryResume(item);
                            }}
                            title="重新排队失败的解析、提取、总结或评分"
                            type="button"
                          >
                            {rowRetrying ? (
                              <i aria-hidden="true" className="spinner" />
                            ) : (
                              <Icon name="refresh" size={14} />
                            )}
                            重试
                          </button>
                        )}
                        <button
                          aria-label={`查看 ${item.display_name?.trim() || "未命名候选人"} 的简历详情`}
                          className="library-open-affordance"
                          onClick={(event) => {
                            event.stopPropagation();
                            onOpenResume(item);
                          }}
                          type="button"
                        >
                          <Icon name="chevron-right" size={17} />
                        </button>
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
              <BackofficeButton
                icon={<Icon name="upload" size={16} />}
                onClick={onUpload}
                tone="primary"
              >
                上传简历
              </BackofficeButton>
            </div>
          </div>
        )}
        </Suspense>
      </section>

      <footer className="library-table-footer">
        <span>
          {loading && library ? (
            <span className="loading-line">
              <i className="spinner" />
              正在更新简历库…
            </span>
          ) : (
            total ? `显示第 ${firstItemIndex}–${lastItemIndex} 份，共 ${total} 份` : "共 0 份简历"
          )}
        </span>
        {total > 0 && (
          <div className="library-footer-controls">
            <div className="library-page-size-control">
              <label id="resume-library-page-size-label" htmlFor="resume-library-page-size">
                每页展示
              </label>
              <BackofficeSelect
                ariaLabelledBy="resume-library-page-size-label"
                disabled={loading}
                id="resume-library-page-size"
                onChange={(value) => {
                  const nextPageSize = Number(value);
                  if (!RESUME_LIBRARY_PAGE_SIZE_OPTIONS.includes(nextPageSize)) {
                    return;
                  }
                  setPage(1);
                  setPageSize(nextPageSize);
                }}
                options={RESUME_LIBRARY_PAGE_SIZE_SELECT_OPTIONS}
                value={String(pageSize)}
              />
            </div>
            {totalPages > 1 && (
              <div className="pagination">
                <BackofficeButton
                  disabled={!canPageBack || loading}
                  onClick={() => setPage((current) => current - 1)}
                >
                  上一页
                </BackofficeButton>
                <span>
                  第 {page} / {totalPages} 页
                </span>
                <BackofficeButton
                  disabled={!canPageForward || loading}
                  onClick={() => setPage((current) => current + 1)}
                >
                  下一页
                </BackofficeButton>
              </div>
            )}
          </div>
        )}
      </footer>
    </div>
  );
}
