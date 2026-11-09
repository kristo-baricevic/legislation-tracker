"use client";
import React from "react";
import Link from "next/link";
import { ApiError, capturePersonalizedScope, isPersonalizedScopeCurrent, trackBill, type BillListItem } from "@/lib/api";
import RepresentativeAvatarBadge from "./RepresentativeAvatarBadge";
import CardTooltip from "./CardTooltip";
import { getBillRecommendations, type BillRecommendationReason } from "@/lib/recommendations";
import { useRecommendations } from "./useRecommendations";
import { RecommendationState } from "./RecommendationState";
import StageTrack from "./StageTrack";
import { dateLabel, readable } from "@/lib/bill-format";
import { stageFor } from "@/lib/bill-stage";
import { topicColor } from "@/lib/bill-format";
import styles from "./recommendations.module.css";


function ReasonBadges({ reasons }: { reasons: BillRecommendationReason[] }) {
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
  return <ul className={styles.reasonBadges} aria-label="Why recommended">{[...badges].map(([key, badge]) => <li key={key}>
    {badge.representativeId !== null ? <RepresentativeAvatarBadge id={badge.representativeId} name={badge.label} notes={[...badge.notes]} /> : <CardTooltip text={[...badge.notes].join("\n")}><Link className={styles.topicPill} href={badge.href} aria-description={[...badge.notes].join(". ")}>{badge.label}</Link></CardTooltip>}
  </li>)}</ul>;
}
export default function BillRecommendations({ onOpenBill, onDismissBill }: { onOpenBill: (bill: BillListItem) => boolean | void; onDismissBill?: () => void }) {
  const heading = React.useRef<HTMLHeadingElement>(null);
  const section = React.useRef<HTMLElement>(null);
  const restoreFocus = React.useRef(false);
  const invalidate = React.useCallback(() => {
    const ownsFocus = restoreFocus.current || section.current?.contains(document.activeElement);
    restoreFocus.current = false;
    onDismissBill?.();
    if (ownsFocus) heading.current?.focus();
  }, [onDismissBill]);
  const state = useRecommendations(getBillRecommendationsFirst, invalidate);
  React.useEffect(() => () => { onDismissBill?.(); }, [onDismissBill]);
  const [pending, setPending] = React.useState<{ id: number; generation: string } | null>(null);
  const [error, setError] = React.useState<{ text: string; generation: string } | null>(null);
  const [paging, setPaging] = React.useState<string | null>(null);
  const generation = state.scope ? `${state.scope.sessionGeneration}:${state.scope.interestGeneration}` : "";
  async function follow(id: number) {
    const scope = state.scope ?? capturePersonalizedScope();
    if (!isPersonalizedScopeCurrent(scope)) return;
    restoreFocus.current = true;
    const key = `${scope.sessionGeneration}:${scope.interestGeneration}`;
    setPending({ id, generation: key }); setError(null);
    try { await trackBill(id, { ...state.requestOptions(), scope }); }
    catch (error) { if (isPersonalizedScopeCurrent(scope)) setError({ text: error instanceof Error && error.name === "AbortError" ? "" : "Your follow was not saved. Try again.", generation: key }); }
    finally { if (isPersonalizedScopeCurrent(scope)) { restoreFocus.current = false; setPending(null); } }
  }
  async function more() {
    const scope = state.scope, cursor = state.data?.next_cursor;
    if (!scope || !cursor || paging === generation) return;
    restoreFocus.current = true;
    setPaging(generation); setError(null);
    try {
      const page = await getBillRecommendations({ cursor }, { ...state.requestOptions(), scope });
      state.update(scope, previous => ({ ...page, results: [...new Map([...previous.results, ...page.results].map(item => [item.bill.id, item])).values()] }));
    } catch (error) {
      if (isPersonalizedScopeCurrent(scope)) {
        if (error instanceof ApiError && [409, 410].includes(error.status)) state.retry();
        else setError({ text: "More recommendations could not be loaded. Try again.", generation });
      }
    } finally { if (isPersonalizedScopeCurrent(scope)) { restoreFocus.current = false; setPaging(null); } }
  }
  return <section ref={section} className={styles.section} aria-labelledby="bill-recommendations-title">
    <div className={styles.heading}><h2 ref={heading} tabIndex={-1} id="bill-recommendations-title">Bills to discover</h2><button className={styles.action} disabled={state.loading} onClick={state.retry}>Refresh bill recommendations</button></div>
    {state.data?.results.length ? <>
      <div className={styles.row} role="region" aria-label="Recommended bills" tabIndex={0}>{state.data.results.map(item => <article className={styles.card} key={item.bill.id} style={{ "--topic": topicColor(item.bill.topics[0]?.topic_id ?? 0) } as React.CSSProperties}>
        <div className={styles.bar} aria-hidden="true" /><div className={styles.body}>
          <p className={styles.meta}>{item.bill.topics[0]?.name && <span className={styles.topicName}>{item.bill.topics[0].name}</span>}{item.bill.bill_number} / {item.bill.session}</p>
          <h3><a href={`/bills/${item.bill.id}`} onClick={event => { if (!event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && onOpenBill(item.bill) !== false) event.preventDefault(); }}>{item.bill.title}</a></h3>
          {stageFor(item.bill.status) ? <StageTrack stage={stageFor(item.bill.status)!} color={topicColor(item.bill.topics[0]?.topic_id ?? 0)} /> : <p className={styles.note}>{readable(item.bill.status || "Status unavailable")}</p>}
          <ReasonBadges reasons={item.reasons} />
          <div className={styles.footer}><span>Last action<br /><time>{dateLabel(item.bill.last_action_at)}</time></span>
            <button className={styles.action} aria-label={`Follow bill ${item.bill.bill_number} / ${item.bill.session}`} disabled={pending?.generation === generation} onClick={() => void follow(item.bill.id)}>{pending && pending.generation === generation && pending.id === item.bill.id ? "Saving…" : "Follow bill"}</button>
          </div>
        </div>
      </article>)}</div>
      {Boolean(state.data.unsupported_follow_types.length) && <p className={styles.note}>The General legislation fallback topic is excluded because it does not describe a specific subject.</p>}
      {state.data.next_cursor && <button className={styles.action} disabled={paging === generation} onClick={() => void more()}>{paging === generation ? "Loading…" : "More recommendations"}</button>}
    </> : <RecommendationState {...state} empty={state.data?.empty_reason} />}
    {error && error.generation === generation && error.text && <p role="alert">{error.text}</p>}
  </section>;
}
const getBillRecommendationsFirst = (options: Parameters<typeof getBillRecommendations>[1]) => getBillRecommendations({}, options);
