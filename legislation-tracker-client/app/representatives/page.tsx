"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import SelectField, { type SelectOption } from "../components/SelectField";
import {
  getMyTracking,
  getBillFilterOptions,
  getRepresentatives,
  getSession,
  trackLegislator,
  type RepresentativeItem,
  untrackLegislator,
} from "@/lib/api";

const PAGE_SIZE = 20;

const US_STATES = [
  "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
  "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
  "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
  "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
  "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
];

const STATE_OPTIONS: SelectOption[] = [
  { value: "", label: "All" },
  ...US_STATES.map((state) => ({ value: state, label: state })),
];

const CHAMBER_OPTIONS: SelectOption[] = [
  { value: "", label: "All" },
  { value: "house", label: "House" },
  { value: "senate", label: "Senate" },
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
  const [hasAccount, setHasAccount] = useState(false);
  const [trackedLegislatorIds, setTrackedLegislatorIds] = useState<number[]>([]);
  const [trackingLegislatorId, setTrackingLegislatorId] = useState<number | null>(
    null,
  );
  const [trackingError, setTrackingError] = useState<string | null>(null);
  const [currentCongress, setCurrentCongress] = useState<number | null>(null);

  useEffect(() => {
    void getBillFilterOptions()
      .then((options) => setCurrentCongress(options.current_congress))
      .catch(() => undefined);
  }, []);

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

  useEffect(() => {
    let cancelled = false;
    void getSession()
      .then((session) => {
        if (cancelled) return;
        const signedIn = Boolean(session);
        setHasAccount(signedIn);
        if (!signedIn) return;
        void getMyTracking()
          .then((summary) => {
            if (!cancelled) {
              setTrackedLegislatorIds(
                summary.legislators.map((item) => item.representative.id),
              );
            }
          })
          .catch((e) => {
            if (!cancelled) {
              setTrackingError(
                e instanceof Error ? e.message : "Failed to load tracked legislators",
              );
            }
          });
      })
      .catch(() => {
        if (!cancelled) setHasAccount(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const hasNext =
    page &&
    page.results.length === PAGE_SIZE &&
    page.count > pageNum * PAGE_SIZE;

  async function toggleLegislatorTracking(representativeId: number) {
    const isTracked = trackedLegislatorIds.includes(representativeId);
    setTrackingLegislatorId(representativeId);
    setTrackingError(null);
    try {
      if (isTracked) {
        await untrackLegislator(representativeId);
        setTrackedLegislatorIds((ids) =>
          ids.filter((id) => id !== representativeId),
        );
      } else {
        await trackLegislator(representativeId);
        setTrackedLegislatorIds((ids) =>
          ids.includes(representativeId) ? ids : [...ids, representativeId],
        );
      }
    } catch (e) {
      setTrackingError(
        e instanceof Error ? e.message : "Failed to update tracked legislator",
      );
    } finally {
      setTrackingLegislatorId(null);
    }
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] w-full bg-background px-4 py-6 font-mono text-slate-900 dark:text-green-300 sm:px-6 lg:px-8">
      <div className="w-full">
        <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-green-400">
            Representatives
          </h1>
          <Link
            href="/"
            className="cursor-pointer text-blue-900 underline hover:text-blue-950 dark:text-green-500 dark:hover:text-green-400"
          >
            ← Dashboard
          </Link>
          <Link
            href="/representatives/compare"
            className="cursor-pointer text-blue-900 underline hover:text-blue-950 dark:text-green-500 dark:hover:text-green-400"
          >
            Compare two representatives
          </Link>
        </div>

        <div className="mb-4 rounded-lg border border-slate-400/70 bg-white/70 p-4 shadow-sm dark:border-green-900/60 dark:bg-green-950/10 dark:shadow-none">
          <div className="responsive-field-grid">
            <SelectField
              label="State"
              value={stateFilter}
              options={STATE_OPTIONS}
              onChange={(value) => {
                setPageNum(1);
                setStateFilter(value);
              }}
            />
            <SelectField
              label="Chamber"
              value={chamberFilter}
              options={CHAMBER_OPTIONS}
              onChange={(value) => {
                setPageNum(1);
                setChamberFilter(value);
              }}
            />
          </div>
        </div>

        {!hasAccount && (
          <p className="mb-4 text-sm text-slate-600 dark:text-green-500">
            <Link
              href="/login"
              className="text-blue-900 underline hover:text-blue-950 dark:text-green-500 dark:hover:text-green-400"
            >
              Log in
            </Link>{" "}
            to track legislators.
          </p>
        )}

        {trackingError && (
          <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
            {trackingError}
          </div>
        )}

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
            <div className="overflow-hidden rounded-lg border border-slate-400 dark:border-green-800">
              <table className="w-full table-fixed text-left">
                <thead>
                  <tr className="border-b border-slate-400 bg-slate-300/80 dark:border-green-800 dark:bg-green-950/20">
                    <th className="truncate p-3 font-semibold text-slate-900 dark:text-green-400">Name</th>
                    <th className="truncate p-3 font-semibold text-slate-900 dark:text-green-400">State</th>
                    <th className="truncate p-3 font-semibold text-slate-900 dark:text-green-400">Chamber</th>
                    <th className="truncate p-3 font-semibold text-slate-900 dark:text-green-400">Party</th>
                    <th className="truncate p-3 font-semibold text-slate-900 dark:text-green-400">District</th>
                    {hasAccount && (
                      <th className="truncate p-3 font-semibold text-slate-900 dark:text-green-400">Tracking</th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {page.results.map((rep) => (
                    <tr
                      key={rep.id}
                      className="border-b border-slate-300 hover:bg-white/60 dark:border-green-900/50 dark:hover:bg-green-950/10"
                    >
                      <td className="truncate p-3 font-medium">
                        <Link
                          href={currentCongress === null ? `/representatives/${rep.id}` : `/representatives/${rep.id}?congress=${currentCongress}`}
                          className="text-blue-900 underline hover:text-blue-950 dark:text-green-400 dark:hover:text-green-300"
                        >
                          {rep.name}
                        </Link>
                      </td>
                      <td className="truncate p-3">{rep.state}</td>
                      <td className="truncate p-3 capitalize">{rep.chamber}</td>
                      <td className="truncate p-3">{rep.party}</td>
                      <td className="truncate p-3">{rep.district ?? "—"}</td>
                      {hasAccount && (
                        <td className="p-3">
                          <button
                            type="button"
                            onClick={() => toggleLegislatorTracking(rep.id)}
                            disabled={trackingLegislatorId === rep.id}
                            className="cursor-pointer border border-slate-700 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50 dark:border-green-700 dark:text-green-300 dark:hover:bg-green-950/40"
                          >
                            {trackingLegislatorId === rep.id
                              ? "Saving..."
                              : trackedLegislatorIds.includes(rep.id)
                                ? "Tracked legislator"
                                : "Track legislator"}
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex flex-wrap gap-3">
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
