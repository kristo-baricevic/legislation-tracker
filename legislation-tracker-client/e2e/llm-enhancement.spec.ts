import { expect, test } from "@playwright/test";

const API_BASE = "http://127.0.0.1:18000";

test("a user saves a key and completes a durable enhancement through the live API", async ({
  page,
  request,
}) => {
  const email = `llm-e2e-${Date.now()}-${Math.random().toString(36).slice(2)}@example.test`;
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
  const headers = { Authorization: `Bearer ${access}` };

  const saved = await request.put(`${API_BASE}/api/settings/llm/`, {
    headers,
    data: { api_key: "e2e-user-owned-key", enabled: true },
  });
  expect(saved.status()).toBe(200);
  expect(await saved.json()).toEqual(
    expect.objectContaining({
      configured: true,
      provider: "e2e",
      key_suffix: "-key",
      validation_status: "unverified",
    }),
  );
  expect(await saved.text()).not.toContain("e2e-user-owned-key");

  const validated = await request.post(`${API_BASE}/api/settings/llm/validate/`, {
    headers,
  });
  expect(validated.status()).toBe(200);
  expect(await validated.json()).toEqual(
    expect.objectContaining({ validation_status: "valid", enabled: true }),
  );

  const response = await request.get(
    `${API_BASE}/api/bills/?bill_number=${encodeURIComponent("HR E2E")}`,
  );
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: Array<{ id: number }> };
  const billId = body.results[0].id;

  await page.addInitScript((accessToken) => {
    localStorage.setItem("legislation_tracker_access", accessToken);
  }, access);
  await page.goto(`/bills/${billId}`);
  await page.getByRole("button", { name: "Enhance with AI" }).click();
  const confirmation = page.getByRole("dialog", { name: "Confirm AI enhancement" });
  await expect(confirmation).toContainText("estimated input tokens");
  await expect(confirmation).toContainText("provider may charge your account");
  await page.getByRole("button", { name: "Confirm and enhance" }).click();

  await expect(page.getByRole("status")).toContainText(/pending|running/);
  await expect(
    page.getByText("The bill directs the Secretary to award grants to rural hospitals."),
  ).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Cited source").first()).toBeVisible();

  const historyResponse = await request.get(
    `${API_BASE}/api/bills/${billId}/enhancements/`,
    { headers },
  );
  expect(historyResponse.status()).toBe(200);
  const history = (await historyResponse.json()) as {
    count: number;
    results: Array<{ id: number; status: string }>;
  };
  expect(history.count).toBe(1);
  expect(history.results[0].status).toBe("succeeded");

  const detailResponse = await request.get(
    `${API_BASE}/api/bills/${billId}/enhancements/${history.results[0].id}/`,
    { headers },
  );
  expect(detailResponse.status()).toBe(200);
  expect(await detailResponse.json()).toEqual(
    expect.objectContaining({
      status: "succeeded",
      result: expect.objectContaining({
        overview: expect.arrayContaining([
          expect.objectContaining({
            cited_sources: expect.arrayContaining([
              expect.objectContaining({ source_ref: "src_0001" }),
            ]),
          }),
        ]),
      }),
    }),
  );
});
