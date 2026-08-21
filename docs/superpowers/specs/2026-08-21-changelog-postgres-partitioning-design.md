# ChangeLog PostgreSQL Partitioning Design

## Goal

Store the append-only `ChangeLog` in monthly PostgreSQL partitions keyed by
`created_at`, without changing its Django API, event writers, or SQLite
development workflow.

## Scope

- PostgreSQL converts the existing `changelog_changelog` table to a range
  partitioned parent table through a reversible migration.
- SQLite remains a normal Django table so the existing local test workflow
  remains usable.
- A shared maintainer creates month partitions through the current month plus
  twelve future months. It is callable from a management command and a daily
  Celery task.
- The migration creates every month needed for existing history before copying
  rows, then creates twelve future months.

## Storage layout

```text
changelog_changelog                  partitioned parent: RANGE (created_at)
├── changelog_changelog_2026_08      [2026-08-01, 2026-09-01)
├── changelog_changelog_2026_09      [2026-09-01, 2026-10-01)
└── ...
```

The parent retains the `ChangeLog` table name. Django continues to call
`ChangeLog.objects.create(...)`; PostgreSQL routes the insert to the matching
month. There is deliberately no default partition: an out-of-range write is a
visible operational failure rather than data silently accumulating in a table
that cannot be attached later.

## Identity and constraints

PostgreSQL requires every unique or primary-key constraint on a partitioned
table to include its partition key. The parent therefore uses
`PRIMARY KEY (id, created_at)`. `id` remains a single global identity sequence
and the Django model remains unchanged, but PostgreSQL no longer enforces `id`
uniqueness by itself. Normal ORM inserts remain safe because they allocate
from that sequence; manual ID assignment is unsupported. No table may have a
foreign key pointing at `ChangeLog`: a Django model check and the conversion
migration reject inbound foreign keys before they produce unsafe physical
constraints.

The migrated parent preserves the existing foreign keys to bills, documents,
and contracts, including their delete behavior, JSON columns, and all existing
query indexes:

- the normal Django indexes for `created_at`, `bill_id`, `document_id`,
  `contract_id`, and `change_type` (including the varchar pattern index);
- the three named compatibility indexes for `created_at DESC`, `bill_id`, and
  `change_type`; and
- the named `(created_at DESC, bill_id)` index.

## Migration and rollback

Migration `changelog.0003_partition_by_created_at` is PostgreSQL only. It
sets a five-second lock timeout, acquires an `ACCESS EXCLUSIVE` lock, verifies
there are no inbound foreign keys, creates a temporary partitioned table,
creates the historical and future partitions, copies all rows, advances the
replacement identity sequence, flushes deferred FK checks, swaps table names,
drops the old table, and then recreates every parent index under its original
name. On failure PostgreSQL rolls back to the intact normal table.

Its reverse operation performs the inverse copy-and-swap back to a normal
table. SQLite is a no-op in both directions.

This is suitable before first production deployment and remains a controlled
maintenance-window operation for an already populated database. API, workers,
Beat, long-running reports, and other readers must be quiesced; no rolling
deployment is safe while the swap is in progress.

## Partition maintenance

`apps.changelog.partitions.ensure_change_log_partitions()` is the single
runtime boundary. It uses a transaction-scoped PostgreSQL advisory lock,
validates that the parent is partitioned, and creates missing month partitions
idempotently. It returns the partition names it created and is a no-op on
non-PostgreSQL connections.

`ensure_changelog_partitions` management command exposes manual recovery.
`apps.changelog.tasks.ensure_change_log_partitions_task` runs daily through
Celery Beat and asks the shared helper to maintain the twelve-month horizon.

## Verification and rollout

- Portable tests cover month boundaries and SQLite no-op behavior.
- PostgreSQL integration tests assert parent/child catalog state, UTC routing
  under a non-UTC session timezone, concurrent maintainer serialization, and
  a forward-and-reverse conversion preserving JSON data, indexes, relations,
  and identity sequence allocation.
- A disposable PostgreSQL 16 container validates the migration and tests.
- Production rollout: quiesce API/worker/Beat/readers, back up/count
  `ChangeLog`, run migrate, verify row counts and partition catalog, resume
  services, then run the management command once as a readiness check.

## Out of scope

- Event retention/deletion or archival.
- RSS, newsletters, API contract changes, and changes to `ChangeLog` payloads.
- A global PostgreSQL unique index for `id`; the identity sequence provides
  allocation only and no foreign key references the event identifier.
