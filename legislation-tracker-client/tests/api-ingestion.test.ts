import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";

import {
  triggerDocumentBackfill,
  triggerPollCongress,
  triggerTopicBackfill,
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

describe("ingestion workflow API helpers", () => {
  it("posts to the Django poll Congress endpoint", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ url: String(url), init });
      return Response.json({
        task_id: "poll-task",
        task_name: "poll_congress",
        jurisdiction: "federal",
        congress: 118,
      });
    };

    const result = await triggerPollCongress({ jurisdiction: "federal", congress: 118 });

    assert.equal(result.task_id, "poll-task");
    assert.equal(requests[0].url, "http://api.test/api/ingestion/poll-congress/");
    assert.equal(requests[0].init?.method, "POST");
    assert.equal(
      requests[0].init?.body,
      JSON.stringify({ jurisdiction: "federal", congress: 118 }),
    );
  });

  it("posts to the Django document backfill endpoint", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ url: String(url), init });
      return Response.json({
        task_id: "backfill-task",
        task_name: "backfill_process_bill_versions_for_all_bills",
        session: 119,
      });
    };

    const result = await triggerDocumentBackfill({ session: 119 });

    assert.equal(result.task_id, "backfill-task");
    assert.equal(requests[0].url, "http://api.test/api/ingestion/backfill-documents/");
    assert.equal(requests[0].init?.method, "POST");
    assert.equal(requests[0].init?.body, JSON.stringify({ session: 119 }));
  });

  it("posts to the Django topic backfill endpoint", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ url: String(url), init });
      return Response.json({
        task_id: "topic-backfill-task",
        task_name: "backfill_update_topics",
        session: 119,
      });
    };

    const result = await triggerTopicBackfill({ session: 119 });

    assert.equal(result.task_id, "topic-backfill-task");
    assert.equal(result.task_name, "backfill_update_topics");
    assert.equal(requests[0].url, "http://api.test/api/ingestion/backfill-topics/");
    assert.equal(requests[0].init?.method, "POST");
    assert.equal(requests[0].init?.body, JSON.stringify({ session: 119 }));
  });
});
