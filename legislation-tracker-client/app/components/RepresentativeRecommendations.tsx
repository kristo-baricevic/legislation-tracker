"use client";
import React from "react";
import Link from "next/link";
import { isPersonalizedScopeCurrent, trackLegislator } from "@/lib/api";
import { getRepresentativeRecommendations, type RepresentativeRecommendationReason } from "@/lib/recommendations";
import { useRecommendations } from "./useRecommendations";
import { RecommendationState } from "./RecommendationState";
import styles from "./recommendations.module.css";

export interface RepresentativeRecommendationsProps {
  renderName?: (representative: { id: number; name: string; chamber: string }) => React.ReactNode;
}
function why(reason: RepresentativeRecommendationReason) {
  if (reason.kind === "followed_topic") return <>Recorded sponsorship or active cosponsorship in {reason.name}, a topic you follow.</>;
  return <>Recorded topic overlap with <Link href={`/representatives/${reason.representative_id}`}>{reason.name}</Link>, whom you follow: {reason.shared_topics.map(topic => topic.name).join(", ")}.</>;
}
export default function RepresentativeRecommendations({ renderName }: RepresentativeRecommendationsProps) {
  const heading = React.useRef<HTMLHeadingElement>(null);
  const section = React.useRef<HTMLElement>(null);
  const restoreFocus = React.useRef(false);
  const invalidate = React.useCallback(() => {
    if (restoreFocus.current || section.current?.contains(document.activeElement)) heading.current?.focus();
    restoreFocus.current = false;
  }, []);
  const state = useRecommendations(getRepresentativeRecommendations, invalidate);
  const [pending, setPending] = React.useState<number | null>(null);
  const [error, setError] = React.useState<{ text: string; session: number; interest: number } | null>(null);
  async function follow(id: number) {
    const scope = state.scope;
    if (!scope || !isPersonalizedScopeCurrent(scope)) return;
    restoreFocus.current = true;
    setPending(id); setError(null);
    try { await trackLegislator(id, { ...state.requestOptions(), scope }); }
    catch (error) { if (isPersonalizedScopeCurrent(scope)) setError({ text: error instanceof Error && error.name === "AbortError" ? "" : "Your follow was not saved. Try again.", session: scope.sessionGeneration, interest: scope.interestGeneration }); }
    finally { if (isPersonalizedScopeCurrent(scope)) restoreFocus.current = false; setPending(null); }
  }
  return <section ref={section} className={styles.section} aria-labelledby="representative-recommendations-title">
    <div className={styles.heading}><h2 ref={heading} tabIndex={-1} id="representative-recommendations-title">Representatives to discover</h2><button className={styles.action} disabled={state.loading} onClick={state.retry}>Refresh representative recommendations</button></div>
    <p className={styles.note}>Up to five current representatives from your followed topics and representatives’ recorded sponsorship activity. Vote positions do not affect this order.</p>
    {state.data?.results.length ? <>
      <div className={styles.row} role="region" aria-label="Recommended representatives" tabIndex={0}>{state.data.results.map(item => <article className={styles.card} key={item.representative_id}>
        <div className={styles.bar} aria-hidden="true" /><div className={styles.body}>
          <p className={styles.meta}>{item.topic_activity_evidence.representative.chamber} · {item.topic_activity_evidence.representative.state}</p>
          <h3>{renderName ? renderName({ id: item.representative_id, name: item.name, chamber: item.topic_activity_evidence.representative.chamber }) : <Link href={`/representatives/${item.representative_id}`}>{item.name}</Link>}</h3>
          <ul className={styles.reasons} aria-label="Why recommended">{item.reasons.map((reason, index) => <li key={index}>{why(reason)}</li>)}</ul>
          <p className={styles.meta}>{item.topic_activity_evidence.channels.sponsor.raw_observation_count} sponsored · {item.topic_activity_evidence.channels.active_cosponsor.raw_observation_count} actively cosponsored bills in the recorded window.</p>
          <div className={styles.footer}><span>Ingested activity</span><button className={styles.action} aria-label={`Follow representative ${item.name}`} disabled={pending !== null} onClick={() => void follow(item.representative_id)}>{pending === item.representative_id ? "Saving…" : "Follow representative"}</button></div>
        </div>
      </article>)}</div>
      <p className={styles.note}>Activity capture: {state.data.activity_as_of ? new Date(state.data.activity_as_of).toLocaleString() : "unavailable"}. History and topic coverage may be incomplete. These are discovery suggestions, with no party or voting preference.</p>
      {Boolean(state.data.unsupported_follow_types.length) && <p className={styles.note}>The General legislation fallback topic is excluded because it does not describe a specific subject.</p>}
    </> : <RecommendationState {...state} kind="representatives" empty={state.data?.empty_reason} />}
    {error && error.session === state.scope?.sessionGeneration && error.interest === state.scope?.interestGeneration && error.text && <p role="alert">{error.text}</p>}
  </section>;
}
