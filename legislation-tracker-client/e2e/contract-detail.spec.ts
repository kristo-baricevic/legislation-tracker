import { expect, test } from "@playwright/test";

const API_BASE = "http://127.0.0.1:18000";

test("a generated v2 contract renders claims with exact source evidence", async ({
  page,
  request,
}) => {
  const response = await request.get(
    `${API_BASE}/api/bills/?bill_number=${encodeURIComponent("HR E2E")}`,
  );
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: Array<{ id: number }> };
  expect(body.results).toHaveLength(1);

  await page.goto(`/bills/${body.results[0].id}`);

  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Requirements" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Funding" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Timelines" })).toBeVisible();
  const requirements = page.getByRole("region", { name: "Requirements" });
  await expect(
    requirements.getByText(
      "The Secretary of Health and Human Services is required to award grants to rural hospitals.",
    ),
  ).toBeVisible();

  await requirements
    .getByLabel("Source evidence for Requirements item 1")
    .click();
  await expect(
    requirements.getByText(
      "The Secretary of Health and Human Services shall award grants to rural hospitals.",
    ),
  ).toBeVisible();
});
