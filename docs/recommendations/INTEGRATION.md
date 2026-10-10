# Integration and final source review

Recommendation source is an isolated clone on `codex/follow-crossover-recommendations` above dashboard baseline `4c5302bcbd36c19fb1d04dcb1c4adb27fe38b4f7`. It must be integrated with profile commit `2540b9ec8382ba0d728fb7cbe5752625c5a947e5` and telemetry commit `aac9aa3479daa6bae0201f606e81262b442ad716` in a separate clean integration checkout. No files were copied into another agent's dirty checkout, and no shared migrations or live ingestion were run.

## Exact exports and routes

- `apps.accounts.recommendations`: `load_profile(user_id)`, `candidate_query(profile)`, `diverse_order(candidates, limit=60)`; algorithm `explicit-facets-mmr-v1`.
- `apps.congress.topic_activity`: `representative_topic_activity(representative_id, *, captured_at=None, policy=None)`; `representative_activity_catalog(*, captured_at=None, policy=None)`; `ActivityPolicy` defaults. The first helper returns `representative-topic-activity-v1`, raises `Representative.DoesNotExist` when absent, and never returns internal ranking vectors.
- Private routes registered in `apps/accounts/urls.py`: `/api/tracking/recommendations/` and `/api/tracking/representative-recommendations/`.
- The profile branch owns strict public `/api/representatives/{id}/topic-activity/` and its wrapper/import. It calls the helper with `captured_at=timezone.now()`; this source does not duplicate the wrapper.
- Client exact DTOs/functions are in `lib/recommendations.ts`: `BillRecommendationsPage`, `BillRecommendationReason`, `RepresentativeRecommendationsResponse`, `RepresentativeTopicActivity`, `getBillRecommendations`, `getRepresentativeRecommendations`, and `getRepresentativeTopicActivity`. Activities retain their own rolling window regardless of profile Congress/chamber controls.

## Generation contract

```ts
// lib/personalized-scope.ts; public exports also reexported from lib/api.ts
interface PersonalizedScope {
  sessionGeneration: number;
  interestGeneration: number;
}
interface PersonalizedRequestOptions {
  signal?: AbortSignal;
  scope?: PersonalizedScope;
}
capturePersonalizedScope(): PersonalizedScope;
isPersonalizedScopeCurrent(scope: PersonalizedScope): boolean;
subscribePersonalizedChanges(listener: (change: {
  kind: 'session' | 'tracking' | 'revalidate'; scope: PersonalizedScope;
}) => void): () => void;
```

`getSession`, `getMyTracking`, all six bill/topic/legislator follow/unfollow helpers, and recommendation reads accept these options. Central authenticated requests default to a captured scope for older callers. UI owners must still cancel/clear their own private state on changes; default API guards alone cannot clear a previously rendered state. `assertPersonalizedScope` is exported from `lib/personalized-scope.ts` for direct boundary assertions. A stale/aborted scope rejects with `AbortError`. Tracking helpers announce an interest generation only after a successful, still-owned response; the announcement intentionally invalidates that request's old scope. Do not optimistically apply its returned payload after that invalidation.

## Profile rendering seam

The profile branch exports `ProfileScope = { representativeId: number; congress: number; chamber?: 'house'|'senate' }`, `LegislatorName` props `{ id: number|null; name: string; congress: number; chamber?: 'house'|'senate' }`, and `ProfileProvider`'s optional `renderActivity(scope): ReactNode`.

This branch's default `RepresentativeActivity` takes `{ scope: { representativeId:number; congress:number; chamber?:'house'|'senate' } }`, structurally matching `ProfileScope`. Add a **client** wrapper, then use it from the server RootLayout:

```tsx
'use client';
import type { ReactNode } from 'react';
import ProfileProvider from './ProfileProvider';
import RepresentativeActivity from './RepresentativeActivity';

export default function ProfileExperience({ children }: { children: ReactNode }) {
  return <ProfileProvider renderActivity={scope => <RepresentativeActivity scope={scope} />}>
    {children}
  </ProfileProvider>;
}
```

`RepresentativeRecommendations` and `RecommendationsPreview` accept optional `renderName: ({ id:number; name:string; chamber:string }) => ReactNode`. The integration owner can supply `LegislatorName` with the dashboard's verified current Congress and validate chamber to house/senate. Do not invent a Congress for a representative activity event. The default fallback remains a working public representative link.

## Dialog ownership and focus seam

`BillRecommendations` accepts `onOpenBill: (bill: BillListItem) => boolean|void` and optional `onDismissBill: () => void`. `RecommendationsPreview` forwards both. Returning `false` preserves the original title anchor navigation for cycle/depth limits.

`BillDeck.tsx` records recommendation ownership separately from ordinary public selections. Session/interest invalidation, refresh/cursor reset, or row removal closes only the recommendation-owned bill. It forwards the optional `fallbackFocus` prop through a conditional spread; profile `BillDeckModal`/`StackDialog` consume that approved seam after integration. The callback `focusRecommendationFallback()` tries `#bill-recommendations-title`, then `[data-recommendations-toggle]`, then `[data-dashboard-heading]`; targets must be connected, visible, and successfully focused. Headings use `tabIndex={-1}`.

The profile stack retains connected opener priority, confines nested restoration to its parent dialog, and reads the latest root callback if the root opener disappeared. No competing edits to StackDialog, ProfileProvider, or BillDeckModal exist in this branch. These combined behaviors require a final browser test after the parent integrates both branches.

## Files the parent must reconcile

1. `lib/api.ts`: retain generation guards and the profile branch's nullable sponsor identity/source `BillListItem` fields. Keep public profile helpers separate.
2. `BillDeck.tsx`: retain recommendation ownership, guarded private tracking/follow controls, persistent focus targets, telemetry controls, and profile opener integration. Profile owns BillDeckModal/StackDialog; telemetry owns its ingestion behavior.
3. Profile RootLayout/client provider renderer and recommendation representative-name adapter. Do not pass a function from a server component into a client provider.
4. Backend URL import/wrapper integration. There is no recommendation migration number to reconcile.
5. Make the preexisting ingestion aggregate fixture hermetic in the integration branch: its manual replay test mocks bill detail but leaves `bill_summaries` able to call upstream. Test-only repair belongs with the parent/telemetry integration.

## Concrete source excerpts for personal review

Final implementation uses the following actual core expressions, without a dependency or schema change:

```python
# apps/accounts/recommendations.py
POOL_LIMIT = 500
RANKING_LIMIT = 60
return 60 * bool(self.topics) + 40 * bool(
    self.representatives or self.sponsor_seeds
)
# candidate_query annotation
recommendation_n = 4 * (60 * recommendation_t + 40 * recommendation_r) \
    + profile.denominator * crossover
# diverse_order selection
Fraction(9, 10) * candidates[i]['score'] - Fraction(1, 10) * redundancy[i]
```

The annotation excerpt above is the equivalent SQL expression flattened for readability; inspect [recommendations.py](../../legislation-tracker-backend/apps/accounts/recommendations.py) for the actual `F(...)` ORM expression. Exact original code for the mutation boundary is:

```ts
async function trackingMutation<T>(request: Promise<T>, options: PersonalizedRequestOptions): Promise<T> {
  const scope = options.scope ?? capturePersonalizedScope();
  const result = await request;
  assertPersonalizedScope(scope, options.signal);
  announceTrackingChange();
  return result;
}
```

Review [recommendation_views.py](../../legislation-tracker-backend/apps/accounts/recommendation_views.py) for cursor ownership/expiry/cache-slot invariants, [recommendation_support.py](../../legislation-tracker-backend/apps/accounts/recommendation_support.py) for strict JSON/read isolation/private errors, [topic_activity.py](../../legislation-tracker-backend/apps/congress/topic_activity.py) for sparse evidence and passage selection, [personalized-scope.ts](../../legislation-tracker-client/lib/personalized-scope.ts) and [api.ts](../../legislation-tracker-client/lib/api.ts) for account transition/replay guards, and [BillDeck.tsx](../../legislation-tracker-client/app/components/BillDeck.tsx) for dialog ownership.
