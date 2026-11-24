import { expect, test, type Locator, type Page } from "@playwright/test";
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
test("always-on row, shared bill modal, persisted follow and responsive scrolling", async ({ page }) => {
  await fixtures(page);
  await page.goto("/");
  const preview = page.getByLabel("Show recommendations on this browser");
  await expect(preview).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Your legislation, in view." })).toBeVisible();
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
  await expect(page.getByRole("region", { name: "Followed bills" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Bills to discover" })).toBeFocused();
  await page.reload();
  await expect(preview).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Followed bills" })).toBeVisible();
  for (const [name, width] of [["desktop", 1280], ["tablet", 768], ["mobile", 390]] as const) {
    await page.setViewportSize({ width, height: 850 });
    await expect(row.getByRole("link", { name: second.title })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (name === "mobile") expect(await row.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true);
    await page.screenshot({ path: `test-results/recommendations-${name}.png`, fullPage: true });
  }
  await expect(page.getByRole("heading", { name: "Your legislation, in view." })).toBeVisible();
  await expect(row).toBeVisible();
  await page.reload();
  await expect(preview).toHaveCount(0);
  await page.getByLabel("Use card dashboard on this browser").uncheck();
  await expect(page.getByRole("heading", { name: "Legislation Tracker Operations" })).toBeVisible();
});
test("error, retry, no-match and logout clear private cards", async ({ page }) => {
  await fixtures(page);
  await page.route("**/api/tracking/recommendations/**", route => route.fulfill({ status: 503, json: { detail: "unavailable" } }));
  await page.goto("/");
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

async function expectStableClick(page: Page, button: Locator, settled: () => Promise<void>) {
  await button.evaluate(el => el.scrollIntoView({ block: "center", inline: "nearest" }));
  const measure = await page.evaluateHandle(() => {
    const initial = window.scrollY;
    let maxShift = 0;
    let frame: number;
    const sample = () => {
      maxShift = Math.max(maxShift, Math.abs(window.scrollY - initial));
      frame = requestAnimationFrame(sample);
    };
    sample();
    return { initial, stop: () => { cancelAnimationFrame(frame); return maxShift; } };
  });
  expect(await measure.evaluate(value => value.initial)).toBeGreaterThan(0);
  await button.click();
  await settled();
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  expect(await measure.evaluate(value => value.stop())).toBeLessThanOrEqual(1);
  await measure.dispose();
}

for (const width of [390, 1280]) {
  for (const kind of ["bills", "representatives"] as const) {
    test(`dashboard scroll stays stable on more and dismiss for ${kind} at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 650 });
      await fixtures(page);
      const people = kind === "representatives";
      const endpoint = people ? "representative-recommendations" : "recommendations";
      const moreName = people ? "More representative recommendations" : "More recommendations";
      const row = page.getByRole("region", { name: people ? "Recommended representatives" : "Recommended bills" });
      let release!: () => void;
      const waitForResponse = () => new Promise<void>(resolve => { release = resolve; });
      await page.route(`**/api/tracking/${endpoint}/**`, async route => {
        if (route.request().method() === "POST") {
          await waitForResponse();
          return route.fulfill({ status: 204 });
        }
        const more = new URL(route.request().url()).searchParams.has(people ? "shown" : "cursor");
        if (more) await waitForResponse();
        const results = (more ? [3, 4] : [1, 2]).map(id => {
          const name = `Member ${id}`;
          return people ? {
            representative_id: id, name, reasons: [], bioguide_id: "",
            card: { top_topics: [] }, topic_activity_evidence: { representative: { id, name, state: "NY", chamber: "house" } },
          } : { bill: { ...bill, id, title: `Bill ${id}` }, reasons: [] };
        });
        return route.fulfill({ json: { ...recommendations, results, next_cursor: more ? null : "next", has_more: !more } });
      });
      await page.goto("/");
      const cards = row.getByRole("article");
      await expect(cards).toHaveCount(2);
      const checkPending = async () => {
        await expect.poll(() => typeof release).toBe("function");
        // Hold the response past the dashboard spinner's delay.
        await page.waitForTimeout(350);
        await expect(row).toBeVisible();
        await expect(page.getByRole("status", { name: "Loading dashboard" })).toHaveCount(0);
        release();
      };
      await expectStableClick(page, page.getByRole("button", { name: moreName, exact: true }), async () => {
        await checkPending();
        await expect(cards).toHaveCount(4);
      });
      const dismissStarted = page.waitForRequest(req => req.method() === "POST" && req.url().endsWith("/dismiss/"));
      await expectStableClick(page, cards.first().getByRole("button", { name: /^Dismiss/ }), async () => {
        await dismissStarted;
        await checkPending();
        await expect(cards).toHaveCount(3);
      });
    });
  }
}
