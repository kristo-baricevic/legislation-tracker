"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import {
  compareRepresentatives,
  getAllCurrentRepresentatives,
  getBillFilterOptions,
  type RepresentativeComparison,
  type RepresentativeItem,
} from "@/lib/api";

function parseIds(value: string | null): [number, number] | null {
  if (!value) return null;
  const ids = value.split(",").map(Number);
  return ids.length === 2 && ids.every((id) => Number.isSafeInteger(id) && id > 0) && ids[0] !== ids[1]
    ? [ids[0], ids[1]]
    : null;
}

function RepresentativeCompareContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const congressParam = searchParams.get("congress");
  const parsedCongress = congressParam === null ? null : Number(congressParam);
  const [defaultCongress, setDefaultCongress] = useState<number | null>(null);
  const congress = parsedCongress ?? defaultCongress;
  const ids = parseIds(searchParams.get("ids"));
  const leftId = ids?.[0] ?? null;
  const rightId = ids?.[1] ?? null;
  const [people, setPeople] = useState<RepresentativeItem[]>([]);
  const [comparison, setComparison] = useState<RepresentativeComparison | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draftLeft, setDraftLeft] = useState("");
  const [draftRight, setDraftRight] = useState("");
  const agreementText = comparison?.agreement_rate === null || comparison?.agreement_rate === undefined
    ? "—"
    : `${Math.round(comparison.agreement_rate * 100)}% agreement`;

  useEffect(() => {
    if (congressParam !== null) return;
    let cancelled = false;
    getBillFilterOptions()
      .then((options) => {
        if (!cancelled) setDefaultCongress(options.current_congress);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load the current Congress.");
      });
    return () => {
      cancelled = true;
    };
  }, [congressParam]);

  useEffect(() => {
    setDraftLeft(leftId ? String(leftId) : "");
    setDraftRight(rightId ? String(rightId) : "");
  }, [leftId, rightId]);

  useEffect(() => {
    let cancelled = false;
    getAllCurrentRepresentatives()
      .then((results) => { if (!cancelled) setPeople(results); })
      .catch(() => { if (!cancelled) setError("Could not load representatives. Try again."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (leftId === null || rightId === null || congress === null || !Number.isSafeInteger(congress) || congress < 1) {
      setComparison(null);
      return;
    }
    let cancelled = false;
    setError(null);
    compareRepresentatives([leftId, rightId], congress)
      .then((result) => { if (!cancelled) setComparison(result); })
      .catch((cause: unknown) => { if (!cancelled) setError(cause instanceof Error ? cause.message : "Could not compare these representatives."); });
    return () => { cancelled = true; };
  }, [congress, leftId, rightId]);

  function setSelection(left: string, right: string) {
    if (!left || !right || left === right || congress === null) return;
    router.replace(`/representatives/compare?ids=${left},${right}&congress=${congress}`);
  }

  return (
    <main className="min-h-[calc(100vh-4rem)] bg-background px-4 py-6 font-mono text-slate-900 dark:text-green-300 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-5xl space-y-6">
        <Link href="/representatives" className="text-blue-900 underline dark:text-green-400">← Representatives</Link>
        <header><h1 className="text-2xl font-semibold">Compare representatives</h1><p className="mt-1 text-slate-600 dark:text-green-600">Compare shared roll calls with stated counts and coverage—not a score.</p></header>
        {loading ? <p>Loading available representatives…</p> : (
          <div className="grid gap-3 rounded border border-slate-300 p-4 sm:grid-cols-2 dark:border-green-900/70">
            <label>First representative<select className="ml-2 max-w-full border bg-white p-2 text-slate-900 dark:bg-black dark:text-green-300" value={draftLeft} onChange={(event) => { const next = event.target.value; setDraftLeft(next); setSelection(next, draftRight); }}><option value="">Choose one</option>{people.map((person) => <option key={person.id} value={person.id} disabled={String(person.id) === draftRight}>{person.name} ({person.state})</option>)}</select></label>
            <label>Second representative<select className="ml-2 max-w-full border bg-white p-2 text-slate-900 dark:bg-black dark:text-green-300" value={draftRight} onChange={(event) => { const next = event.target.value; setDraftRight(next); setSelection(draftLeft, next); }}><option value="">Choose one</option>{people.map((person) => <option key={person.id} value={person.id} disabled={String(person.id) === draftLeft}>{person.name} ({person.state})</option>)}</select></label>
          </div>
        )}
        {error && <p role="alert" className="text-red-700 dark:text-red-300">{error}</p>}
        {comparison && <section className="space-y-4 rounded-lg border border-slate-400/80 bg-white/80 p-4 dark:border-green-800/80 dark:bg-green-950/20">
          <div><h2 className="text-lg font-semibold">Shared vote evidence</h2><p>{comparison.reason ?? `${comparison.agree_count} agreements and ${comparison.disagreement_count} disagreements across ${comparison.shared_vote_count} shared yes/no votes (${agreementText}).`}</p><p className="mt-1 text-sm text-slate-600 dark:text-green-600">Excluded shared positions: {comparison.excluded_shared_vote_count}. Coverage is {comparison.coverage_complete ? "complete" : "partial"}.</p></div>
          {comparison.shared_votes_truncated && (
            <p className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-200">
              Showing {comparison.returned_shared_vote_count} of {comparison.shared_vote_count} shared vote records. The summary counts include the full comparison.
            </p>
          )}
          {comparison.shared_votes.length > 0 && <ul className="divide-y divide-slate-300 dark:divide-green-900/70">{comparison.shared_votes.map((vote) => <li key={vote.vote_id} className="py-3"><div className="font-semibold">{vote.question || vote.result}</div><div className="text-sm">First: {vote.left_position} · Second: {vote.right_position} · {new Date(vote.vote_date).toLocaleDateString()}</div>{vote.bill_id && <Link href={`/bills/${vote.bill_id}`} className="text-sm text-blue-900 underline dark:text-green-400">View bill</Link>}</li>)}</ul>}
        </section>}
      </div>
    </main>
  );
}

export default function RepresentativeComparePage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[60vh] items-center justify-center font-mono text-slate-600 dark:text-green-500">
          Loading representative comparison…
        </div>
      }
    >
      <RepresentativeCompareContent />
    </Suspense>
  );
}
