import { expect, test } from "@playwright/test";

const API_BASE = "http://127.0.0.1:18000";

test("an authenticated user follows a topic and the live API persists it", async ({
  page,
  request,
}) => {
  const email = `e2e-${Date.now()}-${Math.random().toString(36).slice(2)}@example.test`;
  const password = "e2e-password";

  const registration = await request.post(`${API_BASE}/api/auth/register/`, {
    data: { email, password },
  });
  expect(registration.status()).toBe(201);

  const tokenResponse = await request.post(`${API_BASE}/api/auth/token/`, {
    data: { email, password },
  });
  expect(tokenResponse.status()).toBe(200);
  const { access } = (await tokenResponse.json()) as { access: string };

  const topicsResponse = await request.get(`${API_BASE}/api/topics/`);
  expect(topicsResponse.status()).toBe(200);
  const topics = (await topicsResponse.json()) as Array<{
    id: number;
    name: string;
  }>;
  const education = topics.find((topic) => topic.name === "Education");
  expect(education).toBeDefined();

  await page.addInitScript((accessToken) => {
    localStorage.setItem("legislation_tracker_access", accessToken);
  }, access);
  await page.goto("/topics");

  await expect(page.getByRole("heading", { name: "Policy Topics" })).toBeVisible();
  const educationCard = page.getByRole("link", { name: "Education" }).locator("xpath=../..");
  await expect(educationCard.getByRole("button", { name: "Follow", exact: true })).toBeVisible();
  await educationCard.getByRole("button", { name: "Follow", exact: true }).click();
  await expect(educationCard.getByRole("button", { name: "Following", exact: true })).toBeVisible();

  const persisted = await request.get(`${API_BASE}/api/tracking/topics/`, {
    headers: { Authorization: `Bearer ${access}` },
  });
  expect(persisted.status()).toBe(200);
  expect(await persisted.json()).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ topic: expect.objectContaining({ id: education?.id }) }),
    ]),
  );
});
