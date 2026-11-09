"use client";
import React, { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { getResearch, startResearch, getContributors, type Research, type Contributors, type FinanceProgress } from "@/lib/representative-research";
import styles from "./representative-research.module.css";
import ContributorExplorer from "./ContributorExplorer";
import CardTooltip from "./CardTooltip";
import DonationPie from "./DonationPie";
import { getOutsideSpending, getDonationSizes, type DonationSizes, type OutsideSpending } from "@/lib/representative-research";

const reasons: Record<string, string> = {
  missing_fec_key: "Campaign finance research needs the server's FEC API key. Biography and photo research can still run.",
  candidate_not_found: "No matching FEC candidate was found. Retry research or have the candidate identity checked.",
  candidate_identity_requires_verification: "The campaign identity needs verification before donor records can be attached.",
  itemized_receipts_only: "These are reported itemized contributions and refunds, not a complete accounting of campaign funding. Net funding is not shown because the records are not fully reconciled.",
  biography_source_unavailable: "The biography source could not be reached; previously saved information is retained.",
  member_source_unavailable: "Congress.gov could not be reached; saved member information is retained.",
};
function SourceLink({ url, children, "aria-describedby": description }: { url: string; children: React.ReactNode; "aria-describedby"?: string }) {
  return /^https:\/\//.test(url) ? <a href={url} aria-describedby={description} target="_blank" rel="noreferrer">{children}</a> : <span aria-describedby={description}>{children}</span>;
}

type ResearchProps = { representativeId: number; compact?: boolean; profileView?: boolean; financeView?: boolean; modalView?: boolean; cardName?: string; onResearch?: (research: Research) => void; onPortrait?: (portrait: Research["portrait"]) => void };
export default function RepresentativeResearch({ representativeId, compact = false, ...props }: ResearchProps) {
  return <ResearchPanel key={representativeId} representativeId={representativeId} compact={compact} {...props} />;
}

function ResearchPanel({ representativeId, compact, profileView = false, financeView = false, modalView = false, cardName, onResearch, onPortrait }: ResearchProps) {
  const year = new Date().getFullYear();
  const [period, setPeriod] = useState(year + year % 2);
  const [availablePeriods, setAvailablePeriods] = useState<number[]>([]);
  const [allYears, setAllYears] = useState(false);
  const [fundingView, setFundingView] = useState<"donations" | "outside">("donations");
  const [data, setData] = useState<Research | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [preparedFunding, setPreparedFunding] = useState<{ snapshot: string; contributors?: Contributors; sizes?: DonationSizes } | null>(null);
  const [reload, setReload] = useState(0);
  const [expanded, setExpanded] = useState(!compact);
  const [showConnections, setShowConnections] = useState(false);
  const action = useRef<AbortController | null>(null);
  const actionFailed = useRef(false);
  useEffect(() => { onPortrait?.(data?.portrait ?? null); }, [data?.portrait, onPortrait]);
  useEffect(() => { if (data) onResearch?.(data); }, [data, onResearch]);
  const active = data?.status === "queued" || data?.status === "running";
  const overviewReady = data?.finance_progress?.overview_ready === true;
  const overviewPending = active && !overviewReady;
  const progressLabel = busy ? "Starting…" : data?.status === "queued" ? "Queued…" : "Researching…";
  const displayedPeriod = busy && data ? data.period : period;
  useEffect(() => () => action.current?.abort(), []);
  useEffect(() => {
    const refresh = (event: Event) => { if ((event as CustomEvent<number>).detail === representativeId) setReload(value => value + 1); };
    window.addEventListener("representative-research-updated", refresh);
    return () => window.removeEventListener("representative-research-updated", refresh);
  }, [representativeId]);
  useEffect(() => {
    if (busy) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const result = await getResearch(representativeId, period, controller.signal);
        if (controller.signal.aborted) return;
        const periods = result.available_periods ?? [];
        setAvailablePeriods(periods);
        if (!cardName && periods.length && !periods.includes(period) && !["queued", "running"].includes(result.status)) {
          setData(null);
          setPeriod(periods[0]);
          return;
        }
        setData(previous => JSON.stringify(previous) === JSON.stringify(result) ? previous : result);
        if (!actionFailed.current) setError("");
        if (["queued", "running"].includes(result.status)) timer = setTimeout(load, 2500);
      } catch (e) {
        if (!controller.signal.aborted) {
          setError(e instanceof Error ? e.message : "Research could not be loaded.");
          timer = setTimeout(load, 5000);
        }
      }
    };
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [representativeId, period, reload, cardName, busy]);
  async function research() {
    if (busy) return;
    if (active) { setError(""); setReload(n => n + 1); return; }
    const controller = new AbortController();
    action.current = controller;
    actionFailed.current = false;
    setBusy(true); setError("");
    try {
      const run = await startResearch(representativeId, period, controller.signal, Boolean(data?.biography || data?.snapshot));
      if (controller.signal.aborted) return;
      setData(old => ({ ...(old ?? { biography: null, portrait: null, snapshot: null }), period, status: run.status, run }));
      setReload(n => n + 1);
      window.dispatchEvent(new CustomEvent("representative-research-updated", { detail: representativeId }));
    } catch (e) {
      if (!controller.signal.aborted) actionFailed.current = true;
      if (!controller.signal.aborted) setError(e instanceof ApiError && [401, 403].includes(e.status) ? "Sign in to research this representative." : e instanceof Error ? e.message : "Research could not start. Try again.");
    } finally { if (!controller.signal.aborted) setBusy(false); }
  }
  async function selectPeriod(next: number) {
    action.current?.abort();
    const controller = new AbortController();
    action.current = controller;
    actionFailed.current = false;
    setPeriod(next); setError(""); setBusy(true);
    try {
      const saved = await getResearch(representativeId, next, controller.signal);
      if (controller.signal.aborted) return;
      if (financeView && saved.snapshot) {
        const prepared = modalView
          ? { snapshot: saved.snapshot, sizes: await getDonationSizes(representativeId, next, saved.snapshot, controller.signal) }
          : { snapshot: saved.snapshot, contributors: await getContributors(representativeId, next, saved.snapshot, 0, "amount", controller.signal) };
        if (controller.signal.aborted) return;
        setPreparedFunding(prepared);
      }
      if (saved.status === "not_started" && !saved.snapshot) {
        const run = await startResearch(representativeId, next, controller.signal);
        if (controller.signal.aborted) return;
        setData({ ...saved, period: next, status: run.status, run });
        window.dispatchEvent(new CustomEvent("representative-research-updated", { detail: representativeId }));
      } else setData(saved);
      setReload(value => value + 1);
    } catch (e) {
      if (!controller.signal.aborted) actionFailed.current = true;
      if (!controller.signal.aborted) setError(e instanceof ApiError && [401, 403].includes(e.status) ? "Sign in to collect this period's records." : "Could not load this period. Try again.");
    } finally { if (!controller.signal.aborted) setBusy(false); }
  }
  if (cardName) return <div className={styles.cardControls}>
    <CardTooltip text={overviewReady && active ? "Overview ready. Detailed donations continue updating in the background." : active ? "Collecting biography, photo and campaign overview." : "Find and save a biography, photo, donations and outside spending."}><button type="button" className={styles.researchButton} aria-label={`Research ${cardName}`} disabled={busy} onClick={() => void research()}>{busy || overviewPending ? progressLabel : error ? "Retry research" : overviewReady && active ? "Researched" : data?.snapshot ? "Refresh research" : "Research"}</button></CardTooltip>
    {error && <p role="alert">{error}</p>}
    {data?.run?.sections?.biography?.status === "not_available" && <p role="status">No biography found.</p>}
    {data?.status === "failed" && !error && <p role="alert">Research failed. Try again.</p>}
  </div>;
  if (financeView) return <section className={`${styles.panel} ${styles.funding} ${modalView ? styles.modalFunding : ""}`} aria-label="Campaign funding">
    <div className={styles.fundingToolbar} aria-label="Funding controls">
      <div className={styles.recordTabs} aria-label="Funding type"><button aria-pressed={fundingView === "donations"} onClick={() => setFundingView("donations")}>Donations</button><button aria-pressed={fundingView === "outside"} onClick={() => setFundingView("outside")}>Outside spending</button></div>
      {fundingView === "donations" ? <label>Period <select aria-label="Reporting period" disabled={busy || !availablePeriods.length} value={allYears ? "all" : availablePeriods.includes(period) ? period : ""} onChange={event => { const all = event.target.value === "all"; setAllYears(all); if (!all) void selectPeriod(Number(event.target.value)); }}>{!availablePeriods.includes(period) && !allYears && <option value="" disabled>{data ? "No data" : "Loading…"}</option>}<option value="all">All years</option>{availablePeriods.map(value => <option key={value} value={value}>{value - 1}–{value}</option>)}</select></label> : <span className={styles.note}>All years</span>}
    </div>
    {error && <p role="alert">{error} <button onClick={() => void selectPeriod(period)}>Retry</button></p>}
    <div className={styles.fundingLoadStatus} role="status">{!data && !error ? "Loading funding…" : overviewReady && active ? "Donations updating in background" : ""}</div>
    <div className={styles.fundingContent} aria-label="Funding results" aria-busy={busy} inert={busy}>
    {fundingView === "outside" ? <OutsideSpendingTable representativeId={representativeId} collecting={active || busy} refreshToken={`${data?.snapshot}:${data?.finance_progress?.pages_loaded}:${active}`} /> : allYears ? <AllYearsDonations representativeId={representativeId} modalView={modalView} refreshToken={`${reload}:${data?.snapshot}:${data?.finance_progress?.pages_loaded}:${active}`} /> : <>
      {data?.finance_progress && <CampaignTotals progress={data.finance_progress} concise />}
      {data?.snapshot ? modalView ? <DonationPie initialData={preparedFunding?.snapshot === data.snapshot ? preparedFunding.sizes : undefined} refreshToken={`${data.finance_progress?.pages_loaded ?? 0}:${active}`} key={`${displayedPeriod}:${data.snapshot}`} representativeId={representativeId} period={displayedPeriod} snapshot={data.snapshot} /> : <ContributorTable initialData={preparedFunding?.snapshot === data.snapshot ? preparedFunding.contributors : undefined} concise refreshToken={`${data.finance_progress?.pages_loaded ?? 0}:${active}`} key={`${displayedPeriod}:${data.snapshot}`} representativeId={representativeId} period={displayedPeriod} snapshot={data.snapshot} /> : data && <p role="status">{active ? data.status === "queued" ? "Campaign research queued." : "Collecting campaign records…" : "No campaign records available for this period."}</p>}
    </>}
    {data?.run?.sections?.finance?.reason && data.run.sections.finance.reason !== "itemized_receipts_only" && <p className={styles.note}>{reasons[data.run.sections.finance.reason] || "Campaign research needs attention."}</p>}
    {data?.run?.error && <p role="alert">{data.run.error}</p>}
    </div>
  </section>;
  return <section className={styles.panel} aria-label="Representative research">
    <div className={styles.controls}>
      <button type="button" className={styles.primary} disabled={busy} onClick={() => void research()}>{busy || overviewPending ? progressLabel : overviewReady && active ? "Researched" : data?.biography || data?.snapshot ? "Refresh research" : "Research"}</button>
      {compact && <button type="button" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? "Hide research" : "View research"}</button>}
      {!compact && <label>Reporting period <select aria-label="Reporting period" value={availablePeriods.includes(period) ? period : ""} disabled={busy || !availablePeriods.length} onChange={e => void selectPeriod(Number(e.target.value))}>{!availablePeriods.includes(period) && <option value="" disabled>{data ? "No data" : "Loading…"}</option>}{availablePeriods.map(value => <option key={value} value={value}>{value - 1}–{value}</option>)}</select></label>}
    </div>
    {error && <p role="alert">{error} <button type="button" onClick={() => { setError(""); setReload(n => n + 1); }}>Retry status</button></p>}
    {data?.run?.error && <p role="alert">{data.run.error} Saved information is unchanged.</p>}
    {overviewPending && data?.status !== "queued" && <p role="status">Loading campaign overview…</p>}
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

function AllYearsDonations({ representativeId, modalView, refreshToken }: { representativeId: number; modalView: boolean; refreshToken: string }) {
  const [totals, setTotals] = useState<DonationSizes | null>(null);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    getDonationSizes(representativeId, 0, "", controller.signal).then(result => {
      if (controller.signal.aborted) return;
      setTotals(result); setError(false);
      if (result.status === "collecting") timer = setTimeout(() => setRevision(value => value + 1), 5000);
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => { controller.abort(); clearTimeout(timer); };
  }, [representativeId, revision, refreshToken]);
  const dollars = (amount?: string) => amount == null ? "—" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(amount));
  return <>
    <CardTooltip text="Collected itemized records across available periods. These are not total campaign receipts; collection may be incomplete."><span tabIndex={0} className={styles.note}>Collected donations ⓘ</span></CardTooltip>
    {error && <p role="alert">Could not load totals. <button onClick={() => setRevision(value => value + 1)}>Retry</button></p>}
    <dl className={styles.fundingTotals}><div><dt>Donations</dt><dd>{dollars(totals?.total)}</dd></div><div><dt>Refunds</dt><dd>{dollars(totals?.refunds)}</dd></div></dl>
    {modalView ? <DonationPie representativeId={representativeId} period={0} snapshot="" refreshToken={`${refreshToken}:${revision}`} /> : <ContributorTable concise representativeId={representativeId} period={0} snapshot="" refreshToken={`${refreshToken}:${revision}`} />}
  </>;
}

function OutsideSpendingTable({ representativeId, refreshToken, collecting = false }: { representativeId: number; refreshToken: string; collecting?: boolean }) {
  const [data, setData] = useState<OutsideSpending | null>(null);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [cursor, setCursor] = useState(0);
  const [loading, setLoading] = useState(true);
  const list = useRef<HTMLUListElement>(null);
  const end = useRef<HTMLLIElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    setLoading(true);
    const load = async () => {
      // Refresh the visible prefix together: background collection can reorder
      // ranked rows, so appending stale offset pages could omit or repeat groups.
      let result = await getOutsideSpending(representativeId, 0, controller.signal);
      const rows = [...result.results];
      while (result.next_cursor !== null && result.next_cursor <= cursor) {
        const next = result.next_cursor;
        result = await getOutsideSpending(representativeId, next, controller.signal);
        rows.push(...result.results);
        if (result.next_cursor !== null && result.next_cursor <= next) throw new Error("Invalid spending cursor");
      }
      return { ...result, results: [...new Map(rows.map(row => [row.id, row])).values()] };
    };
    load().then(result => {
      if (!controller.signal.aborted) { setData(result); setError(false); if (result.status === "collecting") timer = setTimeout(() => setRetry(value => value + 1), 5000); }
    }).catch(() => { if (!controller.signal.aborted) setError(true); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); clearTimeout(timer); };
  }, [representativeId, cursor, refreshToken, retry]);
  useEffect(() => {
    if (loading || error || data?.next_cursor == null || !end.current || !list.current) return;
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) setCursor(data.next_cursor!);
    }, { root: list.current, rootMargin: "80px" });
    observer.observe(end.current);
    return () => observer.disconnect();
  }, [data?.next_cursor, loading, error]);
  const money = (amount: string | null) => amount === null ? "—" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(Number(amount));
  return <section className={`${styles.contributors} ${styles.outsideSpending}`} aria-label="Outside spending">
    <div className={styles.note}>Independent spending <CardTooltip text="Money groups spent independently supporting or opposing this candidate. Not money received by the campaign. FEC processed Schedule E totals; excludes other forms of outside spending."><span tabIndex={0} aria-label="About independent spending">ⓘ</span></CardTooltip>{data?.status === "collecting" ? " · Updating" : ""}</div>
    <dl className={styles.fundingTotals}><div><dt>Supporting</dt><dd>{money(data?.support ?? null)}</dd></div><div><dt>Opposing</dt><dd>{money(data?.oppose ?? null)}</dd></div></dl>
    <ul ref={list} className={styles.donorList} aria-label="Outside spending records" aria-busy={loading} tabIndex={0}>{data?.results.map(item => <li key={item.id}><div className={styles.spenderIdentity}><SourceLink url={item.source_url}>{item.name}</SourceLink><span className={`${styles.positionPill} ${item.position === "S" ? styles.supports : styles.opposes}`}>{item.position === "S" ? "Supports" : "Opposes"}</span>{item.period && <span className={`${styles.positionPill} ${styles.yearPill}`}>{item.period - 1}–{item.period}</span>}</div><strong>{money(item.amount)}</strong></li>)}<li ref={end} className={styles.scrollSentinel} aria-hidden="true" /></ul>
    <div className={styles.listStatus}>{error ? <span role="alert">Could not load spending. <button onClick={() => setRetry(value => value + 1)}>Retry</button></span> : !data ? <span role="status">Loading spending…</span> : data.status === "not_researched" ? collecting ? "Collecting spending records…" : "Use Research to collect outside spending." : !data.results.length ? data.status === "collecting" ? "Collecting spending records…" : "No outside spending in collected records." : null}</div>
  </section>;
}

function ContributorTable({ representativeId, period, snapshot, refreshToken, concise = false, initialData }: { initialData?: Contributors; concise?: boolean; representativeId: number; period: number; snapshot: string; refreshToken: string }) {
  const [data, setData] = useState<Contributors | null>(initialData ?? null), [error, setError] = useState("");
  const [cursor, setCursor] = useState(0), [sort, setSort] = useState("amount"), [retry, setRetry] = useState(0);
  const [kind, setKind] = useState("contribution");
  const [loading, setLoading] = useState(!initialData);
  const loadedScope = useRef(initialData ? JSON.stringify([representativeId, period, snapshot, 0, "amount", "contribution"]) : "");
  const [displayed, setDisplayed] = useState({ cursor: 0, kind: "contribution" });
  useEffect(() => {
    const controller = new AbortController();
    const scope = JSON.stringify([representativeId, period, snapshot, cursor, sort, kind]);
    setLoading(loadedScope.current !== scope); setError("");
    void getContributors(representativeId, period, snapshot, cursor, sort, controller.signal, kind).then(value => { if (!controller.signal.aborted) { loadedScope.current = scope; setDisplayed({ cursor, kind }); setData(value); } }).catch(() => { if (!controller.signal.aborted) setError("Contributor records could not be loaded."); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [representativeId, period, snapshot, cursor, sort, retry, kind, refreshToken]);
  if (concise) return <section className={styles.contributors} aria-label="Campaign contributors">
    <div className={styles.contributorToolbar}>
      <div className={styles.kindSwitch} aria-label="Record type">
        {(["contribution", "refund"] as const).map(value => <button key={value} aria-pressed={kind === value} onClick={() => { if (kind === value) return; setLoading(true); setKind(value); setCursor(0); }}>{value === "contribution" ? "Contributions" : "Refunds"}</button>)}
      </div>
      <label>Sort <select value={sort} onChange={event => { setLoading(true); setSort(event.target.value); setCursor(0); }}><option value="amount">Amount</option><option value="date">Date</option><option value="name">Name</option></select></label>
    </div>
    {error && <p role="alert">{error} <button onClick={() => setRetry(n => n + 1)}>Retry contributors</button></p>}
    <div className={styles.listStatus} aria-live="polite">{loading ? "Loading contributors…" : "\u00a0"}</div>
    <>
      {data?.status === "collecting" && <CardTooltip text="Records are still being collected. Amounts and rankings may change."><span className={styles.collecting} tabIndex={0}>Updating ⓘ</span></CardTooltip>}
      <ul className={styles.donorList} aria-busy={loading} aria-label={displayed.kind === "refund" ? "Refund records" : "Contribution records"} tabIndex={0}>
        {data?.results.map(row => <li key={row.id}>
          <div className={styles.donorIdentity}><CardTooltip text={`${row.name} · ${row.type} · ${row.committee}. Open the FEC record.`}><SourceLink url={row.source_url}>{row.name}</SourceLink></CardTooltip>
            <time dateTime={row.date || undefined}>{row.date ? new Date(row.date + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }) : "Date not reported"}</time>
          </div>
          <strong>{new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(row.amount))}</strong>
        </li>)}
      </ul>
      {data && !loading && !data.results.length && <p className={styles.emptyRecords}>{data.status === "collecting" ? "Still collecting records." : "No records found for this period."}</p>}
      <nav className={styles.donorPagination} aria-label="Contributor pages">
        <button disabled={loading || !data || displayed.cursor === 0} onClick={() => { setLoading(true); setCursor(Math.max(0, displayed.cursor - 20)); }}>Prev</button>
        <span>{data?.count ? `${displayed.cursor + 1}–${Math.min(displayed.cursor + data.results.length, data.count)} of ${data.count.toLocaleString()}` : data ? "0 records" : "\u00a0"}</span>
        <button disabled={loading || !data || data.next_cursor === null} onClick={() => { if (data?.next_cursor == null) return; setLoading(true); setCursor(data.next_cursor); }}>Next</button>
      </nav>
    </>
  </section>;
  return <section><div className={styles.controls}><h3>Campaign contributors</h3><label>Sort <select value={sort} onChange={e => { setSort(e.target.value); setCursor(0); }}><option value="amount">Amount</option><option value="date">Date</option><option value="name">Name</option></select></label></div>
    <label>Record type <select value={kind} onChange={e => { setKind(e.target.value); setCursor(0); setData(null); }}><option value="contribution">Contributions</option><option value="refund">Refunds</option></select></label>
    {error && <p role="alert">{error} <button onClick={() => setRetry(n => n + 1)}>Retry contributors</button></p>}
    {loading && <p role="status">Loading contributors…</p>}
    {data && <>{data.status === "collecting" && <p className={styles.note}>{concise ? "Still collecting — amounts and rankings may change." : "Partial results — records are still being collected. Amounts and rankings may change."}</p>}{!concise && <p className={styles.note}>{data.count} reported {kind === "refund" ? "refunds" : "contributions"} in this view. Coverage: {data.status}. Contributions are not the same as total campaign receipts.</p>}
      <div className={styles.table}><table><thead><tr><th>{kind === "refund" ? "Refund recipient" : "Contributor"}</th><th>Amount</th>{!concise && <th>Campaign committee</th>}<th>Date</th>{!concise && <th>Evidence</th>}</tr></thead><tbody>{data.results.map(row => <tr key={row.id}><td>{concise ? <CardTooltip text={`${row.type} · ${row.committee}. Open the FEC record.`}><SourceLink url={row.source_url}>{row.name}</SourceLink></CardTooltip> : <>{row.name}<small>{row.type}</small></>}</td><td>{new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(row.amount))}</td>{!concise && <td>{row.committee}</td>}<td>{row.date || "Not reported"}</td>{!concise && <td><SourceLink url={row.source_url}>FEC record</SourceLink></td>}</tr>)}</tbody></table></div>{!data.results.length && <p>{data.status === "collecting" ? "No contributor records loaded yet. Collection is still running." : "No publishable contributor records were found in this scope. This does not mean the campaign received no contributions."}</p>}
      <nav className={styles.controls} aria-label="Contributor pages"><span>{data.count ? `${cursor + 1}–${Math.min(cursor + data.results.length, data.count)} of ${data.count} records` : "0 records"}</span>{(cursor > 0 || data.next_cursor !== null) && <><button disabled={loading || cursor === 0} onClick={() => setCursor(Math.max(0, cursor - 20))}>Prev</button><button disabled={loading || data.next_cursor === null} onClick={() => setCursor(data.next_cursor!)}>Next</button></>}</nav></>}
  </section>;
}

function CampaignTotals({ progress, concise = false }: { progress: FinanceProgress; concise?: boolean }) {
  const format = (value: string | number | null | undefined) => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value)) ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(value)) : "Not reported";
  return <section aria-label="Official campaign totals">
    {progress.official_totals.flatMap((source, i) => source.records.map((record, j) => <div key={`${i}:${j}`}>
      {concise ? <div className={styles.totalsSource}><CardTooltip text={`${source.committee || "Campaign committee"}. Reported coverage: ${record.coverage_start_date || "unavailable"} to ${record.coverage_end_date || "unavailable"}. Totals include more than itemized contributions.`}><SourceLink url={source.source_url}>FEC totals ⓘ</SourceLink></CardTooltip></div> : <h3>Campaign totals{source.committee ? ` — ${source.committee}` : ""}</h3>}
      {!concise && <small>Reported coverage: {record.coverage_start_date ? String(record.coverage_start_date).slice(0, 10) : "Not reported"} to {record.coverage_end_date ? String(record.coverage_end_date).slice(0, 10) : "Not reported"}</small>}
      <dl className={concise ? styles.fundingTotals : styles.totals}><div><dt>Total received</dt><dd>{format(record.receipts)}</dd></div><div><dt>Total spent</dt><dd>{format(record.disbursements)}</dd></div></dl>
      {!concise && <details><summary>Contribution categories ▾</summary><dl className={styles.categories}>
        {([["individual_itemized_contributions", "Itemized individual contributions"], ["individual_unitemized_contributions", "Unitemized individual contributions"], ["political_party_committee_contributions", "Party committee contributions"], ["other_political_committee_contributions", "Other committee contributions"], ["contribution_refunds", "Contribution refunds"]] as const).map(([field, label]) => <div key={field}><dt>{label}</dt><dd>{format(record[field])}</dd></div>)}
      </dl></details>}
      {!concise && <small><SourceLink url={source.source_url}>FEC campaign totals</SourceLink> · Reported totals are separate from the donor records collected below.</small>}
    </div>))}
  </section>;
}
