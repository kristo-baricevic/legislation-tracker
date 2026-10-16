# Three-bill semantic evaluation — 2026-10-16

## Decision

**Do not pass the whole-bill reader-quality release gate.** Citation validation is necessary but insufficient. Both pipelines still omit material information; some generated explanations change the meaning of the source.

| Pinned bill | NLP | AI | Principal problem |
|---|---|---|---|
| H.R. 9300, introduced | Fail | Incomplete | NLP money descriptions lose percentage bases; AI omits recipient eligibility and the one-campus restriction. |
| H.R. 1589, introduced | Fail | Fail | Broken conditional logic, incomplete source packet, omitted financial rules, and an invented notice conflict. |
| S. 5, enrolled | Fail | Incomplete | NLP does not explain the principal detention change; AI leaves the immigration eligibility condition unspecified and omits the injunction exception. |

This is an offline, model-assisted semantic review against the draft answer keys and pinned bill text. It is not independent human approval, a legal opinion, a fresh live-generation run, or a browser/usability test. No paid API calls were made. Source and answer-key hashes were checked against the saved run; all six matched. Tests passing and quotes matching do not change these verdicts.

## Inputs and reproducibility

- NLP for all three bills and repaired AI for H.R. 9300/H.R. 1589: `citation-resolution-2026-10-16.json`.
- Final S. 5 AI: `s5-citation-repair-v2-2026-10-16.json`, `results[0].output`. Do not use the older failed repair as the final analysis.
- Expectations: `answers/BILLS-119hr9300ih.md`, `answers/BILLS-119hr1589ih.md`, `answers/BILLS-119s5enr.md`.
- Primary text: matching files under `sources/`. References below are to these exact versions, not current law or a different bill version.
- NLP IDs below are `output_items[].review_item_id`; AI paths are zero-based JSON paths in `output`.

Artifact SHA-256:

```text
citation-resolution-2026-10-16.json
fd87ad58fc1c514ebd086b26d6e1abb1f3d59b431a9b971d79962c74892b31fa
s5-citation-repair-v2-2026-10-16.json
9466489e3ce1ea8724cd7d91f326d4bfd6a8fb7b8ace48e8ca107f1e10798ae2
```

## Confirmed material failures

### 1. Percentage bases disappear from the money section

H.R. 9300 §5(d) applies the minimum 20% reservation to appropriated funds **not reserved under §4**. Section 5(f) permits up to 5% and 2% of funds **not reserved under §4 or §5(d)**.

NLP `nlp-0019`–`nlp-0021` instead say “of the total amount appropriated.” The structured `source_account` also loses the exclusions. The 20% description additionally loses the requirement for at least one tier-3 practice, with the remaining practices tier 1 or 2. Accurate source expansions and other line items do not make these independently displayed money explanations accurate.

AI `funding_and_timing[1:4]` preserves the residual bases. Retain this as a positive control. The technical-assistance quote alone does not contain its inherited base; supporting context must remain accessible with it.

**Regression requirement:** verify amount, unit, comparator, gross/residual base, exclusions, recipient, purpose, and mandatory/discretionary modality together. Reject a correct percentage with the wrong denominator.

### 2. Conditions are split into apparently independent eligibility rules

H.R. 1589 §104(a)(1) requires (A) continued eligibility **and** (B) no abandonment **and** (C) one qualifying education/service/earned-income route, subject to exceptions.

NLP `nlp-0037` and `nlp-0038` each say the Secretary must remove conditions “if” one condition is met. `nlp-0039` separately gives the activity alternatives. The hardship group is worse: `nlp-0040` ends at “under subparagraphs” and `nlp-0041` contains “if the alien and (B) of paragraph (1).” These are not usable explanations of a combined rule.

AI `obligations[13]` states only continued eligibility and no abandonment. Its source packet ends at `src_0055`, the clause ending “; and”. The activity condition is absent from that saved packet, which explicitly has `truncated: true`. This establishes incomplete input; it does not prove every omission has the same cause. The output nonetheless presents an incomplete rule without marking that particular rule incomplete.

**Regression requirement:** preserve an AND/OR condition group as a unit through extraction, source selection, generation, and rendering. Truncating before a required child must prevent an unconditional eligibility explanation. Test both missing conjuncts and omitted alternative branches.

### 3. Valid quotations support an invented conflict

H.R. 1589 AI `uncertain_language[2]` says one provision makes the second notice optional while another makes it mandatory.

The pinned §102(c)(3)(F)(ii) says: “Not more than 30 days ... the Secretary shall provide a second written notice”. `src_0008` is only the opening deadline fragment; `src_0035` is its continuation. Neither says “may.” They are parts of the same rule, not conflicting rules.

**Regression requirement:** an uncertainty claim must itself be supported. Exact quote matching must not approve an invented modal verb, conflict, exception, actor, or legal effect. Join adjacent fragments before considering them separate rules.

### 4. Financial coverage is not complete

H.R. 1589 AI has one funding item: the FY2026–2036 authorization. It omits the $495 optional fee ceiling, $1,140 fee ceiling, $25 surcharge, $10,000 confidentiality fine, fee substitution, fee exemptions, and counsel-account restrictions. Some are absent from the selected packet; do not try to fix this only by asking the model to be more thorough.

The NLP has 10 financial items, but item count is not coverage. `nlp-0180` ends at “if the applicant--” with no exemption alternatives. The complete alternatives do appear in `nlp-0081`; the money view must not depend on readers discovering another section. Some answer-key financial expectations concern eligibility/documentation, not separate cash flows, and should not be counted as additional spending items.

S. 5 has five distinct >$100 harm provisions. NLP preserves five textual occurrences (`nlp-0006`, `0008`, `0010`, `0012`, `0014`) but has **zero financial items**. AI mentions the threshold collectively, without separately identifying each occurrence. These are legal harm thresholds, not appropriations or five payments. Keep them accessible and correctly classified without pretending they are a budget.

**Regression requirement:** every annotated monetary rule must map to an accessible output or an explicit unresolved entry, with the right type. Coverage must be measured by provision identity, not distinct dollar values or keyword presence.

### 5. The synopsis can describe a secondary program as the bill's purpose

H.R. 1589 NLP orientation starts “Creates a grant program for nonprofit organizations to help eligible applicants,” then lists money categories. The bill principally creates immigration-status adjustment routes. The grants are supporting machinery, not an adequate whole-bill synopsis.

S. 5 has no NLP purpose clause. Its principal new detention criteria are not explained by the 15 output items, which mostly show redesignations, court-expediting rules, harm clauses, and an unsimplified detainer passage.

**Regression requirement:** independently annotated primary purpose and affected population must be explained, not merely mentioned somewhere in evidence. A list of extracted financial categories is not a synopsis.

### 6. Fluent AI prose still leaves eligibility and scope unresolved

- H.R. 9300: the AI explains high-need students well, but does not explain who can receive grants: public institutions, qualifying partnerships/consortia, and the defined Tribal entity. It omits §5(h)'s one-campus-at-a-time limit. Eligibility cannot be reduced to the phrase “eligible entities.”
- S. 5: `key_impacts[0]` lists criminal triggers without the required INA inadmissibility condition. Overview/obligations acknowledge “immigration conditions,” so this is incomplete explanation rather than an unequivocal claim that all noncitizens qualify. The actual referenced grounds remain unidentified in the prose.
- S. 5: §3(f)'s limited injunction-bar exception is absent. Broadly summarizing five enforcement routes does not explain which routes receive that exception.

**Regression requirement:** definitions and internal references needed to understand a material rule must travel with that rule. External legal dependencies should remain explicit, rather than invented or silently dropped.

## Answer-key coverage ledger

Legend: **C** = relevant meaning covered in reviewed output; **P** = partial/fragmented or only raw-source fallback; **M** = missing from explanatory output; **E** = misleading or incorrect explanation. These are model-assisted judgments, not automated semantic scores. C is not a usability pass. Grouped rows retain each answer-key ID; no percentage score is claimed from these heterogeneous expectations.

### H.R. 9300

| Expectation | NLP | AI | Evidence / gap |
|---|---|---|---|
| F01 purpose | C | C | NLP orientation; AI overview. |
| F02 high-need populations | M | C | AI overview lists groups; NLP lacks the definition. |
| F03 recipient eligibility | P | M | NLP eligible-entity definition present, Tribal-entity definition absent; AI leaves both undefined. |
| F04 competitive grants/application content | P | C | NLP application heading lacks substantive checklist; AI obligations and impacts supply it. |
| F05 required reform selection | P | P | NLP only two examples; AI gives four but does not explain the at-least-one application requirement. |
| F06 uses of funds | P | C | NLP raw-source fallback; AI required-plan obligation plus permitted examples. |
| F07 evaluations/report | P | P | Both omit the similar-background comparison requirement; deadline retained. |
| F08 campus limit | C | M | NLP 0017; absent from AI. |
| F09 completion definition/evidence tiers | P | P | NLP completion definition only; AI tiers but not completion definition. |
| M01 mandatory 2% Tribal reservation | C | C | Correct gross annual base; recipient definition gap separately recorded. |
| M02 FY2027–2032 grants, no fixed dollars | P | C | NLP period present; AI also states no dollar total. |
| M03 minimum 20% residual reservation | E | C | NLP 0019 wrong base and missing tier restrictions. |
| M04 optional 5% residual set-aside | E | C | NLP 0020 wrong base. |
| M05 optional 2% technical-assistance set-aside | E | C | NLP 0021 wrong base. |
| M06 required plan/reform spending | P | C | NLP raw fallback; AI obligation. |
| M07 emergency aid/incentives as permitted uses | P | C | Present within NLP fallback and AI examples, not separate appropriations. |
| M08 evaluation grants/contracts | C | C | Both retain direction; neither invents a fixed appropriation. |
| M09 Pell reporting, not benefit change | M | C | AI impact on application reporting; NLP application list missing. |

### H.R. 1589

| Expectation | NLP | AI | Evidence / gap |
|---|---|---|---|
| F01 adjustment routes/whole purpose | E | P | NLP synopsis miscenters grants; AI broad purpose but incomplete route distinctions. |
| F02 title-I eligibility | P | P | NLP 0002 truncated; AI generic categories/date without full criteria. |
| F03 education routes/minor protection | P | P | Protection present; actual alternatives incompletely explained. |
| F04 criminal bars/waivers | P | M | NLP raw fallback and waiver items; AI not an explanation of bars. |
| F05 provisional-denial grounds | P | P | Both omit core grounds; AI acknowledges absent packet dependencies. |
| F06 notice/review protections | P | E | NLP fragmented; AI invents optional-notice conflict and omits key deadlines. |
| F07 conditional duration/revocation/return | P | P | Revocation present; full 10-year/status-return account absent from AI. |
| F08 removing conditions | E | E | Conjunction/required activity loss, detailed above. |
| F09 early removal/initial full status/naturalization | P | M | NLP 0048–0056 fragmented; AI does not explain these protections. |
| F10 higher-education rule repeal | P | M | NLP 0057–0058; external meaning not supplied. |
| F11 title-II criteria | E | M | NLP 0060–0063 split mandatory conjunctions, eligible-group clause truncated. |
| F12 inspected/admitted amendment | M | M | No substantive explanation in reviewed items. |
| F13 biometrics/checks/convictions | P | P | NLP 0072 incorrectly starts “Allows ... not grant”; AI points to missing §302 packet content. |
| F14 removal/application/travel/work protections | P | P | NLP broader but fragmented; AI work and withdrawal only. |
| F15 absences/exceptions | E | M | NLP 0086 is “Requires , an alien to be considered to have failed to maintain.” |
| F16 departed applicants/no cap | P | M | NLP waiver useful; no-cap sentence broken across 0091–0092. |
| F17 appeals/removal exception | C | P | NLP 0093–0098; AI establishment deadline only. |
| F18 documentation safeguards | P | M | Many repetitive NLP document entries; not a coherent checklist of safeguards. |
| F19 implementation rules | C | P | AI omits 180-day finalization and PRA exclusion. |
| F20 confidentiality/exceptions | C | M | NLP 0152–0155; absent from AI. |
| F21 nonprofit assistance/other status/reporting | P | P | NLP broad coverage; AI grant authorization only. |
| M01 optional $495 ceiling | C | M | NLP 0175. |
| M02 DACA fee rule/exception | C | M | NLP 0176 preserves exception. |
| M03 condition-removal processing fee | C | M | NLP 0177. |
| M04 substituted fee, no double charge | C | M | NLP 0178. |
| M05 earned-income duration | P | M | NLP 0039 contains it in a malformed combined eligibility sentence. |
| M06 higher-education repeal | P | M | NLP repeal, not a new dollar benefit. |
| M07 title-II $1,140 ceiling | C | M | NLP 0179 plus title-II timing item. |
| M08 fee-exemption alternatives | E | M | NLP financial item 0180 incomplete; 0081 elsewhere contains alternatives. |
| M09 $10,000 knowing-misuse fine | C | M | NLP 0181. |
| M10 nonprofit grant uses | C | P | NLP 0156–0164; AI authorization lacks use restrictions. |
| M11 FY2026–2036 authorization/availability | C | P | AI authorization correct but omits availability until expended. |
| M12 $25 surcharge/exceptions | C | M | NLP 0184. |
| M13 counsel account/use/reporting | P | M | NLP account and reporting present, not complete receipts/use explanation. |
| M14 counsel funding/appointment | C | P | AI counsel appointment, not funding source. |
| M15 income documentation, not taxes | C | M | NLP document list retains evidentiary purpose. |

### S. 5

| Expectation | NLP | AI | Evidence / gap |
|---|---|---|---|
| LR-F01 principal detention change | M | P | AI crimes present, INA inadmissibility grounds unspecified. |
| LR-F02 local definitions/detainer/custody | P | C | NLP raw fallback; AI explains these. |
| LR-F03 admission/inspection enforcement | P | P | NLP malformed standing actor; AI groups routes. |
| LR-F04 release/bond/parole enforcement | P | P | Generic fragments/grouped route description, not complete route scope. |
| LR-F05 visa-discontinuance enforcement | P | P | Does not separately identify Secretary of State as defendant. |
| LR-F06 parole limits/Secretary replacement | P | P | Route named by AI; limits/replacement not explained. |
| LR-F07 removal-period enforcement | P | P | Route named, not fully explained. |
| LR-F08 expedited proceedings | C | C | No invented fixed deadline. |
| LR-F09 limited injunction exception | M | M | §3(f) absent. |
| LR-M01–M05 five harm thresholds | P | P | NLP five raw-like clauses but no financial entries; AI one grouped threshold without distinct occurrence mapping. |
| LR-M06 no specified funding, not no cost | M | M | Neither supplies this explicit distinction; no invented dollar appropriation observed. |

## Readability and source support

- **H.R. 9300 AI is the strongest reader-facing output** of these three: clear purpose, beneficiary groups, no invented dollar budget, and correct residual percentages. It still is not complete.
- H.R. 1589 AI is more readable than NLP but spends substantial space on procedural duties while omitting core eligibility and money. Shortness alone is not success.
- S. 5 AI gives a useful broad orientation, but “specified immigration conditions” leaves the central reader question unanswered.
- NLP regularly emits “Requires [actor] to,” section headings inside sentences, dangling clauses, and repeated inherited introductions. H.R. 1589's 187 flattened output items do not constitute 187 independently understandable explanations.
- A raw fallback is safer than a false paraphrase, but is only partial credit for communicating meaning. It cannot receive a readability pass.
- Matching quotations establish text location. They do not establish entailment: the invented notice conflict and incomplete §104 eligibility rule demonstrate this directly.
- Actual screen visibility, source-link navigation, and comprehension by people unfamiliar with these bills remain untested in this review. Do not convert these judgments into a claimed human readability score.

## Bounded next correction and regression acceptance

Fix the shared evidence/condition representation before tuning prose or repeatedly regenerating outputs:

1. Preserve complete operative groups: parent conditions, AND/OR branches, exceptions, definitions, percentage bases, and source spans. Incomplete parsing must retain the whole affected source group, not publish a misleading standalone clause.
2. Build AI input from those complete groups with section coverage accounting. Internal references should bring in their same-bill targets. If the budget cannot include required dependencies, mark the affected explanation incomplete; do not call packet omission an unresolved fact about the bill.
3. Make the financial ledger use the same complete groups. Do not build a second abbreviated interpretation that drops restrictions already retained elsewhere.
4. Add fixed regressions for the six failure classes above, plus positive controls: H.R. 9300 AI residual bases; S. 5 >$100 rather than ≥$100; fee ceiling versus mandatory exact charge; authorization versus appropriation; fee substitution versus addition; all/any condition logic; correct Secretary; no invented ambiguity.
5. Replay saved outputs first. These semantic failures must remain failures even when all citation strings validate. New generation is justified only after source selection changes, with model/prompt/source hashes and token usage recorded separately.
6. Rerun these three bills before expanding to ten. Require no incorrect material explanations, no missing annotated financial rules, and complete conditions for each explained rule. Then conduct the actual-screen reader exercise: what changes, who is affected, what money is involved?

The regression cases above are specified, **not implemented as executable tests in this report-only pass**. Existing draft answer keys also still need independent human acceptance. No production code, running service, or answer key was changed by this review.
