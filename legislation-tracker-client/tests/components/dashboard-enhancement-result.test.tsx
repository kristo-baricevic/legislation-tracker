import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import BillDeck from "@/app/components/BillDeck";
import { ModalStackProvider } from "@/app/components/ModalStack";
import {
  createBillEnhancement, getBill, getBillEnhancement, getBillEnhancementEstimate,
  getMyTracking, getSession, getVotes,
  type BillDetail, type BillEnhancement, type BillEnhancementEstimate, type BillListItem,
} from "@/lib/api";
import { getBillRecommendations } from "@/lib/recommendations";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(),
  getSession: vi.fn(), getMyTracking: vi.fn(), getBill: vi.fn(), getVotes: vi.fn(),
  createBillEnhancement: vi.fn(), getBillEnhancement: vi.fn(), getBillEnhancementEstimate: vi.fn(),
}));
vi.mock("@/lib/recommendations", async original => ({ ...await original<typeof import("@/lib/recommendations")>(),
  getBillRecommendations: vi.fn(),
  getRepresentativeRecommendations: vi.fn(async () => ({ results: [], empty_reason: "no_candidates" })),
}));

const bill: BillListItem = {
  id: 10, bill_number: "HR 1", title: "Public reporting", jurisdiction: "federal", session: 119,
  status: "introduced", sponsor_name: null, last_action_at: null, introduced_at: null, topics: [],
  card_summary: "Original summary.", enhancement_id: null, enhancement_status: null,
};
const saved: BillEnhancement = {
  id: 99, bill_id: 10, status: "succeeded", source_compatible: true, stale: false,
  provider: "openai", requested_model: "test", reasoning_effort: "none",
  prompt_version: "test", output_schema_version: "1.4", source_packet_version: "test",
  source_fingerprint: "source", request_fingerprint: "request", truncated: false,
  coverage_notice: null, disclaimer: "", usage: { input_tokens: 10, output_tokens: 10, total_tokens: 20 },
  created_at: "2026-11-23", updated_at: "2026-11-23", completed_at: "2026-11-23", latest_attempt: null,
  result: {
    schema_version: "1.4", summary: [{ text: "New enhanced summary.", cited_sources: [] }], explanations: [],
    identity: { contract_id: null, contract_hash: null, document_id: 4, document_content_hash: "hash" },
    source_review: { policy_changes: [{ title: "Public reports", text: "The agency must publish annual reports.", cited_sources: [] }],
      financial_items: [], additional_changes: [], reviewed_sources: [] },
  },
};
const estimate: BillEnhancementEstimate = {
  feature_available: true, can_enhance: true, unavailable_reason: null, credential_revision: 1,
  provider: "openai", requested_model: "test", reasoning_effort: "none", prompt_version: "test",
  output_schema_version: "1.4", source_packet_version: "test", source_fingerprint: "source",
  request_fingerprint: "request", serialized_request_bytes: 100, estimated_input_tokens: 100,
  max_output_tokens: 100, max_output_includes_reasoning: true, truncated: false,
  coverage_notice: null, source_description: "document_chunk", matching_enhancement: null,
};
const currentBill = { ...bill, card_summary: "New enhanced summary.", enhancement_id: 99, enhancement_status: "succeeded" as const };
function setCards(row: string, value: BillListItem) {
  vi.mocked(getMyTracking).mockResolvedValue({
    bills: row === "Followed bills" ? [{ id: 1, bill: value, created_at: "2026-11-23" }] : [],
    topics: [], legislators: [], is_staff: false,
  });
  vi.mocked(getBillRecommendations).mockResolvedValue({
    algorithm: "test", generated_at: "2026-11-23", count: row === "Recommended bills" ? 1 : 0,
    results: row === "Recommended bills" ? [{ bill: value, score: 1, reasons: [] }] : [],
    next_cursor: null, candidate_pool_truncated: false, ranking_limit_reached: false,
    empty_reason: null, unsupported_follow_types: [],
  });
}
beforeEach(() => {
  window.dispatchEvent(new StorageEvent("storage", { key: "legislation-tracker-session-epoch" }));
  vi.clearAllMocks();
  vi.mocked(getSession).mockResolvedValue({ authenticated: true, user: { email: "reader@example.test" },
    current_congress: 119, dashboard_revision: "unchanged", tracking_revision: "unchanged" });
  vi.mocked(getBill).mockResolvedValue({ ...bill, sponsor: null, latest_contract: null,
    documents: [{ id: 4, is_active_version: true }] } as BillDetail);
  vi.mocked(getVotes).mockResolvedValue({ count: 0, results: [], next: null, previous: null });
  vi.mocked(getBillEnhancement).mockResolvedValue(saved);
});

for (const row of ["Followed bills", "Recommended bills"]) {
  it.each(["immediate", "polled", "shared"])(`${row}: opens the completed %s result and keeps it after remount`, async completion => {
    setCards(row, bill);
    vi.mocked(getBillEnhancementEstimate).mockResolvedValue(completion === "shared"
      ? { ...estimate, can_enhance: false, unavailable_reason: "shared_enhancement_available", matching_enhancement: saved }
      : estimate);
    vi.mocked(createBillEnhancement).mockResolvedValue(completion === "polled"
      ? { ...saved, status: "pending", result: null, active_reader: null } : saved);
    const view = render(<ModalStackProvider><BillDeck /></ModalStackProvider>);
    const cards = within(await screen.findByRole("region", { name: row }));
    await userEvent.click(cards.getByRole("button", { name: "Enhance" }));
    if (completion !== "shared") await userEvent.click(await screen.findByRole("button", { name: "Confirm and enhance" }));
    expect(await cards.findByRole("button", { name: "Enhanced" }, { timeout: 5000 })).toBeDisabled();
    expect(cards.getByRole("button", { name: "Enhanced" })).toHaveStyle({ backgroundColor: "#735099", color: "#ffffff", opacity: "1" });
    expect(cards.getByText("New enhanced summary.")).toBeVisible();
    await userEvent.click(cards.getByRole(row === "Followed bills" ? "button" : "link", { name: bill.title }));
    const modal = within(await screen.findByRole("dialog"));
    expect(await modal.findByText("New enhanced summary.")).toBeVisible();
    expect(await modal.findByText("The agency must publish annual reports.")).toBeVisible();
    expect(modal.queryByText("Original summary.")).not.toBeInTheDocument();
    view.unmount();
    // The server now has the new result, even if the session revision request
    // has not observed it yet. A stale tab cache must not undo the local success.
    setCards(row, currentBill);
    render(<ModalStackProvider><BillDeck /></ModalStackProvider>);
    const returned = within(await screen.findByRole("region", { name: row }));
    expect(returned.getByText("New enhanced summary.")).toBeVisible();
    expect(returned.getByRole("button", { name: "Enhanced" })).toBeDisabled();
  });
}
