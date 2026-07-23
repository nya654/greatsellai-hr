import { expect, test } from "@playwright/test";

import {
  e2eResumePdf,
  e2eControl,
  logout,
  registerAndVerify,
  seedWorkspaceFixture,
} from "./helpers";

interface PasswordResetDelivery {
  recipient: string;
  reset_url: string;
  expires_minutes: number;
}

interface PasswordResetDeliveriesResponse {
  deliveries: PasswordResetDelivery[];
}

test.describe("招聘工作台关键路径", () => {
  test("注册验证后可退出并重新登录", async ({ page }) => {
    const email = await registerAndVerify(page, "registration-login");
    await page.getByRole("button", { name: "退出登录" }).click();
    await expect(page.getByRole("button", { name: "登录工作台" })).toBeVisible();
    await page.locator("#login-email").fill(email);
    await page.locator("#login-password").fill("E2E-password-2026");
    await page.getByRole("button", { name: "登录工作台" }).click();
    await expect(page.getByRole("button", { name: "退出登录" })).toBeVisible();
  });

  test("已验证用户可通过真实浏览器路径找回并使用新密码", async ({ page }) => {
    const email = await registerAndVerify(page, "password-reset");
    const newPassword = "E2E-password-reset-2026";

    await logout(page);
    await page.goto("/forgot-password");
    await page.locator("#reset-email").fill(email);
    await page.getByRole("button", { name: "获取重置指引" }).click();
    await expect(page.getByRole("heading", { name: "请查看邮箱" })).toBeVisible();

    const deliveryPath = `/__e2e__/password-reset-deliveries?recipient=${encodeURIComponent(email)}`;
    const controlHeaders = {
      "X-E2E-Control-Token": process.env.E2E_CONTROL_TOKEN ?? "local-playwright-control",
    };
    await expect
      .poll(async () => {
        const response = await e2eControl<PasswordResetDeliveriesResponse>(page, deliveryPath, {
          headers: controlHeaders,
        });
        return response.deliveries.length;
      })
      .toBeGreaterThan(0);
    const deliveries = await e2eControl<PasswordResetDeliveriesResponse>(page, deliveryPath, {
      headers: controlHeaders,
    });
    const delivery = deliveries.deliveries.at(-1);
    if (!delivery) throw new Error("Expected a local password reset delivery.");
    const resetUrl = new URL(delivery.reset_url);

    await page.goto(`${resetUrl.pathname}${resetUrl.search}`);
    await page.locator("#reset-password").fill(newPassword);
    await page.locator("#reset-password-confirmation").fill(newPassword);
    await page.getByRole("button", { name: "保存新密码" }).click();
    await expect(page.getByRole("heading", { name: "新密码已设置" })).toBeVisible();

    await page.getByRole("link", { name: "前往登录" }).click();
    await expect(page.getByRole("button", { name: "登录工作台" })).toBeVisible();
    await page.locator("#login-email").fill(email);
    await page.locator("#login-password").fill("E2E-password-2026");
    await page.getByRole("button", { name: "登录工作台" }).click();
    await expect(page.getByRole("alert")).toHaveText("邮箱或密码不正确，请重试。");

    await page.locator("#login-password").fill(newPassword);
    await page.getByRole("button", { name: "登录工作台" }).click();
    await expect(page.getByRole("button", { name: "退出登录" })).toBeVisible();
  });

  test("上传页面通过真实 multipart 请求保存 PDF 并进入 AI 队列", async ({ page }) => {
    await registerAndVerify(page, "upload");
    await page.getByRole("button", { name: "上传简历", exact: true }).first().click();
    await expect(page.getByRole("heading", { name: "批量上传简历" })).toBeVisible();

    await page.locator('input[type="file"]').setInputFiles({
      name: "e2e-resume.pdf",
      mimeType: "application/pdf",
      buffer: e2eResumePdf(),
    });
    await expect(page.getByText("e2e-resume.pdf")).toBeVisible();
    await page.getByRole("button", { name: /上传 1 份并自动提取/ }).click();
    await expect(page.getByText("简历已保存，AI 正在提取候选人姓名和结构化事实。")).toBeVisible();
    await expect(page.getByText("原件已保存，AI 正在排队提取候选人姓名和结构化事实")).toBeVisible();
    await page.getByRole("button", { name: "查看状态" }).click();
    await expect(page.getByRole("dialog", { name: /简历详情/ })).toBeVisible();

    const autoPreviewGrant = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.status() === 200 &&
        /\/v1\/resumes\/[^/]+\/file-access$/.test(new URL(response.url()).pathname),
    );
    await page.getByRole("tab", { name: "原始文件" }).click();
    await autoPreviewGrant;
    const originalPreview = page.getByTitle("e2e-resume.pdf 原始文件");
    await expect(originalPreview).toBeVisible();
    await expect(originalPreview).toHaveAttribute("src", /^blob:/);
    await expect(page.getByRole("button", { name: "重新加载预览" })).toBeVisible();
  });

  test("评分不继承候选人，招聘详情按 JD 批量评估", async ({ page }) => {
    await registerAndVerify(page, "screen-score-match");
    const fixture = await seedWorkspaceFixture(page);
    await page.reload();

    await page.getByRole("button", { name: "筛选工作台", exact: true }).click();
    await expect(page.getByLabel("综合评分排序规则")).not.toHaveValue("");
    const institutionTypes = page.getByLabel("院校类型条件");
    await expect(institutionTypes).toBeVisible();
    await expect(page.getByLabel("院校类型快捷筛选")).toHaveCount(0);
    const institution985 = institutionTypes.getByRole("checkbox", { name: "985" });
    await institution985.check();
    await expect(institution985).toBeChecked();
    await page.locator("#school-name").fill("清华");
    await page.getByRole("button", { name: "应用筛选条件" }).click();
    await expect(page.getByText("E2E 推荐候选人")).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "学历 / 院校", exact: true })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "经历", exact: true })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "核心技能", exact: true })).toBeVisible();
    await expect(page.getByText("e2e-fixture-1.pdf", { exact: true })).toHaveCount(0);
    await expect(page.getByText("正式工作年限待核实").first()).toBeVisible();
    await expect(page.getByText("未设门槛")).toHaveCount(0);

    await page.getByRole("button", { name: "查看 E2E 推荐候选人 的评分详情" }).click();
    await expect(page.getByRole("tab", { name: "评分详情" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByRole("heading", { name: "评分详情", exact: true })).toBeVisible();
    await expect(page.getByText("AI 评分理由", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("简历事实依据", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("待确认项", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "关闭简历详情" }).click();

    await page.getByRole("button", { name: "评分模板", exact: true }).click();
    await expect(page.getByRole("heading", { name: "通用评分模板", exact: true })).toBeVisible();
    await expect(page.locator("#main-content").getByText(/当前简历：|尚未选择简历/)).toHaveCount(0);
    await expect(page.locator("#main-content").getByRole("button", { name: /生成当前候选人评分/ })).toHaveCount(0);
    await page.locator("#template-name").fill("E2E 批量评分规则");
    await page.getByRole("button", { name: "创建评分模板" }).click();
    await expect(page.getByText("评分模板“E2E 批量评分规则”已创建。")).toBeVisible();
    const genericScoreRequest = page.waitForRequest((request) => {
      const { pathname } = new URL(request.url());
      return request.method() === "POST" && /^\/v1\/score-templates\/[^/]+\/score-all$/.test(pathname);
    });
    await page.getByRole("button", { name: "生成全部简历的通用评分" }).click();
    await genericScoreRequest;
    await expect(page.getByRole("heading", { name: "批量评分任务" })).toBeVisible();

    await page.getByRole("button", { name: "招聘详情", exact: true }).click();
    await expect(page.getByRole("heading", { name: "招聘详情", exact: true })).toBeVisible();
    await expect(page.locator("#main-content").getByText("当前候选人", { exact: true })).toHaveCount(0);
    await expect(page.locator("#main-content").getByRole("button", { name: "运行岗位匹配" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "候选人评估结果" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "推荐候选人" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "待核实候选人" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "明确不匹配" })).toBeVisible();
    await expect(page.getByText("E2E 推荐候选人", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("E2E 待核实候选人", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("E2E 不匹配候选人", { exact: true }).first()).toBeVisible();

    const forbiddenCandidateRequests: string[] = [];
    const observeCandidateRequests = (request: import("@playwright/test").Request) => {
      const { pathname } = new URL(request.url());
      if (
        request.method() === "POST" &&
        /^\/v1\/resumes\/[^/]+\/(scores|job-matches)$/.test(pathname)
      ) {
        forbiddenCandidateRequests.push(pathname);
      }
    };
    page.on("request", observeCandidateRequests);
    try {
      const jobBatchResponse = page.waitForResponse((response) => {
        const { pathname } = new URL(response.url());
        return response.request().method() === "POST" &&
          pathname === `/v1/job-versions/${fixture.job_version_id}/match-all`;
      });
      await page.getByRole("button", { name: "开始岗位评分（全部可匹配简历）" }).click();
      const response = await jobBatchResponse;
      expect(response.ok()).toBeTruthy();
      const batch = await response.json() as { job_version_id: string };
      expect(batch.job_version_id).toBe(fixture.job_version_id);
      expect(forbiddenCandidateRequests).toEqual([]);
    } finally {
      page.off("request", observeCandidateRequests);
    }
  });

  test("简历详情只保留直接删除当前简历的入口", async ({ page }) => {
    await registerAndVerify(page, "simple-resume-delete");
    await seedWorkspaceFixture(page);

    await page.getByRole("button", { name: "筛选工作台", exact: true }).click();
    await page.locator("#school-name").fill("清华");
    await page.getByRole("button", { name: "应用筛选条件" }).click();
    await page.getByRole("button", { name: "查看 E2E 推荐候选人 的评分详情" }).click();

    const drawer = page.getByRole("dialog", { name: "E2E 推荐候选人 的简历详情" });
    const deleteButton = drawer.getByRole("button", { name: "删除简历", exact: true });
    await expect(deleteButton).toBeVisible();
    await expect(drawer.getByText("候选人数据管理", { exact: true })).toHaveCount(0);
    await expect(drawer.getByText("导出候选人资料", { exact: true })).toHaveCount(0);

    const deleteRequest = page.waitForRequest((request) => {
      const { pathname } = new URL(request.url());
      return request.method() === "DELETE" && /^\/v1\/resumes\/[^/]+$/.test(pathname);
    });
    page.once("dialog", async (dialog) => {
      expect(dialog.type()).toBe("confirm");
      expect(dialog.message()).toContain("删除当前简历");
      await dialog.accept();
    });
    await deleteButton.click();

    const request = await deleteRequest;
    expect(request.postDataJSON()).toEqual({
      reason: "other",
      other_note: "simple_resume_delete",
    });
    await expect(page.getByText(/当前简历版本已移出工作台/)).toBeVisible();
    await expect(drawer).toBeHidden();
  });

  test("窄屏仍可展开筛选条件并应用", async ({ page }) => {
    await registerAndVerify(page, "mobile-filter");
    await page.setViewportSize({ width: 390, height: 844 });

    await page.getByRole("button", { name: "筛选工作台", exact: true }).click();
    const toggle = page.getByRole("button", { name: "展开筛选", exact: true });
    await expect(toggle).toBeVisible();
    await expect(page.locator("#school-name")).not.toBeVisible();

    await toggle.click();
    await expect(page.locator("#school-name")).toBeVisible();
    await page.locator("#school-name").fill("清华");
    await page.getByRole("button", { name: "应用筛选条件", exact: true }).click();
    await expect(page.getByRole("button", { name: "展开筛选", exact: true })).toBeVisible();
  });

  test("招聘助手打开后聚焦关闭键，关闭后返回触发按钮", async ({ page }) => {
    await registerAndVerify(page, "agent-focus");

    const trigger = page.getByRole("button", { name: "招聘助手", exact: true });
    await trigger.click();
    const dialog = page.getByRole("dialog", { name: "招聘助手" });
    const closeButton = dialog.getByRole("button", { name: "关闭招聘助手" });
    await expect(dialog).toBeVisible();
    await expect(closeButton).toBeFocused();
    await expect(dialog.getByText(/当前候选人：|未选择候选人/)).toHaveCount(0);
    await expect(dialog.getByLabel("常用提问")).toHaveCount(0);
    await expect(dialog.getByLabel("向招聘助手提问")).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(trigger).toBeFocused();
  });

  test("邮箱通道保存后同步请求只进入后台队列", async ({ page }) => {
    await registerAndVerify(page, "mailbox");
    await page.getByRole("button", { name: "邮箱入库", exact: true }).click();
    await expect(page.getByRole("heading", { name: "邮箱附件入库" })).toBeVisible();
    await page.locator("#mailbox-display-name").fill("E2E 收件通道");
    await page.locator("#imap-address").fill("e2e-inbox@example.test");
    await page.locator("#imap-password").fill("e2e-local-imap-authorization-code");
    await page.getByRole("button", { name: /^(保存收件通道|创建并开始接收)$/ }).click();
    await expect(page.getByText("收件通道已创建，只会入库从现在起收到的附件。")).toBeVisible();
    await page.getByRole("button", { name: "同步此通道" }).click();
    await expect(page.getByText("已加入后台同步队列。")).toBeVisible();
  });
});
