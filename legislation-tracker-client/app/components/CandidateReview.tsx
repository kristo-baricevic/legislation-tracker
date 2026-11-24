"use client";
import { useId, useState } from "react";
import { confirmCandidate, type ResearchRun } from "@/lib/representative-research";
import StackDialog from "./ModalStack";
import styles from "./representative-research.module.css";

export default function CandidateReview({ representativeId, period, run, initiallyOpen, onConfirmed }: {
  initiallyOpen: boolean; representativeId: number; period: number; run: ResearchRun; onConfirmed: (run: ResearchRun) => void;
}) {
  const title = useId();
  const [open, setOpen] = useState(initiallyOpen);
  const [selected, setSelected] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const finance = run.sections.finance;
  async function confirm() {
    if (!selected || saving) return;
    setSaving(true); setError("");
    try {
      const next = await confirmCandidate(representativeId, run.id, selected);
      setOpen(false);
      onConfirmed(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not confirm this candidate. Please retry.");
    } finally { setSaving(false); }
  }
  return <>
    <button type="button" className={styles.researchButton} onClick={() => { setSelected(""); setError(""); setOpen(true); }}>Review FEC match</button>
    {open && <StackDialog titleId={title} identity={title} size="confirmation" className="rounded-xl border bg-white p-6 shadow-xl" onClose={() => { if (!saving) setOpen(false); }}>
      <h2 id={title}>Confirm FEC candidate</h2>
      <fieldset disabled={saving} className="my-4 space-y-3"><legend>Which record belongs to {finance.representative_name} for the {period} cycle?</legend>
        {finance.candidates?.map(row => <div key={row.candidate_id}>
          <label><input type="radio" name={title} checked={selected === row.candidate_id} onChange={() => setSelected(row.candidate_id)} /> {row.name}</label>
          <div>{row.state} · {row.office === "H" ? `House district ${row.district}` : "Senate"} · <a className="underline" target="_blank" rel="noreferrer" href={`https://www.fec.gov/data/candidate/${row.candidate_id}/?cycle=${period}`}>{row.candidate_id} ↗</a></div>
        </div>)}
      </fieldset>
      {error && <p role="alert">{error}</p>}
      <div className={styles.controls}><button type="button" disabled={saving} onClick={() => setOpen(false)}>Cancel</button>
        <button type="button" className={styles.primary} disabled={!selected || saving} onClick={() => void confirm()}>{saving ? "Confirming…" : "Confirm and collect records"}</button></div>
    </StackDialog>}
  </>;
}
