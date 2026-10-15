"use client";

import Link from "next/link";
import React from "react";
import { getBillFilterOptions, getBills, getMyTracking, getSession, getAllCurrentRepresentatives, trackBill, untrackBill, type BillListItem, type TrackingSummary, type RepresentativeItem } from "@/lib/api";
import BillDeckModal from "./BillDeckModal";
import IngestionTelemetryPreview from "./IngestionTelemetryPreview";
import RecommendationsPreview from "./RecommendationsPreview";
import { focusRecommendationFallback } from "@/lib/recommendation-focus";
import { capturePersonalizedScope, isPersonalizedScopeCurrent, subscribePersonalizedChanges } from "@/lib/api";
import LegislatorName from "./LegislatorName";
import styles from "./bill-deck.module.css";

const colors = ["#233f68", "#923e47", "#2f6b50", "#426c86", "#705786", "#357b78"];
export function topicColor(id: number) { return colors[Math.abs(id) % colors.length]; }
export function readable(value: string) { return value.replaceAll("_", " "); }
export function dateLabel(value: string | null) { if (!value) return "Not recorded"; const date = new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00` : value); return Number.isNaN(date.getTime()) ? "Not recorded" : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }); }

export default function BillDeck() {
  const [tracking, setTracking] = React.useState<TrackingSummary | null>(null);
  const [signedIn, setSignedIn] = React.useState(false);
  const [ready, setReady] = React.useState(false);
  const [error, setError] = React.useState("");
  const [attempt, setAttempt] = React.useState(0);
  const [all, setAll] = React.useState(false);
  const [bills, setBills] = React.useState<BillListItem[]>([]);
  const [page, setPage] = React.useState(0);
  const [total, setTotal] = React.useState(0);
  const [more, setMore] = React.useState(true);
  const [loading, setLoading] = React.useState(false);
  const [catalogError, setCatalogError] = React.useState("");
  const [representatives, setRepresentatives] = React.useState<RepresentativeItem[]>([]);
  const [currentCongress, setCurrentCongress] = React.useState<number | null>(null);
  const [repError, setRepError] = React.useState("");
  const [query, setQuery] = React.useState("");
  const [topic, setTopic] = React.useState("");
  const [sponsor, setSponsor] = React.useState("");
  const [state, setState] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [layout, setLayout] = React.useState("grid");
  const [selected, setSelected] = React.useState<BillListItem | null>(null);
  const [selectedFromRecommendations, setSelectedFromRecommendations] = React.useState(false);
  const recommendationOwnsBill = React.useRef(false);
  const dismissRecommendedBill = React.useCallback(() => {
    if (recommendationOwnsBill.current) { recommendationOwnsBill.current = false; setSelected(null); }
  }, []);
  const [pending, setPending] = React.useState<number | null>(null);
  const [followError, setFollowError] = React.useState("");

  React.useEffect(() => subscribePersonalizedChanges(() => {
    setTracking(null); setSignedIn(false); setReady(false); setError("");
    if (recommendationOwnsBill.current) setSelected(null);
    setPending(null); setFollowError("");
    setAttempt(value => value + 1);
  }), []);

  React.useEffect(() => {
    let live = true;
    const abort = new AbortController();
    const scope = capturePersonalizedScope();
    void (async () => {
      try {
        const session = await getSession({ scope, signal: abort.signal });
        if (!live || !isPersonalizedScopeCurrent(scope)) return;
        setSignedIn(Boolean(session));
        if (session) { const result = await getMyTracking({ scope, signal: abort.signal }); if (live && isPersonalizedScopeCurrent(scope)) setTracking(result); }
        if (live) setError("");
      } catch { if (live && isPersonalizedScopeCurrent(scope)) setError("Your followed bills could not be loaded. Retry to reconnect."); }
      finally { if (live && isPersonalizedScopeCurrent(scope)) setReady(true); }
    })();
    void getBillFilterOptions().then(options => { if (live && Number.isInteger(options.current_congress) && options.current_congress > 0) setCurrentCongress(options.current_congress); }).catch(() => { if (live) setCurrentCongress(null); });
    void getAllCurrentRepresentatives().then(result => { if (live) { setRepresentatives(result); setRepError(""); } }).catch(() => { if (live) setRepError("Sponsor state filters are unavailable until the representative directory reconnects."); });
    return () => { live = false; abort.abort(); };
  }, [attempt]);

  async function loadPage() {
    if (loading) return;
    setLoading(true); setCatalogError("");
    try {
      const result = await getBills({ page: page + 1, sort: "recent_activity" });
      setBills(previous => [...new Map([...previous, ...result.results].map(bill => [bill.id, bill])).values()]);
      setTotal(result.count); setMore(Boolean(result.next)); setPage(previous => previous + 1);
    } catch { setCatalogError("The bill collection could not be loaded. Try again."); }
    finally { setLoading(false); }
  }

  const followed = new Set(tracking?.bills.map(item => item.bill.id));
  const source = all ? bills : tracking?.bills.map(item => item.bill) ?? [];
  const topics = new Map<number, string>();
  tracking?.topics.forEach(item => topics.set(item.topic.id, item.topic.name));
  source.forEach(bill => bill.topics.forEach(item => topics.set(item.topic_id, item.name)));
  const sponsorKey = (bill: BillListItem) => bill.sponsor_id ? `id:${bill.sponsor_id}` : `unidentified:${bill.sponsor_name ?? ""}`;
  const sponsors = [...new Map(source.filter(bill => bill.sponsor_name).map(bill => [sponsorKey(bill), bill.sponsor_name!])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  const statuses = [...new Set(source.map(bill => bill.status).filter(Boolean))].sort();
  const stateBySponsor = new Map(representatives.map(rep => [rep.id, rep.state]));
  const states = [...new Set(source.map(bill => stateBySponsor.get(bill.sponsor_id ?? -1)).filter((value): value is string => Boolean(value)))].sort();
  const visible = source.filter(bill => (!query || `${bill.bill_number} ${bill.title}`.toLowerCase().includes(query.toLowerCase())) && (!topic || bill.topics.some(item => String(item.topic_id) === topic)) && (!sponsor || sponsorKey(bill) === sponsor) && (!state || stateBySponsor.get(bill.sponsor_id ?? -1) === state) && (!status || bill.status === status));
  const groups = new Map<string, { id: number; bills: BillListItem[] }>();
  visible.forEach(bill => {
    const preferred = bill.topics.find(item => tracking?.topics.some(follow => follow.topic.id === item.topic_id)) ?? bill.topics[0];
    const name = all ? "All legislation" : preferred?.name ?? "Other legislation";
    if (!groups.has(name)) groups.set(name, { id: preferred?.topic_id ?? 0, bills: [] });
    groups.get(name)!.bills.push(bill);
  });
  async function toggleFollow(bill: BillListItem) {
    if (!tracking || pending !== null) return;
    const scope = capturePersonalizedScope();
    setPending(bill.id); setFollowError("");
    try {
      if (followed.has(bill.id)) await untrackBill(bill.id, { scope });
      else await trackBill(bill.id, { scope });
    } catch { if (isPersonalizedScopeCurrent(scope)) setFollowError("Your follow preference was not saved. Please try again."); }
    finally { if (isPersonalizedScopeCurrent(scope)) setPending(null); }
  }
  const reset = () => { setQuery(""); setTopic(""); setSponsor(""); setState(""); setStatus(""); };
  return <div className={styles.deck}>
    <header className={styles.heading}>
      <div><h1 data-dashboard-heading tabIndex={-1}>Your legislation, in view.</h1><p>Follow the bills that matter to you. Read what’s happening, and what changed.</p></div>
      <Link href="/topics" className={styles.link}>Manage followed topics</Link>
    </header>
    <div className={styles.toolbar}>
      <div className={styles.segment} aria-label="Bill collection">
        <button aria-pressed={!all} onClick={() => { setAll(false); reset(); }}>Following {tracking ? `(${tracking.bills.length})` : ""}</button>
        <button aria-pressed={all} onClick={() => { setAll(true); reset(); if (!page) void loadPage(); }}>View all bills</button>
      </div>
      <div className={styles.segment} aria-label="Card layout">{["grid", "list"].map(value => <button key={value} aria-pressed={layout === value} onClick={() => setLayout(value)}>{value === "grid" ? "Grid" : "List"}</button>)}</div>
    </div>
    <div className={styles.filters}>
      <label>Search bills<input type="search" placeholder="Title or bill number" value={query} onChange={event => setQuery(event.target.value)} /></label>
      <label>Topic<select aria-label="Topic" value={topic} onChange={event => setTopic(event.target.value)}><option value="">All topics</option>{[...topics].map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
      <label>Representative (sponsor)<select aria-label="Representative (sponsor)" value={sponsor} onChange={event => setSponsor(event.target.value)}><option value="">All sponsors</option>{sponsors.map(([key, name]) => { const representative = representatives.find(rep => key === `id:${rep.id}`); return <option key={key} value={key}>{name}{representative ? ` · ${representative.state} · ${representative.chamber}` : " · Affiliation unavailable"}</option>; })}</select></label>
      <label>Sponsor state<select aria-label="Sponsor state" disabled={Boolean(repError)} value={state} onChange={event => setState(event.target.value)}><option value="">All states</option>{states.map(value => <option key={value}>{value}</option>)}</select></label>
      <label>Status<select aria-label="Status" value={status} onChange={event => setStatus(event.target.value)}><option value="">All statuses</option>{statuses.map(value => <option key={value} value={value}>{readable(value)}</option>)}</select></label>
    </div>
    <div className={styles.resultLine}><p role="status">{visible.length} {visible.length === 1 ? "bill" : "bills"} in view{all ? ` · ${bills.length} of ${total} loaded` : ""}</p><button onClick={reset}>Clear filters</button></div>
    {all && <p className={styles.note}>Filters apply to loaded bills. Load more to browse the full collection. Sponsor state uses the latest stored affiliation by representative ID; historical state may differ and unlisted sponsors have no state metadata.</p>}
    {repError && <p className={styles.note}>{repError} <button onClick={() => setAttempt(value => value + 1)}>Retry directory</button></p>}
    {error && <div role="alert" className={styles.empty}>{error} <button onClick={() => setAttempt(value => value + 1)}>Retry</button></div>}
    {followError && <p role="alert">{followError}</p>}
    <RecommendationsPreview renderName={currentCongress === null ? undefined : ({ id, name, chamber }) => <LegislatorName id={id} name={name} congress={currentCongress} chamber={chamber === "house" || chamber === "senate" ? chamber : undefined} />} onOpenBill={bill => { recommendationOwnsBill.current = true; setSelectedFromRecommendations(true); setSelected(bill); return true; }} onDismissBill={dismissRecommendedBill} />
    {!ready && !all && <p role="status" className={styles.empty}>Loading your followed bills…</p>}
    {ready && !all && !signedIn && !error && <div className={styles.empty}><h2>Start your collection</h2><p><Link href="/login">Log in</Link> to follow bills, or explore all bills above.</p></div>}
    {ready && !error && (all || signedIn) && !visible.length && !loading && <div className={styles.empty}><h2>{source.length ? "No bills match these filters" : all ? "No bills are loaded yet" : "Your collection starts with a bill"}</h2><p>{source.length ? "Clear a filter to see more legislation." : "Explore all bills and follow one to keep it here."}</p>{!all && !tracking?.topics.length && <p>Follow topics to organize your collection around your interests.</p>}</div>}
    {[...groups].map(([name, group]) => <section key={name} className={styles.topicSection}>
      <h2><span style={{ background: topicColor(group.id) }} aria-hidden="true" />{name}<small>{group.bills.length}</small></h2>
      <div className={layout === "grid" ? styles.grid : styles.list}>{group.bills.map(bill => <article key={bill.id} className={styles.card}>
        <div className={styles.bar} style={{ background: topicColor(bill.topics.find(item => tracking?.topics.some(follow => follow.topic.id === item.topic_id))?.topic_id ?? bill.topics[0]?.topic_id ?? 0) }} />
        <div className={styles.cardBody}>
          <div className={styles.cardMeta}><span>{bill.bill_number} / {bill.session}</span><span>{readable(bill.status || "Status unavailable")}</span></div>
          <h3><button onClick={() => { recommendationOwnsBill.current = false; setSelectedFromRecommendations(false); setSelected(bill); }}>{bill.title || "Untitled bill"}</button></h3>
          <p className={styles.cardTopics}>{bill.topics.map(item => item.name).join(", ") || "Topic not recorded"}</p>
          <p className={styles.sponsor}><LegislatorName id={bill.sponsor_id ?? null} name={bill.sponsor_name || "Sponsor not recorded"} congress={bill.session} />{stateBySponsor.get(bill.sponsor_id ?? -1) ? ` (${stateBySponsor.get(bill.sponsor_id!)}, latest stored state)` : ""}</p>
          <div className={styles.cardFooter}><span>Last action<br /><time>{dateLabel(bill.last_action_at)}</time></span>{signedIn && tracking ? <button disabled={pending !== null} aria-pressed={followed.has(bill.id)} onClick={() => void toggleFollow(bill)}>{pending === bill.id ? "Saving…" : followed.has(bill.id) ? "Unfollow" : "Follow"}</button> : error ? <span>Following unavailable</span> : !ready ? <span>Loading preferences…</span> : <Link href="/login">Log in to follow</Link>}</div>
        </div>
      </article>)}</div>
    </section>)}
    {catalogError && all && <p role="alert">{catalogError}</p>}
    {all && (more || catalogError) && <button className={styles.loadMore} disabled={loading} onClick={() => void loadPage()}>{loading ? "Loading bills…" : catalogError ? "Retry loading bills" : "Load more bills"}</button>}
    <IngestionTelemetryPreview isStaff={Boolean(tracking?.is_staff)} />
    {selected && <BillDeckModal {...(selectedFromRecommendations ? { fallbackFocus: focusRecommendationFallback } : {})} bill={selected} onClose={() => { recommendationOwnsBill.current = false; setSelected(null); }} />}
  </div>;
}
