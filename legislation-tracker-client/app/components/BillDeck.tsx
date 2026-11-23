"use client";

import Link from "next/link";
import React from "react";
import { getMyTracking, trackBill, untrackBill, type BillListItem, type TrackingSummary } from "@/lib/api";
import { dashboardSession, dashboardValue } from "@/lib/dashboard-cache";
import BillDeckModal from "./BillDeckModal";
import IngestionTelemetryLive from "./IngestionTelemetryLive";
import RecommendationsPreview from "./RecommendationsPreview";
import { focusRecommendationFallback } from "@/lib/recommendation-focus";
import { capturePersonalizedScope, isPersonalizedScopeCurrent, subscribePersonalizedChanges } from "@/lib/api";
import LegislatorName from "./LegislatorName";
import TrackedLegislators from "./TrackedLegislators";
import styles from "./bill-deck.module.css";

import DashboardBillReader from "./DashboardBillReader";
import BillCard, { readable } from "./BillCard";
import { STAGES, stageFor } from "@/lib/bill-stage";
export { topicColor, readable, dateLabel } from "./BillCard";

export default function BillDeck() {
  const [tracking, setTracking] = React.useState<TrackingSummary | null>(null);
  const [signedIn, setSignedIn] = React.useState(Boolean(tracking));
  const [isSuperuser, setIsSuperuser] = React.useState(false);
  const [ready, setReady] = React.useState(Boolean(tracking));
  const [error, setError] = React.useState("");
  const [attempt, setAttempt] = React.useState(0);
  const [currentCongress, setCurrentCongress] = React.useState<number | null>(null);
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

  React.useEffect(() => subscribePersonalizedChanges(({ kind }) => {
    if (kind === "revalidate" || kind === "tracking") { setPending(null); setAttempt(value => value + 1); return; }
    setTracking(null); setSignedIn(false); setIsSuperuser(false); setReady(false); setError("");
    setSelected(null);
    setPending(null); setFollowError("");
    setAttempt(value => value + 1);
  }), []);

  React.useEffect(() => {
    let live = true;
    const scope = capturePersonalizedScope();
    void (async () => {
      try {
        const session = await dashboardSession();
        if (!live || !isPersonalizedScopeCurrent(scope)) return;
        setSignedIn(Boolean(session));
        if (!session) setTracking(null);
        setIsSuperuser(session?.user.is_superuser === true);
        setCurrentCongress(session?.current_congress ?? null);
        if (session) { const result = await dashboardValue("tracking", () => getMyTracking({ scope })); if (live && isPersonalizedScopeCurrent(scope)) setTracking(result); }
        if (live) setError("");
      } catch { if (live && isPersonalizedScopeCurrent(scope)) { setError("Couldn’t refresh your bills."); } }
      finally { if (live && isPersonalizedScopeCurrent(scope)) setReady(true); }
    })();
    return () => { live = false; };
  }, [attempt]);

  const followed = new Set(tracking?.bills.map(item => item.bill.id));
  const source = tracking?.bills.map(item => item.bill) ?? [];
  const topics = new Map<number, string>();
  tracking?.topics.forEach(item => topics.set(item.topic.id, item.topic.name));
  source.forEach(bill => bill.topics.forEach(item => topics.set(item.topic_id, item.name)));
  const sponsorKey = (bill: BillListItem) => bill.sponsor_id ? `id:${bill.sponsor_id}` : `unidentified:${bill.sponsor_name ?? ""}`;
  const sponsors = [...new Map(source.filter(bill => bill.sponsor_name).map(bill => [sponsorKey(bill), bill.sponsor_name!])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  const presentStages = new Set(source.map(bill => stageFor(bill.status)?.key));
  const stageOptions = STAGES.filter(item => presentStages.has(item.key));
  const statuses = [...new Set(source.map(bill => bill.status).filter(value => value && !stageFor(value)))].sort();
  const stateBySponsor = new Map(source.map(bill => [bill.sponsor_id ?? -1, bill.sponsor_state ?? undefined]));
  const states = [...new Set(source.map(bill => stateBySponsor.get(bill.sponsor_id ?? -1)).filter((value): value is string => Boolean(value)))].sort();
  const visible = source.filter(bill => (!query || `${bill.bill_number} ${bill.title}`.toLowerCase().includes(query.toLowerCase())) && (!topic || bill.topics.some(item => String(item.topic_id) === topic)) && (!sponsor || sponsorKey(bill) === sponsor) && (!state || stateBySponsor.get(bill.sponsor_id ?? -1) === state) && (!status || (stageFor(bill.status)?.key ?? `raw:${bill.status}`) === status));
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
  return <div className={styles.deck}>
    <header className={styles.heading}>
      <h1 data-dashboard-heading tabIndex={-1}>Follow the bills that matter to you.</h1>
    </header>
    <div className={styles.filters}>
      <label>Search bills<input type="search" placeholder="Title or bill number" value={query} onChange={event => setQuery(event.target.value)} /></label>
      <label>Topic<select aria-label="Topic" value={topic} onChange={event => setTopic(event.target.value)}><option value="">All topics</option>{[...topics].map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
      <label>Representative (sponsor)<select aria-label="Representative (sponsor)" value={sponsor} onChange={event => setSponsor(event.target.value)}><option value="">All sponsors</option>{sponsors.map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label>
      <label>Sponsor state<select aria-label="Sponsor state" value={state} onChange={event => setState(event.target.value)}><option value="">All states</option>{states.map(value => <option key={value}>{value}</option>)}</select></label>
      <label>Status<select aria-label="Status" value={status} onChange={event => setStatus(event.target.value)}><option value="">All statuses</option>{stageOptions.map(item => <option key={item.key} value={item.key}>{item.name}</option>)}{statuses.map(value => <option key={value} value={`raw:${value}`}>{readable(value)}</option>)}</select></label>
      <label>Sort bills<select value={sort} onChange={event => setSort(event.target.value)}><option value="recent">Latest action first</option><option value="oldest">Oldest action first</option><option value="title">Title A–Z</option><option value="number">Bill number</option></select></label>
    </div>
    <div className="min-h-6 text-sm text-red-700" aria-live="polite">{error && <span role="alert">{error} <button onClick={() => setAttempt(value => value + 1)}>Retry</button></span>}</div>
    {followError && <p role="alert">{followError}</p>}
    {!ready && <p role="status" className={styles.empty}>Loading your followed bills…</p>}
    {ready && !signedIn && !error && <div className={styles.empty}><h2>Start your collection</h2><p><Link href="/login">Log in</Link> to follow bills, or browse the <Link href="/bills">Bills page</Link>.</p></div>}
    {ready && !error && signedIn && !visible.length && <div className={styles.empty}><h2>{source.length ? "No bills match these filters" : "Your collection starts with a bill"}</h2><p>{source.length ? "Clear a filter to see more legislation." : <>Browse the <Link href="/bills">Bills page</Link> and follow a bill to keep it here.</>}</p>{!tracking?.topics.length && <p>Follow topics to organize your collection around your interests.</p>}</div>}
    {visible.length > 0 && <section className={styles.topicSection}>
      <h2>Following<small>{visible.length}</small></h2>
      <div role="region" aria-label="Followed bills" tabIndex={0} className={styles.followedRow}>{visible.map(bill => <DashboardBillReader key={bill.id} bill={bill}>{(summary, enhance, feedback) => <BillCard feedback={feedback} summary={summary} bill={bill}
        accentTopicId={bill.topics.find(item => tracking?.topics.some(follow => follow.topic.id === item.topic_id))?.topic_id}
        sponsorState={stateBySponsor.get(bill.sponsor_id ?? -1)}
        onOpen={() => { recommendationOwnsBill.current = false; setSelectedFromRecommendations(false); setSelected(bill); }}
        footer={signedIn && tracking ? <div className="bill-card-actions"><button disabled={pending !== null} aria-pressed={followed.has(bill.id)} onClick={() => void toggleFollow(bill)}>{pending === bill.id ? "Saving…" : followed.has(bill.id) ? "Unfollow" : "Follow"}</button>{enhance}</div> : error ? <span>Following unavailable</span> : !ready ? <span>Loading preferences…</span> : <Link href="/login">Log in to follow</Link>}
      />}</DashboardBillReader>)}</div>
    </section>}
    {tracking && <TrackedLegislators items={tracking.legislators} congress={currentCongress} />}
    <RecommendationsPreview renderName={currentCongress === null ? undefined : ({ id, name, chamber }) => <LegislatorName id={id} name={name} congress={currentCongress} chamber={chamber === "house" || chamber === "senate" ? chamber : undefined} />} onOpenBill={bill => { recommendationOwnsBill.current = true; setSelectedFromRecommendations(true); setSelected(bill); return true; }} onDismissBill={dismissRecommendedBill} />
    {ready && signedIn && isSuperuser && <IngestionTelemetryLive />}
    {selected && <BillDeckModal {...(selectedFromRecommendations ? { fallbackFocus: focusRecommendationFallback } : {})} bill={selected} onClose={() => { recommendationOwnsBill.current = false; setSelected(null); }} />}
  </div>;
}
