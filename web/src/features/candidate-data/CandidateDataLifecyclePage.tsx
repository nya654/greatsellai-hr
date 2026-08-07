import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import type {
  CandidateDataAuditEvent,
  CandidateDataDeletionBatch,
  CandidateDataDeletionReason,
  CandidateDataExport,
  CandidateDataRetentionCleanupRun,
  CandidateDataRetentionMode,
  CandidateDataRetentionPolicy,
  CandidateDataRetentionPreview,
} from "../../types";
import { Icon } from "../../icons";
import { BackofficeButton } from "../../backoffice/ui/BackofficeButton";
import { BackofficeInput } from "../../backoffice/ui/BackofficeInput";
import { TableSkeleton } from "../../backoffice/ui/TableSkeleton";
import { StatusPillTag } from "../../backoffice/ui/StatusPillTag";
import { formatLibraryDate } from "../../backoffice/utils/formatters";

const SemiTabs = lazy(() => import("@douyinfe/semi-ui-19/lib/es/tabs"));
const SemiTabPane = lazy(() => import("@douyinfe/semi-ui-19/lib/es/tabs/TabPane"));
const SemiRadioGroup = lazy(() => import("@douyinfe/semi-ui-19/lib/es/radio/radioGroup"));
const SemiRadio = lazy(() => import("@douyinfe/semi-ui-19/lib/es/radio"));
const SemiTable = lazy(() => import("@douyinfe/semi-ui-19/lib/es/table"));
const SemiList = lazy(() => import("@douyinfe/semi-ui-19/lib/es/list"));
const SemiListItem = lazy(() => import("@douyinfe/semi-ui-19/lib/es/list/item"));
const SemiEmpty = lazy(() => import("@douyinfe/semi-ui-19/lib/es/empty"));
const SemiTitle = lazy(() => import("@douyinfe/semi-ui-19/lib/es/typography/title"));
const SemiParagraph = lazy(() => import("@douyinfe/semi-ui-19/lib/es/typography/paragraph"));
const SemiBanner = lazy(() => import("@douyinfe/semi-ui-19/lib/es/banner"));

type ToastKind = "success" | "error";
type CandidateDataEmbeddedSection = "retention" | "activity";

const candidateDataEmbeddedSections: Array<{
  id: CandidateDataEmbeddedSection;
  label: string;
  icon: "gear" | "history";
}> = [
  { id: "retention", label: "保留策略", icon: "gear" },
  { id: "activity", label: "操作与记录", icon: "history" },
];

const candidateDataDeletionReasonOptions: Array<{
  value: CandidateDataDeletionReason;
  label: string;
}> = [
  { value: "candidate_request", label: "候选人提出删除" },
  { value: "recruitment_closed", label: "招聘流程结束" },
  { value: "duplicate", label: "重复资料" },
  { value: "other", label: "其他原因" },
];

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

const mainColumnStyle = { display: "grid", gap: "var(--space-md)", minWidth: 0 };
const sideColumnStyle = { display: "grid", gap: "var(--space-md)", minWidth: 0 };
const fullLayoutStyle = { gap: "var(--space-xl)", alignItems: "start" };

export function CandidateDataLifecyclePage({
  formatError,
  notify,
  onOpenLibrary,
  embedded = false,
}: {
  formatError: (error: unknown) => string;
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
  const [embeddedSection, setEmbeddedSection] = useState<CandidateDataEmbeddedSection>("retention");

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
      const message = formatError(loadError);
      setError(message);
      if (!showLoading) notify("error", message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [formatError, notify]);

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
      notify("error", formatError(previewError));
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
      notify("success", saved.mode === "automatic" ? "已启用候选人资料自动删除策略。" : "已改为手动删除，系统不会按期限自动删除候选人资料。");
      await load(false);
    } catch (saveError) {
      notify("error", formatError(saveError));
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
      notify("error", formatError(cleanupError));
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
      notify("error", formatError(restoreError));
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
      notify("error", formatError(cancelError));
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
      notify("error", formatError(downloadError));
    } finally {
      setDownloadingExportId(null);
    }
  };

  if (loading && !policy) {
    return <div className={pageClassName}><TableSkeleton /></div>;
  }

  const retentionSection = (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <SemiTitle heading={4} style={{ margin: 0 }}>候选人资料保留策略</SemiTitle>
          <SemiParagraph type="tertiary" style={{ margin: "4px 0 0" }}>自动清理只处理到期且未被保留标记的候选人，先进入可恢复删除流程。</SemiParagraph>
        </div>
        <StatusPillTag className={retentionMode === "automatic" ? "is-warning" : ""}>
          {retentionMode === "automatic" ? "自动删除" : "手动删除"}
        </StatusPillTag>
      </div>
      <fieldset disabled={savingPolicy || previewing} style={{ display: "grid", gap: "var(--space-md)", padding: 0, margin: 0, border: 0 }}>
        <SemiRadioGroup
          aria-label="候选人资料保留方式"
          disabled={savingPolicy || previewing}
          name="candidate-data-retention-mode"
          onChange={(event) => {
            const next = event.target.value as CandidateDataRetentionMode;
            if (next === "manual") setPreview(null);
            setRetentionMode(next);
          }}
          value={retentionMode}
        >
          <SemiRadio value="manual">
            <strong>手动删除</strong>
          </SemiRadio>
          <SemiRadio value="automatic">
            <strong>自动删除</strong>
          </SemiRadio>
        </SemiRadioGroup>
        {retentionMode === "automatic" && (
          <label className="field-stack" htmlFor="candidate-data-retention-days" style={{ maxWidth: "15rem" }}>
            <span className="field-label">资料保留天数</span>
            <BackofficeInput
              disabled={savingPolicy || previewing}
              id="candidate-data-retention-days"
              inputMode="numeric"
              max="3650"
              min="30"
              onChange={(value) => {
                setRetentionDays(value);
                setPreview(null);
              }}
              type="number"
              value={retentionDays}
            />
            <span className="field-help">可设置 30 至 3650 天。保存前必须先预览本次影响范围。</span>
          </label>
        )}
      </fieldset>
      {retentionMode === "automatic" && preview && (
        <SemiBanner
          type="info"
          title={previewMatchesPolicy ? "当前预览可用于保存" : "预览已过期，请重新计算"}
          description={
            <>
              <span>计算于 {formatLibraryDate(preview.calculated_at)}，不会删除任何数据。</span>
              <span style={{ display: "block", marginTop: 4 }}>
                <strong>{preview.eligible_candidate_count}</strong> 位候选人可能到期 · 关联{" "}
                <strong>{preview.eligible_resume_count}</strong> 份简历 ·{" "}
                <strong>{preview.held_candidate_count}</strong> 位被保留标记跳过
              </span>
            </>
          }
          style={{ marginTop: "var(--space-md)" }}
        />
      )}
      <div className="review-actions" style={{ justifyContent: "flex-end", marginTop: "var(--space-md)" }}>
        {retentionMode === "automatic" && (
          <BackofficeButton
            disabled={!validRetentionDays || previewing}
            icon={<Icon name="search" size={16} />}
            loading={previewing}
            onClick={() => void previewRetention()}
          >
            {previewing ? "正在预览" : "预览清理范围"}
          </BackofficeButton>
        )}
        <BackofficeButton
          disabled={savingPolicy || (retentionMode === "automatic" && !previewMatchesPolicy)}
          icon={<Icon name="check" size={16} />}
          loading={savingPolicy}
          onClick={() => void saveRetentionPolicy()}
          tone="primary"
        >
          {savingPolicy ? "正在保存" : "保存保留策略"}
        </BackofficeButton>
        <BackofficeButton
          disabled={cleaning || policy?.mode !== "automatic"}
          loading={cleaning}
          onClick={() => void runRetentionCleanup()}
          tone="danger"
        >
          {cleaning ? "正在执行" : "立即执行到期清理"}
        </BackofficeButton>
      </div>
    </section>
  );

  const recoverySection = (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <SemiTitle heading={3} style={{ margin: 0 }}>可恢复删除</SemiTitle>
          <SemiParagraph type="tertiary" style={{ margin: "4px 0 0" }}>此处仅显示删除批次与数量，不重新展示已删除候选人的姓名或原文件名。</SemiParagraph>
        </div>
        <StatusPillTag className="">{deletions.length} 条记录</StatusPillTag>
      </div>
      {deletions.length ? (
        <SemiTable
          columns={[
            {
              title: "范围",
              dataIndex: "trigger_type",
              render: (_, record) => (record as CandidateDataDeletionBatch).trigger_type === "manual_resume" ? "单份简历" : "候选人资料",
            },
            {
              title: "原因",
              dataIndex: "reason",
              render: (_, record) => candidateDataDeletionReasonLabel((record as CandidateDataDeletionBatch).reason),
            },
            {
              title: "影响",
              dataIndex: "deletion_batch_id",
              render: (_, record) => {
                const item = record as CandidateDataDeletionBatch;
                return `${item.affected_candidate_count} 位候选人 · ${item.affected_resume_count} 份简历`;
              },
            },
            {
              title: "恢复截止",
              dataIndex: "recovery_deadline_at",
              render: (_, record) => formatLibraryDate((record as CandidateDataDeletionBatch).recovery_deadline_at),
            },
            {
              title: "状态",
              dataIndex: "status",
              render: (_, record) => {
                const item = record as CandidateDataDeletionBatch;
                return (
                  <StatusPillTag className={item.restorable ? "is-warning" : ""}>
                    {item.restorable ? "可恢复" : item.status === "restored" ? "已恢复" : "已进入清理"}
                  </StatusPillTag>
                );
              },
            },
            {
              title: "",
              dataIndex: "deletion_batch_id",
              render: (_, record) => {
                const item = record as CandidateDataDeletionBatch;
                return item.restorable ? (
                  <BackofficeButton
                    disabled={restoringBatchId === item.deletion_batch_id}
                    loading={restoringBatchId === item.deletion_batch_id}
                    onClick={() => void restoreDeletion(item)}
                  >
                    {restoringBatchId === item.deletion_batch_id ? "正在恢复" : "恢复"}
                  </BackofficeButton>
                ) : null;
              },
            },
          ]}
          dataSource={deletions}
          pagination={false}
          rowKey="deletion_batch_id"
          size="small"
        />
      ) : (
        <SemiEmpty title="没有可恢复删除记录" description="从候选人抽屉删除资料后，恢复期限内的批次会显示在这里。" />
      )}
    </section>
  );

  const exportSection = (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <SemiTitle heading={3} style={{ margin: 0 }}>资料导出</SemiTitle>
          <SemiParagraph type="tertiary" style={{ margin: "4px 0 0" }}>导出文件仅在到期前可下载。候选人资料被删除后，相关导出会立即撤销。</SemiParagraph>
        </div>
        <StatusPillTag className="">{exports.length} 项任务</StatusPillTag>
      </div>
      {exports.length ? (
        <SemiTable
          columns={[
            {
              title: "内容",
              dataIndex: "item_count",
              render: (_, record) => {
                const item = record as CandidateDataExport;
                return `${item.item_count} 位候选人${item.include_originals ? " · 含原文件" : " · 不含原文件"}`;
              },
            },
            {
              title: "创建时间",
              dataIndex: "requested_at",
              render: (_, record) => formatLibraryDate((record as CandidateDataExport).requested_at),
            },
            {
              title: "有效期",
              dataIndex: "expires_at",
              render: (_, record) => {
                const expiresAt = (record as CandidateDataExport).expires_at;
                return expiresAt ? formatLibraryDate(expiresAt) : "—";
              },
            },
            {
              title: "状态",
              dataIndex: "status",
              render: (_, record) => {
                const item = record as CandidateDataExport;
                return (
                  <>
                    <StatusPillTag className={candidateDataExportStatusClass(item.status)}>
                      {candidateDataExportStatusLabel(item.status)}
                    </StatusPillTag>
                    {item.error_code && (
                      <small style={{ display: "block", marginTop: 3, color: "var(--ink-muted)", fontSize: "0.6875rem" }}>{item.error_code}</small>
                    )}
                  </>
                );
              },
            },
            {
              title: "",
              dataIndex: "export_id",
              render: (_, record) => {
                const item = record as CandidateDataExport;
                return (
                  <div style={{ display: "flex", gap: 8, whiteSpace: "nowrap" }}>
                    {item.status === "completed" && (
                      <BackofficeButton
                        disabled={downloadingExportId === item.export_id}
                        icon={downloadingExportId === item.export_id ? undefined : <Icon name="download" size={15} />}
                        loading={downloadingExportId === item.export_id}
                        onClick={() => void downloadExport(item)}
                      >
                        {downloadingExportId === item.export_id ? "正在准备" : "下载"}
                      </BackofficeButton>
                    )}
                    {["queued", "running", "retryable_failed"].includes(item.status) && (
                      <BackofficeButton
                        disabled={cancellingExportId === item.export_id}
                        loading={cancellingExportId === item.export_id}
                        onClick={() => void cancelExport(item)}
                      >
                        {cancellingExportId === item.export_id ? "正在取消" : "取消"}
                      </BackofficeButton>
                    )}
                  </div>
                );
              },
            },
          ]}
          dataSource={exports}
          pagination={false}
          rowKey="export_id"
          size="small"
        />
      ) : (
        <SemiEmpty title="还没有资料导出" description="在候选人抽屉中创建导出后，可在这里查看进度并下载。" />
      )}
    </section>
  );

  const auditSection = (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <SemiTitle heading={3} style={{ margin: 0 }}>访问与操作审计</SemiTitle>
          <SemiParagraph type="tertiary" style={{ margin: "4px 0 0" }}>查看、下载原文件与导出文件均会记录在此。</SemiParagraph>
        </div>
      </div>
      {auditEvents.length ? (
        <SemiList
          dataSource={auditEvents}
          renderItem={(item) => {
            const event = item as CandidateDataAuditEvent;
            return (
              <SemiListItem
                key={event.event_id}
                main={
                  <div style={{ display: "grid", gap: 3 }}>
                    <strong style={{ fontSize: "0.8125rem" }}>{candidateDataAuditActionLabel(event)}</strong>
                    <span style={{ color: "var(--ink-muted)", fontSize: "0.75rem" }}>{formatLibraryDate(event.created_at)}</span>
                    {event.reason_code && (
                      <small style={{ color: "var(--ink-muted)", fontSize: "0.75rem" }}>
                        {candidateDataDeletionReasonLabel(event.reason_code as CandidateDataDeletionReason)}
                      </small>
                    )}
                  </div>
                }
              />
            );
          }}
        />
      ) : (
        <SemiEmpty title="暂无审计记录" description="后续的原文件访问、导出和删除操作会显示在这里。" />
      )}
    </section>
  );

  const cleanupSection = (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <SemiTitle heading={3} style={{ margin: 0 }}>到期清理记录</SemiTitle>
          <SemiParagraph type="tertiary" style={{ margin: "4px 0 0" }}>系统只将符合策略的数据加入可恢复删除流程。</SemiParagraph>
        </div>
      </div>
      {runs.length ? (
        <SemiList
          dataSource={runs}
          renderItem={(item) => {
            const run = item as CandidateDataRetentionCleanupRun;
            return (
              <SemiListItem
                key={run.run_id}
                main={
                  <div style={{ display: "grid", gap: 3 }}>
                    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12 }}>
                      <strong style={{ fontSize: "0.8125rem" }}>{candidateDataRetentionRunStatusLabel(run.status)}</strong>
                      <span style={{ color: "var(--ink-muted)", fontSize: "0.75rem" }}>{formatLibraryDate(run.finished_at ?? run.started_at)}</span>
                    </div>
                    <small style={{ color: "var(--ink-muted)", fontSize: "0.75rem" }}>
                      扫描 {run.scanned_count}，加入删除 {run.queued_count}
                      {run.skipped_hold_count ? `，保留跳过 ${run.skipped_hold_count}` : ""}
                      {run.failed_count ? `，异常 ${run.failed_count}` : ""}
                    </small>
                  </div>
                }
              />
            );
          }}
        />
      ) : (
        <SemiEmpty title="尚未执行到期清理" description="启用自动保留后，可先预览再手动执行首次清理。" />
      )}
    </section>
  );

  const layoutClassName = embedded
    ? "candidate-data-layout is-single-column"
    : "candidate-data-layout";

  const activityLayout = (
    <div className={layoutClassName} style={fullLayoutStyle}>
      <div style={mainColumnStyle}>
        {recoverySection}
        {exportSection}
      </div>
      <aside style={sideColumnStyle}>
        {auditSection}
        {cleanupSection}
      </aside>
    </div>
  );

  const standaloneLayout = (
    <div className={layoutClassName} style={fullLayoutStyle}>
      <div style={mainColumnStyle}>
        {retentionSection}
        {recoverySection}
        {exportSection}
      </div>
      <aside style={sideColumnStyle}>
        {auditSection}
        {cleanupSection}
      </aside>
    </div>
  );

  return (
    <div className={pageClassName}>
      <header className="page-heading">
        <div>
          <SemiTitle heading={embedded ? 2 : 1} style={{ margin: 0 }}>
            {embedded ? "候选人数据与保留" : "数据保留与恢复"}
          </SemiTitle>
          <SemiParagraph type="tertiary" style={{ margin: "6px 0 0" }}>
            {embedded
              ? "先设置候选人资料的保留策略；可在“操作与记录”中处理可恢复删除、导出和审计记录。"
              : "在工作区内管理候选人资料的保留期限、可恢复删除、导出文件和原文件访问记录。所有清理操作都会先进入恢复期，不会立即永久清除数据。"}
          </SemiParagraph>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "flex-end" }}>
          <BackofficeButton
            disabled={refreshing}
            icon={<Icon name="refresh" size={16} />}
            loading={refreshing}
            onClick={() => void load(false)}
          >
            {refreshing ? "正在刷新" : "刷新记录"}
          </BackofficeButton>
          <BackofficeButton onClick={onOpenLibrary}>返回简历库</BackofficeButton>
        </div>
      </header>

      {error && <SemiBanner type="danger" title={error} style={{ marginBottom: "var(--space-md)" }} />}

      <Suspense fallback={<p>加载数据管理…</p>}>
        {embedded ? (
          <SemiTabs
            activeKey={embeddedSection}
            onChange={(key) => setEmbeddedSection(key as CandidateDataEmbeddedSection)}
            type="button"
          >
            {candidateDataEmbeddedSections.map((section) => (
              <SemiTabPane
                icon={<Icon name={section.icon} size={16} />}
                itemKey={section.id}
                key={section.id}
                tab={section.label}
              >
                {section.id === "retention" ? retentionSection : activityLayout}
              </SemiTabPane>
            ))}
          </SemiTabs>
        ) : standaloneLayout}
      </Suspense>
    </div>
  );
}
