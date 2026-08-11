/**
 * Shared "completed score" cell, used by both the resume library and the
 * smart-match score leaderboard so the two surfaces render a finished score
 * the same way (score + `/ 100` + optional review notice).
 */
export function scoreStatusNotice(status: string | null): string | null {
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

export function ScoreDisplay({
  total,
  status,
  templateName,
}: {
  total: number;
  status: string | null;
  templateName: string | null;
}) {
  const notice = scoreStatusNotice(status);
  return (
    <div className="library-score" title={templateName ?? "评分模板"}>
      <strong>{total.toFixed(1)}</strong>
      <span>/ 100</span>
      {notice && <small>{notice}</small>}
    </div>
  );
}
