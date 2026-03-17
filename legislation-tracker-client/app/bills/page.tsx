"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import RequireAuth from "@/app/components/RequireAuth";
import { getBills, type BillListItem } from "@/lib/api";

function BillsTable() {
  const [page, setPage] = useState<{
    count: number;
    results: BillListItem[];
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sessionFilter, setSessionFilter] = useState<string>("119");
  const [pageNum, setPageNum] = useState(1);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getBills({
      session: sessionFilter ? parseInt(sessionFilter, 10) : undefined,
      page: pageNum,
    })
      .then((data) => {
        if (!cancelled) {
          setPage(data);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load bills");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionFilter, pageNum]);

  return (
    <div className="min-h-screen bg-black text-green-300 font-mono p-6">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-semibold text-green-400">Ingested Bills</h1>
          <Link
            href="/"
            className="text-green-500 hover:text-green-400 underline"
          >
            ← Dashboard
          </Link>
        </div>

        <div className="flex gap-4 mb-4 items-center">
          <label className="flex items-center gap-2">
            <span className="text-green-500">Session (Congress):</span>
            <input
              type="text"
              value={sessionFilter}
              onChange={(e) => {
                setSessionFilter(e.target.value);
                setPageNum(1);
              }}
              className="bg-black border border-green-700 text-green-300 px-2 py-1 rounded w-20"
            />
          </label>
        </div>

        {error && (
          <div className="mb-4 p-3 border border-red-800 bg-red-950/30 text-red-300 rounded">
            {error}
          </div>
        )}

        {loading && <p className="text-green-500">Loading…</p>}

        {!loading && page && (
          <>
            <p className="mb-4 text-green-500/80">
              {page.count} bill{page.count !== 1 ? "s" : ""} (page {pageNum})
            </p>
            <div className="overflow-x-auto border border-green-800 rounded-lg">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-green-800 bg-green-950/20">
                    <th className="p-3 text-green-400 font-semibold">Bill #</th>
                    <th className="p-3 text-green-400 font-semibold">Jurisdiction</th>
                    <th className="p-3 text-green-400 font-semibold">Session</th>
                    <th className="p-3 text-green-400 font-semibold">Title</th>
                    <th className="p-3 text-green-400 font-semibold">Status</th>
                    <th className="p-3 text-green-400 font-semibold">Sponsor</th>
                    <th className="p-3 text-green-400 font-semibold">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {page.results.map((bill) => (
                    <tr
                      key={bill.id}
                      className="border-b border-green-900/50 hover:bg-green-950/10"
                    >
                      <td className="p-3 font-medium">{bill.bill_number}</td>
                      <td className="p-3">{bill.jurisdiction}</td>
                      <td className="p-3">{bill.session}</td>
                      <td className="p-3 max-w-md truncate" title={bill.title}>
                        {bill.title}
                      </td>
                      <td className="p-3 max-w-xs truncate" title={bill.status}>
                        {bill.status}
                      </td>
                      <td className="p-3">{bill.sponsor_name ?? "—"}</td>
                      <td className="p-3">
                        <Link
                          href={`/bills/${bill.id}`}
                          className="text-green-400 hover:text-green-300 underline"
                        >
                          View
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex gap-4 mt-4">
              {pageNum > 1 && (
                <button
                  type="button"
                  onClick={() => setPageNum((p) => p - 1)}
                  className="px-3 py-1 border border-green-700 text-green-400 rounded hover:bg-green-950/30"
                >
                  Previous
                </button>
              )}
              {page.results.length === 20 && page.count > pageNum * 20 && (
                <button
                  type="button"
                  onClick={() => setPageNum((p) => p + 1)}
                  className="px-3 py-1 border border-green-700 text-green-400 rounded hover:bg-green-950/30"
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
