import pytest

from apps.legislation.evaluation.whole_bill import assess, load_cases


def test_three_pinned_cases_have_complete_draft_inventories():
    cases = load_cases()
    assert len(cases) == 3
    student = next(c for c in cases if c["id"] == "BILLS-119hr9300ih")
    assert len(student["expectations"]) == 18
    assert sum(e["financial"] for e in student["expectations"]) == 9
    assert all(c["text"] and c["text_sha256"] for c in cases)
    assert all(e["source_reference"] for c in cases for e in c["expectations"])


def test_word_matches_cannot_award_semantic_pass():
    case = load_cases()[0]
    items = [{"text": case["expectations"][0]["answer"], "evidence_valid": True}]
    result = assess(case, items, pipeline="nlp")
    assert result["release_gate"] == "blocked"
    assert result["dimensions"]["coverage"]["status"] == "needs_human_review"
    assert result["dimensions"]["accuracy"]["status"] == "needs_human_review"
    assert (
        result["dimensions"]["source_support"]["semantic_status"]
        == "needs_human_review"
    )
    assert all(row["verdict"] == "unreviewed" for row in result["review_rows"])


def test_missing_output_and_invalid_evidence_cannot_pass():
    case = load_cases()[0]
    assert assess(case, [], pipeline="ai")["release_gate"] == "blocked"
    result = assess(
        case, [{"text": "A claim", "evidence_valid": False}], pipeline="nlp"
    )
    assert result["mechanical_failures"] == ["invalid_or_missing_evidence:0"]
    assert result["release_gate"] == "fail"


def test_source_drift_is_rejected(tmp_path):
    import shutil

    from apps.legislation.evaluation.whole_bill import ROOT

    shutil.copytree(ROOT, tmp_path / "benchmark")
    source = tmp_path / "benchmark/sources/BILLS-119hr9300ih.txt"
    source.write_text(source.read_text() + " changed")
    with pytest.raises(ValueError, match="Decoded source drift"):
        load_cases(tmp_path / "benchmark")


def test_replay_rejects_wrong_version_or_evidence_span():
    from apps.legislation.evaluation.whole_bill import replay_items

    case = load_cases()[0]
    with pytest.raises(ValueError, match="exact pinned"):
        replay_items(case, {"case_id": case["id"], "source_text_sha256": "wrong"})
    with pytest.raises(ValueError, match="exact span"):
        replay_items(
            case,
            {
                "case_id": case["id"],
                "source_text_sha256": case["text_sha256"],
                "status": "succeeded",
                "source_snapshot": [
                    {"quoted_text": "invented", "start_char": 0, "end_char": 8}
                ],
            },
        )


def test_command_writes_both_pipelines_but_blocks_unreviewed_gate(tmp_path):
    import json

    from django.core.management import call_command
    from django.core.management.base import CommandError

    output = tmp_path / "report.json"
    with pytest.raises(CommandError, match="gate blocked"):
        call_command(
            "evaluate_reader_quality",
            suite="whole-bill",
            cases=["BILLS-119hr9300ih"],
            output=str(output),
        )
    report = json.loads(output.read_text())
    assert report["provider_calls"] == 0
    assert report["results"][0]["pipelines"]["nlp"]["status"] == "evaluated"
    assert report["results"][0]["pipelines"]["ai"]["status"] == "not_run"
    assert output.with_suffix(".md").exists()
    packet = report["results"][0]["current_source_packet"]
    assert packet["coverage"]["complete_document"] is True
    assert packet["provider_calls"] == 0
    assert packet["sources"]


def test_command_rejects_colliding_report_paths(tmp_path):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="must end in .json"):
        call_command(
            "evaluate_reader_quality",
            suite="whole-bill",
            output=str(tmp_path / "report.md"),
        )
    assert not list(tmp_path.iterdir())


def test_valid_ai_replay_checks_linkage_not_semantic_accuracy():
    from apps.legislation.evaluation.whole_bill import digest, replay_items

    case = load_cases()[0]
    quote = case["text"][:100]
    source = {
        "source_ref": "src_0001",
        "quoted_text": quote,
        "start_char": 0,
        "end_char": 100,
        "text_sha256": digest(quote),
    }
    output = {
        "schema_version": "1.2",
        "overview": [
            {
                "text": "A claim requiring human verification.",
                "source_refs": ["src_0001"],
                "source_quotes": [{"source_ref": "src_0001", "quote": quote}],
            }
        ],
        "key_impacts": [],
        "obligations": [],
        "funding_and_timing": [],
        "uncertain_language": [],
    }
    items = replay_items(
        case,
        {
            "case_id": case["id"],
            "source_text_sha256": case["text_sha256"],
            "status": "succeeded",
            "source_snapshot": [source],
            "output": output,
        },
    )
    assert len(items) == 1
    result = assess(case, items, pipeline="ai")
    assert result["mechanical_failures"] == []
    assert result["release_gate"] == "blocked"


def test_saved_invalid_output_can_be_resolved_offline_with_audit():
    from apps.legislation.evaluation.whole_bill import digest, replay_items

    from .test_citation_resolution import result, source

    text = "Other text. Funds shall be provided."
    case = dict(id="case", text=text, text_sha256=digest(text))
    row = dict(
        case_id="case",
        source_text_sha256=digest(text),
        status="failed",
        failure_category="invalid_output",
        output=result().output,
        source_snapshot=[
            source("src_0001", "Other text."),
            source("src_0002", "Funds shall be provided.", 12),
        ],
    )
    audit = {}
    items = replay_items(case, row, resolution_audit=audit)
    assert items[0]["source_refs"] == ["src_0002"]
    assert audit["corrections"][0]["method"] == "unique_match"
    assert row["output"]["overview"][0]["source_refs"] == ["src_0001"]
