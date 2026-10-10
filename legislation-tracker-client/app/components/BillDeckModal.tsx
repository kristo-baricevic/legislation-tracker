"use client";

import Link from "next/link";
import React from "react";
import { getBill, compareBillDocuments, type BillListItem, type BillDetail, type DocumentComparison } from "@/lib/api";
import styles from "./bill-deck.module.css";
import StackDialog from "./ModalStack";
import LegislatorName from "./LegislatorName";

export default function BillDeckModal({ bill, onClose, fallbackFocus }: { bill: BillListItem; onClose: () => void; fallbackFocus?: () => void }) {
  const titleId = React.useId();
  const [detail, setDetail] = React.useState<BillDetail | null>(null);
  const [error, setError] = React.useState("");
  const [attempt, setAttempt] = React.useState(0);
  const [selected, setSelected] = React.useState<number | null>(null);
  const [comparison, setComparison] = React.useState<DocumentComparison | null>(null);
  const [comparisonError, setComparisonError] = React.useState("");
  const [comparisonPair, setComparisonPair] = React.useState("");
  const [comparing, setComparing] = React.useState(false);
  React.useEffect(() => {
    const controller = new AbortController();
    void getBill(bill.id, { signal: controller.signal }).then(value => {
      if (controller.signal.aborted) return;
      setDetail(value); setError("");
      setSelected(value.documents.find(document => document.is_active_version)?.id ?? value.documents[0]?.id ?? null);
    }).catch(() => { if (!controller.signal.aborted) setError("Bill details could not be loaded. Please retry."); });
    return () => controller.abort();
  }, [bill.id, attempt]);
  const versions = [...(detail?.documents ?? [])].sort((a, b) => (b.source_order ?? -1) - (a.source_order ?? -1));
  const version = versions.find(document => document.id === selected);
  const previous = version?.source_order != null ? versions.filter(document => document.source_order != null && document.source_order < version.source_order!).sort((a, b) => b.source_order! - a.source_order!)[0] : undefined;
  const beforeId = previous?.id;
  const afterId = version?.id;
  const pair = `${beforeId}:${afterId}`;
  React.useEffect(() => {
    let live = true;
    setComparison(null); setComparisonError(""); setComparing(false); setComparisonPair(pair);
    if (beforeId != null && afterId != null) {
      setComparing(true);
      void compareBillDocuments(bill.id, beforeId, afterId).then(value => { if (live) setComparison(value); }).catch(() => { if (live) setComparisonError("A change comparison is unavailable for this version."); }).finally(() => { if (live) setComparing(false); });
    }
    return () => { live = false; };
  }, [bill.id, beforeId, afterId, pair]);
  const summaryMatches = version && detail?.summary_version_code && detail.summary_version_code.toLowerCase() === version.version_label.toLowerCase();
  // Official summaries can contain markup. Render plain text only, never injected HTML.
  const summary = detail?.summary?.replace(/<[^>]*>/g, " ") ?? "";
  return <StackDialog identity={`bill:${bill.id}`} titleId={titleId} className={`${styles.deck} ${styles.dialog}`} onClose={onClose} fallbackFocus={fallbackFocus}>
    <div className={styles.modalHeader}><p>{bill.bill_number} / Congress {bill.session}</p><button autoFocus onClick={onClose} aria-label="Close bill details">Close ✕</button></div>
    <h2 id={titleId} className={styles.modalTitle}>{bill.title || "Untitled bill"}</h2>
    {error ? <p role="alert">{error} <button onClick={() => setAttempt(value => value + 1)}>Retry</button></p> : !detail ? <p role="status">Loading bill details…</p> : <>
      <dl className={styles.metadata}><div><dt>Status</dt><dd>{bill.status.replaceAll("_", " ") || "Not recorded"}</dd></div><div><dt>Sponsor</dt><dd><LegislatorName id={detail.sponsor ?? null} name={detail.sponsor_name || "Not recorded"} congress={detail.session} /></dd></div><div><dt>Jurisdiction</dt><dd>{bill.jurisdiction || "Not recorded"}</dd></div><div><dt>Introduced</dt><dd>{bill.introduced_at || "Not recorded"}</dd></div></dl>
      <section className={styles.summary}><h3>Bill summary</h3><p>{summary || "No bill summary is available yet."}</p>{summary && <p className={styles.note}>Source: {detail.summary_source || "Stored bill summary"}. {detail.summary_version_code ? `Summary version: ${detail.summary_version_code}.` : "The source does not identify a summary version."}</p>}</section>
      <div className={styles.versionLayout}>
        <nav aria-label="Bill version history"><h3>Version history</h3>{!versions.length ? <p>No document versions are available yet.</p> : <ol className={styles.versions}>{versions.map(document => <li key={document.id}><button aria-pressed={selected === document.id} onClick={() => setSelected(document.id)}>{document.version_label || `Document ${document.id}`}{document.is_active_version ? " · Current" : ""}{document.source_order != null && <small>Source order {document.source_order}</small>}</button></li>)}</ol>}</nav>
        {version && <section aria-live="polite" className={styles.versionContent} key={version.id}>
          <h3>Selected version: {version.version_label || `Document ${version.id}`}</h3>
          <p>{summaryMatches ? summary || "No summary is available for this version." : "A summary specifically linked to this version is unavailable. The bill summary above is shown with its source version."}</p>
          <Link href={`/documents/${version.id}`}>Read this document</Link>
          <h3>Changes from previous version</h3>
          {version.source_order == null ? <p>The source does not record version order, so a previous version cannot be reliably identified.</p> : !previous ? <p>This is the earliest recorded version. No previous version is available for comparison.</p> : <>
            <p className={styles.note}>{previous.version_label || `Document ${previous.id}`} → {version.version_label || `Document ${version.id}`}</p>
            {comparing || comparisonPair !== pair ? <p role="status">Loading comparison…</p> : comparisonError ? <p>{comparisonError}</p> : comparison && comparison.before === beforeId && comparison.after === afterId && <>
              <p>{comparison.total_change_count} section changes recorded by the source comparison.</p>
              {comparison.fallback && <p className={styles.note}>The source uses a document-level fallback; a section-level breakdown is unavailable.</p>}
              {comparison.truncated && <p className={styles.note}>Partial comparison: {comparison.returned_change_count} of {comparison.total_change_count} changes shown. {comparison.truncation_reasons.join(", ")}</p>}
              <ul className={styles.changes}>{comparison.sections.map((section, index) => <li key={`${section.section_key}-${index}`}><strong>{section.section_key || "Document"}</strong>: {section.operation}</li>)}</ul>
              <p className={styles.note}>These are recorded structural changes. A narrative summary of their legal effects is not provided.</p>
            </>}
          </>}
        </section>}
      </div>
    </>}
    <footer className={styles.modalFooter}><Link href={`/bills/${bill.id}`}>Open full bill page</Link></footer>
  </StackDialog>;
}
