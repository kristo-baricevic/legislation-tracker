import { expect, test, type Page } from "@playwright/test";
const bill = { id: 1, jurisdiction: "federal", session: 119, bill_number: "HR 1", title: "Public health reporting", status: "introduced", sponsor_name: "Member One", introduced_at: "2025-01-10", last_action_at: null, topics: [{ topic_id: 1, name: "Health", slug: "health", confidence_score: null }] };
const second = { ...bill, id: 2, bill_number: "HR 2", title: "Rural health reporting" };
const third = { ...bill, id: 3, bill_number: "HR 3", title: "Community health reporting" };
const recommendations = { algorithm: "explicit-facets-mmr-v1", generated_at: "2026-10-10T00:00:00Z", count: 3, next_cursor: null, candidate_pool_truncated: false, ranking_limit_reached: false, empty_reason: null, unsupported_follow_types: [], results: [bill, second, third].map(bill => ({ bill, score: 1, reasons: [{ kind: "followed_topic", topic_id: 1, name: "Health" }] })) };
async function fixtures(page: Page) {
  let followed = false, signedIn = true;
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let response: unknown;
    if (path === "/api/auth/session/current/") { await route.fulfill({ status: signedIn ? 200 : 401, json: signedIn ? { authenticated: true, user: { email: "fixture@example.com" } } : { detail: "anonymous" } }); return; }
    if (path === "/api/auth/session/refresh/") { await route.fulfill({ status: 401, json: { detail: "anonymous" } }); return; }
    if (path === "/api/auth/csrf/") response = { csrf_token: "fixture" };
    else if (path === "/api/auth/session/logout/") { signedIn = false; await route.fulfill({ status: 204 }); return; }
    else if (path === "/api/tracking/") response = { bills: followed ? [{ id: 1, bill, created_at: "2025-01-01" }] : [], topics: [{ id: 1, topic: { id: 1, name: "Health", slug: "health" }, created_at: "2025-01-01" }], legislators: [], is_staff: false };
    else if (path === "/api/tracking/bills/") { followed = true; response = { id: 1, bill, created_at: "2025-01-01" }; }
    else if (path === "/api/tracking/recommendations/") response = { ...recommendations, results: recommendations.results.filter(item => !followed || item.bill.id !== 1) };
    else if (path === "/api/tracking/representative-recommendations/") response = { algorithm: "explicit-representative-topics-mmr-v1", generated_at: "2026-10-10T00:00:00Z", activity_as_of: null, count: 0, results: [], empty_reason: "insufficient_metadata", unsupported_follow_types: [], policy_version: null, coverage: { status: "ingested_subset", service_exposure: "unknown", bill_families: "unavailable", votes_used_for_ranking: false } };
    else if (path === "/api/representatives/") response = { count: 0, next: null, previous: null, results: [] };
    else if (path === "/api/bills/1/") response = { ...bill, documents: [], summary: null, latest_contract: null };
    else if (path === "/api/bills/filter-options/") response = { jurisdictions: ["federal"], current_congress: 119 };
    else if (path === "/api/tracking/feed/") response = { entries: [] };
    else response = {};
    await route.fulfill({ json: response });
  });
}
test("opt-in row, shared bill modal, persisted follow, responsive scrolling and rollback", async ({ page }) => {
  await fixtures(page);
  await page.goto("/");
  const preview = page.getByLabel("Show recommendations on this browser");
  await expect(preview).not.toBeChecked();
  await expect(page.getByRole("heading", { name: "Your legislation, in view." })).toBeVisible();
  await expect(page.getByRole("region", { name: "Recommended bills" })).toHaveCount(0);
  await preview.check();
  const row = page.getByRole("region", { name: "Recommended bills" });
  const opener = row.getByRole("link", { name: bill.title });
  await expect(opener).toBeVisible();
  await expect(row.getByLabel("Why recommended").first()).toContainText("a topic you follow");
  await opener.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("dialog").getByText("No bill summary is available yet.")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(opener).toBeFocused();
  const request = page.waitForRequest(request => request.url().endsWith("/api/tracking/bills/") && request.method() === "POST");
  await row.getByRole("button", { name: "Follow bill HR 1 / 119" }).click();
  expect((await request).postDataJSON()).toEqual({ bill: 1 });
  await expect(row.getByRole("link", { name: second.title })).toBeVisible();
  await expect(row.getByRole("link", { name: bill.title })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Following (1)" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Bills to discover" })).toBeFocused();
  await page.reload();
  await expect(preview).toBeChecked();
  await expect(page.getByRole("button", { name: "Following (1)" })).toBeVisible();
  for (const [name, width] of [["desktop", 1280], ["tablet", 768], ["mobile", 390]] as const) {
    await page.setViewportSize({ width, height: 850 });
    await expect(row.getByRole("link", { name: second.title })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (name === "mobile") expect(await row.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true);
    await page.screenshot({ path: `test-results/recommendations-${name}.png`, fullPage: true });
  }
  await preview.uncheck();
  await expect(page.getByRole("heading", { name: "Your legislation, in view." })).toBeVisible();
  await expect(row).toHaveCount(0);
  await page.reload();
  await expect(preview).not.toBeChecked();
  await page.getByLabel("Use card dashboard on this browser").uncheck();
  await expect(page.getByRole("heading", { name: "Legislation Tracker Operations" })).toBeVisible();
});
test("error, retry, no-match and logout clear private cards", async ({ page }) => {
  await fixtures(page);
  await page.route("**/api/tracking/recommendations/**", route => route.fulfill({ status: 503, json: { detail: "unavailable" } }));
  await page.goto("/");
  await page.getByLabel("Show recommendations on this browser").check();
  const bills = page.getByRole("region", { name: "Recommended bills" });
  await expect(page.getByRole("alert").filter({ hasText: "Recommendations could not" })).toBeVisible();
  await page.unroute("**/api/tracking/recommendations/**");
  await page.getByRole("button", { name: "Retry recommendations" }).click();
  await expect(bills.getByRole("link", { name: bill.title })).toBeVisible();
  await page.route("**/api/tracking/recommendations/**", route => route.fulfill({ json: { ...recommendations, results: [], count: 0, empty_reason: "no_matches" } }));
  const refresh = page.waitForRequest(request => new URL(request.url()).pathname === "/api/tracking/recommendations/");
  await page.getByRole("button", { name: "Refresh bill recommendations" }).click();
  await refresh;
  await expect(page.getByText("No other ingested legislation matches your followed interests yet.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Bills to discover" })).toBeFocused();
  await page.getByRole("button", { name: "Log out", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Bills to discover" })).toBeVisible();
  await expect(bills).toHaveCount(0);
  await expect(page.getByText("Log in to discover legislation", { exact: false })).toHaveCount(2);
});
