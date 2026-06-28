"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { getRepresentatives, type RepresentativeItem } from "@/lib/api";

const PAGE_SIZE = 20;

const US_STATES = [
  "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
  "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
  "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
  "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
  "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
];

function RepresentativesTable() {
  const [page, setPage] = useState<{
    count: number;
    results: RepresentativeItem[];
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stateFilter, setStateFilter] = useState<string>("");
  const [chamberFilter, setChamberFilter] = useState<string>("");
  const [pageNum, setPageNum] = useState(1);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getRepresentatives({
      state: stateFilter || undefined,
      chamber: chamberFilter || undefined,
      page: pageNum,
    })
      .then((data) => {
        if (!cancelled) setPage(data);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load representatives");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [stateFilter, chamberFilter, pageNum]);

  const hasNext =
    page &&
    page.results.length === PAGE_SIZE &&
    page.count > pageNum * PAGE_SIZE;

  return (
    <div className="min-h-screen bg-background p-6 font-mono text-slate-900 dark:text-green-300">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-green-400">Representatives</h1>
          <Link
            href="/"
            className="cursor-pointer text-blue-900 underline hover:text-blue-950 dark:text-green-500 dark:hover:text-green-400"
          >
            ← Dashboard
          </Link>
        </div>

        <div className="mb-4 flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2">
            <span className="text-slate-600 dark:text-green-500">State:</span>
            <select
              value={stateFilter}
              onChange={(e) => {
                setPageNum(1);
                setStateFilter(e.target.value);
              }}
              className="cursor-pointer rounded border border-slate-400 bg-white px-2 py-1 text-slate-900 dark:border-green-700 dark:bg-black dark:text-green-300"
            >
              <option value="">All</option>
              {US_STATES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2">
            <span className="text-slate-600 dark:text-green-500">Chamber:</span>
            <select
              value={chamberFilter}
              onChange={(e) => {
                setPageNum(1);
                setChamberFilter(e.target.value);
              }}
              className="cursor-pointer rounded border border-slate-400 bg-white px-2 py-1 text-slate-900 dark:border-green-700 dark:bg-black dark:text-green-300"
            >
              <option value="">All</option>
              <option value="house">House</option>
              <option value="senate">Senate</option>
            </select>
          </label>
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
              {page.count} representative{page.count !== 1 ? "s" : ""} (ingested from bills/votes)
            </p>
            <div className="overflow-x-auto rounded-lg border border-slate-400 dark:border-green-800">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-slate-400 bg-slate-300/80 dark:border-green-800 dark:bg-green-950/20">
                    <th className="p-3 font-semibold text-slate-900 dark:text-green-400">Name</th>
                    <th className="p-3 font-semibold text-slate-900 dark:text-green-400">State</th>
                    <th className="p-3 font-semibold text-slate-900 dark:text-green-400">Chamber</th>
                    <th className="p-3 font-semibold text-slate-900 dark:text-green-400">Party</th>
                    <th className="p-3 font-semibold text-slate-900 dark:text-green-400">District</th>
                  </tr>
                </thead>
                <tbody>
                  {page.results.map((rep) => (
                    <tr
                      key={rep.id}
                      className="border-b border-slate-300 hover:bg-white/60 dark:border-green-900/50 dark:hover:bg-green-950/10"
                    >
                      <td className="p-3 font-medium">{rep.name}</td>
                      <td className="p-3">{rep.state}</td>
                      <td className="p-3 capitalize">{rep.chamber}</td>
                      <td className="p-3">{rep.party}</td>
                      <td className="p-3">{rep.district ?? "—"}</td>
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

export default function RepresentativesPage() {
  return <RepresentativesTable />;
}
