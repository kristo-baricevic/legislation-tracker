"use client";
import React from "react";
import styles from "./bill-deck.module.css";
import IngestionTelemetryLive from "./IngestionTelemetryLive";
export const TELEMETRY_FLAG_KEY = "legislation-tracker-ingestion-telemetry";
type Stage = {
    name: string;
    status: string;
    detail: string;
};
type SampleTelemetry = {
    observedAt: string;
    completedAt: string;
    ready: number;
    queued: number;
    running: number;
    failed: number;
    stages: Stage[];
    events: {
        time: string;
        message: string;
    }[];
};
// Deliberately static fixtures: these values are never fetched from an operational service.
const sample: SampleTelemetry = {
    observedAt: "Oct 9, 2026 · 2:45 PM ET", completedAt: "Oct 9, 2026 · 2:32 PM ET",
    ready: 24, queued: 46, running: 3, failed: 2,
    stages: [
        { name: "Discover", status: "Sample: complete", detail: "Congress.gov API inventory checked" },
        { name: "Bill metadata", status: "Sample: running", detail: "3 sample work items processing" },
        { name: "Documents", status: "Sample: queued", detail: "Waiting for metadata dependencies" },
        { name: "Compare versions", status: "Sample: attention", detail: "2 sample items need investigation" },
    ],
    events: [
        { time: "2:45 PM ET", message: "Sample inventory observed; 24 missing unqueued identities" },
        { time: "2:41 PM ET", message: "Sample document comparison failed; retry pending" },
        { time: "2:32 PM ET", message: "Sample discovery batch persisted" },
    ],
};
export default function IngestionTelemetryPreview({ isStaff = false }: {
    isStaff?: boolean;
}) {
    const [enabled, setEnabled] = React.useState<boolean | null>(null);
    const [sampleMode, setSampleMode] = React.useState(true);
    const [notice, setNotice] = React.useState("");
    React.useEffect(() => {
        const sync = () => {
            try {
                const value = localStorage.getItem(TELEMETRY_FLAG_KEY);
                setEnabled(value !== "false");
                if (value === null)
                    localStorage.setItem(TELEMETRY_FLAG_KEY, "true");
            }
            catch {
                setEnabled(true);
                setNotice("Browser storage is unavailable; the preview preference will reset on reload.");
            }
        };
        sync();
        const storage = (event: StorageEvent) => { if (event.key === TELEMETRY_FLAG_KEY || event.key === null)
            sync(); };
        window.addEventListener("storage", storage);
        return () => window.removeEventListener("storage", storage);
    }, []);
    if (enabled === null)
        return null;
    const value = (count: number) => sampleMode ? `${count} sample` : "Unavailable";
    return <div className={styles.telemetryArea}>
    <label><input type="checkbox" checked={enabled} onChange={event => {
            const next = event.target.checked;
            setEnabled(next);
            try {
                localStorage.setItem(TELEMETRY_FLAG_KEY, String(next));
                setNotice("");
            }
            catch {
                setNotice("Browser storage is unavailable; the preview preference will reset on reload.");
            }
        }}/> Show ingestion telemetry preview</label>
    {notice && <p role="status">{notice}</p>}
    {enabled && (!sampleMode && isStaff ? <><label><input type="checkbox" checked={sampleMode} onChange={event => setSampleMode(event.target.checked)}/> Show sample data</label><IngestionTelemetryLive /></> : <section aria-labelledby="telemetry-title" className={styles.telemetry}>
      <div className={styles.telemetryBanner}><strong>{sampleMode ? "Preview — sample data" : "Preview — backend not connected"}</strong><span>Operator view · visual evaluation only</span></div>
      <div className={styles.heading}><div><h2 id="telemetry-title">Legislation ingestion</h2><p>From Congress.gov API to readable bill history.</p></div><label><input type="checkbox" checked={sampleMode} onChange={event => setSampleMode(event.target.checked)}/> Show sample data</label></div>
      <p className={styles.note}>No live values are shown in sample mode. All displayed counts, statuses, dates and events are illustrative. This preview does not start, poll or ingest bills.</p>
      <div className={styles.telemetryMetrics}>
        <div><h3>Missing unqueued metadata</h3><strong>{value(sample.ready)}</strong><p>Illustrative full-inventory gaps. Historical gaps may precede the incremental cursor; currently discoverable count unavailable.</p></div>
        <div><h3>Queued</h3><strong>{value(sample.queued)}</strong><p>Sample work items awaiting processing.</p></div>
        <div><h3>Running</h3><strong>{value(sample.running)}</strong><p>Sample work items in progress.</p></div>
        <div><h3>Failed</h3><strong>{value(sample.failed)}</strong><p>Sample work items requiring investigation.</p></div>
      </div>
      <div className={styles.telemetryFreshness}><div><h3>Last discovery completed</h3><p>{sampleMode ? `${sample.completedAt} (sample)` : "Unavailable"}</p></div><div><h3>Telemetry freshness</h3><p>{sampleMode ? `Sample snapshot: ${sample.observedAt}` : "Unavailable — backend connection required"}</p></div></div>
      <h3>Pipeline stages</h3><ol className={styles.telemetryStages}>{sample.stages.map((stage, index) => <li key={stage.name}><span className={styles.bar} style={{ background: ["#233f68", "#2f6b50", "#426c86", "#923e47"][index] }}/><div><h4>{stage.name}</h4><strong>{sampleMode ? stage.status : "Unavailable"}</strong><p>{sampleMode ? stage.detail : "Backend connection required"}</p></div></li>)}</ol>
      <div className={styles.telemetryBottom}><div><h3>Recent events {sampleMode && "(sample)"}</h3>{sampleMode ? <ul>{sample.events.map(event => <li key={event.time}><span>{event.time}</span><p>{event.message}</p></li>)}</ul> : <p>Unavailable — no operational event feed connected.</p>}</div><div><h3>Ingestion controls</h3><button disabled aria-describedby="ingestion-disabled">Start ingestion</button><p id="ingestion-disabled">Backend connection required</p><p className={styles.note}>This sample control has no action. Operational controls require staff access.</p></div></div>
    </section>)}
  </div>;
}
