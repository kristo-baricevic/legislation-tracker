import { expect, test, type APIRequestContext } from "@playwright/test";

test.setTimeout(60000);

async function verifySavedConnections(request: APIRequestContext, id: number, donorName: string) {
  const endpoint = `http://127.0.0.1:18420/api/representatives/${id}/connections/?period=2026`;
  const connections = await request.get(endpoint);
  expect(connections.ok()).toBe(true);
  const donor = (await connections.json()).donors.find((item: {name: string}) => item.name === donorName);
  expect(donor).toBeDefined();
  const related = await request.get(`${endpoint}&contributor=${donor.id}`);
  expect(related.ok()).toBe(true);
  const activity = await related.json();
  expect(activity.related_representatives).toEqual(expect.arrayContaining([expect.objectContaining({id})]));
  expect(activity.bills).toEqual(expect.arrayContaining([expect.objectContaining({
    title: `Research education bill ${id}`, topics: expect.arrayContaining([expect.objectContaining({name:"Education"})])
  })]));
}

test("Research saves source-backed results and survives reopening", async ({ page }) => {
  const csrf = await page.request.get("http://127.0.0.1:18420/api/auth/csrf/");
  const login = await page.request.post("http://127.0.0.1:18420/api/auth/session/", { data: { email: "research@example.test", password: "Research-test-password-2026!" }, headers: { "X-CSRFToken": (await csrf.json()).csrf_token } });
  expect(login.status()).toBe(200);
  await page.goto("/representatives/1?congress=119&tab=funding");
  await expect(page.getByRole("heading", { name: "Research Member 1" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Research Research Member 1", exact: true })).toBeEnabled();
  const started = page.waitForResponse(response => response.url().endsWith("/1/research/") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Research Research Member 1", exact: true }).click();
  expect((await started).status()).toBe(202);
  await expect(page.getByText("$1,200.00", { exact: true })).toBeVisible({ timeout: 30000 });
  await expect(page.getByText("This member serves New York in Congress. The member previously worked in public service.")).toBeVisible({ timeout: 30000 });
  await expect(page.getByRole("list", {name:"Contribution records"}).getByText("Education Example PAC", {exact:true})).toBeVisible({ timeout: 30000 });
  await expect(page.getByRole("list", {name:/^(Contribution|Refund) records$/}).getByText("$150.00", {exact:true})).toBeVisible();
  await page.getByRole("button",{name:"Refunds",exact:true}).click();
  await expect(page.getByRole("list", {name:/^(Contribution|Refund) records$/}).getByText("$25.00", {exact:true})).toBeVisible();
  const saved = await page.request.get("http://127.0.0.1:18420/api/representatives/1/research/?period=2026");
  expect((await saved.json()).snapshot).toBeTruthy();
  await page.reload();
  await expect(page.getByRole("button", { name: "Refresh research" })).toBeEnabled();
  await verifySavedConnections(page.request, 1, "Education Example PAC");
});

for (const [id, expected] of [[2, "Campaign contributors"], [3, "No matching FEC candidate was found. Retry research or have the candidate identity checked."]] as const) {
  test(`Research handles representative ${id} without inventing missing finance data`, async ({ page }) => {
    const csrf = await page.request.get("http://127.0.0.1:18420/api/auth/csrf/");
    const login = await page.request.post("http://127.0.0.1:18420/api/auth/session/", { data: { email: "research@example.test", password: "Research-test-password-2026!" }, headers: { "X-CSRFToken": (await csrf.json()).csrf_token } });
    expect(login.ok()).toBeTruthy();
    await page.goto(`/representatives/${id}?congress=119&tab=funding`);
    await page.getByRole("button", { name: `Research Research Member ${id}`, exact: true }).click();
    await expect(id === 2 ? page.getByRole("region", {name:expected}) : page.getByText(expected, { exact: true })).toBeVisible({ timeout: 30000 });
    await expect(page.getByRole("button", { name: "Refresh research" })).toBeEnabled();
    if (id === 3) await expect(page.getByRole("list", {name:/^(Contribution|Refund) records$/}).getByText("$150.00", {exact:true})).toHaveCount(0);
    if (id === 2) {
      await expect(page.getByRole("list", {name:/^(Contribution|Refund) records$/}).getByText("$150.00", {exact:true})).toHaveCount(2);
      const stored = await page.request.get("http://127.0.0.1:18420/api/representatives/2/contributors/?period=2026");
      expect((await stored.json()).totals.observed_itemized_contributions).toBe("300");
    }
  });
}

test("recorded amended receipts and refunds survive the full research flow", async ({ page }) => {
  const csrf = await page.request.get("http://127.0.0.1:18420/api/auth/csrf/");
  await page.request.post("http://127.0.0.1:18420/api/auth/session/", { data: { email: "research@example.test", password: "Research-test-password-2026!" }, headers: { "X-CSRFToken": (await csrf.json()).csrf_token } });
  await page.goto("/representatives/4?congress=119&tab=funding");
  await page.getByRole("button", { name: "Research Research Member 4", exact: true }).click();
  await expect(page.getByRole("list", {name:/^(Contribution|Refund) records$/}).getByText("$5,000.00", {exact:true})).toBeVisible({ timeout: 30000 });
  await expect(page.getByRole("list", {name:/^(Contribution|Refund) records$/}).getByText("$2,000.00", {exact:true})).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh research" })).toBeEnabled({ timeout: 30000 });
  const response = await page.request.get("http://127.0.0.1:18420/api/representatives/4/contributors/?period=2026");
  const saved = await response.json();
  expect(Number(saved.totals.observed_itemized_contributions)).toBe(7000);
  expect(Number(saved.totals.observed_itemized_refunds)).toBe(400);
  expect(saved.totals.net).toBeNull();
  expect(saved.status).toBe("partial");
  await verifySavedConnections(page.request, 4, "AMERICAN FEDERATION OF TEACHERS COPE");
});
