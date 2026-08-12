import type { ScoreLeaderboard as ScoreLeaderboardData } from "../../types";
import { Icon } from "../../icons";
import { ScoreDisplay } from "../../backoffice/ui/ScoreDisplay";

function scoreTaskInProgress(state: string): boolean {
  return state === "queued" || state === "running";
}

export function ScoreLeaderboard({
  board,
  loading,
  templateName,
}: {
  board: ScoreLeaderboardData;
  loading: boolean;
  templateName: string | null;
}) {
  const batchActive =
    board.batch?.status === "queued" || board.batch?.status === "running";
  return (
    <section className="panel score-leaderboard">
      <div className="panel-heading">
        <div>
          <h2>通用评分</h2>
          <p>
            {templateName
              ? `模板：${templateName}`
              : "按所选评分模板对合格候选人打分"}
          </p>
        </div>
        {batchActive && board.batch ? (
          <span className="status-pill" role="status">
            评分任务进行中 {board.batch.completed_count}/{board.batch.total_count}
          </span>
        ) : (
          <span className="status-pill">{board.items.length} 名候选人</span>
        )}
      </div>
      {loading ? (
        <div
          aria-busy="true"
          aria-label="正在加载通用评分"
          className="match-results-loading"
        >
          <span className="skeleton match-results-loading-card" />
          <span className="skeleton match-results-loading-card" />
        </div>
      ) : board.items.length ? (
        <div className="match-table-wrap">
          <table className="match-table">
            <thead>
              <tr>
                <th scope="col">排名</th>
                <th scope="col">候选人</th>
                <th scope="col">通用分</th>
                <th scope="col">状态</th>
              </tr>
            </thead>
            <tbody>
              {board.items.map((item, index) => (
                <ScoreRow
                  key={item.resume_id}
                  item={item}
                  rank={index + 1}
                  templateName={templateName}
                />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty-state match-empty-state">
          <div className="empty-state-inner">
            <span className="empty-glyph">
              <Icon name="activity" size={23} />
            </span>
            <h2>尚无通用评分</h2>
            <p>发起岗位评估时会自动为同一批候选人补分。</p>
          </div>
        </div>
      )}
    </section>
  );
}

function ScoreRow({
  item,
  rank,
  templateName,
}: {
  item: ScoreLeaderboardData["items"][number];
  rank: number;
  templateName: string | null;
}) {
  const inProgress = scoreTaskInProgress(item.score_task_state);
  return (
    <tr className="score-candidate-row">
      <td className="score-rank">
        <span className="match-rank-number">{rank}</span>
      </td>
      <td>
        <strong>{item.candidate_display_name?.trim() || "未命名候选人"}</strong>
      </td>
      <td>
        {item.score_total !== null ? (
          <ScoreDisplay
            total={item.score_total}
            status={item.score_status}
            templateName={templateName}
          />
        ) : inProgress ? (
          <span className="score-activity" role="status" aria-label="评分生成中">
            <span className="score-activity-dot" aria-hidden="true" />
            <span className="score-activity-copy">评分生成中…</span>
          </span>
        ) : (
          <span className="score-muted">尚无通用评分</span>
        )}
      </td>
      <td>{scoreStatusLabel(item.score_status)}</td>
    </tr>
  );
}

function scoreStatusLabel(
  status: ScoreLeaderboardData["items"][number]["score_status"],
): string {
  if (status === "succeeded") return "已完成";
  if (status === "needs_review") return "待人工复核";
  if (status === "overridden") return "已人工覆盖";
  return "—";
}
