import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { Icon } from "../../icons";
import type { JobApplication, RecruitingJob } from "../../types";

type ToastKind = "success" | "error";

const applicationStatusLabel: Record<JobApplication["status"], string> = {
  active: "进行中",
  hired: "已录用",
  rejected: "已淘汰",
  withdrawn: "已撤回",
};

/**
 * Candidate×Job records are created here by a recruiter on an explicit click.
 * This panel intentionally has no model suggestions or automatic movement.
 */
export function CandidateRecruitingPanel({
  candidateId,
  formatError,
  notify,
}: {
  candidateId: string | null;
  formatError: (error: unknown) => string;
  notify: (kind: ToastKind, message: string) => void;
}) {
  const [jobs, setJobs] = useState<RecruitingJob[]>([]);
  const [applications, setApplications] = useState<JobApplication[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!candidateId) {
      setJobs([]);
      setApplications([]);
      setSelectedJobId("");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [jobResponse, applicationResponse] = await Promise.all([
        api.listRecruitingJobs(),
        api.listCandidateJobApplications(candidateId),
      ]);
      const currentActiveJobIds = new Set(
        applicationResponse.items
          .filter((item) => item.is_current && item.status === "active")
          .map((item) => item.job_id),
      );
      const availableJobs = jobResponse.items.filter(
        (job) => job.recruiting_status === "open" && !currentActiveJobIds.has(job.job_id),
      );
      setJobs(availableJobs);
      setApplications(applicationResponse.items);
      setSelectedJobId((current) =>
        availableJobs.some((job) => job.job_id === current)
          ? current
          : availableJobs[0]?.job_id ?? "",
      );
    } catch (loadError) {
      setJobs([]);
      setApplications([]);
      setSelectedJobId("");
      setError(formatError(loadError));
    } finally {
      setLoading(false);
    }
  }, [candidateId, formatError]);

  useEffect(() => {
    void load();
  }, [load]);

  const addToJob = async () => {
    if (!candidateId || !selectedJobId || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.createJobApplication(selectedJobId, { candidate_id: candidateId });
      notify("success", "候选人已加入岗位流程");
      await load();
    } catch (submitError) {
      const message = formatError(submitError);
      setError(message);
      notify("error", message);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading && !applications.length && !jobs.length) {
    return <div className="candidate-recruiting-panel is-loading"><i className="spinner" />正在加载岗位记录</div>;
  }

  return (
    <section aria-label="候选人应聘记录" className="candidate-recruiting-panel">
      <div className="candidate-recruiting-add">
        <label className="field-label" htmlFor="candidate-recruiting-job">加入岗位</label>
        <div className="candidate-recruiting-add-row">
          <select
            className="select-field"
            disabled={!jobs.length || submitting}
            id="candidate-recruiting-job"
            onChange={(event) => setSelectedJobId(event.target.value)}
            value={selectedJobId}
          >
            {jobs.length ? (
              jobs.map((job) => (
                <option key={job.job_id} value={job.job_id}>
                  {job.title}{job.department ? ` · ${job.department}` : ""}
                </option>
              ))
            ) : (
              <option value="">暂无可加入的招聘中岗位</option>
            )}
          </select>
          <button
            className="button button-primary"
            disabled={!selectedJobId || submitting}
            onClick={() => void addToJob()}
            type="button"
          >
            {submitting ? <><i className="spinner" />加入中</> : <><Icon name="plus" size={16} />加入岗位</>}
          </button>
        </div>
      </div>

      {error && <p className="library-error candidate-recruiting-error" role="alert">{error}</p>}

      <div className="candidate-recruiting-history-heading">
        <h3>应聘记录</h3>
        <button className="text-button" disabled={loading} onClick={() => void load()} type="button">
          <Icon name="refresh" size={15} />刷新
        </button>
      </div>
      {applications.length ? (
        <ul className="candidate-recruiting-history">
          {applications.map((application) => (
            <li key={application.application_id}>
              <div>
                <strong>{application.job_title}</strong>
                <span>{application.current_stage_name}</span>
              </div>
              <div className="candidate-recruiting-statuses">
                <span className={`status-pill is-${application.status}`}>
                  {applicationStatusLabel[application.status]}
                </span>
                {application.round_number > 1 && <span className="tag">第 {application.round_number} 轮</span>}
                {!application.is_current && <span className="tag">历史</span>}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <div className="candidate-recruiting-empty">
          <Icon name="briefcase" size={20} />暂无应聘记录
        </div>
      )}
    </section>
  );
}
