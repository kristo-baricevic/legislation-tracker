"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import RequireAuth from "@/app/components/RequireAuth";
import { getRepresentatives, type RepresentativeItem } from "@/lib/api";

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

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getRepresentatives({
      state: stateFilter || undefined,
      chamber: chamberFilter || undefined,
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
  }, [stateFilter, chamberFilter]);

  return (
    <div className="min-h-screen bg-black text-green-300 font-mono p-6">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-semibold text-green-400">Representatives</h1>
          <Link href="/" className="text-green-500 hover:text-green-400 underline">
            ← Dashboard
          </Link>
        </div>

        <div className="flex gap-4 mb-4 flex-wrap items-center">
          <label className="flex items-center gap-2">
            <span className="text-green-500">State:</span>
            <select
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
              className="bg-black border border-green-700 text-green-300 px-2 py-1 rounded"
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
            <span className="text-green-500">Chamber:</span>
            <select
              value={chamberFilter}
              onChange={(e) => setChamberFilter(e.target.value)}
              className="bg-black border border-green-700 text-green-300 px-2 py-1 rounded"
            >
              <option value="">All</option>
              <option value="house">House</option>
              <option value="senate">Senate</option>
            </select>
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
              {page.count} representative{page.count !== 1 ? "s" : ""} (ingested from bills/votes)
            </p>
            <div className="overflow-x-auto border border-green-800 rounded-lg">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-green-800 bg-green-950/20">
                    <th className="p-3 text-green-400 font-semibold">Name</th>
                    <th className="p-3 text-green-400 font-semibold">State</th>
                    <th className="p-3 text-green-400 font-semibold">Chamber</th>
                    <th className="p-3 text-green-400 font-semibold">Party</th>
                    <th className="p-3 text-green-400 font-semibold">District</th>
                  </tr>
                </thead>
                <tbody>
                  {page.results.map((rep) => (
                    <tr
                      key={rep.id}
                      className="border-b border-green-900/50 hover:bg-green-950/10"
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
          </>
        )}
      </div>
    </div>
  );
}

export default function RepresentativesPage() {
  return (
    <RequireAuth>
      <RepresentativesTable />
    </RequireAuth>
  );
}
