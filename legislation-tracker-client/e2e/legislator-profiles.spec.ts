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
    if (path === "/api/auth/session/") value = { authenticated: false };
    else if (path === "/api/tracking/") value = { bills: [], topics: [], legislators: [], is_staff: false };
    else if (path === "/api/representatives/") value = { count: 2, next: null, previous: null, results: [{ id: 1, bioguide_id: "S000033", name: "Same Name", state: "VT", chamber: "senate", party: "Independent", district: null }, { id: 2, bioguide_id: "I000002", name: "Same Name", state: "NY", chamber: "house", party: "Other", district: "1" }] };
    else if (path === "/api/bills/filter-options/") value = { jurisdictions: ["federal"], current_congress: 119 };
    else if (path === "/api/bills/") value = { count: 1, next: null, previous: null, results: [bill] };
    else if (/\/api\/bills\/1[01]\/$/.test(path)) value = { ...(path.includes("/11/") ? second : bill), sponsor: 1, summary: "Stored official summary", documents: [], latest_contract: null };
    else if (path.endsWith("/profile/")) value = path.includes("/2/") ? { ...profile, identity: { ...profile.identity, id: 2, bioguide_id: "I000002" } } : profile;
    else if (path.endsWith("/biography/")) value = bio;
    else if (path.endsWith("/sponsored-bills/")) value = { count: 2, previous: url.searchParams.get("page") === "2" ? "?page=1" : null, next: url.searchParams.get("page") === "2" ? null : "https://untrusted.invalid/?page=2", results: [url.searchParams.get("page") === "2" ? bill : second] };
    else if (path.endsWith("/voting-record/")) value = { count: 1, next: null, previous: null, results: [vote], coverage, pagination_mode: "live_pages", page_read_at: "2026-10-10T00:00:00Z" };
    await route.fulfill({ json: value });
  });
}

test("real native bill→profile→bill nesting, focus, Escape, Tab and rollback", async ({ page }) => {
  await fixtures(page); await page.goto("/");
  await page.getByRole("checkbox", { name: "Enable legislator profiles" }).check();
  await page.getByRole("button", { name: "View all bills" }).click();
  const opener = page.getByRole("button", { name: "Original bill", exact: true });
  await opener.click();
  const original = page.locator("dialog").filter({ has: page.getByRole("heading", { name: "Original bill" }) });
  await original.getByRole("link", { name: "Same Name" }).click();
  const member = page.locator("dialog").filter({ has: page.getByRole("heading", { name: "Same Name" }) });
  await expect(member).toBeVisible();
  await expect(member.getByText("Verified campaign finance data is not connected.")).toBeVisible();
  await expect(member.locator("script")).toHaveCount(0);
  const innerOpener = member.getByRole("link", { name: "Another introduced bill" });
  await innerOpener.click();
  const nested = page.locator("dialog").filter({ has: page.getByRole("heading", { name: "Another introduced bill" }) });
  await expect(nested).toBeVisible();
  expect(new Set(await page.locator("dialog").evaluateAll(nodes => nodes.map(node => node.getAttribute("aria-labelledby")))).size).toBe(3);
  for (let index = 0; index < 12; index++) { await page.keyboard.press("Tab"); expect(await nested.evaluate(node => node.contains(document.activeElement))).toBe(true); }
  await page.keyboard.press("Escape"); await expect(nested).toHaveCount(0); await expect(innerOpener).toBeFocused();
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("hidden");
  await page.keyboard.press("Escape"); await expect(member).toHaveCount(0); await expect(original.getByRole("link", { name: "Same Name" })).toBeFocused();
  await page.keyboard.press("Escape"); await expect(page.locator("dialog")).toHaveCount(0); await expect(opener).toBeFocused();
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("");
  await page.getByRole("checkbox", { name: "Enable legislator profiles" }).uncheck(); await page.reload();
  await expect(page.getByRole("checkbox", { name: "Enable legislator profiles" })).not.toBeChecked();
});

test("same names stay separate, live pages replace rows, votes and responsive evidence", async ({ page }) => {
  await fixtures(page); await page.goto("/representatives");
  await page.getByRole("checkbox", { name: "Enable legislator profiles" }).check();
  await page.getByRole("link", { name: "Same Name", exact: true }).nth(1).click();
  await expect(page.getByRole("dialog").getByText("Bioguide ID: I000002")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("link", { name: "Same Name", exact: true }).first().click();
  const modal = page.getByRole("dialog");
  await expect(modal.getByText("Bioguide ID: S000033")).toBeVisible();
  await expect(modal.getByRole("link", { name: "Another introduced bill" })).toBeVisible();
  await modal.getByRole("button", { name: "Next", exact: true }).click();
  await expect(modal.getByRole("link", { name: "Original bill" })).toBeVisible();
  await expect(modal.getByRole("link", { name: "Another introduced bill" })).toHaveCount(0);
  await modal.getByRole("button", { name: "Show voting record" }).click();
  await expect(modal.getByText("Not voting", { exact: true })).toBeVisible();
  await expect(modal.getByRole("link", { name: "Official roll call derived from stored identity" })).toHaveAttribute("href", "https://clerk.house.gov/Votes/20251");
  await modal.getByRole("button", { name: "Back to profile" }).click();
  await expect(modal.getByRole("button", { name: "Show voting record" })).toBeFocused();
  for (const [name, width] of [["desktop", 1280], ["tablet", 768], ["mobile", 390]] as const) {
    await page.setViewportSize({ width, height: 850 });
    await modal.evaluate(node => { node.scrollTop = 0; });
    expect(await modal.evaluate(node => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
    await page.screenshot({ path: `test-results/profile-${name}.png` });
  }
});

test("approved live Wikipedia adapter is visible in the isolated local preview", async ({ page }) => {
  test.skip(process.env.PROFILE_LIVE_PREVIEW !== "true", "Opt-in public-source QA requires isolated preview API18011/database15441.");
  await page.goto("/representatives");
  await page.getByRole("checkbox", { name: "Enable legislator profiles" }).check();
  await page.getByRole("link", { name: "Bernie Sanders", exact: true }).click();
  const modal = page.getByRole("dialog", { name: "Bernie Sanders" });
  await expect(modal.getByRole("link", { name: "Wikipedia article", exact: true })).toHaveAttribute("href", "https://en.wikipedia.org/wiki/Bernie_Sanders", { timeout: 25_000 });
  await expect(modal.getByText("Wikipedia contributors", { exact: false })).toBeVisible();
  await expect(modal.getByRole("link", { name: "Article revision observed" })).toHaveAttribute("href", /https:\/\/en.wikipedia.org\/w\/index.php\?oldid=\d+/);
  await modal.evaluate(node => { node.scrollTop = 0; });
  await page.screenshot({ path: "test-results/profile-live-wikipedia.png" });
  await page.keyboard.press("Escape");
});
