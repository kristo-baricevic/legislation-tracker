import { expect, test } from "@playwright/test";

const API_BASE = process.env.E2E_API_URL ?? "http://127.0.0.1:18000";
const sourceFirst = process.env.LLM_SOURCE_FIRST_ENABLED === "True";

test("a user saves a key and completes a durable enhancement through the live API", async ({
  page,
  request,
}) => {
  const email = `llm-e2e-${Date.now()}-${Math.random().toString(36).slice(2)}@example.test`;
  const password = "E2e-secure-password-2026!";
  await request.get(`${API_BASE}/api/auth/csrf/`);
  const csrfToken = (await request.storageState()).cookies.find(
    (cookie) => cookie.name === "csrftoken",
  )?.value;
  expect(csrfToken).toBeTruthy();
  const registration = await request.post(`${API_BASE}/api/auth/register/`, {
    headers: { "X-CSRFToken": csrfToken! },
    data: { email, password },
  });
  expect(registration.status()).toBe(202);

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
    `${API_BASE}/api/bills/?bill_number=${encodeURIComponent(sourceFirst ? "HR SOURCE E2E" : "HR E2E")}`,
  );
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: Array<{ id: number }> };
  const billId = body.results[0].id;

  const sessionResponse = await request.post(`${API_BASE}/api/auth/session/`, {
    headers: { "X-CSRFToken": csrfToken! },
    data: { email, password },
  });
  expect(sessionResponse.status()).toBe(200);
  await page.context().addCookies((await request.storageState()).cookies);
  await page.goto(`/bills/${billId}`);
  await page.getByRole("button", { name: "Enhance with AI" }).click();
  const confirmation = page.getByRole("dialog", { name: "Confirm AI enhancement" });
  await expect(confirmation).toContainText("estimated input tokens");
  await expect(confirmation).toContainText("provider may charge your account");
  if (sourceFirst) await expect(confirmation).toContainText(/Up to \d+ calls/);
  await page.getByRole("button", { name: "Confirm and enhance" }).click();

  await expect(page.getByRole("status")).toContainText(/pending|running/);
  if (sourceFirst) {
    await expect(page.getByText("The Secretary must award $100 in grants to rural hospitals.", { exact: true }).first()).toBeVisible({ timeout: 15_000 });
    await page.getByText("Source text", { exact: true }).first().click();
    await expect(page.getByRole("link", { name: "Read source" }).first()).toHaveAttribute("href", /\/documents\/\d+/);
    const latest = await request.get(`${API_BASE}/api/bills/${billId}/enhancements/latest/`, { headers });
    expect(latest.status()).toBe(200);
    const persisted = await latest.json();
    expect(persisted.result.schema_version).toBe("2.0-source-first");
    expect(persisted.published_attempt_id).toBeTruthy();
    expect(persisted.result.quality.semantic_review_status).toBe("unreviewed");
    await page.reload();
    await expect(page.getByText("The Secretary must award $100 in grants to rural hospitals.", { exact: true }).first()).toBeVisible();
    return;
  }
  await expect(
    page.getByText("The bill directs the Secretary to award grants to rural hospitals."),
  ).toBeVisible({ timeout: 15_000 });
  const overviewItem = page.getByRole("listitem").filter({
    hasText: "The bill directs the Secretary to award grants to rural hospitals.",
  });
  await expect(overviewItem.getByText("Cited source", { exact: true })).toBeHidden();
  await overviewItem.getByText("Read bill text", { exact: true }).click();
  await expect(overviewItem.getByText("Cited source", { exact: true })).toBeVisible();

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
