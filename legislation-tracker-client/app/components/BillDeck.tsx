"use client";

import Link from "next/link";
import React from "react";
import { getBillFilterOptions, getMyTracking, getSession, getAllCurrentRepresentatives, trackBill, untrackBill, type BillListItem, type TrackingSummary, type RepresentativeItem } from "@/lib/api";
import BillDeckModal from "./BillDeckModal";
import IngestionTelemetryLive from "./IngestionTelemetryLive";
import RecommendationsPreview from "./RecommendationsPreview";
import { focusRecommendationFallback } from "@/lib/recommendation-focus";
import { capturePersonalizedScope, isPersonalizedScopeCurrent, subscribePersonalizedChanges } from "@/lib/api";
import LegislatorName from "./LegislatorName";
import styles from "./bill-deck.module.css";

import BillCard, { readable } from "./BillCard";
export { topicColor, readable, dateLabel } from "./BillCard";

export default function BillDeck() {
  const [tracking, setTracking] = React.useState<TrackingSummary | null>(null);
  const [signedIn, setSignedIn] = React.useState(false);
  const [ready, setReady] = React.useState(false);
  const [error, setError] = React.useState("");
  const [attempt, setAttempt] = React.useState(0);
  const [representatives, setRepresentatives] = React.useState<RepresentativeItem[]>([]);
  const [currentCongress, setCurrentCongress] = React.useState<number | null>(null);
  const [repError, setRepError] = React.useState("");
  const [query, setQuery] = React.useState("");
  const [topic, setTopic] = React.useState("");
  const [sponsor, setSponsor] = React.useState("");
  const [state, setState] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [sort, setSort] = React.useState("recent");
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

  const followed = new Set(tracking?.bills.map(item => item.bill.id));
  const source = tracking?.bills.map(item => item.bill) ?? [];
  const topics = new Map<number, string>();
  tracking?.topics.forEach(item => topics.set(item.topic.id, item.topic.name));
  source.forEach(bill => bill.topics.forEach(item => topics.set(item.topic_id, item.name)));
  const sponsorKey = (bill: BillListItem) => bill.sponsor_id ? `id:${bill.sponsor_id}` : `unidentified:${bill.sponsor_name ?? ""}`;
  const sponsors = [...new Map(source.filter(bill => bill.sponsor_name).map(bill => [sponsorKey(bill), bill.sponsor_name!])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  const statuses = [...new Set(source.map(bill => bill.status).filter(Boolean))].sort();
  const stateBySponsor = new Map(representatives.map(rep => [rep.id, rep.state]));
  const states = [...new Set(source.map(bill => stateBySponsor.get(bill.sponsor_id ?? -1)).filter((value): value is string => Boolean(value)))].sort();
  const visible = source.filter(bill => (!query || `${bill.bill_number} ${bill.title}`.toLowerCase().includes(query.toLowerCase())) && (!topic || bill.topics.some(item => String(item.topic_id) === topic)) && (!sponsor || sponsorKey(bill) === sponsor) && (!state || stateBySponsor.get(bill.sponsor_id ?? -1) === state) && (!status || bill.status === status));
  visible.sort((a, b) => {
    if (sort === "title") return a.title.localeCompare(b.title) || a.id - b.id;
    if (sort === "number") return a.bill_number.localeCompare(b.bill_number, undefined, { numeric: true }) || b.session - a.session || a.id - b.id;
    const dateA = Date.parse(a.last_action_at ?? ""), dateB = Date.parse(b.last_action_at ?? "");
    if (!Number.isFinite(dateA)) return Number.isFinite(dateB) ? 1 : a.id - b.id;
    if (!Number.isFinite(dateB)) return -1;
    return (sort === "oldest" ? dateA - dateB : dateB - dateA) || a.id - b.id;
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
    <div className={styles.filters}>
      <label>Search bills<input type="search" placeholder="Title or bill number" value={query} onChange={event => setQuery(event.target.value)} /></label>
      <label>Topic<select aria-label="Topic" value={topic} onChange={event => setTopic(event.target.value)}><option value="">All topics</option>{[...topics].map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
      <label>Representative (sponsor)<select aria-label="Representative (sponsor)" value={sponsor} onChange={event => setSponsor(event.target.value)}><option value="">All sponsors</option>{sponsors.map(([key, name]) => { const representative = representatives.find(rep => key === `id:${rep.id}`); return <option key={key} value={key}>{name}{representative ? ` · ${representative.state} · ${representative.chamber}` : " · Affiliation unavailable"}</option>; })}</select></label>
      <label>Sponsor state<select aria-label="Sponsor state" disabled={Boolean(repError)} value={state} onChange={event => setState(event.target.value)}><option value="">All states</option>{states.map(value => <option key={value}>{value}</option>)}</select></label>
      <label>Status<select aria-label="Status" value={status} onChange={event => setStatus(event.target.value)}><option value="">All statuses</option>{statuses.map(value => <option key={value} value={value}>{readable(value)}</option>)}</select></label>
      <label>Sort bills<select value={sort} onChange={event => setSort(event.target.value)}><option value="recent">Latest action first</option><option value="oldest">Oldest action first</option><option value="title">Title A–Z</option><option value="number">Bill number</option></select></label>
    </div>
    <div className={styles.resultLine}><p role="status">{visible.length} {visible.length === 1 ? "bill" : "bills"} in view</p><button onClick={reset}>Clear filters</button></div>
    {repError && <p className={styles.note}>{repError} <button onClick={() => setAttempt(value => value + 1)}>Retry directory</button></p>}
    {error && <div role="alert" className={styles.empty}>{error} <button onClick={() => setAttempt(value => value + 1)}>Retry</button></div>}
    {followError && <p role="alert">{followError}</p>}
    {!ready && <p role="status" className={styles.empty}>Loading your followed bills…</p>}
    {ready && !signedIn && !error && <div className={styles.empty}><h2>Start your collection</h2><p><Link href="/login">Log in</Link> to follow bills, or browse the <Link href="/bills">Bills page</Link>.</p></div>}
    {ready && !error && signedIn && !visible.length && <div className={styles.empty}><h2>{source.length ? "No bills match these filters" : "Your collection starts with a bill"}</h2><p>{source.length ? "Clear a filter to see more legislation." : <>Browse the <Link href="/bills">Bills page</Link> and follow a bill to keep it here.</>}</p>{!tracking?.topics.length && <p>Follow topics to organize your collection around your interests.</p>}</div>}
    {visible.length > 0 && <section className={styles.topicSection}>
      <h2>Following<small>{visible.length}</small></h2>
      <div role="region" aria-label="Followed bills" tabIndex={0} className={styles.followedRow}>{visible.map(bill => <BillCard key={bill.id} bill={bill}
        accentTopicId={bill.topics.find(item => tracking?.topics.some(follow => follow.topic.id === item.topic_id))?.topic_id}
        sponsorState={stateBySponsor.get(bill.sponsor_id ?? -1)}
        onOpen={() => { recommendationOwnsBill.current = false; setSelectedFromRecommendations(false); setSelected(bill); }}
        footer={signedIn && tracking ? <button disabled={pending !== null} aria-pressed={followed.has(bill.id)} onClick={() => void toggleFollow(bill)}>{pending === bill.id ? "Saving…" : followed.has(bill.id) ? "Unfollow" : "Follow"}</button> : error ? <span>Following unavailable</span> : !ready ? <span>Loading preferences…</span> : <Link href="/login">Log in to follow</Link>}
      />)}</div>
    </section>}
    <RecommendationsPreview renderName={currentCongress === null ? undefined : ({ id, name, chamber }) => <LegislatorName id={id} name={name} congress={currentCongress} chamber={chamber === "house" || chamber === "senate" ? chamber : undefined} />} onOpenBill={bill => { recommendationOwnsBill.current = true; setSelectedFromRecommendations(true); setSelected(bill); return true; }} onDismissBill={dismissRecommendedBill} />
    {ready && <IngestionTelemetryLive key={`${signedIn}:${Boolean(tracking?.is_staff)}`} />}
    {selected && <BillDeckModal {...(selectedFromRecommendations ? { fallbackFocus: focusRecommendationFallback } : {})} bill={selected} onClose={() => { recommendationOwnsBill.current = false; setSelected(null); }} />}
  </div>;
}
