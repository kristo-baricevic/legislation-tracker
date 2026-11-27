import { expect, test, type Page } from "@playwright/test";

import {bill,fixtures} from "./fixtures/profile";

async function personalizedFixtures(page: Page) {
  await fixtures(page);
  await page.route("**/api/auth/session/current/**", route => route.fulfill({json: {authenticated: true, user: {email: "fixture@example.com"},current_congress:119}}));
  await page.route("**/api/tracking/", route => route.fulfill({json: {bills: [], topics: [{id: 1, topic: {id: 1, name: "Health", slug: "health"}, created_at: "2026-01-01"}], legislators: [], is_staff: false}}));
  await page.route("**/api/tracking/recommendations/**", route => route.fulfill({json: {algorithm: "explicit-facets-mmr-v1", generated_at: "2026-10-10T00:00:00Z", count: 1, next_cursor: null, candidate_pool_truncated: false, ranking_limit_reached: false, empty_reason: null, unsupported_follow_types: [], results: [{bill, score: 1, reasons: [{kind: "followed_topic", topic_id: 1, name: "Health"}]}]}}));
  await page.route("**/api/tracking/representative-recommendations/**", route => route.fulfill({status: 503, json: {detail: "fixture unavailable"}}));
}
async function changeAccount(page: Page) {
  await page.evaluate(() => { const key = "legislation-tracker-session-epoch"; localStorage.setItem(key, "stable:browser-account-change"); window.dispatchEvent(new StorageEvent("storage", {key})); });
}
test("recommendation root invalidation closes nested subtree and restores owner focus", async ({page}) => {
  await personalizedFixtures(page); await page.goto("/");
  await expect(page.getByLabel("Enable legislator profiles")).toHaveCount(0);
  await expect(page.getByLabel("Show recommendations on this browser")).toHaveCount(0);
  await page.getByRole("region", {name: "Recommended bills"}).getByRole("link", {name: "Original bill"}).click();
  const root = page.getByRole("dialog", {name: "Original bill"});
  await root.getByRole("link", {name: "Same Name"}).click();
  await page.getByRole("dialog", {name: "Same Name"}).getByRole("button", {name: "Another introduced bill"}).click();
  await expect(page.locator("dialog")).toHaveCount(3);
  await page.screenshot({path: "test-results/integration-nested.png"});
  await changeAccount(page);
  await expect(page.locator("dialog")).toHaveCount(0);
  // Account revalidation temporarily hides personalized rows. The persistent
  // dashboard heading remains a visible keyboard destination throughout.
  await expect(page.locator("[data-dashboard-heading]")).toBeFocused();
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("");
});
test("public bill survives account change and telemetry rollback never ingests", async ({page}) => {
  await personalizedFixtures(page); let ingestionWrites = 0;
  page.on("request", request => { if (request.url().includes("/api/ingestion/") && request.method() !== "GET") ingestionWrites++; });
  await page.goto("/");
  await expect(page.getByRole("region",{name:"Recommended bills"})).toBeVisible();
  await expect(page.getByRole("region",{name:"Legislation ingestion"})).toHaveCount(0);
  await page.goto("/bills");
  await page.getByRole("link",{name:"Original bill",exact:true}).click();
  const title=page.getByRole("heading",{name:/HR 5/});
  await expect(title).toBeVisible();
  await changeAccount(page);
  await expect(title).toBeVisible();
  expect(ingestionWrites).toBe(0);
});

test("late private recommendation response cannot repopulate after account generation changes", async ({page}) => {
  await personalizedFixtures(page); await page.goto("/");
  await expect(page.getByLabel("Show recommendations on this browser")).toHaveCount(0);
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
  await expect(page.getByLabel("Enable legislator profiles")).toHaveCount(0);
  const activityResponse = page.waitForResponse(response => response.url().includes("/topic-activity/") && response.request().method() === "GET");
  await page.getByRole("link", {name: "Synthetic Integration Member", exact: true}).click();
  const response = await activityResponse;
  expect(response.status(), await response.text()).toBe(200);
  await expect(page).toHaveURL(new RegExp(`/representatives/${member.id}`));
  await expect(page.getByRole("heading",{name:member.name})).toBeVisible();
  await expect(page.getByRole("button",{name:"Synthetic integration bill"})).toBeVisible();
  await page.getByRole("tab",{name:"Campaign funding"}).click();
  await expect(page.getByRole("region",{name:"Campaign funding"})).toBeVisible();
});
