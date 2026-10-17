# Source-first continuation: preflight, not accuracy acceptance

The same pinned source files and answer keys remain in use. No answer keys are
sent to generation or repair. This report describes eligibility for generation,
not generated-output correctness, coverage recall or reader comprehension.

| Pinned bill | Units included | Withheld units | Maximum provider calls | Maximum output tokens |
|---|---:|---:|---:|---:|
| H.R. 9300 IH, 119th Congress | 5 | 0 | 3 | 24,000 |
| H.R. 1589 IH, 119th Congress | 21 | 1 | 5 | 40,000 |
| S. 5 ENR, 119th Congress | 3 | 0 | 3 | 24,000 |

Each ceiling includes at most one repair and one synopsis. Neither is called
unconditionally. Existing per-call ceilings remain unchanged. Confirm the freshly
computed fingerprint before any executed run; do not reuse one from this report.

## The withheld amendment

H.R. 1589 section 203 inserts wording after “considered” in INA 244(f)(4):

> as having been inspected and admitted into the United States, and

The baseline sentence is not in the pinned bill. Interpreting the full effect
would require that outside law. The complete bill section is retained for reading,
not replaced with a guessed explanation.

## Unresolved outside-law context

Including a unit does **not** resolve its external references. Explicit rules may
be explained using their supplied source, but backend-owned limitations remain
visible, and the synopsis is partial where context is missing. In particular,
eligibility imported from other statutes must not be generalized away. This is
subject to the same independent answer-key gate as all other generated claims.

## Fresh execution, October 16

The user had already supplied an evaluation credential. The earlier report
incorrectly treated its absence from the process environment as a blocker.
The credential was supplied through hidden terminal input for this run; it was
not saved in repository files. No app services or live database were changed.

Initial requests were rejected because OpenAI does not accept `uniqueItems` in
the response schema. The adapter now omits that keyword from its wire schema
while retaining local uniqueness validation. A regression test failed before
the correction and passed afterward.

Fresh recordings have prefix `source-first-live-20261016-190216-`:

| Bill | Calls | Input tokens | Output tokens | Result |
|---|---:|---:|---:|---|
| H.R. 9300 | 3 | 12,763 | 8,184 | Partial: 3 of 5 sections accepted |
| H.R. 1589 | 1 | 20,788 | 6,479 | Stopped on unknown source-reference IDs |
| S. 5 | 1 | 4,130 | 3,926 | Stopped on an unknown source-reference ID |

H.R. 9300's definitions section was incorrectly rejected by a money-base check
matching “percentage of students”; the grants section remained unresolved for
condition scope. Its resulting synopsis omits the competitive-grant provisions
and is not an acceptable whole-bill explanation. The other two runs contain
mistyped passage hashes (two distinct IDs in H.R. 1589 and one in S. 5). These
were rejected, not silently reassigned. They need a safer reference representation,
not fuzzy citation acceptance. Raw responses are retained for offline regression
work. No result was published to the app, and no bill has passed semantic acceptance.

Verification: 37 focused provider/schema tests passed. An initial full test run
inherited local enabled feature flags and had nine failures in contract-task and
health tests. With the intended default flags explicitly supplied, the full
SQLite suite passed: 1,238 passed, 15 skipped. PostgreSQL-specific and other
opt-in checks were not exercised by this SQLite run.

After generation, review every answer-key expectation and every output claim,
including financial purposes, modality, actors, Boolean conditions and source
support. Human screen-comprehension checks remain separate. Release is blocked
until those checks pass; unit tests do not grant semantic approval.
