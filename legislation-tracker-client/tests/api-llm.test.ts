import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";

import {
  createBillEnhancement,
  deleteLLMSettings,
  getBillEnhancementEstimate,
  getBillEnhancements,
  getLLMSettings,
  getPublicCapabilities,
  updateLLMSettings,
  validateLLMCredential,
} from "../lib/api.ts";

const originalApiUrl = process.env.NEXT_PUBLIC_API_URL;

beforeEach(() => {
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: { cookie: "csrftoken=csrf-test-token" },
  });
});

afterEach(() => {
  process.env.NEXT_PUBLIC_API_URL = originalApiUrl;
  Reflect.deleteProperty(globalThis, "document");
});

describe("LLM API helpers", () => {
  it("loads the public deployment capability without authentication", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ url: String(url), init });
      return Response.json({ llm_enhancements: true });
    };

    const capabilities = await getPublicCapabilities();

    assert.deepEqual(capabilities, { llm_enhancements: true });
    assert.equal(requests[0].url, "http://api.test/api/capabilities/");
    assert.equal(requests[0].init, undefined);
  });

  it("uses only authenticated private settings routes", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ url: String(url), init });
      if (init?.method === "DELETE") return new Response(null, { status: 204 });
      return Response.json({ configured: true });
    };

    await getLLMSettings();
    await updateLLMSettings({ api_key: "sk-test-browser", enabled: true });
    await validateLLMCredential();
    await deleteLLMSettings();

    assert.equal(requests[0].url, "http://api.test/api/settings/llm/");
    assert.equal(requests[1].init?.method, "PUT");
    assert.equal(
      requests[1].init?.body,
      JSON.stringify({ api_key: "sk-test-browser", enabled: true }),
    );
    assert.equal(requests[2].url, "http://api.test/api/settings/llm/validate/");
    assert.equal(requests[2].init?.method, "POST");
    assert.equal(requests[3].init?.method, "DELETE");
  });

  it("sends the exact confirmed estimate identity when enhancing", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ url: String(url), init });
      return Response.json({ status: "pending" });
    };
    const confirmation = {
      source_fingerprint: "a".repeat(64),
      request_fingerprint: "b".repeat(64),
      credential_revision: 4,
    };

    await getBillEnhancementEstimate(18);
    await getBillEnhancements(18, { page: 2, pageSize: 20 });
    await createBillEnhancement(18, confirmation);

    assert.equal(
      requests[0].url,
      "http://api.test/api/bills/18/enhancements/estimate/",
    );
    assert.equal(
      requests[1].url,
      "http://api.test/api/bills/18/enhancements/?page=2&page_size=20",
    );
    assert.equal(requests[2].url, "http://api.test/api/bills/18/enhancements/");
    assert.equal(requests[2].init?.body, JSON.stringify(confirmation));
  });
});
