"use client";

import React from "react";
import type { BillListItem } from "@/lib/api";
import { getIntroducedBills, getLegislatorBiography, getLegislatorProfile, getRecordedVotes, profileHref, profileScopeKey, safeSourceUrl, type LivePage, type ProfileScope, type VotesPage, type VoteCoverage } from "@/lib/legislator-profile";
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
  return <section className={styles.section}><h3>Bills introduced</h3><p className={styles.note}>Primary sponsorship in the stored dataset, Congress {scope.congress}. Cosponsored bills are excluded. Historical ingestion may be incomplete.</p>{records.loading && <p role="status">Loading introduced bills…</p>}{records.error && <p role="alert">Introduced bills could not be loaded. <button onClick={records.retry}>Retry introduced bills</button> Pages can change; refresh from the first page if a page no longer exists.</p>}{records.data && (!records.data.results.length ? <p>No primary-sponsored bills are stored for this Congress. Source coverage may be incomplete.</p> : <ul className={styles.records}>{records.data.results.map(bill => <li key={bill.id}><span>{bill.bill_number}</span><BillLink bill={bill} onOpenBill={onOpenBill} /><small>Introduced: {bill.introduced_at || "Unavailable"} · {safeSourceUrl(bill.congress_gov_url) ? <Source url={bill.congress_gov_url}>Official bill page derived from stored identifier</Source> : "Official bill source link unavailable"}</small></li>)}</ul>)}<PageControls {...records} /></section>;
}
function VotingRecord({ scope, onOpenBill }: { scope: ProfileScope; onOpenBill: (bill: BillListItem) => boolean }) {
  const load = React.useCallback((page: number, signal: AbortSignal) => getRecordedVotes(scope, page, signal), [scope]);
  const records = useLivePage<VotesPage>(load);
  const labels = { yes: "Yes", no: "No", present: "Present", not_voting: "Not voting", other: "Other" };
  return <section className={styles.section}><h3>Voting record</h3><p className={styles.note}>Real stored roll-call positions. Sponsorship and party do not establish a vote. Pages reflect live data and are replaced when you navigate.</p>{records.loading && <p role="status">Loading voting record…</p>}{records.error && <p role="alert">Voting records could not be loaded. <button onClick={records.retry}>Retry voting record</button> Refresh from the first page if a page no longer exists.</p>}{records.data && <><Coverage coverage={records.data.coverage} /><p className={styles.note}>Page read: {date(records.data.page_read_at)}</p>{!records.data.results.length ? <p>No member positions are stored in this scope. This does not establish that the legislator cast no votes.</p> : <ul className={styles.records}>{records.data.results.map(row => <li key={row.id}><strong>{(row.position === "other" || (row.position === "not_voting" && /^absent$/i.test(row.raw_position.trim()))) ? `${row.raw_position || "Unrecognized position"} (source wording)` : labels[row.position]}</strong><span>{row.question || "Question unavailable"}</span>{row.bill ? <BillLink bill={row.bill} onOpenBill={onOpenBill} /> : <span>Bill link unavailable</span>}<small>{date(row.vote_date)} · {row.chamber} · Roll call {row.roll_number} · Session {row.session_number ?? "unverified"}</small><Source url={row.source_url}>{row.source_link_kind === "session_list" ? "Official session vote list (specific roll call unverified)" : "Official roll call derived from stored identity"}</Source>{!safeSourceUrl(row.source_url) && <small>Source link unavailable</small>}</li>)}</ul>}</>}<PageControls {...records} /></section>;
}

export default function LegislatorProfileModal({ scope, onClose, onOpenBill, renderActivity }: { scope: ProfileScope; onClose: () => void; onOpenBill: (bill: BillListItem) => boolean; renderActivity?: (scope: ProfileScope) => React.ReactNode }) {
  const titleId = React.useId();
  const profileLoad = React.useCallback((signal: AbortSignal) => getLegislatorProfile(scope, signal), [scope]);
  const bioLoad = React.useCallback((signal: AbortSignal) => getLegislatorBiography(scope, signal), [scope]);
  const profile = useResource(profileLoad), biography = useResource(bioLoad);
  const [votesOpened, setVotesOpened] = React.useState(false), [showVotes, setShowVotes] = React.useState(false);
  const back = React.useRef<HTMLButtonElement>(null), show = React.useRef<HTMLButtonElement>(null);
  React.useEffect(() => { if (showVotes) back.current?.focus(); }, [showVotes]);
  const data = profile.data, bio = biography.data;
  return <StackDialog identity={`profile:${profileScopeKey(scope)}`} titleId={titleId} className={styles.dialog} onClose={onClose}>
    <header className={styles.header}><span className={styles.avatar} aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="8" r="4" /><path d="M4 22v-3a8 8 0 0 1 16 0v3" /></svg></span><div><p>Congress {scope.congress}{scope.chamber ? ` · ${scope.chamber}` : ""}</p><h2 id={titleId}>{data?.identity.name || "Legislator profile"}</h2><small>Bioguide ID: {data?.identity.bioguide_id || "Loading"}</small></div><button autoFocus onClick={onClose} aria-label="Close legislator profile">Close ✕</button></header>
    <div hidden={showVotes}>
      {profile.loading && <p role="status">Loading legislator profile…</p>}{profile.error && <p role="alert">This legislator profile could not be loaded. <button onClick={profile.retry}>Retry profile</button></p>}
      {data && <><section className={styles.section}><h3>Latest stored affiliation</h3><p>{data.identity.latest_affiliation.chamber} · {data.identity.latest_affiliation.state} · {data.identity.latest_affiliation.party}{data.identity.latest_affiliation.district ? ` · District ${data.identity.latest_affiliation.district}` : ""}</p><p className={styles.note}>{data.identity.is_current ? "Listed as current in the stored directory." : "Historical legislator in the stored directory."} This affiliation is separate from the selected Congress. Last seen: {date(data.identity.last_seen_at)}. <Source url={data.identity.source_url}>Official Bioguide</Source></p></section><section className={styles.section}><h3>Service and elections</h3><p className={styles.note}>{data.service.notice}</p>{data.service.observations.length ? <ul>{data.service.observations.map(term => <li key={term.id}>{term.chamber} · {term.state || "State unavailable"}{term.district ? ` · District ${term.district}` : ""} · {term.start_year}–{term.end_year ?? "End year unavailable"} <Source url={term.source_url}>Bioguide</Source></li>)}</ul> : <p>Service history unavailable for this scope.</p>}{data.elections.map((election, index) => <div key={`${election.chamber}-${index}`}><p>{election.chamber ? `${election.chamber} elections` : "Elections"}</p><dl className={styles.facts}><div><dt>First elected</dt><dd>Unavailable</dd></div><div><dt>Most recent election won</dt><dd>Unavailable</dd></div><div><dt>Exact term start</dt><dd>Unavailable</dd></div></dl></div>)}<p className={styles.note}>Verified election dates are not connected. Stored service years do not establish election dates or exact term starts.</p></section><section className={styles.section}><h3>Top donors</h3><p>Verified campaign finance data is not connected.</p><p className={styles.note}>Top donors are unavailable. A reporting cycle, verified candidate committees, source records and a documented aggregation method are required.</p></section></>}
      <section className={styles.section}><h3>Biography</h3>{biography.loading && <p role="status">Loading Wikipedia excerpt…</p>}{biography.error && <p role="alert">The Wikipedia excerpt could not be loaded. <button onClick={biography.retry}>Retry biography</button></p>}{bio?.status === "unavailable" && <p>A verified Wikipedia excerpt is unavailable. <button onClick={biography.retry}>Retry biography</button></p>}{bio && bio.status !== "unavailable" && <><p>{bio.text}</p>{bio.status === "stale" && <p className={styles.note}>Cached excerpt; the source could not be refreshed.</p>}<p className={styles.note}><Source url={bio.page_url}>Wikipedia article</Source> · {bio.attribution} · <Source url={bio.license_url}>{bio.license}</Source> · Introductory excerpt limited by the source{bio.shortened && " and shortened locally"}</p><p className={styles.note}>Excerpt fetched: {date(bio.fetched_at)}. <Source url={bio.observed_revision_url}>Article revision observed</Source>: {date(bio.observed_revision_at)}. The extract API does not pin text to this revision.</p></>}</section>
      <IntroducedBills scope={scope} onOpenBill={onOpenBill} />{renderActivity?.(scope)}{data && <details className={styles.section}><summary>Stored voting coverage and service-window checks</summary><Coverage coverage={data.coverage} /></details>}
      <button ref={show} onClick={() => { setVotesOpened(true); setShowVotes(true); }}>Show voting record</button>
    </div>
    {votesOpened && <div hidden={!showVotes}><button ref={back} onClick={() => { setShowVotes(false); queueMicrotask(() => show.current?.focus()); }}>Back to profile</button><VotingRecord scope={scope} onOpenBill={onOpenBill} /></div>}
    <footer className={styles.footer}><a href={profileHref(scope)}>Open full legislator page</a></footer>
  </StackDialog>;
}
