import { expect, test } from "@playwright/test";

const API_BASE = process.env.E2E_API_URL ?? "http://127.0.0.1:18000";
const sourceFirst = process.env.LLM_SOURCE_FIRST_ENABLED === "True";

for (const billNumber of (sourceFirst ? ["HR SOURCE E2E"] : ["HR SOURCE E2E", "HR READER E2E"])) {
test(`a user saves a key and reads a durable enhancement for ${billNumber}`, async ({
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
    `${API_BASE}/api/bills/?bill_number=${encodeURIComponent(billNumber)}`,
  );
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: Array<{ id: number; bill_number: string }> };
  const bill = body.results.find(item => item.bill_number === billNumber);
  expect(bill).toBeDefined();
  const billId = bill!.id;

  const sessionResponse = await request.post(`${API_BASE}/api/auth/session/`, {
    headers: { "X-CSRFToken": csrfToken! },
    data: { email, password },
  });
  expect(sessionResponse.status()).toBe(200);
  await page.context().addCookies((await request.storageState()).cookies);
  const reader = billNumber === "HR READER E2E";
  async function captureView(state: string) {
    if (!reader) return;
    for (const width of [1280, 390]) {
      await page.setViewportSize({width, height: 880});
      await page.screenshot({fullPage: true, path: test.info().outputPath(`simulated-reader-${state}-${width}.png`)});
    }
    await page.setViewportSize({width: 1280, height: 880});
  }
  if (reader) {
    await page.goto("/settings");
    await expect(page.getByLabel("Provider", {exact: true})).toBeVisible();
    await captureView("settings");
  }
  await page.goto(`/bills/${billId}`);
  await expect(page.getByRole("button", { name: "Enhance", exact: true })).toBeEnabled();
  await captureView("original");
  await page.getByRole("button", { name: "Enhance", exact: true }).click();
  const confirmation = page.getByRole("dialog", { name: "Confirm enhancement" });
  await expect(confirmation).toContainText("estimated input tokens");
  await expect(confirmation).toContainText("provider may charge your account");
  await captureView("estimate");
  if (sourceFirst) await expect(confirmation).toContainText(/Up to \d+ calls/);
  await page.getByRole("button", { name: "Confirm and enhance" }).click();

  await expect(page.getByRole("button", { name: /Queued…|Enhancing…|Enhanced/ }).first()).toBeVisible();
  const enhanced = page.getByRole("button", { name: "Enhanced", exact: true });
  await expect(enhanced).toBeEnabled({ timeout: 25_000 });
  await enhanced.click();
  await expect(enhanced).toHaveAttribute("aria-pressed", "true");
  const summary = reader ? "Rural hospitals would receive $100 in grants." : sourceFirst
    ? "The Secretary must award $100 in grants to rural hospitals."
    : "The bill directs the Secretary to award grants to rural hospitals.";
  await expect(page.getByRole("paragraph").filter({hasText: summary}).first()).toBeVisible();
  await page.getByRole("button", { name: "Original", exact: true }).click();
  await expect(enhanced).toHaveAttribute("aria-pressed", "false");
  await page.reload();
  await enhanced.click();
  await expect(page.getByRole("paragraph").filter({hasText: summary}).first()).toBeVisible();

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
  const result = (await detailResponse.json()).result;
  if (reader) {
    expect(result.schema_version).toBe("1.4");
    expect(result.source_review.financial_items[0].amount_display).toBe("$100");
    await page.getByRole("tab", {name: "Money"}).click();
    await expect(page.getByRole("tabpanel").filter({hasText: "$100"})).toBeVisible();
    await captureView("money");
    const citation = page.getByRole("tabpanel").getByRole("button", {name: /Source 1/}).first();
    await citation.focus();
    await page.keyboard.press("Enter");
    const evidence = page.getByRole("dialog", {name: /Source 1/});
    await expect(evidence.getByRole("link", {name: "Read bill text"})).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(citation).toBeFocused();
  } else if (sourceFirst) {
    expect(result.schema_version).toBe("2.0-source-first");
    expect(result.quality.semantic_review_status).toBe("unreviewed");
  } else {
    expect(result.overview[0].cited_sources).toEqual(expect.arrayContaining([
      expect.objectContaining({source_ref: "src_0001"}),
    ]));
  }
});
}
