import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ContractSection } from "@/app/bills/[id]/contract-section";
import { getContract, getContractEvidence, getFinancialItems } from "@/lib/api";
import type { BillContractItem, BillDetailSummary } from "@/lib/api";
import type { BillContractSummary } from "@/lib/contracts";

vi.mock("@/lib/api", () => ({
  getApiBase: () => "http://localhost:8000",
  getContract: vi.fn(),
  getContractEvidence: vi.fn(),
  getDefinitionItems: vi.fn(),
  getFinancialItems: vi.fn(),
  getOfficialSummary: vi.fn(),
  getReaderItems: vi.fn(),
  getTimelineItems: vi.fn(),
}));

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
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getContractEvidence).mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    vi.mocked(getFinancialItems).mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
  });

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

  it("hydrates a compact 2.0 summary so the legacy reader remains visible", async () => {
    const summary: BillContractSummary = {
      id: 1,
      schema_version: "2.0-legal-nlp",
      contract_hash: "v2-hash",
      computed_at: "2026-08-20T12:00:00Z",
      document: 1,
      document_version_label: "Introduced",
      coverage_note: null,
      orientation: null,
      reader_stats: null,
    };
    vi.mocked(getContract).mockResolvedValue(v2Contract());

    render(<ContractSection contract={summary} />);

    expect(await screen.findByRole("heading", { name: "Overview" })).toBeVisible();
    expect(getContract).toHaveBeenCalledWith(1);
  });

  it("uses the contract document for source links while a newer version is active", async () => {
    const user = userEvent.setup();
    const summary: BillContractSummary = {
      id: 22,
      schema_version: "2.1-legal-nlp",
      contract_hash: "v21-hash",
      computed_at: "2026-08-20T12:00:00Z",
      document: 1,
      document_version_label: "Introduced",
      coverage_note: "Recognized provisions.",
      orientation: { purpose_clause: null, purpose_line_item_id: null },
      reader_stats: { line_item_count: 0, financial_item_count: 1, timeline_item_count: 0, definition_item_count: 0, section_group_count: 1 },
    };
    const bill = {
      id: 7,
      jurisdiction: "federal",
      session: 119,
      bill_number: "HR 7",
      title: "Versioned Act",
      status: "Introduced",
      topics: [],
      summary_preview: null,
      summary_has_more: false,
      summary_source: null,
      summary_action_date: null,
      summary_version_code: null,
      summary_last_updated_at: null,
      documents: [
        { id: 1, version_label: "Introduced", source_order: 1, is_active_version: false, content_type: "text/plain", file_size_bytes: 10, source_url: null, downloaded_at: null, download_url: "/documents/1/download/", text_url: "/documents/1/text/" },
        { id: 2, version_label: "Enrolled", source_order: 2, is_active_version: true, content_type: "text/plain", file_size_bytes: 20, source_url: null, downloaded_at: null, download_url: "/documents/2/download/", text_url: "/documents/2/text/" },
      ],
      congress_gov_url: null,
      latest_contract: summary,
    } as unknown as BillDetailSummary;
    vi.mocked(getFinancialItems).mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [{
        id: "financial-1",
        source_id: "financial-1",
        section_id: "section-1",
        section_label: "Sec. 1",
        section_path: [{ level: "section", label: "Sec. 1", heading: "Funding" }],
        display_text: "Appropriates $1,000.",
        financial_action: "appropriation",
        direction: "increase",
        amount: "1000.00",
        amount_type: "specified",
        currency: "USD",
        fiscal_years: [],
        purpose: "the program",
        source_account: null,
        destination_account: null,
      }],
    });

    render(<ContractSection contract={summary} bill={bill} />);
    await user.click(await screen.findByRole("button", { name: "Read bill text" }));

    expect(screen.getByRole("link", { name: "Read full text" })).toHaveAttribute(
      "href",
      "http://localhost:8000/documents/1/text/",
    );
    expect(screen.getByRole("link", { name: "Download document" })).toHaveAttribute(
      "href",
      "http://localhost:8000/documents/1/download/",
    );
  });
});
