"use client";
import BillCard from "../components/BillCard";
import BillDeckModal from "../components/BillDeckModal";
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
  type BillListItem,
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

function BillsCatalog() {
  const [layout, setLayout] = useState<"grid" | "list">("grid");
  const [selectedBill, setSelectedBill] = useState<BillListItem | null>(null);
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
  const [trackedBillIds, setTrackedBillIds] = useState<number[]>([]);
  const [pendingBill, setPendingBill] = useState<number | null>(null);
  const [trackingReady, setTrackingReady] = useState(false);
  const [trackingRefresh, setTrackingRefresh] = useState(0);
  useEffect(() => subscribePersonalizedChanges(() => {
    setTrackingReady(false); setTrackedBillIds([]); setPendingBill(null);
    setTrackingRefresh(value => value + 1);
  }), []);
  const [trackingTopicId, setTrackingTopicId] = useState<number | null>(null);
  const [trackingError, setTrackingError] = useState<string | null>(null);
  const [savedSearches, setSavedSearches] = useState<SavedBillSearch[]>([]);
  const [savedSearchError, setSavedSearchError] = useState<string | null>(null);
  const [isSaveSearchFormOpen, setIsSaveSearchFormOpen] = useState(false);
  const [savedSearchName, setSavedSearchName] = useState("");
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
    const scope = capturePersonalizedScope();
    void getSession()
      .then((session) => {
        if (cancelled || !isPersonalizedScopeCurrent(scope)) return;
        const signedIn = Boolean(session);
        setHasAccount(signedIn);
        if (!signedIn) return;
        void getMyTracking()
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

  async function toggleBillTracking(id: number) {
    if (!trackingReady || pendingBill !== null) return;
    const scope = capturePersonalizedScope();
    const followed = trackedBillIds.includes(id);
    setPendingBill(id); setTrackingError(null);
    try {
      if (followed) await untrackBill(id, { scope });
      else await trackBill(id, { scope });
      if (isPersonalizedScopeCurrent(scope)) setTrackedBillIds(ids => followed ? ids.filter(value => value !== id) : [...new Set([...ids, id])]);
    } catch {
      if (isPersonalizedScopeCurrent(scope)) setTrackingError("Your follow preference was not saved. Please try again.");
    } finally {
      if (isPersonalizedScopeCurrent(scope)) setPendingBill(null);
    }
  }

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

  async function saveCurrentSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = savedSearchName.trim();
    if (!name) return;
    setSavedSearchError(null);
    try {
      const saved = await createSavedBillSearch(name, currentSearchQuery());
      setSavedSearches((items) => [saved, ...items]);
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
    <div className="tracker-page min-h-[calc(100vh-4rem)] font-sans">
      {selectedBill && <BillDeckModal key={selectedBill.id} bill={selectedBill} onClose={() => setSelectedBill(null)} />}
      <div className="w-full">
        <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h1 className="tracker-heading text-ink">
            Ingested Bills
          </h1>
          <Link
            href="/"
            className="cursor-pointer text-ink underline hover:text-ink"
          >
            ← Dashboard
          </Link>
        </div>

        <div className="mb-6 tracker-panel">
          <p className="mb-3 text-sm text-muted">
            Search and filters apply automatically. Topic: use <strong>dropdown</strong> for
            an exact tag, or <strong>topic contains</strong> for a fuzzy match
            (not both).
          </p>
          <div className="responsive-field-grid">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted">Full-text search</span>
              <input type="search" value={queryInput} onChange={(event) => { setPageNum(1); queryInputRef.current = event.target.value; setQueryInput(event.target.value); }} placeholder="Words in title, summary, analysis, or text" className="rounded border border-control bg-paper px-2 py-1 text-ink" />
            </label>
            <SelectField label="Sort" value={sort} options={[{ value: "recent_activity", label: "Recent activity" }, { value: "relevance", label: "Relevance" }]} onChange={(value) => { setPageNum(1); setSort(value === "relevance" && queryInput.trim() ? "relevance" : "recent_activity"); }} />
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted">Bill ID</span>
              <input
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
              <input
                type="text"
                value={billNumberFilter}
                onChange={resetPageAndSet(setBillNumberFilter)}
                placeholder="e.g. HR 123"
                className="rounded border border-control bg-paper px-2 py-1 text-ink"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted">Session (Congress)</span>
              <input
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
              <span className="text-muted">Status</span>
              <select
                value={statusFilter}
                onChange={(event) => {
                  setPageNum(1);
                  setStatusFilter(event.target.value);
                }}
                className="min-w-0 w-full rounded border border-control bg-paper px-2 py-1 text-ink"
              >
                <option value="">All statuses</option>
                {statusFilter && !STATUS_OPTIONS.some(option => option.value === statusFilter) && (
                  <option value={statusFilter}>Saved filter: {statusFilter}</option>
                )}
                {STATUS_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted">Sponsor</span>
              <input
                type="text"
                value={sponsorFilter}
                onChange={resetPageAndSet(setSponsorFilter)}
                placeholder="Name or numeric id"
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
              <span className="text-muted">Topic contains (fuzzy)</span>
              <input
                type="text"
                value={topicFuzzyFilter}
                onChange={onTopicFuzzyChange}
                placeholder="Matches topic name/slug"
                disabled={Boolean(topicIdFilter)}
                className="rounded border border-control bg-paper px-2 py-1 text-ink disabled:opacity-40"
              />
            </label>
          </div>
          <div className="mt-4 border-t border-line pt-3 text-sm">
            {hasAccount ? (
              selectedTopic ? (
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-muted">
                    {selectedTopic.name}
                  </span>
                  <button
                    type="button"
                    onClick={toggleSelectedTopicTracking}
                    disabled={trackingTopicId === selectedTopic.id}
                    className="cursor-pointer border border-control px-3 py-1.5 font-semibold text-ink hover:bg-wash disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {trackingTopicId === selectedTopic.id
                      ? "Saving..."
                      : selectedTopicIsTracked
                        ? "Tracked topic"
                        : "Track topic"}
                  </button>
                </div>
              ) : (
                <p className="text-muted">
                  Select an exact topic to track it.
                </p>
              )
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
          </div>
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
                {savedSearches.length > 0 && <span className="text-muted">Saved searches:</span>}
                {savedSearches.map((search) => <button key={search.id} type="button" onClick={() => void openSavedSearch(search)} className="cursor-pointer text-ink underline">{search.name}{search.new_result_count ? ` (${search.new_result_count} new)` : ""}</button>)}
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

        {loading && <p className="text-muted">Loading…</p>}

        {!loading && page && (
          <>
            <p className="mb-4 text-muted">
              {page.count} bill{page.count !== 1 ? "s" : ""} (page {pageNum})
            </p>
            <div className={styles.deck}>
              {trackingError && <p role="alert">{trackingError}</p>}
              <div className={styles.toolbar}>
                <div className={styles.segment} aria-label="Card layout">
                  {(["grid", "list"] as const).map(value => <button key={value} aria-pressed={layout === value} onClick={() => setLayout(value)}>{value === "grid" ? "Grid" : "List"}</button>)}
                </div>
              </div>
              {!page.results.length ? <p className={styles.empty}>No bills match these filters.</p> :
                <div className={layout === "grid" ? styles.grid : styles.list} role="region" aria-label="Bill results" tabIndex={0}>
                  {page.results.map(bill => <BillCard key={bill.id} bill={bill} onOpen={() => setSelectedBill(bill)}
                    footer={<div className="flex flex-wrap items-center gap-3"><Link href={`/bills/${bill.id}`}>Open full bill page</Link>{hasAccount ? trackingReady ? <button disabled={pendingBill !== null} aria-pressed={trackedBillIds.includes(bill.id)} onClick={() => void toggleBillTracking(bill.id)}>{pendingBill === bill.id ? "Saving…" : trackedBillIds.includes(bill.id) ? "Unfollow" : "Follow"}</button> : <button onClick={() => setTrackingRefresh(value => value + 1)}>Load follow status</button> : <Link href="/login">Log in to follow</Link>}</div>} />)}
                </div>}
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

export default function BillsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[60vh] items-center justify-center font-sans text-muted">
          Loading bills…
        </div>
      }
    >
      <BillsCatalog />
    </Suspense>
  );
}
