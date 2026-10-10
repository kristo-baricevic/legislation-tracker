"use client";

import Link from "next/link";
import React from "react";
import { getBills, getMyTracking, getSession, getAllCurrentRepresentatives, trackBill, untrackBill, type BillListItem, type TrackingSummary, type RepresentativeItem } from "@/lib/api";
import BillDeckModal from "./BillDeckModal";
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
  const [repError, setRepError] = React.useState("");
  const [query, setQuery] = React.useState("");
  const [topic, setTopic] = React.useState("");
  const [sponsor, setSponsor] = React.useState("");
  const [state, setState] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [layout, setLayout] = React.useState("grid");
  const [selected, setSelected] = React.useState<BillListItem | null>(null);
  const [pending, setPending] = React.useState<number | null>(null);
  const [followError, setFollowError] = React.useState("");

  React.useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const session = await getSession();
        if (!live) return;
        setSignedIn(Boolean(session));
        if (session) { const result = await getMyTracking(); if (live) setTracking(result); }
        if (live) setError("");
      } catch { if (live) setError("Your followed bills could not be loaded. Retry to reconnect."); }
      finally { if (live) setReady(true); }
    })();
    void getAllCurrentRepresentatives().then(result => { if (live) { setRepresentatives(result); setRepError(""); } }).catch(() => { if (live) setRepError("Sponsor state filters are unavailable until the representative directory reconnects."); });
    return () => { live = false; };
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
  const sponsors = [...new Set(source.map(bill => bill.sponsor_name).filter((name): name is string => Boolean(name)))].sort();
  const statuses = [...new Set(source.map(bill => bill.status).filter(Boolean))].sort();
  const stateBySponsor = new Map(representatives.map(rep => [rep.name, rep.state]));
  const states = [...new Set(source.map(bill => stateBySponsor.get(bill.sponsor_name ?? "")).filter((value): value is string => Boolean(value)))].sort();
  const visible = source.filter(bill => (!query || `${bill.bill_number} ${bill.title}`.toLowerCase().includes(query.toLowerCase())) && (!topic || bill.topics.some(item => String(item.topic_id) === topic)) && (!sponsor || bill.sponsor_name === sponsor) && (!state || stateBySponsor.get(bill.sponsor_name ?? "") === state) && (!status || bill.status === status));
  const groups = new Map<string, { id: number; bills: BillListItem[] }>();
  visible.forEach(bill => {
    const preferred = bill.topics.find(item => tracking?.topics.some(follow => follow.topic.id === item.topic_id)) ?? bill.topics[0];
    const name = all ? "All legislation" : preferred?.name ?? "Other legislation";
    if (!groups.has(name)) groups.set(name, { id: preferred?.topic_id ?? 0, bills: [] });
    groups.get(name)!.bills.push(bill);
  });
  async function toggleFollow(bill: BillListItem) {
    if (!tracking || pending !== null) return;
    setPending(bill.id); setFollowError("");
    try {
      if (followed.has(bill.id)) { await untrackBill(bill.id); setTracking(previous => previous && ({ ...previous, bills: previous.bills.filter(item => item.bill.id !== bill.id) })); }
      else { const item = await trackBill(bill.id); setTracking(previous => previous && ({ ...previous, bills: [...previous.bills, item] })); }
    } catch { setFollowError("Your follow preference was not saved. Please try again."); }
    finally { setPending(null); }
  }
  const reset = () => { setQuery(""); setTopic(""); setSponsor(""); setState(""); setStatus(""); };
  return <div className={styles.deck}>
    <header className={styles.heading}>
      <div><h1>Your legislation, in view.</h1><p>Follow the bills that matter to you. Read what’s happening, and what changed.</p></div>
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
      <label>Representative (sponsor)<select aria-label="Representative (sponsor)" value={sponsor} onChange={event => setSponsor(event.target.value)}><option value="">All sponsors</option>{sponsors.map(name => <option key={name}>{name}</option>)}</select></label>
      <label>Sponsor state<select aria-label="Sponsor state" disabled={Boolean(repError)} value={state} onChange={event => setState(event.target.value)}><option value="">All states</option>{states.map(value => <option key={value}>{value}</option>)}</select></label>
      <label>Status<select aria-label="Status" value={status} onChange={event => setStatus(event.target.value)}><option value="">All statuses</option>{statuses.map(value => <option key={value} value={value}>{readable(value)}</option>)}</select></label>
    </div>
    <div className={styles.resultLine}><p role="status">{visible.length} {visible.length === 1 ? "bill" : "bills"} in view{all ? ` · ${bills.length} of ${total} loaded` : ""}</p><button onClick={reset}>Clear filters</button></div>
    {all && <p className={styles.note}>Filters apply to loaded bills. Load more to browse the full collection. State matches current sponsors in the representative directory; unlisted sponsors have no state metadata.</p>}
    {repError && <p className={styles.note}>{repError} <button onClick={() => setAttempt(value => value + 1)}>Retry directory</button></p>}
    {error && <div role="alert" className={styles.empty}>{error} <button onClick={() => setAttempt(value => value + 1)}>Retry</button></div>}
    {followError && <p role="alert">{followError}</p>}
    {!ready && !all && <p role="status" className={styles.empty}>Loading your followed bills…</p>}
    {ready && !all && !signedIn && !error && <div className={styles.empty}><h2>Start your collection</h2><p><Link href="/login">Log in</Link> to follow bills, or explore all bills above.</p></div>}
    {ready && !error && (all || signedIn) && !visible.length && !loading && <div className={styles.empty}><h2>{source.length ? "No bills match these filters" : all ? "No bills are loaded yet" : "Your collection starts with a bill"}</h2><p>{source.length ? "Clear a filter to see more legislation." : "Explore all bills and follow one to keep it here."}</p>{!all && !tracking?.topics.length && <p>Follow topics to organize your collection around your interests.</p>}</div>}
    {[...groups].map(([name, group]) => <section key={name} className={styles.topicSection}>
      <h2><span style={{ background: topicColor(group.id) }} aria-hidden="true" />{name}<small>{group.bills.length}</small></h2>
      <div className={layout === "grid" ? styles.grid : styles.list}>{group.bills.map(bill => <article key={bill.id} className={styles.card}>
        <div className={styles.bar} style={{ background: topicColor(bill.topics.find(item => tracking?.topics.some(follow => follow.topic.id === item.topic_id))?.topic_id ?? bill.topics[0]?.topic_id ?? 0) }} />
        <div className={styles.cardBody}>
          <div className={styles.cardMeta}><span>{bill.bill_number} / {bill.session}</span><span>{readable(bill.status || "Status unavailable")}</span></div>
          <h3><button onClick={() => setSelected(bill)}>{bill.title || "Untitled bill"}</button></h3>
          <p className={styles.cardTopics}>{bill.topics.map(item => item.name).join(", ") || "Topic not recorded"}</p>
          <p className={styles.sponsor}>{bill.sponsor_name || "Sponsor not recorded"}{stateBySponsor.get(bill.sponsor_name ?? "") ? ` (${stateBySponsor.get(bill.sponsor_name!)})` : ""}</p>
          <div className={styles.cardFooter}><span>Last action<br /><time>{dateLabel(bill.last_action_at)}</time></span>{signedIn && tracking ? <button disabled={pending !== null} aria-pressed={followed.has(bill.id)} onClick={() => void toggleFollow(bill)}>{pending === bill.id ? "Saving…" : followed.has(bill.id) ? "Unfollow" : "Follow"}</button> : error ? <span>Following unavailable</span> : !ready ? <span>Loading preferences…</span> : <Link href="/login">Log in to follow</Link>}</div>
        </div>
      </article>)}</div>
    </section>)}
    {catalogError && all && <p role="alert">{catalogError}</p>}
    {all && (more || catalogError) && <button className={styles.loadMore} disabled={loading} onClick={() => void loadPage()}>{loading ? "Loading bills…" : catalogError ? "Retry loading bills" : "Load more bills"}</button>}
    {selected && <BillDeckModal bill={selected} onClose={() => setSelected(null)} />}
  </div>;
}
