"use client";

import { useMemo, useState } from "react";

import type { VoteDetailItem, VoteListItem, VoteRecordItem } from "@/lib/api";

interface VotingRecordProps {
  votes: VoteListItem[];
  selectedVote: VoteDetailItem | null;
  loadingVoteId: number | null;
  error: string | null;
  onSelect: (voteId: number) => void;
  page: number;
  hasNext: boolean;
  onPrevious: () => void;
  onNext: () => void;
}

type PositionGroup = "yes" | "no" | "present" | "not voting" | "other";

const groupLabels: Record<PositionGroup, string> = {
  yes: "Yes",
  no: "No",
  present: "Present",
  "not voting": "Not voting",
  other: "Other recorded positions",
};

const groupOrder: PositionGroup[] = ["yes", "no", "present", "not voting", "other"];

function normalizedPosition(position: string): PositionGroup {
  const normalized = position.trim().toLowerCase().replaceAll("_", " ");
  if (["yes", "yea", "aye"].includes(normalized)) return "yes";
  if (["no", "nay"].includes(normalized)) return "no";
  if (normalized === "present") return "present";
  if (["not voting", "not voting present", "absent", "paired"].includes(normalized)) {
    return "not voting";
  }
  return "other";
}

function sortRecords(records: VoteRecordItem[]): VoteRecordItem[] {
  return [...records].sort((left, right) => {
    const state = left.representative.state.localeCompare(right.representative.state);
    if (state !== 0) return state;
    const leftDistrict = left.representative.district ?? "";
    const rightDistrict = right.representative.district ?? "";
    const district = leftDistrict.localeCompare(rightDistrict, undefined, { numeric: true });
    if (district !== 0) return district;
    return left.representative.name.localeCompare(right.representative.name);
  });
}

function voteTimestamp(vote: VoteListItem): string {
  const date = new Date(vote.vote_date);
  return Number.isNaN(date.getTime()) ? vote.vote_date : date.toLocaleDateString();
}

function VotePagination({
  page,
  hasNext,
  onPrevious,
  onNext,
}: Pick<VotingRecordProps, "page" | "hasNext" | "onPrevious" | "onNext">) {
  if (page === 1 && !hasNext) return null;
  return (
    <nav className="mt-4 flex items-center justify-between gap-3" aria-label="vote history pagination">
      <button
        type="button"
        onClick={onPrevious}
        disabled={page === 1}
        aria-label="Previous vote history page"
        className="cursor-pointer border border-slate-700 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50 dark:border-green-700 dark:text-green-300 dark:hover:bg-green-950/40"
      >
        Previous
      </button>
      <span className="text-sm text-slate-600 dark:text-green-600">Page {page}</span>
      <button
        type="button"
        onClick={onNext}
        disabled={!hasNext}
        aria-label="Next vote history page"
        className="cursor-pointer border border-slate-700 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50 dark:border-green-700 dark:text-green-300 dark:hover:bg-green-950/40"
      >
        Next
      </button>
    </nav>
  );
}

export function VotingRecord({
  votes,
  selectedVote,
  loadingVoteId,
  error,
  onSelect,
  page,
  hasNext,
  onPrevious,
  onNext,
}: VotingRecordProps) {
  const [query, setQuery] = useState("");
  const [party, setParty] = useState("");
  const [state, setState] = useState("");
  const orderedVotes = useMemo(
    () => [...votes].sort((left, right) => {
      const date = new Date(right.vote_date).getTime() - new Date(left.vote_date).getTime();
      return date || right.id - left.id;
    }),
    [votes],
  );
  const parties = useMemo(
    () => [...new Set(selectedVote?.records.map((record) => record.representative.party).filter(Boolean) ?? [])].sort(),
    [selectedVote],
  );
  const states = useMemo(
    () => [...new Set(selectedVote?.records.map((record) => record.representative.state).filter(Boolean) ?? [])].sort(),
    [selectedVote],
  );
  const groupedRecords = useMemo(() => {
    if (!selectedVote) return new Map<PositionGroup, VoteRecordItem[]>();
    const normalizedQuery = query.trim().toLocaleLowerCase();
    const filtered = selectedVote.records.filter((record) => (
      (!normalizedQuery || record.representative.name.toLocaleLowerCase().includes(normalizedQuery)) &&
      (!party || record.representative.party === party) &&
      (!state || record.representative.state === state)
    ));
    const groups = new Map<PositionGroup, VoteRecordItem[]>();
    for (const record of sortRecords(filtered)) {
      const key = normalizedPosition(record.position);
      groups.set(key, [...(groups.get(key) ?? []), record]);
    }
    return groups;
  }, [party, query, selectedVote, state]);
  const fullCounts = useMemo(() => {
    const counts = new Map<PositionGroup, number>();
    for (const record of selectedVote?.records ?? []) {
      const key = normalizedPosition(record.position);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return counts;
  }, [selectedVote]);

  return (
    <section className="mb-6 overflow-hidden rounded-lg border border-slate-400/80 bg-white/85 shadow-sm dark:border-green-800/80 dark:bg-green-950/20 dark:shadow-none" aria-labelledby="voting-record-heading">
      <header className="border-b border-slate-300 bg-slate-100/80 px-4 py-4 dark:border-green-900 dark:bg-black/20">
        <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-green-700">Congressional record</p>
        <h2 id="voting-record-heading" className="mt-1 text-xl font-semibold text-slate-950 dark:text-green-400">Voting record</h2>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-700 dark:text-green-200/80">Select a roll call to see every returned member record. Positions are reported as received; filters only change what is displayed.</p>
      </header>
      <div className="p-4">
        <ul className="divide-y divide-slate-300 rounded border border-slate-300 dark:divide-green-900/70 dark:border-green-900/70">
          {orderedVotes.map((vote) => (
            <li key={vote.id} className="flex flex-wrap items-center justify-between gap-3 p-3">
              <div>
                <p className="font-semibold text-slate-900 dark:text-green-300">{vote.chamber} session {vote.session_number ?? "unknown"} roll call {vote.roll_number}: {vote.result}</p>
                <p className="text-sm text-slate-600 dark:text-green-600">Yes {vote.yeas} · No {vote.nays} · {voteTimestamp(vote)}</p>
                {vote.question && <p className="mt-1 text-sm text-slate-700 dark:text-green-200">{vote.question}</p>}
                {vote.source_url && <a href={vote.source_url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-block text-sm text-blue-900 underline hover:text-blue-950 dark:text-green-400 dark:hover:text-green-300">Official vote source</a>}
              </div>
              <button
                type="button"
                onClick={() => onSelect(vote.id)}
                disabled={loadingVoteId === vote.id}
                className="cursor-pointer border border-slate-700 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50 dark:border-green-700 dark:text-green-300 dark:hover:bg-green-950/40"
              >
                {loadingVoteId === vote.id ? "Loading voting record..." : "View voting record"}
              </button>
            </li>
          ))}
        </ul>
        <VotePagination page={page} hasNext={hasNext} onPrevious={onPrevious} onNext={onNext} />
        {error && <p role="alert" className="mt-3 text-sm text-red-700 dark:text-red-400">{error}</p>}
        {selectedVote && (
          <div className="mt-6 border-t border-slate-300 pt-5 dark:border-green-900/70">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-green-400">Member positions</h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <label className="text-sm font-semibold text-slate-800 dark:text-green-300">Search members
                <input aria-label="Search members" type="search" value={query} onChange={(event) => setQuery(event.target.value)} className="mt-1 block w-full border border-slate-400 bg-white px-3 py-2 font-normal text-slate-950 dark:border-green-800 dark:bg-black dark:text-green-200" />
              </label>
              <label className="text-sm font-semibold text-slate-800 dark:text-green-300">Party
                <select aria-label="Party" value={party} onChange={(event) => setParty(event.target.value)} className="mt-1 block w-full border border-slate-400 bg-white px-3 py-2 font-normal text-slate-950 dark:border-green-800 dark:bg-black dark:text-green-200">
                  <option value="">All parties</option>
                  {parties.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </label>
              <label className="text-sm font-semibold text-slate-800 dark:text-green-300">State
                <select aria-label="State" value={state} onChange={(event) => setState(event.target.value)} className="mt-1 block w-full border border-slate-400 bg-white px-3 py-2 font-normal text-slate-950 dark:border-green-800 dark:bg-black dark:text-green-200">
                  <option value="">All states</option>
                  {states.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </label>
            </div>
            {(fullCounts.get("yes") !== undefined && selectedVote.yeas !== fullCounts.get("yes")) && <p role="status" className="mt-3 text-sm text-amber-800 dark:text-amber-300">Reported yes total {selectedVote.yeas} differs from {fullCounts.get("yes")} returned member records. The official total may include records not returned here.</p>}
            {(fullCounts.get("no") !== undefined && selectedVote.nays !== fullCounts.get("no")) && <p role="status" className="mt-2 text-sm text-amber-800 dark:text-amber-300">Reported no total {selectedVote.nays} differs from {fullCounts.get("no")} returned member records. The official total may include records not returned here.</p>}
            {groupOrder.map((group) => {
              const records = groupedRecords.get(group) ?? [];
              if (records.length === 0) return null;
              return (
                <section key={group} className="mt-5" aria-label={`${groupLabels[group]} positions`}>
                  <h4 className="text-base font-semibold text-slate-900 dark:text-green-300">{groupLabels[group]} — {records.length}</h4>
                  <ul className="mt-2 divide-y divide-slate-300 rounded border border-slate-300 dark:divide-green-900/70 dark:border-green-900/70">
                    {records.map((record) => (
                      <li key={record.representative.id} className="flex flex-wrap justify-between gap-2 p-3 text-sm">
                        <span className="font-medium text-slate-900 dark:text-green-100">{record.representative.name}</span>
                        <span className="text-slate-600 dark:text-green-600">{record.representative.party || "Party not reported"} · {record.representative.state || "State not reported"}{record.representative.district ? `-${record.representative.district}` : ""} · {record.position}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}
            {selectedVote.records.length > 0 && groupedRecords.size === 0 && <p className="mt-4 text-sm text-slate-600 dark:text-green-600">No returned member records match these filters.</p>}
          </div>
        )}
      </div>
    </section>
  );
}
