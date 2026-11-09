"use client";

import React from "react";
import type { BillListItem } from "@/lib/api";
import { getIntroducedBills, getLegislatorProfile, getVoteSummary, profileHref, profileScopeKey, type ProfileScope } from "@/lib/legislator-profile";
import { getRepresentativeTopicActivity } from "@/lib/recommendations";
import { topRepresentativeTopics } from "@/lib/representative-card";
import CardTooltip from "./CardTooltip";
import type { Research } from "@/lib/representative-research";
import RepresentativeResearch from "./RepresentativeResearch";
import BillCard from "./BillCard";
import deckStyles from "./bill-deck.module.css";
import StackDialog from "./ModalStack";
import styles from "./legislator-profile.module.css";
import { representativeTabKey } from "@/lib/use-url-tab";

function useResource<T>(load: (signal: AbortSignal) => Promise<T>) {
  const [state, setState] = React.useState<{ data: T | null; error: boolean; loading: boolean }>({ data: null, error: false, loading: true });
  const [attempt, retry] = React.useReducer(value => value + 1, 0);
  React.useEffect(() => {
    const controller = new AbortController(); let live = true;
    setState({ data: null, error: false, loading: true });
    void load(controller.signal).then(data => { if (live && !controller.signal.aborted) setState({ data, loading: false, error: false }); }).catch(() => { if (live && !controller.signal.aborted) setState({ data: null, loading: false, error: true }); });
    return () => { live = false; controller.abort(); };
  }, [load, attempt]);
  return { ...state, retry };
}

function IntroducedBills({ scope, onOpenBill }: { scope: ProfileScope; onOpenBill: (bill: BillListItem) => boolean }) {
  const [bills, setBills] = React.useState<BillListItem[]>([]);
  const [request, setRequest] = React.useState({ page: 1, attempt: 0 });
  const [hasNext, setHasNext] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(false);
  const busy = React.useRef(true);
  const row = React.useRef<HTMLDivElement>(null);
  const end = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const controller = new AbortController();
    busy.current = true; setLoading(true); setError(false);
    void getIntroducedBills(scope, request.page, controller.signal).then(data => {
      if (controller.signal.aborted) return;
      setBills(previous => [...new Map([...previous, ...data.results].map(bill => [bill.id, bill])).values()]);
      setHasNext(Boolean(data.next));
    }).catch(() => { if (!controller.signal.aborted) setError(true); }).finally(() => {
      if (!controller.signal.aborted) { busy.current = false; setLoading(false); }
    });
    return () => controller.abort();
  }, [scope, request]);
  const loadNext = React.useCallback(() => {
    if (busy.current || loading || error || !hasNext) return;
    busy.current = true;
    setRequest(previous => ({ page: previous.page + 1, attempt: 0 }));
  }, [loading, error, hasNext]);
  React.useEffect(() => {
    if (!row.current || !end.current || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) loadNext();
    }, { root: row.current, rootMargin: "0px 300px 0px 0px" });
    observer.observe(end.current);
    return () => observer.disconnect();
  }, [loadNext]);
  return <section className={styles.section}><h3>Bills introduced</h3>
    {!loading && !error && !bills.length && <p>No bills introduced are available for this Congress.</p>}
    <div ref={row} className={`${deckStyles.followedRow} ${styles.billRow}`} role="region" aria-label="Bills introduced" tabIndex={0} onScroll={event => {
      const element = event.currentTarget;
      if (element.scrollWidth - element.clientWidth - element.scrollLeft < 300) loadNext();
    }}>
      {bills.map(bill => <BillCard key={bill.id} bill={bill} onOpen={() => { if (!onOpenBill(bill)) window.location.assign(`/bills/${bill.id}`); }} footer={null} />)}
      <div ref={end} className={styles.billSentinel} aria-hidden="true" />
    </div>
    {loading && <p role="status">{bills.length ? "Loading more bills…" : "Loading introduced bills…"}</p>}
    {error && <p role="alert">Could not load {bills.length ? "more bills" : "bills"}. <button onClick={() => {
      if (busy.current) return;
      busy.current = true; setRequest(previous => ({ ...previous, attempt: previous.attempt + 1 }));
    }}>Retry introduced bills</button></p>}
  </section>;
}
export function VotingRecord({ scope, fullPage = false }: { scope: ProfileScope; fullPage?: boolean }) {
  const load = React.useCallback((signal: AbortSignal) => getVoteSummary(scope, signal), [scope]);
  const records = useResource(load);
  return <section className={styles.section}>
    <div className={styles.voteHeading}><h3>Votes by topic</h3>{!fullPage && <a href={`${profileHref(scope)}&tab=votes`}>Full voting record ↗</a>}</div>
    <p className={styles.note}><CardTooltip text="Stored roll calls, including procedural votes. A vote counts under each topic assigned to its bill, so topic counts can overlap. These totals do not imply support for every policy in a topic."><span tabIndex={0}>Congress {scope.congress} · Recorded votes ⓘ</span></CardTooltip></p>
    {records.loading && <p role="status">Loading votes…</p>}
    {records.error && <p role="alert">Could not load votes. <button onClick={records.retry}>Retry votes</button></p>}
    {records.data && <>
      <div className={styles.voteGroups}>{(["yes", "no"] as const).map(position => <section key={position} aria-label={position === "yes" ? "Yes votes" : "No votes"}>
        <h4>{position === "yes" ? "Yes" : "No"} <strong>{records.data!.totals[position]}</strong></h4>
        <ul>{records.data!.topics.filter(topic => topic[position] > 0).sort((a, b) => b[position] - a[position] || a.name.localeCompare(b.name)).map(topic => <li key={topic.id ?? "unassigned"}><span>{topic.name}</span><strong>{topic[position]}</strong></li>)}</ul>
        {!records.data!.totals[position] && <p className={styles.note}>No recorded {position} votes.</p>}
      </section>)}</div>
    </>}
  </section>;
}

export default function LegislatorProfileModal({ scope, onClose, onOpenBill }: { scope: ProfileScope; onClose: () => void; onOpenBill: (bill: BillListItem) => boolean; renderActivity?: (scope: ProfileScope) => React.ReactNode }) {
  const titleId = React.useId();
  const [research, setResearch] = React.useState<Research | null>(null);
  const [failedPortrait, setFailedPortrait] = React.useState("");
  const profileLoad = React.useCallback((signal: AbortSignal) => getLegislatorProfile(scope, signal), [scope]);
  const activityLoad = React.useCallback((signal: AbortSignal) => getRepresentativeTopicActivity(scope.representativeId, { signal }), [scope.representativeId]);
  const profile = useResource(profileLoad);
  const activity = useResource(activityLoad);
  const [tab, setTab] = React.useState("Bills");
  const [opened, setOpened] = React.useState<string[]>(["Bills"]);
  const tabs = ["Bills", "Votes", "Campaign funding"];
  const selectTab = (name: string) => { setTab(name); setOpened(previous => previous.includes(name) ? previous : [...previous, name]); };
  const data = profile.data;
  const portrait = research?.portrait;
  const name = data?.identity.name || "Legislator profile";
  const displayName = name.replace(/^(Rep\.|Sen\.)\s*/, "").replace(/\s*\[.*\]$/, "").replace(/^([^,]+),\s*(.+)$/, "$2 $1");
  const topics = topRepresentativeTopics(activity.data?.channels ? activity.data : null);
  return <StackDialog identity={`profile:${profileScopeKey(scope)}`} titleId={titleId} className={styles.dialog} onClose={onClose}>
    <header className={styles.header}>
      <span className={styles.avatar}>{portrait && portrait.url !== failedPortrait ? <img src={portrait.url} alt={`${name} portrait`} onError={() => setFailedPortrait(portrait.url)} /> : <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="8" r="4" /><path d="M4 22v-3a8 8 0 0 1 16 0v3" /></svg>}</span>
      <div className={styles.headerIdentity}><h2 id={titleId}><CardTooltip text="Open the full representative page"><a href={`${profileHref(scope)}&tab=${representativeTabKey(tab)}`}>{displayName}<span aria-hidden="true"> ↗</span></a></CardTooltip></h2>
      {data && <small>{data.identity.latest_affiliation.chamber === "house" ? "House" : data.identity.latest_affiliation.chamber === "senate" ? "Senate" : data.identity.latest_affiliation.chamber} · {data.identity.latest_affiliation.state} · {({ D: "Democrat", R: "Republican", I: "Independent" } as Record<string, string>)[data.identity.latest_affiliation.party] || data.identity.latest_affiliation.party}{data.identity.latest_affiliation.district ? ` · District ${data.identity.latest_affiliation.district}` : ""}</small>}</div>
      <button autoFocus onClick={onClose} aria-label="Close legislator profile">✕</button>
    </header>
    {profile.loading && <p role="status">Loading profile…</p>}
    {profile.error && <p role="alert">Could not load this profile. <button onClick={profile.retry}>Retry profile</button></p>}
    {research?.biography && <p className={styles.biography}>{research.biography.text}</p>}
    <div className={styles.profileTools}>
      <div className={styles.topics}>{topics.map(topic => <a key={topic.id} href={`/bills?topic_id=${topic.id}`}>{topic.name}</a>)}{activity.error && <button onClick={activity.retry}>Retry topics</button>}</div>
      <RepresentativeResearch representativeId={scope.representativeId} cardName={name} onResearch={setResearch} />
    </div>
    <div className={styles.tabs} role="tablist" aria-label="Representative information">{tabs.map((name, index) => <button key={name} id={`${titleId}-tab-${index}`} role="tab" aria-selected={tab === name} aria-controls={`${titleId}-panel-${index}`} tabIndex={tab === name ? 0 : -1} onClick={() => selectTab(name)} onKeyDown={event => {
      const next = event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
      if (next !== null) { event.preventDefault(); selectTab(tabs[next]); document.getElementById(`${titleId}-tab-${next}`)?.focus(); }
    }}>{name}</button>)}</div>
    {tabs.map((name, index) => opened.includes(name) && <div key={name} role="tabpanel" className={name === "Campaign funding" ? styles.fundingPanel : undefined} id={`${titleId}-panel-${index}`} aria-labelledby={`${titleId}-tab-${index}`} hidden={tab !== name}>
      {name === "Bills" ? <IntroducedBills scope={scope} onOpenBill={onOpenBill} /> : name === "Votes" ? <VotingRecord scope={scope} /> : <RepresentativeResearch representativeId={scope.representativeId} financeView modalView />}
    </div>)}
  </StackDialog>;
}
