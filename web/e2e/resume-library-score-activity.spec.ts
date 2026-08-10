import { expect, test } from "@playwright/test";

import { registerAndVerify, seedWorkspaceFixture } from "./helpers";

test("评分生成中显示动画，完成后变为分数", async ({ page }) => {
  await registerAndVerify(page, "resume-library-score-activity");
  await seedWorkspaceFixture(page);

  let libraryPolls = 0;
  await page.route("**/v1/resume-library**", async (route) => {
    const response = await route.fetch();
    const payload = (await response.json()) as {
      items?: Array<Record<string, unknown>>;
    };
    libraryPolls += 1;
    const scoreStillGenerating = libraryPolls <= 2;
    await route.fulfill({
      response,
      json: {
        ...payload,
        items: (payload.items ?? []).map((item) => ({
          ...item,
          score_task_state: scoreStillGenerating ? "running" : "none",
          score_total: scoreStillGenerating ? null : 88,
          score_status: scoreStillGenerating ? null : "succeeded",
          score_template_name: scoreStillGenerating ? null : "E2E 评分规则",
          score_created_at: scoreStillGenerating
            ? null
            : "2026-08-10T00:00:00+00:00",
        })),
      },
    });
  });

  await page.getByRole("button", { name: "简历库", exact: true }).click();

  const activity = page.locator(".library-score-activity");
  await expect(activity.first()).toBeVisible();
  await expect(
    page.getByText("评分生成中…", { exact: true }).first(),
  ).toBeVisible();
  const dot = activity.first().locator(".library-score-activity-dot");
  await expect(dot).toBeVisible();
  await expect(dot).toHaveAttribute("aria-hidden", "true");
  await expect(activity.first()).toHaveAttribute("role", "status");

  // 前 2 次轮询返回 running，之后返回 none，动画应消失、回到分数数字。
  await expect(activity.first()).not.toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".library-score strong").first()).toHaveText("88.0");
});
