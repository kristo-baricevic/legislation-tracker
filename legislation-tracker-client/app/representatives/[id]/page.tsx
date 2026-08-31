"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  getRepresentative,
  getRepresentativeCommittees,
  getRepresentativeCosponsoredBills,
  getRepresentativeInsights,
  getRepresentativeSponsoredBills,
  type BillCosponsorItem,
  type BillListItem,
  type CommitteeMembershipItem,
  type RepresentativeInsight,
  type RepresentativeItem,
} from "@/lib/api";

function percent(value: number | null) {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

function BillRows({ bills }: { bills: BillListItem[] }) {
  if (!bills.length) return <p className="text-sm text-slate-600 dark:text-green-600">No bills are recorded for this Congress.</p>;
  return (
    <ul className="divide-y divide-slate-300 rounded border border-slate-300 dark:divide-green-900/70 dark:border-green-900/70">
      {bills.map((bill) => (
        <li key={bill.id} className="p-3">
          <Link className="font-semibold text-blue-900 underline dark:text-green-400" href={`/bills/${bill.id}`}>
            {bill.bill_number}: {bill.title}
          </Link>
        </li>
      ))}
    </ul>
  );
}

function InsightCards({ insight }: { insight: RepresentativeInsight }) {
  return (
    <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <div className="rounded border border-slate-300 p-3 dark:border-green-900/70">
        <p className="text-sm text-slate-600 dark:text-green-600">Participation</p>
        <p className="text-xl font-semibold">{percent(insight.participation_rate)}</p>
        <p className="text-sm">{insight.participation_numerator} / {insight.participation_denominator} roll calls</p>
      </div>
      <div className="rounded border border-slate-300 p-3 dark:border-green-900/70">
        <p className="text-sm text-slate-600 dark:text-green-600">Recorded positions</p>
        <p className="text-sm">Yes {insight.position_counts.yes ?? 0} · No {insight.position_counts.no ?? 0}</p>
        <p className="text-sm">Present {insight.position_counts.present ?? 0} · Not voting {insight.position_counts.not_voting ?? 0}</p>
      </div>
      <div className="rounded border border-slate-300 p-3 dark:border-green-900/70">
        <p className="text-sm text-slate-600 dark:text-green-600">Legislation</p>
        <p className="text-sm">Sponsored {insight.sponsored_bill_count}</p>
        <p className="text-sm">Active cosponsored {insight.active_cosponsored_bill_count}</p>
      </div>
      <div className="rounded border border-slate-300 p-3 dark:border-green-900/70">
        <p className="text-sm text-slate-600 dark:text-green-600">Committee roles</p>
        <p className="text-xl font-semibold">{insight.committee_count}</p>
        <p className="text-sm">First vote {insight.first_vote_at ? new Date(insight.first_vote_at).toLocaleDateString() : "—"}</p>
      </div>
    </section>
  );
}

export default function RepresentativeDetailPage() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const representativeId = Number(params.id);
  const congress = Number(searchParams.get("congress") ?? "119");
  const valid = Number.isSafeInteger(representativeId) && representativeId > 0 && Number.isSafeInteger(congress) && congress > 0;
  const [representative, setRepresentative] = useState<RepresentativeItem | null>(null);
  const [insight, setInsight] = useState<RepresentativeInsight | null>(null);
  const [sponsored, setSponsored] = useState<BillListItem[]>([]);
  const [cosponsored, setCosponsored] = useState<BillCosponsorItem[]>([]);
  const [committees, setCommittees] = useState<CommitteeMembershipItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (!valid) {
      setLoading(false);
      setError("Invalid representative or Congress ID.");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([
      getRepresentative(representativeId),
      getRepresentativeInsights(representativeId, congress),
      getRepresentativeSponsoredBills(representativeId, congress),
      getRepresentativeCosponsoredBills(representativeId, congress),
      getRepresentativeCommittees(representativeId, congress),
    ])
      .then(([person, summary, sponsors, cosponsors, memberships]) => {
        if (cancelled) return;
        setRepresentative(person);
        setInsight(summary);
        setSponsored(sponsors.results);
        setCosponsored(cosponsors.results);
        setCommittees(memberships.results);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Could not load representative details.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [congress, representativeId, retry, valid]);

  const activeCosponsoredBills = useMemo(
    () => cosponsored.filter((item) => item.withdrawn_at === null),
    [cosponsored],
  );

  return (
    <main className="min-h-[calc(100vh-4rem)] bg-background px-4 py-6 font-mono text-slate-900 dark:text-green-300 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-6xl space-y-6">
        <Link href={`/representatives?congress=${congress}`} className="text-blue-900 underline dark:text-green-400">← Representatives</Link>
        {loading && <p className="text-slate-600 dark:text-green-600">Loading representative evidence…</p>}
        {error && <div role="alert" className="rounded border border-red-300 p-3 text-red-800 dark:border-red-800 dark:text-red-300">{error} <button type="button" className="underline" onClick={() => setRetry((value) => value + 1)}>Retry</button></div>}
        {!loading && representative && insight && (
          <>
            <header>
              <h1 className="text-2xl font-semibold">{representative.name}</h1>
              <p className="mt-1 text-slate-600 dark:text-green-600">{representative.party} · {representative.state}{representative.district ? `-${representative.district}` : ""} · {representative.chamber} · Congress {congress}</p>
            </header>
            <InsightCards insight={insight} />
            <section className="rounded-lg border border-slate-400/80 bg-white/80 p-4 dark:border-green-800/80 dark:bg-green-950/20">
              <h2 className="text-lg font-semibold">Roll-call coverage</h2>
              <p className="mt-1 text-sm">{insight.coverage_complete ? "Complete official roll-call coverage." : `Partial coverage — ${insight.coverage_reason ?? "source status is unavailable"}`}</p>
              <p className="mt-1 text-sm text-slate-600 dark:text-green-600">{insight.ingested_roll_calls} persisted of {insight.discovered_roll_calls} discovered chamber roll calls. Percentages above show raw counts, not a score.</p>
            </section>
            <section className="grid gap-6 lg:grid-cols-2">
              <div className="rounded-lg border border-slate-400/80 bg-white/80 p-4 dark:border-green-800/80 dark:bg-green-950/20"><h2 className="mb-3 text-lg font-semibold">Sponsored bills</h2><BillRows bills={sponsored} /></div>
              <div className="rounded-lg border border-slate-400/80 bg-white/80 p-4 dark:border-green-800/80 dark:bg-green-950/20"><h2 className="mb-3 text-lg font-semibold">Cosponsored bills</h2><BillRows bills={activeCosponsoredBills.map((item) => item.bill)} />{cosponsored.some((item) => item.withdrawn_at) && <p className="mt-3 text-sm text-slate-600 dark:text-green-600">Withdrawn cosponsorships are retained in the record.</p>}</div>
            </section>
            <section className="rounded-lg border border-slate-400/80 bg-white/80 p-4 dark:border-green-800/80 dark:bg-green-950/20">
              <h2 className="mb-3 text-lg font-semibold">Committee assignments</h2>
              {committees.length ? <ul className="divide-y divide-slate-300 dark:divide-green-900/70">{committees.map((membership) => <li key={`${membership.committee.id}-${membership.congress}`} className="py-2"><span className="font-semibold">{membership.committee.name}</span> · {membership.role.replaceAll("_", " ")}{membership.rank ? ` · rank ${membership.rank}` : ""}{!membership.is_current ? " · former" : ""}</li>)}</ul> : <p className="text-sm text-slate-600 dark:text-green-600">No committee assignments are recorded for this Congress.</p>}
            </section>
          </>
        )}
      </div>
    </main>
  );
}
