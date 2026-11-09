# Outside spending

Campaign funding separates donations from independent spending supporting or
opposing a candidate. These amounts are never added to campaign receipts.

Research collects OpenFEC `schedules/schedule_e/by_candidate/` processed
committee/candidate/cycle/position aggregates. These are provider totals, not
sums of overlapping 24/48-hour notices and regular filings. They include
reporting groups beyond Super PACs and do not cover every kind of outside
political spending. FEC source links accompany each group.

`OutsideSpendingScan` tracks durable pagination per candidate and finance
snapshot; `OutsideSpendingTotal` stores each spender/position total separately
from contributions. Page writes and cursor updates share the research worker's
fenced transaction. Refresh creates a new snapshot rather than adding to old
totals. Invalidated identities hide these records with the parent snapshot.
Provider pagination duplicates or contradictory scope fail the scan rather
than silently inflating totals.

`GET /api/representatives/{id}/outside-spending/?period=2026&cursor=0`
returns separate support/oppose amounts and 20 groups per page. Optional
`position=S` or `position=O` filters records, not the summary totals.
Unresearched amounts are null, not zero; incomplete scans are marked collecting.
Existing published snapshots require Refresh funding to collect this new data.

Apply migration `campaign_finance.0008_outside_spending` and reload the research
worker and API when deploying.
