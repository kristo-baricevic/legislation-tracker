"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import SelectField, { type SelectOption } from "../components/SelectField";
import RepresentativeResearch from "../components/RepresentativeResearch";
import RepresentativeAvatar from "./representative-avatar";
import {
  getMyTracking,
  getBillFilterOptions,
  getRepresentatives,
  getSession,
  trackLegislator,
  type RepresentativeItem,
  untrackLegislator,
} from "@/lib/api";

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
  const [view, setView] = useState<"avatars" | "table">("avatars");
  const [page, setPage] = useState<{
    count: number;
    next: string | null;
    results: RepresentativeItem[];
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stateFilter, setStateFilter] = useState<string>("");
  const [name, setName] = useState("");
  const [search, setSearch] = useState("");
  useEffect(() => {
    if (search === name.trim()) return;
    const timer = setTimeout(() => { resetResults(); setSearch(name.trim()); }, 250);
    return () => clearTimeout(timer);
  }, [name, search]);
  const [chamberFilter, setChamberFilter] = useState<string>("");
  const [partyFilter, setPartyFilter] = useState("");
  const [pageNum, setPageNum] = useState(1);
  const [retry, setRetry] = useState(0);
  const sentinel = useRef<HTMLDivElement>(null);
  const inFlight = useRef(true);
  function resetResults() {
    inFlight.current = true;
    setPage(null);
    setPageNum(1);
    setError(null);
    setLoading(true);
  }
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
    inFlight.current = true;
    setLoading(true);
    setError(null);
    getRepresentatives({
      search: search || undefined,
      state: stateFilter || undefined,
      chamber: chamberFilter || undefined,
      party: partyFilter || undefined,
      page: pageNum,
    })
      .then((data) => {
        if (!cancelled) setPage(previous => {
          if (pageNum === 1 || !previous) return data;
          const ids = new Set(previous.results.map(rep => rep.id));
          return { ...data, results: [...previous.results, ...data.results.filter(rep => !ids.has(rep.id))] };
        });
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load representatives");
      })
      .finally(() => {
        if (!cancelled) { inFlight.current = false; setLoading(false); }
      });
    return () => {
      cancelled = true;
    };
  }, [search, stateFilter, chamberFilter, partyFilter, pageNum, retry]);

  useEffect(() => {
    if (!sentinel.current || !page?.next || loading || error || name.trim() !== search) return;
    let active = true;
    const observer = new IntersectionObserver(entries => {
      if (active && entries.some(entry => entry.isIntersecting) && !inFlight.current) {
        inFlight.current = true;
        setPageNum(number => number + 1);
      }
    }, { rootMargin: "300px" });
    observer.observe(sentinel.current);
    return () => { active = false; observer.disconnect(); };
  }, [page, loading, error, name, search, view]);

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
          <button type="button" onClick={() => setView(current => current === "avatars" ? "table" : "avatars")}
            className="shrink-0 cursor-pointer rounded-full border border-control px-4 py-2 text-sm font-semibold text-ink hover:bg-wash">
            {view === "avatars" ? "Table view" : "Avatar view"}
          </button>
        </div>

        <div className="mb-4 tracker-panel">
          <div className="grid grid-cols-1 items-end gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="block min-w-0 text-sm text-muted">
              <span className="mb-1 block">Search by name</span>
              <input type="search" value={name} maxLength={200} placeholder="Name"
                className="h-10 w-full rounded border border-control bg-paper px-2 py-1 text-base text-ink"
                onChange={event => setName(event.target.value)} />
            </label>
            <SelectField
              label="State"
              value={stateFilter}
              options={STATE_OPTIONS}
              onChange={(value) => {
                if (value === stateFilter) return;
                resetResults();
                setStateFilter(value);
              }}
            />
            <SelectField
              label="Chamber"
              value={chamberFilter}
              options={CHAMBER_OPTIONS}
              onChange={(value) => {
                if (value === chamberFilter) return;
                resetResults();
                setChamberFilter(value);
              }}
            />
            <SelectField label="Party" value={partyFilter}
              options={[{ value: "", label: "All" }, { value: "D", label: "Democrat" }, { value: "R", label: "Republican" }, { value: "I", label: "Independent" }]}
              onChange={value => { if (value !== partyFilter) { resetResults(); setPartyFilter(value); } }} />
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

        {error && !page && (
          <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
            {error}
            <button type="button" className="ml-3 underline" onClick={() => setRetry(value => value + 1)}>Retry loading representatives</button>
          </div>
        )}

        {loading && !page && <p role="status" className="text-muted">Loading…</p>}

        {page && (
          <>
            <p className="mb-4 text-muted">
              {page.count ? <>{page.count} representative{page.count !== 1 ? "s" : ""}</> : "No representatives found."}
            </p>
            {view === "avatars" ? <ul aria-label="Representatives" className="grid grid-cols-2 gap-x-3 gap-y-6 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
              {page.results.map(rep => <RepresentativeAvatar key={rep.id} rep={rep} congress={currentCongress}>
                {hasAccount && <button type="button" aria-pressed={trackedLegislatorIds.includes(rep.id)} aria-label={`${trackedLegislatorIds.includes(rep.id) ? "Untrack" : "Track"} ${rep.name}`}
                  onClick={() => toggleLegislatorTracking(rep.id)} disabled={trackingLegislatorId !== null}
                  className={`mt-auto cursor-pointer rounded-full border px-3 py-1 text-xs font-semibold disabled:opacity-50 ${trackedLegislatorIds.includes(rep.id) ? "border-ink bg-ink text-background" : "border-control text-ink hover:bg-wash"}`}>
                  {trackingLegislatorId === rep.id ? "Saving…" : trackedLegislatorIds.includes(rep.id) ? "✓ Tracked" : "+ Track"}
                </button>}
              </RepresentativeAvatar>)}
            </ul> : <div className="tracker-table" role="region" aria-label="Representative results" tabIndex={0}>
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
                        <Link href={`/representatives/${rep.id}${currentCongress ? `?congress=${currentCongress}` : ""}`}>{rep.name}</Link>
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
                            disabled={trackingLegislatorId !== null}
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
            </div>}
            <div ref={sentinel} className="mt-6 min-h-10 text-center text-sm text-muted">
              {loading && <p role="status">Loading more representatives…</p>}
              {error && <div role="alert"><p>{error}</p><button type="button" className="mt-2 cursor-pointer underline" onClick={() => setRetry(value => value + 1)}>Retry loading representatives</button></div>}
              {!loading && !error && !page.next && page.results.length > 0 && <p>All {page.count} representatives shown</p>}
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
