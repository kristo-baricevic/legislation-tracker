# H.R. 1589 full-source AI evaluation — 2026-10-16

## Verdict

**Input coverage fixed; reader-quality gate remains failed.** The live generation
received the complete pinned bill, including sections 306–313. It now explains
several previously missing monetary rules, but still omits material provisions
and conditions. More input capacity solved source omission, not output coverage.

This is a model-assisted semantic review against the draft independent answer
key and pinned source, not independent human acceptance or a screen test. The
application database and running services were not changed.

## Run evidence

- Artifact: `hr1589-full-source-live-2026-10-16.json`.
- Model: `gpt-6-luna`; prompt 1.3; source packet 1.2.
- Full request: 81,290 serialized bytes; 34 citation chunks; no omitted sections.
- Limits: 100,000 conservative input units and 8,000 output tokens per call.
- Actual calls: one generation plus one citation repair; no retries.
- Initial generation: 18,560 input / 3,931 output tokens.
- Citation repair: 817 input / 53 output tokens.
- Total: 19,377 input / 3,984 output tokens; 32.26 seconds.
- Two repaired citations; no unresolved citations; schema/quote validation passed.
- Initial output used less than half its output allowance. No evidence that the
  output-token ceiling caused these omissions; raising it again is not justified
  by this run.
- Mechanical assessment: `hr1589-full-source-assessment-2026-10-16.json`.
  That command replays this **fresh** artifact. Its generic historical-replay
  wording does not mean this generation used the old source policy. Other bills
  were not regenerated in this run.

## Material remaining problems

1. **Missing financial rule:** no explanation of the maximum $10,000 fine for
   knowing misuse of protected information (§309(d), answer M09). The complete
   source was supplied. Confidentiality and its exceptions are also missing.
2. **Incomplete removal-of-conditions rule:** `key_impacts[1]` lists the activity
   paths and hardship route but omits continuing §102(b)(1)(C) eligibility and
   nonabandonment, which §104(a)(1)(A)–(B) and (a)(2)(A) require. It also leaves
   the hardship tests and referenced citizenship requirement unexplained. A
   reader cannot determine the actual combined eligibility rule from the prose.
3. **Missing fee substitution:** output never explains that initially qualified
   nonconditional applicants pay the removal-of-conditions fee instead of the
   title-I application fee (§104(c)(2)(C), M04).
4. **Vague fee exceptions:** `funding_and_timing[4]` says “except for the stated
   exceptions” without identifying §303(c) or the unresolved §302 cross-reference.
   `key_impacts[3]` omits the serious-chronic-disability exemption and gives no
   age/income thresholds in prose. Correct quotes are not a substitute for the
   explanation.
5. **Evidence presentation remains awkward:** repair correctly relocates a fee
   quote into `src_0013`, but its selected span ends mid-word; the repaired title
   quote begins mid-word. Both match source offsets, yet are poor standalone
   evidence excerpts. The table-of-contents quote is also unnecessary alongside
   the operative section headings supporting the overview.

## Answer-key comparison

Paths below are zero-based in `results[0].output`. C = core meaning covered;
P = partial; M = missing. These judgments are not an automatic percentage score
and C does not imply every condition or citation has independent approval.

| Key | Result | Output / remaining gap |
|---|---|---|
| F01 | C | `overview[0]` distinguishes the two principal adjustment routes; no citizenship grant claim. |
| F02 | P | `key_impacts[0]` names condition categories but leaves dates, eligible populations and restrictions largely in quotes or absent. |
| F03 | P | Education/enrollment categories mentioned; alternatives and minor protection not explained. |
| F04 | M | Criminal bars and waiver conditions not explained. |
| F05 | P | `uncertain_language[1]` names provisional-denial grounds but omits required evidence and safeguards. |
| F06 | M | Notice, response, review and counsel-request procedures absent; old invented optional-notice conflict no longer appears. |
| F07 | P | `funding_and_timing[6]` gives ten-year duration/extension; revocation and status return absent. |
| F08 | P | `key_impacts[1]` activity routes present, required conjunctions and hardship criteria missing. |
| F09 | M | Early condition removal, initial full status and naturalization rules not explained. |
| F10 | P | `key_impacts[5]` explains repeal and external-context limitation; retroactive effective rule absent. |
| F11 | P | `key_impacts[2]` and timing item identify route/deadline; TPS/DED reference dates and waiver rules absent from prose. |
| F12 | M | Inspected/admitted statutory amendment absent. |
| F13 | P | `obligations[0]` impairment alternative present; checks, conviction rules and Selective Service not explained. |
| F14 | P | Removal protection present in timing item; work authorization, pending travel, existing orders and withdrawal absent. |
| F15 | M | Absence thresholds and exceptions absent. |
| F16 | M | Departed applicants and no numerical cap absent. |
| F17 | P | `funding_and_timing[7]` preserves criminal/security exception; appeal setup and return after reversal absent. |
| F18 | P | `key_impacts[3]` mentions records; documentation and anti-restriction safeguards incomplete. |
| F19 | P | `obligations[1]` preserves 90/180-day deadlines; immediate applications and PRA exclusion absent. |
| F20 | M | Confidentiality, exceptions and penalty absent. |
| F21 | P | Grant assistance and annual reporting covered; preservation of other status routes absent. |
| M01 | P | Optional $495 ceiling and exemption in `funding_and_timing[0]`; cost-commensurate condition missing. |
| M02 | P | Same item gives streamlined DACA fee rule/exception; January 2017 eligibility baseline and exception's cost basis missing. |
| M03 | P | `funding_and_timing[1]` reasonable fee/no fixed cap/exemption; cost-commensurate condition appears only in quote. |
| M04 | M | No-double-charging/substitution rule absent. |
| M05 | P | Earned-income route mentioned; three years AND 75% and enrollment reduction not explained in prose. |
| M06 | P | Repeal explained without invented dollar benefit; retroactivity omitted. |
| M07 | P | Required fee up to $1,140/exemption and deadline present; cost-commensurate basis only in quote. |
| M08 | P | Some exemption groups mentioned; disability alternative, thresholds and supporting-evidence requirements incomplete. |
| M09 | M | $10,000 maximum knowing-misuse fine absent. |
| M10 | P | `key_impacts[4]` covers competitive nonprofit assistance uses; authorized-practice restriction absent. |
| M11 | C | `funding_and_timing[3]` unquantified FY2026–2036 authorization and availability until spent; not mislabeled a fixed appropriation. |
| M12 | P | `funding_and_timing[4]` $25 surcharge/purpose; exceptions unnamed. |
| M13 | P | Counsel purpose and two-year reporting present; Treasury account/deposit, availability and adjustment target not fully explained. |
| M14 | P | Counsel purpose present; appointment on request and AG procedure deadline absent. |
| M15 | M | Earned-income documentation alternatives not explained; no invented tax obligation. |

## Recommended next correction

Keep these input limits. Make the generation instructions require a complete
financial checklist (fees, waivers, substitutions, fines, authorizations and
restricted accounts), and require each summarized eligibility rule to carry its
material conjuncts and alternatives. Add answer-key regressions for M04/M09 and
F08, then rerun this same pinned bill. Do not treat keyword presence or valid
quotes as proof that the explanation preserves meaning. Multi-pass is not yet
justified as the fix: this request included all source and did not exhaust output.
