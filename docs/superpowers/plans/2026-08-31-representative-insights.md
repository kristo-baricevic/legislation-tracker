# Representative Insights Implementation Plan

> **Status (2026-08-31):** Implemented. Current-Congress source population remains an operational rollout step. This file retains the original TDD execution checklist as historical design context; current behavior and rollout instructions live in the linked specification and `legislation-tracker-backend/docs/PRODUCTION_OPERATIONS.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add current-Congress committee assignments, bill sponsorship/co-sponsorship histories, descriptive voting summaries, and an auditable two-representative comparison experience.

**Architecture:** Canonical roll-call and relationship tables are populated through persistent cursors and durable work from official Congress, House, and Senate sources. Analytics are computed from complete chamber roll calls, `VoteRecord`, sponsorship, co-sponsorship, and committee rows so every percentage has inspectable counts and coverage metadata. Current Congress plus forward ingestion is automatic; historical backfill is explicit and preview-first.

**Tech Stack:** Django 5, Django REST Framework, PostgreSQL, Celery, Requests/XML parsing, Next.js 16, React 19, TypeScript, Vitest/Testing Library, Playwright

**Spec:** `docs/superpowers/specs/2026-08-31-legislative-intelligence-design.md`

## Global Constraints

- Complete the shared `record_bill_change` and `Bill.last_activity_at` foundation from `2026-08-31-bill-discovery-search.md` before emitting relationship change events.
- Use `rtk` for every shell command and `apply_patch` for hand-authored edits.
- Do not infer ideology, party loyalty, intent, or effectiveness.
- Retire current committee memberships only after a complete chamber snapshot validates.
- Join people by Bioguide ID whenever the source provides it; never fuzzy-match names in an automatic write path.
- First-release comparisons accept exactly two representatives.
- Current Congress is the scheduled scope. Historical execution requires explicit `--congress` and `--execute`.
- Vote-derived claims require complete House and Senate roll-call discovery; a subset attached to known bills must never be labelled a voting pattern.
- Use `.venv/bin/python`, `.venv/bin/pytest`, and `.venv/bin/ruff` for backend commands, and run concurrency/coverage release gates against PostgreSQL.

---

## Task 1: Make complete roll calls first-class data

**Files:**

- Modify: `legislation-tracker-backend/apps/congress/models.py`
- Create: `legislation-tracker-backend/apps/congress/migrations/0007_vote_scope_and_identity.py`
- Modify: `legislation-tracker-backend/apps/congress/serializers.py`
- Modify: `legislation-tracker-backend/apps/congress/views.py`
- Modify: `legislation-tracker-backend/apps/ingestion/models.py`
- Create: `legislation-tracker-backend/apps/ingestion/migrations/0006_rollcallingestionstate_and_dependencies.py`
- Create: `legislation-tracker-backend/apps/congress/tests/test_vote_migration.py`
- Modify: `legislation-tracker-backend/apps/legislation/tests/test_public_api.py`

- [ ] Write migration/API tests with bill-linked, procedural, and nomination roll calls. Prove existing votes backfill Congress from `bill.session`, non-bill votes serialize with `bill=null`, stable identity rejects duplicate `(congress, chamber, session_number, roll_number)` rows, and blocked work is never leased/recovered/dead-lettered until a dependency explicitly wakes it.

- [ ] Add non-null `Vote.congress`, nullable `Vote.bill` with `SET_NULL`, `question`, and `source_url`. Replace bill-scoped uniqueness with `(congress, chamber, session_number, roll_number)` when session is present and `(congress, chamber, roll_number)` when absent. Use a staged migration: add nullable Congress, backfill from linked bills, validate every legacy row, make Congress non-null, then replace constraints. Preserve existing bill vote list/detail behavior and filter by `Vote.congress` rather than joining through bill.

- [ ] Add `RollCallIngestionState(congress, chamber, session_number, next_page_or_roll, discovered_roll_count, source_exhausted_at, source_updated_at, last_polled_at)` with uniqueness on Congress/chamber/session. State advances only in the same transaction that durably enqueues every roll call discovered from that source page; reaching the authoritative end stores its total and exhaustion time, while detecting a newer source head clears exhaustion until the new page set is queued. Add `IngestionWorkStatus.BLOCKED = "blocked"` and `IngestionWorkItem.dependency_keys = models.JSONField(default=list, blank=True)`; dispatch queries must exclude blocked rows.

- [ ] Normalize `VoteRecord.position` to `yes`, `no`, `present`, `not_voting`, and `other`; add `VoteRecord.raw_position` to preserve the exact source value for audit. Add indexes for Congress/chamber/date and representative/vote analytics.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/python manage.py makemigrations --check --dry-run"
rtk run "cd legislation-tracker-backend && DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/legislation_e2e .venv/bin/pytest apps/congress/tests/test_vote_migration.py apps/legislation/tests/test_public_api.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/congress legislation-tracker-backend/apps/ingestion legislation-tracker-backend/apps/legislation/tests/test_public_api.py
rtk git commit -m "feat(representatives): make roll calls first-class"
```

## Task 2: Add committee and legislative relationship models

**Files:**

- Modify: `legislation-tracker-backend/apps/congress/models.py`
- Create: `legislation-tracker-backend/apps/congress/migrations/0008_representative_insight_models.py`
- Modify: `legislation-tracker-backend/apps/congress/admin.py`
- Create: `legislation-tracker-backend/apps/congress/tests/test_insight_models.py`

- [ ] Write failing model tests for upstream uniqueness, parent committee constraints, one representative membership per committee/Congress, one cosponsor per bill/representative, withdrawals, current flags, and cascade/protect behavior.

- [ ] Add these models:

```python
class Committee(models.Model):
    system_code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    chamber = models.CharField(max_length=16, choices=CommitteeChamber.choices)
    committee_type = models.CharField(max_length=32, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)
    website_url = models.URLField(blank=True)
    is_current = models.BooleanField(default=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
```

Canonical `system_code` is the cross-source identity. Preserve source-specific raw values on relationship rows as `source_name` and `source_code` so normalization remains auditable without creating duplicate committees.

```python
class CommitteeMembership(models.Model):
    committee = models.ForeignKey(Committee, on_delete=models.CASCADE)
    representative = models.ForeignKey(Representative, on_delete=models.CASCADE)
    congress = models.PositiveSmallIntegerField()
    rank = models.PositiveSmallIntegerField(null=True, blank=True)
    role = models.CharField(max_length=24, choices=MembershipRole.choices)
    party_side = models.CharField(max_length=32, blank=True)
    source_name = models.CharField(max_length=32)
    source_code = models.CharField(max_length=32)
    is_current = models.BooleanField(default=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
```

Add `CommitteeChamber` values `house`, `senate`, and `joint`, plus the normalized membership-role enum. Add `BillCommittee` with bill, committee, `relationship_type`, `activity_name`, `source_name`, `source_code`, `source_updated_at`, timestamps, and uniqueness on `(bill, committee, relationship_type)`. Add `BillCosponsor` with bill, representative, `sponsorship_date`, `is_original_cosponsor`, nullable `withdrawn_at`, `source_updated_at`, timestamps, and uniqueness on `(bill, representative)`. Put these models in the congress app to keep official-member relationships together; use string model references to legislation models to avoid import cycles.

- [ ] Add indexes for representative/Congress, committee/Congress, bill/relationship, and current-roster queries. Register concise admin views that show IDs, source timestamps, and current flags.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/python manage.py makemigrations --check --dry-run"
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/congress/tests/test_insight_models.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/congress
rtk git commit -m "feat(representatives): add committee and cosponsor models"
```

## Task 3: Extend official clients for members, relationships, and votes

**Files:**

- Modify: `legislation-tracker-backend/apps/ingestion/congress_client.py`
- Modify: `legislation-tracker-backend/apps/ingestion/tests/test_congress_client.py`
- Create or update: JSON fixtures under `legislation-tracker-backend/apps/ingestion/tests/fixtures/`

- [ ] Add failing transport/contract tests for paginated bill cosponsors, committees, House vote lists/details, and member detail; a missing optional update date; HTTP timeout; rate limiting; malformed results; and pagination-loop protection.

- [ ] Implement exact typed, paginated methods: `bill_cosponsors(self, congress: int, bill_type: str, bill_number: str) -> Iterator[dict]`, `bill_committees(self, congress: int, bill_type: str, bill_number: str) -> Iterator[dict]`, `committee_detail(self, chamber: str, system_code: str) -> dict`, `member_detail(self, bioguide_id: str) -> dict`, `house_votes(self, congress: int, session_number: int, *, cursor: str | None) -> VotePage`, and `house_vote_detail(self, congress: int, session_number: int, roll_number: int) -> dict`.

Use the client's existing timeout, authentication, throttling, retry, and pagination primitives. Reject a next URL that leaves the configured API origin or repeats a visited URL.

- [ ] Normalize upstream date strings and relationship identities at the client boundary, but keep persistence outside the HTTP client.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/ingestion/tests/test_congress_client.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/ingestion
rtk git commit -m "feat(ingestion): fetch bill committees and cosponsors"
```

## Task 4: Discover and ingest every current-Congress roll call durably

**Files:**

- Create: `legislation-tracker-backend/apps/ingestion/vote_sources.py`
- Modify: `legislation-tracker-backend/apps/congress/current.py`
- Modify: `legislation-tracker-backend/apps/congress/tests/test_current_congress.py`
- Modify: `legislation-tracker-backend/apps/ingestion/tasks.py`
- Modify: `legislation-tracker-backend/config/celery.py`
- Create: `legislation-tracker-backend/apps/ingestion/tests/test_vote_sources.py`
- Create: `legislation-tracker-backend/apps/ingestion/tests/test_roll_call_work.py`
- Create: `legislation-tracker-backend/apps/ingestion/tests/test_representative_detail_work.py`
- Create: `legislation-tracker-backend/apps/ingestion/tests/fixtures/senate_vote_list.xml`
- Create: `legislation-tracker-backend/apps/ingestion/tests/fixtures/senate_vote_detail.xml`

- [ ] Write source-adapter tests covering House pagination, Senate list/detail XML, bill-linked and non-bill votes, every normalized position, duplicate voters, malformed/truncated payloads, external entities, response caps, and source session/Congress mismatches.

- [ ] Implement `HouseVoteSource` over the Congress.gov list/detail methods and `SenateVoteSource` over official roll-call list/detail XML. Both return `RollCallRef(congress, chamber, session_number, roll_number, source_updated_at, source_url)` and `NormalizedRollCall` with optional bill identity and exact Bioguide vote records. Add `defusedxml` to `requirements/base.txt` and regenerate `requirements/production.lock`; parsers also enforce byte caps and reject wrong Congress/session metadata.

- [ ] Add `current_congress_session(on_date: date | None = None) -> int` beside `current_congress`; it returns session 1 in the Congress's first calendar year and session 2 in its second, preserving the January 3 boundary. Add `WORK_KIND_ROLL_CALL_VOTE = "roll_call_vote"` with dedupe key `vote:<congress>:<chamber>:<session>:<roll>`. A periodic discovery task accepts `congress=None`, resolves it at execution, and polls both chambers for every session from 1 through the current session so a restart in session 2 still fills session 1. For each source page it locks the corresponding `RollCallIngestionState`, enqueues the complete page, and advances its cursor atomically. A crash before commit repeats safely; a crash afterward cannot skip enqueued work.

- [ ] Add `WORK_KIND_REPRESENTATIVE_DETAIL = "representative_detail"` with dedupe key `bioguide:<id>`. Its handler calls `member_detail`, verifies the returned Bioguide ID, and upserts the full canonical profile/source timestamp. After commit it wakes only blocked work whose stored dependency keys are all satisfied.

- [ ] Implement the roll-call detail worker to fetch outside the database transaction, validate the complete voter list, queue representative-detail dependencies for unknown Bioguide IDs, and set itself to `blocked` with reason `blocked_on_dependencies` without consuming terminal attempts. When dependencies are satisfied, atomically upsert `Vote`, its optional bill link, and the complete `VoteRecord` snapshot. When a bill-linked vote materially changes, call `record_bill_change` in that transaction with change type `vote`, event key `f"vote:{congress}:{chamber}:{session_number}:{roll_number}:{source_updated_at.isoformat()}"`, and payload containing `vote_id`, Congress, chamber, session, roll number, result, yeas, and nays; non-bill votes do not invent a bill event. Stale source timestamps are successful no-ops.

- [ ] Remove direct `Vote`, `VoteRecord`, incidental `Representative`, and `ChangeLog` writes from the existing bill-scoped `process_bill_votes` path. When bill actions expose a roll-call reference, enqueue the same canonical `roll_call_vote` key and let the new worker attach the bill. Add a regression proving the legacy task cannot create a vote without Congress or bypass member dependencies.

- [ ] Add PostgreSQL tests for concurrent discovery workers, retry/dead-letter/replay, cursor crash boundaries, unknown member recovery, no-bill roll calls, and idempotent replacement.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/legislation_e2e .venv/bin/pytest apps/congress/tests/test_current_congress.py apps/ingestion/tests/test_vote_sources.py apps/ingestion/tests/test_roll_call_work.py apps/ingestion/tests/test_representative_detail_work.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/ingestion legislation-tracker-backend/config/celery.py legislation-tracker-backend/requirements
rtk git commit -m "feat(ingestion): ingest complete congressional roll calls"
```

## Task 5: Parse official current committee rosters safely

**Files:**

- Create: `legislation-tracker-backend/apps/ingestion/committee_sources.py`
- Create: `legislation-tracker-backend/apps/ingestion/tests/test_committee_sources.py`
- Create: `legislation-tracker-backend/apps/ingestion/tests/fixtures/house_member_data.xml`
- Create: `legislation-tracker-backend/apps/ingestion/tests/fixtures/senate_member_data.xml`
- Modify: `legislation-tracker-backend/requirements/base.txt`
- Modify: `legislation-tracker-backend/requirements/production.lock`

- [ ] Write parser tests with representative, chair, ranking-member, subcommittee, vacancy, unknown-role, duplicate, missing-Bioguide, malformed XML, external-entity, empty snapshot, and truncated snapshot fixtures.

- [ ] Implement pure parsers returning a shared immutable shape:

```python
@dataclass(frozen=True)
class CommitteeAssignment:
    bioguide_id: str
    committee_code: str
    committee_name: str
    chamber: str
    parent_code: str | None
    rank: int | None
    role: str
    party_side: str
```

Also return:

```python
@dataclass(frozen=True)
class CommitteeRosterSnapshot:
    congress: int
    chamber: str
    published_at: datetime
    source_url: str
    source_hash: str
    assignments: tuple[CommitteeAssignment, ...]

def normalize_committee_system_code(*, source: str, chamber: str, raw_code: str) -> str:
    """Map House II00, Senate codes, and Congress.gov systemCode to lowercase hs/ss/js identities."""
```

Congress.gov values already beginning `hs`, `ss`, or `js` normalize by trim/case-fold only. For roster codes, strip a duplicated chamber prefix and prepend `hs`, `ss`, or `js`; House `comcode="II00"` therefore becomes `hsii00`. A House `subcomcode` replaces the parent's terminal `00` before normalization (`II00` plus `01` becomes `hsii01`) and keeps `hsii00` as `parent_code`. Reject codes that do not match the source/chamber grammar rather than guessing.

- [ ] Implement fetchers for the configured official House and Senate URLs with connect/read timeouts, maximum response bytes, content-type checks, and `defusedxml` parsing. Keep URLs overridable in settings for tests and emergency source migration.

- [ ] Add snapshot validation: embedded Congress equals the requested Congress, publication time is inside the configured freshness window, nonzero representatives and assignments, no duplicate identity tuples, every written assignment has a Bioguide ID and canonical committee code, and the represented-member count does not drop below a configurable safe fraction of the last successful snapshot. On validation failure, raise a typed error before any database write.

- [ ] Add a cross-source fixture test proving House XML raw `II00` and Congress.gov `systemCode="hsii00"` normalize to the same committee identity; repeat for Senate and a joint committee.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/ingestion/tests/test_committee_sources.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/ingestion/committee_sources.py legislation-tracker-backend/apps/ingestion/tests
rtk git commit -m "feat(ingestion): parse official committee rosters"
```

## Task 6: Persist committee snapshots atomically

**Files:**

- Create: `legislation-tracker-backend/apps/congress/committee_sync.py`
- Modify: `legislation-tracker-backend/apps/ingestion/tasks.py`
- Modify: `legislation-tracker-backend/config/celery.py`
- Create: `legislation-tracker-backend/apps/congress/tests/test_committee_sync.py`
- Modify: `legislation-tracker-backend/apps/ingestion/tests/test_tasks.py`

- [ ] Write failing tests that a valid chamber snapshot upserts canonical committees/memberships, resolves parent committees, normalizes roles, retains raw source codes, retains the other chamber, marks absent prior memberships non-current, and records publication time/source hash.

- [ ] Add negative tests proving an empty/incomplete snapshot, unknown Bioguide ratio above threshold, or mid-transaction failure leaves every prior current membership intact.

- [ ] Implement `sync_committee_memberships(*, congress: int | None = None)`. Resolve `current_congress()` at execution time when omitted. Fetch outside the write transaction, validate embedded Congress/publication freshness/completeness, then lock the chamber's current rows, upsert the complete canonical snapshot, and retire absent rows in one transaction. Revalidate snapshot freshness immediately before writes.

- [ ] Schedule it after representative roster synchronization without hard-coded Congress Beat arguments. Use task retry policy for transient transport errors; snapshot-validation failures go to existing task-failure/dead-letter observability and do not retry indefinitely.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/legislation_e2e .venv/bin/pytest apps/congress/tests/test_committee_sync.py apps/ingestion/tests/test_tasks.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/congress legislation-tracker-backend/apps/ingestion/tasks.py legislation-tracker-backend/config/celery.py
rtk git commit -m "feat(representatives): synchronize current committee memberships"
```

## Task 7: Add durable relationships with exact member dependencies

**Files:**

- Modify: `legislation-tracker-backend/apps/ingestion/models.py`
- Modify: `legislation-tracker-backend/apps/ingestion/tasks.py`
- Create: `legislation-tracker-backend/apps/congress/relationship_sync.py`
- Create: `legislation-tracker-backend/apps/ingestion/tests/test_bill_relationship_work.py`
- Create: `legislation-tracker-backend/apps/congress/tests/test_relationship_sync.py`

- [ ] Write failing tests for a `bill_relationships` work item, deterministic upstream dedupe key, enqueue after bill metadata commit, idempotent retries, exact Bioguide resolution, withdrawn cosponsors, canonical committee upserts, stale-source no-op, and no partial replace when either upstream collection fails. Include a former/departed member referenced by a current-Congress bill.

- [ ] Add `WORK_KIND_BILL_RELATIONSHIPS = "bill_relationships"`, dispatch it, and implement transactionally atomic `sync_bill_relationships(*, bill_id: int) -> RelationshipSyncResult`. `IngestionWorkItem.kind` is intentionally an unconstrained string, so this does not require a schema migration. Fetch complete cosponsor and committee collections before writes. Upsert present rows and remove/retire missing rows only after both collections validate.

- [ ] Reuse Task 4 representative-detail work for missing relationship identities. Relationship work stores exact dependency keys, returns reason `blocked_on_dependencies` without incrementing terminal attempts, and resumes only after Task 4's wake-up path clears a fully satisfied dependency list and sets `pending` with `available_at=timezone.now()`.

- [ ] After successful replacement, emit concise `cosponsor_update` and `committee_update` events with the shared `record_bill_change` service only when identities actually changed. Payloads contain added/removed stable IDs and are capped; a count plus truncation flag represents larger sets.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/legislation_e2e .venv/bin/pytest apps/ingestion/tests/test_bill_relationship_work.py apps/congress/tests/test_relationship_sync.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/ingestion legislation-tracker-backend/apps/congress
rtk git commit -m "feat(representatives): ingest bill relationships durably"
```

## Task 8: Add a preview-first current/historical backfill

**Files:**

- Create: `legislation-tracker-backend/apps/congress/management/__init__.py`
- Create: `legislation-tracker-backend/apps/congress/management/commands/__init__.py`
- Create: `legislation-tracker-backend/apps/congress/management/commands/backfill_representative_insights.py`
- Create: `legislation-tracker-backend/apps/congress/tests/test_backfill_representative_insights_command.py`
- Modify: `legislation-tracker-backend/apps/congress/README.md`

- [ ] Write command tests for required `--congress`, preview default, `--limit`, invalid future/unsupported Congress, current-vs-historical labels, no writes during preview, and exact durable work counts during execution.

- [ ] Implement preview output with representative count, bill-relationship candidates, House/Senate roll-call candidates and cursor positions, missing/current relationship counts, unknown Bioguide dependencies, and a warning that historical committee-roster completeness is not guaranteed. `--execute` queues roll-call and bill-relationship items and runs committee roster sync only when the requested Congress is current.

- [ ] Ensure repeated execution coalesces work and does not reset successful rows.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/congress/tests/test_backfill_representative_insights_command.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/congress
rtk git commit -m "feat(representatives): add preview-first insights backfill"
```

## Task 9: Implement auditable representative analytics

**Files:**

- Create: `legislation-tracker-backend/apps/congress/insights.py`
- Create: `legislation-tracker-backend/apps/congress/tests/test_insights.py`

- [ ] Build fixtures covering yes, no, present, not voting, abstain/other, bill and non-bill roll calls, duplicate-source attempts blocked by constraints, votes without a record for one member, incomplete discovery coverage, sponsorship, withdrawn co-sponsorship, and committee leadership.

- [ ] Write failing tests for exact numerators/denominators, service-interval scoping, zero-vote behavior, current-Congress scoping, incomplete coverage metadata, active cosponsor counts, and stable chronological pagination.

- [ ] Implement:

Implement exact interfaces `representative_summary(*, representative: Representative, congress: int) -> RepresentativeInsight` and `compare_representatives(*, left: Representative, right: Representative, congress: int) -> RepresentativeComparison`.

The participation denominator is every discovered roll call for the member's chamber during the overlap of the requested Congress and the member's service interval, including procedural and nomination votes; the numerator is a cast yes/no/present/other record. `not_voting` remains an explicit position. Return `first_vote_at`, `last_vote_at`, `total_roll_calls`, `ingested_roll_calls`, and `coverage_complete`. Coverage is true only when every applicable chamber/session state has reached a current authoritative source end, summed `discovered_roll_count` equals distinct persisted vote identities, and no applicable roll-call item is pending, dispatched, processing, blocked, or dead. If coverage is incomplete, return the partial raw counts with `coverage_complete=false` and forbid UI copy that presents them as a complete pattern. Agreement denominator includes only shared votes where both normalized positions are yes or no. Return excluded shared-vote counts separately.

- [ ] Return integer counts with separately computed decimal rates. Quantize display percentages consistently, but never use rounded percentages to calculate another metric.

- [ ] Assert query counts for summary and comparison to prevent per-vote/per-bill N+1 access.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/legislation_e2e .venv/bin/pytest apps/congress/tests/test_insights.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/congress/insights.py legislation-tracker-backend/apps/congress/tests/test_insights.py
rtk git commit -m "feat(representatives): compute descriptive member insights"
```

## Task 10: Expose representative insight APIs

**Files:**

- Modify: `legislation-tracker-backend/apps/congress/serializers.py`
- Modify: `legislation-tracker-backend/apps/congress/views.py`
- Modify: `legislation-tracker-backend/config/urls.py`
- Modify: `legislation-tracker-backend/apps/legislation/tests/test_public_api.py`
- Create: `legislation-tracker-backend/apps/congress/tests/test_insights_api.py`

- [ ] Write API tests for:

```text
GET /api/representatives/{id}/insights/?congress=119
GET /api/representatives/{id}/sponsored-bills/?congress=119
GET /api/representatives/{id}/cosponsored-bills/?congress=119
GET /api/representatives/{id}/committees/?congress=119
GET /api/representatives/compare/?ids={left},{right}&congress=119
GET /api/committees/
GET /api/committees/{id}/
```

Cover invalid/missing Congress, duplicate IDs, more/fewer than two IDs, cross-chamber comparisons, unknown people, empty histories, withdrawal fields, pagination, ordering, and query counts.

- [ ] Register `CommitteeViewSet`. Add detail actions or explicit paths for representative endpoints while preserving the existing representative list contract.

- [ ] Permit cross-chamber comparison but return `shared_vote_count=0` and an explanatory reason; do not fabricate a percentage. Include metric definitions and roll-call coverage metadata in every vote-derived response so clients can display the denominator and completeness rule.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/legislation_e2e .venv/bin/pytest apps/congress/tests/test_insights_api.py apps/legislation/tests/test_public_api.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/congress legislation-tracker-backend/config/urls.py
rtk git commit -m "feat(representatives): expose insights and comparison APIs"
```

## Task 11: Build representative detail and comparison pages

**Files:**

- Modify: `legislation-tracker-client/lib/api.ts`
- Modify: `legislation-tracker-client/app/representatives/page.tsx`
- Create: `legislation-tracker-client/app/representatives/[id]/page.tsx`
- Create: `legislation-tracker-client/app/representatives/[id]/representative-summary.tsx`
- Create: `legislation-tracker-client/app/representatives/[id]/vote-patterns.tsx`
- Create: `legislation-tracker-client/app/representatives/[id]/legislation-history.tsx`
- Create: `legislation-tracker-client/app/representatives/[id]/committee-list.tsx`
- Create: `legislation-tracker-client/app/representatives/compare/page.tsx`
- Create: `legislation-tracker-client/app/representatives/compare/representative-comparison.tsx`
- Create: `legislation-tracker-client/tests/components/representatives-page.test.tsx`
- Create: `legislation-tracker-client/tests/components/representative-detail.test.tsx`
- Create: `legislation-tracker-client/tests/components/representative-comparison.test.tsx`

- [ ] Write component tests for representative links, raw counts and rates, complete/partial coverage copy, first/last vote dates, zero/low sample copy, present/not-voting visibility, sponsored/cosponsored tabs, withdrawn labels, committee leadership, pagination, exactly-two selection, cross-chamber no-shared-vote copy, URL restoration, loading, empty, and retry states.

- [ ] Add typed API functions and runtime parsing for every new response. Keep comparison selection in URL `ids` and `congress` parameters so the result is linkable.

- [ ] Build detail cards that always show numerator and denominator near a percentage. Provide links from sponsorship and shared-vote rows to the corresponding bill/vote.

- [ ] Build comparison selection from current representatives, prevent the same person in both slots, and render shared vote evidence below the summary. Do not add scores, rankings, or red/blue ideological scales.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-client && pnpm exec vitest run tests/components/representatives-page.test.tsx tests/components/representative-detail.test.tsx tests/components/representative-comparison.test.tsx"
rtk run "cd legislation-tracker-client && pnpm typecheck"
rtk run "cd legislation-tracker-client && pnpm lint"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-client/app/representatives legislation-tracker-client/lib/api.ts legislation-tracker-client/tests/components
rtk git commit -m "feat(representatives): build member insights experience"
```

## Task 12: Add PostgreSQL end-to-end and release verification

**Files:**

- Create: `legislation-tracker-client/e2e/representative-insights.spec.ts`
- Modify: `legislation-tracker-backend/docker-compose.e2e-postgres.yml`
- Modify: `legislation-tracker-backend/scripts/start-e2e-api.sh`
- Modify: `legislation-tracker-backend/scripts/seed-e2e-legislative-intelligence.py`
- Modify: `legislation-tracker-backend/README.md`
- Modify: `legislation-tracker-client/README.md`

- [ ] Seed complete House/Senate roll-call coverage including a non-bill vote, a not-voting record, committee codes represented in both source formats, and a departed member dependency. Add Playwright journeys for browsing a member, inspecting coverage and vote counts, following bill relationships, selecting two representatives, auditing a shared vote, and handling partial-coverage/no-shared-vote/error states.

- [ ] Document official source URLs/configuration, timeouts and payload caps, snapshot fail-closed behavior, current-Congress schedule, unresolved identity monitoring, durable relationship replay, and preview-first historical execution.

- [ ] Run the complete release gate:

```bash
rtk docker compose -f legislation-tracker-backend/docker-compose.e2e-postgres.yml up -d
rtk run "cd legislation-tracker-backend && DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/legislation_e2e .venv/bin/pytest -q"
rtk run "cd legislation-tracker-backend && .venv/bin/ruff check ."
rtk run "cd legislation-tracker-client && pnpm test"
rtk run "cd legislation-tracker-client && pnpm typecheck"
rtk run "cd legislation-tracker-client && pnpm lint"
rtk run "cd legislation-tracker-client && pnpm build"
rtk run "cd legislation-tracker-client && E2E_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/legislation_e2e pnpm test:e2e -- e2e/representative-insights.spec.ts"
rtk git diff --check
```

- [ ] Before release, preview current-Congress backfill and record candidate counts, unresolved Bioguide IDs, successfully validated House/Senate member counts, queued work, failures, and replays as separate operational evidence.

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend legislation-tracker-client
rtk git commit -m "test(representatives): cover insights ingestion and journeys"
```

## Completion criteria

- Current House and Senate committee assignments synchronize atomically from official sources without destructive empty-snapshot behavior.
- Current-Congress bill committee and cosponsor relationships are durable, idempotent, replayable, and identity-safe.
- Every current-Congress House and Senate roll call is discovered through a persistent cursor and processed through replayable durable work, including votes without bills.
- Representative pages expose factual vote, sponsorship, co-sponsorship, and committee evidence with explicit counts and roll-call coverage.
- House/Senate roster codes and Congress.gov bill committee codes resolve to the same canonical committee rows.
- Two-member comparison uses a documented denominator and links users to shared roll calls.
- Historical execution remains explicit, preview-first, and honest about committee-roster completeness.
