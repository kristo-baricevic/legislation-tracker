import { expect, test } from "@playwright/test";

const API_BASE = "http://127.0.0.1:18000";

test("a signed-in user confirms one mocked enhancement and sees server-owned citations", async ({
  page,
  request,
}) => {
  const response = await request.get(
    `${API_BASE}/api/bills/?bill_number=${encodeURIComponent("HR E2E")}`,
  );
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: Array<{ id: number }> };
  const billId = body.results[0].id;
  const sourceFingerprint = "a".repeat(64);
  const requestFingerprint = "b".repeat(64);
  let enhancementStarted = false;
  let detailPolls = 0;

  await page.addInitScript(() => {
    localStorage.setItem("legislation_tracker_access", "e2e-access-token");
    localStorage.setItem("legislation_tracker_refresh", "e2e-refresh-token");
  });
  await page.route("**/api/capabilities/", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ llm_enhancements: true }),
    });
  });
  await page.route("**/api/tracking/", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ bills: [], topics: [], legislators: [], is_staff: false }),
    });
  });
  await page.route("**/api/bills/*/enhancements/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/estimate/")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          feature_available: true,
          can_enhance: true,
          unavailable_reason: null,
          credential_revision: 2,
          provider: "openai",
          requested_model: "gpt-5.6-luna",
          reasoning_effort: "none",
          prompt_version: "1.0",
          output_schema_version: "1.1",
          source_packet_version: "1.0",
          source_fingerprint: sourceFingerprint,
          request_fingerprint: requestFingerprint,
          serialized_request_bytes: 1200,
          estimated_input_tokens: 600,
          max_output_tokens: 4000,
          max_output_includes_reasoning: true,
          truncated: false,
          coverage_notice: null,
          source_description: "contract_evidence",
          matching_enhancement: null,
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/latest/")) {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ error: "not_found" }),
      });
      return;
    }
    if (route.request().method() === "POST") {
      enhancementStarted = true;
      expect(route.request().postDataJSON()).toEqual({
        source_fingerprint: sourceFingerprint,
        request_fingerprint: requestFingerprint,
        credential_revision: 2,
      });
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify(enhancementPayload("pending")),
      });
      return;
    }
    detailPolls += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(enhancementPayload(detailPolls > 0 ? "succeeded" : "running")),
    });
  });

  function enhancementPayload(status: "pending" | "running" | "succeeded") {
    const succeeded = status === "succeeded";
    return {
      id: 41,
      bill_id: billId,
      status,
      provider: "openai",
      requested_model: "gpt-5.6-luna",
      reasoning_effort: "none",
      prompt_version: "1.0",
      output_schema_version: "1.1",
      source_packet_version: "1.0",
      source_fingerprint: sourceFingerprint,
      request_fingerprint: requestFingerprint,
      truncated: false,
      coverage_notice: null,
      disclaimer: "AI-generated legal information for review, not legal advice.",
      usage: {
        input_tokens: succeeded ? 100 : null,
        output_tokens: succeeded ? 20 : null,
        total_tokens: succeeded ? 120 : null,
      },
      created_at: "2026-08-21T00:00:00Z",
      updated_at: "2026-08-21T00:00:00Z",
      completed_at: succeeded ? "2026-08-21T00:01:00Z" : null,
      latest_attempt: null,
      result: succeeded
        ? {
            schema_version: "1.1",
            overview: [
              {
                text: "The bill directs the Secretary to award grants.",
                source_refs: ["src_0001"],
                cited_sources: [
                  {
                    source_ref: "src_0001",
                    label: "Cited source",
                    quoted_text:
                      "The Secretary of Health and Human Services shall award grants to rural hospitals.",
                    section_label: "SEC. 2",
                    start_char: 35,
                    end_char: 119,
                  },
                ],
              },
            ],
            key_impacts: [],
            obligations: [],
            funding_and_timing: [],
            uncertain_language: [],
          }
        : null,
      attempts: [],
      poll_after_seconds: succeeded ? null : 1,
      stale: false,
    };
  }

  await page.goto(`/bills/${billId}`);
  await page.getByRole("button", { name: "Enhance with AI" }).click();
  const confirmation = page.getByRole("dialog", { name: "Confirm AI enhancement" });
  await expect(confirmation).toContainText("600 estimated input tokens");
  await expect(confirmation).toContainText("provider may charge your account");
  await page.getByRole("button", { name: "Confirm and enhance" }).click();

  await expect(page.getByText("The bill directs the Secretary to award grants.")).toBeVisible();
  await expect(page.getByText("Cited source")).toBeVisible();
  expect(enhancementStarted).toBe(true);
  expect(detailPolls).toBe(1);
});
