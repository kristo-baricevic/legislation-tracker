"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { compareBillDocuments, compareBillDocumentSection, type BillDocumentItem, type DocumentComparison, type DocumentSectionComparison } from "@/lib/api";

const button = "cursor-pointer rounded border border-slate-400 px-3 py-2 text-sm font-semibold hover:bg-slate-100 disabled:cursor-default disabled:opacity-50 dark:border-green-800 dark:hover:bg-green-950";
const PAGE_SIZE = 5;

function sectionLabel(key: string) {
  return key.split("/").map(part => part.replace(/#\d+/g, "").replace(/^sec\.\s*/i, "Section "))
    .filter((part, index, parts) => index === 0 || part !== parts[index - 1]).join(" · ");
}

function Passage({ label, lines, document }: { label: string; lines: string[]; document: BillDocumentItem }) {
  return <div className="min-w-0 rounded-lg border border-slate-300 bg-white p-4 dark:border-green-900 dark:bg-green-950/20">
    <p className="text-sm font-semibold">{label} · {document.version_label}</p>
    {lines.length ? <p className="mt-3 whitespace-pre-wrap break-words leading-relaxed">{lines.join("\n")}</p>
      : <p className="mt-3 italic text-slate-600 dark:text-green-600">No corresponding text in this version.</p>}
    <Link className="mt-3 inline-block text-sm underline" href={`/documents/${document.id}`}>Read this version</Link>
  </div>;
}

function ComparisonResults({ billId, before, after }: { billId: number; before: BillDocumentItem; after: BillDocumentItem }) {
  const [comparison, setComparison] = useState<DocumentComparison | null>(null);
  const [sections, setSections] = useState<DocumentSectionComparison[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setComparison(null);
    compareBillDocuments(billId, before.id, after.id).then(result => {
      if (!cancelled) setComparison(result);
    }).catch(() => { if (!cancelled) setError("Could not compare these versions. Please try again."); });
    return () => { cancelled = true; };
  }, [billId, before.id, after.id, retry]);

  useEffect(() => {
    let cancelled = false;
    setSections(null);
    if (comparison) {
      Promise.all(comparison.sections.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
        .map(section => compareBillDocumentSection(billId, before.id, after.id, section.section_key)))
        .then(results => { if (!cancelled) setSections(results); })
        .catch(() => { if (!cancelled) setError("Could not load the changed passages. Please try again."); });
    }
    return () => { cancelled = true; };
  }, [comparison, page, billId, before.id, after.id]);

  if (error) return <div role="alert" className="space-y-2"><p>{error}</p>
    <button className={button} onClick={() => setRetry(value => value + 1)}>Retry comparison</button></div>;
  if (!comparison || !sections) return <p role="status">Loading changed passages…</p>;
  const pages = Math.ceil(comparison.sections.length / PAGE_SIZE);
  return <div className="space-y-4">
    <p className="text-sm text-slate-600 dark:text-green-600">
      Exact changed passages from the selected bill texts—not a summary of their legal effects.
    </p>
    {comparison.truncated && <p role="note" className="rounded border border-amber-500 p-3 text-sm">
      This comparison is incomplete. Only part of the bill text or its changes could be compared. Read both full versions for the complete text.
    </p>}
    {comparison.fallback && <p className="text-sm">Section headings could not be matched reliably; changes are grouped by text instead.</p>}
    {!comparison.sections.length && <p>{comparison.truncated ? "No changes were found in the portion compared." : "No text changes were found between these versions."}</p>}
    {sections.map(section => <section key={section.section_key} className="space-y-3" aria-label={sectionLabel(section.section_key)}>
      <h4 className="font-semibold">{sectionLabel(section.section_key)}</h4>
      {section.operations.map((operation, index) => <div key={index} className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Passage label="Before" document={before} lines={operation.before} />
        <Passage label="After" document={after} lines={operation.after} />
      </div>)}
      {!section.operations.length && <p>No changed passages are available for this section. Open the full versions above to inspect it.</p>}
      {section.truncated && <p className="text-sm text-amber-800 dark:text-amber-300">Only part of this section’s changes is shown. Check the full versions for the remaining text.</p>}
    </section>)}
    {pages > 1 && <nav aria-label="Comparison pages" className="flex items-center justify-center gap-4">
      <button className={button} disabled={page === 0} onClick={() => { setSections(null); setPage(page - 1); }}>Prev</button>
      <span className="text-sm">Sections {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, comparison.sections.length)} of {comparison.sections.length}</span>
      <button className={button} disabled={page + 1 >= pages} onClick={() => { setSections(null); setPage(page + 1); }}>Next</button>
    </nav>}
  </div>;
}

export default function BillVersionComparison({ billId, documents, initialPair }: {
  billId: number; documents: BillDocumentItem[]; initialPair: [BillDocumentItem, BillDocumentItem] | null;
}) {
  const [open, setOpen] = useState(false);
  const [beforeId, setBeforeId] = useState(initialPair?.[0].id ?? documents[0]?.id);
  const [afterId, setAfterId] = useState(initialPair?.[1].id ?? documents[1]?.id);
  const before = documents.find(doc => doc.id === beforeId);
  const after = documents.find(doc => doc.id === afterId);
  return <div className="space-y-4 border-t border-slate-300 pt-4 dark:border-green-900">
    <div className="flex items-center justify-between gap-3">
      <h3 className="font-semibold">Compare versions</h3>
      <button className={button} disabled={documents.length < 2} aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "Close comparison" : "Compare versions"}
      </button>
    </div>
    {documents.length < 2 && <p className="text-sm">A comparison will be available when at least two bill text versions are available.</p>}
    {open && <>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {(["Before", "After"] as const).map(label => <label key={label} className="space-y-2 text-sm font-semibold">
          <span>{label} version</span>
          <select className="block w-full rounded border border-slate-400 bg-white p-2 dark:border-green-800 dark:bg-slate-950"
            value={label === "Before" ? beforeId : afterId}
            onChange={event => (label === "Before" ? setBeforeId : setAfterId)(Number(event.target.value))}>
            {documents.map(doc => <option key={doc.id} value={doc.id}>{doc.version_label}{doc.is_active_version ? " (current)" : ""} · Document {doc.id}</option>)}
          </select>
        </label>)}
      </div>
      <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
        {before && <Link className="underline" href={`/documents/${before.id}`}>Read full before version</Link>}
        {after && <Link className="underline" href={`/documents/${after.id}`}>Read full after version</Link>}
      </div>
      {before && after && before.id !== after.id
        ? <ComparisonResults key={`${before.id}:${after.id}`} billId={billId} before={before} after={after} />
        : <p>Choose two different versions.</p>}
    </>}
  </div>;
}
