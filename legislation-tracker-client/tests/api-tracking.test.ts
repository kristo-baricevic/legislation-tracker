import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";

import {
  getRelatedBills,
  getTrackedTopics,
  getMyTracking,
  getTrackingFeed,
  ingestBill,
  trackBill,
  trackLegislator,
  trackTopic,
  untrackBill,
  untrackLegislator,
  untrackTopic,
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

describe("tracking API helpers", () => {
  it("loads followed topics from the sole tracking collection", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ url: String(url), init });
      return Response.json([{ id: 1, topic: { id: 7, name: "Health", slug: "health" } }]);
    };

    const result = await getTrackedTopics();

    assert.deepEqual(result, [{ id: 1, topic: { id: 7, name: "Health", slug: "health" } }]);
    assert.equal(requests[0].url, "http://api.test/api/tracking/topics/");
  });

  it("loads related bills from the public bill endpoint", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ url: String(url), init });
      return Response.json({ results: [] });
    };

    const result = await getRelatedBills(10, { limit: 5 });

    assert.deepEqual(result, { results: [] });
    assert.equal(requests[0].url, "http://api.test/api/bills/10/related/?limit=5");
  });

  it("loads the current user's tracking summary", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ url: String(url), init });
      return Response.json({ bills: [], topics: [], legislators: [] });
    };

    const result = await getMyTracking();

    assert.deepEqual(result, { bills: [], topics: [], legislators: [] });
    assert.equal(requests[0].url, "http://api.test/api/tracking/");
  });

  it("loads the current user's tracking feed", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ url: String(url), init });
      return Response.json({ entries: [] });
    };

    const result = await getTrackingFeed({ limit: 25 });

    assert.deepEqual(result, { entries: [] });
    assert.equal(requests[0].url, "http://api.test/api/tracking/feed/?limit=25");
  });

  it("tracks bills, topics, and legislators with POST requests", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ url: String(url), init });
      return Response.json({ id: requests.length });
    };

    await trackBill(10);
    await trackTopic(20);
    await trackLegislator(30);

    assert.equal(requests[0].url, "http://api.test/api/tracking/bills/");
    assert.equal(requests[0].init?.method, "POST");
    assert.equal(requests[0].init?.body, JSON.stringify({ bill: 10 }));
    assert.equal(requests[1].url, "http://api.test/api/tracking/topics/");
    assert.equal(requests[1].init?.body, JSON.stringify({ topic: 20 }));
    assert.equal(requests[2].url, "http://api.test/api/tracking/legislators/");
    assert.equal(requests[2].init?.body, JSON.stringify({ representative: 30 }));
  });

  it("ingests a bill into the shared corpus and tracks it for the user", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ url: String(url), init });
      return Response.json({
        work_item_id: 10,
        status: "pending",
        status_url: "/api/ingestion/work/10/",
        tracking_status: "pending",
        bill_id: null,
      });
    };

    const result = await ingestBill({
      congress: 119,
      billType: "hr",
      billNumber: "42",
    });

    assert.deepEqual(result, {
      work_item_id: 10,
      status: "pending",
      status_url: "/api/ingestion/work/10/",
      tracking_status: "pending",
      bill_id: null,
    });
    assert.equal(requests[0].url, "http://api.test/api/ingestion/bills/");
    assert.equal(requests[0].init?.method, "POST");
    assert.equal(
      requests[0].init?.body,
      JSON.stringify({ congress: 119, bill_type: "hr", bill_number: "42" }),
    );
  });

  it("untracks bills, topics, and legislators with DELETE requests", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ url: String(url), init });
      return new Response(null, { status: 204 });
    };

    await untrackBill(10);
    await untrackTopic(20);
    await untrackLegislator(30);

    assert.equal(requests[0].url, "http://api.test/api/tracking/bills/10/");
    assert.equal(requests[0].init?.method, "DELETE");
    assert.equal(requests[1].url, "http://api.test/api/tracking/topics/20/");
    assert.equal(requests[1].init?.method, "DELETE");
    assert.equal(requests[2].url, "http://api.test/api/tracking/legislators/30/");
    assert.equal(requests[2].init?.method, "DELETE");
  });
});
