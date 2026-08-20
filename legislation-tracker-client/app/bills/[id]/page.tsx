"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  getBill,
  getApiBase,
  getContracts,
  getMyTracking,
  getStoredAccessToken,
  getVote,
  getVotes,
  trackBill,
  type BillContractItem,
  type BillDetail,
  type VoteDetailItem,
  type VoteListItem,
  untrackBill,
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
        <p className="w-full break-words whitespace-pre-wrap leading-relaxed text-slate-800 [overflow-wrap:anywhere] dark:text-green-100">
          {plain}
        </p>
      ) : (
        <p className="text-sm text-slate-600 dark:text-green-500">No summary text in contract yet.</p>
      )}
      {excerpt && excerpt !== plain && (
        <div className="mt-4">
          <h3 className="mb-1 text-sm text-slate-600 dark:text-green-500">Source excerpt</h3>
          <p className="w-full break-words whitespace-pre-wrap text-sm text-slate-700 [overflow-wrap:anywhere] dark:text-green-300/90">
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
                <div className="mt-1 line-clamp-4 break-words text-slate-700 [overflow-wrap:anywhere] dark:text-green-300/80">
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

function HistoryPagination({
  page,
  hasNext,
  onPrevious,
  onNext,
  historyName,
}: {
  page: number;
  hasNext: boolean;
  onPrevious: () => void;
  onNext: () => void;
  historyName: string;
}) {
  if (page === 1 && !hasNext) return null;
  return (
    <nav className="mt-4 flex items-center justify-between gap-3" aria-label={`${historyName} pagination`}>
      <button
        type="button"
        onClick={onPrevious}
        disabled={page === 1}
        aria-label={`Previous ${historyName} page`}
        className="cursor-pointer border border-slate-700 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50 dark:border-green-700 dark:text-green-300 dark:hover:bg-green-950/40"
      >
        Previous
      </button>
      <span className="text-sm text-slate-600 dark:text-green-600">Page {page}</span>
      <button
        type="button"
        onClick={onNext}
        disabled={!hasNext}
        aria-label={`Next ${historyName} page`}
        className="cursor-pointer border border-slate-700 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50 dark:border-green-700 dark:text-green-300 dark:hover:bg-green-950/40"
      >
        Next
      </button>
    </nav>
  );
}

function ContractHistorySection({
  contracts,
  page,
  hasNext,
  onPrevious,
  onNext,
}: {
  contracts: BillContractItem[];
  page: number;
  hasNext: boolean;
  onPrevious: () => void;
  onNext: () => void;
}) {
  if (contracts.length === 0) return null;
  return (
    <section className="mb-6 rounded-lg border border-slate-400/80 bg-white/80 p-4 shadow-sm dark:border-green-800/80 dark:bg-green-950/20 dark:shadow-none">
      <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-green-400">
        Contract history
      </h2>
      <ul className="space-y-3">
        {contracts.map((contract) => {
          const summary = contract.contract_json.plain_summary;
          return (
            <li key={contract.id} className="rounded border border-slate-300 p-3 dark:border-green-900/70">
              <div className="text-sm font-semibold text-slate-900 dark:text-green-300">
                Schema {contract.schema_version}
                {contract.document_version_label
                  ? ` · ${contract.document_version_label}`
                  : " · Metadata"}
              </div>
              <p className="mt-1 text-xs text-slate-600 dark:text-green-600">
                {new Date(contract.computed_at).toLocaleString()}
              </p>
              {typeof summary === "string" && (
                <p className="mt-2 break-words text-sm text-slate-800 [overflow-wrap:anywhere] dark:text-green-200">
                  {summary}
                </p>
              )}
            </li>
          );
        })}
      </ul>
      <HistoryPagination
        page={page}
        hasNext={hasNext}
        onPrevious={onPrevious}
        onNext={onNext}
        historyName="contract history"
      />
    </section>
  );
}

function VoteHistorySection({
  votes,
  selectedVote,
  loadingVoteId,
  onViewPositions,
  page,
  hasNext,
  onPrevious,
  onNext,
}: {
  votes: VoteListItem[];
  selectedVote: VoteDetailItem | null;
  loadingVoteId: number | null;
  onViewPositions: (voteId: number) => void;
  page: number;
  hasNext: boolean;
  onPrevious: () => void;
  onNext: () => void;
}) {
  if (votes.length === 0) return null;
  return (
    <section className="mb-6 rounded-lg border border-slate-400/80 bg-white/80 p-4 shadow-sm dark:border-green-800/80 dark:bg-green-950/20 dark:shadow-none">
      <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-green-400">
        Roll-call votes
      </h2>
      <ul className="divide-y divide-slate-300 rounded border border-slate-300 dark:divide-green-900/70 dark:border-green-900/70">
        {votes.map((vote) => (
          <li key={vote.id} className="flex flex-wrap items-center justify-between gap-3 p-3">
            <div>
              <p className="font-semibold text-slate-900 dark:text-green-300">
                {vote.chamber} session {vote.session_number} roll call {vote.roll_number}: {vote.result}
              </p>
              <p className="text-sm text-slate-600 dark:text-green-600">
                Yes {vote.yeas} · No {vote.nays} · {new Date(vote.vote_date).toLocaleDateString()}
              </p>
            </div>
            <button
              type="button"
              onClick={() => onViewPositions(vote.id)}
              disabled={loadingVoteId === vote.id}
              className="cursor-pointer border border-slate-700 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50 dark:border-green-700 dark:text-green-300 dark:hover:bg-green-950/40"
            >
              {loadingVoteId === vote.id ? "Loading positions..." : "View member positions"}
            </button>
          </li>
        ))}
      </ul>
      <HistoryPagination
        page={page}
        hasNext={hasNext}
        onPrevious={onPrevious}
        onNext={onNext}
        historyName="vote history"
      />
      {selectedVote && (
        <div className="mt-4">
          <h3 className="text-base font-semibold text-slate-900 dark:text-green-400">
            Member positions
          </h3>
          <ul className="mt-2 divide-y divide-slate-300 rounded border border-slate-300 dark:divide-green-900/70 dark:border-green-900/70">
            {selectedVote.records.map((record) => (
              <li key={record.representative.id} className="flex justify-between gap-3 p-3 text-sm">
                <span>{record.representative.name}</span>
                <span className="font-semibold capitalize">{record.position}</span>
              </li>
            ))}
          </ul>
        </div>
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
  const [hasAccount, setHasAccount] = useState(false);
  const [isTracked, setIsTracked] = useState(false);
  const [trackingLoading, setTrackingLoading] = useState(false);
  const [trackingError, setTrackingError] = useState<string | null>(null);
  const [contractHistory, setContractHistory] = useState<BillContractItem[] | null>(null);
  const [contractPage, setContractPage] = useState(1);
  const [contractHasNext, setContractHasNext] = useState(false);
  const [votes, setVotes] = useState<VoteListItem[] | null>(null);
  const [votePage, setVotePage] = useState(1);
  const [voteHasNext, setVoteHasNext] = useState(false);
  const [selectedVote, setSelectedVote] = useState<VoteDetailItem | null>(null);
  const [loadingVoteId, setLoadingVoteId] = useState<number | null>(null);

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

  useEffect(() => {
    if (Number.isNaN(id)) return;
    let cancelled = false;
    getContracts(id, { page: contractPage })
      .then((contracts) => {
        if (!cancelled) {
          setContractHistory(contracts.results);
          setContractHasNext(Boolean(contracts.next));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setContractHistory([]);
          setContractHasNext(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [contractPage, id]);

  useEffect(() => {
    if (Number.isNaN(id)) return;
    let cancelled = false;
    getVotes(id, { page: votePage })
      .then((voteResult) => {
        if (!cancelled) {
          setVotes(voteResult.results);
          setVoteHasNext(Boolean(voteResult.next));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setVotes([]);
          setVoteHasNext(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [id, votePage]);

  useEffect(() => {
    setContractPage(1);
    setVotePage(1);
    setSelectedVote(null);
  }, [id]);

  useEffect(() => {
    const signedIn = Boolean(getStoredAccessToken());
    setHasAccount(signedIn);
    if (!signedIn || Number.isNaN(id)) return;

    let cancelled = false;
    setTrackingError(null);
    getMyTracking()
      .then((summary) => {
        if (!cancelled) {
          setIsTracked(summary.bills.some((item) => item.bill.id === id));
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setTrackingError(
            e instanceof Error ? e.message : "Failed to load tracking status",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  async function toggleBillTracking() {
    if (!bill) return;
    setTrackingLoading(true);
    setTrackingError(null);
    try {
      if (isTracked) {
        await untrackBill(bill.id);
        setIsTracked(false);
      } else {
        await trackBill(bill.id);
        setIsTracked(true);
      }
    } catch (e) {
      setTrackingError(
        e instanceof Error ? e.message : "Failed to update tracking",
      );
    } finally {
      setTrackingLoading(false);
    }
  }

  async function viewVotePositions(voteId: number) {
    setLoadingVoteId(voteId);
    try {
      setSelectedVote(await getVote(voteId));
    } finally {
      setLoadingVoteId(null);
    }
  }

  if (loading) {
    return (
      <div className="min-h-[calc(100vh-4rem)] w-full bg-background px-4 py-6 font-mono text-slate-900 dark:text-green-300 sm:px-6 lg:px-8">
        <div className="w-full">
          <p className="text-slate-600 dark:text-green-500">Loading...</p>
        </div>
      </div>
    );
  }

  if (error || !bill) {
    return (
      <div className="min-h-[calc(100vh-4rem)] w-full bg-background px-4 py-6 font-mono text-slate-900 dark:text-green-300 sm:px-6 lg:px-8">
        <div className="w-full">
          <p className="text-red-700 dark:text-red-400">{error ?? "Bill not found"}</p>
          <Link
            href="/bills"
            className="mt-4 inline-block cursor-pointer text-blue-900 underline dark:text-green-400"
          >
            ← Back to bills
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] w-full bg-background px-4 py-6 font-mono text-slate-900 dark:text-green-300 sm:px-6 lg:px-8">
      <div className="w-full">
        <Link
          href="/bills"
          className="mb-6 inline-block cursor-pointer text-blue-900 underline hover:text-blue-950 dark:text-green-500 dark:hover:text-green-400"
        >
          ← Back to bills
        </Link>

        <div className="mb-6 flex flex-col gap-3 border-b border-slate-300 pb-4 dark:border-green-900/70 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="mb-2 text-2xl font-semibold text-slate-900 dark:text-green-400">
              {bill.bill_number} ({bill.session})
            </h1>
            <p className="text-slate-800 dark:text-green-200">{bill.title}</p>
          </div>
          <div className="shrink-0">
            {hasAccount ? (
              <button
                type="button"
                onClick={toggleBillTracking}
                disabled={trackingLoading}
                className="cursor-pointer border border-slate-800 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50 dark:border-green-700 dark:text-green-300 dark:hover:bg-green-950/40"
              >
                {trackingLoading
                  ? "Saving..."
                  : isTracked
                    ? "Tracked bill"
                    : "Track bill"}
              </button>
            ) : (
              <Link
                href="/login"
                className="text-sm text-blue-900 underline hover:text-blue-950 dark:text-green-500 dark:hover:text-green-400"
              >
                Log in to track this bill
              </Link>
            )}
            {trackingError && (
              <p className="mt-2 max-w-48 text-sm text-red-700 dark:text-red-300">
                {trackingError}
              </p>
            )}
          </div>
        </div>

        <dl className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
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
              <dd className="w-full break-words whitespace-pre-wrap [overflow-wrap:anywhere]">
                {bill.summary}
              </dd>
            </div>
          )}
        </dl>

        {bill.topics && bill.topics.length > 0 && (
          <div className="mb-6">
            <h2 className="mb-2 text-lg font-semibold text-slate-900 dark:text-green-400">Topics</h2>
            <div className="flex flex-wrap gap-2">
              {bill.topics.map((topic) => (
                <span
                  key={topic.topic_id}
                  className="inline-flex items-center gap-1 rounded-full border border-slate-400 bg-slate-100 px-3 py-1 text-sm text-slate-800 dark:border-green-700 dark:bg-green-950/30 dark:text-green-300"
                  title={
                    topic.confidence_score != null
                      ? `Confidence: ${(topic.confidence_score * 100).toFixed(0)}%`
                      : undefined
                  }
                >
                  {topic.name}
                  {topic.confidence_score != null && (
                    <span className="text-xs text-slate-500 dark:text-green-600">
                      {(topic.confidence_score * 100).toFixed(0)}%
                    </span>
                  )}
                </span>
              ))}
            </div>
          </div>
        )}

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
              task runs, a structured summary will appear here.
            </p>
          </section>
        )}

        {contractHistory && (
          <ContractHistorySection
            contracts={contractHistory}
            page={contractPage}
            hasNext={contractHasNext}
            onPrevious={() => setContractPage((current) => Math.max(1, current - 1))}
            onNext={() => setContractPage((current) => current + 1)}
          />
        )}
        {votes && (
          <VoteHistorySection
            votes={votes}
            selectedVote={selectedVote}
            loadingVoteId={loadingVoteId}
            onViewPositions={viewVotePositions}
            page={votePage}
            hasNext={voteHasNext}
            onPrevious={() => setVotePage((current) => Math.max(1, current - 1))}
            onNext={() => setVotePage((current) => current + 1)}
          />
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
                  <span className="flex shrink-0 flex-wrap gap-3 text-sm">
                    {doc.download_url && (
                      <a
                        href={`${getApiBase()}${doc.download_url}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="cursor-pointer text-blue-900 underline hover:text-blue-950 dark:text-green-400 dark:hover:text-green-300"
                      >
                        Download
                      </a>
                    )}
                    {doc.text_url && (
                      <a
                        href={`${getApiBase()}${doc.text_url}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="cursor-pointer text-blue-900 underline hover:text-blue-950 dark:text-green-400 dark:hover:text-green-300"
                      >
                        Read text
                      </a>
                    )}
                    {doc.source_url && (
                      <a
                        href={doc.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="cursor-pointer text-blue-900 underline hover:text-blue-950 dark:text-green-400 dark:hover:text-green-300"
                      >
                        Source →
                      </a>
                    )}
                  </span>
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
  return <BillDetailInner />;
}
