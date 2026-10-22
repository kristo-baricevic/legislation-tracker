"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import SelectField, { type SelectOption } from "../components/SelectField";
import LegislatorName from "../components/LegislatorName";
import RepresentativeResearch from "../components/RepresentativeResearch";
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
  const [name, setName] = useState("");
  const [search, setSearch] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => { setSearch(name.trim()); setPageNum(1); }, 250);
    return () => clearTimeout(timer);
  }, [name]);
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
      search: search || undefined,
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
  }, [search, stateFilter, chamberFilter, pageNum]);

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
    <div className="tracker-page min-h-[calc(100vh-4rem)] font-sans">
      <div className="w-full">
        <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h1 className="tracker-heading text-ink">
            Representatives
          </h1>
          <Link
            href="/"
            className="cursor-pointer text-ink underline hover:text-ink"
          >
            ← Dashboard
          </Link>
          <Link
            href="/representatives/compare"
            className="cursor-pointer text-ink underline hover:text-ink"
          >
            Compare two representatives
          </Link>
        </div>

        <div className="mb-4 tracker-panel">
          <div className="responsive-field-grid">
            <label className="flex flex-col gap-2 text-sm font-medium">
              Search by name
              <input type="search" value={name} maxLength={200} placeholder="Name"
                className="rounded border border-control bg-background px-3 py-2 text-ink"
                onChange={event => setName(event.target.value)} />
            </label>
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
          <p className="mb-4 text-sm text-muted">
            <Link
              href="/login"
              className="text-ink underline hover:text-ink"
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

        {loading && <p className="text-muted">Loading…</p>}

        {!loading && page && (
          <>
            <p className="mb-4 text-muted">
              {page.count ? <>{page.count} representative{page.count !== 1 ? "s" : ""}</> : "No representatives found."}
            </p>
            <div className="tracker-table" role="region" aria-label="Representative results" tabIndex={0}>
              <table className="w-full table-fixed text-left">
                <thead>
                  <tr className="border-b border-line bg-wash">
                    <th className="truncate p-3 font-semibold text-ink">Name</th>
                    <th className="truncate p-3 font-semibold text-ink">State</th>
                    <th className="truncate p-3 font-semibold text-ink">Chamber</th>
                    <th className="truncate p-3 font-semibold text-ink">Party</th>
                    <th className="truncate p-3 font-semibold text-ink">District</th>
                    <th className="p-3 font-semibold text-ink">Research</th>
                    {hasAccount && (
                      <th className="truncate p-3 font-semibold text-ink">Tracking</th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {page.results.map((rep) => (
                    <tr
                      key={rep.id}
                      className="border-b border-line hover:bg-wash"
                    >
                      <td className="truncate p-3 font-medium">
                        {currentCongress === null ? <Link href={`/representatives/${rep.id}`}>{rep.name}</Link> : <LegislatorName id={rep.id} name={rep.name} congress={currentCongress} />}
                      </td>
                      <td className="truncate p-3">{rep.state}</td>
                      <td className="truncate p-3 capitalize">{rep.chamber}</td>
                      <td className="truncate p-3">{rep.party}</td>
                      <td className="p-3">{rep.district ?? "—"}</td>
                      <td className="p-3"><RepresentativeResearch representativeId={rep.id} compact /></td>
                      {hasAccount && (
                        <td className="p-3">
                          <button
                            type="button"
                            onClick={() => toggleLegislatorTracking(rep.id)}
                            disabled={trackingLegislatorId === rep.id}
                            className="cursor-pointer border border-control px-3 py-1.5 text-sm font-semibold text-ink hover:bg-wash disabled:cursor-not-allowed disabled:opacity-50"
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
                  className="cursor-pointer rounded border border-control px-3 py-1 text-ink hover:bg-wash"
                >
                  Previous
                </button>
              )}
              {hasNext && (
                <button
                  type="button"
                  onClick={() => setPageNum((p) => p + 1)}
                  className="cursor-pointer rounded border border-control px-3 py-1 text-ink hover:bg-wash"
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
