# H.R. 9300: first reader test

Version: [introduced in the House; source, digest and answer key](answers/BILLS-119hr9300ih.md). Baseline, not release approval.

## Offline run

From the backend directory:

`rtk proxy .venv/bin/python manage.py evaluate_reader_quality --suite whole-bill --case BILLS-119hr9300ih --replay ../docs/benchmarks/bill-understanding/ai-baseline-2026-10-15-funded.json --output /private/tmp/hr9300-first-reader-check.json`

| Output | Items | Mechanical failures | Items over 60 words |
|---|---:|---:|---:|
| Current NLP extraction | 25 | 0 | 5 |
| October saved AI replay | 19 | 0 | 0 |

Exit 1: both gates blocked pending semantic/UI review and accepted keys. The replay is not a fresh generation or a snapshot of today's page.

## Findings from the first comparison

- Replay item ai-0000 explains the goal but not that grants go to organizations, or that the bill sets no dollar total. Those details appear later. A whole-output match must not earn a first-card pass.
- ai-0012 through ai-0015 preserve the four distinct percentage bases/qualifiers in prose. The earlier live-page audit found that the prominent amount labels omitted the minimum/maximum qualifiers. Test the labels, not just full-paragraph text.
- The replay omits the one-campus-at-a-time grant limit (§5(h), F08). It also repeats the award years and report deadline and includes broken role/action prose such as “Grant applicant required submit”. Zero long items did not catch these.
- Check all M01–M09, not just four numeric rows. Map financial uses to the same underlying rule where appropriate; Pell reporting is an application requirement, not a new payment. This pilot is not a complete claim audit.

## Reader session (not yet run)

1. Show just Summary. Ask: “What would this bill do? Who gets the grants, and who are they meant to help? What does it tell you about how many dollars would be spent?” Credit help enrolling, staying and finishing college; eligible organizations rather than automatic student checks; no fixed total, not zero spending.
2. Allow Money. Ask: “If Congress provides money, how would it be divided? Which choices are optional?” Score §4: mandatory 2% of total for Tribal grants; §5(d): at least 20% of the post-Tribal balance for qualifying evidence-backed plans; §5(f): optional caps of 5% and 2% of the balance after both reservations for administration-related work and technical help respectively.
3. Allow all tabs. Ask: “Could a college with multiple campuses receive grants for two campuses at once?” Credit no, one campus at a time. Record the tab used, time to answer, wording misunderstood, and any source the participant opened. A correct guess without finding the provision does not pass findability.

Run against Original and Enhanced, counterbalancing which mode readers see first; avoid teaching the answers before measuring first impressions. Record unprompted answers separately from follow-ups.

## First implementation check (2026-11-21)

Rebuilt the running local application and refreshed the saved reader projection for bill 463, document 511. No provider call. In the browser, Original named recipient organizations; Enhanced distinguished colleges/partnerships from students. Both opening cards explained that the percentage rules do not set a dollar total. On the Enhanced Money tab the four prominent values read **2%**, **At least 20%**, **Up to 5%**, **Up to 2%**. On page 2 of What this bill does, both modes displayed the one-campus-at-a-time limit with a source annotation.

The October replay is immutable; it is not the published Enhanced analysis. Its awkward obligation sentences are assembled by the evaluator by joining actor, modality, action and conditions. The whole-bill rerun still reports 25 NLP and 19 replay items, zero mechanical failures and a blocked release gate. Its five long NLP items are extractor outputs, not a measurement of the rendered summary. Broad readability and complete financial findability have not been signed off.
