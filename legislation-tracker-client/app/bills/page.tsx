"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import RequireAuth from "@/app/components/RequireAuth";
import {
  getBillFilterOptions,
  getBills,
  getTopics,
  type BillListItem,
  type BillsPage,
  type TopicItem,
} from "@/lib/api";

const PAGE_SIZE = 20;

function BillsTable() {
  const [page, setPage] = useState<BillsPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [jurisdictions, setJurisdictions] = useState<string[]>([]);
  const [topics, setTopics] = useState<TopicItem[]>([]);

  const [pageNum, setPageNum] = useState(1);
  const [idFilter, setIdFilter] = useState("");
  const [billNumberFilter, setBillNumberFilter] = useState("");
  const [sessionFilter, setSessionFilter] = useState("119");
  const [jurisdictionFilter, setJurisdictionFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sponsorFilter, setSponsorFilter] = useState("");
  const [topicIdFilter, setTopicIdFilter] = useState<string>("");
  const [topicFuzzyFilter, setTopicFuzzyFilter] = useState("");

  const loadFilterMeta = useCallback(async () => {
    try {
      const [opts, topicList] = await Promise.all([
        getBillFilterOptions(),
        getTopics(),
      ]);
      setJurisdictions(opts.jurisdictions ?? []);
      setTopics(topicList);
    } catch {
      /* non-fatal: filters still work with manual input */
    }
  }, []);

  useEffect(() => {
    loadFilterMeta();
  }, [loadFilterMeta]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const sessionParsed = sessionFilter.trim()
      ? parseInt(sessionFilter.trim(), 10)
      : NaN;
    const idParsed = idFilter.trim() ? parseInt(idFilter.trim(), 10) : NaN;
    const topicIdParsed = topicIdFilter
      ? parseInt(topicIdFilter, 10)
      : NaN;

    getBills({
      page: pageNum,
      session: !Number.isNaN(sessionParsed) ? sessionParsed : undefined,
      id: !Number.isNaN(idParsed) ? idParsed : undefined,
      bill_number: billNumberFilter || undefined,
      jurisdiction: jurisdictionFilter || undefined,
      status: statusFilter || undefined,
      sponsor: sponsorFilter || undefined,
      topic: topicFuzzyFilter || undefined,
      topic_id: !Number.isNaN(topicIdParsed) ? topicIdParsed : undefined,
    })
      .then((data) => {
        if (!cancelled) setPage(data);
      })
      .catch((e) => {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "Failed to load bills");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    pageNum,
    idFilter,
    billNumberFilter,
    sessionFilter,
    jurisdictionFilter,
    statusFilter,
    sponsorFilter,
    topicIdFilter,
    topicFuzzyFilter,
  ]);

  const resetPageAndSet = useCallback(
    (setter: React.Dispatch<React.SetStateAction<string>>) =>
      (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
        setPageNum(1);
        setter(e.target.value);
      },
    [],
  );

  const onTopicDropdownChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setPageNum(1);
    setTopicIdFilter(e.target.value);
    if (e.target.value) setTopicFuzzyFilter("");
  };

  const onTopicFuzzyChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setPageNum(1);
    setTopicFuzzyFilter(e.target.value);
    if (e.target.value.trim()) setTopicIdFilter("");
  };

  const hasNext =
    page &&
    page.results.length === PAGE_SIZE &&
    page.count > pageNum * PAGE_SIZE;

  return (
    <div className="min-h-screen bg-background p-6 font-mono text-slate-900 dark:text-green-300">
      <div className="mx-auto max-w-7xl">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-green-400">
            Ingested Bills
          </h1>
          <Link
            href="/"
            className="cursor-pointer text-blue-900 underline hover:text-blue-950 dark:text-green-500 dark:hover:text-green-400"
          >
            ← Dashboard
          </Link>
        </div>

        <div className="mb-6 rounded-lg border border-slate-400/70 bg-white/70 p-4 shadow-sm dark:border-green-900/60 dark:bg-green-950/10 dark:shadow-none">
          <p className="mb-3 text-sm text-slate-600 dark:text-green-500">
            Filters apply automatically. Topic: use <strong>dropdown</strong> for
            an exact tag, or <strong>topic contains</strong> for a fuzzy match
            (not both).
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-slate-600 dark:text-green-500">Bill ID</span>
              <input
                type="text"
                inputMode="numeric"
                value={idFilter}
                onChange={resetPageAndSet(setIdFilter)}
                placeholder="e.g. 42"
                className="rounded border border-slate-400 bg-white px-2 py-1 text-slate-900 dark:border-green-700 dark:bg-black dark:text-green-300"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-slate-600 dark:text-green-500">Bill # (contains)</span>
              <input
                type="text"
                value={billNumberFilter}
                onChange={resetPageAndSet(setBillNumberFilter)}
                placeholder="e.g. HR 123"
                className="rounded border border-slate-400 bg-white px-2 py-1 text-slate-900 dark:border-green-700 dark:bg-black dark:text-green-300"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-slate-600 dark:text-green-500">Session (Congress)</span>
              <input
                type="text"
                value={sessionFilter}
                onChange={resetPageAndSet(setSessionFilter)}
                placeholder="119"
                className="rounded border border-slate-400 bg-white px-2 py-1 text-slate-900 dark:border-green-700 dark:bg-black dark:text-green-300"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-slate-600 dark:text-green-500">Jurisdiction</span>
              <select
                value={jurisdictionFilter}
                onChange={resetPageAndSet(setJurisdictionFilter)}
                className="cursor-pointer rounded border border-slate-400 bg-white px-2 py-1 text-slate-900 dark:border-green-700 dark:bg-black dark:text-green-300"
              >
                <option value="">All</option>
                {jurisdictions.map((j) => (
                  <option key={j} value={j}>
                    {j}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-slate-600 dark:text-green-500">Status (contains)</span>
              <input
                type="text"
                value={statusFilter}
                onChange={resetPageAndSet(setStatusFilter)}
                placeholder="e.g. House"
                className="rounded border border-slate-400 bg-white px-2 py-1 text-slate-900 dark:border-green-700 dark:bg-black dark:text-green-300"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-slate-600 dark:text-green-500">Sponsor</span>
              <input
                type="text"
                value={sponsorFilter}
                onChange={resetPageAndSet(setSponsorFilter)}
                placeholder="Name or numeric id"
                className="rounded border border-slate-400 bg-white px-2 py-1 text-slate-900 dark:border-green-700 dark:bg-black dark:text-green-300"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-slate-600 dark:text-green-500">Topic (exact)</span>
              <select
                value={topicIdFilter}
                onChange={onTopicDropdownChange}
                className="cursor-pointer rounded border border-slate-400 bg-white px-2 py-1 text-slate-900 dark:border-green-700 dark:bg-black dark:text-green-300"
              >
                <option value="">All</option>
                {topics.map((t) => (
                  <option key={t.id} value={String(t.id)}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-slate-600 dark:text-green-500">Topic contains (fuzzy)</span>
              <input
                type="text"
                value={topicFuzzyFilter}
                onChange={onTopicFuzzyChange}
                placeholder="Matches topic name/slug"
                disabled={Boolean(topicIdFilter)}
                className="rounded border border-slate-400 bg-white px-2 py-1 text-slate-900 disabled:opacity-40 dark:border-green-700 dark:bg-black dark:text-green-300"
              />
            </label>
          </div>
        </div>

        {error && (
          <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
            {error}
          </div>
        )}

        {loading && <p className="text-slate-600 dark:text-green-500">Loading…</p>}

        {!loading && page && (
          <>
            <p className="mb-4 text-slate-600 dark:text-green-500/80">
              {page.count} bill{page.count !== 1 ? "s" : ""} (page {pageNum})
            </p>
            <div className="overflow-x-auto rounded-lg border border-slate-400 dark:border-green-800">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-slate-400 bg-slate-300/80 dark:border-green-800 dark:bg-green-950/20">
                    <th className="p-3 font-semibold text-slate-900 dark:text-green-400">ID</th>
                    <th className="p-3 font-semibold text-slate-900 dark:text-green-400">Bill #</th>
                    <th className="p-3 font-semibold text-slate-900 dark:text-green-400">
                      Jurisdiction
                    </th>
                    <th className="p-3 font-semibold text-slate-900 dark:text-green-400">Session</th>
                    <th className="p-3 font-semibold text-slate-900 dark:text-green-400">Title</th>
                    <th className="p-3 font-semibold text-slate-900 dark:text-green-400">Status</th>
                    <th className="p-3 font-semibold text-slate-900 dark:text-green-400">Sponsor</th>
                    <th className="p-3 font-semibold text-slate-900 dark:text-green-400">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {page.results.map((bill: BillListItem) => (
                    <tr
                      key={bill.id}
                      className="border-b border-slate-300 hover:bg-white/60 dark:border-green-900/50 dark:hover:bg-green-950/10"
                    >
                      <td className="p-3 text-slate-600 dark:text-green-500">{bill.id}</td>
                      <td className="p-3 font-medium">{bill.bill_number}</td>
                      <td className="p-3">{bill.jurisdiction}</td>
                      <td className="p-3">{bill.session}</td>
                      <td className="max-w-md truncate p-3" title={bill.title}>
                        {bill.title}
                      </td>
                      <td className="max-w-xs truncate p-3" title={bill.status}>
                        {bill.status}
                      </td>
                      <td className="p-3">{bill.sponsor_name ?? "—"}</td>
                      <td className="p-3">
                        <Link
                          href={`/bills/${bill.id}`}
                          className="cursor-pointer text-blue-900 underline hover:text-blue-950 dark:text-green-400 dark:hover:text-green-300"
                        >
                          View
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex gap-4">
              {pageNum > 1 && (
                <button
                  type="button"
                  onClick={() => setPageNum((p) => p - 1)}
                  className="cursor-pointer rounded border border-slate-400 px-3 py-1 text-slate-900 hover:bg-white/80 dark:border-green-700 dark:text-green-400 dark:hover:bg-green-950/30"
                >
                  Previous
                </button>
              )}
              {hasNext && (
                <button
                  type="button"
                  onClick={() => setPageNum((p) => p + 1)}
                  className="cursor-pointer rounded border border-slate-400 px-3 py-1 text-slate-900 hover:bg-white/80 dark:border-green-700 dark:text-green-400 dark:hover:bg-green-950/30"
                >
                  Next
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function BillsPage() {
  return (
    <RequireAuth>
      <BillsTable />
    </RequireAuth>
  );
}
