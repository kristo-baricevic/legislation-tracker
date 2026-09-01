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
import { SourceEvidence } from "./source-evidence";

const actionLabels: Record<FinancialAction, string> = {
  appropriation: "Appropriation",
  authorization: "Authorization",
  allocation: "Allocation",
  transfer: "Transfer",
  rescission: "Rescission",
  reduction: "Reduction",
  cancellation: "Cancellation",
  set_aside: "Set-aside",
  limitation: "Limitation",
  other_explicit: "Other explicit financial provision",
};

const directionLabels = {
  increase: "Adds or makes funds available",
  decrease: "Removes or reduces funds",
  neutral_transfer: "Moves existing funds",
  limit: "Sets a limit or reserved share",
} as const;

interface FinancialLedgerProps {
  contractId: number;
  totalCount: number;
  lineItemId?: string;
  sectionId?: string;
  textUrl?: string | null;
  downloadUrl?: string | null;
}

function pathLabel(item: LegalNlpFinancialItem): string {
  return item.section_path
    .map((part) => part.heading ? `${part.label}: ${part.heading}` : part.label)
    .join(" · ");
}

function formatAmount(item: LegalNlpFinancialItem): string | null {
  if (item.amount_type === "such_sums") return "Such sums as necessary";
  if (item.amount_type === "percentage") return item.amount ? `${item.amount}%` : null;
  if (!item.amount) return null;
  const amount = Number(item.amount);
  if (!Number.isFinite(amount)) return item.amount;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: item.currency ?? "USD",
    maximumFractionDigits: 0,
  }).format(amount);
}

export function FinancialLedger({
  contractId,
  totalCount,
  lineItemId,
  sectionId,
  textUrl,
  downloadUrl,
}: FinancialLedgerProps) {
  const [items, setItems] = useState<LegalNlpFinancialItem[]>([]);
  const [filteredCount, setFilteredCount] = useState(totalCount);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<FinancialAction | "">("");
  const [yearInput, setYearInput] = useState("");
  const [filters, setFilters] = useState<{ action: FinancialAction | ""; year: number | null }>({ action: "", year: null });
  const requestId = useRef(0);

  async function load(targetPage: number, append: boolean) {
    const activeRequest = ++requestId.current;
    setLoading(true);
    setError(null);
    const params: FinancialItemsParams = {
      page: targetPage,
      pageSize: 25,
      ...(filters.action ? { financialAction: filters.action } : {}),
      ...(filters.year != null ? { fiscalYear: filters.year } : {}),
      ...(lineItemId ? { lineItemId } : {}),
      ...(sectionId ? { sectionId } : {}),
    };
    try {
      const response = await getFinancialItems(contractId, params);
      if (activeRequest !== requestId.current) return;
      setItems((current) => append ? [...current, ...response.results] : response.results);
      setFilteredCount(response.count);
      setPage(targetPage);
      setHasMore(Boolean(response.next));
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
    void load(1, false);
    return () => {
      requestId.current += 1;
    };
    // load is intentionally driven by this immutable request identity and applied filters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contractId, filters, lineItemId, sectionId, totalCount]);

  function applyFilters() {
    const parsedYear = /^\d{4}$/.test(yearInput) ? Number(yearInput) : null;
    setFilters({ action, year: parsedYear });
  }

  return (
    <section className="mb-6 overflow-hidden rounded-lg border border-slate-400/80 bg-white/85 shadow-sm dark:border-green-800/80 dark:bg-green-950/20 dark:shadow-none" aria-labelledby={`money-${contractId}`}>
      <header className="border-b border-slate-300 bg-slate-100/80 px-4 py-4 dark:border-green-900 dark:bg-black/20">
        <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-green-700">Financial provisions</p>
        <h2 id={`money-${contractId}`} className="mt-1 text-xl font-semibold text-slate-950 dark:text-green-400">Money in this bill</h2>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-700 dark:text-green-200/80">
          This ledger covers recognized appropriations, authorizations, allocations, transfers, rescissions, reductions, cancellations, set-asides, and limitations. It is not a CBO cost estimate and does not combine provisions into a spending total.
        </p>
      </header>

      <div className="p-4">
        <div className="grid gap-3 border-b border-slate-200 pb-4 dark:border-green-900/70 sm:grid-cols-[minmax(0,1fr)_10rem_auto] sm:items-end">
          <label className="text-sm font-semibold text-slate-800 dark:text-green-300">
            Financial action
            <select value={action} onChange={(event) => setAction(event.target.value as FinancialAction | "")} className="mt-1 block w-full border border-slate-400 bg-white px-3 py-2 font-normal text-slate-950 dark:border-green-800 dark:bg-black dark:text-green-200">
              <option value="">All actions</option>
              {Object.entries(actionLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label className="text-sm font-semibold text-slate-800 dark:text-green-300">
            Fiscal year
            <input inputMode="numeric" value={yearInput} onChange={(event) => setYearInput(event.target.value)} placeholder="e.g. 2027" className="mt-1 block w-full border border-slate-400 bg-white px-3 py-2 font-normal text-slate-950 dark:border-green-800 dark:bg-black dark:text-green-200" />
          </label>
          <button type="button" onClick={applyFilters} className="cursor-pointer border border-slate-800 px-3 py-2 text-sm font-semibold text-slate-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-green-700 dark:border-green-700 dark:text-green-300">Apply money filters</button>
        </div>

        <p className="mt-4 text-sm text-slate-600 dark:text-green-600">{filteredCount} of {totalCount} provisions shown</p>
        {error && (
          <div role="alert" className="mt-3 text-sm text-red-700 dark:text-red-300">
            <p>{error}</p>
            <button type="button" onClick={() => void load(items.length === 0 ? 1 : page + 1, items.length > 0)} className="mt-2 cursor-pointer border border-current px-2 py-1 font-semibold">Retry money provisions</button>
          </div>
        )}
        {loading && items.length === 0 && <p aria-live="polite" className="mt-4 text-sm text-slate-600 dark:text-green-600">Loading money provisions…</p>}
        {!loading && !error && items.length === 0 && <p className="mt-4 text-sm text-slate-600 dark:text-green-600">No recognized financial provisions match these filters.</p>}

        {items.length > 0 && (
          <ol className="mt-4 divide-y divide-slate-300 border-y border-slate-300 dark:divide-green-900 dark:border-green-900">
            {items.map((item) => (
              <li key={item.id} className="grid gap-3 py-5 md:grid-cols-[11rem_minmax(0,1fr)]">
                <div>
                  <p className="font-semibold text-slate-950 dark:text-green-300">{actionLabels[item.financial_action]}</p>
                  <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-green-600">{directionLabels[item.direction]}</p>
                  {formatAmount(item) && <p className="mt-2 font-mono text-sm font-semibold text-slate-800 dark:text-green-200">{formatAmount(item)}</p>}
                </div>
                <div>
                  <p className="font-mono text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-green-700">{pathLabel(item)}</p>
                  <p className="mt-2 leading-7 text-slate-800 dark:text-green-100">{item.display_text}</p>
                  {item.fiscal_years.length > 0 && <p className="mt-2 text-sm text-slate-600 dark:text-green-600">Fiscal {item.fiscal_years.join(", ")}</p>}
                  <SourceEvidence contractId={contractId} financialItemId={item.id} textUrl={textUrl} downloadUrl={downloadUrl} />
                </div>
              </li>
            ))}
          </ol>
        )}
        {hasMore && !error && (
          <button type="button" disabled={loading} onClick={() => void load(page + 1, true)} className="mt-4 cursor-pointer border border-slate-700 px-3 py-2 text-sm font-semibold text-slate-950 disabled:opacity-50 dark:border-green-700 dark:text-green-300">
            {loading ? "Loading money provisions…" : "Show 25 more money provisions"}
          </button>
        )}
      </div>
    </section>
  );
}
