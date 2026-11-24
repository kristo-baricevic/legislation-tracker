"use client";
import { useId } from "react";
import StackDialog from "./ModalStack";
import type { BillEnhancementEstimate, EnhancementConfirmation } from "@/lib/api";

export function confirmationFromEstimate(estimate: BillEnhancementEstimate): EnhancementConfirmation | null {
  if (!estimate.source_fingerprint || !estimate.request_fingerprint || estimate.credential_revision == null) return null;
  return {
    ...(estimate.rerun_after ? { rerun_after: estimate.rerun_after } : {}),
    source_fingerprint: estimate.source_fingerprint,
    request_fingerprint: estimate.request_fingerprint,
    credential_revision: estimate.credential_revision,
  };
}


export function EnhancementEstimateDialog({ estimate, title, unknownOutcome, submitting, submitEnhancement, onCancel }: {
  estimate: BillEnhancementEstimate; title?: string; unknownOutcome?: boolean; submitting: boolean;
  submitEnhancement: () => void; onCancel: () => void;
}) {
  const titleId = useId();
  return <StackDialog identity={titleId} titleId={titleId} size="confirmation" className="rounded-xl border border-slate-300 bg-white p-6 text-sm text-slate-900 shadow-xl backdrop:bg-black/40" onClose={() => { if (!submitting) onCancel(); }}>
    <h2 id={titleId} className="text-lg font-semibold">Confirm enhancement</h2>
    {title && <p className="mt-1">{title}</p>}
          {unknownOutcome && <p className="mt-2 font-semibold text-amber-900 dark:text-amber-300">The previous request may have completed and another request may duplicate provider usage.</p>}
          <ul className="mt-3 space-y-1">
            <li>{(estimate.estimated_input_tokens ?? 0).toLocaleString()} estimated input tokens{estimate.estimator ? ` (${estimate.estimator})` : ""}</li>
            <li>{(estimate.aggregate_budget?.maximum_output ?? estimate.max_output_tokens ?? 0).toLocaleString()} maximum output tokens, including reasoning</li>
            {estimate.aggregate_budget && <li>Up to {estimate.aggregate_budget.maximum_calls} calls{estimate.reader_coverage ? ", including the summary and item explanations" : ", including glossary batches and any repair or overview"}</li>}
            {estimate.reader_coverage && <li>{estimate.reader_coverage.selected_count} of {estimate.reader_coverage.total_count} items eligible for in-place enhancement in {estimate.reader_coverage.batch_count} batches. {estimate.reader_coverage.unavailable_count} items keep their original explanations because complete source context is unavailable or exceeds the request limit.</li>}
            {estimate.glossary_coverage && <li>All {estimate.glossary_coverage.eligible_definitions} eligible definitions in {estimate.glossary_coverage.batch_count} glossary batches</li>}
            <li>{estimate.provider} · {estimate.requested_model} · reasoning {estimate.reasoning_effort}</li>
            <li>Credential revision {estimate.credential_revision}</li>
          </ul>
          {!!estimate.reader_coverage?.unavailable.length && <details className="mt-3">
            <summary>Items that will keep their original explanation</summary>
            <ul className="mt-2 space-y-1">{estimate.reader_coverage.unavailable.map((item) => <li key={item.target_id}>{item.target_id}: {item.reason.replaceAll("_", " ")}</li>)}</ul>
          </details>}
          {estimate.coverage_notice && <p className="mt-3">{estimate.coverage_notice}</p>}
          <p className="mt-3 font-semibold text-amber-900 dark:text-amber-300">{estimate.cost_status === "free" ? "This model has zero token charges under the verified provider pricing. Provider limits apply." : estimate.aggregate_budget ? "Your provider may charge your account. These are total limits across all planned calls; unused calls are not sent." : "Your provider may charge your account for this request and up to one additional citation-repair request. The token limits above apply to each call; usage includes both calls."}</p>
          <div className="mt-4 flex flex-wrap gap-3">
            <button type="button" onClick={submitEnhancement} disabled={submitting} className="bg-slate-900 px-4 py-2 font-semibold text-white disabled:opacity-50 dark:bg-green-500 dark:text-black">
              {submitting ? "Starting…" : "Confirm and enhance"}
            </button>
            <button autoFocus type="button" onClick={onCancel} disabled={submitting} className="border border-slate-600 px-4 py-2 font-semibold disabled:opacity-50">Cancel</button>
          </div>

  </StackDialog>;
}
