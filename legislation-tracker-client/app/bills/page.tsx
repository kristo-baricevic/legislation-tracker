"use client";
import { Dropdown, SearchInput } from "@/app/components/FilterControls";
import LoadingSpinner from "@/app/components/LoadingSpinner";
import BillCard from "../components/BillCard";
import DashboardBillReader from "../components/DashboardBillReader";
import styles from "../components/bill-deck.module.css";
import { STAGES } from "@/lib/bill-stage";

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
  trackBill,
  untrackBill,
  capturePersonalizedScope,
  isPersonalizedScopeCurrent,
  subscribePersonalizedChanges,
  type BillsPage,
  type TopicItem,
  type SavedBillSearch,
  untrackTopic,
} from "@/lib/api";

const PAGE_SIZE = 20;
const STATUS_OPTIONS = [
  ...STAGES.map(stage => ({ value: `stage:${stage.key}`, label: stage.name })),
  { value: "stage:other", label: "Other / unclassified" },
];
type BillSort = "recent_activity" | "oldest_activity" | "relevance" | "unsorted";

function parsePositiveIntegerFilter(value: string): number | undefined {
  const normalized = value.trim();
  if (!normalized || !/^\d+$/.test(normalized)) return undefined;
  const parsed = Number(normalized);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : undefined;
}

function parseSort(value: unknown): BillSort | null {
  if (value === "oldest_activity" || value === "recent_activity" || value === "relevance" || value === "unsorted") return value;
  return null;
}

function BillsCatalog() {
  const [layout, setLayout] = useState<"grid" | "list">("grid");
  const searchParams = useSearchParams();
  const router = useRouter();
  const [page, setPage] = useState<BillsPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [shownPage, setShownPage] = useState(() => parsePositiveIntegerFilter(searchParams.get("page") ?? "") ?? 1);
  const [error, setError] = useState<string | null>(null);
  const endOfResults = useRef<HTMLDivElement>(null);
  const [firstShownPage, setFirstShownPage] = useState(1);
  const committedResults = useRef({key: "", filters: "", page: 0, start: 1, revision: 0});
  const [retryResults, setRetryResults] = useState(0);

  const [jurisdictions, setJurisdictions] = useState<string[]>([]);
  const [topics, setTopics] = useState<TopicItem[] | null>(null);
  const [catalogVisible, setCatalogVisible] = useState(false);
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
  const [trackingFilter, setTrackingFilter] = useState(() => searchParams.get("tracking") ?? "");
  const [resultsRevision, setResultsRevision] = useState(0);
  const [sponsorFilter, setSponsorFilter] = useState(() => searchParams.get("sponsor") ?? "");
  const [queryInput, setQueryInput] = useState(() => searchParams.get("q") ?? "");
  const [queryFilter, setQueryFilter] = useState(() => searchParams.get("q") ?? "");
  const [selectedSort, setSelectedSort] = useState(() => parseSort(searchParams.get("sort")));
  const sort = selectedSort ?? (queryFilter.trim() ? "relevance" : "unsorted");
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
  const [hasAccount, setHasAccount] = useState<boolean | null>(null);
  const filterAccount = trackingFilter ? hasAccount : true;
  const [trackedTopicIds, setTrackedTopicIds] = useState<number[]>([]);
  const [trackedBillIds, setTrackedBillIds] = useState<number[]>([]);
  const [pendingBills, setPendingBills] = useState<Set<number>>(new Set());
  const [trackingReady, setTrackingReady] = useState(false);
  const [trackingRefresh, setTrackingRefresh] = useState(0);
  const [trackingTopicId, setTrackingTopicId] = useState<number | null>(null);
  const [trackingError, setTrackingError] = useState<string | null>(null);
  const [savedSearches, setSavedSearches] = useState<SavedBillSearch[] | null>(null);
  const [savedSearchError, setSavedSearchError] = useState<string | null>(null);
  const [isSaveSearchFormOpen, setIsSaveSearchFormOpen] = useState(false);
  const [savedSearchName, setSavedSearchName] = useState("");
  const [pendingSavedAck, setPendingSavedAck] = useState<{
    searchId: number;
    watermark: string;
  } | null>(null);
  useEffect(() => subscribePersonalizedChanges(change => {
    if (change.kind === "session") {
      setCatalogVisible(false);
      setSavedSearches(null);
      setSavedSearchError(null);
      setHasAccount(null);
      setTrackingReady(false);
      setTrackedBillIds([]);
      setTrackedTopicIds([]);
      setPendingBills(new Set());
    }
    if (change.kind === "session" && trackingFilter) {
      setPage(null);
      setPageNum(1);
      setError(null);
      setResultsRevision(value => value + 1);
    }
    if (change.kind === "tracking" && trackingFilter) setResultsRevision(value => value + 1);
    setTrackingRefresh(value => value + 1);
  }), [trackingFilter]);
  const currentCongressRef = useRef<number | null>(null);
  const queryInputRef = useRef(queryInput);
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
    setTrackingFilter(params.get("tracking") ?? "");
    setSponsorFilter(params.get("sponsor") ?? "");
    setTopicIdFilter(nextTopicId ? String(nextTopicId) : "");
    setTopicFuzzyFilter(params.get("topic") ?? "");
    if (nextQuery !== queryInputRef.current) {
      suppressNextQueryDebounceRef.current = true;
      queryInputRef.current = nextQuery;
      setQueryInput(nextQuery);
    }
    setQueryFilter(nextQuery);
    setSelectedSort(parseSort(params.get("sort")));
  }, [searchParamsKey]);

  useEffect(() => {
    if (suppressNextQueryDebounceRef.current) {
      suppressNextQueryDebounceRef.current = false;
      return;
    }
    const timeout = window.setTimeout(() => {
      const nextQuery = queryInput.trim();
      setQueryFilter(nextQuery);
      setPageNum(1);
    }, 300);
    return () => window.clearTimeout(timeout);
  }, [queryInput]);

  useEffect(() => {
    let cancelled = false;
    const scope = capturePersonalizedScope();
    setTrackingError(null);
    void getSession()
      .then((session) => {
        if (cancelled || !isPersonalizedScopeCurrent(scope)) return;
        const signedIn = Boolean(session);
        setHasAccount(signedIn);
        if (!signedIn) return;
        void getMyTracking({membershipOnly: true})
          .then((summary) => {
            if (!cancelled && isPersonalizedScopeCurrent(scope)) {
              setTrackedTopicIds(summary.topics.map((item) => item.topic.id));
              setTrackedBillIds(summary.bills.map((item) => item.bill.id));
              setTrackingReady(true);
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
  }, [trackingRefresh]);

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

  const resultFilters = JSON.stringify([idFilter, billNumberFilter, sessionFilter, jurisdictionFilter, statusFilter, trackingFilter, sponsorFilter, topicIdFilter, topicFuzzyFilter, queryFilter, sort, filterAccount]);
  const resultsKey = JSON.stringify([resultFilters, resultsRevision]);

  useEffect(() => {
    if (!filterMetaReady || sessionFilter === null) return;
    if (filterAccount === null) {
      setLoading(true);
      setError(null);
      return;
    }
    if (!filterAccount) {
      setPage(null);
      setLoading(false);
      setError("Log in to filter tracked bills.");
      return;
    }
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

    const refreshLoadedPages = committedResults.current.filters === resultFilters && committedResults.current.revision !== resultsRevision;
    const start = refreshLoadedPages ? 1 : pageNum;
    const requestPage = (requestedPage: number) => getBills({
      page: requestedPage,
      session: sessionParsed,
      id: idParsed,
      bill_number: billNumberFilter || undefined,
      jurisdiction: jurisdictionFilter || undefined,
      status: statusFilter || undefined,
      tracking: trackingFilter === "tracked" || trackingFilter === "untracked" ? trackingFilter : undefined,
      sponsor: sponsorFilter || undefined,
      topic: topicFuzzyFilter || undefined,
      topic_id: topicIdParsed,
      q: queryFilter || undefined,
      sort,
    });
    const load = async () => {
      let data = await requestPage(start);
      for (let next = start + 1; refreshLoadedPages && next <= pageNum && data.next && !cancelled; next++) {
        const more = await requestPage(next);
        data = {...more, results: [...data.results, ...more.results]};
      }
      return data;
    };
    load()
      .then((data) => {
        if (!cancelled) {
          const append = committedResults.current.key === resultsKey && pageNum === committedResults.current.page + 1;
          committedResults.current = {key: resultsKey, filters: resultFilters, page: pageNum, start: append ? committedResults.current.start : start, revision: resultsRevision};
          setPage(previous => {
            if (!append || !previous) return data;
            const ids = new Set(previous.results.map(bill => bill.id));
            return {...data, results: [...previous.results, ...data.results.filter(bill => !ids.has(bill.id))]};
          });
          setFirstShownPage(committedResults.current.start);
          setShownPage(pageNum);
        }
      })
      .catch((e) => {
        if (e?.name === "AbortError") return;
        if (!cancelled)
          setError("Could not load bills. Please try again.");
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
    trackingFilter,
    resultsRevision,
    filterAccount,
    sponsorFilter,
    topicIdFilter,
    topicFuzzyFilter,
    filterMetaReady,
    topicUrlError,
    queryFilter,
    sort,
    resultsKey,
    resultFilters,
    retryResults,
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
    if (trackingFilter) next.set("tracking", trackingFilter);
    if (sponsorFilter) next.set("sponsor", sponsorFilter);
    if (topicIdFilter) next.set("topic_id", topicIdFilter);
    if (topicFuzzyFilter) next.set("topic", topicFuzzyFilter);
    if (queryFilter) next.set("q", queryFilter);
    if (selectedSort) next.set("sort", selectedSort);
    const target = `/bills${next.size ? `?${next}` : ""}`;
    if (next.toString() !== searchParamsKey) {
      // These filters are client-owned. A route navigation can suspend the
      // provider tree and reset scroll even with scroll:false on mobile.
      window.history.replaceState(window.history.state, "", target);
    }
  }, [billNumberFilter, filterMetaReady, idFilter, jurisdictionFilter, pageNum, queryFilter, router, searchParamsKey, sessionFilter, selectedSort, sponsorFilter, statusFilter, trackingFilter, topicFuzzyFilter, topicIdFilter]);

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

  // Reveal the catalog once per session. Later filter requests keep the controls
  // mounted so typing, focus, and scroll position survive a results refresh.
  const catalogReady = (filterMetaReady || Boolean(filterMetaError))
    && (topics !== null || Boolean(topicOptionsError))
    && hasAccount !== null
    && (!hasAccount || ((trackingReady || Boolean(trackingError)) && (savedSearches !== null || Boolean(savedSearchError))))
    && (page !== null || !loading);
  useEffect(() => {
    if (catalogReady) setCatalogVisible(true);
  }, [catalogReady]);

  const hasNext = Boolean(page?.next);
  useEffect(() => {
    if (!endOfResults.current || !hasNext || loading || error || pageNum !== shownPage || committedResults.current.key !== resultsKey || queryInput.trim() !== queryFilter || typeof IntersectionObserver === "undefined") return;
    let active = true;
    const observer = new IntersectionObserver(entries => {
      if (active && entries.some(entry => entry.isIntersecting)) {
        active = false;
        setPageNum(shownPage + 1);
      }
    }, {rootMargin: "300px"});
    observer.observe(endOfResults.current);
    return () => { active = false; observer.disconnect(); };
  }, [catalogVisible, hasNext, loading, error, pageNum, shownPage, resultsKey, queryInput, queryFilter]);
  const selectedTopicId = topicIdFilter ? parseInt(topicIdFilter, 10) : NaN;
  const selectedTopic = topics?.find((topic) => topic.id === selectedTopicId);
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
    ...(topics ?? []).map((topic) => ({
      value: String(topic.id),
      label: topic.name,
    })),
  ];

  async function toggleBillTracking(id: number) {
    if (!trackingReady || pendingBills.has(id)) return;
    const scope = capturePersonalizedScope();
    const followed = trackedBillIds.includes(id);
    setPendingBills(ids => new Set(ids).add(id));
    setTrackingError(null);
    try {
      if (followed) await untrackBill(id, { scope });
      else await trackBill(id, { scope });
      if (capturePersonalizedScope().sessionGeneration === scope.sessionGeneration) setTrackedBillIds(ids => followed ? ids.filter(value => value !== id) : [...new Set([...ids, id])]);
    } catch {
      if (capturePersonalizedScope().sessionGeneration === scope.sessionGeneration) setTrackingError("Your follow preference was not saved. Please try again.");
    } finally {
      if (capturePersonalizedScope().sessionGeneration === scope.sessionGeneration) {
        setPendingBills(ids => {
          const next = new Set(ids);
          next.delete(id);
          return next;
        });
      }
    }
  }

  async function toggleSelectedTopicTracking() {
    if (Number.isNaN(selectedTopicId) || trackingTopicId === selectedTopicId) return;
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
    if (trackingFilter) query.tracking = trackingFilter;
    if (sponsorFilter) query.sponsor = sponsorFilter;
    if (topicId) query.topic_id = topicId;
    if (topicFuzzyFilter) query.topic = topicFuzzyFilter;
    if (queryFilter) query.q = queryFilter;
    if (selectedSort) query.sort = selectedSort;
    return query;
  }

  async function saveCurrentSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = savedSearchName.trim();
    if (!name) return;
    setSavedSearchError(null);
    try {
      const saved = await createSavedBillSearch(name, currentSearchQuery());
      setSavedSearches((items) => [saved, ...(items ?? [])]);
      setSavedSearchName("");
      setIsSaveSearchFormOpen(false);
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
      setTrackingFilter(typeof query.tracking === "string" ? query.tracking : "");
      setSponsorFilter(typeof query.sponsor === "string" ? query.sponsor : "");
      setTopicIdFilter(typeof query.topic_id === "number" ? String(query.topic_id) : "");
      setTopicFuzzyFilter(typeof query.topic === "string" ? query.topic : "");
      const nextQuery = typeof query.q === "string" ? query.q : "";
      if (nextQuery !== queryInputRef.current) {
        suppressNextQueryDebounceRef.current = true;
        queryInputRef.current = nextQuery;
        setQueryInput(nextQuery);
      }
      setQueryFilter(nextQuery);
      setSelectedSort(parseSort(query.sort));
      setPage({ count: result.count, next: null, previous: null, results: result.results });
      setPageNum(1);
      setPendingSavedAck({ searchId: search.id, watermark: result.result_watermark });
    } catch (cause) {
      setSavedSearchError(cause instanceof Error ? cause.message : "Could not open saved search.");
    }
  }

  if (!catalogVisible && !catalogReady) return <LoadingSpinner centered label="Loading bills…" />;

  return (
    <div className="tracker-page min-h-[calc(100vh-4rem)] font-sans">
      <div className="w-full">
        <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h1 className="tracker-heading text-ink">
            Ingested Bills
          </h1>
        </div>

        <div className="mb-6 tracker-panel">
          <div className="responsive-field-grid">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted">Full-text search</span>
              <SearchInput value={queryInput} onChange={(event) => { setPageNum(1); queryInputRef.current = event.target.value; setQueryInput(event.target.value); }} placeholder="Words in title, summary, etc." className="rounded border border-control bg-paper px-2 py-1 text-ink" />
            </label>
            <SelectField label="Sort" value={sort} options={[
              { value: "recent_activity", label: "Recent activity" },
              { value: "oldest_activity", label: "Oldest activity" },
              { value: "relevance", label: "Relevance" },
              { value: "unsorted", label: "Unsorted" },
            ]} onChange={value => { setPageNum(1); setSelectedSort(parseSort(value)); }} />
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted">Bill ID</span>
              <SearchInput
                type="text"
                inputMode="numeric"
                value={idFilter}
                onChange={resetPageAndSet(setIdFilter)}
                placeholder="e.g. 42"
                className="rounded border border-control bg-paper px-2 py-1 text-ink"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted">Bill # (contains)</span>
              <SearchInput
                type="text"
                value={billNumberFilter}
                onChange={resetPageAndSet(setBillNumberFilter)}
                placeholder="e.g. HR 123"
                className="rounded border border-control bg-paper px-2 py-1 text-ink"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted">Session (Congress)</span>
              <SearchInput
                type="text"
                value={sessionFilter ?? ""}
                onChange={(event) => {
                  setPageNum(1);
                  setSessionFilter(event.target.value);
                }}
                placeholder="Current Congress"
                className="rounded border border-control bg-paper px-2 py-1 text-ink"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted">Status</span>
              <Dropdown
                value={statusFilter}
                onChange={(event) => {
                  setPageNum(1);
                  setStatusFilter(event.target.value);
                }}
                className="min-h-10 min-w-0 w-full rounded border border-control bg-paper px-2 py-1 text-ink"
              >
                <option value="">All statuses</option>
                {statusFilter && !STATUS_OPTIONS.some(option => option.value === statusFilter) && (
                  <option value={statusFilter}>Saved filter: {statusFilter}</option>
                )}
                {STATUS_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
              </Dropdown>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted">Tracking</span>
              <Dropdown value={trackingFilter} title={!hasAccount ? "Log in to filter tracked bills" : undefined}
                onChange={resetPageAndSet(setTrackingFilter)}
                className="min-h-10 min-w-0 w-full rounded border border-control bg-paper px-2 py-1 text-ink">
                <option value="">All bills</option>
                <option value="tracked" disabled={!hasAccount}>Tracked</option>
                <option value="untracked" disabled={!hasAccount}>Untracked</option>
              </Dropdown>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted">Sponsor</span>
              <SearchInput
                type="text"
                value={sponsorFilter}
                onChange={resetPageAndSet(setSponsorFilter)}
                placeholder="Sponsor name"
                className="rounded border border-control bg-paper px-2 py-1 text-ink"
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
              <span className="text-muted">Topic contains</span>
              <SearchInput
                type="text"
                value={topicFuzzyFilter}
                onChange={onTopicFuzzyChange}
                placeholder="e.g. health"
                disabled={Boolean(topicIdFilter)}
                className="rounded border border-control bg-paper px-2 py-1 text-ink disabled:opacity-40"
              />
            </label>
          </div>
          {hasAccount !== null && (selectedTopic || !hasAccount || trackingError) && <div className="mt-4 border-t border-line pt-3 text-sm">
            {hasAccount ? (
              selectedTopic ? (
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-muted">
                    {selectedTopic.name}
                  </span>
                  <button
                    type="button"
                    onClick={toggleSelectedTopicTracking}
                    disabled={!trackingReady}
                    aria-disabled={!trackingReady || trackingTopicId === selectedTopic.id}
                    className="cursor-pointer border border-control px-3 py-1.5 font-semibold text-ink hover:bg-wash disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {selectedTopicIsTracked ? "Tracked topic" : "Track topic"}
                  </button>
                </div>
              ) : null
            ) : (
              <Link
                href="/login"
                className="text-ink underline hover:text-ink"
              >
                Log in to track topics
              </Link>
            )}
            {trackingError && (
              <p className="mt-2 text-red-700 dark:text-red-300">{trackingError}</p>
            )}
          </div>}
          {hasAccount && (
            <div className="mt-4 border-t border-line pt-3 text-sm">
              <div className="flex flex-wrap items-center gap-3">
                {isSaveSearchFormOpen ? (
                  <form
                    onSubmit={(event) => void saveCurrentSearch(event)}
                    className="flex flex-wrap items-center gap-2"
                  >
                    <label className="flex items-center gap-2">
                      <span className="text-muted">Name</span>
                      <input
                        type="text"
                        aria-label="Saved search name"
                        value={savedSearchName}
                        onChange={(event) => setSavedSearchName(event.target.value)}
                        autoFocus
                        className="rounded border border-control bg-paper px-2 py-1 text-ink"
                      />
                    </label>
                    <button
                      type="submit"
                      disabled={!savedSearchName.trim()}
                      className="cursor-pointer border border-control px-3 py-1.5 font-semibold text-ink hover:bg-wash disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Save search
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setSavedSearchName("");
                        setIsSaveSearchFormOpen(false);
                      }}
                      className="cursor-pointer text-ink underline"
                    >
                      Cancel
                    </button>
                  </form>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      setSavedSearchError(null);
                      setIsSaveSearchFormOpen(true);
                    }}
                    className="cursor-pointer border border-control px-3 py-1.5 font-semibold text-ink hover:bg-wash"
                  >
                    Save this search
                  </button>
                )}
                {Boolean(savedSearches?.length) && <span className="text-muted">Saved searches:</span>}
                {savedSearches?.map((search) => <button key={search.id} type="button" onClick={() => void openSavedSearch(search)} className="cursor-pointer text-ink underline">{search.name}{search.new_result_count ? ` (${search.new_result_count} new)` : ""}</button>)}
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

        <div className="min-h-6 text-sm text-red-700" aria-live="polite">
          {!loading && error ? <span role="alert">{error}</span> : null}
        </div>

        <LoadingSpinner centered active={loading && !page} label="Loading bills…" />

        {page && (
          <>
            {firstShownPage > 1 && <button type="button" disabled={loading}
              onClick={() => setPageNum(firstShownPage - 1)}
              className="mb-3 rounded border border-control px-3 py-1 text-ink">Previous page</button>}
            <p className="mb-4 text-muted">
              {page.count} bill{page.count !== 1 ? "s" : ""}
            </p>
            <div className={styles.deck}>
              {trackingError && <p role="alert">{trackingError}</p>}
              <div className={styles.toolbar}>
                <div className={styles.segment} aria-label="Card layout">
                  {(["grid", "list"] as const).map(value => <button key={value} aria-pressed={layout === value} onClick={() => setLayout(value)}>{value === "grid" ? "Grid" : "List"}</button>)}
                </div>
              </div>
              {!page.results.length ? <p className={styles.empty}>No bills match these filters.</p> :
                <div className={layout === "grid" ? styles.grid : styles.list} role="region" aria-label="Bill results" aria-busy={loading} tabIndex={0}>
                  {page.results.map(bill => <DashboardBillReader key={bill.id} bill={bill}>{(summary, enhance, feedback, currentBill) => <BillCard bill={currentBill} summary={summary} feedback={feedback}
                    footer={<div className="bill-card-actions">{hasAccount === null ? <button disabled aria-busy="true" aria-label="Loading follow status">Follow</button> : hasAccount ? trackingReady ? <button aria-disabled={pendingBills.has(bill.id)} aria-pressed={trackedBillIds.includes(bill.id)} onClick={() => void toggleBillTracking(bill.id)}>{trackedBillIds.includes(bill.id) ? "Unfollow" : "Follow"}</button> : <button disabled={!trackingError} aria-busy={!trackingError} aria-label={trackingError ? "Retry follow status" : "Loading follow status"} onClick={() => setTrackingRefresh(value => value + 1)}>{trackingError ? "Retry" : "Follow"}</button> : <Link href="/login">Log in to follow</Link>}{enhance}</div>} />}</DashboardBillReader>)}
                </div>}
            </div>
            <div ref={endOfResults} className="mt-4 flex min-h-12 items-center justify-center" aria-label="More bills">
              <LoadingSpinner active={loading} label="Loading more bills…" />
              {!loading && error && <button type="button" onClick={() => setRetryResults(value => value + 1)} className="rounded border border-control px-3 py-1 text-ink">Retry loading bills</button>}
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
        <div className="flex min-h-[60vh] items-center justify-center font-sans text-muted">
          <LoadingSpinner centered label="Loading bills…" />
        </div>
      }
    >
      <BillsCatalog />
    </Suspense>
  );
}
