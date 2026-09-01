"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import {
  getDefinitionItems,
  getOfficialSummary,
  getReaderItems,
  type BillDetailSummary,
} from "@/lib/api";
import type {
  BillContractSummary,
  LegalNlpDefinitionItem,
  LegalNlpLineItem,
  LegalNlpSectionPathItem,
  LegalNlpSectionSupplement,
  LegalNlpV21ContractSummary,
} from "@/lib/contracts";
import {
  cleanLegislativeText,
  isReaderReady,
  readablePath,
  readerOverview,
  topicExplanation,
} from "@/lib/reader-guide";
import { SourceEvidence } from "./source-evidence";

interface BillBriefProps {
  bill: BillDetailSummary;
  contractSummary: BillContractSummary;
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

function ReaderItem({ bill, contractId, item }: { bill: BillDetailSummary; contractId: number; item: LegalNlpLineItem }) {
  const document = activeDocument(bill);
  return (
    <li className="border-t border-slate-200 py-4 first:border-t-0 dark:border-green-900/70">
      <p className="leading-7 text-slate-900 dark:text-green-100">{cleanLegislativeText(item.display_text)}</p>
      {(item.actor || item.action || item.effect) && (
        <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-3">
          {item.actor && <div><dt className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-green-700">Who</dt><dd className="mt-1 text-slate-700 dark:text-green-300">{cleanLegislativeText(item.actor)}</dd></div>}
          {item.action && <div><dt className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-green-700">Action</dt><dd className="mt-1 text-slate-700 dark:text-green-300">{cleanLegislativeText(item.action)}</dd></div>}
          {item.effect && <div><dt className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-green-700">Effect</dt><dd className="mt-1 text-slate-700 dark:text-green-300">{cleanLegislativeText(item.effect)}</dd></div>}
        </dl>
      )}
      {item.exact_financial_preview.length > 0 && (
        <div className="mt-3 border-l-2 border-emerald-600 pl-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-green-600">Money in this exact provision · {item.exact_financial_count}</p>
          <ul className="mt-2 space-y-2 text-sm text-slate-700 dark:text-green-200">
            {item.exact_financial_preview.map((financial) => <li key={financial.id}>{financial.display_text}</li>)}
          </ul>
          {item.exact_financial_count > item.exact_financial_preview.length && <a href="#money-in-this-bill" className="mt-2 inline-block text-sm font-semibold text-blue-900 underline dark:text-green-400">Show all {item.exact_financial_count}</a>}
        </div>
      )}
      {item.timeline_preview.length > 0 && (
        <div className="mt-3 border-l-2 border-amber-500 pl-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-green-600">Deadlines in this exact provision · {item.timeline_count}</p>
          <ul className="mt-2 space-y-2 text-sm text-slate-700 dark:text-green-200">{item.timeline_preview.map((timeline) => <li key={timeline.id}>{timeline.display_text}</li>)}</ul>
        </div>
      )}
      {item.definition_count > 0 && <p className="mt-3 text-sm text-slate-600 dark:text-green-600">{item.definition_count} linked {item.definition_count === 1 ? "term" : "terms"}</p>}
      <SourceEvidence contractId={contractId} lineItemId={item.id} textUrl={document?.text_url} downloadUrl={document?.download_url} />
    </li>
  );
}

function KeyTerms({ bill, contractId, totalCount }: { bill: BillDetailSummary; contractId: number; totalCount: number }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<LegalNlpDefinitionItem[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);
  const document = activeDocument(bill);

  useEffect(() => () => { requestId.current += 1; }, [contractId]);

  async function load(targetPage: number, append: boolean) {
    const activeRequest = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const response = await getDefinitionItems(contractId, { page: targetPage, pageSize: 25, unlinked: true });
      if (requestId.current !== activeRequest) return;
      setItems((current) => append ? [...current, ...response.results] : response.results);
      setPage(targetPage);
      setHasMore(Boolean(response.next));
    } catch {
      if (requestId.current === activeRequest) setError("Could not load key terms. Try again.");
    } finally {
      if (requestId.current === activeRequest) setLoading(false);
    }
  }

  if (totalCount === 0) return null;
  return (
    <section className="border-t border-slate-300 px-4 py-4 dark:border-green-900">
      <button type="button" aria-expanded={open} onClick={() => { const next = !open; setOpen(next); if (next && items.length === 0 && !loading) void load(1, false); }} className="cursor-pointer text-base font-semibold text-slate-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-green-700 dark:text-green-400">
        Key terms ({totalCount})
      </button>
      {open && (
        <div className="mt-3">
          {loading && items.length === 0 && <p className="text-sm text-slate-600 dark:text-green-600">Loading key terms…</p>}
          {error && <div role="alert" className="text-sm text-red-700 dark:text-red-300"><p>{error}</p><button type="button" onClick={() => void load(items.length ? page + 1 : 1, items.length > 0)} className="mt-2 border border-current px-2 py-1 font-semibold">Retry key terms</button></div>}
          <dl className="space-y-4">{items.map((item) => <div key={item.id} className="border-l-2 border-slate-300 pl-3 dark:border-green-800"><dt className="font-semibold text-slate-950 dark:text-green-300">{item.term}</dt><dd className="mt-1 text-slate-700 dark:text-green-200">{item.definition}</dd><dd className="mt-1 font-mono text-xs text-slate-500 dark:text-green-700">{pathLabel(item.section_path)}</dd><SourceEvidence contractId={contractId} definitionItemId={item.id} textUrl={document?.text_url} downloadUrl={document?.download_url} /></div>)}</dl>
          {hasMore && !error && <button type="button" disabled={loading} onClick={() => void load(page + 1, true)} className="mt-4 border border-slate-700 px-3 py-1.5 text-sm font-semibold dark:border-green-700">{loading ? "Loading key terms…" : "Show 25 more key terms"}</button>}
        </div>
      )}
    </section>
  );
}

function V21Brief({ bill, contract }: { bill: BillDetailSummary; contract: LegalNlpV21ContractSummary }) {
  const [summary, setSummary] = useState<string | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [items, setItems] = useState<LegalNlpLineItem[]>([]);
  const [supplements, setSupplements] = useState<Map<string, LegalNlpSectionSupplement>>(new Map());
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [readerOpen, setReaderOpen] = useState(false);
  const [readerLoading, setReaderLoading] = useState(false);
  const [readerError, setReaderError] = useState<string | null>(null);
  const summaryRequest = useRef(0);
  const readerRequest = useRef(0);
  async function loadReader(targetPage: number, append: boolean) {
    const activeRequest = ++readerRequest.current;
    setReaderLoading(true);
    setReaderError(null);
    try {
      const response = await getReaderItems(contract.id, { page: targetPage, pageSize: 25 });
      if (readerRequest.current !== activeRequest) return;
      const readableItems = response.results.filter(isReaderReady);
      setItems((current) => append ? [...current, ...readableItems] : readableItems);
      setSupplements((current) => {
        const next = append ? new Map(current) : new Map<string, LegalNlpSectionSupplement>();
        for (const supplement of response.section_supplements) next.set(supplement.section_id, supplement);
        return next;
      });
      setPage(targetPage);
      setHasMore(Boolean(response.next));
    } catch {
      if (readerRequest.current === activeRequest) setReaderError(append ? "Could not load more bill provisions. Try again." : "Could not load the bill breakdown. Try again.");
    } finally {
      if (readerRequest.current === activeRequest) setReaderLoading(false);
    }
  }

  useEffect(() => {
    setItems([]);
    setPage(1);
    setHasMore(false);
    setReaderOpen(false);
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
  const sourceLabel = bill.summary_source === "crs" ? "Official CRS summary" : bill.summary_source === "source_metadata" ? "Congress.gov source description" : null;
  const fallbackOverview = readerOverview(bill.jurisdiction, bill.status, bill.topics.map((topic) => topic.name));
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
        <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-green-700">Reader brief · deterministic analysis</p>
        <h2 className="mt-1 text-2xl font-semibold text-slate-950 dark:text-green-400">What this bill does</h2>
        {sourceLabel ? (
          <div className="mt-4">
            <p className="text-sm font-semibold text-slate-700 dark:text-green-500">{sourceLabel}{bill.summary_action_date ? ` · ${bill.summary_action_date}` : ""}</p>
            {preview && !summary && <p className="mt-2 max-w-4xl whitespace-pre-line text-base leading-7 text-slate-900 dark:text-green-100">{preview}</p>}
            {summary && <p className="mt-2 max-w-4xl whitespace-pre-line text-base leading-7 text-slate-900 dark:text-green-100">{summary}</p>}
            {bill.summary_has_more && !summary && <button type="button" disabled={summaryLoading} onClick={() => void loadSummary()} className="mt-3 cursor-pointer text-sm font-semibold text-blue-900 underline decoration-blue-300 underline-offset-4 dark:text-green-400">{summaryLoading ? "Loading complete summary…" : bill.summary_source === "crs" ? "Read full official summary" : "Read full source description"}</button>}
            {summaryError && <div role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300"><p>{summaryError}</p><button type="button" onClick={() => void loadSummary()} className="mt-1 border border-current px-2 py-1 font-semibold">Retry complete summary</button></div>}
          </div>
        ) : <p className="mt-4 max-w-4xl text-base leading-7 text-slate-900 dark:text-green-100">{fallbackOverview}</p>}
        {bill.congress_gov_url && <a href={bill.congress_gov_url} target="_blank" rel="noopener noreferrer" className="mt-3 inline-block text-sm font-semibold text-blue-900 underline dark:text-green-400">View on Congress.gov</a>}
      </div>

      <div className="border-y border-slate-300 bg-slate-50/70 p-4 dark:border-green-900 dark:bg-black/20 sm:p-5">
        <h3 className="text-xl font-semibold text-slate-950 dark:text-green-400">Topics</h3>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600 dark:text-green-600">Policy areas covered by this bill. Select a topic to see every matching bill.</p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {bill.topics.map((topic) => (
            <Link key={topic.topic_id} href={`/bills?topic_id=${topic.topic_id}`} className="border-l-4 border-blue-700 bg-white px-4 py-3 transition-colors hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700 dark:border-green-600 dark:bg-green-950/20 dark:hover:bg-green-950/40 dark:focus-visible:outline-green-500">
              <h4 className="font-semibold text-slate-950 dark:text-green-300">{topic.name}</h4>
              <p className="mt-1 text-sm leading-6 text-slate-700 dark:text-green-200">{topicExplanation(topic.name)}</p>
            </Link>
          ))}
        </div>
      </div>

      <div className="p-4 sm:p-5">
        <details onToggle={(event) => {
          const open = event.currentTarget.open;
          setReaderOpen(open);
          if (open && items.length === 0 && !readerLoading && !readerError) void loadReader(1, false);
        }}>
          <summary className="cursor-pointer text-lg font-semibold text-blue-900 underline decoration-blue-300 underline-offset-4 dark:text-green-400">Browse detailed provisions</summary>
          {readerOpen && <div className="mt-4">
            <p className="text-sm leading-6 text-slate-600 dark:text-green-600">These provisions are shown in bill order. Open the source under any item to verify the exact legal text.</p>
            {readerLoading && items.length === 0 && <p className="mt-4 text-sm text-slate-600 dark:text-green-600">Loading bill provisions…</p>}
            {readerError && <div role="alert" className="mt-4 text-sm text-red-700 dark:text-red-300"><p>{readerError}</p><button type="button" onClick={() => void loadReader(items.length ? page + 1 : 1, items.length > 0)} className="mt-2 border border-current px-2 py-1 font-semibold">Retry bill provisions</button></div>}
            {grouped.map((group) => {
              const section = supplements.get(group.items[0].section_id);
              return <section key={group.key} className="mt-6 border-l-4 border-slate-300 pl-4 dark:border-green-800"><h4 className="font-mono text-sm font-semibold text-slate-700 dark:text-green-500">{pathLabel(group.path)}</h4>{section && (section.section_financial_count > 0 || section.section_timeline_count > 0) && <p className="mt-1 text-xs text-slate-500 dark:text-green-700">{section.section_financial_count > 0 ? `Money in this section: ${section.section_financial_count}` : ""}{section.section_financial_count > 0 && section.section_timeline_count > 0 ? " · " : ""}{section.section_timeline_count > 0 ? `Deadlines in this section: ${section.section_timeline_count}` : ""}</p>}<ol>{group.items.map((item) => <ReaderItem key={item.id} bill={bill} contractId={contract.id} item={item} />)}</ol></section>;
            })}
            {hasMore && !readerError && <button type="button" disabled={readerLoading} onClick={() => void loadReader(page + 1, true)} className="mt-5 border border-slate-700 px-3 py-2 text-sm font-semibold text-slate-950 disabled:opacity-50 dark:border-green-700 dark:text-green-300">{readerLoading ? "Loading provisions…" : "Show 25 more"}</button>}
          </div>}
        </details>
      </div>
      <KeyTerms bill={bill} contractId={contract.id} totalCount={contract.reader_stats.definition_item_count} />
    </section>
  );
}

export function BillBrief({ bill, contractSummary }: BillBriefProps) {
  if (contractSummary.schema_version !== "2.1-legal-nlp" || contractSummary.reader_stats === null || contractSummary.orientation === null || contractSummary.coverage_note === null) return null;
  return <V21Brief bill={bill} contract={contractSummary as LegalNlpV21ContractSummary} />;
}
