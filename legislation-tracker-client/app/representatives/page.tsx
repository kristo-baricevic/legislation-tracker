"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import SelectField, { type SelectOption } from "../components/SelectField";
import LoadingSpinner from "../components/LoadingSpinner";
import RepresentativeAvatar from "./representative-avatar";
import { capturePersonalizedScope, subscribePersonalizedChanges } from "@/lib/personalized-scope";
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

function RepresentativesDirectory() {
  const [trackingFilter, setTrackingFilter] = useState<"" | "tracked" | "untracked">("");
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
  const refreshLoadedPages = useRef(false);
  const sentinel = useRef<HTMLDivElement>(null);
  const inFlight = useRef(true);
  function resetResults() {
    refreshLoadedPages.current = false;
    inFlight.current = true;
    setPageNum(1);
    setError(null);
    setLoading(true);
  }
  const [hasAccount, setHasAccount] = useState<boolean | null>(null);
  const [trackingRetry, setTrackingRetry] = useState(0);
  const [trackedLegislatorIds, setTrackedLegislatorIds] = useState<number[]>([]);
  const trackingRequests = useRef(new Set<number>());
  const [trackingLegislatorIds, setTrackingLegislatorIds] = useState<Set<number>>(new Set());
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
    const refresh = refreshLoadedPages.current;
    const loadPage = (number: number) => getRepresentatives({
      search: search || undefined,
      state: stateFilter || undefined,
      chamber: chamberFilter || undefined,
      party: partyFilter || undefined,
      tracking: trackingFilter || undefined,
      page: number,
    });
    async function load() {
      if (!refresh) return loadPage(pageNum);
      let data = await loadPage(1);
      const results = [...data.results];
      let number = 1;
      while (!cancelled && number < pageNum && data.next) {
        data = await loadPage(++number);
        results.push(...data.results);
      }
      return { ...data, results };
    }
    load()
      .then((data) => {
        if (!cancelled) setPage(previous => {
          if (refresh || pageNum === 1 || !previous) return data;
          const ids = new Set(previous.results.map(rep => rep.id));
          return { ...data, results: [...previous.results, ...data.results.filter(rep => !ids.has(rep.id))] };
        });
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load representatives");
      })
      .finally(() => {
        if (!cancelled) { refreshLoadedPages.current = false; inFlight.current = false; setLoading(false); }
      });
    return () => {
      cancelled = true;
    };
  }, [search, stateFilter, chamberFilter, partyFilter, trackingFilter, pageNum, retry]);

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
  }, [page, loading, error, name, search, hasAccount]);

  useEffect(() => {
    let cancelled = false;
    async function loadTracking() {
      try {
        const session = await getSession();
        if (cancelled) return;
        if (session) {
          const summary = await getMyTracking();
          if (cancelled) return;
          setTrackedLegislatorIds(summary.legislators.map(item => item.representative.id));
        }
        setHasAccount(Boolean(session));
      } catch (e) {
        if (!cancelled) setTrackingError(e instanceof Error ? e.message : "Failed to load tracked legislators");
      }
    }
    void loadTracking();
    return () => {
      cancelled = true;
    };
  }, [trackingRetry]);

  async function toggleLegislatorTracking(representativeId: number) {
    if (trackingRequests.current.has(representativeId)) return;
    trackingRequests.current.add(representativeId);
    const isTracked = trackedLegislatorIds.includes(representativeId);
    setTrackingLegislatorIds(new Set(trackingRequests.current));
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
      if (trackingFilter) {
        refreshLoadedPages.current = true;
        setRetry(value => value + 1);
      }
    } catch (e) {
      setTrackingError(
        e instanceof Error ? e.message : "Failed to update tracked legislator",
      );
    } finally {
      trackingRequests.current.delete(representativeId);
      setTrackingLegislatorIds(new Set(trackingRequests.current));
    }
  }

  return (
    <div className="tracker-page min-h-[calc(100vh-4rem)] font-sans">
      <div className="w-full">
        <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h1 className="tracker-heading text-ink">
            Representatives
          </h1>
        </div>

        <div className="mb-4 tracker-panel">
          <div className="grid grid-cols-1 items-end gap-3 sm:grid-cols-2 lg:grid-cols-5">
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
            <SelectField label="Tracking" value={trackingFilter} disabled={hasAccount !== true}
              options={[{ value: "", label: "All" }, { value: "tracked", label: "Tracked" }, { value: "untracked", label: "Untracked" }]}
              onChange={value => { if (value !== trackingFilter) { resetResults(); setTrackingFilter(value as typeof trackingFilter); } }} />
          </div>
        </div>

        <p className="mb-4 min-h-5 text-sm text-muted">
          {hasAccount === false && <>
            <Link
              href="/login"
              className="text-ink underline hover:text-ink"
            >
              Log in
            </Link>{" "}
            to track legislators.
          </>}
        </p>

        {trackingError && (
          <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
            {trackingError}
            {hasAccount === null && <button type="button" className="ml-3 underline" onClick={() => {
              setTrackingError(null);
              setTrackingRetry(value => value + 1);
            }}>Retry loading tracking</button>}
          </div>
        )}

        {error && !page && (
          <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
            {error}
            <button type="button" className="ml-3 underline" onClick={() => setRetry(value => value + 1)}>Retry loading representatives</button>
          </div>
        )}

        <div className="min-h-12">
          <LoadingSpinner centered active={!error && ((!page && loading) || (hasAccount === null && !trackingError))} label="Loading representatives…" />
        </div>

        {page && hasAccount !== null && (
          <>
            <p className="mb-4 text-muted">
              {page.count ? <>{page.count} representative{page.count !== 1 ? "s" : ""}</> : "No representatives found."}
            </p>
            <ul aria-label="Representatives" aria-busy={loading} className="grid grid-cols-2 gap-x-3 gap-y-6 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
              {page.results.map(rep => <RepresentativeAvatar key={rep.id} rep={rep} congress={currentCongress}>
                {hasAccount && <button type="button" aria-pressed={trackedLegislatorIds.includes(rep.id)} aria-label={`${trackedLegislatorIds.includes(rep.id) ? "Untrack" : "Track"} ${rep.name}`}
                  onClick={() => toggleLegislatorTracking(rep.id)} aria-disabled={trackingLegislatorIds.has(rep.id)} aria-busy={trackingLegislatorIds.has(rep.id)}
                  className={`mt-auto cursor-pointer rounded-full border px-3 py-1 text-xs font-semibold disabled:opacity-50 ${trackedLegislatorIds.includes(rep.id) ? "border-ink bg-ink text-background" : "border-control text-ink hover:bg-wash"}`}>
                  {trackedLegislatorIds.includes(rep.id) ? "✓ Tracked" : "+ Track"}
                </button>}
              </RepresentativeAvatar>)}
            </ul>
            <div ref={sentinel} className="mt-6 min-h-10 text-center text-sm text-muted">
              <LoadingSpinner active={loading && pageNum > 1 && !refreshLoadedPages.current} label="Loading more representatives…" />
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
  const [session, setSession] = useState(() => capturePersonalizedScope().sessionGeneration);
  useEffect(() => subscribePersonalizedChanges(change => {
    if (change.kind === "session") setSession(change.scope.sessionGeneration);
  }), []);
  // Never retain a previous account's private filter results or pending writes.
  // Ordinary tracking changes intentionally preserve all existing card nodes.
  return <RepresentativesDirectory key={session} />;
}
