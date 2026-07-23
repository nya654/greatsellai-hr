import { expect, test } from "@playwright/test";

const organizationId = "org-internal-alpha";
const organizationName = "星河科技";
const fastOrganizationId = "org-internal-bravo";
const fastOrganizationName = "晨星科技";
const secondPageOrganizationId = "org-internal-second-page";
const secondPageOrganizationName = "第二页公司";

function organizationSummary(organization_id: string, name: string) {
  return {
    organization_id,
    name,
    plan_id: null,
    plan_code: "basic",
    plan_name: "基础版",
    plan_status: "trial",
    trial_started_at: "2026-07-01T00:00:00Z",
    trial_ends_at: "2026-08-01T00:00:00Z",
    member_count: 1,
    active_member_count: 1,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
  };
}

function json(route: import("@playwright/test").Route, body: unknown) {
  return route.fulfill({
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

const tokenFilterKeys = [
  "organization_id",
  "feature",
  "provider_slug",
  "model_slug",
  "started_at_from",
  "started_at_to",
] as const;

function tokenTotalFor(url: URL) {
  const filterValue = tokenFilterKeys.map((key) => url.searchParams.get(key) ?? "").join("|");
  return [...filterValue].reduce((hash, character) => (
    ((hash * 31) + character.charCodeAt(0)) % 900_000
  ), 7) + 10_000;
}

function tokenUsageSummary(url: URL) {
  const totalTokens = tokenTotalFor(url);
  const inputTokens = Math.floor(totalTokens * 0.55);
  const cachedReadTokens = Math.floor(totalTokens * 0.1);
  const cachedWriteTokens = Math.floor(totalTokens * 0.05);
  const outputTokens = totalTokens - inputTokens - cachedReadTokens - cachedWriteTokens;
  return [{
    organization_id: url.searchParams.get("organization_id") ?? organizationId,
    feature: url.searchParams.get("feature") ?? "resume_summary",
    provider_slug: url.searchParams.get("provider_slug") ?? "demo-provider",
    model_slug: url.searchParams.get("model_slug") ?? "demo-model",
    invocation_count: 2,
    costed_invocation_count: 0,
    unavailable_cost_invocation_count: 2,
    potentially_billed_invocation_count: 2,
    reported_cost_cny_micros: 0,
    token_usage_invocation_count: 2,
    input_tokens: inputTokens,
    cached_read_input_tokens: cachedReadTokens,
    cached_write_input_tokens: cachedWriteTokens,
    output_tokens: outputTokens,
    reasoning_tokens: 0,
    total_tokens: totalTokens,
    known_run_count: 2,
    partial_run_count: 0,
    unavailable_run_count: 0,
  }];
}

function trendTokenTotalFor(url: URL) {
  return tokenTotalFor(url) + (url.searchParams.get("granularity") === "day" ? 1_000 : 0);
}

function tokenUsageTrend(url: URL) {
  const totalTokens = trendTokenTotalFor(url);
  const inputTokens = Math.floor(totalTokens * 0.55);
  const cachedReadTokens = Math.floor(totalTokens * 0.1);
  const cachedWriteTokens = Math.floor(totalTokens * 0.05);
  const outputTokens = totalTokens - inputTokens - cachedReadTokens - cachedWriteTokens;
  return [{
    bucket_started_at: url.searchParams.get("started_at_from") ?? new Date().toISOString(),
    time_zone: url.searchParams.get("time_zone") ?? "UTC",
    provider_slug: url.searchParams.get("provider_slug") ?? "demo-provider",
    model_slug: url.searchParams.get("model_slug") ?? "demo-model",
    invocation_count: 2,
    token_usage_invocation_count: 2,
    input_tokens: inputTokens,
    cached_read_input_tokens: cachedReadTokens,
    cached_write_input_tokens: cachedWriteTokens,
    output_tokens: outputTokens,
    reasoning_tokens: 0,
    total_tokens: totalTokens,
  }];
}

test("平台 AI 运营按公司选择并保持内部工作区筛选", async ({ page }) => {
  const organizations = [
    organizationSummary(organizationId, organizationName),
    ...Array.from({ length: 99 }, (_, index) => organizationSummary(`org-internal-${index}`, `测试公司 ${index}`)),
    organizationSummary(secondPageOrganizationId, secondPageOrganizationName),
  ];
  const organizationOffsets: number[] = [];

  await page.route("**/v1/auth/session", (route) => json(route, {
    authenticated: true,
    login_required: false,
    is_platform_admin: true,
    email_verified: true,
    email_verification_required: false,
    user: {
      user_id: "platform-admin",
      display_name: "Platform Admin",
      email: "platform-admin@example.test",
    },
    organization: null,
    role: null,
    plan: null,
    trial: null,
  }));
  await page.route("**/v1/platform/organizations**", (route) => {
    const url = new URL(route.request().url());
    const limit = Number(url.searchParams.get("limit") ?? "100");
    const offset = Number(url.searchParams.get("offset") ?? "0");
    organizationOffsets.push(offset);
    return json(route, {
      items: organizations.slice(offset, offset + limit),
      total: organizations.length,
      limit,
      offset,
    });
  });
  await page.route("**/v1/platform/ai/usage/runs**", (route) => json(route, [
    {
      run_id: "run-alpha",
      organization_id: organizationId,
      feature: "ai_summary",
      service_kind: "model",
      status: "succeeded",
      started_at: "2026-07-23T00:00:00Z",
      finished_at: "2026-07-23T00:00:01Z",
      total_cost_cny_micros: 0,
      cost_status: "known",
      invocation_count: 1,
      potentially_billed_invocation_count: 1,
      token_usage_invocation_count: 1,
      total_tokens: 100,
    },
  ]));
  await page.route("**/v1/platform/ai/usage/summary**", (route) => json(route, []));
  await page.route("**/v1/platform/ai/providers", (route) => json(route, []));
  await page.route("**/v1/platform/ai/models", (route) => json(route, []));
  await page.route("**/v1/platform/ai/routes", (route) => json(route, []));

  await page.goto("/platform/ai");

  const companySelect = page.getByLabel("公司", { exact: true });
  await expect(companySelect).toBeVisible();
  await expect.poll(() => organizationOffsets).toContain(100);
  await expect(companySelect.locator(`option[value="${organizationId}"]`)).toHaveText(organizationName);
  await expect(companySelect.locator(`option[value="${secondPageOrganizationId}"]`)).toHaveText(secondPageOrganizationName);
  await expect(page.getByRole("columnheader", { name: "公司", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: organizationName, exact: true })).toBeVisible();
  await expect(page.getByText(organizationId, { exact: false })).toHaveCount(0);

  const filteredRunsRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return request.method() === "GET"
      && url.pathname === "/v1/platform/ai/usage/runs"
      && url.searchParams.get("organization_id") === organizationId;
  });
  await companySelect.selectOption(organizationId);
  await page.getByRole("button", { name: "筛选记录", exact: true }).click();
  await filteredRunsRequest;
});

test("Token 用量筛选变更后自动刷新统计与趋势", async ({ page }) => {
  await page.route("**/v1/auth/session", (route) => json(route, {
    authenticated: true,
    login_required: false,
    is_platform_admin: true,
    email_verified: true,
    email_verification_required: false,
    user: {
      user_id: "platform-admin",
      display_name: "Platform Admin",
      email: "platform-admin@example.test",
    },
    organization: null,
    role: null,
    plan: null,
    trial: null,
  }));
  await page.route("**/v1/platform/organizations**", (route) => json(route, {
    items: [
      organizationSummary(organizationId, organizationName),
      organizationSummary(fastOrganizationId, fastOrganizationName),
    ],
    total: 2,
    limit: 100,
    offset: 0,
  }));
  await page.route("**/v1/platform/ai/usage/runs**", (route) => json(route, []));
  const delayStaleOrganizationResponse = async (url: URL) => {
    if (url.searchParams.get("organization_id") === organizationId) {
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  };
  await page.route("**/v1/platform/ai/usage/summary**", async (route) => {
    const url = new URL(route.request().url());
    await delayStaleOrganizationResponse(url);
    return json(route, tokenUsageSummary(url));
  });
  await page.route("**/v1/platform/ai/usage/trend**", async (route) => {
    const url = new URL(route.request().url());
    await delayStaleOrganizationResponse(url);
    return json(route, tokenUsageTrend(url));
  });
  await page.route("**/v1/platform/ai/providers", (route) => json(route, [{
    provider_id: "provider-demo",
    slug: "demo-provider",
    display_name: "测试模型服务",
    driver: "openai_compatible",
    endpoint_url: "https://api.example.test/v1",
    credential_ref: "AI_PROVIDER_DEMO_API_KEY",
    credential_configured: true,
    request_defaults: {},
    is_enabled: true,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
  }]));
  await page.route("**/v1/platform/ai/models", (route) => json(route, [{
    model_id: "model-demo",
    slug: "demo-model",
    provider_id: "provider-demo",
    provider_slug: "demo-provider",
    display_name: "测试聊天模型",
    provider_model_id: "demo-chat",
    capabilities: ["chat"],
    context_window_tokens: 128_000,
    max_output_tokens: 8_000,
    is_enabled: true,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
  }]));
  await page.route("**/v1/platform/ai/routes", (route) => json(route, []));

  const matchesUsageRequest = (url: URL, path: string, filters: Record<string, string>) => (
    url.pathname === path
      && Object.entries(filters).every(([key, value]) => url.searchParams.get(key) === value)
  );
  const matchingRequest = (path: string, filters: Record<string, string>) => page.waitForRequest((request) => {
    const url = new URL(request.url());
    return request.method() === "GET" && matchesUsageRequest(url, path, filters);
  });
  const matchingResponse = (path: string, filters: Record<string, string>) => page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.request().method() === "GET" && matchesUsageRequest(url, path, filters);
  });
  const waitForUsageRefresh = (filters: Record<string, string>) => Promise.all([
    matchingRequest("/v1/platform/ai/usage/summary", filters),
    matchingRequest("/v1/platform/ai/usage/trend", filters),
  ]);
  const expectUpdatedUsage = async (summaryRequest: import("@playwright/test").Request) => {
    const totalTokens = tokenTotalFor(new URL(summaryRequest.url()));
    const formattedTotal = new Intl.NumberFormat("zh-CN").format(totalTokens);
    await expect(page.getByLabel("当前 Token 统计区间").getByText(`${formattedTotal} Token`, { exact: true })).toBeVisible();
    await expect(page.getByRole("img", { name: new RegExp(`共 ${formattedTotal} Token。`) })).toBeVisible();
  };

  await page.goto("/platform/ai");
  const companySelect = page.getByLabel("公司", { exact: true });
  await expect(companySelect).toBeVisible();
  await companySelect.selectOption(organizationId);
  const manuallyAppliedRunRequest = matchingRequest("/v1/platform/ai/usage/runs", {
    organization_id: organizationId,
  });
  await page.getByRole("button", { name: "筛选记录", exact: true }).click();
  await manuallyAppliedRunRequest;

  await page.getByRole("button", { name: "Token 用量", exact: true }).click();
  await expect(page.getByLabel("当前 Token 统计区间")).toBeVisible();
  await expect(page.getByRole("button", { name: "查看 Token", exact: true })).toHaveCount(0);
  await expect(companySelect).toHaveValue("");

  const staleCompanyFilters = { organization_id: organizationId };
  const staleCompanyRequests = waitForUsageRefresh(staleCompanyFilters);
  const staleCompanyResponses = Promise.all([
    matchingResponse("/v1/platform/ai/usage/summary", staleCompanyFilters),
    matchingResponse("/v1/platform/ai/usage/trend", staleCompanyFilters),
  ]);
  await companySelect.selectOption(organizationId);
  await staleCompanyRequests;

  const companyFilters = { organization_id: fastOrganizationId };
  const companyRefresh = waitForUsageRefresh(companyFilters);
  await companySelect.selectOption(fastOrganizationId);
  const [companySummaryRequest] = await companyRefresh;
  await expectUpdatedUsage(companySummaryRequest);
  await staleCompanyResponses;
  await expectUpdatedUsage(companySummaryRequest);

  const featureFilters = { ...companyFilters, feature: "resume_summary" };
  const featureRefresh = waitForUsageRefresh(featureFilters);
  await page.getByLabel("AI 功能", { exact: true }).selectOption("resume_summary");
  const [featureSummaryRequest] = await featureRefresh;
  await expectUpdatedUsage(featureSummaryRequest);

  const modelFilters = {
    ...featureFilters,
    provider_slug: "demo-provider",
    model_slug: "demo-model",
  };
  const modelRefresh = waitForUsageRefresh(modelFilters);
  await page.getByLabel("模型", { exact: true }).selectOption("demo-provider::demo-model");
  const [modelSummaryRequest] = await modelRefresh;
  await expectUpdatedUsage(modelSummaryRequest);

  const currentEndDate = await page.getByLabel("结束日期", { exact: true }).inputValue();
  const [startDate, endDate] = await page.evaluate((currentEnd) => {
    const localDate = (date: Date) => {
      const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
      return local.toISOString().slice(0, 10);
    };
    const current = new Date(`${currentEnd}T00:00:00`);
    const start = new Date(current);
    start.setDate(start.getDate() - 2);
    const end = new Date(current);
    end.setDate(end.getDate() - 1);
    return [localDate(start), localDate(end)];
  }, currentEndDate);
  const startAt = await page.evaluate((value) => new Date(`${value}T00:00:00.000`).toISOString(), startDate);
  const startRefresh = waitForUsageRefresh({ ...modelFilters, started_at_from: startAt });
  await page.getByLabel("开始日期", { exact: true }).fill(startDate);
  const [startSummaryRequest] = await startRefresh;
  await expectUpdatedUsage(startSummaryRequest);

  const endAt = await page.evaluate((value) => new Date(`${value}T23:59:59.999`).toISOString(), endDate);
  const endRefresh = waitForUsageRefresh({ ...modelFilters, started_at_from: startAt, started_at_to: endAt });
  await page.getByLabel("结束日期", { exact: true }).fill(endDate);
  const [endSummaryRequest] = await endRefresh;
  await expectUpdatedUsage(endSummaryRequest);

  const invalidDate = await page.evaluate((value) => {
    const next = new Date(`${value}T00:00:00`);
    next.setDate(next.getDate() + 1);
    const local = new Date(next.getTime() - next.getTimezoneOffset() * 60_000);
    return local.toISOString().slice(0, 10);
  }, endDate);
  const invalidStartAt = await page.evaluate((value) => new Date(`${value}T00:00:00.000`).toISOString(), invalidDate);
  const unexpectedInvalidRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return request.method() === "GET"
      && url.pathname === "/v1/platform/ai/usage/summary"
      && url.searchParams.get("started_at_from") === invalidStartAt
      && url.searchParams.get("started_at_to") === endAt;
  }, { timeout: 500 }).then(() => true).catch(() => false);
  await page.getByLabel("开始日期", { exact: true }).fill(invalidDate);
  await expect(page.getByRole("alert")).toContainText("结束日期不能早于开始日期。 当前统计和趋势仍显示上一次有效筛选结果。");
  await expectUpdatedUsage(endSummaryRequest);
  expect(await unexpectedInvalidRequest).toBe(false);
  await page.getByRole("button", { name: "运行记录", exact: true }).click();
  await page.getByRole("button", { name: "Token 用量", exact: true }).click();
  await expect(page.getByLabel("开始日期", { exact: true })).toHaveValue(invalidDate);
  await expect(page.getByRole("alert")).toContainText("结束日期不能早于开始日期。 当前统计和趋势仍显示上一次有效筛选结果。");

  const correctedEndAt = await page.evaluate((value) => new Date(`${value}T23:59:59.999`).toISOString(), invalidDate);
  const correctedRefresh = waitForUsageRefresh({
    ...modelFilters,
    started_at_from: invalidStartAt,
    started_at_to: correctedEndAt,
  });
  await page.getByLabel("结束日期", { exact: true }).fill(invalidDate);
  const [correctedSummaryRequest] = await correctedRefresh;
  await expectUpdatedUsage(correctedSummaryRequest);

  const dailyTrendResponse = matchingResponse("/v1/platform/ai/usage/trend", {
    ...modelFilters,
    started_at_from: invalidStartAt,
    started_at_to: correctedEndAt,
    granularity: "day",
  });
  await page.getByRole("button", { name: "按天", exact: true }).click();
  const dailyTrend = await dailyTrendResponse;
  const dailyTotal = trendTokenTotalFor(new URL(dailyTrend.request().url()));
  const formattedDailyTotal = new Intl.NumberFormat("zh-CN").format(dailyTotal);
  await expect(page.getByRole("button", { name: "按天", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("img", { name: new RegExp(`共 ${formattedDailyTotal} Token。`) })).toBeVisible();
  await page.getByText(/查看趋势明细/).click();
  await expect(page.getByRole("columnheader", { name: "日期", exact: true })).toBeVisible();

  const preservedRunRequest = matchingRequest("/v1/platform/ai/usage/runs", {
    organization_id: organizationId,
  });
  await page.getByRole("button", { name: "运行记录", exact: true }).click();
  await preservedRunRequest;
  await expect(companySelect).toHaveValue(organizationId);
});
