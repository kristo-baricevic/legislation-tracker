"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  ApiError,
  createBillEnhancement,
  getBillEnhancement,
  getBillEnhancementEstimate,
  getLatestBillEnhancement,
  getStoredAccessToken,
  retryBillEnhancement,
  type BillEnhancement,
  type BillEnhancementEstimate,
  type EnhancementCitedSource,
  type EnhancementConfirmation,
} from "@/lib/api";

function CitedSources({ sources }: { sources: EnhancementCitedSource[] }) {
  return (
    <div className="mt-2 space-y-2">
      {sources.map((source) => (
        <details key={source.source_ref} className="border-l-2 border-amber-400 pl-3 text-xs">
          <summary className="font-mono font-semibold text-amber-800 dark:text-amber-300">
            <span>{source.label}</span>
            {source.section_label ? ` · ${source.section_label}` : ""}
          </summary>
          <blockquote className="mt-2 whitespace-pre-wrap text-slate-700 dark:text-green-500">
            {source.quoted_text}
          </blockquote>
        </details>
      ))}
    </div>
  );
}

function EnhancementResult({ enhancement }: { enhancement: BillEnhancement }) {
  const result = enhancement.result;
  if (!result) return null;
  return (
    <div className="mt-5 font-sans text-slate-900 dark:text-green-200">
      {result.overview.length > 0 && (
        <section>
          <h3 className="font-mono text-sm font-semibold uppercase tracking-wide text-slate-600 dark:text-green-600">Overview</h3>
          <ul className="mt-2 space-y-4">
            {result.overview.map((item, index) => (
              <li key={`${item.text}-${index}`}>
                <p>{item.text}</p>
                <CitedSources sources={item.cited_sources} />
              </li>
            ))}
          </ul>
        </section>
      )}
      {result.key_impacts.length > 0 && (
        <section className="mt-6">
          <h3 className="font-mono text-sm font-semibold uppercase tracking-wide text-slate-600 dark:text-green-600">Key impacts</h3>
          <ul className="mt-2 space-y-4">
            {result.key_impacts.map((item, index) => (
              <li key={`${item.text}-${index}`}>
                <p>{item.text}</p>
                <CitedSources sources={item.cited_sources} />
              </li>
            ))}
          </ul>
        </section>
      )}
      {result.obligations.length > 0 && (
        <section className="mt-6">
          <h3 className="font-mono text-sm font-semibold uppercase tracking-wide text-slate-600 dark:text-green-600">Obligations</h3>
          <ul className="mt-2 space-y-4">
            {result.obligations.map((item, index) => (
              <li key={`${item.action}-${index}`}>
                <p><strong>{item.actor}</strong> is {item.modality} to {item.action}</p>
                {item.conditions && <p className="mt-1 text-sm text-slate-600 dark:text-green-500">Condition: {item.conditions}</p>}
                <CitedSources sources={item.cited_sources} />
              </li>
            ))}
          </ul>
        </section>
      )}
      {result.funding_and_timing.length > 0 && (
        <section className="mt-6">
          <h3 className="font-mono text-sm font-semibold uppercase tracking-wide text-slate-600 dark:text-green-600">Funding and timing</h3>
          <ul className="mt-2 space-y-4">
            {result.funding_and_timing.map((item, index) => (
              <li key={`${item.text}-${index}`}>
                <p>{item.text}</p>
                <CitedSources sources={item.cited_sources} />
              </li>
            ))}
          </ul>
        </section>
      )}
      {result.uncertain_language.length > 0 && (
        <section className="mt-6">
          <h3 className="font-mono text-sm font-semibold uppercase tracking-wide text-slate-600 dark:text-green-600">Uncertain language</h3>
          <ul className="mt-2 space-y-4">
            {result.uncertain_language.map((item, index) => (
              <li key={`${item.text}-${index}`}>
                <p>{item.text}</p>
                <p className="mt-1 text-sm text-slate-600 dark:text-green-500">Why it matters: {item.why_it_matters}</p>
                <CitedSources sources={item.cited_sources} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function confirmationFromEstimate(estimate: BillEnhancementEstimate): EnhancementConfirmation | null {
  if (!estimate.source_fingerprint || !estimate.request_fingerprint || estimate.credential_revision == null) return null;
  return {
    source_fingerprint: estimate.source_fingerprint,
    request_fingerprint: estimate.request_fingerprint,
    credential_revision: estimate.credential_revision,
  };
}

function EnhancementUnavailable({ reason }: { reason: string | null }) {
  if (reason === "source_unavailable") {
    return (
      <p className="mt-4 text-sm text-slate-700 dark:text-green-500">
        AI enhancement is unavailable because no stored bill text or usable cited provisions are available yet.
      </p>
    );
  }
  if (reason === "request_too_large") {
    return (
      <p className="mt-4 text-sm text-slate-700 dark:text-green-500">
        The stored bill material cannot fit within the configured request safety limits.
      </p>
    );
  }
  return (
    <p className="mt-4 text-sm text-slate-700 dark:text-green-500">
      Configure and validate an enabled provider key in <Link href="/settings" className="font-semibold underline">Settings</Link> before enhancing this bill.
    </p>
  );
}

export default function BillEnhancementPanel({ billId }: { billId: number }) {
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [estimate, setEstimate] = useState<BillEnhancementEstimate | null>(null);
  const [enhancement, setEnhancement] = useState<BillEnhancement | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<"create" | "retry" | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const authenticated = Boolean(getStoredAccessToken());
    setSignedIn(authenticated);
    setEstimate(null);
    setEnhancement(null);
    setError(null);
    setConfirming(null);
    if (!authenticated || Number.isNaN(billId)) return;
    let active = true;
    setLoading(true);
    Promise.all([
      getBillEnhancementEstimate(billId),
      getLatestBillEnhancement(billId),
    ])
      .then(([nextEstimate, latest]) => {
        if (!active) return;
        setEstimate(nextEstimate);
        setEnhancement(latest);
      })
      .catch((reason) => {
        if (!active) return;
        if (reason instanceof ApiError && reason.status === 401) setSignedIn(false);
        else setError(reason instanceof Error ? reason.message : "Could not load AI enhancement.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [billId]);

  useEffect(() => {
    if (!enhancement || !["pending", "running"].includes(enhancement.status)) return;
    let active = true;
    const timer = window.setTimeout(async () => {
      try {
        const updated = await getBillEnhancement(billId, enhancement.id);
        if (active) setEnhancement(updated);
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Could not refresh AI enhancement.");
      }
    }, Math.max(1, enhancement.poll_after_seconds ?? 2) * 1000);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [billId, enhancement]);

  async function submitEnhancement() {
    if (!estimate || !confirming) return;
    const confirmation = confirmationFromEstimate(estimate);
    if (!confirmation || !enhancement && confirming === "retry") return;
    setSubmitting(true);
    setError(null);
    try {
      const updated = confirming === "retry" && enhancement
        ? await retryBillEnhancement(billId, enhancement.id, confirmation)
        : await createBillEnhancement(billId, confirmation);
      setEnhancement(updated);
      setConfirming(null);
    } catch (reason) {
      const refreshableConflict = reason instanceof ApiError && reason.status === 409;
      if (refreshableConflict) {
        setConfirming(null);
        try {
          const [nextEstimate, latest] = await Promise.all([
            getBillEnhancementEstimate(billId),
            getLatestBillEnhancement(billId),
          ]);
          setEstimate(nextEstimate);
          setEnhancement(latest);
          setError("The bill or credential changed. Review the refreshed estimate and confirm again.");
        } catch (refreshReason) {
          if (refreshReason instanceof ApiError && refreshReason.status === 401) setSignedIn(false);
          else setError(refreshReason instanceof Error ? refreshReason.message : "Could not refresh AI enhancement.");
        }
      } else {
        setError(reason instanceof Error ? reason.message : "Could not start AI enhancement.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (signedIn === null) return null;
  if (!signedIn) {
    return (
      <section className="mb-6 border-l-4 border-amber-500 bg-white/70 p-4 dark:border-amber-400 dark:bg-green-950/20">
        <h2 className="text-lg font-semibold text-slate-950 dark:text-green-300">AI enhancement</h2>
        <p className="mt-2 text-sm text-slate-700 dark:text-green-600">Use your own provider key to request an optional source-cited explanation.</p>
        <Link href="/login" className="mt-3 inline-block text-sm font-semibold text-blue-900 underline dark:text-green-400">
          Log in to use AI enhancement
        </Link>
      </section>
    );
  }
  if (loading) {
    return <section className="mb-6 border-l-4 border-amber-500 p-4 text-sm">Loading private AI enhancement…</section>;
  }
  if (estimate && !estimate.feature_available) return null;

  const retryable = Boolean(enhancement?.latest_attempt?.retry_allowed);
  const isActive = enhancement && ["pending", "running"].includes(enhancement.status);
  const canStartNewIdentity = Boolean(enhancement?.stale);
  return (
    <section className="mb-6 border-l-4 border-amber-500 bg-white/80 p-4 shadow-sm dark:border-amber-400 dark:bg-green-950/20 dark:shadow-none sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-700 dark:text-amber-400">Private overlay</p>
          <h2 className="mt-1 text-lg font-semibold text-slate-950 dark:text-green-300">AI enhancement</h2>
          <p className="mt-1 text-sm text-slate-600 dark:text-green-600">Generated only when you confirm; it never changes the shared bill contract.</p>
        </div>
        {enhancement && <span className="border border-slate-400 px-2 py-1 text-xs uppercase tracking-wide dark:border-green-800">{enhancement.status.replace("_", " ")}</span>}
      </div>

      {estimate && !estimate.can_enhance && (
        <EnhancementUnavailable reason={estimate.unavailable_reason} />
      )}
      {estimate?.can_enhance && enhancement && !isActive && (retryable || canStartNewIdentity) && (
        <button type="button" onClick={() => setConfirming(retryable && !canStartNewIdentity ? "retry" : "create")} className="mt-4 border border-slate-900 bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-amber-500 dark:border-green-500 dark:bg-green-500 dark:text-black dark:hover:bg-green-400">
          {canStartNewIdentity ? "Enhance current version" : "Retry AI enhancement"}
        </button>
      )}
      {estimate?.can_enhance && !enhancement && (
        <button type="button" onClick={() => setConfirming("create")} className="mt-4 border border-slate-900 bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-amber-500 dark:border-green-500 dark:bg-green-500 dark:text-black dark:hover:bg-green-400">
          Enhance with AI
        </button>
      )}
      {isActive && <p role="status" className="mt-4 text-sm text-slate-700 dark:text-green-500">The confirmed request is {enhancement.status}. This panel will update automatically.</p>}
      {enhancement?.status === "succeeded" && (
        <>
          {enhancement.stale && <p className="mt-4 border border-amber-400 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/20 dark:text-amber-300">This result is for an older bill source or execution version.</p>}
          <EnhancementResult enhancement={enhancement} />
          <p className="mt-5 text-xs leading-5 text-slate-600 dark:text-green-600">{enhancement.disclaimer}</p>
          <p className="mt-2 text-xs text-slate-500 dark:text-green-700">Requested {enhancement.requested_model}; resolved {enhancement.latest_attempt?.resolved_model ?? "unknown"}; provider-reported usage {enhancement.usage.total_tokens ?? "unknown"} total tokens.</p>
        </>
      )}
      {enhancement && ["failed", "refused", "outcome_unknown"].includes(enhancement.status) && (
        <p className="mt-4 text-sm text-slate-700 dark:text-green-500">
          {enhancement.status === "outcome_unknown" ? "The provider outcome is unknown. The earlier request may already have incurred usage." : `The request ended as ${enhancement.status}.`}
        </p>
      )}

      {confirming && estimate && (
        <div role="dialog" aria-modal="true" aria-label="Confirm AI enhancement" className="mt-5 border border-amber-500 bg-amber-50 p-4 text-sm text-slate-900 dark:bg-amber-950/20 dark:text-green-300">
          <h3 className="font-semibold">Confirm AI enhancement</h3>
          {confirming === "retry" && enhancement?.status === "outcome_unknown" && <p className="mt-2 font-semibold text-amber-900 dark:text-amber-300">The previous request may have completed and another request may duplicate provider usage.</p>}
          <ul className="mt-3 space-y-1">
            <li>{(estimate.estimated_input_tokens ?? 0).toLocaleString()} estimated input tokens</li>
            <li>{(estimate.max_output_tokens ?? 0).toLocaleString()} maximum output tokens, including reasoning</li>
            <li>{estimate.provider} · {estimate.requested_model} · reasoning {estimate.reasoning_effort}</li>
            <li>Credential revision {estimate.credential_revision}</li>
          </ul>
          {estimate.coverage_notice && <p className="mt-3">{estimate.coverage_notice}</p>}
          <p className="mt-3 font-semibold text-amber-900 dark:text-amber-300">Your provider may charge your account for this request.</p>
          <div className="mt-4 flex flex-wrap gap-3">
            <button type="button" onClick={submitEnhancement} disabled={submitting} className="bg-slate-900 px-4 py-2 font-semibold text-white disabled:opacity-50 dark:bg-green-500 dark:text-black">
              {submitting ? "Starting…" : "Confirm and enhance"}
            </button>
            <button type="button" onClick={() => setConfirming(null)} disabled={submitting} className="border border-slate-600 px-4 py-2 font-semibold disabled:opacity-50">Cancel</button>
          </div>
        </div>
      )}
      {enhancement?.attempts && enhancement.attempts.length > 0 && (
        <details className="mt-5 border-t border-slate-300 pt-4 text-xs dark:border-green-900/70">
          <summary className="font-semibold">Attempt history</summary>
          <ol className="mt-3 space-y-2">
            {enhancement.attempts.map((attempt) => (
              <li key={attempt.id}>
                Attempt {attempt.sequence}: {attempt.status} · {attempt.usage.total_tokens ?? "unknown"} total tokens
                {attempt.resolved_model ? ` · ${attempt.resolved_model}` : ""}
                {attempt.failure_category ? ` · ${attempt.failure_category.replaceAll("_", " ")}` : ""}
              </li>
            ))}
          </ol>
        </details>
      )}
      {error && <p role="alert" className="mt-4 text-sm text-red-700 dark:text-red-400">{error}</p>}
    </section>
  );
}
