import { test, expect } from "@playwright/test";

test("pages share the dashboard reading and control typefaces", async ({ page }) => {
  await page.route("**/api/**", route => route.fulfill({ json: new URL(route.request().url()).pathname === "/api/topics/" ? [] : {
    authenticated: false, count: 0, next: null, previous: null, results: [],
    bills: [], topics: [], legislators: [], jurisdictions: ["federal"], current_congress: 119,
  } }));
  await page.goto("/");
  const dashboard = page.locator("main h1").first();
  await expect(dashboard).toBeVisible();
  const family = await dashboard.evaluate(el => getComputedStyle(el).fontFamily.split(",")[0].trim());
  expect(family.toLowerCase()).toContain("literata");
  const controlFamily = await page.locator("body").evaluate(el => getComputedStyle(el).fontFamily.split(",")[0].trim());
  expect(controlFamily.toLowerCase()).toContain("atkinson");
  for (const path of ["/login", "/signup", "/bills", "/topics", "/representatives", "/representatives/compare", "/settings"]) {
    await page.goto(path);
    await expect(page.locator("h1").first()).toBeVisible();
    const mismatches = await page.locator("h1, h2, p, label, input, select, button").evaluateAll((elements, expected) => elements
      .filter(el => el.getBoundingClientRect().width > 0 && el.getRootNode() === document)
      .filter(el => getComputedStyle(el).fontFamily.split(",")[0].trim() !== (el.matches("h1, h2") ? expected.heading : expected.control))
      .map(el => ({ tag: el.tagName, text: el.textContent?.slice(0, 60), font: getComputedStyle(el).fontFamily })), { heading: family, control: controlFamily });
    expect(mismatches, path).toEqual([]);
  }
});
