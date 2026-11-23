"use client";
import { useEffect, useRef, useState } from "react";
import { getRepresentativeCard, type TrackedLegislatorItem } from "@/lib/api";
import { startResearch } from "@/lib/representative-research";
import CardTooltip from "./CardTooltip";
import styles from "./representative-research.module.css";

type Card = NonNullable<TrackedLegislatorItem["card"]>;
export default function RepresentativeCardResearch({ id, name, card, onCard }: {id: number; name: string; card?: Card; onCard: (card: Card) => void}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  const action = useRef<AbortController | null>(null);
  const active = card?.research?.status === "queued" || card?.research?.status === "running";
  useEffect(() => () => action.current?.abort(), []);
  useEffect(() => {
    if (!active && !revision) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const next = await getRepresentativeCard(id, controller.signal);
        if (controller.signal.aborted) return;
        onCard(next); setError(false);
        if (["queued", "running"].includes(next.research?.status ?? "")) timer = setTimeout(refresh, 10000);
        else { setRevision(0); window.dispatchEvent(new CustomEvent("representative-research-updated", { detail: id })); }
      } catch { if (!controller.signal.aborted) { setError(true); timer = setTimeout(refresh, 10000); } }
    }
    // Saved cards need no lookup. Only active or newly requested research polls.
    timer = setTimeout(refresh, revision ? 0 : 10000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [id, active, revision, onCard]);
  async function research() {
    if (busy) return;
    if (active) { setRevision(value => value + 1); return; }
    const controller = new AbortController(); action.current = controller;
    setBusy(true); setError(false);
    try {
      const year = new Date().getFullYear();
      const period = card?.research?.period ?? year + year % 2;
      const run = await startResearch(id, period, controller.signal, Boolean(card?.biography || card?.research?.status === "succeeded"));
      if (controller.signal.aborted) return;
      onCard({...card, biography: card?.biography ?? null, portrait: card?.portrait ?? null, latest_bill: card?.latest_bill ?? null, research: {period, status: run.status, overview_ready: false}});
      window.dispatchEvent(new CustomEvent("representative-research-updated", { detail: id }));
      setRevision(value => value + 1);
    } catch { if (!controller.signal.aborted) setError(true); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <div className={styles.cardControls}><CardTooltip text="Find and save a biography, photo, donations and outside spending."><button type="button" className={styles.researchButton} aria-label={`Research ${name}`} disabled={busy} onClick={() => void research()}>{busy ? "Starting…" : error ? "Retry research" : active ? card?.research?.overview_ready ? "Researched" : card?.research?.status === "queued" ? "Queued…" : "Researching…" : "Research"}</button></CardTooltip></div>;
}
