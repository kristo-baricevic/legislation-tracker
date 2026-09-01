import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BillBrief } from "@/app/bills/[id]/bill-brief";
import { getDefinitionItems, getOfficialSummary, getReaderItems } from "@/lib/api";
import type { BillDetailSummary } from "@/lib/api";
import type { BillContractSummary, LegalNlpLineItem } from "@/lib/contracts";

vi.mock("@/lib/api", () => ({
  getApiBase: () => "http://localhost:8000",
  getContractEvidence: vi.fn(),
  getDefinitionItems: vi.fn(),
  getOfficialSummary: vi.fn(),
  getReaderItems: vi.fn(),
  getTimelineItems: vi.fn(),
}));

const contract: BillContractSummary = {
  id: 12,
  schema_version: "2.1-legal-nlp",
  contract_hash: "hash",
  computed_at: "2026-09-01T00:00:00Z",
  document: 4,
  document_version_label: "Introduced",
  coverage_note: "The breakdown contains every provision recognized by the supported rules.",
  orientation: { purpose_clause: "Creates a rural hospital grant program.", purpose_line_item_id: "line-1" },
  reader_stats: { line_item_count: 61, financial_item_count: 4, timeline_item_count: 2, definition_item_count: 1, section_group_count: 3 },
};

const bill: BillDetailSummary = {
  id: 7,
  jurisdiction: "federal",
  session: 119,
  bill_number: "HR 7",
  title: "Rural Health Act",
  status: "Introduced",
  sponsor_name: null,
  introduced_at: null,
  last_action_at: null,
  topics: [{ topic_id: 1, name: "Health", slug: "health", confidence_score: null }],
  summary_preview: "Rural Health Act\n\nCreates grants for rural hospitals.",
  summary_has_more: true,
  summary_source: "crs",
  summary_action_date: "2026-08-20",
  summary_version_code: "Introduced in House",
  summary_last_updated_at: "2026-08-21T00:00:00Z",
  processing_status: "complete",
  sponsor: null,
  source_api_id: null,
  documents: [{ id: 4, version_label: "Introduced", source_order: 1, is_active_version: true, content_type: "text/plain", file_size_bytes: 10, source_url: null, downloaded_at: null, download_url: "/download/", text_url: "/text/" }],
  congress_gov_url: "https://www.congress.gov/bill/119th-congress/house-bill/7",
  latest_contract: contract,
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
};

function line(number: number): LegalNlpLineItem {
  const section = number <= 25 ? 1 : number <= 50 ? 2 : 3;
  return {
    id: `line-${number}`,
    source_id: `requirement-${number}`,
    section_id: `section-${section}`,
    section_path: [{ level: "section", label: `Sec. ${section}`, heading: `Part ${section}` }],
    kind: "requirement",
    display_text: `Requires action ${number}.`,
    actor: "the Secretary",
    action: `take action ${number}`,
    effect: null,
    exact_financial_count: 0,
    exact_financial_preview: [],
    timeline_count: 0,
    timeline_preview: [],
    definition_count: 0,
  };
}

describe("BillBrief", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getReaderItems).mockResolvedValue({ count: 0, next: null, previous: null, results: [], section_supplements: [] });
    vi.mocked(getDefinitionItems).mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
  });

  it("orients with attributed preview and fetches the complete CRS summary only on request", async () => {
    const user = userEvent.setup();
    vi.mocked(getOfficialSummary).mockResolvedValue({ summary: "Rural Health Act\n\nCreates grants for rural hospitals.\n\nRequires annual reports.", summary_source: "crs", summary_action_date: "2026-08-20", summary_version_code: "Introduced in House", summary_last_updated_at: "2026-08-21T00:00:00Z" });
    render(<BillBrief bill={bill} contractSummary={contract} />);

    expect(screen.getByRole("heading", { name: "What this bill does" })).toBeVisible();
    expect(screen.getByText(/Official CRS summary/)).toBeVisible();
    expect(screen.getByText("Creates grants for rural hospitals.")).toBeVisible();
    expect(screen.queryByText("Requires annual reports.")).not.toBeInTheDocument();
    expect(getOfficialSummary).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "View on Congress.gov" })).toHaveAttribute("href", bill.congress_gov_url);

    await user.click(screen.getByRole("button", { name: "Read full official summary" }));
    expect(await screen.findByText("Requires annual reports.", { exact: false })).toBeVisible();
    expect(getOfficialSummary).toHaveBeenCalledWith(7);
    expect(screen.queryByText(/recognized line items/i)).not.toBeInTheDocument();
  });

  it("provides a useful reader overview and links each topic to all matching bills", () => {
    const noSummary = { ...bill, summary_preview: null, summary_has_more: false, summary_source: null };
    const { rerender } = render(<BillBrief bill={noSummary} contractSummary={contract} />);
    expect(screen.getByText(/This federal bill changes health policy/i)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Topics" })).toBeVisible();
    expect(screen.getByRole("link", { name: /Health/ })).toHaveAttribute("href", "/bills?topic_id=1");
    expect(screen.getByText(/health-care programs, coverage, funding, or administration/i)).toBeVisible();
    expect(screen.queryByText("No official CRS summary is available yet.")).not.toBeInTheDocument();
    expect(screen.queryByText(/recognized line items/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Extraction coverage/i)).not.toBeInTheDocument();

    rerender(<BillBrief bill={{ ...noSummary, summary_preview: "Source description", summary_source: "source_metadata" }} contractSummary={contract} />);
    expect(screen.getByText(/Congress\.gov source description/)).toBeVisible();
    expect(screen.queryByText(/Official CRS summary/)).not.toBeInTheDocument();
  });

  it("keeps detailed extraction collapsed and excludes malformed reader fragments", async () => {
    const user = userEvent.setup();
    const malformed = {
      ...line(1),
      display_text: "Requires Allowable cost adjustments.--The Secretary to -(A) <<NOTE: Hawaii.",
      actor: "Allowable cost adjustments.--The Secretary",
      action: "-(A) <<NOTE: Hawaii",
    };
    vi.mocked(getReaderItems).mockResolvedValue({
      count: 2,
      next: null,
      previous: null,
      results: [malformed, line(2)],
      section_supplements: [],
    });

    render(<BillBrief bill={bill} contractSummary={contract} />);

    expect(getReaderItems).not.toHaveBeenCalled();
    expect(screen.queryByText(/Requires action 2/)).not.toBeInTheDocument();
    await user.click(screen.getByText("Browse detailed provisions"));
    expect(await screen.findByText("Requires action 2.")).toBeVisible();
    expect(screen.queryByText(/Hawaii/)).not.toBeInTheDocument();
  });

  it("paginates source-ordered reader items and keeps earlier pages when a later page fails", async () => {
    const user = userEvent.setup();
    vi.mocked(getReaderItems)
      .mockResolvedValueOnce({ count: 61, next: "page-2", previous: null, results: Array.from({ length: 25 }, (_, index) => line(index + 1)), section_supplements: [] })
      .mockRejectedValueOnce(new Error("page unavailable"))
      .mockResolvedValueOnce({ count: 61, next: "page-3", previous: "page-1", results: Array.from({ length: 25 }, (_, index) => line(index + 26)), section_supplements: [] })
      .mockResolvedValueOnce({ count: 61, next: null, previous: "page-2", results: Array.from({ length: 11 }, (_, index) => line(index + 51)), section_supplements: [] });

    render(<BillBrief bill={bill} contractSummary={contract} />);
    await user.click(screen.getByText("Browse detailed provisions"));
    expect(await screen.findByText("Requires action 25.")).toBeVisible();
    expect(screen.queryByText("Requires action 26.")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show 25 more" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load more bill provisions");
    expect(screen.getByText("Requires action 1.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Retry bill provisions" }));
    expect(await screen.findByText("Requires action 50.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Show 25 more" }));
    expect(await screen.findByText("Requires action 61.")).toBeVisible();
    await waitFor(() => expect(getReaderItems).toHaveBeenLastCalledWith(12, { page: 3, pageSize: 25 }));
  });
});
