"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import RequireAuth from "@/app/components/RequireAuth";
import { getBill, type BillDetail } from "@/lib/api";

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
      <div className="min-h-screen bg-black text-green-300 font-mono p-6">
        <p className="text-green-500">Loading…</p>
      </div>
    );
  }

  if (error || !bill) {
    return (
      <div className="min-h-screen bg-black text-green-300 font-mono p-6">
        <p className="text-red-400">{error ?? "Bill not found"}</p>
        <Link href="/bills" className="text-green-400 underline mt-4 inline-block">
          ← Back to bills
        </Link>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-black text-green-300 font-mono p-6">
      <div className="max-w-4xl mx-auto">
        <Link
          href="/bills"
          className="text-green-500 hover:text-green-400 underline mb-6 inline-block"
        >
          ← Back to bills
        </Link>

        <h1 className="text-2xl font-semibold text-green-400 mb-2">
          {bill.bill_number} ({bill.session})
        </h1>
        <p className="text-green-200 mb-6">{bill.title}</p>

        <dl className="grid gap-2 mb-6">
          <div>
            <dt className="text-green-500 text-sm">Jurisdiction</dt>
            <dd>{bill.jurisdiction}</dd>
          </div>
          <div>
            <dt className="text-green-500 text-sm">Session</dt>
            <dd>{bill.session}</dd>
          </div>
          <div>
            <dt className="text-green-500 text-sm">Status</dt>
            <dd>{bill.status}</dd>
          </div>
          <div>
            <dt className="text-green-500 text-sm">Sponsor</dt>
            <dd>{bill.sponsor_name ?? "—"}</dd>
          </div>
          {bill.introduced_at && (
            <div>
              <dt className="text-green-500 text-sm">Introduced</dt>
              <dd>{bill.introduced_at}</dd>
            </div>
          )}
          {bill.summary && (
            <div>
              <dt className="text-green-500 text-sm">Summary</dt>
              <dd className="whitespace-pre-wrap max-w-2xl">{bill.summary}</dd>
            </div>
          )}
        </dl>

        <div className="mb-6">
          <h2 className="text-lg font-semibold text-green-400 mb-2">Source & documents</h2>
          <ul className="space-y-2">
            {bill.congress_gov_url && (
              <li>
                <a
                  href={bill.congress_gov_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-green-400 hover:text-green-300 underline"
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
                  className="text-green-400 hover:text-green-300 underline"
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
                  className="text-green-400 hover:text-green-300 underline"
                >
                  PDF
                </a>
              </li>
            )}
          </ul>
        </div>

        {bill.documents && bill.documents.length > 0 && (
          <div className="mb-6">
            <h2 className="text-lg font-semibold text-green-400 mb-2">Bill documents</h2>
            <ul className="border border-green-800 rounded-lg divide-y divide-green-800">
              {bill.documents.map((doc) => (
                <li key={doc.id} className="p-3 flex items-center justify-between gap-4">
                  <span>
                    {doc.version_label}
                    {doc.is_active_version && (
                      <span className="ml-2 text-green-500 text-sm">(active)</span>
                    )}
                  </span>
                  {doc.source_url && (
                    <a
                      href={doc.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-green-400 hover:text-green-300 underline text-sm"
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
