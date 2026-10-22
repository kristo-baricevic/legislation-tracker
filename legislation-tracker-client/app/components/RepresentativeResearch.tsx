"use client";
import React, { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { getResearch, startResearch, getContributors, getConnections, getFinanceHistory, type FinanceHistory, type Research, type Contributors, type Connections } from "@/lib/representative-research";
import styles from "./representative-research.module.css";

const reasons: Record<string, string> = {
  missing_fec_key: "Campaign finance research needs the server's FEC API key. Biography and photo research can still run.",
  candidate_identity_requires_verification: "The campaign identity needs verification before donor records can be attached.",
  itemized_receipts_only: "These are reported itemized contributions and refunds, not a complete accounting of campaign funding. Net funding is not shown because the records are not fully reconciled.",
  biography_source_unavailable: "The biography source could not be reached; previously saved information is retained.",
  member_source_unavailable: "Congress.gov could not be reached; saved member information is retained.",
};
function SourceLink({ url, children }: { url: string; children: React.ReactNode }) {
  return /^https:\/\//.test(url) ? <a href={url} target="_blank" rel="noreferrer">{children}</a> : <span>{children}</span>;
}

export default function RepresentativeResearch({ representativeId, compact = false }: { representativeId: number; compact?: boolean }) {
  return <ResearchPanel key={representativeId} representativeId={representativeId} compact={compact} />;
}

function ResearchPanel({ representativeId, compact }: { representativeId: number; compact: boolean }) {
  const year = new Date().getFullYear();
  const [period, setPeriod] = useState(year + year % 2);
  const [data, setData] = useState<Research | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [expanded, setExpanded] = useState(!compact);
  const [showConnections, setShowConnections] = useState(false);
  const action = useRef<AbortController | null>(null);
  const active = data?.status === "queued" || data?.status === "running";
  useEffect(() => () => action.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const result = await getResearch(representativeId, period, controller.signal);
        if (controller.signal.aborted) return;
        setData(result);
        if (["queued", "running"].includes(result.status)) timer = setTimeout(load, 2500);
      } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Research could not be loaded."); }
    };
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [representativeId, period, reload]);
  async function research() {
    if (busy || active) return;
    const controller = new AbortController();
    action.current = controller;
    setBusy(true); setError("");
    try {
      const run = await startResearch(representativeId, period, controller.signal);
      if (controller.signal.aborted) return;
      setData(old => ({ ...(old ?? { biography: null, portrait: null, snapshot: null }), period, status: run.status, run }));
      setReload(n => n + 1);
    } catch (e) {
      if (!controller.signal.aborted) setError(e instanceof ApiError && [401, 403].includes(e.status) ? "Sign in to research this representative." : e instanceof Error ? e.message : "Research could not start. Try again.");
    } finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <section className={styles.panel} aria-label="Representative research">
    <div className={styles.controls}>
      <button type="button" className={styles.primary} disabled={busy || active} onClick={() => void research()}>{busy || active ? "Researching…" : data?.biography || data?.snapshot ? "Refresh research" : "Research"}</button>
      {compact && <button type="button" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? "Hide research" : "View research"}</button>}
      {!compact && <label>Reporting period <select aria-label="Reporting period" value={period} disabled={busy} onChange={e => { action.current?.abort(); setData(null); setError(""); setPeriod(Number(e.target.value)); }}>{Array.from({ length: (year + year % 2 - 1980) / 2 + 1 }, (_, i) => year + year % 2 - 2 * i).map(value => <option key={value} value={value}>{value - 1}–{value}</option>)}</select></label>}
    </div>
    {error && <p role="alert">{error} <button type="button" onClick={() => { setError(""); setReload(n => n + 1); }}>Retry status</button></p>}
    {data?.run?.error && <p role="alert">{data.run.error} Saved information is unchanged.</p>}
    {active && <p role="status">Research continues in the background. You can leave this page.</p>}
    {expanded && <>
      {data?.run && <div className={styles.progress}>{Object.entries(data.run.sections).map(([name, section]) => <span key={name}>{name === "finance" ? "Campaign finance" : name === "photo" ? "Photo" : "Biography"}: {section.status.replaceAll("_", " ")}</span>)}</div>}
      <div className={styles.bio}>
        {data?.portrait && <img src={data.portrait.url} alt="Official representative portrait" width={88} height={110} onError={e => { e.currentTarget.hidden = true; }} />}
        <div>{data?.biography ? <><h3>About this representative</h3><p>{data.biography.text}</p><small><SourceLink url={data.biography.source.url}>{data.biography.source.attribution || "Biography source"}</SourceLink>{data.biography.source.license && ` · ${data.biography.source.license}`} · Last researched {new Date(data.biography.source.fetched_at).toLocaleDateString()}</small></> : <p>{data ? "Not researched yet. Research gathers a biography, photo and campaign finance records." : "Loading saved research…"}</p>}{data?.portrait && <small><SourceLink url={data.portrait.source.url}>{data.portrait.source.attribution || "Photo source"}</SourceLink></small>}</div>
      </div>
      {data?.run && Object.entries(data.run.sections).map(([name, section]) => section.reason && reasons[section.reason] ? <p className={styles.note} key={name}>{reasons[section.reason]}</p> : null)}
      {data?.snapshot && <ContributorTable key={`${period}:${data.snapshot}`} representativeId={representativeId} period={period} snapshot={data.snapshot} />}
      <button type="button" aria-expanded={showConnections} onClick={() => setShowConnections(value => !value)}>{showConnections ? "Hide connections ▴" : "Explore connections ▾"}</button>
      {showConnections && <ConnectionList key={period} representativeId={representativeId} period={period} />}
    </>}
  </section>;
}

function ContributorTable({ representativeId, period, snapshot }: { representativeId: number; period: number; snapshot: string }) {
  const [data, setData] = useState<Contributors | null>(null), [error, setError] = useState("");
  const [cursor, setCursor] = useState(0), [sort, setSort] = useState("amount"), [retry, setRetry] = useState(0);
  const [kind, setKind] = useState("contribution");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError("");
    void getContributors(representativeId, period, snapshot, cursor, sort, controller.signal, kind).then(value => { if (!controller.signal.aborted) setData(value); }).catch(() => { if (!controller.signal.aborted) setError("Contributor records could not be loaded."); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [representativeId, period, snapshot, cursor, sort, retry, kind]);
  return <section><div className={styles.controls}><h3>Campaign contributors</h3><label>Sort <select value={sort} onChange={e => { setSort(e.target.value); setCursor(0); }}><option value="amount">Amount</option><option value="date">Date</option><option value="name">Name</option></select></label></div>
    <label>Record type <select value={kind} onChange={e => { setKind(e.target.value); setCursor(0); setData(null); }}><option value="contribution">Contributions</option><option value="refund">Refunds</option></select></label>
    {error && <p role="alert">{error} <button onClick={() => setRetry(n => n + 1)}>Retry contributors</button></p>}
    {loading && <p role="status">Loading contributors…</p>}
    {data && <>{!data.individuals_visible && <p className={styles.note}>Committee contributors only. Individual contributor publication has not been enabled.</p>}<p className={styles.note}>{data.count} reported {kind === "refund" ? "refunds" : "contributions"} in this view. Coverage: {data.status}. Contributions are not the same as total campaign receipts.</p>
      <div className={styles.table}><table><thead><tr><th>{kind === "refund" ? "Refund recipient" : "Contributor"}</th><th>Amount</th><th>Campaign committee</th><th>Date</th><th>Evidence</th></tr></thead><tbody>{data.results.map(row => <tr key={row.id}><td>{row.name}<small>{row.type}</small></td><td>{new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(row.amount))}</td><td>{row.committee}</td><td>{row.date || "Not reported"}</td><td><SourceLink url={row.source_url}>FEC record</SourceLink></td></tr>)}</tbody></table></div>{!data.results.length && <p>No publishable contributor records were found in this scope. This does not mean the campaign received no contributions.</p>}
      <nav className={styles.controls} aria-label="Contributor pages"><button disabled={loading || cursor === 0} onClick={() => setCursor(Math.max(0, cursor - 20))}>Prev</button><button disabled={loading || data.next_cursor === null} onClick={() => setCursor(data.next_cursor!)}>Next</button></nav></>}
  </section>;
}

function ConnectionList({ representativeId, period }: { representativeId: number; period: number }) {
  const [data, setData] = useState<Connections | null>(null), [error, setError] = useState("");
  const [cursor, setCursor] = useState(0), [retry, setRetry] = useState(0);
  const [selectedDonor, setSelectedDonor] = useState<number>();
  const [donorCursor, setDonorCursor] = useState(0);
  const [relatedCursor, setRelatedCursor] = useState(0);
  const [history, setHistory] = useState<FinanceHistory | null>(null);
  const [historyCursor, setHistoryCursor] = useState(0);
  const [historyError, setHistoryError] = useState("");
  const [snapshot, setSnapshot] = useState("");
  const [start, setStart] = useState(`${period - 1}-01-01`);
  const [end, setEnd] = useState(`${period}-12-31`);
  const [dates, setDates] = useState({ legislative_start: start, legislative_end: end });
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    setHistoryError("");
    void getFinanceHistory(representativeId, period, historyCursor, controller.signal).then(value => {
      if (!controller.signal.aborted) setHistory(old => ({ ...value, results: historyCursor ? [...(old?.results ?? []), ...value.results.filter(row => !old?.results.some(existing => existing.id === row.id))] : value.results }));
    }).catch(() => { if (!controller.signal.aborted) setHistoryError("Snapshot history could not be loaded."); });
    return () => controller.abort();
  }, [representativeId, period, historyCursor, retry]);
  useEffect(() => {
    const controller = new AbortController(); setError(""); setData(null); setLoading(true);
    void getConnections(representativeId, period, cursor, controller.signal, selectedDonor, donorCursor, relatedCursor, { snapshot, ...dates }).then(value => { if (!controller.signal.aborted) setData(value); }).catch(() => { if (!controller.signal.aborted) setError("Connections could not be loaded."); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [representativeId, period, cursor, retry, selectedDonor, donorCursor, relatedCursor, snapshot, dates]);
  return <section><h3>Connected legislative activity</h3><div className={styles.controls}><label>Finance snapshot <select value={snapshot} onChange={e => { setSnapshot(e.target.value); setCursor(0); setDonorCursor(0); setRelatedCursor(0); setSelectedDonor(undefined); }}><option value="">Latest research</option>{history?.results.map(row => <option key={row.id} value={row.id}>{new Date(row.published_at).toLocaleString()} · {row.coverage}</option>)}</select></label>{history?.next_cursor != null && <button onClick={() => setHistoryCursor(history.next_cursor!)}>Load older snapshots</button>}</div>{historyError && <p role="alert">{historyError} <button onClick={() => setRetry(n => n + 1)}>Retry history</button></p>}<form className={styles.controls} onSubmit={e => { e.preventDefault(); if (start && end && start <= end) { setDates({ legislative_start: start, legislative_end: end }); setCursor(0); } }}><label>Legislative start <input type="date" required value={start} max={end} onChange={e => setStart(e.target.value)} /></label><label>Legislative end <input type="date" required value={end} min={start} onChange={e => setEnd(e.target.value)} /></label><button type="submit">Apply dates</button></form>{loading && <p role="status">Loading connections…</p>}<p className={styles.note}>Reported contributors → campaign → representative → bills → topics</p>{error && <p role="alert">{error} <button onClick={() => setRetry(n => n + 1)}>Retry connections</button></p>}{data && <><p>{data.notice}</p><p className={styles.note}>Legislative window: {dates.legislative_start}–{dates.legislative_end}. Finance period: {period - 1}–{period}. Finance coverage: {data.finance_status}.</p><div className={styles.web}><section><h4>Reported committee contributors</h4>{data.donors.map(donor => <div key={donor.id}><button aria-pressed={selectedDonor === donor.id} onClick={() => { setSelectedDonor(donor.id); setRelatedCursor(0); setData(null); }}>{donor.name}</button><p>{new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(donor.amount))} in observed contributions</p><SourceLink url={donor.source_url}>Contribution evidence</SourceLink></div>)}{!data.donors.length && <p>No verified committee connections are available yet.</p>}<nav><button disabled={donorCursor === 0} onClick={() => setDonorCursor(Math.max(0, donorCursor - 20))}>Prev donors</button><button disabled={data.next_donor_cursor === null} onClick={() => setDonorCursor(data.next_donor_cursor!)}>Next donors</button></nav></section><section><h4>Connected representatives</h4>{selectedDonor ? data.related_representatives.map(rep => <p key={rep.id}><a href={`/representatives/${rep.id}`}>{rep.name}</a> <SourceLink url={rep.source_url}>Campaign contribution evidence</SourceLink></p>) : <p>Select a contributor to see other researched representatives whose campaigns received contributions.</p>}<nav><button disabled={relatedCursor === 0} onClick={() => setRelatedCursor(Math.max(0, relatedCursor - 20))}>Prev representatives</button><button disabled={data.next_related_cursor === null} onClick={() => setRelatedCursor(data.next_related_cursor!)}>Next representatives</button></nav><p className={styles.note}>Only published research is shown; missing connections do not establish an absence of funding.</p></section></div><ul className={styles.connections}>{data.bills.map(bill => <li key={bill.id}><span>{bill.relations.join(", ")}</span><a href={`/bills/${bill.id}`}>{bill.number}: {bill.title}</a><div>{bill.votes.map(vote => <p key={vote.vote_id}>{vote.question}: {vote.position} <SourceLink url={vote.source_url}>Recorded vote</SourceLink></p>)}</div><div>{bill.topics.map(topic => <a className={styles.pill} key={topic.id} href={`/bills?topic_id=${topic.id}`}>{topic.name}</a>)}</div></li>)}</ul>{!data.bills.length && <p>No linked bills are stored for this period.</p>}<nav className={styles.controls}><button disabled={cursor === 0} onClick={() => setCursor(Math.max(0, cursor - 10))}>Prev</button><button disabled={data.next_cursor === null} onClick={() => setCursor(data.next_cursor!)}>Next</button></nav></>}</section>;
}
