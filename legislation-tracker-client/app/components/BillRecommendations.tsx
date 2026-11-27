"use client";
import RecommendationFollowButton from "./RecommendationFollowButton";
import { useDashboardLoading } from "./DashboardLoading";
import DismissRecommendation from "./DismissRecommendation";
import LoadingSpinner from "@/app/components/LoadingSpinner";
import React from "react";
import Link from "next/link";
import { ApiError, capturePersonalizedScope, isPersonalizedScopeCurrent, trackBill, untrackBill, getMyTracking, type BillListItem } from "@/lib/api";
import { dashboardValue } from "@/lib/dashboard-cache";
import RepresentativeAvatarBadge from "./RepresentativeAvatarBadge";
import CardTooltip from "./CardTooltip";
import { getBillRecommendations, recommendationFilterQuery, type RecommendationFilters, type BillRecommendationReason } from "@/lib/recommendations";
import { useRecommendations } from "./useRecommendations";
import { RecommendationState } from "./RecommendationState";
import DashboardBillReader from "./DashboardBillReader";
import StageTrack from "./StageTrack";
import { dateLabel, ordinal, readable } from "@/lib/bill-format";
import { stageFor } from "@/lib/bill-stage";
import { topicColor } from "@/lib/bill-format";
import styles from "./recommendations.module.css";


function ReasonBadges({ reasons, topic }: { reasons: BillRecommendationReason[]; topic?: BillListItem["topics"][number] }) {
  const badges = new Map<string, { label: string; href: string; representativeId: number | null; notes: Set<string> }>();
  for (const reason of reasons) {
    const isTopic = reason.kind === "followed_topic" || reason.kind === "followed_bill_topic";
    const key = isTopic ? `topic:${reason.topic_id}` : `representative:${reason.representative_id}`;
    const plainName = reason.name.replace(/^(Rep\.|Sen\.|Del\.|Resident Commissioner)\s*/i, "").replace(/\s*\[[^\]]*\]\s*$/, "");
    const label = isTopic ? reason.name : plainName.includes(",") ? `${plainName.split(",").slice(1).join(",").trim()} ${plainName.split(",")[0].trim()}` : plainName;
    const badge = badges.get(key) ?? { label, href: isTopic ? `/bills?topic_id=${reason.topic_id}` : `/representatives/${reason.representative_id}`, representativeId: isTopic ? null : reason.representative_id, notes: new Set<string>() };
    if (reason.kind === "followed_topic") badge.notes.add("You follow this topic");
    else if (reason.kind === "followed_bill_topic") badge.notes.add(`Shared topic with ${reason.seed_bill_number} (Congress ${reason.seed_session}), a bill you follow`);
    else if (reason.kind === "followed_bill_sponsor") badge.notes.add(`Introduced this bill and ${reason.seed_bill_number} (Congress ${reason.seed_session}), a bill you follow`);
    else badge.notes.add(`${reason.relation === "cosponsor" ? "Cosponsored" : "Introduced"} this bill · You follow this representative`);
    badges.set(key, badge);
  }
  return <div className={styles.contextBadges}>
    {topic && !badges.has(`topic:${topic.topic_id}`) && <Link className={styles.topicPill} href={`/bills?topic_id=${topic.topic_id}`}>{topic.name}</Link>}
    <ul className={styles.reasonBadges} aria-label="Why recommended">{[...badges].map(([key, badge]) => <li key={key}>
    {badge.representativeId !== null ? <RepresentativeAvatarBadge id={badge.representativeId} name={badge.label} notes={[...badge.notes]} /> : <CardTooltip text={[...badge.notes].join("\n")}><Link className={styles.topicPill} href={badge.href} aria-description={[...badge.notes].join(". ")}>{badge.label}</Link></CardTooltip>}
  </li>)}</ul></div>;
}
export default function BillRecommendations({ onOpenBill, onDismissBill, filters }: { onOpenBill: (bill: BillListItem) => boolean | void; onDismissBill?: () => void; filters?: RecommendationFilters }) {
  const filterQuery = recommendationFilterQuery(filters);
  const load = React.useCallback((options: Parameters<typeof getBillRecommendations>[1]) => getBillRecommendations({ filters: Object.fromEntries(new URLSearchParams(filterQuery)) }, options), [filterQuery]);
  const heading = React.useRef<HTMLHeadingElement>(null);
  const section = React.useRef<HTMLElement>(null);
  const restoreFocus = React.useRef(false);
  const invalidate = React.useCallback(() => {
    const ownsFocus = restoreFocus.current || section.current?.contains(document.activeElement);
    restoreFocus.current = false;
    onDismissBill?.();
    if (ownsFocus) heading.current?.focus({ preventScroll: true });
  }, [onDismissBill]);
  const state = useRecommendations(`bill-recommendations${filterQuery ? `:${filterQuery}` : ""}`, load, invalidate, true);
  const [followed, setFollowed] = React.useState<Set<number>>(new Set());
  React.useEffect(() => {
    const scope = state.scope;
    if (!scope) { setFollowed(new Set()); return; }
    let live = true;
    void dashboardValue("tracking", () => getMyTracking({ scope })).then(tracking => {
      if (live && isPersonalizedScopeCurrent(scope)) setFollowed(new Set(tracking.bills.map(item => item.bill.id)));
    }).catch(() => { /* Preserve confirmed state; a later refresh can retry. */ });
    return () => { live = false; };
  }, [state.scope]);
  React.useEffect(() => () => { onDismissBill?.(); }, [onDismissBill]);

  const [error, setError] = React.useState<{ text: string; generation: string } | null>(null);
  const [completedPage, setCompletedPage] = React.useState<string | null>(null);
  const [paging, setPaging] = React.useState<string | null>(null);
  const generation = state.scope ? `${state.scope.sessionGeneration}:${state.scope.interestGeneration}:${filterQuery}` : "";
  const dashboardLoading = useDashboardLoading("bills", state.loading && !state.data);
  async function follow(id: number) {
    const scope = state.scope ?? capturePersonalizedScope();
    if (!isPersonalizedScopeCurrent(scope)) return;

    const wasFollowed = followed.has(id);
    await (wasFollowed ? untrackBill : trackBill)(id, { ...state.requestOptions(), scope, source: "recommendation" });
    if (capturePersonalizedScope().sessionGeneration === scope.sessionGeneration) setFollowed(previous => {
      const next = new Set(previous); if (wasFollowed) next.delete(id); else next.add(id); return next;
    });
  }
  async function more() {
    const scope = state.scope, cursor = state.data?.next_cursor;
    if (!scope || !cursor || state.loading || paging === generation) return;
    restoreFocus.current = true;
    setPaging(generation); setError(null);
    try {
      const options = { ...state.requestOptions(), scope };
      let page;
      try {
        page = await getBillRecommendations({ cursor, filters }, options);
      } catch (error) {
        if (!(error instanceof ApiError) || ![409, 410].includes(error.status)) throw error;
        const shown = new Set(state.data?.results.map(item => item.bill.id));
        page = await getBillRecommendations({ filters }, options);
        while (page.next_cursor && page.results.every(item => shown.has(item.bill.id))) {
          page = await getBillRecommendations({ cursor: page.next_cursor, filters }, options);
        }
      }
      if (isPersonalizedScopeCurrent(scope)) setCompletedPage(page.next_cursor ? null : generation);
      state.update(scope, previous => ({ ...page, results: [...new Map([...previous.results, ...page.results].map(item => [item.bill.id, item])).values()] }));
    } catch (error) {
      if (isPersonalizedScopeCurrent(scope)) {
        setError({ text: "More recommendations could not be loaded. Try again.", generation });
      }
    } finally { if (isPersonalizedScopeCurrent(scope)) { restoreFocus.current = false; setPaging(null); } }
  }
  const visible = state.data?.results.filter(item => !state.dismissed?.has(item.bill.id)) ?? [];
  return <section ref={section} className={styles.section} aria-labelledby="bill-recommendations-title">
    <div className={styles.heading}><h2 ref={heading} tabIndex={-1} id="bill-recommendations-title">Bills to discover</h2><button className={styles.action} aria-disabled={state.loading} aria-busy={state.loading} onClick={state.retry}>Refresh bill recommendations</button></div>
    {!dashboardLoading && <LoadingSpinner reserveSpace active={state.loading} label="Loading recommendations…" />}
    {state.data && state.error && <p className="text-sm text-red-700" role="alert">{state.error}</p>}
    {visible.length && state.data ? <>
      <div className={styles.row} role="region" aria-label="Recommended bills" tabIndex={0}>{visible.map(item => <DashboardBillReader key={item.bill.id} bill={item.bill}>{(summary, enhance, feedback, currentBill) => <article className={styles.card} data-enhanced={currentBill.enhancement_status === "succeeded"} key={item.bill.id} style={{ "--topic": topicColor(item.bill.topics[0]?.topic_id ?? 0) } as React.CSSProperties}>
        <div className={styles.bar} aria-hidden="true" /><div className={styles.body}>
          <div className={styles.cardHeader}>
            <h3><a href={`/bills/${item.bill.id}`} onClick={event => { if (!event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && onOpenBill(currentBill) !== false) event.preventDefault(); }}>{item.bill.title || "Untitled bill"}</a></h3>
            <DismissRecommendation kind="bill" id={item.bill.id} name={item.bill.bill_number} scope={state.scope} onDismiss={state.dismiss} />
          </div>
          <div className={styles.identifiers}>
            <span>{item.bill.bill_number}</span>
            <span>{item.bill.jurisdiction === "federal" ? `${ordinal(item.bill.session)} Congress` : `Session ${item.bill.session}`}</span>
          </div>
          {summary}
          <ReasonBadges reasons={item.reasons} topic={item.bill.topics[0]} />
          {stageFor(item.bill.status) ? <StageTrack stage={stageFor(item.bill.status)!} color={topicColor(item.bill.topics[0]?.topic_id ?? 0)} /> : <p className={styles.note}>{readable(item.bill.status || "Status unavailable")}</p>}
          <div className={styles.footer}><span>Last action<br /><time>{dateLabel(item.bill.last_action_at)}</time></span>
            <div className="bill-card-actions"><RecommendationFollowButton key={state.scope?.sessionGeneration} label={`${followed.has(item.bill.id) ? "Unfollow" : "Follow"} bill ${item.bill.bill_number} / ${item.bill.session}`} followed={followed.has(item.bill.id)} onToggle={() => follow(item.bill.id)}>{followed.has(item.bill.id) ? "Unfollow" : "Follow bill"}</RecommendationFollowButton>{enhance}</div>
          </div>
          {feedback}
        </div>
      </article>}</DashboardBillReader>)}</div>
      {Boolean(state.data.unsupported_follow_types.length) && <p className={styles.note}>The General legislation fallback topic is excluded because it does not describe a specific subject.</p>}
    </> : <RecommendationState {...state} empty={state.data?.empty_reason ?? "no_matches"} />}
    {state.data?.next_cursor ? <button className={styles.action} disabled={paging === generation} aria-busy={paging === generation} onClick={() => void more()}>{paging === generation ? "Loading more…" : "More recommendations"}</button> : state.data && completedPage === generation ? <button className={styles.action} disabled>All recommendations shown</button> : null}
    {error && error.generation === generation && error.text && <p role="alert">{error.text}</p>}
  </section>;
}
