import React from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import BillModalDetails from "@/app/components/BillModalDetails";
import { getReaderItems, getVotes, getVote } from "@/lib/api";
import type { BillEnhancement, BillDetail } from "@/lib/api";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), getReaderItems: vi.fn(), getVotes: vi.fn(), getVote: vi.fn() }));
const line = { id: "line-1", source_id: "source-1", section_id: "sec-1", section_path: [], kind: "requirement" as const, display_text: "Schools must check applications for identity fraud.", actor: null, action: null, effect: null, exact_financial_count: 0, exact_financial_preview: [], timeline_count: 0, timeline_preview: [], definition_count: 0 };
beforeEach(() => {
  vi.mocked(getVotes).mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
  vi.mocked(getReaderItems).mockResolvedValue({ count: 1, next: null, previous: null, results: [line], section_supplements: [] });
});
it("shows a document-only XML review without an NLP contract, but not for another version", () => {
  const enhancement = { status: "succeeded", source_compatible: true, result: {
    schema_version: "1.4", identity: { contract_id: null, contract_hash: null, document_id: 4, document_content_hash: "text" },
    summary: [], explanations: [], source_review: { reviewed_sources: ["src_0001"], financial_items: [], additional_changes: [],
      policy_changes: [{ title: "Protect workers", text: "Employers must protect workers.", cited_sources: [] }] },
  } } as unknown as BillEnhancement;
  const view = render(<BillModalDetails billId={1876} document={{ id: 4 } as BillDetail["documents"][number]} enhancement={enhancement} />);
  expect(screen.getByText("Employers must protect workers.")).toBeVisible();
  expect(getReaderItems).not.toHaveBeenCalled();
  view.rerender(<BillModalDetails billId={1876} document={{ id: 5 } as BillDetail["documents"][number]} enhancement={enhancement} />);
  expect(screen.queryByText("Employers must protect workers.")).not.toBeInTheDocument();
});
it("uses the saved explanation only for the exact matching contract and source wording", async () => {
  const document = { id: 4 } as BillDetail["documents"][number];
  const enhancement: BillEnhancement = { id: 9, bill_id: 1876, provider: "openai", requested_model: "test",
    reasoning_effort: "none", prompt_version: "1", output_schema_version: "1.4", source_packet_version: "1",
    source_fingerprint: "source", request_fingerprint: "request", truncated: false, coverage_notice: null,
    disclaimer: "", usage: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
    created_at: "2026-11-22T00:00:00Z", updated_at: "2026-11-22T00:00:00Z", completed_at: "2026-11-22T00:00:00Z", latest_attempt: null,
    status: "succeeded", source_compatible: true, result: {
    schema_version: "1.4", identity: { contract_id: 7, contract_hash: "hash", document_id: 4, document_content_hash: "text" },
    summary: [], explanations: [{ kind: "line_item", item_id: line.id, target_id: "line_item:line-1", unresolved_reason: null,
      source_quotes: [{ source_ref: "source-1", quote: "identity fraud" }], status: "explained", original_text: line.display_text,
      contract_id: 7, contract_hash: "hash", document_id: 4, document_content_hash: "text", text: "Schools must check for fake applications.", cited_sources: [{ source_ref: "source-1", label: "Cited source", section_label: null, quoted_text: "identity fraud", start_char: 0, end_char: 14 }] }],
  } };
  const view = render(<BillModalDetails billId={1876} contractId={7} contractHash="hash" document={document} enhancement={enhancement} />);
  expect(await screen.findByText("Schools must check for fake applications.")).toBeVisible();
  expect(screen.queryByText(line.display_text)).not.toBeInTheDocument();
  view.rerender(<BillModalDetails billId={1876} contractId={7} contractHash="new-hash" document={document} enhancement={enhancement} />);
  expect(screen.getByText(line.display_text)).toBeVisible();
  expect(screen.queryByText("Schools must check for fake applications.")).not.toBeInTheDocument();
  if (enhancement.result?.schema_version !== "1.4") throw new Error("Expected reader fixture");
  enhancement.result.source_review = { reviewed_sources: ["source-1"], financial_items: [], additional_changes: [],
    policy_changes: [{ title: "Prevent fraud", text: "Schools must check for fake applications.", cited_sources: enhancement.result.explanations[0].cited_sources }] };
  vi.mocked(getReaderItems).mockClear();
  view.rerender(<BillModalDetails billId={1876} contractId={7} contractHash="hash" document={document} enhancement={enhancement} />);
  expect(screen.getByText("Prevent fraud")).toBeVisible();
  expect(screen.queryByRole("status", { name: "Loading breakdown" })).not.toBeInTheDocument();
  expect(getReaderItems).not.toHaveBeenCalled();
});
it("loads explanations with pagination and retries a failed page", async () => {
  vi.mocked(getReaderItems).mockResolvedValueOnce({ count: 7, next: "page2", previous: null, results: [line], section_supplements: [] }).mockRejectedValueOnce(new Error("offline"));
  render(<BillModalDetails billId={1876} contractId={7} />);
  expect(await screen.findByText(line.display_text)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the breakdown");
  expect(screen.getByText(line.display_text)).toBeVisible();
  expect(screen.getByText("Page 1")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Retry breakdown" }));
  expect(await screen.findByText(line.display_text)).toBeVisible();
  expect(screen.getByText("Page 2")).toBeVisible();
});
it("keeps the current page and controls mounted while the next page loads", async () => {
  let resolve!: (value: Awaited<ReturnType<typeof getReaderItems>>) => void;
  vi.mocked(getReaderItems).mockResolvedValueOnce({ count: 7, next: "page2", previous: null, results: [line], section_supplements: [] })
    .mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  render(<BillModalDetails billId={1876} contractId={7} />);
  await screen.findByText(line.display_text);
  const next = screen.getByRole("button", { name: "Next" });
  await userEvent.click(next);
  expect(screen.getByText(line.display_text)).toBeVisible();
  expect(screen.getByText("Page 1")).toBeVisible();
  expect(next).toBeDisabled();
  await act(async () => resolve({ count: 7, next: null, previous: "page1", results: [{ ...line, id: "second", display_text: "Schools must report results." }], section_supplements: [] }));
  expect(screen.getByText("Page 2")).toBeVisible();
  expect(screen.getByRole("button", { name: "Next" })).toBe(next);
});
it("shows vote history and voter avatars instead of printed member names", async () => {
  const vote = { id: 3, bill: 1876, congress: 119, chamber: "house", session_number: 2, roll_number: 8, vote_date: "2026-11-01", result: "Passed", yeas: 1, nays: 0, question: "On passage" };
  vi.mocked(getVotes).mockResolvedValue({ count: 1, next: null, previous: null, results: [vote] });
  vi.mocked(getVote).mockResolvedValue({ ...vote, records: [{ position: "yes", representative: { id: 121, name: "Burgess Owens", bioguide_id: "O000086", party: "R", chamber: "house", state: "UT", district: "4", image_url: null, first_name: "Burgess", last_name: "Owens", official_website_url: null, is_current: true } }] });
  render(<BillModalDetails billId={1876} />);
  await userEvent.click(await screen.findByRole("button", { name: "View voting record" }));
  expect(await screen.findByRole("link", { name: "Burgess Owens" })).toBeVisible();
  expect(await screen.findByRole("img", { name: "Burgess Owens" })).toHaveAttribute("src", "https://www.congress.gov/img/member/o000086_200.jpg");
  expect(screen.queryByText("Burgess Owens")).not.toBeInTheDocument();
});
