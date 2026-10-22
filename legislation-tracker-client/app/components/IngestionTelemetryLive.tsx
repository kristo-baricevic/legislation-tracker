"use client";
import React from "react";
import { authGet, authPost } from "@/lib/api";
import dashboard from "./ingestion-dashboard.module.css";
type Telemetry = {
    observed_at: string;
    last_discovery_completed_at: string | null;
    last_successful_work_item_at: string | null;
    counts_by_kind_and_status: {
        kind: string;
        status: string;
        count: number;
    }[];
    stale_leases: number;
    discovery_run: {
        id: string;
        status: string;
        started_at: string | null;
        finished_at: string | null;
        discovered: number | null;
        created: number | null;
    } | null;
    recent_work_states: {
        id: number;
        kind: string;
        status: string;
        updated_at: string;
    }[];
};
type Readiness = {
    available: boolean;
    missing_unqueued_metadata: number | null;
    ready_to_start?: number | null;
    incremental_discoverable_count_available?: boolean;
    discovery_basis?: {cursor_at: string | null; from_date_time: string | null};
    discovery_checked_completed_at?: string;
    missing_bill_metadata?: number | null;
    age_seconds?: number;
    complete?: boolean;
    reason?: string | null;
};
export default function IngestionTelemetryLive() {
    const [expanded, setExpanded] = React.useState(true);
    const contentId = React.useId();
    const [scope, setScope] = React.useState("119");
    const [telemetry, setTelemetry] = React.useState<Telemetry | null>(null);
    const [readiness, setReadiness] = React.useState<Readiness | null>(null);
    const [error, setError] = React.useState("");
    const [busy, setBusy] = React.useState(false);
    const [notice, setNotice] = React.useState("");
    const [receivedAt, setReceivedAt] = React.useState<number | null>(null);
    const [now, setNow] = React.useState(0);
    const [requestKey, setRequestKey] = React.useState<string | null>(null);
    const [acceptedRunId, setAcceptedRunId] = React.useState<string | null>(null);
    const epoch = React.useRef(0);
    React.useEffect(() => () => { epoch.current++; }, []);
    React.useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
    async function refresh() {
        const current = ++epoch.current;
        setBusy(true);
        setError("");
        setTelemetry(null);
        setReadiness(null);
        try {
            const suffix = `?jurisdiction=federal&congress=${encodeURIComponent(scope)}`;
            const [status, source] = await Promise.all([authGet<Telemetry>(`/api/ingestion/telemetry/${suffix}`), authGet<Readiness>(`/api/ingestion/source-readiness/${suffix}`)]);
            if (!Array.isArray(status.counts_by_kind_and_status) || typeof status.observed_at !== "string" || typeof source.available !== "boolean")
                throw new Error("Invalid telemetry");
            if (current === epoch.current) {
                setTelemetry(status);
                setReadiness(source);
                setReceivedAt(Date.now());
                setNow(Date.now());
            }
        }
        catch {
            if (current === epoch.current)
                setError("Telemetry unavailable. Check the backend connection and staff access, then retry.");
        }
        finally {
            if (current === epoch.current)
                setBusy(false);
        }
    }
    async function start() {
        const current = ++epoch.current;
        setBusy(true);
        setNotice("");
        // A pre-start completed snapshot cannot authorize discarding this request key.
        setTelemetry(previous => previous && ({ ...previous, discovery_run: null }));
        const key = requestKey ?? crypto.randomUUID();
        setRequestKey(key);
        try {
            const result = await authPost<{
                run_id: string;
                status: string;
            }>("/api/ingestion/poll-congress/", { jurisdiction: "federal", congress: Number(scope), idempotency_key: key });
            if (!result.run_id || !result.status)
                throw new Error("Invalid run response");
            if (current !== epoch.current) return;
            setAcceptedRunId(result.run_id);
            setNotice(`Discovery request ${result.run_id}: ${result.status}. Downstream processing is separate. Refresh to check status.`);
        }
        catch {
            if (current !== epoch.current) return;
            setNotice("Start could not be confirmed. Retry uses the same request key; check status before creating another request.");
        }
        finally {
            if (current === epoch.current) setBusy(false);
        }
    }
    const count = (statuses: string[]) => telemetry ? telemetry.counts_by_kind_and_status.filter(row => statuses.includes(row.status)).reduce((total, row) => total + row.count, 0) : "Unavailable";
    const sourceAge = readiness?.age_seconds != null && receivedAt != null ? readiness.age_seconds + Math.max(0, (now - receivedAt) / 1000) : null;
    const sourceFresh = readiness?.available && sourceAge != null && sourceAge <= 300;
    const stageNames: Record<string, string> = { bill: "Bill metadata", bill_versions: "Bill text versions", document_download: "Document downloads", generate_contract: "Bill analysis", bill_subjects: "Topics", bill_actions: "Bill actions", bill_cosponsors: "Cosponsors", bill_committees: "Committees", bill_summaries: "Official summaries", bill_votes: "Votes" };
    const label = (value: string) => stageNames[value] ?? value.replaceAll("_", " ").replace(/^./, char => char.toUpperCase());
    const date = (value?: string | null) => {
        if (!value) return "Not recorded";
        const parsed = new Date(value);
        return Number.isNaN(parsed.getTime()) ? "Not recorded" : parsed.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    };
    const rows = telemetry?.counts_by_kind_and_status ?? [];
    const stages = [...new Set(rows.map(row => row.kind))];
    const stageCount = (kind: string, statuses: string[]) => rows.filter(row => row.kind === kind && statuses.includes(row.status)).reduce((total, row) => total + row.count, 0);
    const otherStates = [...new Set(rows.map(row => row.status))].filter(status => !["pending", "dispatched", "processing", "blocked", "dead", "succeeded"].includes(status));
    return <section aria-labelledby="live-telemetry-title" className={dashboard.dashboard}>
      <div className={dashboard.header}>
        <h2 id="live-telemetry-title">Legislation ingestion</h2>
        <button type="button" className={dashboard.secondary} aria-expanded={expanded} aria-controls={contentId} aria-label={expanded ? "Collapse legislation ingestion" : "Expand legislation ingestion"} onClick={() => setExpanded(value => !value)}>{expanded ? "Collapse ▴" : "Expand ▾"}</button>
      </div>
      <div id={contentId} hidden={!expanded}>
      <div className={dashboard.header}>
        <p>Bring bills from Congress.gov into the tracker.</p>
        <div className={dashboard.actions}>
          <label>Congress <input type="number" min="1" max="200" step="1" value={scope} disabled={busy} onChange={event => { epoch.current++; setScope(event.target.value); setTelemetry(null); setReadiness(null); setRequestKey(null); setAcceptedRunId(null); setNotice(""); }}/></label>
          <button className={dashboard.secondary} disabled={busy} onClick={() => void refresh()}>{busy ? "Working…" : "Refresh telemetry"}</button>
          <button className={dashboard.primary} disabled={busy || !scope || !Number.isInteger(Number(scope)) || Number(scope) < 1 || Number(scope) > 200} onClick={() => void start()}>Start discovery and ingestion</button>
        </div>
      </div>
      <div className={dashboard.snapshot}><span className={dashboard.badge}>{telemetry ? "Snapshot loaded" : "Not loaded"}</span><span>{telemetry ? `Updated ${date(telemetry.observed_at)}` : "Refresh to load counts. You can start ingestion without refreshing."}</span><span>Staff access required</span></div>
      {error && <p role="alert" className={dashboard.alert}>{error}</p>}
      <p role="status" className={notice ? dashboard.notice : undefined}>{notice}</p>
      <div className={dashboard.metrics}>
        <div><h3>Queued</h3><strong>{telemetry ? count(["pending", "dispatched"]) : "—"}</strong><span>Waiting to be processed</span></div>
        <div><h3>Processing</h3><strong>{telemetry ? count(["processing"]) : "—"}</strong><span>Work currently in progress</span></div>
        <div className={dashboard.failed}><h3>Failed</h3><strong>{telemetry ? count(["dead"]) : "—"}</strong><span>Stopped after retries</span></div>
        <div><h3>Last discovery completed</h3><strong className={dashboard.dateValue}>{date(telemetry?.last_discovery_completed_at)}</strong><span>Discovery only, not all processing</span></div>
      </div>
      <div className={dashboard.pipelineHeader}><div><h3>Current pipeline backlog</h3><p>Work items across this Congress—not a completion percentage.</p></div>{telemetry?.discovery_run && <span className={dashboard.badge}>Latest discovery: {label(telemetry.discovery_run.status)}</span>}</div>
      {!telemetry ? <div className={dashboard.empty}>No pipeline snapshot loaded. Select Refresh telemetry to see current work.</div> : !stages.length ? <div className={dashboard.empty}>No work items in this snapshot.</div> :
        <div className={dashboard.tableScroll} role="region" aria-label="Pipeline counts" tabIndex={0}><table aria-label="Pipeline work items">
          <thead><tr><th scope="col">Stage</th>{["Queued", "Processing", "Blocked", "Failed", "Completed", ...otherStates.map(label)].map(name => <th scope="col" key={name}>{name}</th>)}</tr></thead>
          <tbody>{stages.map(kind => <tr key={kind}><th scope="row">{label(kind)}</th>{[["pending", "dispatched"], ["processing"], ["blocked"], ["dead"], ["succeeded"], ...otherStates.map(status => [status])].map((statuses, index) => <td key={statuses.join(",")} className={index === 3 && stageCount(kind, statuses) > 0 ? dashboard.failureCount : undefined}>{stageCount(kind, statuses).toLocaleString()}</td>)}</tr>)}</tbody>
        </table></div>}
      <details className={dashboard.details}><summary>Recent activity</summary>
        <p>Latest recorded work states; not a complete event log.</p>
        <div className={dashboard.activity}>{telemetry?.recent_work_states.length ? <ul>{telemetry.recent_work_states.map(row => <li key={row.id}><div><strong>{label(row.kind)}</strong><span>{label(row.status)}</span></div><time dateTime={row.updated_at}>{date(row.updated_at)}</time></li>)}</ul> : <p>{telemetry ? "No recent activity recorded." : "Refresh telemetry to load activity."}</p>}</div>
      </details>
      <details className={dashboard.details}><summary>Source &amp; technical details</summary>
        <div className={dashboard.sourceMetrics}><div><h3>Ready for incremental discovery</h3><strong>{sourceFresh && readiness?.incremental_discoverable_count_available ? readiness.ready_to_start ?? "Unavailable" : "Unavailable"}</strong><p>New or updated bill records eligible for discovery.</p></div><div><h3>Missing unqueued metadata</h3><strong>{sourceFresh ? readiness?.missing_unqueued_metadata ?? "Unavailable" : "Unavailable"}</strong><p>Historical gaps may fall before the discovery cursor; Start may not fill them.</p></div></div>
        <dl className={dashboard.facts}>
          <div><dt>Last successful work item</dt><dd>{date(telemetry?.last_successful_work_item_at)}</dd></div>
          <div><dt>Stale leases</dt><dd>{telemetry?.stale_leases ?? "Unavailable"}</dd></div>
          <div><dt>Latest discovery started</dt><dd>{date(telemetry?.discovery_run?.started_at)}</dd></div>
          <div><dt>Latest discovery finished</dt><dd>{date(telemetry?.discovery_run?.finished_at)}</dd></div>
        </dl>
        <p>Source snapshot: {sourceAge != null ? `${Math.round(sourceAge)} seconds old; ${readiness?.complete ? "complete observed inventory" : "incomplete"}` : "Unavailable"}. {sourceAge != null && sourceAge > 300 ? "Stale — readiness is unavailable." : readiness?.reason}</p>
        <p>Discovery basis: cursor {readiness?.discovery_basis?.cursor_at ?? "none / unavailable"}; fromDateTime {readiness?.discovery_basis?.from_date_time ?? "full discovery / unavailable"}; observed {readiness?.discovery_checked_completed_at ?? "Unavailable"}.</p>
        <p>Refresh reads stored status; it does not scan Congress.gov or enqueue work. Retrying Start uses the same request key to avoid duplicate discovery.</p>
        <button className={dashboard.secondary} disabled={busy || !requestKey || !acceptedRunId || telemetry?.discovery_run?.id !== acceptedRunId || !["succeeded", "failed", "unknown"].includes(telemetry.discovery_run.status)} onClick={() => { setRequestKey(null); setAcceptedRunId(null); setNotice("New request prepared. Start explicitly when ready."); }}>Prepare a new discovery request</button>
      </details>
      </div>
    </section>;
}
