"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import {
  getDefinitionItems,
  getOfficialSummary,
  getReaderItems,
  getTimelineItems,
  type BillDetailSummary,
} from "@/lib/api";
import type {
  BillContractSummary,
  LegalNlpDefinitionItem,
  LegalNlpLineItem,
  LegalNlpSectionPathItem,
  LegalNlpSectionSupplement,
  LegalNlpTimelinePublicItem,
  LegalNlpV21ContractSummary,
} from "@/lib/contracts";
import {
  cleanLegislativeText,
  isReaderReady,
  readablePath,
  readerOverview,
} from "@/lib/reader-guide";
import { SourceEvidence } from "./source-evidence";
import { buildGlossary, legalDefinition, type GlossaryEntry } from "@/lib/glossary";
import { ReaderExplanation, ReaderIdentityProvider, ReaderSummary, LegacyReaderChanges } from "./reader-explanation";

interface BillBriefProps {
  bill: BillDetailSummary;
  contractSummary: BillContractSummary;
  onShowAllFinancial: (lineItemId: string) => void;
}

function normalizedParagraph(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}

function withoutDuplicateTitle(value: string, title: string): string {
  const paragraphs = value.split(/\n\s*\n/);
  if (paragraphs.length > 1 && normalizedParagraph(paragraphs[0]) === normalizedParagraph(title)) {
    return paragraphs.slice(1).join("\n\n").trim();
  }
  return value.trim();
}

function pathKey(path: LegalNlpSectionPathItem[]): string {
  return JSON.stringify(path);
}

function pathLabel(path: LegalNlpSectionPathItem[]): string {
  return readablePath(path);
}

function activeDocument(bill: BillDetailSummary) {
  return bill.documents.find((document) => document.is_active_version) ?? bill.documents[0] ?? null;
}

function contractDocument(bill: BillDetailSummary, documentId: number | null) {
  if (documentId !== null) return bill.documents.find((document) => document.id === documentId) ?? null;
  return activeDocument(bill);
}

type BillDocument = BillDetailSummary["documents"][number];

function LinkedTimelineDetails({ contractId, item, document }: { contractId: number; item: LegalNlpLineItem; document: BillDocument | null }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<LegalNlpTimelinePublicItem[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  useEffect(() => () => { requestId.current += 1; }, [contractId, item.id]);

  async function load(targetPage: number, append: boolean) {
    const activeRequest = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const response = await getTimelineItems(contractId, { page: targetPage, pageSize: 25, lineItemId: item.id });
      if (requestId.current !== activeRequest) return;
      setItems((current) => append ? [...current, ...response.results] : response.results);
      setPage(targetPage);
      setHasMore(Boolean(response.next));
    } catch {
      if (requestId.current === activeRequest) setError("Could not load linked deadlines. Try again.");
    } finally {
      if (requestId.current === activeRequest) setLoading(false);
    }
  }

  if (item.timeline_count <= item.timeline_preview.length) return null;
  return (
    <div className="mt-2">
      <button type="button" aria-expanded={open} onClick={() => { const next = !open; setOpen(next); if (next && items.length === 0 && !loading) void load(1, false); }} className="cursor-pointer text-sm font-semibold text-blue-900 underline dark:text-green-400">Show all {item.timeline_count} deadlines</button>
      {open && (
        <div className="mt-3">
          {loading && items.length === 0 && <p className="text-sm text-slate-600 dark:text-green-600">Loading linked deadlines…</p>}
          {error && <div role="alert" className="text-sm text-red-700 dark:text-red-300"><p>{error}</p><button type="button" onClick={() => void load(items.length ? page + 1 : 1, items.length > 0)} className="mt-2 border border-current px-2 py-1 font-semibold">Retry linked deadlines</button></div>}
          <ul className="space-y-2 text-sm text-slate-700 dark:text-green-200">{items.map((timeline) => <li key={timeline.id}>{timeline.display_text}</li>)}</ul>
          {hasMore && !error && <button type="button" disabled={loading} onClick={() => void load(page + 1, true)} className="mt-3 border border-slate-700 px-3 py-1.5 text-sm font-semibold dark:border-green-700">{loading ? "Loading linked deadlines…" : "Show 25 more deadlines"}</button>}
          {items.length > 0 && <SourceEvidence contractId={contractId} lineItemId={item.id} textUrl={document?.text_url} downloadUrl={document?.download_url} label="Read deadline source text" />}
        </div>
      )}
    </div>
  );
}

function LinkedDefinitionDetails({ contractId, item, document }: { contractId: number; item: LegalNlpLineItem; document: BillDocument | null }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<LegalNlpDefinitionItem[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  useEffect(() => () => { requestId.current += 1; }, [contractId, item.id]);

  async function load(targetPage: number, append: boolean) {
    const activeRequest = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const response = await getDefinitionItems(contractId, { page: targetPage, pageSize: 25, lineItemId: item.id });
      if (requestId.current !== activeRequest) return;
      setItems((current) => append ? [...current, ...response.results] : response.results);
      setPage(targetPage);
      setHasMore(Boolean(response.next));
    } catch {
      if (requestId.current === activeRequest) setError("Could not load linked terms. Try again.");
    } finally {
      if (requestId.current === activeRequest) setLoading(false);
    }
  }

  if (item.definition_count === 0) return null;
  const label = `View ${item.definition_count} linked ${item.definition_count === 1 ? "term" : "terms"}`;
  return (
    <div className="mt-3">
      <button type="button" aria-expanded={open} onClick={() => { const next = !open; setOpen(next); if (next && items.length === 0 && !loading) void load(1, false); }} className="cursor-pointer text-sm font-semibold text-blue-900 underline dark:text-green-400">{label}</button>
      {open && (
        <div className="mt-3">
          {loading && items.length === 0 && <p className="text-sm text-slate-600 dark:text-green-600">Loading linked terms…</p>}
          {error && <div role="alert" className="text-sm text-red-700 dark:text-red-300"><p>{error}</p><button type="button" onClick={() => void load(items.length ? page + 1 : 1, items.length > 0)} className="mt-2 border border-current px-2 py-1 font-semibold">Retry linked terms</button></div>}
          <dl className="space-y-3">{items.map((definition) => <GlossaryTerm key={definition.id} item={definition} contractId={contractId} document={document} />)}</dl>
          {hasMore && !error && <button type="button" disabled={loading} onClick={() => void load(page + 1, true)} className="mt-3 border border-slate-700 px-3 py-1.5 text-sm font-semibold dark:border-green-700">{loading ? "Loading linked terms…" : "Show 25 more linked terms"}</button>}
        </div>
      )}
    </div>
  );
}

function ReaderItem({ contractId, item, document, onShowAllFinancial }: { contractId: number; item: LegalNlpLineItem; document: BillDocument | null; onShowAllFinancial: (lineItemId: string) => void }) {
  return (
    <li className="border-t border-slate-200 py-4 first:border-t-0 dark:border-green-900/70">
      <ReaderExplanation kind="line_item" itemId={item.id} original={item.display_text} fallback={cleanLegislativeText(item.display_text)} />
      {item.effect && !item.display_text.includes(item.effect) && <p className="mt-2 text-sm leading-6 text-slate-700 dark:text-green-300">{cleanLegislativeText(item.effect)}</p>}
      {item.exact_financial_preview.length > 0 && (
        <div className="mt-3 border-l-2 border-emerald-600 pl-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-green-600">Money in this exact provision · {item.exact_financial_count}</p>
          <ul className="mt-2 space-y-2 text-sm text-slate-700 dark:text-green-200">
            {item.exact_financial_preview.map((financial) => <li key={financial.id}>{financial.display_text}</li>)}
          </ul>
          {item.exact_financial_count > item.exact_financial_preview.length && <button type="button" onClick={() => onShowAllFinancial(item.id)} className="mt-2 cursor-pointer text-sm font-semibold text-blue-900 underline dark:text-green-400">Show all {item.exact_financial_count} money items</button>}
        </div>
      )}
      {item.timeline_preview.length > 0 && (
        <div className="mt-3 border-l-2 border-amber-500 pl-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-green-600">Deadlines in this exact provision · {item.timeline_count}</p>
          <ul className="mt-2 space-y-2 text-sm text-slate-700 dark:text-green-200">{item.timeline_preview.map((timeline) => <li key={timeline.id}>{timeline.display_text}</li>)}</ul>
          <LinkedTimelineDetails contractId={contractId} item={item} document={document} />
        </div>
      )}
      <LinkedDefinitionDetails contractId={contractId} item={item} document={document} />
      <SourceEvidence contractId={contractId} lineItemId={item.id} textUrl={document?.text_url} downloadUrl={document?.download_url} />
    </li>
  );
}

function GlossaryTerm({ item, contractId, document }: { item: LegalNlpDefinitionItem; contractId: number; document: BillDocument | null }) {
  return <GlossaryEntryView entry={buildGlossary([item])[0]} contractId={contractId} document={document} />;
}

import { useAiGlossary } from "./ai-glossary-context";

export function GlossaryEntryView({ entry, contractId, document }: { entry: GlossaryEntry; contractId: number; document: BillDocument | null }) {
  const { enhancement } = useAiGlossary();
  const result = enhancement?.status === "succeeded" && (enhancement.source_compatible ?? !enhancement.stale) ? enhancement.result : null;
  const refined = result && result.schema_version !== "2.0-source-first" && result.schema_version !== "1.4"
    ? result.glossary?.find(item => item.contract_id === contractId && item.cited_sources.length > 0 &&
      entry.sources.some(source => source.id === item.definition_id && source.term === item.term && source.definition === item.definition))
    : undefined;
  return <div className="border-l-2 border-slate-300 pl-3 dark:border-green-800">
    <dt className="font-semibold text-slate-950 dark:text-green-300">{entry.term}</dt>
    <dd className="mt-1 text-slate-700 dark:text-green-200">{result?.schema_version === "1.4"
      ? <ReaderExplanation kind="definition" itemId={entry.sources[0].id} original={entry.sources[0].display_text || entry.sources[0].definition} fallback={entry.explanation} />
      : refined?.text ?? entry.explanation}</dd>
    {refined && <dd className="text-xs text-slate-500">AI explanation · private</dd>}
    <dd className="mt-1 text-xs text-slate-500 dark:text-green-500">Used in: {entry.scopes.join("; ") || "See source section"}</dd>
    <dd><details className="mt-2 text-sm">
      <summary className="cursor-pointer text-blue-900 underline dark:text-green-400">View legal definition</summary>
      <p className="mt-2 text-slate-700 dark:text-green-200">{legalDefinition(entry.sources[0])}</p>
      {refined?.source_quotes?.map((quote, index) => <blockquote key={index} className="mt-2 border-l pl-2">{quote.quote}</blockquote>)}
      {entry.sources.map(item => <div key={item.id}>
      <p className="mt-1 text-xs text-slate-500 dark:text-green-500">{pathLabel(item.section_path)}</p>
      <SourceEvidence contractId={contractId} definitionItemId={item.id} textUrl={document?.text_url} downloadUrl={document?.download_url} />
      </div>)}
    </details></dd>
  </div>;
}

function KeyTerms({ document, contractId, totalCount }: { document: BillDocument | null; contractId: number; totalCount: number }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<LegalNlpDefinitionItem[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  useEffect(() => () => { requestId.current += 1; }, [contractId]);

  async function load() {
    const activeRequest = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const all: LegalNlpDefinitionItem[] = [];
      let page = 1;
      while (true) {
        const response = await getDefinitionItems(contractId, { page, pageSize: 25 });
        if (requestId.current !== activeRequest) return;
        all.push(...response.results);
        if (!response.next) break;
        if (!response.results.length || page * 25 >= response.count) throw new Error("Invalid glossary pagination");
        page += 1;
      }
      setItems(all);
      setLoaded(true);
    } catch {
      if (requestId.current === activeRequest) setError("Could not load key terms. Try again.");
    } finally {
      if (requestId.current === activeRequest) setLoading(false);
    }
  }

  if (totalCount === 0) return null;
  const entries = buildGlossary(items);
  return (
    <section className="border-t border-slate-300 px-4 py-4 dark:border-green-900">
      <button type="button" aria-expanded={open} onClick={() => { const next = !open; setOpen(next); if (next && !loaded && !loading) void load(); }} className="inline-flex cursor-pointer items-center gap-2 text-base font-semibold text-slate-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-green-700 dark:text-green-400">
        <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" className={`h-4 w-4 shrink-0 transition-transform motion-reduce:transition-none ${open ? "rotate-90" : ""}`}>
          <path d="m7 4 6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Key terms{loaded ? ` (${entries.length})` : ""}
      </button>
      {open && (
        <div className="mt-3">
          <p className="mb-4 text-sm text-slate-600 dark:text-green-600">Brief explanations for reading this bill. Legal definitions contain the complete criteria; meanings can differ by section.</p>
          {loading && items.length === 0 && <p className="text-sm text-slate-600 dark:text-green-600">Loading key terms…</p>}
          {error && <div role="alert" className="text-sm text-red-700 dark:text-red-300"><p>{error}</p><button type="button" disabled={loading} onClick={() => void load()} className="mt-2 border border-current px-2 py-1 font-semibold">Retry key terms</button></div>}
          <dl className="space-y-4">{entries.map(entry => <GlossaryEntryView key={entry.sources[0].id} entry={entry} contractId={contractId} document={document} />)}</dl>
        </div>
      )}
    </section>
  );
}

function V21Brief({ bill, contract, onShowAllFinancial }: { bill: BillDetailSummary; contract: LegalNlpV21ContractSummary; onShowAllFinancial: (lineItemId: string) => void }) {
  const [summary, setSummary] = useState<string | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [items, setItems] = useState<LegalNlpLineItem[]>([]);
  const [supplements, setSupplements] = useState<Map<string, LegalNlpSectionSupplement>>(new Map());
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [requestedPage, setRequestedPage] = useState(1);
  const [readerCount, setReaderCount] = useState(0);
  const [readerLoading, setReaderLoading] = useState(false);
  const [readerError, setReaderError] = useState<string | null>(null);
  const summaryRequest = useRef(0);
  const readerRequest = useRef(0);
  const readerHeading = useRef<HTMLHeadingElement>(null);
  const document = contractDocument(bill, contract.document);
  async function loadReader(targetPage: number, navigate = false) {
    const activeRequest = ++readerRequest.current;
    setReaderLoading(true);
    setReaderError(null);
    setRequestedPage(targetPage);
    try {
      const response = await getReaderItems(contract.id, { page: targetPage, pageSize: 6 });
      if (readerRequest.current !== activeRequest) return;
      const readableItems = response.results.filter(isReaderReady);
      setItems(readableItems);
      setReaderCount(response.count);
      setSupplements(() => {
        const next = new Map<string, LegalNlpSectionSupplement>();
        for (const supplement of response.section_supplements) next.set(supplement.section_id, supplement);
        return next;
      });
      setPage(targetPage);
      setHasMore(Boolean(response.next));
      if (navigate) {
        readerHeading.current?.focus({ preventScroll: true });
        readerHeading.current?.scrollIntoView?.({ block: "start" });
      }
    } catch {
      if (readerRequest.current === activeRequest) setReaderError("Could not load the bill breakdown. Try again.");
    } finally {
      if (readerRequest.current === activeRequest) setReaderLoading(false);
    }
  }

  useEffect(() => {
    setItems([]);
    setPage(1);
    setHasMore(false);
    void loadReader(1);
    return () => { readerRequest.current += 1; summaryRequest.current += 1; };
  }, [contract.id]);

  async function loadSummary() {
    const activeRequest = ++summaryRequest.current;
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      const response = await getOfficialSummary(bill.id);
      if (summaryRequest.current === activeRequest) setSummary(response.summary ? withoutDuplicateTitle(response.summary, bill.title) : null);
    } catch {
      if (summaryRequest.current === activeRequest) setSummaryError("Could not load the complete summary. Try again.");
    } finally {
      if (summaryRequest.current === activeRequest) setSummaryLoading(false);
    }
  }

  const preview = bill.summary_preview ? withoutDuplicateTitle(bill.summary_preview, bill.title) : null;
  const sourceLabel = bill.summary_source === "crs"
    ? "Official CRS summary"
    : bill.summary_source === "source_metadata"
      ? "Congress.gov source description"
      : preview
        ? "Previously stored bill summary"
        : null;
  const fallbackOverview = contract.orientation.purpose_clause
    ?? document?.reader_summary
    ?? readerOverview(bill.jurisdiction, bill.status, bill.topics.map((topic) => topic.name));
  const grouped = items.reduce<Array<{ key: string; path: LegalNlpSectionPathItem[]; items: LegalNlpLineItem[] }>>((groups, item) => {
    const key = pathKey(item.section_path);
    const previous = groups.at(-1);
    if (previous?.key === key) previous.items.push(item);
    else groups.push({ key, path: item.section_path, items: [item] });
    return groups;
  }, []);

  return (
    <section className="mb-6 overflow-hidden rounded-lg border border-slate-400/80 bg-white/85 shadow-sm dark:border-green-800/80 dark:bg-green-950/20 dark:shadow-none">
      <div className="p-4 sm:p-5">
        <p className="font-sans text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-green-700">Reader brief</p>
        <h2 className="mt-1 text-2xl font-semibold text-slate-950 dark:text-green-400">What this bill does</h2>
        <ReaderSummary>{sourceLabel ? (
          <div className="mt-4">
            <p className="text-sm font-semibold text-slate-700 dark:text-green-500">{sourceLabel}{bill.summary_action_date ? ` · ${bill.summary_action_date}` : ""}</p>
            {preview && !summary && <p className="mt-2 w-full whitespace-pre-line text-base leading-7 text-slate-900 dark:text-green-100">{preview}</p>}
            {summary && <p className="mt-2 w-full whitespace-pre-line text-base leading-7 text-slate-900 dark:text-green-100">{summary}</p>}
            {bill.summary_has_more && !summary && <button type="button" disabled={summaryLoading} onClick={() => void loadSummary()} className="mt-3 cursor-pointer text-sm font-semibold text-blue-900 underline decoration-blue-300 underline-offset-4 dark:text-green-400">{summaryLoading ? "Loading complete summary…" : bill.summary_source === "crs" ? "Read full official summary" : "Read full source description"}</button>}
            {summaryError && <div role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300"><p>{summaryError}</p><button type="button" onClick={() => void loadSummary()} className="mt-1 border border-current px-2 py-1 font-semibold">Retry complete summary</button></div>}
          </div>
        ) : <div className="mt-4">
          <p className="mt-2 w-full text-base leading-7 text-slate-900 dark:text-green-100">{fallbackOverview}</p>
          {contract.orientation.purpose_clause && contract.orientation.purpose_line_item_id && <SourceEvidence contractId={contract.id} lineItemId={contract.orientation.purpose_line_item_id} textUrl={document?.text_url} downloadUrl={document?.download_url} label="Read synopsis source text" />}
          {!contract.orientation.purpose_clause && document?.reader_summary && <a href={`/documents/${document.id}`} className="mt-2 inline-block underline">Read summary source text</a>}
        </div>}</ReaderSummary>
        {bill.congress_gov_url && <a href={bill.congress_gov_url} target="_blank" rel="noopener noreferrer" className="mt-3 inline-block text-sm font-semibold text-blue-900 underline dark:text-green-400">View on Congress.gov</a>}
      </div>

      <div className="border-y border-slate-300 bg-slate-50/70 p-4 dark:border-green-900 dark:bg-black/20 sm:p-5">
        <h3 className="text-xl font-semibold text-slate-950 dark:text-green-400">Topics</h3>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600 dark:text-green-600">Policy areas covered by this bill. Select a topic to see every matching bill.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {bill.topics.map((topic) => (
            <Link key={topic.topic_id} href={`/bills?topic_id=${topic.topic_id}`} className="inline-flex max-w-full items-center rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-sm font-medium text-blue-900 transition-colors hover:border-blue-400 hover:bg-blue-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700 dark:border-green-800 dark:bg-green-950/20 dark:text-green-300 dark:hover:border-green-600 dark:hover:bg-green-950/40 dark:focus-visible:outline-green-500">
              {topic.name}
            </Link>
          ))}
        </div>
      </div>

      <div className="p-4 sm:p-5">
        <h3 ref={readerHeading} tabIndex={-1} className="mb-3 scroll-mt-4 text-xl font-semibold text-slate-950 dark:text-green-400">What changes</h3>
        <aside className="mb-4 text-sm leading-6 text-slate-700 dark:text-green-300" aria-label="About this breakdown">
          <p>{contract.coverage_note}</p>
          {document?.text_url && <Link href={`/documents/${document.id}`} className="font-semibold text-blue-900 underline dark:text-green-400">Read full bill text</Link>}
        </aside>
        <LegacyReaderChanges>
          <div className="mt-4" aria-busy={readerLoading}>
            <p className="text-sm leading-6 text-slate-600 dark:text-green-600">In bill order. Read the source for the exact legal wording.</p>
            {readerLoading && items.length === 0 && <p className="mt-4 text-sm text-slate-600 dark:text-green-600">Loading bill provisions…</p>}
            {readerError && <div role="alert" className="mt-4 text-sm text-red-700 dark:text-red-300"><p>{readerError}</p><button type="button" onClick={() => void loadReader(requestedPage, true)} className="mt-2 border border-current px-2 py-1 font-semibold">Retry bill provisions</button></div>}
            <div className="mt-4 flex flex-col gap-4">{grouped.map((group, index) => {
              const section = supplements.get(group.items[0].section_id);
              return <section key={`${group.key}-${index}`} className="rounded-lg border border-slate-300 p-5 dark:border-green-800"><h4 className="font-sans text-sm font-semibold text-slate-700 dark:text-green-500">{pathLabel(group.path)}</h4>{section && (section.section_financial_count > 0 || section.section_timeline_count > 0) && <p className="mt-1 text-xs text-slate-500 dark:text-green-700">{section.section_financial_count > 0 ? `Money in this section: ${section.section_financial_count}` : ""}{section.section_financial_count > 0 && section.section_timeline_count > 0 ? " · " : ""}{section.section_timeline_count > 0 ? `Deadlines in this section: ${section.section_timeline_count}` : ""}</p>}<ol>{group.items.map((item) => <ReaderItem key={item.id} contractId={contract.id} item={item} document={document} onShowAllFinancial={onShowAllFinancial} />)}</ol></section>;
            })}</div>
            {!readerLoading && !readerError && !items.length && <p className="mt-4">No readable provisions on this page. Use Next to continue if more pages are available.</p>}
            {readerCount > 0 && <nav aria-label="Bill provision pages" className="mt-5 flex flex-wrap items-center justify-center gap-4">
              <button type="button" disabled={readerLoading || page === 1} onClick={() => void loadReader(page - 1, true)} className="rounded border border-slate-500 px-3 py-2 text-sm font-semibold disabled:opacity-40">Previous provisions</button>
              <span className="text-sm" role="status">Page {page} of {Math.ceil(readerCount / 6)}</span>
              <button type="button" disabled={readerLoading || !hasMore} onClick={() => void loadReader(page + 1, true)} className="rounded border border-slate-500 px-3 py-2 text-sm font-semibold disabled:opacity-40">Next provisions</button>
            </nav>}
          </div>
        </LegacyReaderChanges>
      </div>
      <KeyTerms key={contract.id} document={document} contractId={contract.id} totalCount={contract.reader_stats.definition_item_count} />
    </section>
  );
}

export function BillBrief({ bill, contractSummary, onShowAllFinancial }: BillBriefProps) {
  if (contractSummary.schema_version !== "2.1-legal-nlp" || contractSummary.reader_stats === null || contractSummary.orientation === null || contractSummary.coverage_note === null) return null;
  return <ReaderIdentityProvider value={{ contractId: contractSummary.id, contractHash: contractSummary.contract_hash, documentId: contractSummary.document }}>
    <V21Brief bill={bill} contract={contractSummary as LegalNlpV21ContractSummary} onShowAllFinancial={onShowAllFinancial} />
  </ReaderIdentityProvider>;
}
