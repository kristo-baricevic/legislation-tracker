# Understand a bill in 30 seconds — implementation plan

> Execution: use superpowers:executing-plans, single agent. Plan only; no paid calls or data changes are authorized by this document.

**Goal:** Someone unfamiliar with Congress can explain what a bill would do, whom it affects, and what money is involved after reading the first card. They can verify any claim and find every financial line item without reading the entire bill.

**Architecture:** Retain the extraction and evidence records. Produce a separate, versioned reader explanation from them and the exact bill text. Original and Enhanced use the same reader structure and validation; Original requires no model or key. Keep the current tabs, numbered source tooltips and shared enhancements.

**Stack:** Existing Django/PostgreSQL, Celery, Next.js, pytest and Playwright. **Design baseline:** [reader-first brief](../specs/2026-09-01-reader-first-bill-brief-design.md), [reader tabs](2026-11-09-bill-reader-tabs.md), and the five-page November audit. This changes how explanations are produced, not the navigation.

## Delivery order and acceptance tests

### Research-backed test protocol

- Follow the [CRS bill-reading guide](https://www.congress.gov/crs_external_products/R/PDF/R46484/R46484.4.pdf): resolve definitions and exceptions across the document; distinguish references inside proposed statutory text from references in the bill itself. Verify prior law before asserting a change from it.
- Put actor and action together; put important qualifications in a second visible sentence rather than burying them mid-clause. [Legal-language experiments](https://www.research.ed.ac.uk/files/256304933/Poor_Writing_MARTINEZ_DOA17022022_VOR_CC_BY_NC_ND.pdf) support this for contracts; verify it for bill readers.
- Score in both directions: every displayed claim against its evidence, and every material answer-key point against a findable explanation. Separate first-card comprehension from detail-tab coverage. [Pointwise legal evaluation](https://aclanthology.org/2024.nllp-1.10/); [source-span verification](https://aclanthology.org/2020.emnlp-main.750/).
- Compare current versus grouped output on identical pinned versions before bulk rollout. Log lost conditions, coverage, time and cost separately; multi-step processing is not inherently better. [Long regulatory document study](https://aclanthology.org/2024.nllp-1.2/).
- Start with the [H.R. 9300 baseline and interview script](../../benchmarks/bill-understanding/hr9300-reader-pilot.md). A fixture count of four means four percentage rules, not complete financial coverage.

For each task, reproduce the failure first, implement, then rerun the failing case and neighboring regressions. Backend paths below are under legislation-tracker-backend/apps/legislation; client paths are under legislation-tracker-client.

### 1. Freeze the failures and the expected reader answers

- [ ] Extend docs/benchmarks/bill-understanding and evaluation/reader_quality.py. Pin the exact version and source digest, not local database IDs. Reuse the existing ten-bill answer keys; supplement the five audited cases with verified passages where absent. Capture today's rendered Original and available Enhanced results, not just intermediate JSON.
- [ ] Score five separate things: correct practical effect, affected people, money and conditions, evidence coverage, and reader comprehension. Do not let shorter prose compensate for a factual failure. Record unresolved amendments separately from missing extraction and from confirmed absence of financial provisions.

| Regression | What must be true on the page |
|---|---|
| H.R. 9300, student grants | Identify the grant recipients and student benefit. Explain set-asides without implying a dollar appropriation. Keep all four rules, with distinct bases and mandatory versus optional wording. |
| H.R. 10906, wood products | Cover the distinct tax, housing and trade changes, not merely account transfers. Do not publish punctuation edits as policy. Test the two different distributions of lumber-duty money independently. |
| H.R. 3045, sanctions | Identify covered conduct and practical consequences; attach entry exceptions to entry restrictions, not asset blocking. No dangling “and.” |
| H.R. 7583, workplace protections | Say who gains which protection. Do not apply one employer-size threshold across unrelated rules. Cite each claim to its own passage. |
| H.R. 1, omnibus | The opening identifies substantive programs across divisions. The household-size formula appears as one rule with its full schedule, not a paragraph repeated per household size. Test the enacted version in past/present rather than proposed-law language. |

### 2. Serve the saved explanation without waiting for worker status

- [ ] Trace the compact bill response, reader API, page.tsx under app/bills/[id], and bill-enhancement-panel.tsx. Measure which request actually delays the first readable text. Return the selected saved brief and its mode/version together in the initial read. Fetch job status, permissions and paginated detail independently; never run generation on page load.
- [ ] Extend e2e/reader-tabs.spec.ts: hold status pending, then reject it. Saved Enhanced text must appear without an Original flash; an Original-only bill must remain readable; an explicit mode choice must survive late responses. Navigate from bill A to B while A is still loading. Assert no stale or private content crosses accounts or versions. Measure cold and warm first-summary times on the same stack before/after; the held-status test must pass without releasing the request.

### 3. Build an explanation of the rule, not a shorter source fragment

- [ ] Add extraction/reader_effects.py with a proposed build_effects(contract, source_context) interface. Each effect carries a stable ID, action, actor, affected group/program, obligation or permission, applicable conditions, timing, linked money IDs and exact evidence spans. Group by program, operative action and scope; section proximity or similar wording alone cannot join rules. Keep separate rules when exceptions, beneficiaries or percentage bases differ. Preserve source order within groups.
- [ ] For amendments, combine the editing instruction with the inserted text and its parent provision. For a before/after claim, require the correct cited prior text applicable to that version (cache by citation, edition and digest). Start with exact, verifiable references; no general legal-research crawler. When the old rule cannot be established, explain only what the new text establishes. Never infer the prior rule, silently omit the provision, or promote an editing fragment to a summary.
- [ ] In extraction/reader_language.py and extraction/synopsis.py, render one plain statement per effect using supported rule types. Prefer concrete verbs and names. Build the overview from distinct purposes, affected people and money mechanics, not a list of financial categories. A matching official summary can supply context; never import a different version's conclusion. If evidence is inadequate, retain the source and mark the gap for repair rather than counting filler as success.
- [ ] Test in test_reader_correctness.py, test_reader_synopsis.py and test_reader_large_bills.py: nested exceptions, changed percentage bases, cross-section dependencies, repeated rules and genuinely different rules with identical headings. Add a short, nonfinancial control bill. No bill-number branches.

### 4. Give Enhanced the same contract, not the same blind spots

- [ ] Adapt enhancements/reader_discovery.py, reader_summary.py and reader_integrity.py. Keep full-source discovery so a missed Original provision can still be found. Reuse verified findings and evidence; ask the model to explain related rules together, not paraphrase each chunk. Reconcile cross-section rules before drafting the overview. Chunk by text/output budget with existing resumable caches.
- [ ] Validate citations, amounts, units, qualifiers, actors and conditions before publishing. Track source sections as accounted for, nonoperative or unresolved; “processed” alone is not coverage. Reject obvious paragraph stitching, unsupported effects and generic-only summaries. Use human judgment for meaning, not keyword or reading-grade scores alone.
- [ ] Replay saved provider responses first. Test truncation, crash/resume, stale source, and discovery of a financial item absent from Original. An invalid candidate cannot replace a valid saved result. Reuse verified intermediates only when their source and relevant processing versions match. No corpus-wide paid regeneration.

### 5. Present the same facts at the right level

- [ ] Summary: normally two or three short sentences; no rigid word cutoff that removes a material condition. Example target for H.R. 9300: “Colleges and education partnerships could compete for grants to help students stay in school and graduate. The bill sets rules for dividing the grant money but does not set a dollar total.” Verify against source before publishing.
- [ ] What this bill does: render effect groups in app/bills/[id]/reader-explanation.tsx. Lead with the program and who it affects before application paperwork. Use stable pagination for long lists; for omnibus bills offer direct navigation by policy/program instead of requiring hundreds of Next clicks. Expose the full schedule behind a clearly labeled link where a rule has many rates. Source tooltips contain evidence, not essential meaning.
- [ ] Money: keep every distinct financial provision, including Enhanced discoveries. Put “at least,” “up to,” the unit and the basis next to the number. Name the purpose and recipient. Never sum overlapping allocations or present an authorization as spending. Hide single-page navigation; offer only applicable filters. Verify deep links, keyboard/touch annotations and stable layout on small screens.

### 6. Release against actual saved pages

- [ ] Run the backend reader tests, whole-bill benchmark and client component/E2E suites. Compare both modes with pinned answers. Gate: no critical factual errors, no meaning-changing omitted conditions, every annotated financial item reachable, every material claim source-supported. For large bills explicitly state which coverage was exhaustively verified versus sampled.
- [ ] Use [Digital.gov paraphrase testing](https://digital.gov/guides/plain-language/test/paraphrase-testing): recruit 6–9 unfamiliar readers for one-on-one sessions. Show the first card for 30 seconds, then ask what changes, who is affected and what money is involved. Test finding details separately with tabs available. Record answers verbatim before prompting or correcting. Rework and retest recurring or material misconceptions; do not treat this qualitative sample as a population success rate.
- [ ] Extend management/commands/refresh_reader_copy.py rather than rerunning ingestion. It currently handles 2.1 contracts only: inventory other schema versions, missing source and saved enhancements before promising full coverage. Stage new wording alongside the prior revision; dry-run then publish the five canaries. Recheck that the document hash still matches before promoting. Batch the rest with a resume cursor; rerun twice to prove unchanged records are skipped. Keep last-good revisions for rollback.
- [ ] Report totals by current/updated/blocked/failed, plus any Enhanced work requiring new paid calls and its estimated cost. Seek budget approval before that work. Verify served pages after rollout, not just the database. Do not declare the corpus finished while unexplained gaps remain.

**First shippable slice:** H.R. 9300 in both modes, plus H.R. 10906 with enhancement status unavailable, using general code paths. Expand to the sanctions, workplace and omnibus cases before bulk publication. Do not redesign other pages or introduce another evaluation platform.
