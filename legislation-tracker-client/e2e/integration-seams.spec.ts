import { expect, test, type Page } from "@playwright/test";

const fact = { status: "unavailable", value: null, precision: null, reason: "unverified", source_url: null, retrieved_at: null };
const coverage = { scope: { congress: 119, chamber: null }, stored_record_count: 1, unknown_session_record_count: 0, member_position_completeness: "unknown", provider_scopes: [], legacy_ingestion_check: { scopes: [], coverage_complete: false, reason: "No service history", discovered_count: 0, persisted_count: 0, notice: "Member completeness unknown" } };
const bill = { id: 10, bill_number: "HR 5", session: 119, title: "Original bill", jurisdiction: "federal", status: "introduced", sponsor_id: 1, sponsor_bioguide_id: "S000033", sponsor_name: "Same Name", introduced_at: "2025-01-09", last_action_at: null, topics: [] };
const second = { ...bill, id: 11, title: "Another introduced bill" };
const profile = { schema_version: "legislator-profile-v1", scope: { congress: 119, chamber: null }, identity: { id: 1, bioguide_id: "S000033", name: "Same Name", is_current: true, latest_affiliation: { chamber: "senate", party: "Independent", state: "VT", district: null }, last_seen_at: null, source_url: null }, service: { status: "available", precision: "year", observations: [{ id: 1, chamber: "house", state: "VT", district: "1", start_year: 2023, end_year: 2027, source_url: null, retrieved_at: null }], notice: "Stored years; exact dates unverified." }, elections: [{ chamber: "house", first_elected: fact, most_recent_election_won: fact, term_start: fact }], donors: { status: "unavailable", reason: "source_not_connected", cycle: null, reporting_period: null, currency: null, source_url: null, methodology: null, donors: [] }, coverage };
const bio = { status: "available", text: "<script>unsafe()</script> A factual source excerpt.", reason: null, wikidata_id: "Q359442", page_id: 361176, observed_revision_id: 1378464460, observed_revision_at: "2026-10-04T16:55:30Z", page_url: "https://en.wikipedia.org/wiki/Bernie_Sanders", observed_revision_url: "https://en.wikipedia.org/w/index.php?oldid=1378464460", fetched_at: "2026-10-10T00:00:00Z", shortened: true, attribution: "Wikipedia contributors", license: "CC BY-SA 4.0", license_url: "https://creativecommons.org/licenses/by-sa/4.0/" };
const vote = { id: 1, representative_id: 1, vote_id: 1, congress: 119, chamber: "house", session_number: 1, roll_number: 1, vote_date: "2025-01-09T19:00:00Z", question: "On passage", position: "not_voting", raw_position: "Not Voting", bill: second, source_url: "https://clerk.house.gov/Votes/20251", source_link_kind: "roll_call", source_updated_at: null };

async function fixtures(page: Page) {
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url()), path = url.pathname;
    let value: unknown = {};
    if (path === "/api/auth/session/current/") value = { authenticated: false };
    else if (path === "/api/tracking/") value = { bills: [], topics: [], legislators: [], is_staff: false };
    else if (path === "/api/representatives/") value = { count: 2, next: null, previous: null, results: [{ id: 1, bioguide_id: "S000033", name: "Same Name", state: "VT", chamber: "senate", party: "Independent", district: null }, { id: 2, bioguide_id: "I000002", name: "Same Name", state: "NY", chamber: "house", party: "Other", district: "1" }] };
    else if (path === "/api/bills/filter-options/") value = { jurisdictions: ["federal"], current_congress: 119 };
    else if (path === "/api/bills/") value = { count: 1, next: null, previous: null, results: [bill] };
    else if (/\/api\/bills\/1[01]\/$/.test(path)) value = { ...(path.includes("/11/") ? second : bill), sponsor: 1, summary: "Stored official summary", documents: [], latest_contract: null };
    else if (path.endsWith("/profile/")) value = path.includes("/2/") ? { ...profile, identity: { ...profile.identity, id: 2, bioguide_id: "I000002" } } : profile;
    else if (path.endsWith("/biography/")) value = bio;
    else if (path.endsWith("/sponsored-bills/")) value = { count: 2, previous: url.searchParams.get("page") === "2" ? "?page=1" : null, next: url.searchParams.get("page") === "2" ? null : "https://untrusted.invalid/?page=2", results: [url.searchParams.get("page") === "2" ? bill : second] };
    else if (path.endsWith("/voting-record/")) value = { count: 1, next: null, previous: null, results: [vote], coverage, pagination_mode: "live_pages", page_read_at: "2026-10-10T00:00:00Z" };
    if (path.endsWith("/topic-activity/")) { await route.fulfill({status: 503, json: {detail: "fixture activity unavailable"}}); return; }
    await route.fulfill({ json: value });
  });
}


async function personalizedFixtures(page: Page) {
  await fixtures(page);
  await page.route("**/api/auth/session/current/", route => route.fulfill({json: {authenticated: true, user: {email: "fixture@example.com"}}}));
  await page.route("**/api/tracking/", route => route.fulfill({json: {bills: [], topics: [{id: 1, topic: {id: 1, name: "Health", slug: "health"}, created_at: "2026-01-01"}], legislators: [], is_staff: false}}));
  await page.route("**/api/tracking/recommendations/**", route => route.fulfill({json: {algorithm: "explicit-facets-mmr-v1", generated_at: "2026-10-10T00:00:00Z", count: 1, next_cursor: null, candidate_pool_truncated: false, ranking_limit_reached: false, empty_reason: null, unsupported_follow_types: [], results: [{bill, score: 1, reasons: [{kind: "followed_topic", topic_id: 1, name: "Health"}]}]}}));
  await page.route("**/api/tracking/representative-recommendations/**", route => route.fulfill({status: 503, json: {detail: "fixture unavailable"}}));
}
async function changeAccount(page: Page) {
  await page.evaluate(() => { const key = "legislation-tracker-session-epoch"; localStorage.setItem(key, "stable:browser-account-change"); window.dispatchEvent(new StorageEvent("storage", {key})); });
}
test("recommendation root invalidation closes nested subtree and restores owner focus", async ({page}) => {
  await personalizedFixtures(page); await page.goto("/");
  await page.getByLabel("Enable legislator profiles").check();
  await page.getByLabel("Show recommendations on this browser").check();
  await page.getByRole("region", {name: "Recommended bills"}).getByRole("link", {name: "Original bill"}).click();
  const root = page.getByRole("dialog", {name: "Original bill"});
  await root.getByRole("link", {name: "Same Name"}).click();
  await page.getByRole("dialog", {name: "Same Name"}).getByRole("link", {name: "Another introduced bill"}).click();
  await expect(page.locator("dialog")).toHaveCount(3);
  await page.screenshot({path: "test-results/integration-nested.png"});
  await changeAccount(page);
  await expect(page.locator("dialog")).toHaveCount(0);
  await expect(page.getByRole("heading", {name: "Bills to discover"})).toBeFocused();
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("");
});
test("public bill survives account change and telemetry rollback never ingests", async ({page}) => {
  await personalizedFixtures(page); let ingestionWrites = 0;
  page.on("request", request => { if (request.url().includes("/api/ingestion/") && request.method() !== "GET") ingestionWrites++; });
  await page.goto("/");
  await expect(page.getByText("Preview — sample data")).toBeVisible();
  await expect(page.getByRole("button", {name: "Start ingestion"})).toBeDisabled();
  await page.screenshot({path: "test-results/integration-telemetry.png", fullPage: true});
  await page.getByLabel("Show ingestion telemetry preview").uncheck();
  await expect(page.getByText("Preview — sample data")).toHaveCount(0);
  await page.getByRole("button", {name: "View all bills"}).click();
  await page.getByRole("button", {name: "Original bill", exact: true}).click();
  await expect(page.getByRole("dialog", {name: "Original bill"})).toBeVisible();
  await changeAccount(page);
  await expect(page.getByRole("dialog", {name: "Original bill"})).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", {name: "Original bill", exact: true})).toBeFocused();
  expect(ingestionWrites).toBe(0);
});

test("late private recommendation response cannot repopulate after account generation changes", async ({page}) => {
  await personalizedFixtures(page); await page.goto("/");
  await page.getByLabel("Show recommendations on this browser").check();
  await expect(page.getByRole("region", {name: "Recommended bills"})).toBeVisible();
  let release!: () => Promise<void>; let held = false;
  await page.route("**/api/tracking/recommendations/**", async route => {
    if (!held) { held = true; await new Promise<void>(resolve => { release = async () => { await route.fulfill({json: {algorithm: "explicit-facets-mmr-v1", generated_at: "2026-10-10T00:00:00Z", count: 1, next_cursor: null, results: [{bill: {...bill, title: "Private stale owner A"}, score: 1, reasons: []}], unsupported_follow_types: []}}).catch(() => {}); resolve(); }; }); }
    else await route.fulfill({json: {algorithm: "explicit-facets-mmr-v1", generated_at: "2026-10-10T00:00:00Z", count: 0, next_cursor: null, results: [], empty_reason: "no_matches", unsupported_follow_types: []}});
  });
  await page.getByRole("button", {name: "Refresh bill recommendations"}).click();
  await expect.poll(() => held).toBe(true);
  await changeAccount(page);
  await expect(page.getByText("No other ingested legislation matches your followed interests yet.")).toBeVisible();
  await release();
  await expect(page.getByText("Private stale owner A")).toHaveCount(0);
});
test("real isolated API activity is rendered through the client profile wrapper", async ({page, request}) => {
  const apiBase = process.env.E2E_API_URL ?? "http://127.0.0.1:18000";
  const directory = await request.get(`${apiBase}/api/representatives/`);
  expect(directory.status()).toBe(200);
  const member = (await directory.json()).results.find((item: {name: string}) => item.name === "Synthetic Integration Member");
  expect(member).toBeTruthy();
  // Build the catalog once before React development-mode duplicate reads.
  // Concurrent cold catalog requests deliberately return an honest 503.
  const catalog = await request.get(`${apiBase}/api/representatives/${member.id}/topic-activity/`);
  expect(catalog.status(), await catalog.text()).toBe(200);
  await page.goto("/representatives");
  await page.getByLabel("Enable legislator profiles").check();
  const activityResponse = page.waitForResponse(response => response.url().includes("/topic-activity/") && response.request().method() === "GET");
  await page.getByRole("link", {name: "Synthetic Integration Member", exact: true}).click();
  const response = await activityResponse;
  expect(response.status(), await response.text()).toBe(200);
  const modal = page.getByRole("dialog", {name: "Synthetic Integration Member"});
  await expect(modal.getByRole("heading", {name: "Recorded topic activity"})).toBeVisible();
  await expect(modal.getByText(/Rolling .*month window/)).toBeVisible();
  await expect(modal.getByText("Verified campaign finance data is not connected.")).toBeVisible();
  await page.screenshot({path: "test-results/integration-real-api-profile.png"});
  for (const [name, width] of [["desktop", 1280], ["mobile", 390]] as const) {
    await page.setViewportSize({width, height: 850});
    await modal.evaluate(node => {node.scrollTop = 0;});
    expect(await modal.evaluate(node => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
    await page.screenshot({path: `test-results/profile-prioritized-real-api-${name}.png`});
  }
  await page.keyboard.press("Escape");
});
