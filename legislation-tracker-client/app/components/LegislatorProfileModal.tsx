"use client";

import React from "react";
import type { BillListItem } from "@/lib/api";
import { getIntroducedBills, getLegislatorProfile, getRecordedVotes, profileHref, profileScopeKey, safeSourceUrl, type LivePage, type ProfileScope, type VotesPage, type VoteCoverage } from "@/lib/legislator-profile";
import type { Research } from "@/lib/representative-research";
import RepresentativeResearch from "./RepresentativeResearch";
import StackDialog from "./ModalStack";
import styles from "./legislator-profile.module.css";

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

function useLivePage<T extends LivePage<unknown>>(load: (page: number, signal: AbortSignal) => Promise<T>) {
  const [request, setRequest] = React.useState({ page: 1, attempt: 0 });
  const [state, setState] = React.useState<{ data: T | null; page: number; error: boolean; loading: boolean }>({ data: null, page: 1, error: false, loading: true });
  const busy = React.useRef(true);
  React.useEffect(() => {
    const controller = new AbortController(); let live = true; busy.current = true;
    setState(previous => ({ ...previous, loading: true, error: false }));
    void load(request.page, controller.signal).then(data => { if (live && !controller.signal.aborted) setState({ data, page: request.page, error: false, loading: false }); }).catch(() => { if (live && !controller.signal.aborted) setState(previous => ({ ...previous, error: true, loading: false })); }).finally(() => { if (live) busy.current = false; });
    return () => { live = false; controller.abort(); };
  }, [load, request]);
  const navigate = (page: number) => { if (!busy.current) { busy.current = true; setRequest(previous => ({ page, attempt: previous.attempt + 1 })); } };
  return { ...state, navigate, retry: () => navigate(request.page) };
}

function Source({ url, children }: { url: unknown; children: React.ReactNode }) {
  const safe = safeSourceUrl(url);
  return safe ? <a href={safe} target="_blank" rel="noopener noreferrer">{children}</a> : null;
}
function truncationNotice(notice: string) { return notice.match(/Only the first[^.]*\./)?.[0] ?? null; }
function date(value: string | null) { return value ? new Date(value).toLocaleString("en-US", { timeZone: "UTC", dateStyle: "medium", timeStyle: "short" }) + " UTC" : "Unavailable"; }
function PageControls({ data, page, loading, navigate }: { data: LivePage<unknown> | null; page: number; loading: boolean; navigate: (page: number) => void }) {
  return <nav className={styles.pagination} aria-label="Record pages"><button disabled={loading || !data?.previous} onClick={() => navigate(page - 1)}>Previous</button><span>Page {page}{data ? ` · ${data.count} stored records` : ""}</span><button disabled={loading || !data?.next} onClick={() => navigate(page + 1)}>Next</button><button disabled={loading} onClick={() => navigate(1)}>Refresh from first page</button></nav>;
}
function Coverage({ coverage }: { coverage: VoteCoverage }) {
  return <div className={styles.note}><p>{coverage.stored_record_count} stored member positions for Congress {coverage.scope.congress}{coverage.scope.chamber ? `, ${coverage.scope.chamber}` : ""}. Member position completeness is unknown.</p>{coverage.unknown_session_record_count > 0 && <p>{coverage.unknown_session_record_count} records have an unverified session.</p>}{coverage.provider_scopes.map(provider => <p key={provider.chamber}>{provider.description} <Source url={provider.source_url}>Source coverage</Source></p>)}<h4>Service-window ingestion checks</h4><p>{coverage.legacy_ingestion_check.coverage_complete ? "Stored checks passed" : "Stored checks incomplete"}. Discovered: {coverage.legacy_ingestion_check.discovered_count}; persisted: {coverage.legacy_ingestion_check.persisted_count}. Reason: {coverage.legacy_ingestion_check.reason || "Not recorded"}.</p>{coverage.legacy_ingestion_check.scopes.length ? <ul>{coverage.legacy_ingestion_check.scopes.map((item, index) => <li key={index}>{item.chamber} · Session {item.session_number} · Derived service window {date(item.start_at)}–{date(item.end_at)} · {item.full_session ? "Full derived session" : "Partial derived session"}</li>)}</ul> : <p>No derived service windows are available.</p>}<p>{coverage.legacy_ingestion_check.notice}</p></div>;
}
function BillLink({ bill, onOpenBill }: { bill: BillListItem; onOpenBill: (bill: BillListItem) => boolean }) {
  return <a href={`/bills/${bill.id}`} onClick={event => { if (event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && onOpenBill(bill)) event.preventDefault(); }}>{bill.title || bill.bill_number}</a>;
}
function IntroducedBills({ scope, onOpenBill }: { scope: ProfileScope; onOpenBill: (bill: BillListItem) => boolean }) {
  const load = React.useCallback((page: number, signal: AbortSignal) => getIntroducedBills(scope, page, signal), [scope]);
  const records = useLivePage(load);
  const [expanded, setExpanded] = React.useState(false);
  return <section className={styles.section}><h3>Bills introduced</h3><p className={styles.note}>Congress {scope.congress} · Available records</p>{records.loading && <p role="status">Loading introduced bills…</p>}{records.error && <p role="alert">Introduced bills could not be loaded. <button onClick={records.retry}>Retry introduced bills</button> Pages can change; refresh from the first page if a page no longer exists.</p>}{records.data && (!records.data.results.length ? <p>No primary-sponsored bills are stored for this Congress. Source coverage may be incomplete.</p> : <ul className={styles.records}>{(expanded ? records.data.results : records.data.results.slice(0, 5)).map(bill => <li key={bill.id}><span>{bill.bill_number}</span><BillLink bill={bill} onOpenBill={onOpenBill} /><small>{bill.introduced_at}</small></li>)}</ul>)}{records.data && (records.data.results.length > 5 || records.data.next || expanded) && <button aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? "Show fewer bills" : "Show more bills"}</button>}{expanded && <PageControls {...records} />}</section>;
}
function VotingRecord({ scope, onOpenBill }: { scope: ProfileScope; onOpenBill: (bill: BillListItem) => boolean }) {
  const load = React.useCallback((page: number, signal: AbortSignal) => getRecordedVotes(scope, page, signal), [scope]);
  const records = useLivePage<VotesPage>(load);
  const labels = { yes: "Yes", no: "No", present: "Present", not_voting: "Not voting", other: "Other" };
  return <section className={styles.section}><h3>Voting record</h3><p className={styles.note}>Real stored roll-call positions. Sponsorship and party do not establish a vote. Pages reflect live data and are replaced when you navigate.</p>{records.loading && <p role="status">Loading voting record…</p>}{records.error && <p role="alert">Voting records could not be loaded. <button onClick={records.retry}>Retry voting record</button> Refresh from the first page if a page no longer exists.</p>}{records.data && <><p className={styles.note}>{records.data.coverage.stored_record_count} stored member positions. Member position completeness is unknown.</p>{records.data.coverage.unknown_session_record_count > 0 && <p className={styles.note}>{records.data.coverage.unknown_session_record_count} records have an unverified session.</p>}{truncationNotice(records.data.coverage.legacy_ingestion_check.notice) && <p className={styles.note}>{truncationNotice(records.data.coverage.legacy_ingestion_check.notice)}</p>}<details className={styles.evidence}><summary>Voting sources, coverage and page freshness</summary><Coverage coverage={records.data.coverage} /><p className={styles.note}>Page read: {date(records.data.page_read_at)}</p></details>{!records.data.results.length ? <p>No member positions are stored in this scope. This does not establish that the legislator cast no votes.</p> : <ul className={styles.records}>{records.data.results.map(row => <li key={row.id}><strong>{(row.position === "other" || (row.position === "not_voting" && /^absent$/i.test(row.raw_position.trim()))) ? `${row.raw_position || "Unrecognized position"} (source wording)` : labels[row.position]}</strong><span>{row.question || "Question unavailable"}</span>{row.bill ? <BillLink bill={row.bill} onOpenBill={onOpenBill} /> : <span>Bill link unavailable</span>}<small>{date(row.vote_date)} · {row.chamber} · Roll call {row.roll_number} · Session {row.session_number ?? "unverified"}</small><Source url={row.source_url}>{row.source_link_kind === "session_list" ? "Official session vote list (specific roll call unverified)" : "Official roll call derived from stored identity"}</Source>{!safeSourceUrl(row.source_url) && <small>Source link unavailable</small>}</li>)}</ul>}</>}<PageControls {...records} /></section>;
}

export default function LegislatorProfileModal({ scope, onClose, onOpenBill, renderActivity }: { scope: ProfileScope; onClose: () => void; onOpenBill: (bill: BillListItem) => boolean; renderActivity?: (scope: ProfileScope) => React.ReactNode }) {
  const titleId = React.useId();
  const [portrait, setPortrait] = React.useState<Research["portrait"]>(null);
  const [failedPortrait, setFailedPortrait] = React.useState("");
  const profileLoad = React.useCallback((signal: AbortSignal) => getLegislatorProfile(scope, signal), [scope]);
  const profile = useResource(profileLoad);
  const [votesOpened, setVotesOpened] = React.useState(false), [showVotes, setShowVotes] = React.useState(false);
  const back = React.useRef<HTMLButtonElement>(null), show = React.useRef<HTMLButtonElement>(null);
  React.useEffect(() => { if (showVotes) back.current?.focus(); }, [showVotes]);
  const data = profile.data;
  return <StackDialog identity={`profile:${profileScopeKey(scope)}`} titleId={titleId} className={styles.dialog} onClose={onClose}>
    <header className={styles.header}><span className={styles.avatar}>{portrait && portrait.url !== failedPortrait ? <img src={portrait.url} alt={`${data?.identity.name || "Representative"} portrait`} onError={() => setFailedPortrait(portrait.url)} /> : <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="8" r="4" /><path d="M4 22v-3a8 8 0 0 1 16 0v3" /></svg>}</span><div><p>Congress {scope.congress}{scope.chamber ? ` · ${scope.chamber}` : ""}</p><h2 id={titleId}>{data?.identity.name || "Legislator profile"}</h2>{data && <small>{data.identity.latest_affiliation.chamber === "house" ? "House" : data.identity.latest_affiliation.chamber === "senate" ? "Senate" : data.identity.latest_affiliation.chamber} · {data.identity.latest_affiliation.state} · {({ D: "Democrat", R: "Republican", I: "Independent" } as Record<string, string>)[data.identity.latest_affiliation.party] || data.identity.latest_affiliation.party}{data.identity.latest_affiliation.district ? ` · District ${data.identity.latest_affiliation.district}` : ""}<span className={styles.affiliationLabel}>Latest affiliation</span></small>}</div><button autoFocus onClick={onClose} aria-label="Close legislator profile">Close ✕</button></header>
    <div hidden={showVotes}>
      {profile.loading && <p role="status">Loading legislator profile…</p>}{profile.error && <p role="alert">This legislator profile could not be loaded. <button onClick={profile.retry}>Retry profile</button></p>}
      <RepresentativeResearch representativeId={scope.representativeId} profileView onPortrait={setPortrait} />
      {renderActivity && <details className={styles.section}><summary>Topic activity ▾</summary>{renderActivity(scope)}</details>}<IntroducedBills scope={scope} onOpenBill={onOpenBill} />
      <button ref={show} onClick={() => { setVotesOpened(true); setShowVotes(true); }}>Show voting record</button>

    </div>
    {votesOpened && <div hidden={!showVotes}><button ref={back} onClick={() => { setShowVotes(false); queueMicrotask(() => show.current?.focus()); }}>Back to profile</button><VotingRecord scope={scope} onOpenBill={onOpenBill} /></div>}
    <footer className={styles.footer}><a href={profileHref(scope)}>Open full legislator page</a></footer>
  </StackDialog>;
}
