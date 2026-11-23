# Committees Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Single-agent execution only.

**Goal:** Show committee members and their introduced bills in two simple horizontal rows per committee.

**Architecture:** Extend the existing committee API with Congress-scoped membership data and independently paginated bills. Reuse existing avatar, tooltip and bill-card components in a new client page.

**Tech Stack:** Django REST Framework, Next.js, React, existing CSS modules and test tooling.

**Spec:** `docs/superpowers/specs/2026-11-23-committees-design.md`

## Global Constraints

- Keep copy minimal; no explanatory paragraphs or raw metadata.
- Leadership labels come from stored roles, never inferred from membership rank.
- Bills are distinct primary-sponsored bills, not cosponsored bills, from the same Congress.
- No paid API calls, data deletion, new dependencies or subagents.

## Review Focus

- Historical memberships must not leak into the current Congress.
- Multiple member associations must not duplicate bill cards.
- A failed later page must retain existing cards and offer retry.
- A filter change must ignore responses from the previous scope.
- Missing portraits, empty rosters and long names must remain usable on mobile.

### Task 1: Scoped committee API

Files: modify `legislation-tracker-backend/apps/congress/views.py` and `serializers.py`; create `apps/congress/tests/test_committee_directory.py`.

Interfaces: `GET /api/committees/?congress=<n>&chamber=<house|senate|joint>&page=<n>` returns paginated committee metadata plus `members`, each with representative details and role. `GET /api/committees/<id>/introduced-bills/?congress=<n>&page=<n>` returns the existing paginated BillListSerializer shape, with card summaries.

- [ ] Write tests for chamber filtering, Congress isolation, leadership roles, primary-sponsored-only bills, distinct results and deterministic latest-introduced ordering.
- [ ] Run `rtk proxy .venv/bin/pytest apps/congress/tests/test_committee_directory.py -q`; confirm expected failures.
- [ ] Add validated query serializers; prefetch scoped memberships and representatives. Filter introduced bills by membership subquery and Congress; retain the existing bill-card serialization and summary enrichment.
- [ ] Run targeted tests and the backend suite; report any existing failures separately.

### Task 2: Committees page and navigation

Files: create client `app/committees/page.tsx`, `app/committees/committees.module.css`, `lib/committees.ts`, `tests/components/committees.test.tsx`; modify `app/components/AuthNav.tsx`.

Interfaces: typed `getCommittees(congress, chamber, page, signal)` and `getCommitteeBills(id, congress, page, signal)` consume Task 1 endpoints. Page uses the existing RepresentativeAvatarBadge and BillCard components, passing portrait data to prevent per-avatar fetches.

- [ ] Read the installed Next.js routing/client-component guides before implementation.
- [ ] Write failing tests for navigation, two rows, role labels, profile/bill links, chamber filter, appended bill pages, retry retention and stale-response suppression.
- [ ] Implement the page using the app's current Congress default. Load committee pages incrementally; mount bill loaders when sections approach the viewport. Use a horizontal sentinel for subsequent bill pages, with in-row loading/retry space.
- [ ] Add Committees to navbar active-link handling. Use existing fonts/colors and stable-width cards; retain keyboard-scrollable rows and initials fallback.
- [ ] Run client test suite and production build.

### Task 3: Runtime verification

- [ ] Build and reload only affected Docker services; preserve databases and workers not requiring new code.
- [ ] Check real committees and roles on localhost:13000/committees; verify links and distinct sponsored bills against the API.
- [ ] Visually check desktop/mobile, horizontal pagination, filter changes, empty states and loading stability.
- [ ] Inspect the final diff for query fan-out, accessibility and scope errors; correct regressions before reporting completion.

No commit or PR is requested for this feature yet; leave changes in the current checkout and preserve unrelated edits.
