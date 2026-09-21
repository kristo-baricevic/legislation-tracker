import json
from pathlib import Path
from types import SimpleNamespace

from django.test import override_settings

from apps.legislation.extraction.service import extract_contract

FIXTURE = Path(__file__).parent / "fixtures/reader_evals/hr9300.json"


def extract_fixture():
    case = json.loads(FIXTURE.read_text())
    with override_settings(LEGAL_NLP_V21_WRITE_ENABLED=True):
        result = extract_contract(
            bill=SimpleNamespace(jurisdiction="federal", title=case["title"]),
            document=SimpleNamespace(
                extracted_text=case["text"], version_label="Introduced in House"
            ),
        )
    assert result.schema_version == "2.1-legal-nlp", result.fallback_reason
    return case, result


def test_reader_preserves_funding_units_qualifiers_bases_and_purposes():
    _, result = extract_fixture()
    money = result.contract_json["financial_items"]
    assert len(money) == 4
    assert "at least 20 percent" in money[1]["display_text"]
    assert "not reserved under section 4" in money[1]["display_text"]
    assert "5 percent" in money[2]["display_text"]
    assert "reporting" in money[2]["purpose"]
    assert "subsection (d)" in money[2]["display_text"]
    assert "2 percent" in money[3]["display_text"]
    assert money[0]["purpose"].startswith("grants to")


def test_reader_extracts_unquoted_definitions_purpose_and_nested_activities():
    case, result = extract_fixture()
    contract = result.contract_json
    assert "high-need students" in (contract["orientation"]["purpose_clause"] or "")
    definitions = {
        item["term"].lower(): item["definition"] for item in contract["definitions"]
    }
    assert "military-connected" in definitions["high-need student"]
    assert "Tribal College" in definitions["eligible indian entity"]
    text = "\n".join(item["display_text"] for item in contract["line_items"])
    assert "recruit and retain faculty" in text
    assert "emergency financial assistance" in text
    assert "Allows Providing" not in text
    assert "to include the following." not in text
    assert "organizations to." not in text
    for evidence in result.evidence:
        assert (
            case["text"][evidence.start_char : evidence.end_char]
            == evidence.quoted_text
        )


def test_eval_catches_money_mutation_and_missing_fact():
    from apps.legislation.evaluation.reader_quality import score_reader

    case = {
        "required_facts": [
            {
                "id": "floor",
                "category": "financial",
                "patterns": [r"at least 20 percent", "tribal"],
            }
        ],
        "expected_financial_count": 1,
    }
    good = [
        {
            "category": "financial",
            "text": "Sets aside at least 20 percent after tribal funding.",
        }
    ]
    assert score_reader(case, good)["passed"]
    wrong = [
        {"category": "financial", "text": "Sets aside 20 percent after tribal funding."}
    ]
    report = score_reader(case, wrong)
    assert not report["passed"]
    assert report["missing_facts"] == ["floor"]
    assert not score_reader(case, [])["passed"]


def test_eval_rejects_fragments_and_duplicate_output():
    from apps.legislation.evaluation.reader_quality import score_reader

    report = score_reader({}, [{"text": "Requires the Secretary to."}] * 2)
    assert not report["passed"]
    assert report["metrics"]["fragment_count"] == 2
    assert report["metrics"]["duplicate_count"] == 1


def test_offline_command_runs_real_extractor_and_fails_bad_replay(tmp_path):
    import pytest
    from django.core.management import call_command
    from django.core.management.base import CommandError

    report = tmp_path / "report.json"
    call_command("evaluate_reader_quality", "--case", "hr9300-119-ih", output=str(report))
    artifact = json.loads(report.read_text())
    assert artifact["results"][0]["quality"]["passed"]
    assert artifact["results"][0]["quality"]["metrics"]["required_fact_recall"] == 1
    replay = tmp_path / "replay.json"
    replay.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "case_id": "hr9300-119-ih",
                        "output": {
                            "overview": [
                                {"text": "Does stuff.", "source_refs": ["src_missing"]}
                            ]
                        },
                        "source_snapshot": [],
                    }
                ]
            }
        )
    )
    with pytest.raises(CommandError, match="failed"):
        call_command("evaluate_reader_quality", "--case", "hr9300-119-ih", replay=str(replay), output=str(report))
    assert not json.loads(report.read_text())["results"][0]["quality"]["passed"]


def test_eval_cost_unknown_is_not_zero_and_citation_existence_is_not_entailment():
    from apps.legislation.evaluation.reader_quality import score_reader

    report = score_reader(
        {},
        [{"text": "Funding is $99 million.", "source_refs": ["src_0001"]}],
        sources=[{"source_ref": "src_0001", "quoted_text": "No funding."}],
    )
    assert report["metrics"]["estimated_cost_usd"] is None
    assert "semantic support of each claim" in report["human_review_required"]


def test_list_context_does_not_invent_grants_or_reclassify_quoted_law():
    from apps.legislation.extraction.federal_structure import parse_federal_structure
    from apps.legislation.extraction.reader_context import enrich_reader_claims

    source = "SEC. 2. Reports\nThe Secretary shall publish a report that may include the following:\n(1) Research results.\nSEC. 3. Amendment\n[[QUOTED_BLOCK_START]]\n(a) Definitions.—The term visitor means a guest.\n(b) Rules.—The Director shall include the following:\n(1) New requirements.\n[[QUOTED_BLOCK_END]]"
    claims = enrich_reader_claims(source, parse_federal_structure(source), ())
    assert claims
    assert not any("grant" in str(c.fields) for c in claims)
    assert not any(
        "visitor" in str(c.fields) or "New requirements" in str(c.fields)
        for c in claims
    )


def test_structure_keeps_lettered_subsections_after_nested_roman_clauses():
    from apps.legislation.extraction.federal_structure import parse_federal_structure

    source = "SEC. 1. Rules\n(c) Prior.—Text.\n(1) List.—Text.\n(A) Sublist.—Text.\n(i) First.—Text.\n(ii) Second.—Text.\n(d) Next.—Text.\nSEC. 2. Other\n(i) Standalone.—Text."
    sections = parse_federal_structure(source)
    assert next(s for s in sections if s.label == "(d)").level == "subsection"
    assert sections[-1].level == "subsection"


def test_eval_flags_document_absence_claims_when_source_is_truncated():
    from apps.legislation.evaluation.reader_quality import score_reader

    report = score_reader(
        {"truncated": True}, [{"text": "The bill contains no funding."}]
    )
    assert not report["passed"]
    assert "unsupported_absence_claim" in report["failures"]
    assert score_reader(
        {"truncated": True},
        [
            {
                "text": "The supplied provisions give percentages rather than a dollar total."
            }
        ],
    )["passed"]


def test_readability_release_gate_cannot_be_bypassed_by_fact_coverage(tmp_path):
    import pytest
    from django.core.management import call_command
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="failed"):
        call_command(
            "evaluate_reader_quality",
            cases=["hr9300-119-ih"],
            max_item_words=1,
            output=str(tmp_path / "report.json"),
        )
    row = json.loads((tmp_path / "report.json").read_text())["results"][0]
    assert "readability_word_limit" in row["quality"]["failures"]
