import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { describe, it } from "node:test";

describe("tracking UI controls", () => {
  it("bill detail can track and untrack a bill", async () => {
    const source = await readFile("app/bills/[id]/page.tsx", "utf8");

    assert.equal(source.includes("trackBill"), true);
    assert.equal(source.includes("untrackBill"), true);
    assert.equal(source.includes("Track bill"), true);
  });

  it("bill list can track selected topics", async () => {
    const source = await readFile("app/bills/page.tsx", "utf8");

    assert.equal(source.includes("trackTopic"), true);
    assert.equal(source.includes("untrackTopic"), true);
    assert.equal(source.includes("Track topic"), true);
  });

  it("representatives can be tracked from the representatives page", async () => {
    const source = await readFile("app/representatives/page.tsx", "utf8");

    assert.equal(source.includes("trackLegislator"), true);
    assert.equal(source.includes("untrackLegislator"), true);
    assert.equal(source.includes("Track legislator"), true);
  });

  it("dashboard includes a tracked item summary", async () => {
    const source = await readFile("app/components/Dashboard.tsx", "utf8");

    assert.equal(source.includes("getMyTracking"), true);
    assert.equal(source.includes("My tracked"), true);
  });

  it("dashboard includes recent tracked changes", async () => {
    const source = await readFile("app/components/Dashboard.tsx", "utf8");

    assert.equal(source.includes("getTrackingFeed"), true);
    assert.equal(source.includes("Recent tracked changes"), true);
  });
});
