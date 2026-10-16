import { test, expect } from "@playwright/test";

test("page headings and form controls match the dashboard typeface", async ({ page }) => {
  await page.route("**/api/**", route => route.fulfill({ json: new URL(route.request().url()).pathname === "/api/topics/" ? [] : {
    authenticated: false, count: 0, next: null, previous: null, results: [],
    bills: [], topics: [], legislators: [], jurisdictions: ["federal"], current_congress: 119,
  } }));
  await page.goto("/");
  const dashboard = page.locator("main h1").first();
  await expect(dashboard).toBeVisible();
  const family = await dashboard.evaluate(el => getComputedStyle(el).fontFamily.split(",")[0].trim());
  expect(family.toLowerCase()).toContain("geist");
  expect(family.toLowerCase()).not.toContain("mono");
  for (const path of ["/login", "/signup", "/bills", "/topics", "/representatives", "/representatives/compare", "/settings"]) {
    await page.goto(path);
    await expect(page.locator("h1").first()).toBeVisible();
    const mismatches = await page.locator("h1, h2, p, label, input, select, button").evaluateAll((elements, expected) => elements
      .filter(el => el.getBoundingClientRect().width > 0 && el.getRootNode() === document)
      .filter(el => getComputedStyle(el).fontFamily.split(",")[0].trim() !== expected)
      .map(el => ({ tag: el.tagName, text: el.textContent?.slice(0, 60), font: getComputedStyle(el).fontFamily })), family);
    expect(mismatches, path).toEqual([]);
  }
});
