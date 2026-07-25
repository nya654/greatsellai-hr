import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Icon } from "../../icons";
import type {
  RecruitingAgentCandidate,
  RecruitingAgentSearchSummary,
} from "../../types";

function agentMarkdownUrlTransform(url: string): string {
  const normalized = defaultUrlTransform(url);
  return /^(?:https?:|mailto:)/i.test(normalized) ? normalized : "";
}

export function AgentMarkdown({ content }: { content: string }) {
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

export function AgentSearchSummaryPanel({
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

export function AgentCandidateCard({
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
