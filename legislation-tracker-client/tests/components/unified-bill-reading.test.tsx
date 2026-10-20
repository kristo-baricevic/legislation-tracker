import { useEffect } from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { BillEnhancement } from "@/lib/api";
import { resolveReaderExplanation } from "@/lib/reader-enhancements";
import { AiGlossaryProvider, useAiGlossary, ReaderModeSwitch } from "@/app/bills/[id]/ai-glossary-context";
import { ReaderIdentityProvider, ReaderExplanation, ReaderSummary, LegacyReaderChanges } from "@/app/bills/[id]/reader-explanation";
import { beginSessionTransition, endSessionTransition } from "@/lib/personalized-scope";
import { FinancialLedger } from "@/app/bills/[id]/financial-ledger";
import { getFinancialItems } from "@/lib/api";

vi.mock("@/lib/api", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/api")>(),
  getFinancialItems: vi.fn(),
}));

const identity = { contractId: 7, contractHash: "hash-a", documentId: 4 };
const saved = {
  id: 1, bill_id: 4846, status: "succeeded", source_compatible: true,
  result: {
    schema_version: "1.4", identity: {
      contract_id: 7, contract_hash: "hash-a", document_id: 4, document_content_hash: "text-a",
    },
    summary: [{ text: "Protects workers from harassment.", cited_sources: [
      { source_ref: "src_0001", quoted_text: "Workplace protections.", start_char: 0, end_char: 22 },
    ] }],
    explanations: [{
      kind: "financial_item", item_id: "fine", target_id: "financial_item:fine", status: "explained",
      contract_id: 7, contract_hash: "hash-a", document_id: 4, document_content_hash: "text-a",
      original_text: "A fine of $1,000 applies.", text: "Employers face a fine of up to $1,000.",
      cited_sources: [{ source_ref: "src_0001", quoted_text: "Not more than $1,000.", start_char: 5, end_char: 25 }],
    }],
  },
} as unknown as BillEnhancement;

describe("unified reader", () => {
  it.each([
    { contractId: 9 }, { contractHash: "hash-b" }, { documentId: 8 },
  ])("does not apply another identity %j", mismatch => {
    expect(resolveReaderExplanation(saved, { ...identity, ...mismatch }, "financial_item", "fine", "A fine of $1,000 applies.")).toBeNull();
  });
  it("keeps missing or changed originals rather than substituting an unrelated AI item", () => {
    expect(resolveReaderExplanation(saved, identity, "financial_item", "other", "Original")).toBeNull();
    expect(resolveReaderExplanation(saved, identity, "financial_item", "fine", "Changed amount")).toBeNull();
  });
  function Content() {
    const { setEnhancement } = useAiGlossary();
    useEffect(() => setEnhancement(saved), [setEnhancement]);
    return <ReaderIdentityProvider value={identity}>
      <ReaderModeSwitch />
      <h2>What this bill does</h2>
      <ReaderSummary><p>Original summary.</p></ReaderSummary>
      <ReaderExplanation kind="financial_item" itemId="fine" original="A fine of $1,000 applies." />
      <ReaderExplanation kind="financial_item" itemId="authorization" original="Authorizes such sums as necessary." />
    </ReaderIdentityProvider>;
  }
  it("switches the whole reading view without hiding controls or starting another request", async () => {
    render(<AiGlossaryProvider><Content /></AiGlossaryProvider>);
    await userEvent.click(screen.getByRole("button", { name: "Original" }));
    expect(screen.getByText("Original summary.")).toBeVisible();
    expect(screen.getByText("A fine of $1,000 applies.")).toBeVisible();
    expect(screen.queryByText("Protects workers from harassment.")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "AI-enhanced" }));
    expect(screen.getByText("Protects workers from harassment.")).toBeVisible();
    expect(screen.getByText("Employers face a fine of up to $1,000.")).toBeVisible();
    expect(screen.getByRole("button", { name: "AI-enhanced" })).toHaveAttribute("aria-pressed", "true");
  });
  it("shows a compatible saved older AI version without requiring regeneration", async () => {
    const legacy = { ...saved, result: { schema_version: "1.3",
      overview: [{ text: "Saved AI summary.", cited_sources: [] }],
      key_impacts: [{ text: "Employers must publish policies.", cited_sources: [] }],
      obligations: [], funding_and_timing: [], uncertain_language: [],
    } } as unknown as BillEnhancement;
    function Legacy() {
      const { setEnhancement } = useAiGlossary();
      useEffect(() => setEnhancement(legacy), [setEnhancement]);
      return <ReaderIdentityProvider value={identity}><ReaderModeSwitch />
        <ReaderSummary><p>Original summary.</p></ReaderSummary>
        <LegacyReaderChanges><p>Original provisions.</p></LegacyReaderChanges>
      </ReaderIdentityProvider>;
    }
    render(<AiGlossaryProvider><Legacy /></AiGlossaryProvider>);
    expect(screen.getByText("Saved AI summary.")).toBeVisible();
    expect(screen.getByText("Employers must publish policies.")).toBeVisible();
    expect(screen.queryByText("Original provisions.")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Original" }));
    expect(screen.getByText("Original provisions.")).toBeVisible();
    expect(screen.queryByText("Saved AI summary.")).not.toBeInTheDocument();
  });
  it("enhances in place, retains unmatched money, and exposes original and source", async () => {
    render(<AiGlossaryProvider><Content /></AiGlossaryProvider>);
    expect(screen.getByText("Protects workers from harassment.")).toBeVisible();
    expect(screen.getByText("Original summary.")).not.toBeVisible();
    expect(screen.getByText("Employers face a fine of up to $1,000.")).toBeVisible();
    expect(screen.getByText("Authorizes such sums as necessary.")).toBeVisible();
    await userEvent.click(screen.getAllByText("View original")[1]);
    expect(screen.getByText("A fine of $1,000 applies.")).toBeVisible();
    expect(screen.getAllByRole("link", { name: "Read bill text" })[0]).toHaveAttribute("href", expect.stringContaining("/documents/4"));
    act(() => { const scope = beginSessionTransition(); endSessionTransition(null, scope); });
    expect(screen.queryByText("Protects workers from harassment.")).not.toBeInTheDocument();
    expect(screen.getByText("Original summary.")).toBeVisible();
  });
  it("keeps financial pagination and filters driven by the original complete inventory", async () => {
    const item = (id: string, text: string) => ({
      id, display_text: text, source_id: id, section_id: "s", section_path: [], section_label: null,
      financial_action: "penalty" as const, direction: "not_applicable" as const,
      amount: "1000", amount_type: "ceiling" as const, currency: "USD" as const,
      fiscal_years: [], purpose: null, source_account: null, destination_account: null,
    });
    vi.mocked(getFinancialItems).mockResolvedValueOnce({
      count: 2, next: "?page=2", previous: null, results: [item("fine", "A fine of $1,000 applies.")],
    }).mockResolvedValueOnce({
      count: 2, next: null, previous: "?page=1", results: [item("other", "A separate original financial provision.")],
    }).mockResolvedValueOnce({
      count: 1, next: null, previous: null, results: [item("other", "A separate original financial provision.")],
    });
    function Ledger() {
      const { setEnhancement } = useAiGlossary();
      useEffect(() => setEnhancement(saved), [setEnhancement]);
      return <ReaderIdentityProvider value={identity}><FinancialLedger contractId={7} totalCount={2} /></ReaderIdentityProvider>;
    }
    render(<AiGlossaryProvider><Ledger /></AiGlossaryProvider>);
    expect(await screen.findByText("Employers face a fine of up to $1,000.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Show 25 more money provisions" }));
    expect(await screen.findByText("A separate original financial provision.")).toBeVisible();
    expect(screen.getByText("Employers face a fine of up to $1,000.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Apply money filters" }));
    expect(await screen.findByText("A separate original financial provision.")).toBeVisible();
  });
});
