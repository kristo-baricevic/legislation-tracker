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
  await expect(page.getByRole("link", { name: "Campaign contribution evidence" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Education", exact: true })).toBeVisible();
});

for (const [id, expected] of [[2, "Campaign contributors"], [3, "The campaign identity needs verification before donor records can be attached."]] as const) {
  test(`Research handles representative ${id} without inventing missing finance data`, async ({ page }) => {
    const csrf = await page.request.get("http://127.0.0.1:18420/api/auth/csrf/");
    const login = await page.request.post("http://127.0.0.1:18420/api/auth/session/", { data: { email: "research@example.test", password: "Research-test-password-2026!" }, headers: { "X-CSRFToken": (await csrf.json()).csrf_token } });
    expect(login.ok()).toBeTruthy();
    await page.goto(`/representatives/${id}?congress=119`);
    await page.getByRole("button", { name: "Research", exact: true }).click();
    await expect(page.getByText(expected, { exact: true })).toBeVisible({ timeout: 30000 });
    await expect(page.getByRole("button", { name: "Refresh research" })).toBeEnabled();
    if (id === 3) await expect(page.getByRole("cell", { name: "$150.00" })).toHaveCount(0);
  });
}
