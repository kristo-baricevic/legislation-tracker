"use client";
import React from "react";
import { authGet, authPost } from "@/lib/api";
import styles from "./bill-deck.module.css";
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
    return <section aria-labelledby="live-telemetry-title" className={styles.telemetry}>
    <div className={styles.telemetryBanner}><strong>Operational telemetry · staff only</strong><span>Observed snapshots; downstream run completion is not tracked.</span></div>
    <div className={styles.heading}><div><h2 id="live-telemetry-title">Legislation ingestion</h2><p>Congress.gov API · federal HR and S bills</p></div><button className={styles.loadMore} disabled={busy} onClick={() => void refresh()}>{busy ? "Loading…" : "Refresh telemetry"}</button></div>
    <label className={styles.telemetryScope}>Congress <input type="number" min="1" max="200" step="1" value={scope} disabled={busy} onChange={event => { epoch.current++; setScope(event.target.value); setTelemetry(null); setReadiness(null); setRequestKey(null); setAcceptedRunId(null); setNotice(""); }}/></label>
    {error && <p role="alert">{error}</p>}
    {!telemetry && !error && <p>Unavailable — refresh to read the backend. This view never starts ingestion automatically.</p>}
    <div className={styles.telemetryMetrics}><div><h3>Ready for incremental discovery</h3><strong>{sourceFresh && readiness?.incremental_discoverable_count_available ? readiness.ready_to_start ?? "Unavailable" : "Unavailable"}</strong><p>Observed bill identities whose source revision would create new bill work. Includes updates; existing equal or newer work revisions are excluded regardless of status.</p></div><div><h3>Missing unqueued metadata</h3><strong>{sourceFresh ? readiness?.missing_unqueued_metadata ?? "Unavailable" : "Unavailable"}</strong><p>Full inventory gaps excluding queued, active, blocked and failed identities. Historical gaps may fall before the incremental cursor and will not necessarily be discovered by Start. This historical gap count is separate from incremental readiness.</p></div><div><h3>Queued work items</h3><strong>{count(["pending", "dispatched"])}</strong></div><div><h3>Processing work items</h3><strong>{count(["processing"])}</strong></div><div><h3>Terminal failed items</h3><strong>{count(["dead"])}</strong></div></div>
    <p className={styles.note}>Source snapshot: {sourceAge != null ? `${Math.round(sourceAge)} seconds old; ${readiness?.complete ? "complete observed inventory" : "incomplete"}` : "Unavailable"}. {sourceAge != null && sourceAge > 300 ? "Stale — readiness is unavailable." : readiness?.reason} Queue observed: {telemetry?.observed_at ?? "Unavailable"}. Refresh does not scan Congress.gov or enqueue work.</p>
    <p className={styles.note}>Discovery basis: cursor {readiness?.discovery_basis?.cursor_at ?? "none / unavailable"}; fromDateTime {readiness?.discovery_basis?.from_date_time ?? "full discovery / unavailable"}; observed {readiness?.discovery_checked_completed_at ?? "Unavailable"}. Readiness becomes unavailable when the cursor or bill-work revision basis changes.</p>
    <div className={styles.telemetryFreshness}><div><h3>Last discovery completed</h3><p>{telemetry?.last_discovery_completed_at ?? "Unavailable"}</p></div><div><h3>Last successful work item</h3><p>{telemetry?.last_successful_work_item_at ?? "Unavailable"}</p></div></div>
    <h3>Latest discovery run</h3><p>{telemetry?.discovery_run ? `${telemetry.discovery_run.status} · started ${telemetry.discovery_run.started_at ?? "not recorded"} · finished ${telemetry.discovery_run.finished_at ?? "not recorded"}` : "Unavailable"}</p>
    <h3>Current pipeline backlog</h3><p className={styles.note}>Scoped work-item counts, not progress for the latest run. Stale leases: {telemetry?.stale_leases ?? "Unavailable"}.</p><ul>{telemetry?.counts_by_kind_and_status.map(row => <li key={`${row.kind}:${row.status}`}>{row.kind.replaceAll("_", " ")} · {row.status}: {row.count}</li>) ?? <li>Unavailable</li>}</ul>
    <div className={styles.telemetryBottom}><div><h3>Recent work states</h3><ul>{telemetry?.recent_work_states.map(row => <li key={row.id}>{row.updated_at} · {row.kind} · {row.status}</li>) ?? <li>Unavailable</li>}</ul></div><div><h3>Ingestion controls</h3><button disabled={busy || !telemetry || !scope || !Number.isInteger(Number(scope)) || Number(scope) < 1 || Number(scope) > 200} onClick={() => void start()}>Start discovery and ingestion</button><p className={styles.note}>Explicit action queues discovery and downstream work. Backend connection and staff access required. Request retries retain the same idempotency key.</p><button disabled={busy || !requestKey || !acceptedRunId || telemetry?.discovery_run?.id !== acceptedRunId || !["succeeded", "failed", "unknown"].includes(telemetry.discovery_run.status)} onClick={() => { setRequestKey(null); setAcceptedRunId(null); setNotice("New request prepared. Start explicitly when ready."); }}>Prepare a new discovery request</button><p role="status">{notice}</p></div></div>
  </section>;
}
