"use client";
import { usePendingCards } from "./usePendingCards";
import Link from "next/link";
import React from "react";
import { getMyTracking, trackBill, untrackBill, type BillListItem, type TrackingSummary, type TrackingMembership } from "@/lib/api";
import { dashboardSession, dashboardValue } from "@/lib/dashboard-cache";
import { capturePersonalizedScope, isPersonalizedScopeCurrent, subscribePersonalizedChanges } from "@/lib/api";
import BillCard from "./BillCard";
import DashboardBillReader from "./DashboardBillReader";

export function useDashboardBillTracking({ onSessionChange, membershipOnly = false }: { onSessionChange?: () => void; membershipOnly?: boolean } = {}) {
  const [tracking, setTracking] = React.useState<TrackingSummary | null>(null);
  const [membership, setMembership] = React.useState<TrackingMembership | null>(null);
  const [signedIn, setSignedIn] = React.useState(Boolean(tracking));
  const [isSuperuser, setIsSuperuser] = React.useState(false);
  const [ready, setReady] = React.useState(Boolean(tracking));
  const [error, setError] = React.useState("");
  const [attempt, setAttempt] = React.useState(0);
  const [currentCongress, setCurrentCongress] = React.useState<number | null>(null);
  const { pending, begin } = usePendingCards();
  const [followError, setFollowError] = React.useState("");

  React.useEffect(() => subscribePersonalizedChanges(({ kind, source }) => {
    // A recommendation updates its own button. Rebuild the collection on
    // revalidation or remount so it cannot shift the row being used.
    if (ready && kind === "tracking" && source === "recommendation") return;
    if (kind === "revalidate" || kind === "tracking") { setAttempt(value => value + 1); return; }
    setTracking(null); setMembership(null); setSignedIn(false); setIsSuperuser(false); setReady(false); setError("");
    onSessionChange?.();
    setFollowError("");
    setAttempt(value => value + 1);
  }), [onSessionChange, ready]);

  React.useEffect(() => {
    let live = true;
    const scope = capturePersonalizedScope();
    void (async () => {
      try {
        const session = await dashboardSession();
        if (!live || !isPersonalizedScopeCurrent(scope)) return;
        setSignedIn(Boolean(session));
        if (!session) { setTracking(null); setMembership(null); }
        setIsSuperuser(session?.user.is_superuser === true);
        setCurrentCongress(session?.current_congress ?? null);
        if (session && membershipOnly) {
          const result = await getMyTracking({ scope, membershipOnly: true });
          if (live && isPersonalizedScopeCurrent(scope)) setMembership(result);
        } else if (session) {
          const result = await dashboardValue("tracking", () => getMyTracking({ scope }));
          if (live && isPersonalizedScopeCurrent(scope)) setTracking(result);
        }
        if (live) setError("");
      } catch { if (live && isPersonalizedScopeCurrent(scope)) { setError("Couldn’t refresh your bills."); } }
      finally { if (live && isPersonalizedScopeCurrent(scope)) setReady(true); }
    })();
    return () => { live = false; };
  }, [attempt, membershipOnly]);

  const currentTracking = membershipOnly ? membership : tracking;
  const followed = new Set(currentTracking?.bills.map(item => item.bill.id));
  async function toggleFollow(bill: BillListItem) {
    if (!currentTracking) return;
    const finish = begin(bill.id);
    if (!finish) return;
    const scope = capturePersonalizedScope();
    setFollowError("");
    try {
      let saved: TrackingSummary["bills"][number] | null = null;
      if (followed.has(bill.id)) await untrackBill(bill.id, { scope });
      else saved = await trackBill(bill.id, { scope });
      if (capturePersonalizedScope().sessionGeneration === scope.sessionGeneration) {
        if (membershipOnly) {
          setMembership(current => current && ({
            ...current,
            bills: [...current.bills.filter(item => item.bill.id !== bill.id), ...(saved ? [saved] : [])],
          }));
        } else setTracking(current => {
          if (!current) return current;
          const bills = current.bills.filter(item => item.bill.id !== bill.id);
          return { ...current, bills: saved ? [...bills, saved] : bills };
        });
      }
    } catch { if (capturePersonalizedScope().sessionGeneration === scope.sessionGeneration) setFollowError("Your follow preference was not saved. Please try again."); }
    finally { finish(); }
  }
  return { tracking, hasTracking: Boolean(currentTracking), signedIn, isSuperuser, ready, error, followError, currentCongress, followed, pending, toggleFollow, retry: () => setAttempt(value => value + 1) };
}

export default function DashboardBillCard({ bill, controls, onOpen, accentTopicId, sponsorState }: {
  bill: BillListItem;
  controls: ReturnType<typeof useDashboardBillTracking>;
  onOpen?: (bill: BillListItem) => void;
  accentTopicId?: number;
  sponsorState?: string;
}) {
  const { hasTracking, signedIn, ready, error, followed, pending, toggleFollow } = controls;
  return <DashboardBillReader bill={bill}>{(summary, enhance, feedback, currentBill) =>
    <BillCard bill={currentBill} summary={summary} feedback={feedback} accentTopicId={accentTopicId}
      sponsorState={sponsorState} onOpen={onOpen && (() => onOpen(currentBill))}
      footer={signedIn && hasTracking ? <div className="bill-card-actions"><button aria-disabled={pending.has(currentBill.id)} aria-pressed={followed.has(currentBill.id)} onClick={() => void toggleFollow(currentBill)}>{followed.has(currentBill.id) ? "Unfollow" : "Follow"}</button>{enhance}</div> : error ? <span>Following unavailable</span> : !ready ? <button disabled aria-busy="true" aria-label="Loading follow status">Follow</button> : <Link href="/login">Log in to follow</Link>} />}
  </DashboardBillReader>;
}
