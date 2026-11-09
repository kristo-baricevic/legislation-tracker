import { test, expect } from "@playwright/test";

test("reader tabs retain the summary, page all money, and open exact source popovers", async ({ page, request }, testInfo) => {
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
    await expect(ledger.getByRole("heading", { name: "Money in this bill", exact: true })).toBeFocused();
    await expect(ledger.getByRole("heading", { name: "Money in this bill", exact: true })).toBeInViewport();
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
  await page.screenshot({ path: testInfo.outputPath("reader-tabs-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(summary).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("reader-tabs-mobile.png"), fullPage: true });
});

test("nested glossary citations allow document navigation on a small screen", async ({ page, request }) => {
  const response = await request.get(`${process.env.E2E_API_URL}/api/bills/?bill_number=HR%20E2E`);
  const bill = (await response.json()).results.find((item: { bill_number: string }) => item.bill_number === "HR E2E");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/bills/${bill.id}`);
  await page.getByRole("tab", { name: "Key terms", exact: true }).click();
  await page.getByRole("button", { name: "View legal definition" }).first().click();
  await page.getByRole("dialog", { name: "View legal definition" }).getByRole("button", { name: "Read bill text", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(2);
  const source = page.getByRole("dialog", { name: "Read bill text", exact: true });
  await expect(source.getByTestId("source-evidence-text")).toContainText("covered hospital");
  await source.getByRole("link", { name: "Read full text" }).click();
  await expect(page).toHaveURL(/\/documents\/\d+$/);
  await expect(page.getByText("Full bill text, not a summary. Wording is preserved from the stored source.")).toBeVisible();
});

test("a keyboard reader can jump to scoped money and return to the changes tab", async ({ page, request }) => {
  const response = await request.get(`${process.env.E2E_API_URL}/api/bills/?bill_number=HR%20E2E`);
  const bill = (await response.json()).results.find((item: { bill_number: string }) => item.bill_number === "HR E2E");
  await page.goto(`/bills/${bill.id}`);
  const jump = page.getByRole("button", { name: "Show all 4 money items" });
  await jump.focus();
  await page.keyboard.press("Enter");
  const tab = page.getByRole("tab", { name: "Money", exact: true });
  await expect(tab).toBeFocused();
  await expect(page.getByRole("heading", { name: "Money in this provision" })).toBeVisible();
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByRole("tab", { name: "What changes" })).toBeFocused();
  await expect(jump).toBeVisible();
});
