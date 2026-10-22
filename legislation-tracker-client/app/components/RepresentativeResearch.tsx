"use client";
import React, { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { getResearch, startResearch, getContributors, type Research, type Contributors, type FinanceProgress } from "@/lib/representative-research";
import styles from "./representative-research.module.css";
import ContributorExplorer from "./ContributorExplorer";

const reasons: Record<string, string> = {
  missing_fec_key: "Campaign finance research needs the server's FEC API key. Biography and photo research can still run.",
  candidate_not_found: "No matching FEC candidate was found. Retry research or have the candidate identity checked.",
  candidate_identity_requires_verification: "The campaign identity needs verification before donor records can be attached.",
  itemized_receipts_only: "These are reported itemized contributions and refunds, not a complete accounting of campaign funding. Net funding is not shown because the records are not fully reconciled.",
  biography_source_unavailable: "The biography source could not be reached; previously saved information is retained.",
  member_source_unavailable: "Congress.gov could not be reached; saved member information is retained.",
};
function SourceLink({ url, children }: { url: string; children: React.ReactNode }) {
  return /^https:\/\//.test(url) ? <a href={url} target="_blank" rel="noreferrer">{children}</a> : <span>{children}</span>;
}

type ResearchProps = { representativeId: number; compact?: boolean; profileView?: boolean; onPortrait?: (portrait: Research["portrait"]) => void };
export default function RepresentativeResearch({ representativeId, compact = false, ...props }: ResearchProps) {
  return <ResearchPanel key={representativeId} representativeId={representativeId} compact={compact} {...props} />;
}

function ResearchPanel({ representativeId, compact, profileView = false, onPortrait }: ResearchProps) {
  const year = new Date().getFullYear();
  const [period, setPeriod] = useState(year + year % 2);
  const [data, setData] = useState<Research | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [expanded, setExpanded] = useState(!compact);
  const [showConnections, setShowConnections] = useState(false);
  const action = useRef<AbortController | null>(null);
  useEffect(() => { onPortrait?.(data?.portrait ?? null); }, [data?.portrait, onPortrait]);
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
    {active && <p role="status">{profileView ? "Collecting campaign records…" : data?.finance_progress ? `${data.finance_progress.totals_loaded ? "Campaign totals loaded" : "Loading campaign totals"} · ${data.finance_progress.pages_loaded} pages loaded · ${data.finance_progress.streams_completed} of ${data.finance_progress.streams_total} record groups finished. Collection continues in the background.` : "Finding campaign records…"}</p>}
    {expanded && <>
      {!profileView && data?.run && <div className={styles.progress}>{Object.entries(data.run.sections).map(([name, section]) => <span key={name}>{name === "finance" ? "Campaign finance" : name === "photo" ? "Photo" : "Biography"}: {section.status.replaceAll("_", " ")}</span>)}</div>}
      <div className={styles.bio}>
        {!profileView && data?.portrait && <img src={data.portrait.url} alt="Official representative portrait" width={88} height={110} onError={e => { e.currentTarget.hidden = true; }} />}
        <div>{data?.biography && !(profileView && data.biography.kind === "official_service_facts") ? <><h3>About this representative</h3><p>{data.biography.text}</p><small><SourceLink url={data.biography.source.url}>{data.biography.source.attribution || "Biography source"}</SourceLink>{data.biography.source.license && ` · ${data.biography.source.license}`}{!profileView && <> · Last researched {new Date(data.biography.source.fetched_at).toLocaleDateString()}</>}</small></> : profileView ? null : <p>{data ? "Not researched yet. Research gathers a biography, photo and campaign finance records." : "Loading saved research…"}</p>}{data?.portrait && <small><SourceLink url={data.portrait.source.url}>{data.portrait.source.attribution || "Photo source"}</SourceLink></small>}</div>
      </div>
      {data?.run && Object.entries(data.run.sections).map(([name, section]) => section.reason && reasons[section.reason] ? profileView ? name === "finance" && section.reason !== "itemized_receipts_only" ? <p className={styles.note} key={name}>Campaign funding unavailable — {section.reason === "candidate_not_found" ? "no matching campaign found." : "research needs attention."}</p> : null : <p className={styles.note} key={name}>{reasons[section.reason]}</p> : null)}
      {data?.finance_progress && <CampaignTotals progress={data.finance_progress} />}
      {data?.snapshot && <details open={profileView ? undefined : true}><summary>Contributions ▾</summary><ContributorTable refreshToken={`${data.finance_progress?.pages_loaded ?? 0}:${active}`}  key={`${period}:${data.snapshot}`} representativeId={representativeId} period={period} snapshot={data.snapshot} /></details>}
      {(!profileView || data?.snapshot) && <button type="button" aria-expanded={showConnections} onClick={() => setShowConnections(value => !value)}>{showConnections ? "Hide connections ▴" : "Explore connections ▾"}</button>}
      {showConnections && <ContributorExplorer refreshToken={`${data?.finance_progress?.pages_loaded ?? 0}:${active}`} key={`connections:${period}:${data?.snapshot ?? "none"}`} representativeId={representativeId} period={period} />}
    </>}
  </section>;
}

function ContributorTable({ representativeId, period, snapshot, refreshToken }: { representativeId: number; period: number; snapshot: string; refreshToken: string }) {
  const [data, setData] = useState<Contributors | null>(null), [error, setError] = useState("");
  const [cursor, setCursor] = useState(0), [sort, setSort] = useState("amount"), [retry, setRetry] = useState(0);
  const [kind, setKind] = useState("contribution");
  const [loading, setLoading] = useState(true);
  const loadedScope = useRef("");
  useEffect(() => {
    const controller = new AbortController();
    const scope = JSON.stringify([representativeId, period, snapshot, cursor, sort, kind]);
    setLoading(loadedScope.current !== scope); setError("");
    void getContributors(representativeId, period, snapshot, cursor, sort, controller.signal, kind).then(value => { if (!controller.signal.aborted) { loadedScope.current = scope; setData(value); } }).catch(() => { if (!controller.signal.aborted) setError("Contributor records could not be loaded."); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [representativeId, period, snapshot, cursor, sort, retry, kind, refreshToken]);
  return <section><div className={styles.controls}><h3>Campaign contributors</h3><label>Sort <select value={sort} onChange={e => { setSort(e.target.value); setCursor(0); }}><option value="amount">Amount</option><option value="date">Date</option><option value="name">Name</option></select></label></div>
    <label>Record type <select value={kind} onChange={e => { setKind(e.target.value); setCursor(0); setData(null); }}><option value="contribution">Contributions</option><option value="refund">Refunds</option></select></label>
    {error && <p role="alert">{error} <button onClick={() => setRetry(n => n + 1)}>Retry contributors</button></p>}
    {loading && <p role="status">Loading contributors…</p>}
    {data && <>{data.status === "collecting" && <p className={styles.note}>Partial results — records are still being collected. Amounts and rankings may change.</p>}<p className={styles.note}>{data.count} reported {kind === "refund" ? "refunds" : "contributions"} in this view. Coverage: {data.status}. Contributions are not the same as total campaign receipts.</p>
      <div className={styles.table}><table><thead><tr><th>{kind === "refund" ? "Refund recipient" : "Contributor"}</th><th>Amount</th><th>Campaign committee</th><th>Date</th><th>Evidence</th></tr></thead><tbody>{data.results.map(row => <tr key={row.id}><td>{row.name}<small>{row.type}</small></td><td>{new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(row.amount))}</td><td>{row.committee}</td><td>{row.date || "Not reported"}</td><td><SourceLink url={row.source_url}>FEC record</SourceLink></td></tr>)}</tbody></table></div>{!data.results.length && <p>{data.status === "collecting" ? "No contributor records loaded yet. Collection is still running." : "No publishable contributor records were found in this scope. This does not mean the campaign received no contributions."}</p>}
      <nav className={styles.controls} aria-label="Contributor pages"><span>{data.count ? `${cursor + 1}–${Math.min(cursor + data.results.length, data.count)} of ${data.count} records` : "0 records"}</span>{(cursor > 0 || data.next_cursor !== null) && <><button disabled={loading || cursor === 0} onClick={() => setCursor(Math.max(0, cursor - 20))}>Prev</button><button disabled={loading || data.next_cursor === null} onClick={() => setCursor(data.next_cursor!)}>Next</button></>}</nav></>}
  </section>;
}

function CampaignTotals({ progress }: { progress: FinanceProgress }) {
  const format = (value: string | number | null | undefined) => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value)) ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(value)) : "Not reported";
  return <section aria-label="Official campaign totals">
    {progress.official_totals.flatMap((source, i) => source.records.map((record, j) => <div key={`${i}:${j}`}>
      <h3>Campaign totals{source.committee ? ` — ${source.committee}` : ""}</h3>
      <small>Reported coverage: {record.coverage_start_date ? String(record.coverage_start_date).slice(0, 10) : "Not reported"} to {record.coverage_end_date ? String(record.coverage_end_date).slice(0, 10) : "Not reported"}</small>
      <dl className={styles.totals}><div><dt>Total received</dt><dd>{format(record.receipts)}</dd></div><div><dt>Total spent</dt><dd>{format(record.disbursements)}</dd></div></dl>
      <details><summary>Contribution categories ▾</summary><dl className={styles.categories}>
        {([["individual_itemized_contributions", "Itemized individual contributions"], ["individual_unitemized_contributions", "Unitemized individual contributions"], ["political_party_committee_contributions", "Party committee contributions"], ["other_political_committee_contributions", "Other committee contributions"], ["contribution_refunds", "Contribution refunds"]] as const).map(([field, label]) => <div key={field}><dt>{label}</dt><dd>{format(record[field])}</dd></div>)}
      </dl></details>
      <small><SourceLink url={source.source_url}>FEC campaign totals</SourceLink> · Reported totals are separate from the donor records collected below.</small>
    </div>))}
  </section>;
}
