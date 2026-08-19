import { expect, test } from "@playwright/test";

const API_BASE = "http://localhost:8000";
const token = "e2e-access-token";
const corsHeaders = { "access-control-allow-origin": "http://127.0.0.1:3100" };

test("an authenticated user follows a topic and sees the persisted state", async ({ page }) => {
  const trackedTopics = [
    {
      id: 1,
      topic: { id: 7, name: "Health", slug: "health" },
      created_at: "2026-08-19T00:00:00Z",
    },
  ];
  let postedTopicId: number | undefined;

  await page.addInitScript((accessToken) => {
    localStorage.setItem("legislation_tracker_access", accessToken);
  }, token);
  await page.route(`${API_BASE}/api/topics/`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      headers: corsHeaders,
      body: JSON.stringify([
        { id: 7, name: "Health", slug: "health" },
        { id: 8, name: "Education", slug: "education" },
      ]),
    });
  });
  await page.route(`${API_BASE}/api/tracking/topics/`, async (route) => {
    const request = route.request();
    expect(request.headers().authorization).toBe(`Bearer ${token}`);
    if (request.method() === "GET") {
      await route.fulfill({
        contentType: "application/json",
        headers: corsHeaders,
        body: JSON.stringify(trackedTopics),
      });
      return;
    }
    expect(request.method()).toBe("POST");
    const topicId = request.postDataJSON().topic;
    if (typeof topicId !== "number") {
      throw new Error("Tracking request must include a numeric topic ID");
    }
    postedTopicId = topicId;
    trackedTopics.push({
      id: 2,
      topic: { id: topicId, name: "Education", slug: "education" },
      created_at: "2026-08-19T00:01:00Z",
    });
    await route.fulfill({
      contentType: "application/json",
      headers: corsHeaders,
      body: JSON.stringify(trackedTopics[1]),
    });
  });

  await page.goto("/topics");

  await expect(page.getByRole("heading", { name: "Topics" })).toBeVisible();
  const follow = page.getByRole("button", { name: "Follow", exact: true });
  await expect(follow).toBeVisible();
  const followRequest = page.waitForRequest(
    (request) => request.url() === `${API_BASE}/api/tracking/topics/` && request.method() === "POST",
  );
  await follow.click();
  await followRequest;

  await expect(page.getByRole("button", { name: "Following" })).toHaveCount(2);
  expect(postedTopicId).toBe(8);

  const persisted = await page.evaluate(async ({ apiBase, accessToken }) => {
    const response = await fetch(`${apiBase}/api/tracking/topics/`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return response.json();
  }, { apiBase: API_BASE, accessToken: token });
  expect(persisted).toHaveLength(2);
  expect(persisted[1].topic.id).toBe(8);
});
