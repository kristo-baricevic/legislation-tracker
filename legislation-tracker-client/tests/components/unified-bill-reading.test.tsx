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
  it('paginates long policy lists, keeps citation numbering, and excludes inactive pages from interaction', async () => {
    const policies = { ...saved, result: { ...saved.result, source_review: {
      reviewed_sources: [], financial_items: [], additional_changes: [],
      policy_changes: Array.from({ length: 13 }, (_, i) => ({ title: `Policy ${i + 1}`, text: `Explanation ${i + 1}.`, cited_sources: [] })),
    } } } as BillEnhancement;
    function Policies() {
      const { setEnhancement } = useAiGlossary();
      useEffect(() => setEnhancement(policies), [setEnhancement]);
      return <ReaderIdentityProvider value={identity}><LegacyReaderChanges>Original</LegacyReaderChanges></ReaderIdentityProvider>;
    }
    render(<AiGlossaryProvider><Policies /></AiGlossaryProvider>);
    expect(screen.getAllByRole('heading')).toHaveLength(6);
    expect(screen.getByRole('button', { name: 'Prev' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByRole('heading', { name: 'Policy 7' })).toBeVisible();
    expect(screen.queryByRole('heading', { name: 'Policy 1' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Source 9' })).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getAllByRole('heading')).toHaveLength(1);
    expect(screen.getByRole('heading', { name: 'Policy 13' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Prev' }));
    expect(screen.getByRole('heading', { name: 'Policy 7' })).toBeVisible();
  });
  it("shows one policy-level list including newly discovered changes, with sources and no clause pagination", async () => {
    const source = { source_ref: 'src_0001', label: 'Source', section_label: 'Section 1', quoted_text: 'A credit of $85 applies.', start_char: 0, end_char: 23 };
    const policies = { ...saved, result: { ...saved.result,
      source_review: { reviewed_sources: ['src_0001'], financial_items: [], additional_changes: [],
        policy_changes: [
          { title: 'Help build with wood', text: 'Qualifying wood buildings get an $85 credit per ton of stored carbon.', cited_sources: [source] },
          { title: 'Support housing loans', text: 'States receive grants to help eligible people buy homes.', cited_sources: [source] },
        ] } } } as BillEnhancement;
    function Policies() {
      const { setEnhancement } = useAiGlossary();
      useEffect(() => setEnhancement(policies), [setEnhancement]);
      return <ReaderIdentityProvider value={identity}><ReaderModeSwitch />
        <LegacyReaderChanges><p>Raw amendment clauses</p><p>Page 1 of 19</p></LegacyReaderChanges>
      </ReaderIdentityProvider>;
    }
    render(<AiGlossaryProvider><Policies /></AiGlossaryProvider>);
    expect(screen.getByRole('heading', { name: 'Help build with wood' })).toBeVisible();
    expect(screen.getByText('States receive grants to help eligible people buy homes.')).toBeVisible();
    expect(screen.queryByText('Page 1 of 19')).not.toBeInTheDocument();
    expect(screen.queryByText('Other changes')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Source 3' }));
    expect(screen.getByRole('link', { name: 'Read bill text' })).toHaveAttribute('href', '/documents/4?start=0&end=23');
    await userEvent.keyboard('{Escape}');
    await userEvent.click(screen.getByRole('button', { name: 'Original' }));
    expect(screen.getByText('Raw amendment clauses')).toBeVisible();
  });
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
      <h2>Summary</h2>
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
    await userEvent.click(screen.getByRole("button", { name: "Enhanced" }));
    expect(screen.getByText("Protects workers from harassment.")).toBeVisible();
    expect(screen.getByText("Employers face a fine of up to $1,000.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Enhanced" })).toHaveAttribute("aria-pressed", "true");
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
    expect(screen.queryByText("Original summary.")).not.toBeInTheDocument();
    expect(screen.getByText("Employers face a fine of up to $1,000.")).toBeVisible();
    expect(screen.getByText("Authorizes such sums as necessary.")).toBeVisible();
    await userEvent.click(screen.getAllByRole("button", { name: "Source 1" })[0]);
    expect(screen.getAllByRole("link", { name: "Read bill text" })[0]).toHaveAttribute("href", expect.stringContaining("/documents/4"));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Original" }));
    expect(screen.getByText("A fine of $1,000 applies.")).toBeVisible();
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
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("A separate original financial provision.")).toBeVisible();
    expect(screen.queryByText("Employers face a fine of up to $1,000.")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Apply money filters" }));
    expect(await screen.findByText("A separate original financial provision.")).toBeVisible();
  });
});
