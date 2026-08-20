import assert from "node:assert/strict";
import test from "node:test";

import {
  getContractSummary,
  groupEvidenceByFieldPath,
  isLegalNlpV2Contract,
} from "../lib/contracts.ts";

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
