import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ContractSection } from "@/app/bills/[id]/contract-section";
import type { BillContractItem } from "@/lib/api";

function v2Contract(): BillContractItem {
  return {
    id: 1,
    schema_version: "2.0-legal-nlp",
    contract_hash: "v2-hash",
    computed_at: "2026-08-20T12:00:00Z",
    document: 1,
    document_version_label: "Introduced",
    contract_json: {
      schema_version: "2.0-legal-nlp",
      title: "Test Act",
      version_label: "Introduced",
      extraction: {
        method: "federal-rules",
        parser_version: "2.0.0",
        sections_seen: 3,
        sections_with_claims: 2,
        warnings: ["item_limit_reached:requirements", "future_warning"],
      },
      plain_summary: "The Secretary is required to publish a report.",
      key_provisions: [
        {
          kind: "requirement",
          section_label: "Sec. 2",
          heading: "Reports",
          text: "The Secretary is required to publish a report.",
        },
      ],
      requirements: [
        {
          section_label: "Sec. 2",
          display_text: "The Secretary is required to publish a report.",
          modality: "required",
          actor: "The Secretary",
          action: "publish a report",
          object: null,
          conditions: [],
        },
      ],
      funding_items: [
        {
          section_label: "Sec. 3",
          display_text: "Funding of $25,000,000.00 is specified for fiscal year 2027.",
          amount: "25000000.00",
          amount_type: "specified",
          currency: "USD",
          fiscal_years: [2027],
          purpose: null,
        },
      ],
      timeline_items: [
        {
          section_label: "Sec. 3",
          display_text: "A deadline occurs 90 days after enactment.",
          timeline_type: "relative",
          date: null,
          relative_value: 90,
          relative_unit: "days",
          trigger: "enactment",
        },
      ],
      definitions: [
        {
          section_label: "Sec. 4",
          display_text: "“covered entity” means a rural hospital.",
          term: "covered entity",
          definition: "a rural hospital",
          definition_type: "means",
        },
      ],
      applicability: [
        {
          section_label: "Sec. 5",
          display_text: "The program applies to rural hospitals.",
          subject: "The program",
          scope: "rural hospitals",
          applicability_type: "applies",
        },
      ],
      amendment_operations: [
        {
          section_label: "Sec. 6",
          display_text: "section 5 replaces “old” with “new”.",
          target: "section 5",
          operation: "replace",
          removed_text: "old",
          inserted_text: "new",
        },
      ],
      limitations: ["Not legal advice."],
    },
    evidence_spans: [
      {
        field_path: "key_provisions[0].text",
        start_char: 0,
        end_char: 9,
        quoted_text: "SEC. 2. REPORTS\nThe Secretary shall report.",
        page_number: null,
      },
      {
        field_path: "requirements[0].display_text",
        start_char: 10,
        end_char: 35,
        quoted_text: "The Secretary shall report.",
        page_number: 1,
      },
      {
        field_path: "requirements[0].display_text",
        start_char: 40,
        end_char: 65,
        quoted_text: "The report covers grants.",
        page_number: 2,
      },
    ],
  };
}

describe("ContractSection", () => {
  it("renders structured v2 categories with evidence attached to each claim", async () => {
    const user = userEvent.setup();
    render(<ContractSection contract={v2Contract()} />);

    for (const heading of [
      "Overview",
      "Key provisions",
      "Requirements",
      "Funding",
      "Timelines",
      "Definitions",
      "Applicability",
      "Amendments",
      "Limitations",
    ]) {
      expect(screen.getByRole("heading", { name: heading })).toBeVisible();
    }
    expect(screen.getAllByText("Sec. 2").length).toBeGreaterThan(0);
    expect(screen.getAllByText("The Secretary is required to publish a report.").length).toBeGreaterThan(0);

    await user.click(
      screen.getByLabelText("Source evidence for Key provisions item 1"),
    );
    expect(
      screen.getByText("SEC. 2. REPORTS The Secretary shall report."),
    ).toBeVisible();

    await user.click(
      screen.getByLabelText("Source evidence for Requirements item 1"),
    );
    expect(screen.getByText("The Secretary shall report.")).toBeVisible();
    expect(screen.getByText("The report covers grants.")).toBeVisible();
    expect(screen.getByText("Only the first 100 extracted requirements are shown.")).toBeVisible();
    expect(
      screen.getByText(
        "Some provisions could not be represented in this automated summary.",
      ),
    ).toBeVisible();
    expect(screen.queryByText("future_warning")).not.toBeInTheDocument();
  });

  it("omits empty v2 category headings", () => {
    const contract = v2Contract();
    contract.contract_json = {
      ...contract.contract_json,
      funding_items: [],
      timeline_items: [],
    };

    render(<ContractSection contract={contract} />);

    expect(screen.queryByRole("heading", { name: "Funding" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Timelines" })).not.toBeInTheDocument();
  });

  it("falls back safely for malformed v2 and preserves legacy rendering", () => {
    const malformed = v2Contract();
    malformed.contract_json = {
      schema_version: "2.0-legal-nlp",
      plain_summary: "Safe fallback summary",
      source_excerpt: "Fallback source excerpt",
    };
    malformed.evidence_spans = [
      {
        field_path: "plain_summary",
        start_char: 0,
        end_char: 12,
        quoted_text: "Legacy quote",
        page_number: null,
      },
    ];

    render(<ContractSection contract={malformed} />);

    expect(screen.getByRole("heading", { name: /Plain-language summary/ })).toBeVisible();
    expect(screen.getByText("Safe fallback summary")).toBeVisible();
    expect(screen.getByText("Fallback source excerpt")).toBeVisible();
    expect(screen.getByText("Evidence spans (1)")).toBeVisible();
  });
});
