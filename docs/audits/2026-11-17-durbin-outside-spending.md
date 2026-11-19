# Durbin outside-spending verification

Read-only live check on 2026-11-17, candidate `S6IL00151`, against OpenFEC
`/schedules/schedule_e/by_candidate/`, using `cycle`, `per_page=100`, and
`sort=committee_id`. Every response was HTTP 200 and had at most one page.

| Reporting cycle | Supporting | Opposing | Spender/position groups |
| --- | ---: | ---: | ---: |
| 2016 | $0 | $0 | 0 |
| 2018 | $0 | $0 | 0 |
| 2020 | $69.76 | $77,000 | 3 |
| 2022 | $0 | $0 | 0 |
| 2024 | $0 | $0 | 0 |
| 2026 | $8.67 | $0 | 1 |

The 2020 groups are Sierra Club Independent Action ($10 supporting), Planned
Parenthood Votes ($59.76 supporting), and Restoration PAC ($77,000 opposing).
The 2026 group is Planned Parenthood Votes ($8.67 supporting).

The independent `/schedules/schedule_e/totals/by_candidate/` endpoint agreed
with the 2020 support/opposition totals. The itemized 2020 request with
`is_notice=false` and `most_recent=true` also agreed after excluding memo rows.
Summing memo rows would double-count amounts. These results concern processed
Schedule E aggregates, not campaign contributions, electioneering communications,
or all recent notices. They do not establish complete political spending.

Public evidence: [2020 FEC independent-expenditure records](https://www.fec.gov/data/independent-expenditures/?data_type=processed&candidate_id=S6IL00151&cycle=2020).

## Corrections

- All-period responses now include missing known reporting cycles in
  `failed_periods`, even when no research run exists for that cycle. The existing
  research/history retry queues missing cycles; complete saved cycles are reused.
- Final aggregate pages must reconcile saved spender/position groups with the
  provider's reported count when supplied. Mismatches roll back the page and
  cannot mark the scan complete. Invalid counts and boolean page counts fail.

## Other categories and older records

The same read-only check queried `/communication_costs/by_candidate/` and
`/electioneering/by_candidate/` for cycles 2016–2026.
Communication costs returned two 2020 supporting groups:

- American Federation of Teachers, AFL-CIO: $11,690.78.
- National Association of Realtors: $52,833.72.

That adds $64,524.50 missing from the original pipeline. No electioneering
aggregates were returned for Durbin in those checked cycles. Combined checked
categories total $64,602.93 supporting and $77,000 opposing—not campaign
donations, and not a lifetime total.

The 2014 independent-expenditure aggregates additionally returned $23,044.55
supporting and $717,747.51 opposing. They belong outside the current last-ten-
calendar-years range, but inside all available years. Older cycles have not all
been manually reconciled here.

Electioneering communications have no support/opposition flag. The implementation
uses a separate “Mentions” amount, preserving the provider's candidate allocation.
[FEC electioneering records](https://www.fec.gov/data/electioneering-communications/)
and [communication costs](https://www.fec.gov/data/communication-costs/) remain
separate source links.

## Implementation and rollout

Migration 0011 preserves existing scans as independent expenditures and permits
one scan per snapshot/candidate/category. All three are required for complete
outside-spending coverage. Completed scans are reused; unfinished pages resume.
The outside-only backfill does not repeat campaign receipt/disbursement downloads.
Normal Research queues missing outside-spending cycles from the verified FEC
candidate's reporting history. Full donation research still covers ten years.

The API and UI distinguish `last_ten_years` from `all_years`, show the actual
reporting range, and report missing categories/periods as partial coverage.
“All available years” means known provider reporting cycles, not proof that
every form of political spending is captured.

Once the app database and research worker are available, run from the backend:

```sh
rtk proxy python manage.py migrate
rtk proxy python manage.py backfill_outside_spending --all-researched --scope all_years
```

Use `--representative-id ID` instead of `--all-researched` for a targeted retry.
The command queues durable work; the research worker must run to finish it.
It can be rerun without repeating completed categories or duplicating active jobs.

**Initial verification:** live backfill was not run. Docker could not start; the user explicitly chose
to leave Docker alone and finish code/tests. No application database was migrated.
An isolated native PostgreSQL test database was used for verification.

Verification:

- Full backend SQLite suite with the default writer/enhancement feature flags:
  1,767 passed, 18 skipped. The initial run inherited enabled local flags and
  failed unrelated default-configuration assertions; the explicit-default rerun passed.
- PostgreSQL Congress/research suite: 243 passed, including the migration.
  Final category/migration/lifecycle regression run: 9 passed.
- Full frontend component and API suites passed; TypeScript check passed.
- Django migration drift check and Git whitespace check passed.
- No live application UI or database-backfill completion is claimed.

## Subsequent live startup verification, November 17

At the user's request XT was stopped without purging volumes and legislation
was started. Migrations were applied to the existing app database, expired
leases were recovered, and the outside-only backfill command queued missing work.
API health checks passed; the representative page, funding tab and both range
options were exercised in the browser. The historical backfill remains in progress.

Live testing exposed communication rows with position codes 24F/24N.
[FEC defines these as communication costs for/against a candidate](https://www.fec.gov/campaign-finance-data/transaction-type-code-descriptions/).
Migration 0012 preserves these raw group keys so a committee's S and 24F groups
do not collide or break provider-count reconciliation. API totals and display
map them to support/opposition. Regression tests cover mixed codes.
The fix was deployed; communication records are visible in Durbin's live results.
Tests: 22 outside-spending tests, the migration test, and 23 frontend component
tests passed. A transient revision-change load error during collection cleared
on Retry; no claim of completed historical coverage is made.

Local frontend: http://localhost:3000; API: http://localhost:18000.
Port 8000 belongs to another project and was left untouched.
