import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { resolveAllowedCongressActionUrl } from "../app/api/congress/action/allowlisted-url.ts";

describe("resolveAllowedCongressActionUrl", () => {
  it("allows Congress API URLs and injects the configured API key", () => {
    const url = resolveAllowedCongressActionUrl(
      "https://api.congress.gov/v3/bill/119/hr/1/actions",
      "server-key",
    );

    assert.equal(
      url?.toString(),
      "https://api.congress.gov/v3/bill/119/hr/1/actions?api_key=server-key",
    );
  });

  it("replaces caller-supplied Congress API keys with the configured API key", () => {
    const url = resolveAllowedCongressActionUrl(
      "https://api.congress.gov/v3/bill/119/hr/1/actions?api_key=attacker-key",
      "server-key",
    );

    assert.equal(url?.searchParams.get("api_key"), "server-key");
  });

  it("allows official House clerk vote URLs without adding an API key", () => {
    const url = resolveAllowedCongressActionUrl(
      "https://clerk.house.gov/evs/2025/roll001.xml",
      "server-key",
    );

    assert.equal(
      url?.toString(),
      "https://clerk.house.gov/evs/2025/roll001.xml",
    );
  });

  it("rejects non-allowlisted and non-HTTPS URLs", () => {
    assert.equal(
      resolveAllowedCongressActionUrl("https://api.congress.gov.evil.test/x", "key"),
      null,
    );
    assert.equal(resolveAllowedCongressActionUrl("http://api.congress.gov/v3/x", "key"), null);
    assert.equal(resolveAllowedCongressActionUrl("http://169.254.169.254/latest", "key"), null);
    assert.equal(resolveAllowedCongressActionUrl("not-a-url", "key"), null);
  });
});
