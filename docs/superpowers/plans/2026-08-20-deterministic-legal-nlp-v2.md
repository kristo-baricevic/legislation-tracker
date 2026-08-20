# Deterministic Legal-NLP v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a federal-first, deterministic legal extraction pipeline that produces validated structured bill contracts with exact evidence and renders them in the bill-detail UI without any LLM or external NLP service.

**Architecture:** Keep Celery and the existing `BillContract`/`EvidenceSpan` persistence flow as orchestration, but move extraction into focused, ORM-free modules for structure parsing, legal rules, controlled rendering, schema validation, and legacy fallback. Store `2.0-legal-nlp` contracts beside existing `1.1-deterministic` history and select the appropriate frontend renderer by schema version.

**Tech Stack:** Python 3, Django, Celery, PostgreSQL/SQLite tests, `jsonschema>=4.23,<5`, pytest, TypeScript, React 19, Next.js 16 App Router, Vitest, Testing Library, and Playwright.

**Spec:** `docs/superpowers/specs/2026-08-20-deterministic-legal-nlp-v2-design.md`

## Global Constraints

- Do not add an LLM, hosted NLP API, embeddings, spaCy, local statistical model, provider adapter, API key, or extraction-time network call.
- Target federal bill structure only; state, missing-text, unsupported, zero-claim, and invalid-v2 cases must return the unchanged `1.1-deterministic` contract.
- Use schema version `2.0-legal-nlp` and extractor version `federal-rules-2.0.0` exactly.
- Preserve the original `BillDocument.extracted_text` string for Python character offsets; every evidence quote must equal `source_text[start_char:end_char]` exactly.
- Require evidence for `plain_summary`, every `key_provisions[i].text`, every category `display_text`, and both `definitions[i].term` and `definitions[i].display_text`.
- Cap each extracted category at 100 items and add `item_limit_reached:<category>` when a cap is reached.
- Do not add a database migration or a new API endpoint.
- Keep metadata-only contracts on `1.1-deterministic`.
- Keep the v1 client renderer and mixed v1/v2 history working.
- Backfill must be preview-only without `--execute`, require a narrowing selector, use the durable queue, and default to active document versions.
- Do not implement GitHub Actions, RSS, or newsletters.
- Follow test-driven development: observe each focused test fail before implementing its behavior.
- Route every command through `rtk`, including git, Python, pytest, pnpm, Node, and searches.
- Before frontend implementation, read `legislation-tracker-client/node_modules/next/dist/docs/01-app/01-getting-started/05-server-and-client-components.md`; keep the existing page as a Client Component because it owns effects and event handlers.

---

## Planned File Map

### Backend production files

- `legislation-tracker-backend/apps/legislation/extraction/__init__.py`: public extraction constants and service export.
- `legislation-tracker-backend/apps/legislation/extraction/types.py`: immutable extraction dataclasses and expected-rejection exception.
- `legislation-tracker-backend/apps/legislation/extraction/federal_structure.py`: exact-offset structure and sentence parsing.
- `legislation-tracker-backend/apps/legislation/extraction/legal_rules.py`: all supported deterministic claim rules and normalization.
- `legislation-tracker-backend/apps/legislation/extraction/renderer.py`: controlled display text, summary selection, deduplication, caps, and evidence paths.
- `legislation-tracker-backend/apps/legislation/extraction/schema.py`: JSON Schema and evidence semantic validation.
- `legislation-tracker-backend/apps/legislation/extraction/legacy.py`: current v1 extractor behavior moved out of `tasks.py`.
- `legislation-tracker-backend/apps/legislation/extraction/service.py`: federal-v2 selection and expected fallback.
- `legislation-tracker-backend/apps/legislation/extraction/schemas/contract_v2.json`: exact v2 JSON contract.
- `legislation-tracker-backend/apps/legislation/tasks.py`: call the service, persist its version/evidence, version durable dedupe, and log extraction metrics.
- `legislation-tracker-backend/apps/legislation/management/commands/backfill_contracts.py`: preview-first bounded durable backfill.
- `legislation-tracker-backend/requirements/base.txt`: explicit `jsonschema` production dependency.

### Backend tests and fixtures

- `legislation-tracker-backend/apps/legislation/tests/test_extraction_schema.py`
- `legislation-tracker-backend/apps/legislation/tests/test_federal_structure.py`
- `legislation-tracker-backend/apps/legislation/tests/test_legal_rules.py`
- `legislation-tracker-backend/apps/legislation/tests/test_contract_renderer.py`
- `legislation-tracker-backend/apps/legislation/tests/test_extraction_service.py`
- `legislation-tracker-backend/apps/legislation/tests/test_extraction_evaluation.py`
- `legislation-tracker-backend/apps/legislation/tests/test_backfill_contracts_command.py`
- `legislation-tracker-backend/apps/legislation/tests/fixtures/legal_nlp/*.json`
- Existing `test_tasks.py` and `test_public_api.py`: persistence, queue, fallback, and compatibility coverage.

### Frontend files

- `legislation-tracker-client/lib/contracts.ts`: evidence and v1/v2 contract types, runtime guard, summary helper, and evidence grouping.
- `legislation-tracker-client/lib/api.ts`: use the versioned contract type.
- `legislation-tracker-client/app/bills/[id]/contract-section.tsx`: v1 and v2 contract presentation.
- `legislation-tracker-client/app/bills/[id]/page.tsx`: import the component and shared summary helper.
- `legislation-tracker-client/tests/contracts.test.ts`: runtime type/helper tests.
- `legislation-tracker-client/tests/components/contract-section.test.tsx`: structured rendering and evidence behavior.
- Existing bill-detail component tests: integration and mixed-history behavior.
- `legislation-tracker-client/e2e/contract-detail.spec.ts`: live-API v2 bill-detail flow.

### Test support and documentation

- `legislation-tracker-backend/scripts/start-e2e-api.sh`: seed one v2 contract in the disposable E2E database.
- `legislation-tracker-backend/docs/PHASE_5_CONTRACT.md`: describe the implemented v2 pipeline.
- `legislation-tracker-backend/docs/PHASE_5_3_PLAN.md`: mark the old provider-oriented plan as superseded by the approved deterministic design.
- `legislation-tracker-backend/apps/legislation/README.md`: update the Phase 5 summary and file map.

---

### Task 1: Add v2 types, JSON Schema, and evidence validation

**Files:**
- Create: `legislation-tracker-backend/apps/legislation/extraction/__init__.py`
- Create: `legislation-tracker-backend/apps/legislation/extraction/types.py`
- Create: `legislation-tracker-backend/apps/legislation/extraction/schema.py`
- Create: `legislation-tracker-backend/apps/legislation/extraction/schemas/contract_v2.json`
- Modify: `legislation-tracker-backend/requirements/base.txt`
- Test: `legislation-tracker-backend/apps/legislation/tests/test_extraction_schema.py`

**Interfaces:**
- Produces: `SCHEMA_VERSION = "2.0-legal-nlp"` and `EXTRACTOR_VERSION = "federal-rules-2.0.0"`.
- Produces: `SourceSpan`, `StructuralSection`, `ExtractedClaim`, `EvidenceCandidate`, and `ExtractionResult` frozen dataclasses with the exact fields from the design.
- Produces: `ExpectedExtractionRejection(reason: str)` whose `.reason` is one approved fallback code.
- Produces: `validate_contract(contract_json: Mapping[str, object], evidence: Sequence[EvidenceCandidate], source_text: str) -> None`.
- Raises: `ContractValidationError(reason: str, message: str)` for JSON shape, field-path, offset, quote-length, quote-match, or missing-evidence failures. Its `.reason` is exactly `schema_validation_failed` or `evidence_validation_failed`.

- [ ] **Step 1: Add the dependency and write failing schema/evidence tests**

Add `jsonschema>=4.23,<5` to `requirements/base.txt`. Create tests covering one minimal valid contract and these independent failures: extra object property, missing required category array, wrong schema-version literal, unknown field path, out-of-bounds span, mismatched quote, quote longer than 4,000 characters, and missing evidence for a visible field.

Use this minimal valid fixture in the tests:

```python
contract = {
    "schema_version": "2.0-legal-nlp",
    "title": "Test Act",
    "version_label": "Introduced",
    "extraction": {
        "method": "federal-rules",
        "parser_version": "2.0.0",
        "sections_seen": 1,
        "sections_with_claims": 1,
        "warnings": [],
    },
    "plain_summary": "The Secretary is required to publish a report.",
    "key_provisions": [{
        "kind": "requirement",
        "section_label": "Sec. 2",
        "heading": "Reports",
        "text": "The Secretary is required to publish a report.",
    }],
    "requirements": [{
        "section_label": "Sec. 2",
        "display_text": "The Secretary is required to publish a report.",
        "modality": "required",
        "actor": "The Secretary",
        "action": "publish a report",
        "object": None,
        "conditions": [],
    }],
    "funding_items": [],
    "timeline_items": [],
    "definitions": [],
    "applicability": [],
    "amendment_operations": [],
    "limitations": [
        "This automated summary is based on explicit patterns in the bill text and is not legal advice."
    ],
}
```

Create three evidence candidates over the same exact source sentence for `plain_summary`, `key_provisions[0].text`, and `requirements[0].display_text`.

- [ ] **Step 2: Run the focused tests and confirm the missing package failure**

Run from `legislation-tracker-backend`:

```bash
rtk .venv/bin/pytest apps/legislation/tests/test_extraction_schema.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'apps.legislation.extraction'`.

- [ ] **Step 3: Install the updated development requirements**

```bash
rtk .venv/bin/python -m pip install -r requirements/dev.txt
```

Expected: `jsonschema` 4.x is installed successfully in the backend virtual environment.

- [ ] **Step 4: Add the immutable types and approved constants**

Implement these exact public shapes in `types.py`:

```python
@dataclass(frozen=True)
class SourceSpan:
    text: str
    start_char: int
    end_char: int

@dataclass(frozen=True)
class StructuralSection:
    label: str
    heading: str | None
    level: str
    span: SourceSpan
    parent_label: str | None

@dataclass(frozen=True)
class ExtractedClaim:
    category: str
    fields: dict[str, object]
    section_label: str | None
    evidence: tuple[SourceSpan, ...]
    rule_id: str

@dataclass(frozen=True)
class EvidenceCandidate:
    field_path: str
    quoted_text: str
    start_char: int
    end_char: int
    page_number: int | None = None

@dataclass(frozen=True)
class ExtractionResult:
    schema_version: str
    contract_json: dict[str, object]
    evidence: tuple[EvidenceCandidate, ...]
    method: str
    fallback_reason: str | None = None
```

`ExpectedExtractionRejection` accepts only the six reason strings in the spec and raises `ValueError` if constructed with any other reason.

- [ ] **Step 5: Implement the complete JSON Schema**

Use JSON Schema draft 2020-12. Set `additionalProperties: false` on the top level, `extraction`, and every item definition. Require every top-level key shown in the fixture. Set all category arrays to `maxItems: 100`.

Define item requirements exactly as follows:

```text
key_provision: kind, section_label, heading, text
requirement: section_label, display_text, modality, actor, action, object, conditions
funding: section_label, display_text, amount, amount_type, currency, fiscal_years, purpose
timeline: section_label, display_text, timeline_type, date, relative_value, relative_unit, trigger
definition: section_label, display_text, term, definition, definition_type
applicability: section_label, display_text, subject, scope, applicability_type
amendment: section_label, display_text, target, operation, removed_text, inserted_text
```

Constrain enums to the design categories, nullable fields with `type: ["string", "null"]`, decimal money strings with `^[0-9]+(?:\\.[0-9]{2})?$`, ISO dates with `^\\d{4}-\\d{2}-\\d{2}$`, and relative units to `days`, `months`, or `years`.

- [ ] **Step 6: Implement schema and semantic evidence validation**

Load the schema once with `functools.lru_cache`. Use `Draft202012Validator.iter_errors()` and sort errors by their absolute path for stable messages.

Resolve only the approved path grammar with this segment expression:

```python
SEGMENT_RE = re.compile(r"^(?P<key>[a-z_][a-z0-9_]*)(?:\[(?P<index>\d+)\])?$")
```

Build required visible paths deterministically from the contract arrays. Reject a contract unless every required path has at least one valid `EvidenceCandidate`. Verify the exact substring and the 4,000-character cap before returning.

- [ ] **Step 7: Run schema tests and the existing canonical-hash tests**

```bash
rtk .venv/bin/pytest apps/legislation/tests/test_extraction_schema.py apps/legislation/tests/test_contract_json.py -q
```

Expected: all focused tests pass.

- [ ] **Step 8: Commit the schema boundary**

```bash
rtk git add legislation-tracker-backend/requirements/base.txt legislation-tracker-backend/apps/legislation/extraction legislation-tracker-backend/apps/legislation/tests/test_extraction_schema.py
rtk git commit -m "feat(contract): add legal NLP v2 schema validation"
```

---

### Task 2: Parse federal legislative structure with exact offsets

**Files:**
- Create: `legislation-tracker-backend/apps/legislation/extraction/federal_structure.py`
- Test: `legislation-tracker-backend/apps/legislation/tests/test_federal_structure.py`

**Interfaces:**
- Consumes: `SourceSpan` and `StructuralSection` from Task 1.
- Produces: `parse_federal_structure(source_text: str) -> tuple[StructuralSection, ...]`.
- Produces: `sentence_spans(section: StructuralSection, source_text: str) -> tuple[SourceSpan, ...]`.
- Raises: `ExpectedExtractionRejection("unrecognized_federal_structure")` when no `SEC.` or `SECTION` marker is present.

- [ ] **Step 1: Write exact-offset parser tests**

Cover `TITLE`, `SUBTITLE`, `PART`, `SEC.`, `SECTION`, alphanumeric section labels, same-line headings, next-line headings, `(a)/(1)/(A)/(i)` markers, repeated sentences, Unicode apostrophes/dashes, leading whitespace, and a trailing sentence without punctuation.

The core assertion must always use the original string:

```python
for section in sections:
    assert source[section.span.start_char:section.span.end_char] == section.span.text
for sentence in sentence_spans(sections[0], source):
    assert source[sentence.start_char:sentence.end_char] == sentence.text
```

Add a negative test proving `"This bill creates a program."` raises the approved unrecognized-structure rejection.

- [ ] **Step 2: Run the parser tests and confirm the import failure**

```bash
rtk .venv/bin/pytest apps/legislation/tests/test_federal_structure.py -q
```

Expected: FAIL because `federal_structure.py` does not exist.

- [ ] **Step 3: Implement line-anchored structural markers**

Compile case-insensitive, multiline regexes for:

```python
SECTION_RE = re.compile(
    r"(?im)^(?P<indent>[ \t]*)(?P<kind>SEC\.|SECTION)\s+"
    r"(?P<label>[0-9]+[A-Z]?(?:-[0-9A-Z]+)*)\.\s*(?P<heading>[^\n]*)$"
)
CONTAINER_RE = re.compile(
    r"(?im)^[ \t]*(?P<kind>TITLE|SUBTITLE|PART|SUBPART|CHAPTER)\s+"
    r"(?P<label>[IVXLCDM0-9A-Z-]+)(?:[.—-]\s*|\s+)(?P<heading>[^\n]*)$"
)
SUBDIVISION_RE = re.compile(r"(?m)^[ \t]*(?P<label>\([a-z0-9A-Zivxlcdm]+\))\s*")
```

Create spans from each marker start through the next marker of the same or higher level, or end of text. Preserve source text exactly and normalize only labels/headings stored as metadata.

- [ ] **Step 4: Implement sentence spans within a structural range**

Use punctuation followed by whitespace plus the section end, not `str.split()`. Translate every local regex match back with `section.span.start_char`. Keep the terminal fragment when it contains non-whitespace.

- [ ] **Step 5: Run parser and schema tests**

```bash
rtk .venv/bin/pytest apps/legislation/tests/test_federal_structure.py apps/legislation/tests/test_extraction_schema.py -q
```

Expected: all focused tests pass, including repeated-sentence location assertions.

- [ ] **Step 6: Commit the structural parser**

```bash
rtk git add legislation-tracker-backend/apps/legislation/extraction/federal_structure.py legislation-tracker-backend/apps/legislation/tests/test_federal_structure.py
rtk git commit -m "feat(contract): parse federal bill structure"
```

---

### Task 3: Extract operative modalities, definitions, and applicability

**Files:**
- Create: `legislation-tracker-backend/apps/legislation/extraction/legal_rules.py`
- Test: `legislation-tracker-backend/apps/legislation/tests/test_legal_rules.py`

**Interfaces:**
- Consumes: `StructuralSection`, `SourceSpan`, and `sentence_spans()`.
- Produces: `extract_modality_claims(source_text: str, sections: Sequence[StructuralSection]) -> tuple[ExtractedClaim, ...]`.
- Produces: `extract_definition_claims(...)` and `extract_applicability_claims(...)` with the same parameters and return type.
- Produces: `extract_claims(source_text: str, sections: Sequence[StructuralSection]) -> tuple[ExtractedClaim, ...]`, which later tasks extend.

- [ ] **Step 1: Write positive and adversarial rule tests**

Use federal-style source blocks and assert normalized fields plus exact evidence. Include each supported modality phrase, a definitions section, explicit `The term "covered entity" means`, `includes`, `applies to`, `does not apply to`, `eligible entity`, and exclusion language.

Add negative tests for:

```text
TABLE OF CONTENTS containing “Sec. 4. The Secretary shall report”
“The term ‘requirement’ means a rule that shall apply ...” inside a definition
“strike ‘the Secretary shall publish’” inside amendment payload text
“The report may discuss whether the agency should act”
```

Assert that none becomes a current requirement or permission.

- [ ] **Step 2: Run the focused tests and observe the missing functions**

```bash
rtk .venv/bin/pytest apps/legislation/tests/test_legal_rules.py -q
```

Expected: FAIL on missing `legal_rules` imports.

- [ ] **Step 3: Implement operative-context filtering**

Mark table-of-contents ranges, definition-only sentences, amendment instruction payloads, and explicitly quoted ranges before modality matching. Filtering must compare candidate evidence offsets to excluded ranges; it must not remove matching text globally because the same words may appear later as operative language.

- [ ] **Step 4: Implement high-precision modality rules**

Use this ordered modal expression so negative forms win:

```python
MODAL_RE = re.compile(
    r"\b(?P<modal>shall not|may not|is prohibited from|is required to|"
    r"is authorized to|shall|must|may)\b",
    re.IGNORECASE,
)
```

Treat text before the modal in the same operative clause as `actor` and text after it through the clause terminator as `action`. Strip structural lead-ins such as `(a) IN GENERAL.—` while preserving the evidence span as the full operative sentence. Emit nothing if actor or action becomes empty or exceeds the schema limits. Map modals to `required`, `prohibited`, or `permitted`; keep `object: None` unless an explicit rule isolates it, and store explicit `if`, `when`, `unless`, or `subject to` phrases in `conditions`.

- [ ] **Step 5: Implement definition and applicability rules**

Definitions require either a definitions-section ancestor or the explicit `The term <quoted term> means/includes` form. Applicability claims use exact phrases and enum values `applies`, `does_not_apply`, `eligible`, or `excluded`. Each claim carries one exact sentence `SourceSpan` and a stable `rule_id`, such as `modality.shall.v1` or `definition.term_means.v1`.

- [ ] **Step 6: Run rule and parser tests**

```bash
rtk .venv/bin/pytest apps/legislation/tests/test_legal_rules.py apps/legislation/tests/test_federal_structure.py -q
```

Expected: all focused tests pass and every evidence slice equals its source substring.

- [ ] **Step 7: Commit the first rule families**

```bash
rtk git add legislation-tracker-backend/apps/legislation/extraction/legal_rules.py legislation-tracker-backend/apps/legislation/tests/test_legal_rules.py
rtk git commit -m "feat(contract): extract operative legal provisions"
```

---

### Task 4: Extract funding, timelines, and amendment operations

**Files:**
- Modify: `legislation-tracker-backend/apps/legislation/extraction/legal_rules.py`
- Modify: `legislation-tracker-backend/apps/legislation/tests/test_legal_rules.py`

**Interfaces:**
- Produces: `extract_funding_claims(...)`, `extract_timeline_claims(...)`, and `extract_amendment_claims(...)`.
- Extends: `extract_claims()` to return every category in stable source-offset order.
- Produces: `normalize_usd_amount(raw: str) -> str`, returning two fractional digits.

- [ ] **Step 1: Add failing funding normalization and extraction tests**

Cover `$25,000,000`, `$1.5 million`, authorization versus direct appropriation, fiscal year 2027, fiscal years 2027 through 2029, and `such sums as may be necessary`. Assert `"25000000.00"`, `currency == "USD"`, inclusive fiscal-year arrays, and `amount_type` values `specified` or `such_sums`.

- [ ] **Step 2: Add failing timeline and amendment tests**

Cover `January 1, 2028`, `not later than 90 days after enactment`, `2 years after the date of enactment`, `takes effect`, add, insert, strike, strike-and-insert, replace, redesignate, repeal, and amended-section targets. Assert that text marked as removed or insertion payload does not also produce a modality claim.

- [ ] **Step 3: Run the focused tests and observe missing-category failures**

```bash
rtk .venv/bin/pytest apps/legislation/tests/test_legal_rules.py -q
```

Expected: the new funding, timeline, and amendment tests fail while Task 3 tests remain green.

- [ ] **Step 4: Implement deterministic money and fiscal-year normalization**

Use `Decimal`, never `float`. Recognize numeric suffixes `thousand`, `million`, and `billion` with multipliers, quantize to `Decimal("0.01")`, and render with `format(amount, ".2f")`. Do not infer currency for an amount without `$` or explicit `dollars`.

- [ ] **Step 5: Implement deterministic timeline normalization**

Map English month names with a constant dictionary and construct `datetime.date`; invalid calendar dates do not emit claims. Relative deadlines store the integer, singular unit enum, and literal trigger. Do not convert months or years to days.

- [ ] **Step 6: Implement amendment operation precedence**

Run amendment recognition before modality recognition and record the exact payload ranges it consumes. `strike_and_insert` must be one operation, not separate `strike` and `insert` claims. Use enum values `add`, `insert`, `strike`, `strike_and_insert`, `replace`, `redesignate`, `repeal`, and `amend`.

- [ ] **Step 7: Run all extraction unit tests**

```bash
rtk .venv/bin/pytest apps/legislation/tests/test_federal_structure.py apps/legislation/tests/test_legal_rules.py -q
```

Expected: all parser and rule tests pass.

- [ ] **Step 8: Commit the remaining rule families**

```bash
rtk git add legislation-tracker-backend/apps/legislation/extraction/legal_rules.py legislation-tracker-backend/apps/legislation/tests/test_legal_rules.py
rtk git commit -m "feat(contract): extract funding timelines and amendments"
```

---

### Task 5: Render v2 contracts and select safe legacy fallback

**Files:**
- Create: `legislation-tracker-backend/apps/legislation/extraction/renderer.py`
- Create: `legislation-tracker-backend/apps/legislation/extraction/legacy.py`
- Create: `legislation-tracker-backend/apps/legislation/extraction/service.py`
- Modify: `legislation-tracker-backend/apps/legislation/extraction/__init__.py`
- Modify: `legislation-tracker-backend/apps/legislation/tasks.py:231-423`
- Test: `legislation-tracker-backend/apps/legislation/tests/test_contract_renderer.py`
- Test: `legislation-tracker-backend/apps/legislation/tests/test_extraction_service.py`

**Interfaces:**
- Consumes: schema/types from Task 1, parser from Task 2, and claims from Tasks 3-4.
- Produces: `render_contract(*, title: str, version_label: str, sections: Sequence[StructuralSection], claims: Sequence[ExtractedClaim], source_text: str) -> ExtractionResult`.
- Produces: `build_legacy_document_contract(document: BillDocument, bill: Bill) -> ExtractionResult` and `build_legacy_metadata_contract(bill: Bill) -> dict[str, object]`.
- Produces: `extract_contract(*, document: BillDocument, bill: Bill) -> ExtractionResult`.

- [ ] **Step 1: Write failing renderer tests**

Assert stable source ordering, exact controlled sentences, category arrays, key-provision selection, three-sentence summary priority, category cap warnings, exact evidence field paths, and deterministic output for repeated invocation.

Use these modality templates exactly:

```text
required: “{actor} is required to {action}.”
prohibited: “{actor} is prohibited from {action}.”
permitted: “{actor} is authorized to {action}.”
```

Funding, timeline, definition, applicability, and amendment templates must use only extracted fields and omit missing optional clauses without substituting guessed text.

- [ ] **Step 2: Write failing service-selection tests**

Cover successful federal v2, state fallback, missing text fallback, unrecognized structure fallback, no supported claims fallback, schema failure fallback, evidence failure fallback, and propagation of an unexpected `RuntimeError` from a rule function.

- [ ] **Step 3: Run the new tests and observe missing modules**

```bash
rtk .venv/bin/pytest apps/legislation/tests/test_contract_renderer.py apps/legislation/tests/test_extraction_service.py -q
```

Expected: import failures for renderer/service/legacy.

- [ ] **Step 4: Move the current extractor unchanged into `legacy.py`**

Move `_source_text`, `_sentence_spans`, `_is_heading`, `_first_meaningful_sentence`, `_matches_any`, `_matching_sentences`, `_contract_item`, `_add_evidence`, `_build_contract`, and `_build_metadata_contract` out of `tasks.py`. Preserve output keys, keyword sets, five-item limits, evidence behavior, and `1.1-deterministic` hashes. Wrap the document result in `ExtractionResult(method="legacy-deterministic")`.

- [ ] **Step 5: Implement controlled rendering, caps, and evidence paths**

Deduplicate using `(category, canonicalized fields, evidence start/end pairs)`, sort by first evidence start and category order, and cap after sorting. Create a `key_provisions` entry from the first ten primary claims while retaining up to 100 items in each category. Attach the originating evidence to every category display path and every derived key-provision path. Attach each summary claim's evidence to `plain_summary`.

- [ ] **Step 6: Implement federal-v2 selection and expected fallback**

Only catch `ExpectedExtractionRejection` and `ContractValidationError`. Map validation errors to the approved schema/evidence reason, log the reason in the caller, and return an unchanged legacy result with `fallback_reason`. Do not catch `Exception`.

- [ ] **Step 7: Run renderer, service, legacy task, and schema tests**

```bash
rtk .venv/bin/pytest apps/legislation/tests/test_contract_renderer.py apps/legislation/tests/test_extraction_service.py apps/legislation/tests/test_extraction_schema.py apps/legislation/tests/test_tasks.py -q
```

Expected: renderer/service tests pass and existing task tests prove legacy behavior was preserved before task integration changes.

- [ ] **Step 8: Commit rendering and fallback**

```bash
rtk git add legislation-tracker-backend/apps/legislation/extraction legislation-tracker-backend/apps/legislation/tasks.py legislation-tracker-backend/apps/legislation/tests/test_contract_renderer.py legislation-tracker-backend/apps/legislation/tests/test_extraction_service.py legislation-tracker-backend/apps/legislation/tests/test_tasks.py
rtk git commit -m "feat(contract): render legal NLP contracts with fallback"
```

---

### Task 6: Add the extraction evaluation corpus and release gate

**Files:**
- Create: `legislation-tracker-backend/apps/legislation/tests/fixtures/legal_nlp/*.json`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_extraction_evaluation.py`

**Interfaces:**
- Consumes: `extract_contract()` and the normalized claim schema.
- Produces: `claim_key(category: str, fields: Mapping[str, object]) -> tuple[object, ...]` for exact evaluation matching.
- Produces: aggregate `precision`, `recall`, schema validity, evidence validity, and negative-amendment false-positive assertions as pytest release gates.

- [ ] **Step 1: Define and test the fixture loader and scorer**

Each JSON fixture contains `name`, `title`, `version_label`, `source_text`, `expected_claims`, and `forbidden_claims`. Expected/forbidden claims contain `category`, normalized `fields`, and one or more literal evidence quotations. The loader computes offsets with occurrence indices and fails when a quote is absent or ambiguous without an occurrence index.

Define category core fields exactly:

```python
CORE_FIELDS = {
    "requirements": ("modality", "actor", "action", "object", "conditions"),
    "funding_items": ("amount", "amount_type", "currency", "fiscal_years", "purpose"),
    "timeline_items": ("timeline_type", "date", "relative_value", "relative_unit", "trigger"),
    "definitions": ("term", "definition", "definition_type"),
    "applicability": ("subject", "scope", "applicability_type"),
    "amendment_operations": ("target", "operation", "removed_text", "inserted_text"),
}
```

- [ ] **Step 2: Run the empty-corpus test and confirm it fails**

```bash
rtk .venv/bin/pytest apps/legislation/tests/test_extraction_evaluation.py -q
```

Expected: FAIL because fewer than 25 fixtures are present.

- [ ] **Step 3: Add the required corpus cases**

Create at least these named cases, using public-domain federal bill excerpts and recording the Congress.gov source citation in each fixture's `source_reference` field:

```text
required_shall, required_must, required_is_required,
prohibited_may_not, prohibited_shall_not, permitted_may,
funding_appropriation, funding_authorization, funding_such_sums,
timeline_explicit_date, timeline_relative_days, timeline_effective,
definition_means, definition_includes, definition_section,
applicability_applies, eligibility_entity, applicability_exclusion,
amend_add, amend_insert, amend_strike_insert, amend_repeal, amend_redesignate,
negative_quoted_modal, negative_table_of_contents, negative_removed_modal,
repeated_sentence_offsets, unicode_punctuation, trailing_sentence_no_punctuation
```

Every supported category must have at least three positive claims across the corpus. The five negative/amendment cases required by the spec may overlap only when each has an explicit forbidden-claim assertion.

- [ ] **Step 4: Implement and enforce the quality calculations**

Count exact core-field matches as true positives, unexpected emitted keys as false positives, and missing expected keys as false negatives. Assert:

```python
assert every_contract_valid
assert every_evidence_span_exact
assert aggregate_precision >= 0.95
assert aggregate_recall >= 0.70
assert forbidden_false_positive_count == 0
```

Print per-category counts in an assertion message so regressions are diagnosable.

- [ ] **Step 5: Run the evaluation and all extraction tests**

```bash
rtk .venv/bin/pytest apps/legislation/tests/test_extraction_evaluation.py apps/legislation/tests/test_federal_structure.py apps/legislation/tests/test_legal_rules.py apps/legislation/tests/test_contract_renderer.py apps/legislation/tests/test_extraction_service.py -q
```

Expected: all gates pass.

- [ ] **Step 6: Commit the corpus and gates**

```bash
rtk git add legislation-tracker-backend/apps/legislation/tests/fixtures/legal_nlp legislation-tracker-backend/apps/legislation/tests/test_extraction_evaluation.py
rtk git commit -m "test(contract): add federal extraction quality corpus"
```

---

### Task 7: Wire v2 extraction into durable contract generation

**Files:**
- Modify: `legislation-tracker-backend/apps/legislation/tasks.py:1-585`
- Modify: `legislation-tracker-backend/apps/legislation/tests/test_tasks.py:1-225`
- Modify: `legislation-tracker-backend/apps/legislation/tests/test_public_api.py:108-285`
- Modify: `legislation-tracker-backend/apps/ingestion/tests/test_tasks.py:260-300`

**Interfaces:**
- Consumes: `extract_contract()`, `build_legacy_metadata_contract()`, `EXTRACTOR_VERSION`, and `ExtractionResult`.
- Preserves: `generate_contract`, `_generate_contract_impl`, `generate_contract_for_bill`, and durable work kind names.
- Changes: document work dedupe key to `<document_id>:<content_hash-or-pending>:federal-rules-2.0.0`.

- [ ] **Step 1: Add failing task-level v2 and dedupe tests**

Add tests proving:

- A supported federal document persists `schema_version == "2.0-legal-nlp"` on both the model and JSON.
- Every persisted evidence row exactly matches `extracted_text`.
- An inactive v2 document does not replace `Bill.latest_contract`.
- Re-running unchanged extraction reuses the same contract and does not duplicate `ChangeLog` or evidence.
- Metadata-only generation remains `1.1-deterministic`.
- `enqueue_document_contract()` includes `federal-rules-2.0.0`, producing a distinct durable item from the prior legacy dedupe key.
- Unexpected extraction errors propagate to the durable worker and are retryable.

- [ ] **Step 2: Run focused task tests and confirm v2 assertions fail**

```bash
rtk .venv/bin/pytest apps/legislation/tests/test_tasks.py apps/ingestion/tests/test_tasks.py -q
```

Expected: v2 schema and extractor-version dedupe assertions fail against the old task wiring.

- [ ] **Step 3: Replace task-local extraction with `ExtractionResult`**

In `_generate_contract_impl`, call `extract_contract(document=document, bill=bill)` before opening the transaction. Use `result.contract_json`, `result.schema_version`, and `result.evidence`. Persist `result.schema_version`; do not use one global schema constant for both document and metadata contracts.

Keep hash skip, active-version selection, `ChangeLog`, `contract_generated_at`, and topic enqueue semantics unchanged.

- [ ] **Step 4: Version durable document work**

Build the dedupe key with `EXTRACTOR_VERSION`. Do not change `source_updated_at`, the unique constraint, work kinds, payload shape, dispatcher, or replay API.

- [ ] **Step 5: Add one structured extraction log event**

Measure extraction with `time.monotonic()`. Log `document_id`, `bill_id`, schema, method, parser version, category counts, sections seen/with claims, warning codes, fallback reason, and integer duration milliseconds using `logger.info(..., extra={...})`. Do not log source text or quotations.

- [ ] **Step 6: Add mixed v1/v2 public API tests**

Create one bill with v1 history and a selected v2 latest contract. Assert `/api/bills/{id}/` and `/api/contracts/?bill={id}` serialize both versions and evidence unchanged, with model and v2 JSON schema versions equal.

- [ ] **Step 7: Run legislation and ingestion integration tests**

```bash
rtk .venv/bin/pytest apps/legislation/tests/test_tasks.py apps/legislation/tests/test_public_api.py apps/ingestion/tests/test_tasks.py apps/ingestion/tests/test_views.py -q
```

Expected: all integration tests pass.

- [ ] **Step 8: Commit durable integration**

```bash
rtk git add legislation-tracker-backend/apps/legislation/tasks.py legislation-tracker-backend/apps/legislation/tests/test_tasks.py legislation-tracker-backend/apps/legislation/tests/test_public_api.py legislation-tracker-backend/apps/ingestion/tests/test_tasks.py
rtk git commit -m "feat(contract): generate v2 contracts through durable work"
```

---

### Task 8: Add the preview-first bounded contract backfill

**Files:**
- Create: `legislation-tracker-backend/apps/legislation/management/commands/backfill_contracts.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_backfill_contracts_command.py`

**Interfaces:**
- Consumes: `BillDocument` and `enqueue_document_contract(document)`.
- Produces: `python manage.py backfill_contracts [selectors] [--all-versions] [--execute]`.
- Does not call `generate_contract()` synchronously.

- [ ] **Step 1: Write failing command validation and preview tests**

Cover no selector, invalid ID range, non-positive limit, default active-only selection, `--all-versions`, session filtering through `bill__session`, inclusive ID bounds, deterministic ID ordering before limit, preview output, and the absence of `IngestionWorkItem` rows without `--execute`.

- [ ] **Step 2: Write failing execution and idempotency tests**

Patch the broker wake-up to prove work is persisted first. Run `--execute` twice for the same extractor version and assert only one durable item per document. Assert output reports selected and enqueued counts separately.

- [ ] **Step 3: Run the command tests and observe the unknown-command failure**

```bash
rtk .venv/bin/pytest apps/legislation/tests/test_backfill_contracts_command.py -q
```

Expected: FAIL with `Unknown command: 'backfill_contracts'`.

- [ ] **Step 4: Implement argument validation and queryset construction**

Require at least one of `--session`, `--start-id`, `--end-id`, or `--limit`. Validate `start_id <= end_id` and `limit > 0`. Begin with `BillDocument.objects.select_related("bill").order_by("id")`; filter active versions unless `--all-versions` is set, apply selectors, then slice for limit.

- [ ] **Step 5: Implement preview and durable execution**

Print selected count, minimum/maximum ID, session counts, and active/inactive counts. Without `--execute`, print `Preview only; pass --execute to enqueue.` and return. With it, call `enqueue_document_contract()` for each selected document and print the number of newly created-or-existing durable items as `enqueued` without publishing extraction directly.

- [ ] **Step 6: Run command and task tests**

```bash
rtk .venv/bin/pytest apps/legislation/tests/test_backfill_contracts_command.py apps/legislation/tests/test_tasks.py -q
```

Expected: all focused tests pass.

- [ ] **Step 7: Commit the backfill command**

```bash
rtk git add legislation-tracker-backend/apps/legislation/management/commands/backfill_contracts.py legislation-tracker-backend/apps/legislation/tests/test_backfill_contracts_command.py
rtk git commit -m "feat(contract): add controlled v2 contract backfill"
```

---

### Task 9: Add versioned frontend contract types and guards

**Files:**
- Create: `legislation-tracker-client/lib/contracts.ts`
- Create: `legislation-tracker-client/tests/contracts.test.ts`

**Interfaces:**
- Produces: `EvidenceSpanItem`, `LegacyContractJson`, `LegalNlpV2ContractJson`, all v2 item interfaces, and `ContractJson`.
- Produces: `isLegalNlpV2Contract(schemaVersion: string, value: unknown) -> value is LegalNlpV2ContractJson`.
- Produces: `getContractSummary(value: unknown) -> string | null`.
- Produces: `groupEvidenceByFieldPath(spans: readonly EvidenceSpanItem[]) -> ReadonlyMap<string, readonly EvidenceSpanItem[]>`.

- [ ] **Step 1: Read the installed Next.js client-component guide**

```bash
rtk sed -n '1,260p' node_modules/next/dist/docs/01-app/01-getting-started/05-server-and-client-components.md
```

Expected: confirms that interactive evidence controls may remain under the existing client-component page boundary.

- [ ] **Step 2: Write failing type-guard and helper tests**

Use `node:test` and `node:assert/strict` because `tests/*.test.ts` runs through `test:api`. Test one complete v2 object, wrong schema version, missing array, malformed extraction metadata, invalid item, valid legacy summary, non-object payload, non-string summary, and evidence grouping with multiple spans for the same path.

- [ ] **Step 3: Run the Node tests and observe the missing module**

```bash
rtk pnpm run test:api
```

Expected: FAIL because `lib/contracts.ts` is missing or exports are undefined.

- [ ] **Step 4: Implement the versioned interfaces and runtime guard**

Model every field defined by `contract_v2.json`. The guard must check the literal schema version, required strings, extraction number/string arrays, and that every category is an array. It may validate item objects shallowly because the backend schema is authoritative, but it must reject missing arrays and non-object entries so rendering cannot throw.

Use safe helpers:

```typescript
export function getContractSummary(value: unknown): string | null {
  if (!isRecord(value)) return null;
  return typeof value.plain_summary === "string" ? value.plain_summary : null;
}
```

- [ ] **Step 5: Run tests and typecheck**

```bash
rtk pnpm test
rtk pnpm typecheck
```

Expected: all existing tests, new helper tests, and typecheck pass. `BillContractItem.contract_json` remains unchanged until Task 10, so this task has an independently green commit.

- [ ] **Step 6: Commit the type boundary**

```bash
rtk git add legislation-tracker-client/lib/contracts.ts legislation-tracker-client/tests/contracts.test.ts
rtk git commit -m "feat(client): type versioned bill contracts"
```

---

### Task 10: Render structured v2 contracts and per-claim evidence

**Files:**
- Create: `legislation-tracker-client/app/bills/[id]/contract-section.tsx`
- Modify: `legislation-tracker-client/lib/api.ts:200-235`
- Modify: `legislation-tracker-client/app/bills/[id]/page.tsx:1-87,139-165,560-571`
- Create: `legislation-tracker-client/tests/components/contract-section.test.tsx`
- Modify: `legislation-tracker-client/tests/components/bill-detail-page.test.tsx`

**Interfaces:**
- Consumes: `BillContractItem`, `isLegalNlpV2Contract()`, `getContractSummary()`, and `groupEvidenceByFieldPath()`.
- Produces: `ContractSection({ contract }: { contract: BillContractItem })`.
- Changes: `BillContractItem.contract_json` from `Record<string, unknown>` to `ContractJson`.
- Preserves: the legacy plain summary/source excerpt/evidence renderer and history pagination.

- [ ] **Step 1: Write failing component tests for v2 behavior**

Render a complete v2 contract with two evidence rows for one requirement. Assert headings for overview, key provisions, requirements, funding, timelines, definitions, applicability, amendments, and limitations; section labels; controlled text; one accessible `Source evidence for <section title> item <n>` disclosure; and both supporting quotations after expansion.

Also assert:

- Empty categories do not render headings.
- A known `item_limit_reached:requirements` warning uses friendly copy.
- An unknown warning uses generic copy and does not expose its raw value.
- A malformed v2 payload falls back to the safe legacy renderer without throwing.
- A v1 contract retains its existing summary, source excerpt, and evidence list.

- [ ] **Step 2: Run the component test and observe the missing component**

```bash
rtk pnpm exec vitest run tests/components/contract-section.test.tsx
```

Expected: FAIL because `contract-section.tsx` does not exist.

- [ ] **Step 3: Extract the legacy component from the page**

Move the current `ContractSection` markup into the new file as `LegacyContractSection`. Keep class names and copy unchanged so current tests remain meaningful. Export only the schema-selecting `ContractSection`.

- [ ] **Step 4: Implement the v2 renderer**

Create small local render helpers for labeled category lists and evidence disclosures. Group evidence once with `useMemo` or a pure helper; do not scan the entire evidence array repeatedly inside every item. Render only non-empty arrays and use stable keys composed from field path plus item index.

Translate warning codes with an explicit map:

```typescript
const WARNING_COPY: Record<string, string> = {
  "item_limit_reached:requirements":
    "Only the first 100 extracted requirements are shown.",
  "item_limit_reached:funding_items":
    "Only the first 100 extracted funding items are shown.",
};
```

All other warnings render `Some provisions could not be represented in this automated summary.` exactly once.

- [ ] **Step 5: Update page integration and history summary reads**

Import `ContractJson` and `EvidenceSpanItem` from `lib/contracts.ts`, remove the duplicate API-local evidence interface, change the API field to `contract_json: ContractJson`, import `ContractSection`, and remove the inline implementation. Replace direct history access with `getContractSummary(contract.contract_json)`. Do not change bill fetching, tracking, vote selection, history pagination, or document links.

- [ ] **Step 6: Run component tests, all frontend tests, typecheck, and lint**

```bash
rtk pnpm test
rtk pnpm typecheck
rtk pnpm lint
```

Expected: all commands pass with no unsafe `contract_json` property reads.

- [ ] **Step 7: Commit the typed structured UI**

```bash
rtk git add legislation-tracker-client/lib/contracts.ts legislation-tracker-client/lib/api.ts 'legislation-tracker-client/app/bills/[id]/contract-section.tsx' 'legislation-tracker-client/app/bills/[id]/page.tsx' legislation-tracker-client/tests/contracts.test.ts legislation-tracker-client/tests/components/contract-section.test.tsx legislation-tracker-client/tests/components/bill-detail-page.test.tsx
rtk git commit -m "feat(client): render structured bill contracts"
```

---

### Task 11: Add live E2E coverage, update documentation, and verify the feature

**Files:**
- Modify: `legislation-tracker-backend/scripts/start-e2e-api.sh`
- Create: `legislation-tracker-client/e2e/contract-detail.spec.ts`
- Modify: `legislation-tracker-backend/docs/PHASE_5_CONTRACT.md`
- Modify: `legislation-tracker-backend/docs/PHASE_5_3_PLAN.md`
- Modify: `legislation-tracker-backend/apps/legislation/README.md`

**Interfaces:**
- Produces: one disposable E2E bill with a valid v2 contract and exact evidence.
- Produces: a browser flow through the real Django bill-detail API and Next.js page.
- Documents: implemented scope, fallback, validation, backfill, and deferred model integrations.

- [ ] **Step 1: Write the failing Playwright scenario**

Add a test that queries the live API for the seeded `HR E2E` bill, opens `/bills/{id}`, verifies the structured summary, requirement, funding, and deadline sections, expands source evidence, and sees the exact quote.

Core flow:

```typescript
const response = await request.get(
  `${API_BASE}/api/bills/?bill_number=${encodeURIComponent("HR E2E")}`,
);
expect(response.status()).toBe(200);
const body = await response.json();
const bill = body.results[0];
await page.goto(`/bills/${bill.id}`);
await expect(page.getByRole("heading", { name: "Plain-language overview" })).toBeVisible();
await page.getByRole("button", { name: /Source evidence for Requirements item 1/ }).click();
await expect(page.getByText(/shall award grants to rural hospitals/)).toBeVisible();
```

- [ ] **Step 2: Run the E2E test and confirm the missing-seed failure**

```bash
rtk pnpm exec playwright test e2e/contract-detail.spec.ts
```

Expected: FAIL because the disposable API has no `HR E2E` bill.

- [ ] **Step 3: Seed one valid v2 contract in the disposable E2E API**

Extend the existing `manage.py shell -c` block in `start-e2e-api.sh`. Create one federal bill and active document with the exact source below, call `extract_contract(document=document, bill=bill)`, assert `result.schema_version == "2.0-legal-nlp"`, and create the `BillContract` and `EvidenceSpan` rows from that result using `contract_hash_from_dict()`. Set `bill.latest_contract` and `processing_status` directly. This exercises real extraction and validation while avoiding a broker publish during E2E database setup.

Use source text containing these exact supported claims:

```text
SEC. 2. RURAL HOSPITAL GRANTS.
The Secretary of Health and Human Services shall award grants to rural hospitals.
There is authorized to be appropriated $25,000,000 for fiscal year 2027.
This Act takes effect 90 days after enactment.
```

- [ ] **Step 4: Run the focused E2E test**

```bash
rtk pnpm exec playwright test e2e/contract-detail.spec.ts
```

Expected: one Chromium test passes against the live disposable Django API.

- [ ] **Step 5: Update Phase 5 documentation**

Document `2.0-legal-nlp`, the module boundaries, exact evidence validation, federal-only fallback, extractor-version durable dedupe, preview-first `backfill_contracts`, and the evaluation gates. Add a superseded banner to `PHASE_5_3_PLAN.md` linking to the approved spec and state that LLM/provider work is deferred and unimplemented.

- [ ] **Step 6: Run the complete backend verification**

From `legislation-tracker-backend`:

```bash
rtk .venv/bin/python manage.py check
rtk .venv/bin/pytest -q
```

Expected: Django check reports no issues and the complete backend suite passes.

- [ ] **Step 7: Run the complete frontend and E2E verification**

From `legislation-tracker-client`:

```bash
rtk pnpm test
rtk pnpm typecheck
rtk pnpm lint
rtk pnpm exec next build --webpack
rtk pnpm test:e2e
```

Expected: Vitest and Node tests pass, typecheck and lint exit zero, the webpack production build succeeds, and all Playwright tests pass.

- [ ] **Step 8: Run extension regression tests**

From `legislation-tracker-extension`:

```bash
rtk run "node --test tests/*.test.js"
```

Expected: all extension tests pass.

- [ ] **Step 9: Review the aggregate diff and commit final coverage/docs**

```bash
rtk git diff --check
rtk git status --short
rtk git add legislation-tracker-backend/scripts/start-e2e-api.sh legislation-tracker-client/e2e/contract-detail.spec.ts legislation-tracker-backend/docs/PHASE_5_CONTRACT.md legislation-tracker-backend/docs/PHASE_5_3_PLAN.md legislation-tracker-backend/apps/legislation/README.md
rtk git commit -m "test(contract): verify legal NLP flow end to end"
```

Expected: the commit succeeds and `rtk git status --short` is empty.

---

## Completion Checklist

- [ ] Every task's focused tests were observed failing before implementation and passing afterward.
- [ ] No LLM, external NLP service, model package, API key, or extraction-time network code was added.
- [ ] No database migration or API endpoint was added.
- [ ] Federal v2, every expected fallback reason, and unexpected-error propagation are tested.
- [ ] All customer-visible v2 claims have exact, validated evidence.
- [ ] Evaluation gates meet 100% schema/evidence validity, 95% aggregate precision, 70% aggregate recall, and zero forbidden false positives.
- [ ] Mixed v1/v2 API history and legacy client rendering pass.
- [ ] Backfill remains preview-first, bounded, durable, and idempotent by extractor version.
- [ ] Full backend, frontend, build, E2E, and extension validation passes.
- [ ] Documentation accurately distinguishes implemented deterministic extraction from deferred model-based work.
