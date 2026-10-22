import { expect, test } from "@playwright/test";

test.setTimeout(60000);

test("Research saves source-backed results and survives reopening", async ({ page }) => {
  const csrf = await page.request.get("http://127.0.0.1:18420/api/auth/csrf/");
  const login = await page.request.post("http://127.0.0.1:18420/api/auth/session/", { data: { email: "research@example.test", password: "Research-test-password-2026!" }, headers: { "X-CSRFToken": (await csrf.json()).csrf_token } });
  expect(login.status()).toBe(200);
  await page.goto("/representatives/1?congress=119");
  await expect(page.getByRole("heading", { name: "Research Member 1" })).toBeVisible();
  await expect(page.getByText(/Not researched yet/)).toBeVisible();
  const started = page.waitForResponse(response => response.url().endsWith("/1/research/") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Research", exact: true }).click();
  expect((await started).status()).toBe(202);
  await expect(page.getByText("$1,200.00", { exact: true })).toBeVisible({ timeout: 30000 });
  await expect(page.getByText("This member serves New York in Congress. The member previously worked in public service.")).toBeVisible({ timeout: 30000 });
  await expect(page.getByRole("cell", { name: "Education Example PAC", exact: false })).toBeVisible({ timeout: 30000 });
  await expect(page.getByRole("cell", { name: "$150.00" })).toBeVisible();
  await page.getByLabel("Record type").selectOption("refund");
  await expect(page.getByRole("cell", { name: "$25.00" })).toBeVisible();
  const saved = await page.request.get("http://127.0.0.1:18420/api/representatives/1/research/?period=2026");
  expect((await saved.json()).snapshot).toBeTruthy();
  await page.reload();
  await expect(page.getByRole("button", { name: "Refresh research" })).toBeEnabled();
  await page.getByRole("button", { name: "Explore connections ▾" }).click();
  await expect(page.getByRole("button", { name: "Education Example PAC" })).toBeVisible();
  await page.getByRole("button", { name: "Education Example PAC" }).click();
  await page.getByRole("button", { name: "Research Member 1", exact: true }).click();
  await expect(page.getByRole("region", { name: "Selected representative activity" }).getByRole("link", { name: "HR 1: Research education bill 1", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Selected representative activity" }).getByRole("link", { name: "Education", exact: true })).toBeVisible();
});

for (const [id, expected] of [[2, "Campaign contributors"], [3, "No matching FEC candidate was found. Retry research or have the candidate identity checked."]] as const) {
  test(`Research handles representative ${id} without inventing missing finance data`, async ({ page }) => {
    const csrf = await page.request.get("http://127.0.0.1:18420/api/auth/csrf/");
    const login = await page.request.post("http://127.0.0.1:18420/api/auth/session/", { data: { email: "research@example.test", password: "Research-test-password-2026!" }, headers: { "X-CSRFToken": (await csrf.json()).csrf_token } });
    expect(login.ok()).toBeTruthy();
    await page.goto(`/representatives/${id}?congress=119`);
    await page.getByRole("button", { name: "Research", exact: true }).click();
    await expect(page.getByText(expected, { exact: true })).toBeVisible({ timeout: 30000 });
    await expect(page.getByRole("button", { name: "Refresh research" })).toBeEnabled();
    if (id === 3) await expect(page.getByRole("cell", { name: "$150.00" })).toHaveCount(0);
    if (id === 2) {
      await expect(page.getByRole("cell", { name: "$150.00" })).toHaveCount(2);
      const stored = await page.request.get("http://127.0.0.1:18420/api/representatives/2/contributors/?period=2026");
      expect((await stored.json()).totals.observed_itemized_contributions).toBe("300");
    }
  });
}

test("recorded amended receipts and refunds survive the full research flow", async ({ page }) => {
  const csrf = await page.request.get("http://127.0.0.1:18420/api/auth/csrf/");
  await page.request.post("http://127.0.0.1:18420/api/auth/session/", { data: { email: "research@example.test", password: "Research-test-password-2026!" }, headers: { "X-CSRFToken": (await csrf.json()).csrf_token } });
  await page.goto("/representatives/4?congress=119");
  await page.getByRole("button", { name: "Research", exact: true }).click();
  await expect(page.getByRole("cell", { name: "$5,000.00" })).toBeVisible({ timeout: 30000 });
  await expect(page.getByRole("cell", { name: "$2,000.00" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh research" })).toBeEnabled({ timeout: 30000 });
  const response = await page.request.get("http://127.0.0.1:18420/api/representatives/4/contributors/?period=2026");
  const saved = await response.json();
  expect(Number(saved.totals.observed_itemized_contributions)).toBe(7000);
  expect(Number(saved.totals.observed_itemized_refunds)).toBe(400);
  expect(saved.totals.net).toBeNull();
  expect(saved.status).toBe("partial");
  await page.getByRole("button", { name: "Explore connections ▾" }).click();
  await expect(page.getByRole("button", { name: "AMERICAN FEDERATION OF TEACHERS COPE", exact: true })).toBeVisible();
  await expect(page.getByRole("img", { name: "Recorded connections map" })).toHaveCount(0);
  await page.getByRole("button", { name: "AMERICAN FEDERATION OF TEACHERS COPE", exact: true }).click();
  await page.getByRole("button", { name: "Research Member 4", exact: true }).click();
  await expect(page.getByRole("link", { name: "HR 4: Research education bill 4", exact: true })).toBeVisible();
});
