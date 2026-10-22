# Representative research

Research is an explicit, authenticated action on the representative list, detail
page, or profile modal. Reads use saved database records; they never scrape.
Shared results remain available after a failed refresh. No OpenAI key is used.

## Deployment

Apply the additive `research` and `campaign_finance` migrations before deploying
the frontend. Start the dedicated `research-worker` from the production Compose
file, alongside the existing worker and Beat. Local equivalent:

```sh
rtk proxy celery -A config worker -Q research --concurrency=1 --prefetch-multiplier=1 -l info
```

Configure `FEC_API_KEY` on the backend/worker, never in a `NEXT_PUBLIC_` variable.
`LEGISLATOR_WIKIPEDIA_ENABLED=True` enables the existing exact-Bioguide-identity
Wikimedia adapter during research. Without it, biography research uses recorded
official service facts. Missing FEC credentials do not block biography or photo.

Research has one admitted job at a time, separate from bill dispatch capacity.
Each delivery processes one bounded page and commits its records and next cursor
together. Provider backoff uses the durable queue's retry policy; exhausted work
is dead-lettered. Existing lease recovery handles a disappearing worker. Refresh
starts a new whole-period scan, not an incremental timestamp-only scan.

## Candidate verification

FEC candidate search creates **unverified suggestions**, never a name-only join.
A staff operator must verify the candidate ID, office, state, historical district,
and applicable reporting periods against official records in Django admin's
RepresentativeCandidate screen. Record the supporting URL and mark verified.
Click Refresh research afterward. Multiple candidate IDs can belong to a member.
Revocation through the admin save path invalidates active results. Do not use bulk
SQL/update/delete to change identity mappings: those bypass publication locks.

The current implementation deliberately requires staff verification for every new
mapping; automatic official crosswalk verification is not implemented.

## Finance interpretation

- Only authorized primary/other authorized committees (P/A) are scanned.
- Processed Schedule A contributions and Schedule B refunds are separate rows.
- Memo records, loans, self-funding, other receipts, negative adjustments, and
  unresolved earmarked/conduit records are excluded from contribution totals.
- Committee IDs support shared-contributor connections. Individual records are
  source-scoped; matching names or employers never merge people or businesses.
- Each refresh is a separate snapshot. A changed duplicate source ID aborts the
  scan rather than silently combining conflicting values. Previous published
  results remain available. Retry with a fresh Research run after an unstable
  upstream scan; replay is only appropriate for transient transport failures.
- Official totals are retained and compared only when committee/category/date
  coverage matches the full selected two-year scope. Missing values are not zero.
- Coverage remains **partial**, even when arithmetic matches: non-atomic upstream
  scans and unresolved excluded records do not establish a complete accounting.
  No per-donor net amount or donor-to-topic dollar allocation is inferred.

`FEC_INDIVIDUAL_PUBLICATION_ENABLED` defaults to False. Before enabling it, obtain
review of the intended use under [FEC sale/use guidance](https://www.fec.gov/updates/sale-or-use-contributor-information/).
Do not collect addresses or contact details, offer outreach tools, or assume an
exception applies. Committee data can be displayed independently.

## Sources, photos, and retention

Biographies retain excerpt/fact evidence, source hash/revision, attribution and
license. Wikimedia excerpts are not an independent fact-check. Portraits use
identity-matched Congress.gov HTTPS image URLs and preserve attribution; this
release does not download/rehost pictures or accept arbitrary source URLs.
Rehosting/image decoding and official-site HTML scraping remain deferred pending
source-specific reuse/robots decisions. Saved sources and historical snapshots
are retained indefinitely; provider keys and donor contact fields are never
persisted in evidence. No raw-provider-payload endpoint is exposed.

## Connections

Connections mean a contribution to a campaign whose member has recorded bill
activity—not endorsement of each topic or evidence of influence. Votes include
their question and recorded position; withdrawn cosponsorship is labeled.
Legislative activity currently uses the selected reporting period's dates.
The view queries current relational data without a time-based cache.

## Verification and remaining release work

Run the isolated browser harness from the client:

```sh
rtk proxy pnpm exec playwright test --config playwright.research.config.ts
```

It creates a disposable SQLite database and servers on 13420/18420, uses real
authentication/API/job persistence, and replaces only upstream source adapters.
It does not prove live FEC HTTP compatibility or broker delivery. The focused
backend suite also runs against disposable PostgreSQL, including concurrent
request joining. No live research run or migration of the user's running stack was done
during implementation.

Before production release: run a credentialed FEC smoke test; expand recorded-provider fixtures for amended/deleted
filings and conduit reconciliation. Snapshot-pinned historical graph browsing,
and separate legislative scope selection are still pending. Contributor pages
retain their published snapshot through refresh; identity revocation invalidates
historical snapshots as well. Shared representative expansion is paginated.
