"use client";
import React from "react";
import Link from "next/link";
import { getReaderItems, getVotes, getVote, type BillDetail, type VoteDetailItem, type VotesPage } from "@/lib/api";
import type { LegalNlpReaderItemsPage } from "@/lib/contracts";
import { changeCopy } from "@/lib/reader-copy";
import { SourceEvidence } from "../bills/[id]/source-evidence";
import { VotingRecord } from "../bills/[id]/voting-record";
import styles from "./bill-deck.module.css";

export default function BillModalDetails({ billId, contractId, document }: { billId: number; contractId?: number; document?: BillDetail["documents"][number] }) {
  const [page, setPage] = React.useState(1);
  const [reader, setReader] = React.useState<LegalNlpReaderItemsPage | null>(null);
  const [readerError, setReaderError] = React.useState(false);
  const [readerRetry, setReaderRetry] = React.useState(0);
  const [votePage, setVotePage] = React.useState(1);
  const [votes, setVotes] = React.useState<VotesPage | null>(null);
  const [voteError, setVoteError] = React.useState("");
  const [voteRetry, setVoteRetry] = React.useState(0);
  const [selected, setSelected] = React.useState<VoteDetailItem | null>(null);
  const [loadingVote, setLoadingVote] = React.useState<number | null>(null);
  const selection = React.useRef(0);
  React.useEffect(() => () => { selection.current++; }, []);
  React.useEffect(() => {
    if (!contractId) return;
    const controller = new AbortController();
    setReader(null); setReaderError(false);
    void getReaderItems(contractId, { page, pageSize: 6, grouped: true, signal: controller.signal }).then(value => { if (!controller.signal.aborted) setReader(value); }).catch(() => { if (!controller.signal.aborted) setReaderError(true); });
    return () => controller.abort();
  }, [contractId, page, readerRetry]);
  React.useEffect(() => {
    let live = true;
    selection.current++; setSelected(null); setLoadingVote(null); setVotes(null); setVoteError("");
    void getVotes(billId, { page: votePage }).then(value => { if (live) setVotes(value); }).catch(() => { if (live) setVoteError("Voting history could not be loaded."); });
    return () => { live = false; selection.current++; };
  }, [billId, votePage, voteRetry]);
  async function selectVote(id: number) {
    const token = ++selection.current;
    setLoadingVote(id); setSelected(null); setVoteError("");
    try { const result = await getVote(id); if (selection.current === token) setSelected(result); }
    catch { if (selection.current === token) setVoteError("Could not load member positions. Try again."); }
    finally { if (selection.current === token) setLoadingVote(null); }
  }
  return <>
    <section className={styles.modalChanges}><h3><Link href={`/bills/${billId}?tab=changes`}>What this bill does <span aria-hidden="true">↗</span></Link></h3>
      {!contractId ? <p>A detailed breakdown is not available yet.</p> : readerError ? <p role="alert">Could not load the breakdown. <button onClick={() => setReaderRetry(n => n + 1)}>Retry breakdown</button></p> : !reader ? <p role="status">Loading breakdown…</p> : <>
        <ul className={styles.modalChangeList}>{reader.results.map((item, index) => { const copy = changeCopy(item); return <li key={item.id}><strong>{copy.title}</strong><p>{copy.text}<SourceEvidence number={(page - 1) * 6 + index + 1} contractId={contractId} lineItemId={item.id} textUrl={document?.text_url} downloadUrl={document?.download_url} /></p></li>; })}</ul>
        {!reader.results.length && <p>No detailed changes have been extracted yet.</p>}
        {(page > 1 || reader.next) && <nav className={styles.modalPagination} aria-label="Bill explanation pages"><button disabled={page === 1} onClick={() => setPage(n => n - 1)}>Prev</button><span>Page {page}</span><button disabled={!reader.next} onClick={() => setPage(n => n + 1)}>Next</button></nav>}
      </>}
    </section>
    {votes?.results?.length ? <VotingRecord headingHref={`/bills/${billId}?tab=votes`} votes={votes.results} selectedVote={selected} loadingVoteId={loadingVote} error={voteError} onSelect={id => void selectVote(id)} page={votePage} hasNext={Boolean(votes.next)} onPrevious={() => setVotePage(n => Math.max(1, n - 1))} onNext={() => setVotePage(n => n + 1)} /> : voteError ? <p role="alert">{voteError} <button onClick={() => setVoteRetry(n => n + 1)}>Retry votes</button></p> : null}
  </>;
}
