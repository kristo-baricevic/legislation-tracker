import {
  expect,
  type APIRequestContext,
  type Locator,
  type Page,
  test,
} from "@playwright/test";

const API_BASE = "http://127.0.0.1:18000";

async function billId(request: APIRequestContext, billNumber: string) {
  const response = await request.get(
    `${API_BASE}/api/bills/?bill_number=${encodeURIComponent(billNumber)}`,
  );
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    results: Array<{ id: number; bill_number: string }>;
  };
  const exact = body.results.find((bill) => bill.bill_number === billNumber);
  expect(exact).toBeDefined();
  return exact!.id;
}

async function clickForResponse(page: Page, control: Locator, path: string) {
  const responsePromise = page.waitForResponse((response) =>
    response.request().method() === "GET" && response.url().includes(path),
  );
  await control.click();
  expect((await responsePromise).status()).toBe(200);
}

test("a visitor can read the complete bounded bill brief and official summary", async ({
  page,
  request,
}) => {
  const id = await billId(request, "HR E2E");
  const compact = await request.get(`${API_BASE}/api/bills/${id}/?contract_view=summary`);
  const compactBody = await compact.text();
  expect(compactBody).not.toContain("preserves the official roll-call record");
  expect(compactBody).not.toContain("line_items");

  await page.goto(`/bills/${id}`);
  await expect(page.getByRole("heading", { name: "What this bill does" })).toBeVisible();
  await expect(page.getByText("Official CRS summary · 2026-01-02")).toBeVisible();
  await expect(page.getByText(/publish a rural-health implementation plan/)).toBeVisible();
  await expect(page.getByText(/preserves the official roll-call record/)).toHaveCount(0);

  await clickForResponse(
    page,
    page.getByRole("button", { name: "Read full official summary" }),
    `/api/bills/${id}/official-summary/`,
  );
  await expect(page.getByText(/preserves the official roll-call record/)).toBeVisible();

  const breakdown = page.getByText("Browse detailed provisions").locator("..");
  await expect(page.getByText("Requires the Secretary to complete reader provision 26.")).toHaveCount(0);
  await clickForResponse(
    page,
    page.getByText("Browse detailed provisions"),
    "reader-items/?page=1",
  );
  await clickForResponse(page, page.getByRole("button", { name: "Show 25 more", exact: true }), "reader-items/?page=2");
  await expect(page.getByText("Requires the Secretary to complete reader provision 50.")).toBeVisible();
  await clickForResponse(page, page.getByRole("button", { name: "Show 25 more", exact: true }), "reader-items/?page=3");
  await expect(page.getByText("Requires the Secretary to complete reader provision 61.")).toBeVisible();
  await expect(breakdown).toContainText("These provisions are shown in bill order.");
});

test("a visitor sees a clear fallback when CRS has not published a summary", async ({
  page,
  request,
}) => {
  const id = await billId(request, "HR E2E NO CRS");
  await page.goto(`/bills/${id}`);
  await expect(page.getByText("This bill requires the Secretary to publish a report.")).toBeVisible();
  await expect(page.getByText("No official CRS summary is available yet.")).toHaveCount(0);
});

test("a visitor can audit every financial item without a computed total", async ({
  page,
  request,
}) => {
  const id = await billId(request, "HR E2E");
  await page.goto(`/bills/${id}`);
  const money = page.getByRole("region", { name: "Money in this bill" });
  await expect(money.getByText("25 of 101 provisions shown")).toBeVisible();
  for (const action of ["Appropriation", "Authorization", "Transfer", "Rescission"]) {
    await expect(money.locator("ol").getByText(action, { exact: true }).first()).toBeVisible();
  }
  await expect(money.getByText(/combined total/i)).toHaveCount(0);

  for (let targetPage = 2; targetPage <= 5; targetPage += 1) {
    await clickForResponse(
      page,
      money.getByRole("button", { name: "Show 25 more money provisions" }),
      `financial-items/?page=${targetPage}`,
    );
  }
  await expect(money.locator("ol > li")).toHaveCount(101);
  await expect(money.getByText("101 of 101 provisions shown")).toBeVisible();
  const finalItem = money.locator("ol > li").last();
  await expect(finalItem.getByText("$101,000", { exact: true })).toBeVisible();
  await expect(finalItem.getByText("Rural health program 101", { exact: true })).toBeVisible();

  await money.getByLabel("Financial action").selectOption("transfer");
  await clickForResponse(
    page,
    money.getByRole("button", { name: "Apply money filters" }),
    "financial_action=transfer",
  );
  await expect(money.getByText("25 of 25 matching provisions shown")).toBeVisible();
  await expect(money.locator("ol > li")).toHaveCount(25);
  await expect(money.locator("ol").getByText("Appropriation", { exact: true })).toHaveCount(0);
});

test("a visitor can reconstruct and paginate exact evidence and open document links", async ({
  page,
  request,
}) => {
  const id = await billId(request, "HR E2E");
  await page.goto(`/bills/${id}`);
  await clickForResponse(
    page,
    page.getByText("Browse detailed provisions"),
    "reader-items/?page=1",
  );

  const firstLine = page
    .getByText("Requires the Secretary to publish a complete rural health implementation plan.")
    .locator("xpath=ancestor::li[1]");
  await clickForResponse(
    page,
    firstLine.getByRole("button", { name: "Read bill text" }),
    "evidence/?page=1&page_size=25&line_item_id=line-0",
  );
  await expect(firstLine.getByTestId("source-evidence-text")).toContainText("LONG EVIDENCE START|");
  await expect(firstLine.getByTestId("source-evidence-text")).toContainText("|LONG EVIDENCE END");

  const secondLine = page
    .getByText("Requires the Secretary to complete reader provision 2.")
    .locator("xpath=ancestor::li[1]");
  await clickForResponse(
    page,
    secondLine.getByRole("button", { name: "Read bill text" }),
    "evidence/?page=1&page_size=25&line_item_id=line-1",
  );
  await expect(secondLine.getByTestId("source-evidence-text")).toContainText("Evidence page chunk 25.");
  await clickForResponse(
    page,
    secondLine.getByRole("button", { name: "Load more source text" }),
    "evidence/?page=2&page_size=25&line_item_id=line-1",
  );
  await expect(secondLine.getByTestId("source-evidence-text")).toContainText("Evidence page chunk 26.");

  const textLink = firstLine.getByRole("link", { name: "Read full text" });
  const downloadLink = firstLine.getByRole("link", { name: "Download document" });
  await expect(textLink).toHaveAttribute("href", /\/api\/documents\/\d+\/text\/$/);
  await expect(downloadLink).toHaveAttribute("href", /\/api\/documents\/\d+\/download\/$/);
  expect((await request.get(await textLink.getAttribute("href") as string)).status()).toBe(200);
  expect((await request.get(await downloadLink.getAttribute("href") as string)).status()).toBe(200);
});

test("a visitor can inspect linked and paginated key terms", async ({ page, request }) => {
  const id = await billId(request, "HR E2E");
  await page.goto(`/bills/${id}`);
  await clickForResponse(
    page,
    page.getByText("Browse detailed provisions"),
    "reader-items/?page=1",
  );
  await expect(page.getByText("1 linked term")).toBeVisible();

  const contractId = ((await (await request.get(
    `${API_BASE}/api/bills/${id}/?contract_view=summary`,
  )).json()) as { latest_contract: { id: number } }).latest_contract.id;
  const linked = await request.get(
    `${API_BASE}/api/contracts/${contractId}/definition-items/?line_item_id=line-0`,
  );
  expect(linked.status()).toBe(200);
  expect(((await linked.json()) as { results: Array<{ term: string }> }).results[0].term)
    .toBe("covered hospital");

  await clickForResponse(
    page,
    page.getByRole("button", { name: "Key terms (27)" }),
    "definition-items/?page=1&page_size=25&unlinked=true",
  );
  await expect(page.getByText("reader term 2", { exact: true })).toBeVisible();
  await clickForResponse(
    page,
    page.getByRole("button", { name: "Show 25 more key terms" }),
    "definition-items/?page=2&page_size=25&unlinked=true",
  );
  await expect(page.getByText("reader term 27", { exact: true })).toBeVisible();
});

test("a visitor can select, search, and filter the complete voting record", async ({
  page,
  request,
}) => {
  const id = await billId(request, "HR E2E");
  await page.goto(`/bills/${id}`);
  const voting = page.getByRole("region", { name: "Voting record" });
  await expect(voting.getByRole("button", { name: "View voting record" })).toHaveCount(2);
  const rollOne = voting.locator("li", { hasText: "roll call 1" });
  await clickForResponse(
    page,
    rollOne.getByRole("button", { name: "View voting record" }),
    "/api/votes/",
  );
  await expect(voting.getByRole("heading", { name: "Yes — 2" })).toBeVisible();
  await expect(voting.getByRole("heading", { name: "Present — 1" })).toBeVisible();
  await expect(voting.getByRole("heading", { name: "Not voting — 1" })).toBeVisible();

  await voting.getByLabel("Search members").fill("Casey");
  await expect(voting.getByText("Casey Chen")).toBeVisible();
  await expect(voting.getByText("Alex Avery")).toHaveCount(0);
  await voting.getByLabel("Search members").fill("");
  await voting.getByLabel("Party").selectOption("Republican");
  await expect(voting.getByText("Drew Diaz")).toBeVisible();
  await expect(voting.getByText("Casey Chen")).toHaveCount(0);
});
