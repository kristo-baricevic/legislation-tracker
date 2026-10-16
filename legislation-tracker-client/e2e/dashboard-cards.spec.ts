import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";

const bill = { id: 1, bill_number: "H.R. 1589", session: 119, title: "To amend the Internal Revenue Code of 1986 to increase the limitation on the deduction for state and local taxes.", jurisdiction: "federal", status: "introduced", sponsor_id: 1, sponsor_bioguide_id: "T000001", sponsor_name: "Test Representative", introduced_at: "2025-02-26", last_action_at: "2025-02-26", topics: [{ topic_id: 1, name: "Taxation", slug: "taxation", confidence_score: 1 }] };
const other = { ...bill, id: 2, bill_number: "H.R. 619", title: "A second bill in the test collection", sponsor_name: null, topics: [], status: "passed_house" };
const documents = [1, 2, 3].map(id => ({ id, source_order: id, version_label: ["Introduced", "Reported", "Engrossed"][id - 1], is_active_version: id === 3, content_type: "text/html", file_size_bytes: 400, source_url: null, downloaded_at: null, download_url: null, text_url: null }));

async function fixtures(page: Page, empty = false) {
  let following = !empty;
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let response: unknown = {};
    if (path === "/api/auth/session/current/") response = { authenticated: true, user: { email: "fixture@example.com" } };
    else if (path === "/api/auth/csrf/") response = { csrf_token: "fixture" };
    else if (path === "/api/tracking/") response = { bills: following ? [{ id: 1, bill, created_at: "2025-01-01" }] : [], topics: empty ? [] : [{ id: 1, topic: { id: 1, name: "Taxation", slug: "taxation" }, created_at: "2025-01-01" }], legislators: [], is_staff: false };
    else if (path === "/api/tracking/bills/1/") { following = false; await route.fulfill({ status: 204 }); return; }
    else if (path === "/api/tracking/bills/") { following = true; response = { id: 1, bill, created_at: "2025-01-01" }; }
    else if (path === "/api/representatives/") response = { count: 1, next: null, previous: null, results: [{ id: 1, name: "Test Representative", state: "NY" }] };
    else if (path === "/api/bills/") response = { count: 2, next: null, previous: null, results: [bill, other] };
    else if (path === "/api/bills/1/") response = { ...bill, documents, summary: "This bill increases the limitation on the deduction for state and local taxes.", summary_source: "source_metadata", summary_version_code: "Introduced", latest_contract: null };
    else if (path === "/api/bills/1/comparisons/documents/") response = { before: Number(url.searchParams.get("before")), after: Number(url.searchParams.get("after")), sections: [{ section_key: `section-for-version-${url.searchParams.get("after")}`, operation: "modified" }], total_change_count: 1, returned_change_count: 1, truncated: false, fallback: false, truncation_reasons: [] };
    else if (path === "/api/bills/filter-options/") response = { jurisdictions: ["federal"], current_congress: 119 };
    else if (path === "/api/topics/") response = [{ id: 1, name: "Taxation", slug: "taxation" }];
    else if (path === "/api/tracking/feed/") response = { entries: [] };
    else if (path === "/api/saved-searches/") response = { count: 0, results: [] };
    else if (path.includes("recommendations")) response = { algorithm: "fixture", generated_at: "2026-10-15T00:00:00Z", count: 0, results: [], next_cursor: null, candidate_pool_truncated: false, ranking_limit_reached: false, empty_reason: "no_candidates", unsupported_follow_types: [] };
    await route.fulfill({ json: response });
  });
}

test("readers see the live panel without samples or automatic ingestion requests", async ({ page }) => {
  const writes: string[] = [];
  const ingestionRequests: string[] = [];
  page.on("request", request => { if (!["GET", "HEAD", "OPTIONS"].includes(request.method()) && request.url().includes("/api/")) writes.push(request.url()); });
  page.on("request", request => { if (request.url().includes("/api/ingestion/")) ingestionRequests.push(request.url()); });
  await page.addInitScript(() => localStorage.setItem("legislation-tracker-ingestion-telemetry", "true"));
  await fixtures(page); await page.goto("/");
  await expect(page.getByRole("button", { name: bill.title, exact: true })).toBeVisible();
  const panel = page.getByRole("region", { name: "Legislation ingestion" });
  await expect(panel).toBeVisible();
  await expect(panel.getByRole("button", { name: "Start discovery and ingestion" })).toBeEnabled();
  await expect(page.getByLabel("Show ingestion telemetry preview")).toHaveCount(0);
  await expect(page.getByText("24 sample", { exact: true })).toHaveCount(0);
  expect(writes).toEqual([]);
  expect(ingestionRequests).toEqual([]);
});

test("staff dashboard never exposes sample telemetry even with a legacy preference", async ({ page }) => {
  const ingestionRequests: string[] = [];
  page.on("request", request => { if (request.url().includes("/api/ingestion/")) ingestionRequests.push(request.url()); });
  await page.addInitScript(() => localStorage.setItem("legislation-tracker-ingestion-telemetry", "true"));
  await fixtures(page);
  await page.route("**/api/tracking/", route => route.fulfill({ json: { bills: [], topics: [], legislators: [], is_staff: true } }));
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Refresh telemetry" })).toBeVisible();
  const toggle = page.getByLabel("Show ingestion telemetry preview");
  await expect(toggle).toHaveCount(0);
  await expect(page.getByText("24 sample", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Show sample data")).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("button", { name: "Refresh telemetry" })).toBeVisible();
  await expect(toggle).toHaveCount(0);
  await expect(page.getByText("24 sample", { exact: true })).toHaveCount(0);
  expect(ingestionRequests).toEqual([]);
});

test("staff operational telemetry refresh is read-only and start is an explicit mocked action", async ({page})=>{
  await fixtures(page);
  await page.route("**/api/tracking/",route=>route.fulfill({json:{bills:[],topics:[],legislators:[],is_staff:true}}));
  let starts=0;const keys:string[]=[];
  await page.route("**/api/ingestion/telemetry/**",route=>route.fulfill({json:{observed_at:"2026-10-09T18:00:00Z",last_discovery_completed_at:"2026-10-09T17:00:00Z",last_successful_work_item_at:"2026-10-09T17:15:00Z",counts_by_kind_and_status:[{kind:"bill",status:"pending",count:4},{kind:"bill_versions",status:"processing",count:2},{kind:"document_download",status:"blocked",count:1}],stale_leases:0,discovery_run:{id:starts ? "fixture-start" : "fixture-run",status:"succeeded",started_at:"2026-10-09T16:55:00Z",finished_at:"2026-10-09T17:00:00Z",discovered:6,created:4},recent_work_states:[{id:1,kind:"bill",status:"pending",updated_at:"2026-10-09T18:00:00Z"}]}}));
  await page.route("**/api/ingestion/source-readiness/**",route=>route.fulfill({json:{available:false,ready_to_start:null,age_seconds:500,complete:true,reason:"Source check stale"}}));
  await page.route("**/api/ingestion/poll-congress/",route=>{starts++;keys.push(route.request().postDataJSON().idempotency_key);return route.fulfill({json:{run_id:"fixture-start",status:"pending"}});});
  await page.goto("/");
  await expect(page.getByLabel("Show ingestion telemetry preview")).toHaveCount(0);
  await expect(page.getByText("24 sample", { exact: true })).toHaveCount(0);
  const panel=page.getByRole("region",{name:"Legislation ingestion"});
  await expect(panel.getByRole("button",{name:"Start discovery and ingestion",exact:true})).toBeEnabled();
  await panel.getByRole("button",{name:"Refresh telemetry"}).click();
  await expect(panel.getByText("Current pipeline backlog",{exact:true})).toBeVisible();
  await expect(panel.getByText("Source & technical details").locator("..")).not.toHaveAttribute("open", "");
  await panel.getByText("Source & technical details", {exact:true}).click();
  await expect(panel.getByText(/Stale — readiness is unavailable/)).toBeVisible();
  expect(starts).toBe(0);
  await panel.screenshot({path:"test-results/ingestion-telemetry-operational-fixture.png"});
  const start=panel.getByRole("button",{name:"Start discovery and ingestion",exact:true});
  await start.click();await expect(panel.getByRole("status")).toContainText("fixture-start");
  await expect(panel.getByRole("button",{name:"Prepare a new discovery request"})).toBeDisabled();
  await start.click();await expect.poll(()=>starts).toBe(2);expect(keys[0]).toBe(keys[1]);
  await panel.getByRole("button",{name:"Refresh telemetry"}).click();
  await panel.getByRole("button",{name:"Prepare a new discovery request"}).click();
  await start.click();await expect.poll(()=>starts).toBe(3);expect(keys[2]).not.toBe(keys[0]);
});

test("filters, collection, follow behavior, modal versions, keyboard and persistent rollback", async ({ page }) => {
  await fixtures(page); await page.goto("/");
  const title = page.getByRole("button", { name: bill.title, exact: true });
  await expect(title).toBeVisible();
  await page.getByLabel("Sponsor state").selectOption("NY"); await expect(title).toBeVisible();
  await page.getByLabel("Status", { exact: true }).selectOption("introduced");
  await page.getByLabel("Topic", { exact: true }).selectOption("1");
  await page.getByLabel("Representative (sponsor)").selectOption("id:1");
  await page.getByLabel("Search bills").fill("no match"); await expect(page.getByText("No bills match these filters")).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();
  await title.click(); const modal = page.getByRole("dialog"); await expect(modal).toBeVisible();
  await expect(modal.getByText("section-for-version-3", { exact: false })).toBeVisible();
  await modal.getByRole("button", { name: /Reported/ }).click(); await expect(modal.getByText("section-for-version-2", { exact: false })).toBeVisible();
  await expect(modal.getByText("section-for-version-3", { exact: false })).toHaveCount(0);
  await modal.getByRole("button", { name: /Introduced/ }).click(); await expect(modal.getByText(/earliest recorded version/)).toBeVisible();
  for (let index = 0; index < 14; index++) { await page.keyboard.press("Tab"); expect(await modal.evaluate(element => element.contains(document.activeElement))).toBe(true); }
  await page.keyboard.press("Escape"); await expect(modal).toHaveCount(0); await expect(title).toBeFocused();
  await expect(page.getByRole("button", { name: "View all bills" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: other.title })).toHaveCount(0);
  await page.getByRole("checkbox", { name: "Use card dashboard" }).uncheck(); await expect(page.getByText("Legislation Tracker Operations")).toBeVisible();
  await page.screenshot({ path: "test-results/dashboard-legacy-rollback.png", fullPage: true });
  await page.reload(); await expect(page.getByText("Legislation Tracker Operations")).toBeVisible(); await expect(title).toHaveCount(0);
  await page.getByRole("checkbox", { name: "Use card dashboard" }).check(); await expect(title).toBeVisible();
  await page.reload(); await expect(title).toBeVisible();
  await page.getByRole("button", { name: "Unfollow", exact: true }).click();
  await expect(page.getByText("Your collection starts with a bill")).toBeVisible();
  await expect(title).toHaveCount(0);
});

test("responsive visual evidence and empty collection", async ({ page }) => {
  await fixtures(page); await page.goto("/"); await expect(page.getByRole("button", { name: bill.title })).toBeVisible();
  await page.screenshot({ path: "test-results/dashboard-desktop.png", fullPage: true });
  await page.goto("/bills"); await expect(page.getByRole("button", { name: other.title })).toBeVisible();
  await page.screenshot({ path: "test-results/bills-catalog.png", fullPage: true });
  await page.setViewportSize({ width: 1280, height: 1050 });
  await page.getByRole("button", { name: bill.title }).click();
  await expect(page.getByRole("dialog").getByText("section-for-version-3", { exact: false })).toBeVisible();
  await page.screenshot({ path: "test-results/dashboard-modal-desktop.png", fullPage: false });
  await page.keyboard.press("Escape");
  for (const [name, width] of [["tablet", 768], ["mobile", 390]] as const) {
    await page.setViewportSize({ width, height: 850 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/dashboard-${name}.png`, fullPage: true });
  }
  await page.getByRole("button", { name: bill.title }).click(); await expect(page.getByRole("dialog").getByText("section-for-version-3", { exact: false })).toBeVisible();
  await page.screenshot({ path: "test-results/dashboard-modal-mobile.png", fullPage: false });
  await page.keyboard.press("Escape"); await page.setViewportSize({ width: 1280, height: 850 });
  await page.getByRole("button", { name: "Switch to dark mode", exact: true }).click();
  await page.screenshot({ path: "test-results/dashboard-dark.png", fullPage: true });
});

test("empty followed bills and topics", async ({ page }) => {
  await fixtures(page, true); await page.goto("/"); await expect(page.getByText("Your collection starts with a bill")).toBeVisible(); await expect(page.getByText("Follow topics to organize")).toBeVisible();
});

test("catalog cards preserve server pagination and open the shared detail modal", async ({ page }) => {
  await fixtures(page);
  await page.route("**/api/bills/?**", async route => {
    const params = new URL(route.request().url()).searchParams;
    const second = params.get("page") === "2";
    expect(params.get("session")).toBe("119");
    const firstPage = [bill, ...Array.from({ length: 19 }, (_, index) => ({ ...bill, id: 100 + index, title: `Catalog bill ${index + 1}` }))];
    await route.fulfill({ json: { count: 21, next: second ? null : "?page=2", previous: second ? "?page=1" : null, results: second ? [other] : firstPage } });
  });
  await page.goto("/bills?session=119");
  const title = page.getByRole("button", { name: bill.title, exact: true });
  await expect(title).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(0);
  await title.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Close bill details" }).click();
  await expect(title).toBeFocused();
  await page.getByRole("button", { name: "List", exact: true }).click();
  await expect(page.getByRole("button", { name: "List", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("button", { name: other.title })).toBeVisible();
  await expect(title).toHaveCount(0);
  await expect(page).toHaveURL(/page=2/);
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(title).toBeVisible();
});

test("dashboard tracking errors remain actionable without offering a catalog", async ({ page }) => {
  await fixtures(page);
  await page.route("**/api/tracking/", route => route.fulfill({ status: 503, json: { detail: "Unavailable" } }));
  await page.goto("/");
  const alert = page.getByRole("alert").filter({ hasText: "followed bills could not be loaded" });
  await expect(alert).toBeVisible();
  await expect(page.getByRole("button", { name: "View all bills" })).toHaveCount(0);
  await page.unroute("**/api/tracking/");
  await alert.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("button", { name: bill.title })).toBeVisible();
});

test("absent summary and version order are honest; stale comparisons never replace a new selection", async ({ page }) => {
  await fixtures(page);
  await page.route("**/api/bills/1/", route => route.fulfill({ json: { ...bill, summary: null, documents: [{ ...documents[0], source_order: null, is_active_version: true }, ...documents.slice(1)], latest_contract: null } }));
  await page.route("**/api/bills/1/comparisons/documents/**", async route => {
    await new Promise(resolve => setTimeout(resolve, 250));
    await route.fulfill({ json: { before: 2, after: 3, sections: [{ section_key: "Delayed old comparison", operation: "modified" }], total_change_count: 1, returned_change_count: 1, truncated: false, fallback: false, truncation_reasons: [] } });
  });
  await page.goto("/"); await page.getByRole("button", { name: bill.title }).click(); const modal = page.getByRole("dialog");
  await expect(modal.getByText("No bill summary is available yet.")).toBeVisible();
  await expect(modal.getByText(/source does not record version order/)).toBeVisible();
  const delayedResponse = page.waitForResponse(response => response.url().includes("/comparisons/documents/") && new URL(response.url()).searchParams.get("after") === "3");
  const delayedRequest = page.waitForRequest(request => request.url().includes("/comparisons/documents/") && new URL(request.url()).searchParams.get("after") === "3");
  await modal.getByRole("button", { name: /Engrossed/ }).click();
  await delayedRequest;
  await modal.getByRole("button", { name: /Reported/ }).click();
  await expect(modal.getByText(/earliest recorded version/)).toBeVisible();
  await delayedResponse;
  await expect(modal.getByText("Delayed old comparison", { exact: false })).toHaveCount(0);
  await modal.getByRole("button", { name: /Introduced/ }).click(); await expect(modal.getByText(/source does not record version order/)).toBeVisible();
});


test("telemetry separates incremental readiness from historical inventory gaps", async ({page}) => {
  await fixtures(page);
  await page.route("**/api/tracking/",route=>route.fulfill({json:{bills:[],topics:[],legislators:[],is_staff:true}}));
  await page.route("**/api/ingestion/telemetry/**",route=>route.fulfill({json:{observed_at:"2026-10-09T18:10:00Z",counts_by_kind_and_status:[],stale_leases:0,discovery_run:null,recent_work_states:[]}}));
  let valid=true;
  await page.route("**/api/ingestion/source-readiness/**",route=>route.fulfill({json:{available:true,age_seconds:1,complete:true,missing_unqueued_metadata:9,ready_to_start:valid?3:null,incremental_discoverable_count_available:valid,discovery_basis:{cursor_at:"2026-10-09T18:00:00Z",from_date_time:"2026-10-09T17:55:00Z"},discovery_checked_completed_at:"2026-10-09T18:10:00Z"}}));
  await page.goto("/");
  const panel=page.getByRole("region",{name:"Legislation ingestion"});
  await panel.getByRole("button",{name:"Refresh telemetry"}).click();
  await panel.getByText("Source & technical details", {exact:true}).click();
  const ready=panel.getByRole("heading",{name:"Ready for incremental discovery"}).locator("..");
  const gaps=panel.getByRole("heading",{name:"Missing unqueued metadata"}).locator("..");
  await expect(ready.locator("strong")).toHaveText("3");await expect(gaps.locator("strong")).toHaveText("9");
  await expect(panel.getByText(/Discovery basis: cursor/)).toContainText("2026-10-09T17:55:00Z");
  await panel.screenshot({path:"test-results/ingestion-telemetry-readiness-fixture.png"});
  valid=false;await panel.getByRole("button",{name:"Refresh telemetry"}).click();
  await expect(ready.locator("strong")).toHaveText("Unavailable");await expect(gaps.locator("strong")).toHaveText("9");
});
