import { expect, test } from "@playwright/test";

import { registerAndVerify, seedWorkspaceFixture } from "./helpers";

test("智能匹配左右并排两个表，通用评分可生成中并落分", async ({ page }) => {
  await registerAndVerify(page, "job-match-score-loop");
  await seedWorkspaceFixture(page);

  // 评分榜生成中 → 完成后落分：前 2 次轮询返回 running，之后返回 none + 88 分。
  let leaderboardPolls = 0;
  await page.route("**/v1/job-versions/**/score-leaderboard**", async (route) => {
    const response = await route.fetch();
    const payload = (await response.json()) as {
      items?: Array<Record<string, unknown>>;
      batch?: Record<string, unknown> | null;
    };
    leaderboardPolls += 1;
    const stillGenerating = leaderboardPolls <= 2;
    await route.fulfill({
      response,
      json: {
        ...payload,
        batch: stillGenerating
          ? {
              batch_id: "e2e-score-batch",
              status: "running",
              total_count: 1,
              completed_count: 0,
            }
          : null,
        items: (payload.items ?? []).map((item, index) => ({
          ...item,
          score_task_state: stillGenerating ? "running" : "none",
          score_total: stillGenerating ? null : index === 0 ? 88 : null,
          score_status: stillGenerating ? null : index === 0 ? "succeeded" : null,
        })),
      },
    });
  });

  await page.getByRole("button", { name: "智能匹配", exact: true }).click();

  // 左右并排两个表。
  const matchTable = page.locator(".match-leaderboard");
  const scoreTable = page.locator(".score-leaderboard");
  await expect(matchTable).toBeVisible();
  await expect(scoreTable).toBeVisible();
  await expect(page.locator(".score-loop-tables")).toBeVisible();

  // 评分表生成中动画。
  const activity = scoreTable.locator(".score-activity").first();
  await expect(activity).toBeVisible();
  await expect(activity).toHaveAttribute("role", "status");
  await expect(scoreTable.getByText("评分生成中…").first()).toBeVisible();
  const dot = activity.locator(".score-activity-dot");
  await expect(dot).toHaveAttribute("aria-hidden", "true");

  // 完成后动画消失、回到分数数字（共享 ScoreDisplay 渲染 .library-score）。
  await expect(activity).not.toBeVisible({ timeout: 10_000 });
  await expect(
    scoreTable.locator(".library-score strong").first(),
  ).toHaveText("88.0");
});
