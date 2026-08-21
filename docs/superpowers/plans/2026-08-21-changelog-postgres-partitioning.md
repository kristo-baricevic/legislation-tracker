# ChangeLog PostgreSQL Partitioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store `ChangeLog` events in monthly PostgreSQL partitions while preserving Django writes, existing query behavior, and SQLite development support.

**Architecture:** A PostgreSQL-only migration converts the normal table to a `created_at` range-partitioned parent. A small changelog-owned helper computes UTC month bounds and idempotently creates partitions under an advisory lock; a management command and daily Celery task share that helper. SQLite is deliberately a no-op.

**Tech Stack:** Django 5.2 migrations and management commands, PostgreSQL 16 declarative partitioning, Celery Beat, pytest-django.

**Spec:** `docs/superpowers/specs/2026-08-21-changelog-postgres-partitioning-design.md`

## Global Constraints

- Do not change `ChangeLog` API serializers, event payloads, writers, or RSS/newsletter scope.
- Partition only PostgreSQL; SQLite must retain the ordinary table and all current tests.
- Use monthly UTC ranges and maintain twelve future months with no default partition.
- Preserve foreign-key delete semantics and query indexes.
- Use test-first changes; every new behavior must fail before its implementation is written.
- Migration conversion must be transactional and reversible, with writers paused during an existing-data rollout.

---

### Task 1: Add partition-boundary and maintenance primitives

**Files:**
- Create: `legislation-tracker-backend/apps/changelog/partitions.py`
- Create: `legislation-tracker-backend/apps/changelog/tests/test_partitions.py`

**Interfaces:**
- Produces: `month_bounds(month: date) -> tuple[datetime, datetime]` with UTC bounds.
- Produces: `partition_name(month: date) -> str`.
- Produces: `ensure_change_log_partitions(*, months_ahead: int = 12, connection=None) -> list[str]`.

- [x] **Step 1: Write failing portable tests**

```python
def test_month_bounds_roll_over_december():
    assert month_bounds(date(2026, 12, 1)) == (
        datetime(2026, 12, 1, tzinfo=timezone.utc),
        datetime(2027, 1, 1, tzinfo=timezone.utc),
    )


def test_partition_maintenance_is_a_noop_on_sqlite():
    assert ensure_change_log_partitions(connection=connection) == []
```

- [x] **Step 2: Run the focused tests and confirm the import failure**

Run: `rtk .venv/bin/pytest -q apps/changelog/tests/test_partitions.py`

Expected: FAIL because `apps.changelog.partitions` does not exist.

- [x] **Step 3: Implement the smallest portable helper**

```python
def month_bounds(month: date) -> tuple[date, date]:
    start = month.replace(day=1)
    end = date(start.year + (start.month == 12), (start.month % 12) + 1, 1)
    return start, end


def ensure_change_log_partitions(*, months_ahead=12, connection=None):
    connection = connection or django_connection
    if connection.vendor != "postgresql":
        return []
```

- [x] **Step 4: Run the focused tests and confirm they pass**

Run: `rtk .venv/bin/pytest -q apps/changelog/tests/test_partitions.py`

Expected: PASS.

- [x] **Step 5: Extend the helper with PostgreSQL DDL**

Use a transaction-scoped `pg_advisory_xact_lock`, verify `relkind = 'p'` for
`changelog_changelog`, and issue one safe, generated `CREATE TABLE IF NOT
EXISTS ... PARTITION OF` per missing UTC month. Return only partitions created
by this invocation.

- [x] **Step 6: Commit the helper and portable tests**

```bash
rtk git add legislation-tracker-backend/apps/changelog/partitions.py legislation-tracker-backend/apps/changelog/tests/test_partitions.py
rtk git commit -m "feat(changelog): add monthly partition maintenance"
```

### Task 2: Convert PostgreSQL ChangeLog storage through a reversible migration

**Files:**
- Create: `legislation-tracker-backend/apps/changelog/migrations/0003_partition_by_created_at.py`
- Modify: `legislation-tracker-backend/apps/changelog/models.py`
- Modify: `legislation-tracker-backend/apps/changelog/tests/test_partitions.py`

**Interfaces:**
- Produces: PostgreSQL parent table `changelog_changelog` partitioned by `created_at`.
- Preserves: existing rows, foreign keys, index names, and the global `id` identity sequence.

- [x] **Step 1: Write a failing PostgreSQL integration test**

```python
@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL only")
def test_changelog_write_is_routed_to_its_month_partition():
    event = ChangeLog.objects.create(bill=bill, change_type="status_update", new_value={})
    assert partition_for_event(event.id) == "changelog_changelog_2026_08"
```

- [x] **Step 2: Run it against the disposable PostgreSQL database**

Run: `rtk .venv/bin/pytest -q apps/changelog/tests/test_partitions.py`

Expected: FAIL because the parent is still a normal table.

- [x] **Step 3: Implement the migration copy-and-swap**

Use `RunPython` guarded by `schema_editor.connection.vendor == "postgresql"`.
The forward migration locks the source, creates a temporary parent with
`PRIMARY KEY (id, created_at)`, creates all historical and future partitions,
copies columns by name, resets the identity sequence, swaps names, recreates
the model’s indexes, and drops the old table. The reverse migration copies
back to a normal `id` primary-key table. Keep `Migration.atomic = True`.

- [x] **Step 4: Add catalog and preservation assertions**

Assert `pg_class.relkind = 'p'`, that the child boundary includes the event’s
timestamp, and that a pre-conversion event remains readable after migration.

- [x] **Step 5: Run PostgreSQL migration and integration verification**

Run: `rtk .venv/bin/pytest -q apps/changelog/tests/test_partitions.py`

Expected: PASS against PostgreSQL; SQLite tests remain green because the
migration is a no-op there.

- [x] **Step 6: Commit the storage migration**

```bash
rtk git add legislation-tracker-backend/apps/changelog
rtk git commit -m "feat(changelog): partition events by month"
```

### Task 3: Expose maintenance and schedule it

**Files:**
- Create: `legislation-tracker-backend/apps/changelog/tasks.py`
- Create: `legislation-tracker-backend/apps/changelog/management/commands/ensure_changelog_partitions.py`
- Modify: `legislation-tracker-backend/config/celery.py`
- Modify: `legislation-tracker-backend/apps/ingestion/tests/test_celery_schedule.py`
- Create: `legislation-tracker-backend/apps/changelog/tests/test_partition_maintenance.py`

**Interfaces:**
- Produces: `python manage.py ensure_changelog_partitions [--months-ahead N]`.
- Produces: Celery task `apps.changelog.tasks.ensure_change_log_partitions_task`.

- [x] **Step 1: Write failing command and schedule tests**

```python
def test_partition_command_reports_created_partitions():
    call_command("ensure_changelog_partitions", "--months-ahead", "3")
    assert "created=0" in stdout.getvalue()


def test_celery_beat_schedules_partition_maintenance():
    assert app.conf.beat_schedule["ensure-changelog-partitions"]["task"] == (
        "apps.changelog.tasks.ensure_change_log_partitions_task"
    )
```

- [x] **Step 2: Run the focused tests and confirm they fail**

Run: `rtk .venv/bin/pytest -q apps/changelog/tests/test_partitions.py apps/ingestion/tests/test_celery_schedule.py`

Expected: FAIL because the command, task, and schedule do not exist.

- [x] **Step 3: Implement command, task, and daily schedule**

The command validates `months_ahead >= 0`, calls the shared helper, and prints
`created=<count> partitions=<comma-separated names or none>`. The task logs
the same outcome and returns a serializable mapping. Add the task to Beat once
per day with a twelve-month horizon.

- [x] **Step 4: Run focused command and schedule tests**

Run: `rtk .venv/bin/pytest -q apps/changelog/tests/test_partitions.py apps/ingestion/tests/test_celery_schedule.py`

Expected: PASS.

- [x] **Step 5: Commit maintenance wiring**

```bash
rtk git add legislation-tracker-backend/apps/changelog legislation-tracker-backend/config/celery.py legislation-tracker-backend/apps/ingestion/tests/test_celery_schedule.py
rtk git commit -m "feat(changelog): schedule partition maintenance"
```

### Task 4: Document rollout and verify all supported environments

**Files:**
- Modify: `legislation-tracker-backend/apps/changelog/README.md`
- Modify: `legislation-tracker-backend/docs/PRODUCTION_OPERATIONS.md`
- Modify: `legislation-tracker/BACKEND_BUILD_STEPS.md`

- [x] **Step 1: Update documentation**

Document monthly UTC partitions, the `PRIMARY KEY (id, created_at)` constraint,
the management command, the twelve-month horizon, writer pause during a
populated-table conversion, and the verification SQL/counts.

- [x] **Step 2: Run full backend verification on SQLite**

Run: `rtk .venv/bin/python manage.py check && rtk .venv/bin/pytest -q`

Expected: PASS.

- [x] **Step 3: Run PostgreSQL integration verification**

Run the focused partition suite with `DATABASE_URL` pointing at an isolated
PostgreSQL 16 container.

Expected: PASS, including parent catalog and child-routing assertions.

- [ ] **Step 4: Review aggregate diff and commit documentation**

```bash
rtk git diff --check
rtk git status --short
rtk git add legislation-tracker-backend/apps/changelog/README.md legislation-tracker-backend/docs/PRODUCTION_OPERATIONS.md BACKEND_BUILD_STEPS.md
rtk git commit -m "docs(changelog): document partition rollout"
```

## Completion Checklist

- [x] PostgreSQL `ChangeLog` writes route into the correct monthly partition.
- [x] Existing rows survive forward and reverse conversion.
- [x] SQLite remains an ordinary table and the local suite passes.
- [x] Parent and partition query indexes are present.
- [x] The maintainer is idempotent, advisory-locked, command-accessible, and scheduled.
- [x] No default partition, retention policy, API contract, RSS, or newsletter work was added.
- [x] Full backend and isolated PostgreSQL verification have fresh passing evidence.
