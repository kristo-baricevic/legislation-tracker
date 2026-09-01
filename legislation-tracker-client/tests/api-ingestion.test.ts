import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";

import {
  getBill,
  getContract,
  getContractEvidence,
  getContracts,
  getDefinitionItems,
  getFinancialItems,
  getOfficialSummary,
  getReaderItems,
  getTimelineItems,
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

describe("bounded bill brief API helpers", () => {
  it("builds compact and filtered reader URLs with URLSearchParams", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    const urls: string[] = [];
    globalThis.fetch = async (url) => {
      const value = String(url);
      urls.push(value);
      if (value.includes("/api/bills/7/official-summary/")) {
        return Response.json({
          summary: "Official summary.",
          summary_source: "crs",
          summary_action_date: "2026-08-01",
          summary_version_code: "RS",
          summary_last_updated_at: "2026-08-02T10:00:00Z",
        });
      }
      if (value.includes("/api/bills/7/")) {
        return Response.json({
          id: 7,
          jurisdiction: "federal",
          session: 119,
          bill_number: "HR 7",
          title: "Reader Act",
          status: "Introduced",
          sponsor_name: null,
          introduced_at: null,
          last_action_at: null,
          topics: [],
          summary_preview: null,
          summary_has_more: false,
          summary_source: null,
          summary_action_date: null,
          summary_version_code: null,
          summary_last_updated_at: null,
          processing_status: "complete",
          sponsor: null,
          source_api_id: null,
          documents: [],
          congress_gov_url: null,
          latest_contract: null,
          created_at: "2026-09-01T00:00:00Z",
          updated_at: "2026-09-01T00:00:00Z",
        });
      }
      if (value.includes("/api/contracts/?")) {
        return Response.json({ count: 0, next: null, previous: null, results: [] });
      }
      if (value.includes("/reader-items/")) {
        return Response.json({
          count: 0,
          next: null,
          previous: null,
          results: [],
          section_supplements: [],
        });
      }
      return Response.json({ count: 0, next: null, previous: null, results: [] });
    };

    await getBill(7, { contractView: "summary" });
    await getContract(12);
    await getContracts(7, { view: "summary", page: 2 });
    await getReaderItems(12, { page: 2, pageSize: 50 });
    await getFinancialItems(12, {
      financialAction: "transfer",
      fiscalYear: 2027,
      sectionId: "section-1",
      page: 3,
      pageSize: 10,
    });
    await getTimelineItems(12, { lineItemId: "line-1", page: 2 });
    await getDefinitionItems(12, { unlinked: true, pageSize: 100 });
    await getContractEvidence(12, {
      financialItemId: "financial-1",
      page: 2,
      pageSize: 1,
    });
    await getOfficialSummary(7);

    assert.deepEqual(urls, [
      "http://api.test/api/bills/7/?contract_view=summary",
      "http://api.test/api/contracts/12/",
      "http://api.test/api/contracts/?bill=7&view=summary&page=2",
      "http://api.test/api/contracts/12/reader-items/?page=2&page_size=50",
      "http://api.test/api/contracts/12/financial-items/?page=3&page_size=10&financial_action=transfer&fiscal_year=2027&section_id=section-1",
      "http://api.test/api/contracts/12/timeline-items/?page=2&line_item_id=line-1",
      "http://api.test/api/contracts/12/definition-items/?page_size=100&unlinked=true",
      "http://api.test/api/contracts/12/evidence/?page=2&page_size=1&financial_item_id=financial-1",
      "http://api.test/api/bills/7/official-summary/",
    ]);
  });

  it("passes abort signals through and rejects malformed reader responses", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    const controller = new AbortController();
    let receivedSignal: AbortSignal | null | undefined;
    globalThis.fetch = async (_url, init) => {
      receivedSignal = init?.signal;
      return Response.json({ count: "one", next: null, previous: null, results: [] });
    };

    await assert.rejects(
      getReaderItems(12, { signal: controller.signal }),
      /invalid reader items response/i,
    );
    assert.equal(receivedSignal, controller.signal);
  });

  it("accepts a compact 2.0 fallback without treating raw JSON as a reader contract", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    globalThis.fetch = async () =>
      Response.json({
        id: 7,
        jurisdiction: "federal",
        session: 119,
        bill_number: "HR 7",
        title: "Legacy Act",
        status: "Introduced",
        sponsor_name: null,
        introduced_at: null,
        last_action_at: null,
        topics: [],
        summary_preview: "A legacy bill.",
        summary_has_more: false,
        summary_source: "crs",
        summary_action_date: null,
        summary_version_code: null,
        summary_last_updated_at: null,
        processing_status: "complete",
        sponsor: null,
        source_api_id: null,
        documents: [],
        congress_gov_url: null,
        latest_contract: {
          id: 2,
          schema_version: "2.0-legal-nlp",
          contract_hash: "legacy-hash",
          computed_at: "2026-09-01T00:00:00Z",
          document: null,
          document_version_label: null,
          coverage_note: null,
          orientation: null,
          reader_stats: null,
        },
        created_at: "2026-09-01T00:00:00Z",
        updated_at: "2026-09-01T00:00:00Z",
      });

    const bill = await getBill(7, { contractView: "summary" });
    assert.equal(bill.latest_contract?.schema_version, "2.0-legal-nlp");
    assert.equal(bill.latest_contract?.reader_stats, null);
    assert.equal("contract_json" in (bill.latest_contract ?? {}), false);
  });
});
