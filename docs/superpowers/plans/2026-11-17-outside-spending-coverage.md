# Outside spending coverage implementation

User-approved scope: collect independent expenditures, communication costs and
electioneering communications; distinguish last ten calendar years from all
available years; regress against Durbin and backfill researched representatives.

Use existing snapshots, durable research deliveries and FEC aggregates. Do not
sum notices with processed reports or label electioneering as support/opposition.
Preserve saved donations and completed category scans. UI stays compact.

- [x] Add category-scoped scans and migration preserving existing Schedule E rows;
  normalize all three FEC response formats and test Durbin plus neutral mentions.
- [x] Add resumable outside-only historical backfill, callable by normal Research
  history and an operator command. Verify fencing, identity, missing cycles,
  category completeness, idempotency, and preservation of donations.
- [x] Add range/category metadata and totals to API; last-ten/all-years selector,
  category pills and mentions total to the existing spending UI. Test scope
  switches, pagination and partial coverage.
- [x] Run backend/frontend tests and PostgreSQL migration checks; review the diff.
- [ ] Finish backfilling all previously researched representatives and reconcile
  historical totals. The application database is now migrated, missing work is
  queued, and Durbin's live results have been checked. Historical collection is
  still in progress; see the audit for verified results and remaining limits.

Last-ten means calendar years current year minus nine through current year,
using the intersecting two-year FEC reporting cycles. All-years means all known
provider reporting cycles, with missing coverage explicitly reported.
