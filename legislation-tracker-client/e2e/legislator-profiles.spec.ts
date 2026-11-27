import { expect, test } from "@playwright/test";

import {fixtures} from "./fixtures/profile";

test("real native bill→profile→bill nesting, focus, Escape, Tab and rollback", async ({ page }) => {
  await fixtures(page); await page.goto("/");
  await expect(page.getByRole("checkbox", { name: "Enable legislator profiles" })).toHaveCount(0);

  const opener = page.getByRole("button", { name: "Original bill", exact: true });
  await opener.click();
  const original = page.locator("dialog").filter({ has: page.getByRole("heading", { name: "Original bill" }) });
  await original.getByRole("link", { name: "Same Name" }).click();
  const member = page.locator("dialog").filter({ has: page.getByRole("heading", { name: "Same Name" }) });
  await expect(member).toBeVisible();
  await expect(member.getByText("<script>unsafe()</script> A factual source excerpt.",{exact:true})).toBeVisible();
  await expect(member.locator("script")).toHaveCount(0);
  const innerOpener = member.getByRole("button", { name: "Another introduced bill" });
  await innerOpener.click();
  const nested = page.getByRole("dialog", {name:"Another introduced bill",exact:true});
  await expect(nested).toBeVisible();
  await expect(page.locator("dialog[open]")).toHaveCount(3);
  expect(new Set(await page.locator("dialog").evaluateAll(nodes => nodes.map(node => node.getAttribute("aria-labelledby")))).size).toBe(3);
  for (let index = 0; index < 12; index++) { await page.keyboard.press("Tab"); expect(await nested.evaluate(node => node.contains(document.activeElement))).toBe(true); }
  await nested.getByRole("button",{name:"Close bill details"}).focus();
  await page.keyboard.press("Escape"); await expect(nested).toHaveCount(0); await expect(innerOpener).toBeFocused();
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("hidden");
  await page.keyboard.press("Escape"); await expect(member).toHaveCount(0); await expect(original.getByRole("link", { name: "Same Name" })).toBeFocused();
  await page.keyboard.press("Escape"); await expect(page.locator("dialog")).toHaveCount(0); await expect(opener).toBeFocused();
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("");
  await page.reload();
  await expect(page.getByRole("checkbox", { name: "Enable legislator profiles" })).toHaveCount(0);
});

test("same names stay separate, bill pages accumulate, votes and responsive evidence", async ({ page }) => {
  await fixtures(page); await page.goto("/representatives");
  await expect(page.getByRole("checkbox", { name: "Enable legislator profiles" })).toHaveCount(0);
  const names = page.getByRole("link", {name:"Same Name",exact:true});
  await expect(names).toHaveCount(2);
  await expect(names.nth(1)).toHaveAttribute("href",/representatives\/2/);
  await expect(names.first()).toHaveAttribute("href",/representatives\/1/);
  await page.goto("/");
  await page.getByRole("button",{name:"Original bill",exact:true}).click();
  await page.getByRole("dialog").getByRole("link",{name:"Same Name",exact:true}).click();
  const modal=page.getByRole("dialog",{name:"Same Name"});
  const row=modal.getByRole("region",{name:"Bills introduced"});
  await expect(row.getByRole("button",{name:"Another introduced bill"})).toBeVisible();
  await row.evaluate(el=>{el.scrollLeft=el.scrollWidth;el.dispatchEvent(new Event("scroll"));});
  await expect(row.getByRole("button",{name:"Original bill"})).toBeAttached();
  await modal.getByRole("tab",{name:"Votes"}).click();
  await expect(modal.getByRole("region",{name:"Yes votes"}).getByText("Health")).toBeVisible();
  await expect(modal.getByRole("link",{name:/Full voting record/})).toHaveAttribute("href",/representatives\/1.*tab=votes/);
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
  await expect(page.getByRole("checkbox", { name: "Enable legislator profiles" })).toHaveCount(0);
  await page.getByRole("link", { name: "Bernie Sanders", exact: true }).click();
  const modal = page.getByRole("dialog", { name: "Bernie Sanders" });
  await expect(modal.getByRole("link", { name: "Wikipedia article", exact: true })).toHaveAttribute("href", "https://en.wikipedia.org/wiki/Bernie_Sanders", { timeout: 25_000 });
  await expect(modal.getByText("Wikipedia contributors", { exact: false })).toBeVisible();
  await modal.locator("summary", { hasText: "Biography source dates and revision limits" }).click();
  await expect(modal.getByRole("link", { name: "Article revision observed" })).toHaveAttribute("href", /https:\/\/en.wikipedia.org\/w\/index.php\?oldid=\d+/);
  await modal.evaluate(node => { node.scrollTop = 0; });
  await page.screenshot({ path: "test-results/profile-live-wikipedia.png" });
  await page.keyboard.press("Escape");
});

test("profile tabs and funding disclosures work by keyboard on mobile", async ({page}) => {
  await fixtures(page);
  await page.setViewportSize({width:390,height:850});
  await page.goto("/");
  await page.getByRole("button",{name:"Original bill"}).click();
  const opener=page.getByRole("dialog").getByRole("link",{name:"Same Name"});
  await opener.click();
  const modal=page.getByRole("dialog",{name:"Same Name"});
  await expect(modal.getByText("<script>unsafe()</script> A factual source excerpt.",{exact:true})).toBeVisible();
  await modal.getByRole("tab",{name:"Bills"}).focus();
  await page.keyboard.press("End");
  await expect(modal.getByRole("tab",{name:"Campaign funding"})).toBeFocused();
  await expect(modal.getByText("No campaign records available for this period.")).toBeVisible();
  expect(await modal.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
  await page.keyboard.press("Escape");
  await expect(opener).toBeFocused();
});
