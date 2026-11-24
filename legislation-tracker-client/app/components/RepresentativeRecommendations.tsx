"use client";
import { useDashboardLoading } from "./DashboardLoading";
import DismissRecommendation from "./DismissRecommendation";
import LoadingSpinner from "@/app/components/LoadingSpinner";
import React from "react";
import { capturePersonalizedScope, getMyTracking, isPersonalizedScopeCurrent, trackLegislator, untrackLegislator } from "@/lib/api";
import { dashboardValue } from "@/lib/dashboard-cache";
import { getRepresentativeRecommendations, recommendationFilterQuery, type RecommendationFilters } from "@/lib/recommendations";
import RepresentativeAvatarBadge from "./RepresentativeAvatarBadge";
import { useRecommendations } from "./useRecommendations";
import { RecommendationState } from "./RecommendationState";
import styles from "./recommendations.module.css";
import cards from "./tracked-legislators.module.css";
import { LegislatorCard } from "./TrackedLegislators";

export interface RepresentativeRecommendationsProps {
  filters?: RecommendationFilters;
  renderName?: (representative: { id: number; name: string; chamber: string }) => React.ReactNode;
}
export default function RepresentativeRecommendations({ renderName, filters }: RepresentativeRecommendationsProps) {
  const filterQuery = recommendationFilterQuery({ ...filters, sort: undefined });
  const load = React.useCallback((options: Parameters<typeof getRepresentativeRecommendations>[0]) => getRepresentativeRecommendations(options, Object.fromEntries(new URLSearchParams(filterQuery))), [filterQuery]);
  const heading = React.useRef<HTMLHeadingElement>(null);
  const section = React.useRef<HTMLElement>(null);
  const restoreFocus = React.useRef(false);
  const invalidate = React.useCallback(() => {
    if (restoreFocus.current || section.current?.contains(document.activeElement)) heading.current?.focus({ preventScroll: true });
    restoreFocus.current = false;
  }, []);
  const state = useRecommendations(`rep-recommendations${filterQuery ? `:${filterQuery}` : ""}`, load, invalidate, true);
  const dashboardLoading = useDashboardLoading("representatives", state.loading);
  const [followed, setFollowed] = React.useState<Set<number>>(new Set());
  const [followedProfiles, setFollowedProfiles] = React.useState<import("@/lib/api").TrackedLegislatorItem[]>([]);
  React.useEffect(() => {
    const scope = state.scope;
    if (!scope) { setFollowed(new Set()); setFollowedProfiles([]); return; }
    let live = true;
    void dashboardValue("tracking", () => getMyTracking({ scope })).then(tracking => {
      if (live && isPersonalizedScopeCurrent(scope)) { setFollowed(new Set(tracking.legislators.map(item => item.representative.id))); setFollowedProfiles(tracking.legislators); }
    }).catch(() => {});
    return () => { live = false; };
  }, [state.scope]);
  const [pending, setPending] = React.useState<number | null>(null);
  const [error, setError] = React.useState<{ text: string; session: number; interest: number } | null>(null);
  async function follow(id: number) {
    if (pending !== null) return;
    const scope = state.scope;
    if (!scope || !isPersonalizedScopeCurrent(scope)) return;
    restoreFocus.current = true;
    setPending(id); setError(null);
    try {
      const wasFollowed = followed.has(id);
      await (wasFollowed ? untrackLegislator : trackLegislator)(id, { ...state.requestOptions(), scope });
      if (capturePersonalizedScope().sessionGeneration === scope.sessionGeneration) setFollowed(previous => {
        const next = new Set(previous); if (wasFollowed) next.delete(id); else next.add(id); return next;
      });
    }
    catch (error) { if (isPersonalizedScopeCurrent(scope)) setError({ text: error instanceof Error && error.name === "AbortError" ? "" : "Your follow was not saved. Try again.", session: scope.sessionGeneration, interest: scope.interestGeneration }); }
    finally { if (isPersonalizedScopeCurrent(scope)) restoreFocus.current = false; setPending(null); }
  }
  return <section ref={section} className={cards.section} aria-labelledby="representative-recommendations-title">
    <div className={cards.heading}><h2 ref={heading} tabIndex={-1} id="representative-recommendations-title">Representatives to discover</h2><button className={styles.action} aria-label="Refresh representative recommendations" aria-disabled={state.loading} aria-busy={state.loading} onClick={state.retry}>Refresh</button></div>
    {!dashboardLoading && <LoadingSpinner reserveSpace active={state.loading} label="Loading recommendations…" />}
    {state.data && <div className="min-h-5 text-sm text-red-700" aria-live="polite">{state.error && <span role="alert">{state.error}</span>}</div>}
    {state.data?.results.length ? <>
      <div className={cards.row} role="region" aria-label="Recommended representatives" tabIndex={0}>{state.data.results.map(item => <LegislatorCard key={item.representative_id} representative={{ ...item.topic_activity_evidence.representative, id: item.representative_id, name: item.name, bioguide_id: item.bioguide_id }} facts={item.card} renderName={renderName} activity={item.topic_activity_evidence}
        headerAction={<DismissRecommendation kind="representative" id={item.representative_id} name={item.name} scope={state.scope} />}
        actions={<button className={styles.action} aria-label={`${followed.has(item.representative_id) ? "Unfollow" : "Follow"} representative ${item.name}`} aria-pressed={followed.has(item.representative_id)} aria-disabled={pending !== null} onClick={() => void follow(item.representative_id)}>{pending === item.representative_id ? "Saving…" : followed.has(item.representative_id) ? "Unfollow" : "Follow"}</button>}>
        <div className={cards.similarAvatars}>{item.reasons.filter(reason => reason.kind === "followed_representative_activity").map(reason => {
          const profile = followedProfiles.find(value => value.representative.id === reason.representative_id);
          return <RepresentativeAvatarBadge key={reason.representative_id} id={reason.representative_id} representative={profile ? {...profile.representative, image_url: profile.card?.portrait?.url ?? profile.representative.image_url} : {bioguide_id: ""}} name={reason.name.replace(/\s*\[[^\]]*\]\s*$/, "")} notes={["Similar to this representative in recorded topic activity"]} />;
        })}</div>
      </LegislatorCard>)}</div>
    </> : <RecommendationState {...state} kind="representatives" empty={state.data?.empty_reason} />}
    {error && error.session === state.scope?.sessionGeneration && error.interest === state.scope?.interestGeneration && error.text && <p role="alert">{error.text}</p>}
  </section>;
}
