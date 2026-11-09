# Simple changes reader

Goal: Apply the approved mockup's short heading, plain explanation and numbered source to every bill, without bill-specific copy or lost financial records.

Architecture (revised after reader feedback): Store a versioned, rebuildable reader-copy projection alongside immutable contracts. Never change the source offsets, original text, hashes or AI matching identities. Render complete explanations in short paragraphs; keep material conditions visible. Use numbered source popovers for supporting notes, not Details disclosures. The financial ledger remains authoritative and unchanged.

## Tasks
1. Normalize controlled requirement/permission grammar only when slots agree with stored text. Simplify legal boilerplate without changing numeric limits, eligibility, quotations, or amendments. Run `refresh_reader_copy --execute` for existing 2.1 contracts. New extraction saves the same projection; the API computes a fallback for missing or stale projections.
2. Group consecutive clauses under one heading; remove repeated application boilerplate when the heading states the obligation. No standalone annotation buttons beside pagination. Keep full explanations visible, with sources and supplementary notes in numbered popovers. No omission of difficult sentences or conditions.
3. Update versioned AI instructions to explain the actual practical change, resolve technical names from supplied definitions, and preserve essential qualifications in visible prose. The user authorized refreshing the four bills with existing successful AI analyses with a total spending cap below $5. Preserve prior successful results if validation fails. Budget the actual citation-ID envelope before selecting complete source sections.
4. Test grants, taxes, prohibitions, conditional requirements, amendments, long lists and legacy/saved AI data. Run frontend and backend suites and inspect bill 463 in the live app.

Review focus: no substring truncation; no weakened negation/conditions; preserved amounts/bases; compatibility with existing contracts; all linked source/detail/financial actions reachable by keyboard.

Limitation: controlled deterministic rewrites do not establish that every complex provision is now understandable. Unrecognized legal constructions remain intact; semantic simplification requires source-grounded generation and review, not hiding the text.

## Execution evidence and remaining work

- Reader groups are formed before pagination using full section paths, with all member evidence and financial references retained. Application checklists become one overview. Numbered source popovers replace the reader's disclosure controls.
- All 31,396 saved 2.1 contracts were backfilled. A second pass filled 26,086 empty introductions from the documents' source-purpose text. These counts cover versions, not distinct bills, and are not readability pass rates.
- Financial summaries distinguish set-asides, authorizations, appropriations and other financial mechanisms. An unstated total is not reported as zero cost. No financial ledger items were deleted or combined into a guessed total.
- The provider adapter now actually sends the bounded reader schema supplied by the preflight. Previously it substituted the generic schema. Regression coverage exercises the outgoing request, not just the schema builder.
- H.R. 9300's latest refresh (attempt 63) succeeded with two short summary paragraphs. H.R. 7583's attempt 64 failed the assigned-provision citation check; its previous successful analysis remains unchanged. Do not describe every saved AI analysis as refreshed successfully. Further paid retries require rechecking the cumulative budget, including interrupted attempts with unknown usage.
- Universal plain-language quality is **not complete**. The audit before the purpose-text pass found 73,777 grouped explanations longer than 400 characters. Those unknown constructions retain source wording. Overlarge merged groups are separated into their original provisions rather than causing an API validation failure or losing text. This safety fallback does not solve their readability.
- Remaining release gate: evaluate the actual rendered introductions and changes across bill types, shorten the unsupported constructions with source-grounded rules or generation, and rerun accuracy/readability checks. Backfill completion or passing unit tests alone cannot satisfy that gate.

Execution: main agent only, in the existing checkout, per the user's explicit implementation request. Preserve other local fixes and the running app.
