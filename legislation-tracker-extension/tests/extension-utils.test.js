const assert = require("node:assert/strict");
const { describe, it } = require("node:test");

const {
  AUTH_REFRESH_KEY,
  AUTH_TOKEN_KEY,
  DEFAULT_API_BASE,
  DEFAULT_APP_BASE,
  buildJsonRequest,
  escapeHtml,
  formatPercent,
  getBillUrl,
  getTopicTrackingPath,
  normalizeBaseUrl,
  originPermissionForBaseUrl,
} = require("../extension-utils.js");

describe("extension utilities", () => {
  it("keeps extension auth keys aligned with the web app", () => {
    assert.equal(AUTH_TOKEN_KEY, "legislation_tracker_access");
    assert.equal(AUTH_REFRESH_KEY, "legislation_tracker_refresh");
  });

  it("normalizes configured API and app base URLs independently", () => {
    assert.equal(DEFAULT_API_BASE, "http://localhost:8000");
    assert.equal(DEFAULT_APP_BASE, "http://localhost:3000");
    assert.equal(normalizeBaseUrl(" https://tracker.example.com/ "), "https://tracker.example.com");
    assert.equal(normalizeBaseUrl("", DEFAULT_API_BASE), DEFAULT_API_BASE);
  });

  it("builds app bill URLs without deriving the app origin from the API origin", () => {
    assert.equal(getBillUrl("https://app.example.com/", 42), "https://app.example.com/bills/42");
  });

  it("derives a Chrome host permission only for HTTP(S) API origins", () => {
    assert.equal(
      originPermissionForBaseUrl("https://api.example.com/v1/"),
      "https://api.example.com/*",
    );
    assert.equal(
      originPermissionForBaseUrl("http://localhost:8000"),
      "http://localhost:8000/*",
    );
    assert.throws(
      () => originPermissionForBaseUrl("javascript:alert(1)"),
      /HTTP or HTTPS/,
    );
  });

  it("builds JSON requests with optional bearer auth", () => {
    assert.deepEqual(buildJsonRequest("POST", { bill: 42 }, "token-123"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer token-123",
      },
      body: JSON.stringify({ bill: 42 }),
    });
    assert.deepEqual(buildJsonRequest("POST", { topic_id: 5 }, ""), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic_id: 5 }),
    });
  });

  it("uses the tracking collection for topic follow actions", () => {
    assert.equal(getTopicTrackingPath(), "/api/tracking/topics/");
  });

  it("escapes API-controlled text before rendering HTML", () => {
    assert.equal(escapeHtml(`<b>"Health" & jobs</b>`), "&lt;b&gt;&quot;Health&quot; &amp; jobs&lt;/b&gt;");
  });

  it("formats confidence scores defensively", () => {
    assert.equal(formatPercent(0.456), "46%");
    assert.equal(formatPercent(undefined), "");
  });
});
