"use client";
import LoadingSpinner from "@/app/components/LoadingSpinner";
import React from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { getReaderItems, getVotes, getVote, type BillEnhancement, type BillDetail, type VoteDetailItem, type VotesPage } from "@/lib/api";
import { compatibleReader, resolveReaderExplanation } from "@/lib/reader-enhancements";
import { Evidence } from "../bills/[id]/reader-explanation";
import type { LegalNlpReaderItemsPage } from "@/lib/contracts";
import { changeCopy } from "@/lib/reader-copy";
import { SourceEvidence } from "../bills/[id]/source-evidence";
import { VotingRecord } from "../bills/[id]/voting-record";
import styles from "./bill-deck.module.css";
import { StableResults } from "./StableResults";
import ReaderText from "./ReaderText";

export default function BillModalDetails({ billId, contractId, contractHash, enhancement = null, document, paginationTarget }: { billId: number; contractId?: number; contractHash?: string; enhancement?: BillEnhancement | null; document?: BillDetail["documents"][number]; paginationTarget?: string }) {
  const [pager, setPager] = React.useState<HTMLElement | null>(null);
  React.useEffect(() => { setPager(paginationTarget ? window.document.getElementById(paginationTarget) : null); }, [paginationTarget]);
  const [page, setPage] = React.useState(1);
  const [shownPage, setShownPage] = React.useState(1);
  const [readerLoading, setReaderLoading] = React.useState(true);
  const [reader, setReader] = React.useState<LegalNlpReaderItemsPage | null>(null);
  const [readerError, setReaderError] = React.useState(false);
  const [readerRetry, setReaderRetry] = React.useState(0);
  const [votePage, setVotePage] = React.useState(1);
  const [shownVotePage, setShownVotePage] = React.useState(1);
  const [votesLoading, setVotesLoading] = React.useState(true);
  const [votes, setVotes] = React.useState<VotesPage | null>(null);
  const [voteError, setVoteError] = React.useState("");
  const [voteRetry, setVoteRetry] = React.useState(0);
  const [selected, setSelected] = React.useState<VoteDetailItem | null>(null);
  const [loadingVote, setLoadingVote] = React.useState<number | null>(null);
  const selection = React.useRef(0);
  const identity = document ? { contractId: contractId ?? null, contractHash: contractHash ?? null, documentId: document.id } : null;
  const enhanced = compatibleReader(enhancement, identity);
  const policy = enhanced?.source_review?.policy_changes;
  const hasPolicy = Boolean(policy?.length);
  const policyPage = Math.min(page, Math.max(1, Math.ceil((policy?.length ?? 0) / 6)));
  React.useEffect(() => () => { selection.current++; }, []);
  React.useEffect(() => {
    if (!contractId || hasPolicy) return;
    const controller = new AbortController();
    setReaderLoading(true); setReaderError(false);
    void getReaderItems(contractId, { page, pageSize: 6, grouped: true, signal: controller.signal }).then(value => { if (!controller.signal.aborted) { setReader(value); setShownPage(page); } }).catch(() => { if (!controller.signal.aborted) setReaderError(true); }).finally(() => { if (!controller.signal.aborted) setReaderLoading(false); });
    return () => controller.abort();
  }, [contractId, page, readerRetry, hasPolicy]);
  React.useEffect(() => {
    let live = true;
    selection.current++; setSelected(null); setLoadingVote(null); setVotesLoading(true); setVoteError("");
    void getVotes(billId, { page: votePage }).then(value => { if (live) { setVotes(value); setShownVotePage(votePage); } }).catch(() => { if (live) setVoteError("Voting history could not be loaded."); }).finally(() => { if (live) setVotesLoading(false); });
    return () => { live = false; selection.current++; };
  }, [billId, votePage, voteRetry]);
  async function selectVote(id: number) {
    const token = ++selection.current;
    setLoadingVote(id); setSelected(null); setVoteError("");
    try { const result = await getVote(id); if (selection.current === token) setSelected(result); }
    catch { if (selection.current === token) setVoteError("Could not load member positions. Try again."); }
    finally { if (selection.current === token) setLoadingVote(null); }
  }
  const currentPage = policy?.length ? policyPage : shownPage;
  const pending = !policy?.length && readerLoading;
  const next = policy?.length ? policyPage * 6 < policy.length : Boolean(reader?.next);
  const pagination = <nav className={styles.modalPagination} aria-label="Bill explanation pages"><button disabled={pending || currentPage === 1} onClick={() => { setPage(currentPage - 1); setReaderRetry(n => n + 1); }}>Prev</button><span>Page {currentPage}</span><button disabled={pending || !next} onClick={() => { setPage(currentPage + 1); setReaderRetry(n => n + 1); }}>Next</button></nav>;
  return <>
    <section className={styles.modalChanges}><h3><Link href={`/bills/${billId}?tab=changes`}>What this bill does <span aria-hidden="true">↗</span></Link></h3>
      {!contractId && !hasPolicy ? <p>A detailed breakdown is not available yet.</p> : <>
        <StableResults page={currentPage} busy={pending} label="Bill explanations">
        {!hasPolicy && readerError && <p role="alert">Could not load the breakdown. <button disabled={readerLoading} onClick={() => setReaderRetry(n => n + 1)}>Retry breakdown</button></p>}
        <LoadingSpinner active={!hasPolicy && !reader && !readerError} label="Loading breakdown…" />
        {policy?.length && document ? <ul className={styles.modalChangeList}>{policy.slice((policyPage - 1) * 6, policyPage * 6).map((item, index) => <li key={index}><strong>{item.title}</strong><ReaderText text={item.text} citation={<Evidence number={(policyPage - 1) * 6 + index + 1} sources={item.cited_sources} documentId={document.id} />} /></li>)}</ul> : reader && contractId && <><ul className={styles.modalChangeList}>{reader.results.map((item, index) => { const copy = changeCopy(item); const saved = resolveReaderExplanation(enhancement, identity, "line_item", item.id, item.display_text); return <li key={item.id}><strong>{copy.title}</strong><ReaderText text={saved?.text || copy.text} citation={saved ? <Evidence number={(shownPage - 1) * 6 + index + 1} sources={saved.cited_sources} documentId={saved.document_id} /> : <SourceEvidence number={(shownPage - 1) * 6 + index + 1} contractId={contractId} lineItemId={item.id} textUrl={document?.text_url} downloadUrl={document?.download_url} />} /></li>; })}</ul>
        {!reader.results.length && <p>No detailed changes have been extracted yet.</p>}
        </>}
        </StableResults>
        {pager ? createPortal(pagination, pager) : pagination}
      </>}
    </section>
    {votes?.results?.length ? <VotingRecord loading={votesLoading} headingHref={`/bills/${billId}?tab=votes`} votes={votes.results} selectedVote={selected} loadingVoteId={loadingVote} error={voteError} onSelect={id => void selectVote(id)} onCollapse={() => setSelected(null)} page={shownVotePage} hasNext={Boolean(votes.next)} onPrevious={() => { setVotePage(Math.max(1, shownVotePage - 1)); setVoteRetry(n => n + 1); }} onNext={() => { setVotePage(shownVotePage + 1); setVoteRetry(n => n + 1); }} /> : voteError ? <p role="alert">{voteError} <button onClick={() => setVoteRetry(n => n + 1)}>Retry votes</button></p> : null}
  </>;
}
