import { expect, test } from "@playwright/test";

import { e2eControl, registerAndVerify, seedWorkspaceFixture } from "./helpers";

interface ResumeDetailFixture {
  candidate_id: string;
}

interface RecruitingJobFixture {
  job_id: string;
  title: string;
}

interface RecruitingJobListFixture {
  items: RecruitingJobFixture[];
}

interface RecruitingWorkflowFixture {
  versions: Array<{ workflow_version_id: string }>;
}

/**
 * Exercises the recruiter-owned browser flow against the local API. The
 * application is created through the same human action API used by the
 * candidate drawer, then the browser advances it through the workbench.
 */
test("职位管理展示应聘快照，并由人工推进阶段", async ({ page }) => {
  await registerAndVerify(page, "recruiting-core");
  const fixture = await seedWorkspaceFixture(page);
  const resumeId = fixture.resume_ids[0];
  if (!resumeId) throw new Error("Expected a seeded resume.");

  const resume = await e2eControl<ResumeDetailFixture>(page, `/v1/resumes/${resumeId}`);
  const jobs = await e2eControl<RecruitingJobListFixture>(page, "/v1/recruiting/jobs");
  const job = jobs.items.find((item) => item.title === "E2E 后端工程师");
  if (!job) throw new Error("Expected a seeded recruiting job.");

  await e2eControl(page, `/v1/recruiting/jobs/${job.job_id}/applications`, {
    method: "POST",
    body: { candidate_id: resume.candidate_id },
  });
  const revisedWorkflow = await e2eControl<RecruitingWorkflowFixture>(
    page,
    "/v1/recruiting/workflows",
    {
      method: "POST",
      body: {
        name: "E2E revised flow",
        stages: [
          { stage_key: "review", name: "New review", stage_type: "active", sort_order: 10 },
          { stage_key: "hired", name: "Hired", stage_type: "hired", sort_order: 90 },
          { stage_key: "rejected", name: "Rejected", stage_type: "rejected", sort_order: 100 },
        ],
      },
    },
  );
  const revisedWorkflowVersionId = revisedWorkflow.versions[0]?.workflow_version_id;
  if (!revisedWorkflowVersionId) throw new Error("Expected the revised workflow version.");
  await e2eControl(page, `/v1/recruiting/jobs/${job.job_id}`, {
    method: "PATCH",
    body: { recruiting_workflow_version_id: revisedWorkflowVersionId },
  });

  await page.reload();
  await page.getByRole("button", { name: "职位管理", exact: true }).click();

  await expect(page.getByRole("heading", { name: "职位管理", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "E2E 后端工程师", exact: true })).toBeVisible();
  const candidateCard = page.locator(".recruiting-application-card").filter({
    hasText: "E2E 推荐候选人",
  });
  await expect(candidateCard).toBeVisible();
  await expect(candidateCard.getByText("JD v1", { exact: true })).toBeVisible();
  await expect(candidateCard.getByText("简历事实 v1", { exact: true })).toBeVisible();

  const transitionRequest = page.waitForResponse((response) => (
    response.request().method() === "POST" &&
    /\/v1\/recruiting\/applications\/[^/]+\/advance$/.test(new URL(response.url()).pathname)
  ));
  await candidateCard.getByRole("button", { name: "推进", exact: true }).click();
  await transitionRequest;

  await expect(page.locator(".recruiting-stage-lane").filter({ hasText: "初筛" })
    .getByText("E2E 推荐候选人", { exact: true })).toBeVisible();
  await candidateCard.getByRole("button", { name: "流转记录", exact: true }).click();
  await expect(candidateCard.getByText("待筛选 → 初筛", { exact: true })).toBeVisible();
});
