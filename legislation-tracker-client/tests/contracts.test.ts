import assert from "node:assert/strict";
import test from "node:test";

import {
  getContractSummary,
  groupEvidenceByFieldPath,
  isLegalNlpDefinitionItemsPage,
  isLegalNlpEvidencePage,
  isLegalNlpFinancialItem,
  isLegalNlpFinancialItemsPage,
  isLegalNlpReaderItemsPage,
  isLegalNlpTimelineItemsPage,
  isLegalNlpV21ContractSummary,
  isOfficialSummaryResponse,
  isLegalNlpV2Contract,
} from "../lib/contracts.ts";

const sectionPath = [
  { level: "section", label: "Sec. 1", heading: "Programs" },
];

function validFinancialItem(): Record<string, unknown> {
  return {
    id: "financial-1",
    source_id: "financial-1",
    section_id: "section-1",
    section_label: "Sec. 1",
    section_path: sectionPath,
    display_text: "Appropriates $1,000.00.",
    financial_action: "appropriation",
    direction: "increase",
    amount: "1000.00",
    amount_type: "specified",
    currency: "USD",
    fiscal_years: [2026],
    purpose: "hospital grants",
    source_account: null,
    destination_account: null,
  };
}

function validReaderItem(): Record<string, unknown> {
  return {
    id: "line-1",
    source_id: "requirement-1",
    section_id: "section-1",
    section_path: sectionPath,
    kind: "requirement",
    display_text: "The Secretary must report.",
    actor: "the Secretary",
    action: "report",
    effect: null,
    exact_financial_count: 1,
    exact_financial_preview: [
      {
        id: "financial-1",
        display_text: "Appropriates $1,000.00.",
        financial_action: "appropriation",
        direction: "increase",
        amount: "1000.00",
        amount_type: "specified",
        currency: "USD",
        fiscal_years: [2026],
      },
    ],
    timeline_count: 1,
    timeline_preview: [
      {
        id: "timeline-1",
        display_text: "Requires a report within 30 days.",
        timeline_type: "relative",
        date: null,
        relative_value: 30,
        relative_unit: "days",
        trigger: "enactment",
      },
    ],
    definition_count: 0,
  };
}

function page(results: unknown[]): Record<string, unknown> {
  return { count: results.length, next: null, previous: null, results };
}

function validV2Contract(): Record<string, unknown> {
  return {
    schema_version: "2.0-legal-nlp",
    title: "Test Act",
    version_label: "Introduced",
    extraction: {
      method: "federal-rules",
      parser_version: "2.0.0",
      sections_seen: 1,
      sections_with_claims: 1,
      warnings: [],
    },
    plain_summary: "The Secretary is required to report.",
    key_provisions: [
      {
        kind: "requirement",
        section_label: "Sec. 2",
        heading: "Reports",
        text: "The Secretary is required to report.",
      },
    ],
    requirements: [
      {
        section_label: "Sec. 2",
        display_text: "The Secretary is required to report.",
        modality: "required",
        actor: "The Secretary",
        action: "report",
        object: null,
        conditions: [],
      },
    ],
    funding_items: [],
    timeline_items: [],
    definitions: [],
    applicability: [],
    amendment_operations: [],
    limitations: ["Not legal advice."],
  };
}

test("isLegalNlpV2Contract accepts a complete v2 payload", () => {
  const value = validV2Contract();
  assert.equal(isLegalNlpV2Contract("2.0-legal-nlp", value), true);
});

test("isLegalNlpV2Contract rejects unsafe payloads", () => {
  const wrongVersion = validV2Contract();
  wrongVersion.schema_version = "1.1-deterministic";
  assert.equal(isLegalNlpV2Contract("2.0-legal-nlp", wrongVersion), false);

  const missingArray = validV2Contract();
  delete missingArray.funding_items;
  assert.equal(isLegalNlpV2Contract("2.0-legal-nlp", missingArray), false);

  const malformedExtraction = validV2Contract();
  malformedExtraction.extraction = { method: "federal-rules" };
  assert.equal(isLegalNlpV2Contract("2.0-legal-nlp", malformedExtraction), false);

  const invalidItem = validV2Contract();
  invalidItem.requirements = [null];
  assert.equal(isLegalNlpV2Contract("2.0-legal-nlp", invalidItem), false);

  assert.equal(isLegalNlpV2Contract("1.1-deterministic", validV2Contract()), false);
});

test("getContractSummary safely handles legacy and malformed values", () => {
  assert.equal(getContractSummary({ plain_summary: "Legacy summary" }), "Legacy summary");
  assert.equal(getContractSummary({ plain_summary: 42 }), null);
  assert.equal(getContractSummary(null), null);
});

test("groupEvidenceByFieldPath retains every span in source order", () => {
  const first = {
    field_path: "requirements[0].display_text",
    start_char: 20,
    end_char: 30,
    quoted_text: "second",
    page_number: null,
  };
  const second = {
    field_path: "requirements[0].display_text",
    start_char: 0,
    end_char: 10,
    quoted_text: "first",
    page_number: 1,
  };

  const grouped = groupEvidenceByFieldPath([first, second]);

  assert.deepEqual(grouped.get("requirements[0].display_text"), [second, first]);
});

test("accepts a complete 2.1 contract summary and rejects inconsistent orientation", () => {
  const summary = {
    id: 12,
    schema_version: "2.1-legal-nlp",
    contract_hash: "abc123",
    computed_at: "2026-09-01T12:00:00Z",
    document: 3,
    document_version_label: "Introduced",
    coverage_note: "Deterministic extraction coverage.",
    orientation: {
      purpose_clause: "Creates a grant program.",
      purpose_line_item_id: "line-1",
    },
    reader_stats: {
      line_item_count: 1,
      financial_item_count: 1,
      timeline_item_count: 1,
      definition_item_count: 0,
      section_group_count: 1,
    },
  };
  assert.equal(isLegalNlpV21ContractSummary(summary), true);

  const invalid = structuredClone(summary);
  invalid.orientation.purpose_line_item_id = null as unknown as string;
  assert.equal(isLegalNlpV21ContractSummary(invalid), false);
});

test("reader page guards reject duplicate IDs, dangling supplements, and malformed paths", () => {
  const valid: Record<string, unknown> = {
    ...page([validReaderItem()]),
    section_supplements: [
      {
        section_id: "section-1",
        section_path: sectionPath,
        section_financial_count: 0,
        section_timeline_count: 0,
      },
    ],
  };
  assert.equal(isLegalNlpReaderItemsPage(valid), true);

  const duplicate = structuredClone(valid);
  const duplicateResults = duplicate.results as unknown[];
  duplicateResults.push(structuredClone(duplicateResults[0]));
  duplicate.count = 2;
  assert.equal(isLegalNlpReaderItemsPage(duplicate), false);

  const dangling = structuredClone(valid);
  const danglingSupplements = dangling.section_supplements as Array<
    Record<string, unknown>
  >;
  danglingSupplements[0].section_id = "section-999";
  assert.equal(isLegalNlpReaderItemsPage(dangling), false);

  const malformedPath = structuredClone(valid);
  const malformedResult = (malformedPath.results as Array<Record<string, unknown>>)[0];
  malformedResult.section_path = [
    { level: "unknown", label: "Sec. 1", heading: null },
  ];
  assert.equal(isLegalNlpReaderItemsPage(malformedPath), false);
});

test("strict item guards reject unsupported financial semantics", () => {
  const item = validFinancialItem();
  assert.equal(isLegalNlpFinancialItem(item), true);

  const unknownAction = structuredClone(item);
  unknownAction.financial_action = "spending";
  assert.equal(isLegalNlpFinancialItem(unknownAction), false);

  const invalidDirection = structuredClone(item);
  invalidDirection.direction = "outgoing";
  assert.equal(isLegalNlpFinancialItem(invalidDirection), false);
});

test("accepts valid bounded association and evidence pages", () => {
  const financial = page([validFinancialItem()]);
  assert.equal(isLegalNlpFinancialItemsPage(financial), true);

  const timeline = page([
    {
      id: "timeline-1",
      source_id: "timeline-1",
      section_id: "section-1",
      section_label: "Sec. 1",
      section_path: sectionPath,
      display_text: "Requires a report within 30 days.",
      timeline_type: "relative",
      date: null,
      relative_value: 30,
      relative_unit: "days",
      trigger: "enactment",
    },
  ]);
  assert.equal(isLegalNlpTimelineItemsPage(timeline), true);

  const definitions = page([
    {
      id: "definition-1",
      source_id: "definition-1",
      section_id: "section-1",
      section_label: "Sec. 1",
      section_path: sectionPath,
      display_text: "Defines eligible entity.",
      term: "eligible entity",
      definition: "a qualifying hospital",
      definition_type: "means",
    },
  ]);
  assert.equal(isLegalNlpDefinitionItemsPage(definitions), true);

  const evidence = page([
    {
      start_char: 0,
      end_char: 24,
      quoted_text: "The Secretary must act.",
      page_number: 1,
    },
  ]);
  assert.equal(isLegalNlpEvidencePage(evidence), true);
});

test("page guards reject invalid pagination metadata", () => {
  const value = page([validFinancialItem()]);
  value.count = -1;
  assert.equal(isLegalNlpFinancialItemsPage(value), false);

  const invalidNext = page([validFinancialItem()]);
  invalidNext.next = 2;
  assert.equal(isLegalNlpFinancialItemsPage(invalidNext), false);
});

test("accepts the guarded official summary and nullable summary fields", () => {
  assert.equal(
    isOfficialSummaryResponse({
      summary: "An official summary.",
      summary_source: "crs",
      summary_action_date: "2026-08-01",
      summary_version_code: "RS",
      summary_last_updated_at: "2026-08-02T10:00:00Z",
    }),
    true,
  );
  assert.equal(
    isOfficialSummaryResponse({
      summary: null,
      summary_source: null,
      summary_action_date: null,
      summary_version_code: null,
      summary_last_updated_at: null,
    }),
    true,
  );
});
