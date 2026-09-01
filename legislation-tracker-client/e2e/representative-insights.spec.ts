import { expect, test } from "@playwright/test";

const API_BASE = "http://127.0.0.1:18000";

type Representative = {
  id: number;
  name: string;
  chamber: string;
};

test("a visitor can audit current representative evidence and a pairwise comparison", async ({
  page,
  request,
}) => {
  const response = await request.get(`${API_BASE}/api/representatives/?chamber=house`);
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: Representative[] };
  const alex = body.results.find((person) => person.name === "Alex Avery");
  const blair = body.results.find((person) => person.name === "Blair Brooks");
  expect(alex).toBeDefined();
  expect(blair).toBeDefined();

  await page.goto(`/representatives/${alex!.id}?congress=119`);
  await expect(page.getByRole("heading", { name: "Alex Avery" })).toBeVisible();
  await expect(page.getByText("2 / 2 roll calls")).toBeVisible();
  await expect(
    page.getByText("Complete official roll-call coverage."),
  ).toBeVisible();
  await expect(page.getByText("Rules Committee")).toBeVisible();
  await expect(page.getByRole("link", { name: /HR E2E: Rural Hospital Grants Act/ })).toBeVisible();

  await page.goto(
    `/representatives/compare?ids=${alex!.id},${blair!.id}&congress=119`,
  );
  await expect(
    page.getByRole("heading", { name: "Shared vote evidence" }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "1 agreements and 1 disagreements across 2 shared yes/no votes (50% agreement).",
    ),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "View bill" })).toBeVisible();
});
