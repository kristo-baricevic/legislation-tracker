"use client";

import { useEffect, useState } from "react";

import {
  acknowledgeBillChanges,
  compareBillContracts,
  compareBillDocuments,
  getBillChanges,
  type BillContractItem,
  type BillDocumentItem,
  type BillChangesPage,
  type ContractComparison,
  type DocumentComparison,
} from "@/lib/api";

export default function BillChangeExperience({
  billId,
  contracts,
  documents,
}: {
  billId: number;
  contracts: BillContractItem[];
  documents: BillDocumentItem[];
}) {
  const [changes, setChanges] = useState<BillChangesPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [acknowledging, setAcknowledging] = useState(false);
  const [contractDiff, setContractDiff] = useState<ContractComparison | null>(null);
  const [documentDiff, setDocumentDiff] = useState<DocumentComparison | null>(null);
  const [diffError, setDiffError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getBillChanges(billId)
      .then((page) => { if (!cancelled) setChanges(page); })
      .catch((cause: unknown) => { if (!cancelled) setError(cause instanceof Error ? cause.message : "Could not load bill changes."); });
    return () => { cancelled = true; };
  }, [billId]);

  async function acknowledge() {
    if (!changes?.page_end_cursor) return;
    setAcknowledging(true);
    setError(null);
    try {
      await acknowledgeBillChanges(billId, changes.page_end_cursor);
      setChanges((current) => current ? { ...current, unread_count: 0 } : current);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not acknowledge changes.");
    } finally {
      setAcknowledging(false);
    }
  }

  async function loadComparison(kind: "contract" | "document") {
    setDiffError(null);
    try {
      if (kind === "contract") {
        if (contracts.length < 2) return;
        setContractDiff(await compareBillContracts(billId, contracts[1].id, contracts[0].id));
      } else {
        if (documents.length < 2) return;
        setDocumentDiff(await compareBillDocuments(billId, documents[1].id, documents[0].id));
      }
    } catch (cause) {
      setDiffError(cause instanceof Error ? cause.message : "Could not compare versions.");
    }
  }

  return (
    <section className="mb-6 space-y-4 rounded-lg border border-slate-400/80 bg-white/80 p-4 shadow-sm dark:border-green-800/80 dark:bg-green-950/20 dark:shadow-none">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h2 className="text-lg font-semibold text-slate-900 dark:text-green-400">What changed?</h2><p className="text-sm text-slate-600 dark:text-green-600">A chronological record of bill updates, versions, analysis, relationships, and votes.</p></div>
        {changes?.personalized && changes.page_end_cursor && <button type="button" onClick={acknowledge} disabled={acknowledging} className="cursor-pointer border border-slate-700 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-slate-200 disabled:opacity-50 dark:border-green-700 dark:text-green-300 dark:hover:bg-green-950/40">{acknowledging ? "Saving…" : changes.unread_count ? `Mark ${changes.unread_count} as seen` : "Changes seen"}</button>}
      </div>
      {error && <p role="alert" className="text-sm text-red-700 dark:text-red-300">{error}</p>}
      {!changes && !error && <p className="text-sm text-slate-600 dark:text-green-600">Loading change history…</p>}
      {changes?.initial_window_truncated && <p className="text-sm text-slate-600 dark:text-green-600">Showing the newest changes first; older history is available.</p>}
      {changes && (changes.results.length ? <ol className="divide-y divide-slate-300 dark:divide-green-900/70">{changes.results.map((change) => <li key={change.id} className="py-3"><p className="font-semibold">{change.summary}</p><p className="text-sm text-slate-600 dark:text-green-600">{new Date(change.occurred_at).toLocaleString()}</p>{change.after && <pre className="mt-1 overflow-x-auto text-xs text-slate-700 dark:text-green-500">{JSON.stringify(change.after, null, 2)}</pre>}</li>)}</ol> : <p className="text-sm text-slate-600 dark:text-green-600">No changes have been recorded yet.</p>)}
      <div className="border-t border-slate-300 pt-3 dark:border-green-900/70"><h3 className="font-semibold">Compare versions</h3><p className="mb-2 text-sm text-slate-600 dark:text-green-600">Compare the two newest available versions. The diff is bounded and shows structured changes rather than full text.</p><div className="flex flex-wrap gap-3"><button type="button" disabled={contracts.length < 2} onClick={() => void loadComparison("contract")} className="cursor-pointer border border-slate-700 px-3 py-1.5 text-sm disabled:opacity-50 dark:border-green-700">Compare analysis</button><button type="button" disabled={documents.length < 2} onClick={() => void loadComparison("document")} className="cursor-pointer border border-slate-700 px-3 py-1.5 text-sm disabled:opacity-50 dark:border-green-700">Compare bill text</button></div></div>
      {diffError && <p role="alert" className="text-sm text-red-700 dark:text-red-300">{diffError}</p>}
      {contractDiff && <div><h3 className="font-semibold">Analysis changes ({contractDiff.total_change_count})</h3><ul className="mt-2 space-y-2 text-sm">{contractDiff.changes.map((change) => <li key={`${change.path}-${change.operation}`}><span className="font-semibold">{change.operation}</span> {change.path}</li>)}</ul>{contractDiff.truncated && <p className="text-sm">Results are truncated.</p>}</div>}
      {documentDiff && <div><h3 className="font-semibold">Text section changes ({documentDiff.total_change_count})</h3><ul className="mt-2 space-y-2 text-sm">{documentDiff.sections.map((section) => <li key={section.section_key}><span className="font-semibold">{section.operation}</span> {section.section_key}</li>)}</ul>{documentDiff.truncated && <p className="text-sm">Results are truncated.</p>}</div>}
    </section>
  );
}
