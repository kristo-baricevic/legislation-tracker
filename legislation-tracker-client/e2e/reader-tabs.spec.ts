import { test, expect } from "@playwright/test";

test("reader tabs retain the summary, page all money, and open exact source popovers", async ({ page, request }) => {
  const api = process.env.E2E_API_URL ?? "http://127.0.0.1:18000";
  const response = await request.get(`${api}/api/bills/?bill_number=HR%20E2E`);
  expect(response.ok()).toBeTruthy();
  const bill = (await response.json()).results.find((item: { bill_number: string }) => item.bill_number === "HR E2E");
  await page.goto(`/bills/${bill.id}`);
  const summary = page.getByRole("heading", { name: "What this bill does" });
  await expect(summary).toBeVisible();
  await page.getByRole("tab", { name: "Money", exact: true }).click();
  const ledger = page.getByRole("region", { name: "Money in this bill", exact: true });
  await expect(ledger.getByText("25 of 101 provisions shown")).toBeVisible();
  for (let n = 2; n <= 5; n++) {
    await ledger.getByRole("button", { name: "Next", exact: true }).click();
    await expect(ledger.getByText(`Page ${n} of 5`, { exact: true })).toBeVisible();
  }
  await expect(ledger.locator("ol > li")).toHaveCount(1);
  await expect(ledger.getByText("$101,000", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "What changes" }).click();
  await expect(ledger).not.toBeVisible();
  await expect(summary).toBeVisible();
  await page.getByRole("tab", { name: "Money", exact: true }).click();
  await expect(ledger.getByText("Page 5 of 5", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "What changes" }).click();
  const line = page.getByRole("tabpanel").getByRole("button", { name: "Read bill text", exact: true }).first();
  await line.click();
  await expect(page.getByRole("dialog").getByTestId("source-evidence-text")).not.toBeEmpty();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(line).toBeFocused();
  await page.getByRole("tab", { name: "Key terms", exact: true }).click();
  await expect(page.getByText("reader term 27", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Votes & sponsor" }).click();
  await expect(page.getByRole("heading", { name: "Voting record" })).toBeVisible();
  await page.getByRole("tab", { name: "Versions" }).click();
  await expect(page.getByRole("heading", { name: "Bill documents" })).toBeVisible();
  await page.getByRole("tab", { name: "What changes" }).click();
  await page.screenshot({ path: "/private/tmp/legislation-reader-tabs-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(summary).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "/private/tmp/legislation-reader-tabs-mobile.png", fullPage: true });
});
