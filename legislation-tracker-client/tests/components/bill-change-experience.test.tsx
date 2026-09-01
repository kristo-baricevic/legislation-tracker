import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BillChangeExperience, {
  selectDocumentComparisonPair,
} from "@/app/bills/[id]/bill-change-experience";
import {
  acknowledgeBillChanges,
  compareBillContracts,
  compareBillDocumentSection,
  compareBillDocuments,
  getBillChanges,
} from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getBillChanges: vi.fn(),
  acknowledgeBillChanges: vi.fn(),
  compareBillContracts: vi.fn(),
  compareBillDocuments: vi.fn(),
  compareBillDocumentSection: vi.fn(),
}));

describe("BillChangeExperience", () => {
  beforeEach(() => {
    vi.mocked(getBillChanges).mockResolvedValue({
      results: [{ id: 1, type: "status_update", occurred_at: "2026-01-01T00:00:00Z", summary: "Bill status changed", before: { status: "Introduced" }, after: { status: "Reported" }, document_id: null, contract_id: null }],
      page_end_cursor: "ack-cursor",
      stream_head_cursor: "head-cursor",
      older_cursor: null,
      has_more_newer: false,
      has_more_older: false,
      unread_count: 1,
      personalized: true,
      initial_window_truncated: false,
    });
    vi.mocked(acknowledgeBillChanges).mockResolvedValue({ unread_count: 0 });
  });

  it("does not acknowledge on load and only marks displayed changes seen after an explicit action", async () => {
    const user = userEvent.setup();
    render(<BillChangeExperience billId={10} contracts={[]} documents={[]} />);
    expect(await screen.findByText("Bill status changed")).toBeVisible();
    expect(screen.getByText(/Introduced/)).toBeVisible();
    expect(screen.getByText(/Reported/)).toBeVisible();
    expect(acknowledgeBillChanges).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Mark 1 as seen" }));
    expect(acknowledgeBillChanges).toHaveBeenCalledWith(10, "ack-cursor");
    expect(await screen.findByRole("button", { name: "Changes seen" })).toBeVisible();
  });

  it("withholds acknowledgement while the initial timeline window omits older changes", async () => {
    vi.mocked(getBillChanges).mockResolvedValueOnce({
      results: [{ id: 1, type: "status_update", occurred_at: "2026-01-01T00:00:00Z", summary: "Recent change", before: null, after: {}, document_id: null, contract_id: null }],
      page_end_cursor: "unsafe-ack-cursor",
      stream_head_cursor: "head-cursor",
      older_cursor: "older-cursor",
      has_more_newer: false,
      has_more_older: true,
      unread_count: 2,
      personalized: true,
      initial_window_truncated: true,
    });

    render(<BillChangeExperience billId={10} contracts={[]} documents={[]} />);

    expect(await screen.findByText("Recent change")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Mark .* as seen/ })).toBeNull();
  });

  it("uses the source predecessor even when an older version is re-downloaded last", () => {
    const pair = selectDocumentComparisonPair([
      { id: 3, version_label: "introduced", is_active_version: false, content_type: null, file_size_bytes: null, source_url: null, downloaded_at: "2026-01-03T00:00:00Z", download_url: null, text_url: null, source_order: 1 },
      { id: 1, version_label: "active", is_active_version: true, content_type: null, file_size_bytes: null, source_url: null, downloaded_at: "2026-01-02T00:00:00Z", download_url: null, text_url: null, source_order: 3 },
      { id: 4, version_label: "engrossed", is_active_version: false, content_type: null, file_size_bytes: null, source_url: null, downloaded_at: "2026-01-01T00:00:00Z", download_url: null, text_url: null, source_order: 2 },
    ]);

    expect(pair?.map((document) => document.id)).toEqual([4, 1]);
  });

  it("keeps the server unread count and loads older timeline pages", async () => {
    const user = userEvent.setup();
    vi.mocked(acknowledgeBillChanges).mockResolvedValueOnce({ unread_count: 2 });
    vi.mocked(getBillChanges)
      .mockResolvedValueOnce({
        results: [{ id: 2, type: "status_update", occurred_at: "2026-01-02T00:00:00Z", summary: "New change", before: null, after: {}, document_id: null, contract_id: null }],
        page_end_cursor: null,
        stream_head_cursor: "head",
        older_cursor: "older-2",
        has_more_newer: false,
        has_more_older: true,
        unread_count: 3,
        personalized: true,
        initial_window_truncated: true,
      })
      .mockResolvedValueOnce({
        results: [{ id: 1, type: "bill_created", occurred_at: "2026-01-01T00:00:00Z", summary: "Old change", before: null, after: {}, document_id: null, contract_id: null }],
        page_end_cursor: null,
        stream_head_cursor: "head",
        older_cursor: null,
        has_more_newer: false,
        has_more_older: false,
        unread_count: 3,
        personalized: true,
        initial_window_truncated: false,
      });

    render(<BillChangeExperience billId={10} contracts={[]} documents={[]} />);
    await user.click(await screen.findByRole("button", { name: "Load older changes" }));
    expect(await screen.findByText("Old change")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Mark 3 as seen" }));
    expect(acknowledgeBillChanges).toHaveBeenCalledWith(10, "head");
    expect(await screen.findByRole("button", { name: "Mark 2 as seen" })).toBeVisible();
  });

  it("loads changes newer than the displayed page-end cursor", async () => {
    const user = userEvent.setup();
    vi.mocked(getBillChanges)
      .mockResolvedValueOnce({
        results: [{ id: 1, type: "bill_created", occurred_at: "2026-01-01T00:00:00Z", summary: "Initial change", before: null, after: {}, document_id: null, contract_id: null }],
        page_end_cursor: "shown-cursor",
        stream_head_cursor: "newer-head",
        older_cursor: null,
        has_more_newer: true,
        has_more_older: false,
        unread_count: 2,
        personalized: true,
        initial_window_truncated: false,
      })
      .mockResolvedValueOnce({
        results: [{ id: 2, type: "status_update", occurred_at: "2026-01-02T00:00:00Z", summary: "Newer change", before: {}, after: {}, document_id: null, contract_id: null }],
        page_end_cursor: "newer-cursor",
        stream_head_cursor: "newer-head",
        older_cursor: null,
        has_more_newer: false,
        has_more_older: false,
        unread_count: 2,
        personalized: true,
        initial_window_truncated: false,
      });

    render(<BillChangeExperience billId={10} contracts={[]} documents={[]} />);
    await user.click(await screen.findByRole("button", { name: "Load newer changes" }));

    expect(getBillChanges).toHaveBeenLastCalledWith(10, { afterCursor: "shown-cursor" });
    expect(await screen.findByText("Newer change")).toBeVisible();
  });

  it("renders before and after contract values and expandable section operations", async () => {
    const user = userEvent.setup();
    vi.mocked(compareBillContracts).mockResolvedValue({
      before: 1,
      after: 2,
      changes: [{ path: "plain_summary", operation: "changed", before: "old text", after: "new text" }],
      total_change_count: 1,
      returned_change_count: 1,
      truncated: false,
    });
    vi.mocked(compareBillDocuments).mockResolvedValue({
      before: 1,
      after: 2,
      sections: [{ section_key: "sec. 1#1", operation: "modified", before_hash: "a", after_hash: "b" }],
      total_change_count: 1,
      returned_change_count: 1,
      truncated: false,
      fallback: false,
      truncation_reasons: [],
    });
    vi.mocked(compareBillDocumentSection).mockResolvedValue({
      section_key: "sec. 1#1",
      operations: [{ operation: "replace", before: ["old line"], after: ["new line"] }],
      truncated: false,
      truncation_reasons: [],
    });
    const contracts = [
      { id: 1, schema_version: "1", contract_json: {}, contract_hash: "a", computed_at: "2026-01-01T00:00:00Z", document: null, document_version_label: null, evidence_spans: [] },
      { id: 2, schema_version: "1", contract_json: {}, contract_hash: "b", computed_at: "2026-01-02T00:00:00Z", document: null, document_version_label: null, evidence_spans: [] },
    ];
    const documents = [
      { id: 1, version_label: "old", is_active_version: false, content_type: null, file_size_bytes: null, source_url: null, downloaded_at: "2026-01-01T00:00:00Z", download_url: null, text_url: null, source_order: 1 },
      { id: 2, version_label: "active", is_active_version: true, content_type: null, file_size_bytes: null, source_url: null, downloaded_at: "2026-01-02T00:00:00Z", download_url: null, text_url: null, source_order: 2 },
    ];
    render(<BillChangeExperience billId={10} contracts={contracts} documents={documents} />);

    await user.click(await screen.findByRole("button", { name: "Compare analysis" }));
    expect(await screen.findByText('"old text"')).toBeVisible();
    expect(screen.getByText('"new text"')).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Compare bill text" }));
    await user.click(await screen.findByRole("button", { name: /modified sec\. 1#1/ }));
    expect(await screen.findByText(/old line/)).toBeVisible();
    expect(screen.getByText(/new line/)).toBeVisible();
  });
});
