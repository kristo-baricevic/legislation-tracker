"use client";
import React from "react";
import { isPersonalizedScopeCurrent, trackLegislator } from "@/lib/api";
import { getRepresentativeRecommendations } from "@/lib/recommendations";
import RepresentativeAvatarBadge from "./RepresentativeAvatarBadge";
import { useRecommendations } from "./useRecommendations";
import { RecommendationState } from "./RecommendationState";
import styles from "./recommendations.module.css";
import cards from "./tracked-legislators.module.css";
import { LegislatorCard } from "./TrackedLegislators";

export interface RepresentativeRecommendationsProps {
  renderName?: (representative: { id: number; name: string; chamber: string }) => React.ReactNode;
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
      <div className={cards.row} role="region" aria-label="Recommended representatives" tabIndex={0}>{state.data.results.map(item => <LegislatorCard key={item.representative_id} representative={{ ...item.topic_activity_evidence.representative, id: item.representative_id, name: item.name, bioguide_id: item.bioguide_id }} renderName={renderName} activity={item.topic_activity_evidence}
        actions={<button className={styles.action} aria-label={`Follow representative ${item.name}`} disabled={pending !== null} onClick={() => void follow(item.representative_id)}>{pending === item.representative_id ? "Saving…" : "Follow"}</button>}>
        <div className={cards.similarAvatars}>{item.reasons.filter(reason => reason.kind === "followed_representative_activity").map(reason => <RepresentativeAvatarBadge key={reason.representative_id} id={reason.representative_id} name={reason.name.replace(/\s*\[[^\]]*\]\s*$/, "")} notes={["Similar to this representative in recorded topic activity"]} />)}</div>
      </LegislatorCard>)}</div>
    </> : <RecommendationState {...state} kind="representatives" empty={state.data?.empty_reason} />}
    {error && error.session === state.scope?.sessionGeneration && error.interest === state.scope?.interestGeneration && error.text && <p role="alert">{error.text}</p>}
  </section>;
}
