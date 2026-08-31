import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BillChangeExperience from "@/app/bills/[id]/bill-change-experience";
import { acknowledgeBillChanges, getBillChanges } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getBillChanges: vi.fn(),
  acknowledgeBillChanges: vi.fn(),
  compareBillContracts: vi.fn(),
  compareBillDocuments: vi.fn(),
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
    expect(acknowledgeBillChanges).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Mark 1 as seen" }));
    expect(acknowledgeBillChanges).toHaveBeenCalledWith(10, "ack-cursor");
    expect(await screen.findByRole("button", { name: "Changes seen" })).toBeVisible();
  });
});
