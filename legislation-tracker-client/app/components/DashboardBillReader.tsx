"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { forgetDashboardValue } from "@/lib/dashboard-cache";
import { plainBillText } from "@/lib/bill-format";
import { createBillEnhancement, retryBillEnhancement, getBillEnhancementEstimate, getBillEnhancement,
  type BillListItem, type BillEnhancementEstimate, type BillEnhancement } from "@/lib/api";
import { EnhancementEstimateDialog, confirmationFromEstimate } from "./EnhancementEstimateDialog";

export default function DashboardBillReader({ bill, children }: { bill: BillListItem; children: (summary: ReactNode, action: ReactNode, feedback: ReactNode, currentBill: BillListItem) => ReactNode }) {
  const [estimate, setEstimate] = useState<BillEnhancementEstimate | null>(null);
  const [saved, setSaved] = useState<BillEnhancement | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  const active = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => {
    if (!saved || saved.status === "pending" || saved.status === "running") return;
    forgetDashboardValue("tracking");
    forgetDashboardValue("bill-recommendations");
  }, [saved]);
  const status = saved?.status ?? bill.enhancement_status;
  const id = saved?.id ?? bill.enhancement_id;
  useEffect(() => {
    if (!id || (status !== "pending" && status !== "running")) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await getBillEnhancement(bill.id, id);
        if (!live) return;
        setSaved(next);
        if (["failed", "refused", "outcome_unknown"].includes(next.status)) setError(next.status === "outcome_unknown" ? "Enhancement status unknown." : "Enhancement failed.");
        if (next.status !== "pending" && next.status !== "running") return;
        timer = setTimeout(poll, Math.max(2, next.poll_after_seconds ?? 3) * 1000);
      } catch { if (live) timer = setTimeout(poll, 10000); }
    };
    timer = setTimeout(poll, 3000);
    return () => { live = false; clearTimeout(timer); };
  }, [bill.id, id, status]);

  async function act(confirm: boolean) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError("");
    try {
      if (!confirm) {
        const next = await getBillEnhancementEstimate(bill.id);
        if (!active.current) return;
        if (next.unavailable_reason === "shared_enhancement_available" && next.matching_enhancement) {
          const shared = await getBillEnhancement(bill.id, next.matching_enhancement.id);
          if (active.current) setSaved(shared);
        } else if (next.can_enhance && confirmationFromEstimate(next)) setEstimate(next);
        else setError(next.unavailable_reason?.startsWith("credential_") ? "Check your model in Settings." :
          next.unavailable_reason === "source_unavailable" ? "Bill text is not available yet." : "Enhancement is unavailable for this bill.");
      } else if (estimate) {
        const confirmation = confirmationFromEstimate(estimate);
        if (!confirmation) return;
        const match = estimate.matching_enhancement;
        const next = match?.latest_attempt?.retry_allowed ? await retryBillEnhancement(bill.id, match.id, confirmation)
          : await createBillEnhancement(bill.id, confirmation);
        if (active.current) { setSaved(next); setEstimate(null); if (["failed", "refused", "outcome_unknown"].includes(next.status)) setError(next.status === "outcome_unknown" ? "Enhancement status unknown." : "Enhancement failed."); }
      }
    } catch { if (active.current) { setEstimate(null); setError(confirm ? "Couldn’t start enhancement." : "Couldn’t load estimate."); } }
    finally { lock.current = false; if (active.current) setBusy(false); }
  }
  const reader = saved?.active_reader !== undefined ? saved.active_reader : saved?.status === "succeeded" && (saved.source_compatible ?? !saved.stale) ? saved : null;
  const result = reader?.result;
  const summary = (result?.schema_version === "2.0-source-first" ? result.synopsis.text :
    (result?.schema_version === "1.4" ? result.summary : result?.overview)?.map(c => c.text).join(" ")) || bill.card_summary;
  const currentBill: BillListItem = reader ? { ...bill, card_summary: summary,
    enhancement_id: reader.id, enhancement_status: "succeeded" } : bill;
  const enhanced = !!reader || (!saved && status === "succeeded");
  return <>{children(summary ? <p className="my-2 line-clamp-4 text-sm leading-relaxed">{plainBillText(summary)}</p> : null, bill.jurisdiction === "federal" && <>
    <button type="button" className="min-w-[6.5rem] rounded-md border border-slate-400 px-3 py-1.5 text-sm disabled:opacity-65" style={enhanced ? { backgroundColor: "#735099", borderColor: "#735099", color: "#ffffff", opacity: 1 } : undefined} aria-busy={busy} disabled={enhanced || status === "pending" || status === "running"} onClick={() => void act(false)}>
      {enhanced ? "Enhanced" : status === "pending" ? "Queued" : status === "running" ? "Enhancing" : busy ? "Preparing…" : status === "paused" ? "Continue" : "Enhance"}
    </button>
  </>, bill.jurisdiction === "federal" && <div className="min-h-[2lh] text-right text-sm leading-snug text-red-700" aria-live="polite">{error && <span role="alert">{error.includes("Settings") ? <Link className="underline" href="/settings">Check model settings.</Link> : error}</span>}</div>, currentBill)}
    {estimate && <EnhancementEstimateDialog estimate={estimate} title={bill.title} submitting={busy}
      unknownOutcome={estimate.matching_enhancement?.status === "outcome_unknown"} submitEnhancement={() => void act(true)} onCancel={() => setEstimate(null)} />}
  </>;
}
