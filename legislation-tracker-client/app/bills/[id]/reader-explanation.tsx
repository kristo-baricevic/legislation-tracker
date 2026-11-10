"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import type { EnhancementCitedSource, ReaderExplanationItem } from "@/lib/api";
import { compatibleReader, resolveReaderExplanation, type ReaderIdentity } from "@/lib/reader-enhancements";
import { useAiGlossary } from "./ai-glossary-context";
import { SourcePopover } from "./source-popover";
import { explanationParagraphs } from "@/lib/reader-copy";

const Identity = createContext<ReaderIdentity | null>(null);
export const ReaderIdentityProvider = Identity.Provider;

export function useCompatibleReader() {
  const { enhancement } = useAiGlossary();
  return compatibleReader(enhancement, useContext(Identity));
}

export function useReaderExplanation(kind: ReaderExplanationItem["kind"], itemId: string, original: string) {
  const { enhancement } = useAiGlossary();
  return resolveReaderExplanation(enhancement, useContext(Identity), kind, itemId, original);
}

export function Evidence({ sources, documentId, notes, number = 1 }: { sources: EnhancementCitedSource[]; documentId: number; notes?: ReactNode; number?: number }) {
  return <SourcePopover number={number}>
    {notes}
    {sources.map((source, index) => <div key={index} className="mb-4 last:mb-0">
      <blockquote className="whitespace-pre-wrap text-slate-700 dark:text-green-300">{source.quoted_text}</blockquote>
      <a className="underline" href={`/documents/${documentId}${source.start_char != null && source.end_char != null ? `?start=${source.start_char}&end=${source.end_char}` : ""}`}>Read bill text</a>
    </div>)}
  </SourcePopover>;
}

export function ReaderExplanation({ kind, itemId, original, fallback = original, citation, heading, details, renderCitation, hideHeading, citationNumber }: {
  kind: ReaderExplanationItem["kind"]; itemId: string; original: string; fallback?: string; citation?: ReactNode; heading?: string; details?: ReactNode;
  renderCitation?: (notes: ReactNode) => ReactNode;
  hideHeading?: boolean;
  citationNumber?: number;
}) {
  const item = useReaderExplanation(kind, itemId, original);
  if (heading) {
    const paragraphs = explanationParagraphs(item?.text ?? fallback);
    const source = item ? <Evidence sources={item.cited_sources} documentId={item.document_id} notes={details} number={citationNumber} /> : renderCitation?.(details) ?? citation;
    return <>
      {!hideHeading && <h4 className="mb-2 text-lg font-semibold text-slate-950 dark:text-green-200">{heading}</h4>}
      <p className="leading-7 text-slate-800 dark:text-green-100">{paragraphs.join(" ")}{source}</p>
    </>;
  }
  if (!item) return <p className="leading-7 text-slate-900 dark:text-green-100">{fallback}{citation}</p>;
  return <div>
    <p className="leading-7 text-slate-900 dark:text-green-100">{item.text}<Evidence sources={item.cited_sources} documentId={item.document_id} notes={details} number={citationNumber} /></p>
  </div>;
}

export function useSummaryCitationCount() {
  const { enhancement } = useAiGlossary();
  const identity = useContext(Identity);
  const legacy = useLegacyReader();
  const result = compatibleReader(enhancement, identity);
  if (legacy?.overview.length && identity?.documentId != null) return legacy.overview.length;
  return result?.summary.length && result.summary.every(item => item.cited_sources.length) ? result.summary.length : 1;
}

export function ReaderSummary({ children }: { children: ReactNode }) {
  const { enhancement } = useAiGlossary();
  const identity = useContext(Identity);
  const legacy = useLegacyReader();
  const result = compatibleReader(enhancement, identity);
  // Older saved prose may contain clipped sentences. Never present those as
  // the brief while a corrected, source-bound analysis is being refreshed.
  if (result?.summary.some(item => !/[.!?]$/.test(item.text.trim()))) return <>{children}</>;
  if (legacy?.overview.length && identity?.documentId != null) return <div className="mt-4 space-y-3">
    {legacy.overview.map((item, index) => <p key={index} className="w-full text-base leading-7">{item.text}<Evidence number={index + 1} sources={item.cited_sources} documentId={identity.documentId!} /></p>)}
  </div>;
  if (!result?.summary.length || result.summary.some(item => !item.cited_sources.length)) return <>{children}</>;
  return <div className="mt-4">
    {result.summary.map((item, index) => <div key={index}>
      <p className="w-full text-base leading-7 text-slate-900 dark:text-green-100">{item.text}<Evidence number={index + 1} sources={item.cited_sources} documentId={result.identity.document_id} /></p>
    </div>)}
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
  const reader = useCompatibleReader();
  if (reader?.source_review?.policy_changes) return <PolicyChanges key={`${enhancement?.id}-${reader.identity.contract_hash}`} reader={reader} />;
  if (reader?.source_review) return <>{children}<ReviewedChanges key={`${reader.identity.contract_hash}-${enhancement?.id}`} reader={reader} /></>;
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
    <ul>{rows.slice((current - 1) * 6, current * 6).map((item, index) => {
      const paragraphs = explanationParagraphs(item.text);
      return <li key={`${current}-${index}`} className="border-b border-slate-200 py-5 last:border-b-0 dark:border-green-900/70">
        {paragraphs.map((text, index) => <p key={index} className="mt-2 w-full leading-7">{text}{index === paragraphs.length - 1 && <Evidence sources={item.cited_sources} documentId={identity.documentId!} />}</p>)}
      </li>;
    })}</ul>
    {totalPages > 1 && <nav aria-label="AI explanation pages" className="mt-4 flex items-center justify-center gap-4">
      <button type="button" disabled={current === 1} onClick={() => setPage(current - 1)} className="rounded border px-3 py-2 disabled:opacity-40">Prev</button>
      <span>Page {current} of {totalPages}</span>
      <button type="button" disabled={current === totalPages} onClick={() => setPage(current + 1)} className="rounded border px-3 py-2 disabled:opacity-40">Next</button>
    </nav>}
  </div>;
}

function PolicyChanges({ reader }: { reader: NonNullable<ReturnType<typeof useCompatibleReader>> }) {
  const sourceStart = useSummaryCitationCount() + 2;
  const [page, setPage] = useState(0);
  const rows = reader.source_review?.policy_changes ?? [];
  const pageCount = Math.max(1, Math.ceil(rows.length / 6));
  const current = Math.min(page, pageCount - 1);
  return <div>
    {/* Overlaid grid pages reserve the tallest page's natural height at every
        viewport width. Inactive pages cannot be read, clicked or tabbed into. */}
    <div className="grid">
      {Array.from({ length: pageCount }, (_, index) => <ul key={index}
        aria-label="Bill policy changes" aria-hidden={index !== current} inert={index !== current}
        style={{ gridArea: '1 / 1', visibility: index === current ? 'visible' : 'hidden' }}
        className="m-0 min-w-0 self-start list-none space-y-7">
        {rows.slice(index * 6, index * 6 + 6).map((item, offset) => <li key={offset}>
          <h4 className="mb-1 text-base font-semibold text-slate-950">{item.title}</h4>
          <p className="w-full leading-7 text-slate-800">{item.text}<Evidence number={sourceStart + index * 6 + offset} sources={item.cited_sources} documentId={reader.identity.document_id} /></p>
        </li>)}
      </ul>)}
    </div>
    {pageCount > 1 && <nav aria-label="Policy explanation pages" className="mt-6 flex items-center justify-center gap-4">
      <button type="button" disabled={current === 0} onClick={() => setPage(current - 1)} className="rounded border px-3 py-2 disabled:opacity-40">Prev</button>
      <span aria-live="polite" className="min-w-24 text-center tabular-nums">Page {current + 1} of {pageCount}</span>
      <button type="button" disabled={current === pageCount - 1} onClick={() => setPage(current + 1)} className="rounded border px-3 py-2 disabled:opacity-40">Next</button>
    </nav>}
  </div>;
}

function ReviewedChanges({ reader }: { reader: NonNullable<ReturnType<typeof useCompatibleReader>> }) {
  const [page, setPage] = useState(1);
  const rows = [...(reader.source_review?.additional_changes ?? [])]
    .sort((a, b) => (a.cited_sources[0]?.start_char ?? 0) - (b.cited_sources[0]?.start_char ?? 0));
  const pages = Math.max(1, Math.ceil(rows.length / 6));
  if (!rows.length) return null;
  return <div className="mt-6"><h4 className="mb-4 text-lg font-semibold">Other changes</h4><ul className="space-y-5">{rows.slice((page - 1) * 6, page * 6).map((item, index) =>
    <li key={`${page}-${index}`} className="leading-7">{item.text}<Evidence number={(page - 1) * 6 + index + 1} sources={item.cited_sources} documentId={reader.identity.document_id} /></li>)}</ul>
    {pages > 1 && <nav aria-label="Additional provision pages" className="mt-5 flex items-center justify-center gap-4">
      <button disabled={page === 1} onClick={() => setPage(page - 1)} className="rounded border px-3 py-2 disabled:opacity-40">Prev</button>
      <span>Page {page} of {pages}</span><button disabled={page === pages} onClick={() => setPage(page + 1)} className="rounded border px-3 py-2 disabled:opacity-40">Next</button>
    </nav>}</div>;
}
