"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import RequireAuth from "@/app/components/RequireAuth";
import {
  getBill,
  type BillContractItem,
  type BillDetail,
} from "@/lib/api";

function ContractSection({ contract }: { contract: BillContractItem }) {
  const j = contract.contract_json;
  const plain =
    typeof j.plain_summary === "string" ? j.plain_summary : null;
  const excerpt =
    typeof j.source_excerpt === "string" ? j.source_excerpt : null;
  const versionLabel =
    typeof j.version_label === "string"
      ? j.version_label
      : contract.document_version_label;

  return (
    <section className="mb-6 rounded-lg border border-slate-400/80 bg-white/80 p-4 shadow-sm dark:border-green-800/80 dark:bg-green-950/20 dark:shadow-none">
      <h2 className="mb-1 text-lg font-semibold text-slate-900 dark:text-green-400">
        Plain-language summary{" "}
        <span className="text-sm font-normal text-slate-600 dark:text-green-600">(beta)</span>
      </h2>
      <p className="mb-3 text-xs text-slate-600 dark:text-green-600">
        Schema {contract.schema_version}
        {versionLabel ? ` · Version: ${versionLabel}` : ""}
        {contract.computed_at
          ? ` · Generated ${new Date(contract.computed_at).toLocaleString()}`
          : ""}
      </p>
      {plain ? (
        <p className="max-w-2xl whitespace-pre-wrap leading-relaxed text-slate-800 dark:text-green-100">
          {plain}
        </p>
      ) : (
        <p className="text-sm text-slate-600 dark:text-green-500">No summary text in contract yet.</p>
      )}
      {excerpt && excerpt !== plain && (
        <div className="mt-4">
          <h3 className="mb-1 text-sm text-slate-600 dark:text-green-500">Source excerpt</h3>
          <p className="max-w-2xl whitespace-pre-wrap text-sm text-slate-700 dark:text-green-300/90">
            {excerpt}
          </p>
        </div>
      )}
      {contract.evidence_spans.length > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-sm text-slate-600 dark:text-green-500">
            Evidence spans ({contract.evidence_spans.length})
          </summary>
          <ul className="mt-2 space-y-2 text-sm text-slate-800 dark:text-green-400/90">
            {contract.evidence_spans.map((ev, i) => (
              <li
                key={`${ev.field_path}-${i}`}
                className="border-l-2 border-slate-400 pl-3 dark:border-green-800"
              >
                <div className="font-mono text-xs text-slate-600 dark:text-green-500">
                  {ev.field_path}
                </div>
                <div className="mt-1 line-clamp-4 text-slate-700 dark:text-green-300/80">
                  {ev.quoted_text}
                </div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function BillDetailInner() {
  const params = useParams();
  const id = parseInt(params?.id as string, 10);
  const [bill, setBill] = useState<BillDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (Number.isNaN(id)) {
      setError("Invalid bill ID");
      setLoading(false);
      return;
    }
    let cancelled = false;
    getBill(id)
      .then((data) => {
        if (!cancelled) setBill(data);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load bill");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (loading) {
    return (
      <div className="min-h-screen bg-background p-6 font-mono text-slate-900 dark:text-green-300">
        <p className="text-slate-600 dark:text-green-500">Loading…</p>
      </div>
    );
  }

  if (error || !bill) {
    return (
      <div className="min-h-screen bg-background p-6 font-mono text-slate-900 dark:text-green-300">
        <p className="text-red-700 dark:text-red-400">{error ?? "Bill not found"}</p>
        <Link
          href="/bills"
          className="mt-4 inline-block cursor-pointer text-blue-900 underline dark:text-green-400"
        >
          ← Back to bills
        </Link>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background p-6 font-mono text-slate-900 dark:text-green-300">
      <div className="mx-auto max-w-4xl">
        <Link
          href="/bills"
          className="mb-6 inline-block cursor-pointer text-blue-900 underline hover:text-blue-950 dark:text-green-500 dark:hover:text-green-400"
        >
          ← Back to bills
        </Link>

        <h1 className="mb-2 text-2xl font-semibold text-slate-900 dark:text-green-400">
          {bill.bill_number} ({bill.session})
        </h1>
        <p className="mb-6 text-slate-800 dark:text-green-200">{bill.title}</p>

        <dl className="mb-6 grid gap-2">
          <div>
            <dt className="text-sm text-slate-600 dark:text-green-500">Jurisdiction</dt>
            <dd>{bill.jurisdiction}</dd>
          </div>
          <div>
            <dt className="text-sm text-slate-600 dark:text-green-500">Session</dt>
            <dd>{bill.session}</dd>
          </div>
          <div>
            <dt className="text-sm text-slate-600 dark:text-green-500">Status</dt>
            <dd>{bill.status}</dd>
          </div>
          <div>
            <dt className="text-sm text-slate-600 dark:text-green-500">Sponsor</dt>
            <dd>{bill.sponsor_name ?? "—"}</dd>
          </div>
          {bill.introduced_at && (
            <div>
              <dt className="text-sm text-slate-600 dark:text-green-500">Introduced</dt>
              <dd>{bill.introduced_at}</dd>
            </div>
          )}
          {bill.summary && (
            <div>
              <dt className="text-sm text-slate-600 dark:text-green-500">Summary</dt>
              <dd className="max-w-2xl whitespace-pre-wrap">{bill.summary}</dd>
            </div>
          )}
        </dl>

        {bill.latest_contract ? (
          <ContractSection contract={bill.latest_contract} />
        ) : (
          <section className="mb-6 rounded-lg border border-dashed border-slate-400 p-4 text-sm text-slate-700 dark:border-green-900/60 dark:text-green-600">
            <h2 className="mb-2 text-base font-semibold text-slate-900 dark:text-green-500">
              Plain-language summary (beta)
            </h2>
            <p>
              No generated summary yet. After a bill document is downloaded and
              the{" "}
              <code className="text-slate-800 dark:text-green-500/90">generate_contract</code> Celery
              task runs, a stub summary will appear here.
            </p>
          </section>
        )}

        <div className="mb-6">
          <h2 className="mb-2 text-lg font-semibold text-slate-900 dark:text-green-400">Source & documents</h2>
          <ul className="space-y-2">
            {bill.congress_gov_url && (
              <li>
                <a
                  href={bill.congress_gov_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="cursor-pointer text-blue-900 underline hover:text-blue-950 dark:text-green-400 dark:hover:text-green-300"
                >
                  View on Congress.gov →
                </a>
              </li>
            )}
            {bill.raw_text_url && (
              <li>
                <a
                  href={bill.raw_text_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="cursor-pointer text-blue-900 underline hover:text-blue-950 dark:text-green-400 dark:hover:text-green-300"
                >
                  Raw text
                </a>
              </li>
            )}
            {bill.pdf_url && (
              <li>
                <a
                  href={bill.pdf_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="cursor-pointer text-blue-900 underline hover:text-blue-950 dark:text-green-400 dark:hover:text-green-300"
                >
                  PDF
                </a>
              </li>
            )}
          </ul>
        </div>

        {bill.documents && bill.documents.length > 0 && (
          <div className="mb-6">
            <h2 className="mb-2 text-lg font-semibold text-slate-900 dark:text-green-400">Bill documents</h2>
            <ul className="divide-y divide-slate-400 rounded-lg border border-slate-400 dark:divide-green-800 dark:border-green-800">
              {bill.documents.map((doc) => (
                <li key={doc.id} className="flex items-center justify-between gap-4 p-3">
                  <span>
                    {doc.version_label}
                    {doc.is_active_version && (
                      <span className="ml-2 text-sm text-slate-600 dark:text-green-500">(active)</span>
                    )}
                  </span>
                  {doc.source_url && (
                    <a
                      href={doc.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="cursor-pointer text-sm text-blue-900 underline hover:text-blue-950 dark:text-green-400 dark:hover:text-green-300"
                    >
                      Source →
                    </a>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

export default function BillDetailPage() {
  return (
    <RequireAuth>
      <BillDetailInner />
    </RequireAuth>
  );
}
