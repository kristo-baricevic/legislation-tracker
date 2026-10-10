import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";

const bill = { id: 1, bill_number: "H.R. 1589", session: 119, title: "To amend the Internal Revenue Code of 1986 to increase the limitation on the deduction for state and local taxes.", jurisdiction: "federal", status: "introduced", sponsor_name: "Test Representative", introduced_at: "2025-02-26", last_action_at: "2025-02-26", topics: [{ topic_id: 1, name: "Taxation", slug: "taxation", confidence_score: 1 }] };
const other = { ...bill, id: 2, bill_number: "H.R. 619", title: "A second bill in the test collection", sponsor_name: null, topics: [], status: "passed_house" };
const documents = [1, 2, 3].map(id => ({ id, source_order: id, version_label: ["Introduced", "Reported", "Engrossed"][id - 1], is_active_version: id === 3, content_type: "text/html", file_size_bytes: 400, source_url: null, downloaded_at: null, download_url: null, text_url: null }));

async function fixtures(page: Page, empty = false) {
  let following = !empty;
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let response: unknown = {};
    if (path === "/api/auth/session/") response = { authenticated: true, user: { email: "fixture@example.com" } };
    else if (path === "/api/auth/csrf/") response = { csrf_token: "fixture" };
    else if (path === "/api/tracking/") response = { bills: following ? [{ id: 1, bill, created_at: "2025-01-01" }] : [], topics: empty ? [] : [{ id: 1, topic: { id: 1, name: "Taxation", slug: "taxation" }, created_at: "2025-01-01" }], legislators: [], is_staff: false };
    else if (path === "/api/tracking/bills/1/") { following = false; await route.fulfill({ status: 204 }); return; }
    else if (path === "/api/tracking/bills/") { following = true; response = { id: 1, bill, created_at: "2025-01-01" }; }
    else if (path === "/api/representatives/") response = { count: 1, next: null, previous: null, results: [{ id: 1, name: "Test Representative", state: "NY" }] };
    else if (path === "/api/bills/") response = { count: 2, next: null, previous: null, results: [bill, other] };
    else if (path === "/api/bills/1/") response = { ...bill, documents, summary: "This bill increases the limitation on the deduction for state and local taxes.", summary_source: "source_metadata", summary_version_code: "Introduced", latest_contract: null };
    else if (path === "/api/bills/1/comparisons/documents/") response = { before: Number(url.searchParams.get("before")), after: Number(url.searchParams.get("after")), sections: [{ section_key: `section-for-version-${url.searchParams.get("after")}`, operation: "modified" }], total_change_count: 1, returned_change_count: 1, truncated: false, fallback: false, truncation_reasons: [] };
    else if (path === "/api/bills/filter-options/") response = { jurisdictions: ["federal"], current_congress: 119 };
    else if (path === "/api/tracking/feed/") response = { entries: [] };
    await route.fulfill({ json: response });
  });
}

test("filters, collection, follow behavior, modal versions, keyboard and persistent rollback", async ({ page }) => {
  await fixtures(page); await page.goto("/");
  const title = page.getByRole("button", { name: bill.title, exact: true });
  await expect(title).toBeVisible();
  await page.getByLabel("Sponsor state").selectOption("NY"); await expect(title).toBeVisible();
  await page.getByLabel("Status", { exact: true }).selectOption("introduced");
  await page.getByLabel("Topic", { exact: true }).selectOption("1");
  await page.getByLabel("Representative (sponsor)").selectOption("Test Representative");
  await page.getByLabel("Search bills").fill("no match"); await expect(page.getByText("No bills match these filters")).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();
  await title.click(); const modal = page.getByRole("dialog"); await expect(modal).toBeVisible();
  await expect(modal.getByText("section-for-version-3", { exact: false })).toBeVisible();
  await modal.getByRole("button", { name: /Reported/ }).click(); await expect(modal.getByText("section-for-version-2", { exact: false })).toBeVisible();
  await expect(modal.getByText("section-for-version-3", { exact: false })).toHaveCount(0);
  await modal.getByRole("button", { name: /Introduced/ }).click(); await expect(modal.getByText(/earliest recorded version/)).toBeVisible();
  for (let index = 0; index < 14; index++) { await page.keyboard.press("Tab"); expect(await modal.evaluate(element => element.contains(document.activeElement))).toBe(true); }
  await page.keyboard.press("Escape"); await expect(modal).toHaveCount(0); await expect(title).toBeFocused();
  await page.getByRole("button", { name: "View all bills" }).click(); await expect(page.getByRole("button", { name: other.title })).toBeVisible();
  await page.getByRole("button", { name: "List", exact: true }).click(); await expect(page.getByRole("button", { name: "List", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Unfollow", exact: true }).click(); await expect(page.getByRole("button", { name: "Follow", exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Following (0)" }).click(); await expect(page.getByText("Your collection starts with a bill")).toBeVisible();
  await page.getByRole("button", { name: "View all bills" }).click(); await page.getByRole("article").filter({ has: title }).getByRole("button", { name: "Follow", exact: true }).click();
  await page.getByRole("button", { name: "Following (1)" }).click(); await expect(title).toBeVisible();
  await page.getByRole("checkbox", { name: "Use card dashboard" }).uncheck(); await expect(page.getByText("Legislation Tracker Operations")).toBeVisible();
  await page.screenshot({ path: "test-results/dashboard-legacy-rollback.png", fullPage: true });
  await page.reload(); await expect(page.getByText("Legislation Tracker Operations")).toBeVisible(); await expect(title).toHaveCount(0);
  await page.getByRole("checkbox", { name: "Use card dashboard" }).check(); await expect(title).toBeVisible();
  await page.reload(); await expect(title).toBeVisible();
});

test("responsive visual evidence and empty collection", async ({ page }) => {
  await fixtures(page); await page.goto("/"); await expect(page.getByRole("button", { name: bill.title })).toBeVisible();
  await page.screenshot({ path: "test-results/dashboard-desktop.png", fullPage: true });
  await page.getByRole("button", { name: "View all bills" }).click(); await expect(page.getByRole("button", { name: other.title })).toBeVisible();
  await page.screenshot({ path: "test-results/dashboard-all-bills.png", fullPage: true });
  await page.getByRole("button", { name: "Following (1)" }).click();
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

test("tracking and catalog errors remain actionable, pagination preserves cards", async ({ page }) => {
  await fixtures(page);
  await page.route("**/api/tracking/", route => route.fulfill({ status: 503, json: { detail: "Unavailable" } }));
  await page.route("**/api/bills/?**", route => route.fulfill({ status: 503, json: { detail: "Unavailable" } }));
  await page.goto("/"); await expect(page.getByRole("alert").filter({ hasText: "followed bills could not be loaded" })).toBeVisible();
  await page.getByRole("button", { name: "View all bills" }).click(); await expect(page.getByRole("button", { name: "Retry loading bills" })).toBeVisible();
  await expect(page.getByText("Your followed bills could not be loaded", { exact: false })).toBeVisible();
  await page.unroute("**/api/bills/?**");
  await page.route("**/api/bills/?**", async route => {
    const second = new URL(route.request().url()).searchParams.get("page") === "2";
    await route.fulfill({ json: { count: 2, next: second ? null : "http://example.invalid/?page=2", previous: null, results: second ? [other] : [bill] } });
  });
  await page.getByRole("button", { name: "Retry loading bills" }).click(); await expect(page.getByRole("button", { name: bill.title })).toBeVisible();
  await expect(page.getByText("Following unavailable")).toBeVisible();
  await page.getByRole("button", { name: "Load more bills" }).click(); await expect(page.getByRole("button", { name: other.title })).toBeVisible();
  await expect(page.getByRole("button", { name: bill.title })).toBeVisible(); await expect(page.getByText(/2 of 2 loaded/)).toBeVisible();
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
