import assert from "node:assert/strict";
import { describe, it } from "node:test";

import nextConfig from "../next.config.ts";

describe("Next document security headers", () => {
  it("applies a compatible restrictive policy to every route", async () => {
    assert.equal(typeof nextConfig.headers, "function");
    const rules = await nextConfig.headers!();
    const catchAll = rules.find((rule) => rule.source === "/:path*");
    const headers = new Map(
      catchAll?.headers.map((header) => [header.key, header.value]),
    );

    assert.match(headers.get("Content-Security-Policy") ?? "", /default-src 'self'/);
    assert.match(headers.get("Content-Security-Policy") ?? "", /object-src 'none'/);
    assert.match(headers.get("Content-Security-Policy") ?? "", /frame-ancestors 'none'/);
    assert.match(headers.get("Content-Security-Policy") ?? "", /img-src 'self' data: blob: https:/);
    assert.equal(headers.get("X-Content-Type-Options"), "nosniff");
    assert.equal(headers.get("Referrer-Policy"), "strict-origin-when-cross-origin");
    assert.equal(headers.get("Permissions-Policy"), "camera=(), microphone=(), geolocation=()")
  });
});
