"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import type { EnhancementCitedSource, ReaderExplanationItem } from "@/lib/api";
import { compatibleReader, resolveReaderExplanation, type ReaderIdentity } from "@/lib/reader-enhancements";
import { useAiGlossary } from "./ai-glossary-context";

const Identity = createContext<ReaderIdentity | null>(null);
export const ReaderIdentityProvider = Identity.Provider;

export function useReaderExplanation(kind: ReaderExplanationItem["kind"], itemId: string, original: string) {
  const { enhancement } = useAiGlossary();
  return resolveReaderExplanation(enhancement, useContext(Identity), kind, itemId, original);
}

function Evidence({ sources, documentId }: { sources: EnhancementCitedSource[]; documentId: number }) {
  return <details className="mt-2 text-sm">
    <summary className="cursor-pointer text-blue-900 underline dark:text-green-400">Sources</summary>
    {sources.map((source, index) => <div key={index} className="mt-2 border-l-2 border-slate-300 pl-3">
      <blockquote className="whitespace-pre-wrap text-slate-700 dark:text-green-300">{source.quoted_text}</blockquote>
      <a className="underline" href={`/documents/${documentId}${source.start_char != null && source.end_char != null ? `?start=${source.start_char}&end=${source.end_char}` : ""}`}>Read bill text</a>
    </div>)}
  </details>;
}

export function ReaderExplanation({ kind, itemId, original, fallback = original }: {
  kind: ReaderExplanationItem["kind"]; itemId: string; original: string; fallback?: string;
}) {
  const item = useReaderExplanation(kind, itemId, original);
  if (!item) return <p className="leading-7 text-slate-900 dark:text-green-100">{fallback}</p>;
  return <div>
    <p className="leading-7 text-slate-900 dark:text-green-100">{item.text}</p>
    <span className="text-xs text-slate-500 dark:text-green-500">AI-enhanced</span>
    <details className="mt-2 text-sm">
      <summary className="cursor-pointer text-blue-900 underline dark:text-green-400">View original</summary>
      <p className="mt-2">{fallback}</p>
    </details>
    <Evidence sources={item.cited_sources} documentId={item.document_id} />
  </div>;
}

export function ReaderSummary({ children }: { children: ReactNode }) {
  const { enhancement } = useAiGlossary();
  const identity = useContext(Identity);
  const legacy = useLegacyReader();
  const result = compatibleReader(enhancement, identity);
  if (legacy?.overview.length && identity?.documentId != null) return <div className="mt-4 space-y-3">
    {legacy.overview.map((item, index) => <div key={index}><p className="w-full text-base leading-7">{item.text}</p><Evidence sources={item.cited_sources} documentId={identity.documentId!} /></div>)}
  </div>;
  if (!result?.summary.length || result.summary.some(item => !item.cited_sources.length)) return <>{children}</>;
  return <div className="mt-4">
    {result.summary.map((item, index) => <div key={index}>
      <p className="w-full text-base leading-7 text-slate-900 dark:text-green-100">{item.text}</p>
      <Evidence sources={item.cited_sources} documentId={result.identity.document_id} />
    </div>)}
    <span className="text-xs text-slate-500 dark:text-green-500">AI-enhanced</span>
    <details className="mt-2 text-sm"><summary className="cursor-pointer underline">View original</summary>{children}</details>
  </div>;
}

function useLegacyReader() {
  const { enhancement } = useAiGlossary();
  const result = enhancement?.result;
  return result && result.schema_version !== "1.4" && result.schema_version !== "2.0-source-first" ? result : null;
}

/** Older reports are displayed as their own saved version, never guessed onto NLP IDs. */
export function LegacyReaderChanges({ children }: { children: ReactNode }) {
  const result = useLegacyReader();
  const { enhancement } = useAiGlossary();
  const identity = useContext(Identity);
  const [page, setPage] = useState(1);
  if (!result || identity?.documentId == null) return <>{children}</>;
  const rows = [
    ...result.key_impacts.map(item => ({ ...item, label: "Change" })),
    ...result.obligations.map(item => ({ text: `${item.actor} ${{ required: "must", prohibited: "must not", permitted: "may" }[item.modality]} ${item.action}${item.conditions ? ` ${item.conditions}` : ""}`, cited_sources: item.cited_sources, label: "Requirement" })),
    ...result.funding_and_timing.map(item => ({ ...item, label: item.kind === "funding" ? "Money" : "Timing" })),
    ...result.uncertain_language.map(item => ({ ...item, text: `${item.text} ${item.why_it_matters}`, label: "Uncertainty" })),
  ];
  const totalPages = Math.max(1, Math.ceil(rows.length / 6));
  const current = Math.min(page, totalPages);
  return <div>
    {enhancement?.coverage_notice && <p className="mb-3 text-sm text-amber-800 dark:text-amber-300">{enhancement.coverage_notice}</p>}
    <p className="mb-4 text-sm text-slate-600 dark:text-green-500">Saved AI explanation. Switch to Original to browse every extracted provision; the complete money ledger remains below.</p>
    <ul className="flex flex-col gap-4">{rows.slice((current - 1) * 6, current * 6).map((item, index) => <li key={`${current}-${index}`} className="rounded-lg border border-slate-300 p-5 dark:border-green-800">
      <p className="mb-2 text-sm font-semibold text-slate-600 dark:text-green-500">{item.label}</p>
      <p className="w-full leading-7">{item.text}</p>
      <Evidence sources={item.cited_sources} documentId={identity.documentId!} />
    </li>)}</ul>
    {totalPages > 1 && <nav aria-label="AI explanation pages" className="mt-4 flex items-center justify-center gap-4">
      <button type="button" disabled={current === 1} onClick={() => setPage(current - 1)} className="rounded border px-3 py-2 disabled:opacity-40">Prev</button>
      <span>Page {current} of {totalPages}</span>
      <button type="button" disabled={current === totalPages} onClick={() => setPage(current + 1)} className="rounded border px-3 py-2 disabled:opacity-40">Next</button>
    </nav>}
  </div>;
}
