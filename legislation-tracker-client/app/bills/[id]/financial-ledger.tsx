"use client";

import { useEffect, useRef, useState } from "react";

import {
  getFinancialItems,
  type FinancialItemsParams,
} from "@/lib/api";
import type {
  FinancialAction,
  LegalNlpFinancialItem,
} from "@/lib/contracts";
import { financialPurpose, readablePath } from "@/lib/reader-guide";
import { SourceEvidence } from "./source-evidence";
import { ReaderExplanation, useReaderExplanation } from "./reader-explanation";
import { financialGlossary } from "@/lib/financial-glossary";
import { ProvisionType } from "./provision-type";
import { useCompatibleReader } from "./reader-explanation";
import { ReviewedMoney } from "./reviewed-money";

function FinancialExplanation({ item, contractId, number, textUrl, downloadUrl }: {
  item: LegalNlpFinancialItem; contractId: number; number: number; textUrl?: string | null; downloadUrl?: string | null;
}) {
  const enhanced = useReaderExplanation("financial_item", item.id, item.display_text);
  const notes = <div className="mb-3 space-y-2 text-sm">
    <p className="font-semibold">{pathLabel(item)}</p>
    {(item.source_account || item.destination_account) && <dl className="space-y-2">
      {item.source_account && <div><dt className="font-semibold">From</dt><dd>{item.source_account}</dd></div>}
      {item.destination_account && <div><dt className="font-semibold">To</dt><dd>{item.destination_account}</dd></div>}
    </dl>}
  </div>;
  return <>
    {!enhanced && <p className="mt-1 text-lg font-semibold leading-7 text-slate-950 dark:text-green-200">{financialPurpose(item)}</p>}
    <ReaderExplanation kind="financial_item" itemId={item.id} original={item.display_text} details={notes} citationNumber={number}
      citation={<SourceEvidence contractId={contractId} financialItemId={item.id} textUrl={textUrl} downloadUrl={downloadUrl} annotations={notes} number={number} />} />
  </>;
}

interface FinancialLedgerProps {
  contractId: number;
  totalCount: number;
  lineItemId?: string;
  sectionId?: string;
  textUrl?: string | null;
  downloadUrl?: string | null;
  onClearLineItem?: () => void;
}

function pathLabel(item: LegalNlpFinancialItem): string {
  return readablePath(item.section_path);
}

function formatAmount(item: LegalNlpFinancialItem): string | null {
  if (item.amount_type === "unspecified") return "Amount not extracted";
  if (item.amount_type === "such_sums") return "Such sums as necessary";
  if (item.amount_type === "percentage" || (item.amount_type === "ceiling" && item.currency == null)) return item.amount ? `${Number(item.amount)}%` : null;
  if (!item.amount) return null;
  const amount = Number(item.amount);
  if (!Number.isFinite(amount)) return item.amount;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: item.currency ?? "USD",
    maximumFractionDigits: 0,
  }).format(amount);
}

export function FinancialLedger(props: FinancialLedgerProps) {
  const result = useCompatibleReader();
  if (result?.source_review && !props.lineItemId && !props.sectionId) {
    return <ReviewedMoney key={`${result.identity.contract_hash}-${result.source_review.reviewed_sources.join(',')}`} result={result} />;
  }
  return <OriginalFinancialLedger {...props} />;
}

function OriginalFinancialLedger({
  contractId,
  totalCount,
  lineItemId,
  sectionId,
  textUrl,
  downloadUrl,
  onClearLineItem,
}: FinancialLedgerProps) {
  const [items, setItems] = useState<LegalNlpFinancialItem[]>([]);
  const [filteredCount, setFilteredCount] = useState(totalCount);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<FinancialAction | "">("");
  const [yearInput, setYearInput] = useState("");
  const [filterError, setFilterError] = useState<string | null>(null);
  const [filtersApplied, setFiltersApplied] = useState(false);
  const [filters, setFilters] = useState<{ action: FinancialAction | ""; year: number | null }>({ action: "", year: null });
  const requestId = useRef(0);
  const requestedPage = useRef(1);
  const heading = useRef<HTMLHeadingElement>(null);

  async function load(targetPage: number, navigate = false) {
    requestedPage.current = targetPage;
    const activeRequest = ++requestId.current;
    setLoading(true);
    setError(null);
    const params: FinancialItemsParams = {
      page: targetPage,
      pageSize: 25,
      ...(filters.action ? { financialAction: filters.action } : {}),
      ...(filters.year != null ? { fiscalYear: filters.year } : {}),
      ...(lineItemId ? { lineItemId } : {}),
      ...(!lineItemId && sectionId ? { sectionId } : {}),
    };
    try {
      const response = await getFinancialItems(contractId, params);
      if (activeRequest !== requestId.current) return;
      setItems(response.results);
      setFilteredCount(response.count);
      setPage(targetPage);
      setHasMore(Boolean(response.next));
      if (navigate && !heading.current?.closest("[hidden]")) {
        heading.current?.focus({ preventScroll: true });
        heading.current?.scrollIntoView?.({ block: "start" });
      }
    } catch {
      if (activeRequest === requestId.current) {
        setError("Could not load money provisions. Try again.");
      }
    } finally {
      if (activeRequest === requestId.current) setLoading(false);
    }
  }

  useEffect(() => {
    setItems([]);
    setFilteredCount(totalCount);
    setPage(1);
    setHasMore(false);
    void load(1);
    return () => {
      requestId.current += 1;
    };
    // load is intentionally driven by this immutable request identity and applied filters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contractId, filters, lineItemId, sectionId, totalCount]);

  function applyFilters() {
    if (yearInput.trim() && !/^\d{4}$/.test(yearInput.trim())) {
      setFilterError("Enter a four-digit fiscal year, or leave it blank for all years.");
      return;
    }
    setFilterError(null);
    setFiltersApplied(true);
    const parsedYear = yearInput.trim() ? Number(yearInput.trim()) : null;
    setFilters({ action, year: parsedYear });
  }

  return (
    <section className="mb-6 overflow-hidden rounded-lg border border-slate-400/80 bg-white/85 shadow-sm dark:border-green-800/80 dark:bg-green-950/20 dark:shadow-none" aria-labelledby={`money-${contractId}`}>
      <header className="border-b border-slate-300 bg-slate-100/80 px-4 py-4 dark:border-green-900 dark:bg-black/20">
        <p className="font-sans text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-green-700">Financial provisions</p>
        <h2 ref={heading} tabIndex={-1} id={`money-${contractId}`} className="mt-1 scroll-mt-4 text-xl font-semibold text-slate-950 dark:text-green-400">{lineItemId ? "Money in this provision" : "Money in this bill"}</h2>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-700 dark:text-green-200/80">
          Every recognized financial provision is listed here with its amount, purpose, timing, and source text. This is not a CBO cost estimate and does not combine provisions into a spending total.
        </p>
      </header>

      <div className="p-4">
        <fieldset disabled={totalCount === 0} className="grid gap-3 border-b border-slate-200 pb-4 disabled:opacity-50 dark:border-green-900/70 sm:grid-cols-[minmax(0,1fr)_10rem_auto] sm:items-end">
          <label className="text-sm font-semibold text-slate-800 dark:text-green-300">
            Financial action
            <select value={action} onChange={(event) => setAction(event.target.value as FinancialAction | "")} className="mt-1 block w-full border border-slate-400 bg-white px-3 py-2 font-normal text-slate-950 dark:border-green-800 dark:bg-black dark:text-green-200">
              <option value="">All actions</option>
              {Object.entries(financialGlossary).map(([value, term]) => <option key={value} value={value}>{term.label}</option>)}
            </select>
          </label>
          <label className="text-sm font-semibold text-slate-800 dark:text-green-300">
            Fiscal year
            <input inputMode="numeric" value={yearInput} onChange={(event) => setYearInput(event.target.value)} placeholder="e.g. 2027" className="mt-1 block w-full border border-slate-400 bg-white px-3 py-2 font-normal text-slate-950 dark:border-green-800 dark:bg-black dark:text-green-200" />
          </label>
          <button type="button" onClick={applyFilters} className="cursor-pointer border border-slate-800 px-3 py-2 text-sm font-semibold text-slate-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-green-700 dark:border-green-700 dark:text-green-300">Apply money filters</button>
        </fieldset>
        {filterError && <p role="alert" className="mt-3 text-sm text-red-700 dark:text-red-300">{filterError}</p>}
        {filtersApplied && !loading && !error && !filterError && <p role="status" className="mt-3 text-sm text-slate-700 dark:text-green-300">Filters applied: {filteredCount} matching provisions.</p>}

        {lineItemId && onClearLineItem && (
          <button type="button" onClick={onClearLineItem} className="mt-4 cursor-pointer text-sm font-semibold text-blue-900 underline dark:text-green-400">Show all money in this bill</button>
        )}
        <p className="mt-4 text-sm text-slate-600 dark:text-green-600">
          {items.length} of {lineItemId || sectionId || filters.action || filters.year != null ? `${filteredCount} matching` : totalCount} provisions shown
        </p>
        {error && (
          <div role="alert" className="mt-3 text-sm text-red-700 dark:text-red-300">
            <p>{error}</p>
            <button type="button" disabled={loading} onClick={() => void load(requestedPage.current, true)} className="mt-2 cursor-pointer border border-current px-2 py-1 font-semibold">Retry money provisions</button>
          </div>
        )}
        {loading && items.length === 0 && <p aria-live="polite" className="mt-4 text-sm text-slate-600 dark:text-green-600">Loading money provisions…</p>}
        {!loading && !error && items.length === 0 && <p className="mt-4 text-sm text-slate-600 dark:text-green-600">{totalCount === 0 ? "No financial provisions have been extracted for this bill. Filters are unavailable until financial records exist; this does not mean the bill has no financial effects." : "No recognized financial provisions match these filters."}</p>}

        {items.length > 0 && (
          <ol className="mt-4 divide-y divide-slate-300 border-y border-slate-300 dark:divide-green-900 dark:border-green-900">
            {items.map((item, index) => (
              <li key={item.id} className="grid gap-3 py-5 md:grid-cols-[11rem_minmax(0,1fr)]">
                <div>
                  <ProvisionType action={item.financial_action} />
                  {formatAmount(item) && <p className="mt-2 font-sans text-sm font-semibold text-slate-800 dark:text-green-200">{formatAmount(item)}</p>}
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-green-700">What the money is for</p>
                  <FinancialExplanation item={item} contractId={contractId} number={(page - 1) * 25 + index + 1} textUrl={textUrl} downloadUrl={downloadUrl} />
                  {item.fiscal_years.length > 0 && <p className="mt-2 text-sm text-slate-600 dark:text-green-600">Fiscal {item.fiscal_years.join(", ")}</p>}
                </div>
              </li>
            ))}
          </ol>
        )}
        {filteredCount > 0 && <nav aria-label="Financial provision pages" className="mt-5 flex items-center justify-center gap-4">
          <button type="button" disabled={loading || page <= 1} onClick={() => void load(page - 1, true)} className="rounded border px-3 py-2 disabled:opacity-40">Prev</button>
          <span aria-live="polite">Page {page} of {Math.max(page, Math.ceil(filteredCount / 25))}{loading ? " · Loading…" : ""}</span>
          <button type="button" disabled={loading || !hasMore} onClick={() => void load(page + 1, true)} className="rounded border px-3 py-2 disabled:opacity-40">Next</button>
        </nav>}
      </div>
    </section>
  );
}
