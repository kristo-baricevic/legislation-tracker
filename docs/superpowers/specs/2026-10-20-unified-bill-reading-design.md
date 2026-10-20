# One bill page, enhanced in place

## Approved product direction

Readers should see one coherent account of a bill, not an NLP report followed
by a competing AI report. Both modes use Summary, What changes, Money, Key terms,
and Votes/history. AI explanations improve identified items in that same page.
Financial provisions must remain accessible regardless of AI coverage.

Requirements, exceptions, and effective dates belong beside the changes they
qualify. In H.R. 7583, the 15-employee threshold and one-year deadline belong
with the policy requirement. The tipped-wage amount, escalation formula, and
effective dates must remain together. A model-generated grouping is not proof
that these relationships are correct.

No ingestion or NLP-wide rerun is required. AI generation remains private,
on demand, and explicitly confirmed. This implementation does not authorize
paid generation, bulk regeneration, public AI caching, or enabling source-first.

## Current code and actual gap

The active output schema 1.3 has independent overview, key_impacts, obligations,
funding_and_timing, uncertain_language, and glossary lists. Only glossary entries
have stable target IDs validated against a saved contract. The bill page renders
the other lists in BillEnhancementPanel after its normal reader content.

The normal reader already has identified line items, financial items, timeline
items, definitions, source IDs, and exact versus section-level relationships.
Keep those identities and relationships. Do not infer matching from array order,
similar prose, section heading alone, or the first citation.

## Proposed implementation decisions

### Versioned, targeted explanations

Introduce schema `1.4` for newly requested enhancements. Preserve validation and
historical viewing of schemas 1.1–1.3 and the separate disabled source-first path.
New results contain a cited summary and targeted explanations, not six competing
reader-facing lists.

Each immutable target snapshot records contract ID/hash, document ID/content hash,
target kind (`line_item`, `financial_item`, `definition`), target ID, original
display text, and complete available source evidence. Include exact linked
money, dates, and necessary enclosing qualifiers as context. If adequate context
cannot be assembled within bounds, mark the target unavailable for enhancement
and retain its existing display; never quietly truncate it.

Model responses contain target ID, explanation or explicit unresolved status,
and exact quotations. They cannot change amounts, formulas, actors, obligations,
dates, relationships, ordering, or source identity in the stored NLP contract.
Validate target membership, uniqueness, completeness of each requested batch,
and citation support against the assigned source context. Preserve existing
semantic checks; ID and quote validation alone do not prove a faithful explanation.

Use the existing confirmed batching/usage/lease machinery. Preflight must show
selected, eligible and excluded target counts with exclusion reasons, all calls,
and aggregate budget before payment. A request that cannot fit the configured
budget must not silently grow it or select supposedly “most consequential” items.
Explicitly unresolved targets fall back; transport or validation failure must
not publish an incomplete new result.

### One presentation model

Resolve each displayed item using the current signed-in user's successful,
non-stale enhancement for that exact document and contract. A matching supported
explanation replaces only the explanation text. Render its attached structured
facts, exceptions and source controls with it. Financial pagination, counts,
filters and ordering still use the complete NLP collection, never the AI list.
Unmatched, unresolved or stale targets use the original explanation.

Summary uses the matching supported AI summary where available. What changes
shows the same underlying provision collection with explanations substituted;
no second AI-only list. Exact linked deadlines stay beside their provision.
Section-level deadlines must retain their broader scope rather than attaching
to arbitrary provisions. Money can link to its parent change without duplicating
the entire explanation in both places.

Use a small “AI-enhanced” indicator and “View original” disclosure. Keep the
current app styling. Move generation controls and usage/failure/attempt history
into a compact “AI enhancement” details control near the reading controls.
Votes and legislative history are unchanged.

### Compatibility and privacy

Do not relabel old broad paragraphs as ID-bound replacements. Existing 1.3
glossary mappings can continue to work with their existing identity checks;
other historical analysis remains accessible through enhancement history, not
as a second default report. Explain that in-place provision enhancement requires
a new confirmed generation. Retain all saved analyses.

Changing the execution schema alone must not invalidate source-current old
glossary explanations: distinguish source/contract compatibility from “latest
generation format” availability. Never relax an actual source mismatch.

Logout/account switch immediately clears private explanations. Selecting a
historical analysis must not replace the current bill's default reading state.
A failed refresh must not erase a still-compatible previously successful result.

## Acceptance

Use frozen H.R. 7583 source and target snapshots as the test bill; do not derive
expected facts from its generated AI response. Verify the policy threshold,
deadline, tipped-wage amount/formula/effective dates, and all annotated financial
items against that text.

Automated tests must prove identity isolation, complete financial accessibility,
fallback, source navigation, original-text access, and no duplicate report.
Meaning/readability require explicit review of the rendered example; a passing
schema/citation test is not a semantic-quality verdict.

No unrelated ingestion changes, redesign, backfill, deployment, push, or paid
rerun is part of this implementation.
