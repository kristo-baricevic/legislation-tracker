"use client";
import React from "react";
import Link from "next/link";
import { ApiError, capturePersonalizedScope, isPersonalizedScopeCurrent, trackBill, type BillListItem } from "@/lib/api";
import { getBillRecommendations, type BillRecommendationReason } from "@/lib/recommendations";
import { useRecommendations } from "./useRecommendations";
import { RecommendationState } from "./RecommendationState";
import styles from "./recommendations.module.css";

function reasonText(reason: BillRecommendationReason) {
  if (reason.kind === "followed_topic") return <>Tagged <Link href={`/bills?topic_id=${reason.topic_id}`}>{reason.name}</Link>, a topic you follow.</>;
  if (reason.kind === "followed_bill_topic") return <>Shares the recorded topic {reason.name} with <Link href={`/bills/${reason.seed_bill_id}`}>{reason.seed_bill_number} / {reason.seed_session}</Link>, a bill you follow.</>;
  if (reason.kind === "followed_bill_sponsor") return <>Sponsored by {reason.name}, who also sponsored <Link href={`/bills/${reason.seed_bill_id}`}>{reason.seed_bill_number} / {reason.seed_session}</Link>, a bill you follow.</>;
  return <>{reason.relation === "cosponsor" ? "Actively cosponsored" : "Sponsored"} by <Link href={`/representatives/${reason.representative_id}`}>{reason.name}</Link>, a representative you follow.</>;
}
function dateLabel(value: string | null) {
  if (!value) return "Not recorded";
  const date = new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00` : value);
  return Number.isNaN(date.getTime()) ? "Not recorded" : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
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
    <p className={styles.note}>Based on topics, representatives and bills you explicitly follow. Search filters do not change your followed interests.</p>
    {state.data?.results.length ? <>
      <div className={styles.row} role="region" aria-label="Recommended bills" tabIndex={0}>{state.data.results.map(item => <article className={styles.card} key={item.bill.id}>
        <div className={styles.bar} aria-hidden="true" /><div className={styles.body}>
          <p className={styles.meta}>{item.bill.bill_number} / {item.bill.session} · {item.bill.status.replaceAll("_", " ") || "Status unavailable"}</p>
          <h3><a href={`/bills/${item.bill.id}`} onClick={event => { if (!event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && onOpenBill(item.bill) !== false) event.preventDefault(); }}>{item.bill.title}</a></h3>
          <ul className={styles.reasons} aria-label="Why recommended">{item.reasons.map((reason, index) => <li key={index}>{reasonText(reason)}</li>)}</ul>
          <div className={styles.footer}><span>Last action<br /><time>{dateLabel(item.bill.last_action_at)}</time></span>
            <button className={styles.action} aria-label={`Follow bill ${item.bill.bill_number} / ${item.bill.session}`} disabled={pending?.generation === generation} onClick={() => void follow(item.bill.id)}>{pending && pending.generation === generation && pending.id === item.bill.id ? "Saving…" : "Follow bill"}</button>
          </div>
        </div>
      </article>)}</div>
      <p className={styles.note}>Ingested bills only. {state.data.candidate_pool_truncated || state.data.ranking_limit_reached ? "This is a bounded selection of matching bills." : ""}</p>
      {Boolean(state.data.unsupported_follow_types.length) && <p className={styles.note}>The General legislation fallback topic is excluded because it does not describe a specific subject.</p>}
      {state.data.next_cursor && <button className={styles.action} disabled={paging === generation} onClick={() => void more()}>{paging === generation ? "Loading…" : "More recommendations"}</button>}
    </> : <RecommendationState {...state} empty={state.data?.empty_reason} />}
    {error && error.generation === generation && error.text && <p role="alert">{error.text}</p>}
  </section>;
}
const getBillRecommendationsFirst = (options: Parameters<typeof getBillRecommendations>[1]) => getBillRecommendations({}, options);
