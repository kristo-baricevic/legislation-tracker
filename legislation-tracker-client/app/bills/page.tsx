"use client";

import React, { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import SelectField, { type SelectOption } from "../components/SelectField";
import {
  getBillFilterOptions,
  getBills,
  createSavedBillSearch,
  getSavedBillSearches,
  getSavedBillSearchResults,
  openSavedBillSearch,
  getMyTracking,
  getSession,
  getTopics,
  parseTopicIdFromSearchParam,
  trackTopic,
  type BillListItem,
  type BillsPage,
  type TopicItem,
  type SavedBillSearch,
  untrackTopic,
} from "@/lib/api";

const PAGE_SIZE = 20;
type BillSort = "recent_activity" | "relevance";

function parsePositiveIntegerFilter(value: string): number | undefined {
  const normalized = value.trim();
  if (!normalized || !/^\d+$/.test(normalized)) return undefined;
  const parsed = Number(normalized);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : undefined;
}

function sortFromParams(params: URLSearchParams): BillSort {
  if (!params.get("q")) return "recent_activity";
  return params.get("sort") === "recent_activity"
    ? "recent_activity"
    : "relevance";
}

function BillsTable() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [page, setPage] = useState<BillsPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [jurisdictions, setJurisdictions] = useState<string[]>([]);
  const [topics, setTopics] = useState<TopicItem[]>([]);
  const [filterMetaReady, setFilterMetaReady] = useState(false);
  const [filterMetaError, setFilterMetaError] = useState<string | null>(null);
  const [topicOptionsError, setTopicOptionsError] = useState<string | null>(null);

  const searchParamsKey = searchParams.toString();
  const [pageNum, setPageNum] = useState(
    () => parsePositiveIntegerFilter(searchParams.get("page") ?? "") ?? 1,
  );
  const [idFilter, setIdFilter] = useState(() => searchParams.get("id") ?? "");
  const [billNumberFilter, setBillNumberFilter] = useState(() => searchParams.get("bill_number") ?? "");
  const [sessionFilter, setSessionFilter] = useState<string | null>(() => searchParams.get("session"));
  const [jurisdictionFilter, setJurisdictionFilter] = useState(() => searchParams.get("jurisdiction") ?? "");
  const [statusFilter, setStatusFilter] = useState(() => searchParams.get("status") ?? "");
  const [sponsorFilter, setSponsorFilter] = useState(() => searchParams.get("sponsor") ?? "");
  const [queryInput, setQueryInput] = useState(() => searchParams.get("q") ?? "");
  const [queryFilter, setQueryFilter] = useState(() => searchParams.get("q") ?? "");
  const [sort, setSort] = useState<BillSort>(() => sortFromParams(searchParams));
  const rawTopicIdFromUrl = searchParams.get("topic_id");
  const topicIdFromUrl = parseTopicIdFromSearchParam(rawTopicIdFromUrl);
  const topicUrlError =
    rawTopicIdFromUrl !== null && topicIdFromUrl === undefined
      ? "topic_id must be a positive integer."
      : null;
  const [topicIdFilter, setTopicIdFilter] = useState<string>(() => {
    const topicId = parseTopicIdFromSearchParam(rawTopicIdFromUrl);
    return topicId ? String(topicId) : "";
  });
  const [topicFuzzyFilter, setTopicFuzzyFilter] = useState(
    () => searchParams.get("topic") ?? "",
  );
  const initialTopicIdRef = useRef(topicIdFromUrl);
  const [hasAccount, setHasAccount] = useState(false);
  const [trackedTopicIds, setTrackedTopicIds] = useState<number[]>([]);
  const [trackingTopicId, setTrackingTopicId] = useState<number | null>(null);
  const [trackingError, setTrackingError] = useState<string | null>(null);
  const [savedSearches, setSavedSearches] = useState<SavedBillSearch[]>([]);
  const [savedSearchError, setSavedSearchError] = useState<string | null>(null);
  const [pendingSavedAck, setPendingSavedAck] = useState<{
    searchId: number;
    watermark: string;
  } | null>(null);
  const currentCongressRef = useRef<number | null>(null);
  const queryInputRef = useRef(queryInput);
  const queryFilterRef = useRef(queryFilter);
  const suppressNextQueryDebounceRef = useRef(true);

  const loadFilterMeta = useCallback(async () => {
    setFilterMetaReady(false);
    setFilterMetaError(null);
    setLoading(true);
    try {
      const opts = await getBillFilterOptions();
      setJurisdictions(opts.jurisdictions ?? []);
      currentCongressRef.current = opts.current_congress;
      setSessionFilter((current) => current ?? (initialTopicIdRef.current ? "" : String(opts.current_congress)));
      setFilterMetaReady(true);
    } catch {
      setFilterMetaError("Could not load bill filter metadata.");
      setLoading(false);
    }
  }, []);

  const loadTopicOptions = useCallback(async () => {
    setTopicOptionsError(null);
    try {
      setTopics(await getTopics());
    } catch {
      setTopicOptionsError("Could not load topic choices.");
    }
  }, []);

  useEffect(() => {
    void loadFilterMeta();
    void loadTopicOptions();
  }, [loadFilterMeta, loadTopicOptions]);

  useEffect(() => {
    const params = new URLSearchParams(searchParamsKey);
    const nextQuery = params.get("q") ?? "";
    const nextTopicId = parseTopicIdFromSearchParam(params.get("topic_id"));
    setPageNum(parsePositiveIntegerFilter(params.get("page") ?? "") ?? 1);
    setIdFilter(params.get("id") ?? "");
    setBillNumberFilter(params.get("bill_number") ?? "");
    setSessionFilter(
      params.get("session") ??
        (nextTopicId ? "" : currentCongressRef.current ? String(currentCongressRef.current) : null),
    );
    setJurisdictionFilter(params.get("jurisdiction") ?? "");
    setStatusFilter(params.get("status") ?? "");
    setSponsorFilter(params.get("sponsor") ?? "");
    setTopicIdFilter(nextTopicId ? String(nextTopicId) : "");
    setTopicFuzzyFilter(params.get("topic") ?? "");
    if (nextQuery !== queryInputRef.current) {
      suppressNextQueryDebounceRef.current = true;
      queryInputRef.current = nextQuery;
      setQueryInput(nextQuery);
    }
    queryFilterRef.current = nextQuery;
    setQueryFilter(nextQuery);
    setSort(sortFromParams(params));
  }, [searchParamsKey]);

  useEffect(() => {
    if (suppressNextQueryDebounceRef.current) {
      suppressNextQueryDebounceRef.current = false;
      return;
    }
    const timeout = window.setTimeout(() => {
      const nextQuery = queryInput.trim();
      const hadQuery = Boolean(queryFilterRef.current);
      queryFilterRef.current = nextQuery;
      setQueryFilter(nextQuery);
      if (!hadQuery && nextQuery) setSort("relevance");
      setPageNum(1);
      if (!nextQuery) setSort("recent_activity");
    }, 300);
    return () => window.clearTimeout(timeout);
  }, [queryInput]);

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
              setTrackedTopicIds(summary.topics.map((item) => item.topic.id));
            }
          })
          .catch((e) => {
            if (!cancelled) {
              setTrackingError(
                e instanceof Error ? e.message : "Failed to load tracked topics",
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

  useEffect(() => {
    if (!hasAccount) return;
    let cancelled = false;
    getSavedBillSearches()
      .then((value) => { if (!cancelled) setSavedSearches(value.results); })
      .catch(() => { if (!cancelled) setSavedSearchError("Could not load saved searches."); });
    return () => { cancelled = true; };
  }, [hasAccount]);

  useEffect(() => {
    if (!pendingSavedAck) return;
    let cancelled = false;
    const { searchId, watermark } = pendingSavedAck;
    openSavedBillSearch(searchId, watermark)
      .then(() => getSavedBillSearches())
      .then((value) => {
        if (!cancelled) setSavedSearches(value.results);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setSavedSearchError(
            cause instanceof Error
              ? cause.message
              : "Could not acknowledge the displayed search results.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setPendingSavedAck(null);
      });
    return () => {
      cancelled = true;
    };
  }, [pendingSavedAck]);

  useEffect(() => {
    if (!filterMetaReady || sessionFilter === null) return;
    let cancelled = false;

    const sessionParsed = sessionFilter.trim()
      ? parsePositiveIntegerFilter(sessionFilter)
      : undefined;
    const idParsed = idFilter.trim()
      ? parsePositiveIntegerFilter(idFilter)
      : undefined;
    const validationError =
      topicUrlError ??
      (sessionFilter.trim() && sessionParsed === undefined
        ? "Session must be a positive integer."
        : null) ??
      (idFilter.trim() && idParsed === undefined
        ? "Bill ID must be a positive integer."
        : null);
    if (validationError) {
      setPage(null);
      setError(validationError);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    const topicIdParsed = topicIdFilter
      ? parsePositiveIntegerFilter(topicIdFilter)
      : undefined;

    getBills({
      page: pageNum,
      session: sessionParsed,
      id: idParsed,
      bill_number: billNumberFilter || undefined,
      jurisdiction: jurisdictionFilter || undefined,
      status: statusFilter || undefined,
      sponsor: sponsorFilter || undefined,
      topic: topicFuzzyFilter || undefined,
      topic_id: topicIdParsed,
      q: queryFilter || undefined,
      sort,
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
    filterMetaReady,
    topicUrlError,
    queryFilter,
    sort,
  ]);

  useEffect(() => {
    if (!filterMetaReady) return;
    const next = new URLSearchParams();
    if (pageNum > 1) next.set("page", String(pageNum));
    if (idFilter) next.set("id", idFilter);
    if (billNumberFilter) next.set("bill_number", billNumberFilter);
    if (sessionFilter) next.set("session", sessionFilter);
    if (jurisdictionFilter) next.set("jurisdiction", jurisdictionFilter);
    if (statusFilter) next.set("status", statusFilter);
    if (sponsorFilter) next.set("sponsor", sponsorFilter);
    if (topicIdFilter) next.set("topic_id", topicIdFilter);
    if (topicFuzzyFilter) next.set("topic", topicFuzzyFilter);
    if (queryFilter) next.set("q", queryFilter);
    if (queryFilter && sort === "recent_activity") next.set("sort", sort);
    const target = `/bills${next.size ? `?${next}` : ""}`;
    if (next.toString() !== searchParamsKey) {
      router.replace(target, { scroll: false });
    }
  }, [billNumberFilter, filterMetaReady, idFilter, jurisdictionFilter, pageNum, queryFilter, router, searchParamsKey, sessionFilter, sort, sponsorFilter, statusFilter, topicFuzzyFilter, topicIdFilter]);

  const resetPageAndSet = useCallback(
    (setter: React.Dispatch<React.SetStateAction<string>>) =>
      (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
        setPageNum(1);
        setter(e.target.value);
      },
    [],
  );

  const onTopicFuzzyChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setPageNum(1);
    setTopicFuzzyFilter(e.target.value);
    if (e.target.value.trim()) setTopicIdFilter("");
  };

  const hasNext =
    page &&
    page.results.length === PAGE_SIZE &&
    page.count > pageNum * PAGE_SIZE;
  const selectedTopicId = topicIdFilter ? parseInt(topicIdFilter, 10) : NaN;
  const selectedTopic = topics.find((topic) => topic.id === selectedTopicId);
  const selectedTopicIsTracked =
    !Number.isNaN(selectedTopicId) && trackedTopicIds.includes(selectedTopicId);
  const jurisdictionOptions: SelectOption[] = [
    { value: "", label: "All" },
    ...jurisdictions.map((jurisdiction) => ({
      value: jurisdiction,
      label: jurisdiction,
    })),
  ];
  const topicOptions: SelectOption[] = [
    { value: "", label: "All" },
    ...topics.map((topic) => ({
      value: String(topic.id),
      label: topic.name,
    })),
  ];

  async function toggleSelectedTopicTracking() {
    if (Number.isNaN(selectedTopicId)) return;
    setTrackingTopicId(selectedTopicId);
    setTrackingError(null);
    try {
      if (selectedTopicIsTracked) {
        await untrackTopic(selectedTopicId);
        setTrackedTopicIds((ids) => ids.filter((id) => id !== selectedTopicId));
      } else {
        await trackTopic(selectedTopicId);
        setTrackedTopicIds((ids) =>
          ids.includes(selectedTopicId) ? ids : [...ids, selectedTopicId],
        );
      }
    } catch (e) {
      setTrackingError(
        e instanceof Error ? e.message : "Failed to update tracked topic",
      );
    } finally {
      setTrackingTopicId(null);
    }
  }

  function currentSearchQuery(): Record<string, unknown> {
    const query: Record<string, unknown> = {};
    const session = parsePositiveIntegerFilter(sessionFilter ?? "");
    const id = parsePositiveIntegerFilter(idFilter);
    const topicId = parsePositiveIntegerFilter(topicIdFilter);
    if (session) query.session = session;
    if (id) query.id = id;
    if (billNumberFilter) query.bill_number = billNumberFilter;
    if (jurisdictionFilter) query.jurisdiction = jurisdictionFilter;
    if (statusFilter) query.status = statusFilter;
    if (sponsorFilter) query.sponsor = sponsorFilter;
    if (topicId) query.topic_id = topicId;
    if (topicFuzzyFilter) query.topic = topicFuzzyFilter;
    if (queryFilter) query.q = queryFilter;
    if (sort === "recent_activity" && queryFilter) query.sort = sort;
    return query;
  }

  async function saveCurrentSearch() {
    const name = window.prompt("Name this saved search");
    if (!name?.trim()) return;
    setSavedSearchError(null);
    try {
      const saved = await createSavedBillSearch(name, currentSearchQuery());
      setSavedSearches((items) => [saved, ...items]);
    } catch (cause) {
      setSavedSearchError(cause instanceof Error ? cause.message : "Could not save this search.");
    }
  }

  async function openSavedSearch(search: SavedBillSearch) {
    setSavedSearchError(null);
    try {
      const result = await getSavedBillSearchResults(search.id);
      const query = search.query_json;
      setSessionFilter(typeof query.session === "number" ? String(query.session) : "");
      setIdFilter(typeof query.id === "number" ? String(query.id) : "");
      setBillNumberFilter(typeof query.bill_number === "string" ? query.bill_number : "");
      setJurisdictionFilter(typeof query.jurisdiction === "string" ? query.jurisdiction : "");
      setStatusFilter(typeof query.status === "string" ? query.status : "");
      setSponsorFilter(typeof query.sponsor === "string" ? query.sponsor : "");
      setTopicIdFilter(typeof query.topic_id === "number" ? String(query.topic_id) : "");
      setTopicFuzzyFilter(typeof query.topic === "string" ? query.topic : "");
      const nextQuery = typeof query.q === "string" ? query.q : "";
      if (nextQuery !== queryInputRef.current) {
        suppressNextQueryDebounceRef.current = true;
        queryInputRef.current = nextQuery;
        setQueryInput(nextQuery);
      }
      queryFilterRef.current = nextQuery;
      setQueryFilter(nextQuery);
      setSort(
        nextQuery
          ? query.sort === "recent_activity"
            ? "recent_activity"
            : "relevance"
          : "recent_activity",
      );
      setPage({ count: result.count, next: null, previous: null, results: result.results });
      setPageNum(1);
      setPendingSavedAck({ searchId: search.id, watermark: result.result_watermark });
    } catch (cause) {
      setSavedSearchError(cause instanceof Error ? cause.message : "Could not open saved search.");
    }
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] w-full bg-background px-4 py-6 font-mono text-slate-900 dark:text-green-300 sm:px-6 lg:px-8">
      <div className="w-full">
        <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
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
            Search and filters apply automatically. Topic: use <strong>dropdown</strong> for
            an exact tag, or <strong>topic contains</strong> for a fuzzy match
            (not both).
          </p>
          <div className="responsive-field-grid">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-slate-600 dark:text-green-500">Full-text search</span>
              <input type="search" value={queryInput} onChange={(event) => { setPageNum(1); queryInputRef.current = event.target.value; setQueryInput(event.target.value); }} placeholder="Words in title, summary, analysis, or text" className="rounded border border-slate-400 bg-white px-2 py-1 text-slate-900 dark:border-green-700 dark:bg-black dark:text-green-300" />
            </label>
            <SelectField label="Sort" value={sort} options={[{ value: "recent_activity", label: "Recent activity" }, { value: "relevance", label: "Relevance" }]} onChange={(value) => { setPageNum(1); setSort(value === "relevance" && queryInput.trim() ? "relevance" : "recent_activity"); }} />
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
                value={sessionFilter ?? ""}
                onChange={(event) => {
                  setPageNum(1);
                  setSessionFilter(event.target.value);
                }}
                placeholder="Current Congress"
                className="rounded border border-slate-400 bg-white px-2 py-1 text-slate-900 dark:border-green-700 dark:bg-black dark:text-green-300"
              />
            </label>
            <SelectField
              label="Jurisdiction"
              value={jurisdictionFilter}
              options={jurisdictionOptions}
              onChange={(value) => {
                setPageNum(1);
                setJurisdictionFilter(value);
              }}
            />
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
            <SelectField
              label="Topic (exact)"
              value={topicIdFilter}
              options={topicOptions}
              onChange={(value) => {
                setPageNum(1);
                setTopicIdFilter(value);
                if (value) setTopicFuzzyFilter("");
              }}
            />
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
          <div className="mt-4 border-t border-slate-300 pt-3 text-sm dark:border-green-900/70">
            {hasAccount ? (
              selectedTopic ? (
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-slate-600 dark:text-green-500">
                    {selectedTopic.name}
                  </span>
                  <button
                    type="button"
                    onClick={toggleSelectedTopicTracking}
                    disabled={trackingTopicId === selectedTopic.id}
                    className="cursor-pointer border border-slate-800 px-3 py-1.5 font-semibold text-slate-950 hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50 dark:border-green-700 dark:text-green-300 dark:hover:bg-green-950/40"
                  >
                    {trackingTopicId === selectedTopic.id
                      ? "Saving..."
                      : selectedTopicIsTracked
                        ? "Tracked topic"
                        : "Track topic"}
                  </button>
                </div>
              ) : (
                <p className="text-slate-600 dark:text-green-500">
                  Select an exact topic to track it.
                </p>
              )
            ) : (
              <Link
                href="/login"
                className="text-blue-900 underline hover:text-blue-950 dark:text-green-500 dark:hover:text-green-400"
              >
                Log in to track topics
              </Link>
            )}
            {trackingError && (
              <p className="mt-2 text-red-700 dark:text-red-300">{trackingError}</p>
            )}
          </div>
          {hasAccount && (
            <div className="mt-4 border-t border-slate-300 pt-3 text-sm dark:border-green-900/70">
              <div className="flex flex-wrap items-center gap-3">
                <button type="button" onClick={() => void saveCurrentSearch()} className="cursor-pointer border border-slate-800 px-3 py-1.5 font-semibold text-slate-950 hover:bg-slate-200 dark:border-green-700 dark:text-green-300 dark:hover:bg-green-950/40">Save this search</button>
                {savedSearches.length > 0 && <span className="text-slate-600 dark:text-green-500">Saved searches:</span>}
                {savedSearches.map((search) => <button key={search.id} type="button" onClick={() => void openSavedSearch(search)} className="cursor-pointer text-blue-900 underline dark:text-green-400">{search.name}{search.new_result_count ? ` (${search.new_result_count} new)` : ""}</button>)}
              </div>
              {savedSearchError && <p role="alert" className="mt-2 text-red-700 dark:text-red-300">{savedSearchError}</p>}
            </div>
          )}
        </div>

        {filterMetaError && (
          <div
            role="alert"
            className="mb-4 flex flex-wrap items-center gap-3 rounded border border-red-200 bg-red-50 p-3 text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300"
          >
            <span>{filterMetaError}</span>
            <button
              type="button"
              onClick={() => void loadFilterMeta()}
              className="cursor-pointer border border-current px-2 py-1 font-semibold"
            >
              Retry bill metadata
            </button>
          </div>
        )}

        {topicOptionsError && (
          <div
            role="alert"
            className="mb-4 flex flex-wrap items-center gap-3 rounded border border-amber-300 bg-amber-50 p-3 text-amber-900 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-200"
          >
            <span>{topicOptionsError}</span>
            <button
              type="button"
              onClick={() => void loadTopicOptions()}
              className="cursor-pointer border border-current px-2 py-1 font-semibold"
            >
              Retry topic choices
            </button>
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
              {page.count} bill{page.count !== 1 ? "s" : ""} (page {pageNum})
            </p>
            <div className="overflow-hidden rounded-lg border border-slate-400 dark:border-green-800">
              <table className="w-full table-fixed text-left">
                <thead>
                  <tr className="border-b border-slate-400 bg-slate-300/80 dark:border-green-800 dark:bg-green-950/20">
                    <th className="truncate p-3 font-semibold text-slate-900 dark:text-green-400">ID</th>
                    <th className="truncate p-3 font-semibold text-slate-900 dark:text-green-400">Bill #</th>
                    <th className="truncate p-3 font-semibold text-slate-900 dark:text-green-400">
                      Jurisdiction
                    </th>
                    <th className="truncate p-3 font-semibold text-slate-900 dark:text-green-400">Session</th>
                    <th className="truncate p-3 font-semibold text-slate-900 dark:text-green-400">Title</th>
                    <th className="truncate p-3 font-semibold text-slate-900 dark:text-green-400">Status</th>
                    <th className="truncate p-3 font-semibold text-slate-900 dark:text-green-400">Sponsor</th>
                    <th className="truncate p-3 font-semibold text-slate-900 dark:text-green-400">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {page.results.map((bill: BillListItem) => (
                    <tr
                      key={bill.id}
                      className="border-b border-slate-300 hover:bg-white/60 dark:border-green-900/50 dark:hover:bg-green-950/10"
                    >
                      <td className="truncate p-3 text-slate-600 dark:text-green-500">{bill.id}</td>
                      <td className="truncate p-3 font-medium">{bill.bill_number}</td>
                      <td className="truncate p-3">{bill.jurisdiction}</td>
                      <td className="truncate p-3">{bill.session}</td>
                      <td className="truncate p-3" title={bill.title}>
                        {bill.title}
                        {bill.highlights?.[0] && <p className="mt-1 text-xs text-slate-600 dark:text-green-600">{bill.highlights[0].segments.map((segment, index) => <span key={index} className={segment.matched ? "font-bold text-slate-900 dark:text-green-300" : ""}>{segment.text}</span>)}</p>}
                      </td>
                      <td className="truncate p-3" title={bill.status}>
                        {bill.status}
                      </td>
                      <td className="truncate p-3" title={bill.sponsor_name ?? undefined}>
                        {bill.sponsor_name ?? "—"}
                      </td>
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

export default function BillsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[60vh] items-center justify-center font-mono text-slate-600 dark:text-green-500">
          Loading bills…
        </div>
      }
    >
      <BillsTable />
    </Suspense>
  );
}
