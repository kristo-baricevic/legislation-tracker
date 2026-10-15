# Legislator profiles: independent plan review

Reviewed by the independent `profile_plan_review` agent against baseline `4c5302bcbd36c19fb1d04dcb1c4adb27fe38b4f7` and authoritative provider documentation. Review was read-only. All shell inspections used RTK. No product code or product tests were involved.

## Pass 1: repair before approval

1. P1: personalized request/cache scope must include account/session and explicit-interest generations. Repaired with abort/clear lifecycle, private/no-store responses, and abort-aware authenticated reads with replay checks.
2. P2: House legislation-linked 118/119 provider restrictions must not apply to Senate. Repaired with chamber-specific provider scope and unknown historical Senate availability.
3. P2: legacy insight checks do not measure member-position completeness. Repaired with separate direct stored-record counts, provider scope, legacy service-window check scope, and member completeness unknown.
4. P2: mutable offset pagination can skip records during inserts/deletes/date/activity changes. Repaired with live page replacement, Previous/Next, explicit live-data notice and refresh/reset; no accumulated completeness claim.
5. P2: historical Congress/chamber context was ambiguous. Repaired with bill.session, vote.congress/actual chamber, directory current-Congress context, optional chamber, separately labeled latest roster fields and historical observations, including unknown/multiple chambers.
6. P2: existing BillDeckModal must join shared modal ownership. Repaired with an explicit integration edit, sibling portals, unique title IDs, top-only handlers, central scroll lock and connected-opener fallback.
7. P2: stored source URLs may require credentials or point at a session list. Repaired with validated public Clerk/Senate roll-call link projections and explicit roll-call/session-list/unavailable kinds.
8. P2: TextExtracts does not establish exact excerpt revision. Repaired with excerpt-fetched and article-revision-observed metadata, no immutable revision claim.

An additional nullable list bill-source projection was reviewed: strict supported federal HR/S identity and fixed-host Congress.gov URL, explicit derived-source label, unsupported links unavailable, no per-row fetch or API credential forwarding. No actionable finding remained there.

## Pass 2: follow mutation lifecycle

One P1 remained: account-A follow could be sent/replayed under account B while baseline authPost waited for CSRF or refreshed authentication. Repaired by requiring captured auth generation and AbortSignal for the profile follow/unfollow mutation, checks after CSRF and before initial send, before refresh and immediately before replay, no replay across a generation change, and tests asserting no POST for B. An already sent A request is not represented as undone by cancellation.

## Pass 3: final verdict

The reviewer's final report:

> No actionable plan findings remain in the final proposal.
>
> The follow-mutation repair now covers CSRF setup, initial send, authentication refresh/replay, cancellation, and account-generation changes. All earlier findings are resolved. The proposal is ready for parent approval.
>
> Baseline remains 4c5302b; only the proposal is untracked. This was a read-only plan review, with no product tests run. Wikipedia resolver transport and the recommendation DTO remain explicit implementation prerequisites.

The parent subsequently approved implementation within the reviewed existing stack, without new dependencies/model migrations, and approved bounded local public Wikipedia reads. Implementation/review/test evidence is recorded in `legislator-profiles-implementation.md`. No authorization exists for push, deployment, shared DB migrations, paid services, new credentials or production ingestion.
