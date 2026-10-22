"use client";
import React from "react";
import Link from "next/link";
import { isPersonalizedScopeCurrent, trackLegislator } from "@/lib/api";
import { getRepresentativeRecommendations, type RepresentativeRecommendationReason } from "@/lib/recommendations";
import { useRecommendations } from "./useRecommendations";
import { RecommendationState } from "./RecommendationState";
import styles from "./recommendations.module.css";
import cards from "./tracked-legislators.module.css";
import { LegislatorCard } from "./TrackedLegislators";

export interface RepresentativeRecommendationsProps {
  renderName?: (representative: { id: number; name: string; chamber: string }) => React.ReactNode;
}
function topics(reasons: RepresentativeRecommendationReason[]) {
  const unique = new Map<number, string>();
  for (const reason of reasons) {
    if (reason.kind === "followed_topic") unique.set(reason.topic_id, reason.name);
    else for (const topic of reason.shared_topics) unique.set(topic.id, topic.name);
  }
  return [...unique];
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
  return <section ref={section} className={cards.section} aria-labelledby="representative-recommendations-title">
    <div className={cards.heading}><h2 ref={heading} tabIndex={-1} id="representative-recommendations-title">Representatives to discover</h2><button className={styles.action} aria-label="Refresh representative recommendations" disabled={state.loading} onClick={state.retry}>Refresh</button></div>
    {state.data?.results.length ? <>
      <div className={cards.row} role="region" aria-label="Recommended representatives" tabIndex={0}>{state.data.results.map(item => <LegislatorCard key={item.representative_id} representative={{ ...item.topic_activity_evidence.representative, id: item.representative_id, name: item.name, bioguide_id: item.bioguide_id }} renderName={renderName} showLatest={false}>
        <div className={cards.topics} aria-label="Matching topics">{topics(item.reasons).map(([id, name]) => <Link className={cards.pill} key={id} href={`/bills?topic_id=${id}`}>{name}</Link>)}</div>
        {item.reasons.filter(reason => reason.kind === "followed_representative_activity").map(reason => <p className={cards.similar} key={reason.representative_id}><span>Similar to</span>{" "}<Link href={`/representatives/${reason.representative_id}`}>{reason.name.replace(/\s*\[[^\]]*\]\s*$/, "")}</Link></p>)}
        <div className={cards.actions}><button className={styles.action} aria-label={`Follow representative ${item.name}`} disabled={pending !== null} onClick={() => void follow(item.representative_id)}>{pending === item.representative_id ? "Saving…" : "Follow"}</button></div>
      </LegislatorCard>)}</div>
    </> : <RecommendationState {...state} kind="representatives" empty={state.data?.empty_reason} />}
    {error && error.session === state.scope?.sessionGeneration && error.interest === state.scope?.interestGeneration && error.text && <p role="alert">{error.text}</p>}
  </section>;
}
