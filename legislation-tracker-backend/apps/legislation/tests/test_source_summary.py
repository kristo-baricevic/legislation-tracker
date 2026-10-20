from types import SimpleNamespace
import json
from io import StringIO
import pytest

from apps.legislation.source_summary import source_summary
from pathlib import Path


def test_hr3045_has_a_substantive_source_backed_synopsis():
    from apps.legislation.extraction.federal_structure import parse_federal_structure
    from apps.legislation.extraction.synopsis import structured_synopsis
    text = (Path(__file__).resolve().parents[3] / "tests/fixtures/hr3045_119_ih.txt").read_text()
    result = structured_synopsis(parse_federal_structure(text), (), text)
    assert result is not None
    summary, _, evidence = result
    assert "President" in summary
    assert "West Bank" in summary
    assert "property" in summary and "United States" in summary
    assert "exceptions" in summary and "waivers" in summary
    assert "90 days" in summary
    assert "sections cover" not in source_summary(text)
    assert len(summary.split()) < 220
    assert all(text[span.start_char:span.end_char] == span.text for span in evidence)


def test_generic_synopsis_keeps_complete_rules_instead_of_needing_a_bill_template():
    text = ("SEC. 1. Short title\nThis Act may be cited as the Test Act.\n"
            "SEC. 2. Findings\n" + "Congress finds that water is important. " * 100 +
            "\nSEC. 3. Publication\nThe Administrator shall publish water quality measurements "
            "annually, except that private addresses must not be disclosed.")
    result = source_summary(text)
    assert result is not None
    assert "water quality measurements" in result
    assert "except that private addresses must not be disclosed" in result
    assert "may be cited" not in result


@pytest.mark.parametrize("replacement", ["may impose sanctions", "shall not impose sanctions"])
def test_sanctions_synopsis_does_not_turn_permission_or_prohibition_into_a_mandate(replacement):
    from apps.legislation.extraction.federal_structure import parse_federal_structure
    from apps.legislation.extraction.synopsis import structured_synopsis
    text = (Path(__file__).resolve().parents[3] / "tests/fixtures/hr3045_119_ih.txt").read_text()
    text = text.replace("shall impose sanctions", replacement)
    result = structured_synopsis(parse_federal_structure(text), (), text)
    assert result is None or "Requires the President to impose sanctions" not in result[0]


def test_general_short_bill_keeps_complete_rule_and_exception():
    text = ("SEC. 1. Short title\nThis Act may be cited as the Test Act.\n"
            "SEC. 2. Reporting\nThe Secretary shall publish a report annually, "
            "except that personal information must not be disclosed.")
    summary = source_summary(text)
    assert summary
    assert "except that personal information must not be disclosed" in summary
    assert "may be cited" not in summary
    assert "Bill text" in summary


def test_long_section_uses_heading_not_a_cut_off_condition():
    text = "SEC. 1. Eligibility for rural health grants\n" + (
        "The Secretary shall award grants only if " + "a condition applies and " * 100
        + "all requirements are satisfied."
    )
    summary = source_summary(text)
    assert "Eligibility for rural health grants" in summary
    assert "shall award" not in summary
    assert len(summary) < 1000
    assert "overview" in summary.lower()


def test_does_not_promote_deleted_quoted_headings_to_bill_policy():
    text = ("SEC. 1. Updating requirements\nSection 2 is amended by striking the following:\n"
            "[[QUOTED_BLOCK_START]]\nSEC. 2. Ban on medical care\n"
            "The Secretary shall ban medical care.\n[[QUOTED_BLOCK_END]]")
    assert "Ban on medical care" not in source_summary(text)


def test_no_source_means_no_invented_summary():
    assert source_summary("") is None
    assert source_summary("SEC. 1. Short title\nThis Act may be cited as the Test Act.") is None


def test_document_serializer_uses_general_source_fallback():
    from apps.legislation.serializers import BillDocumentSerializer
    doc = SimpleNamespace(
        extracted_text="SEC. 2. Reports\nThe Secretary shall publish annual reports.",
        raw_text=None,
    )
    assert "annual reports" in BillDocumentSerializer().get_reader_summary(doc)


def test_definitions_heading_can_contain_substantive_obligations():
    text = "SEC. 2. Definitions\nThe Commission shall revise the definition of a qualifying investment within 180 days."
    assert "within 180 days" in source_summary(text)


def test_appropriations_preamble_without_section_headings():
    preamble = ("That the following sums are appropriated, out of any money in the Treasury "
                "not otherwise appropriated, for the Department of Defense for the fiscal "
                "year ending September 30, 2027, and for other purposes, namely:")
    text = preamble + "\nTITLE I\nSEC. 8001.\n" + ("A restriction applies. " * 200)
    assert preamble in source_summary(text)


@pytest.mark.django_db
def test_audit_counts_visible_summary_not_contract_existence():
    from django.core.management import call_command
    from apps.legislation.models import Bill, BillDocument
    bill = Bill.objects.create(jurisdiction="federal", session=119, bill_number="HR 1",
                               title="Test", status="Introduced")
    BillDocument.objects.create(bill=bill, is_active_version=True, version_label="Introduced",
                                extracted_text="SEC. 2. Reports\nThe Secretary shall publish annual reports.")
    Bill.objects.create(jurisdiction="federal", session=119, bill_number="HR 2",
                        title="Test 2", status="Introduced")
    out = StringIO()
    call_command("audit_bill_summaries", stdout=out)
    report = json.loads(out.getvalue())
    assert report["counts"]["source_fallback"] == 1
    assert report["counts"]["missing_source"] == 1
    assert report["total"] == 2


@pytest.mark.django_db
def test_summary_gate_rejects_a_headings_only_fallback_and_missing_analysis():
    from django.core.management import call_command, CommandError
    from apps.legislation.models import Bill, BillDocument
    bill = Bill.objects.create(jurisdiction="federal", session=119, bill_number="HR 9",
                               title="Test", status="Introduced")
    BillDocument.objects.create(
        bill=bill, is_active_version=True, version_label="Introduced",
        extracted_text="SEC. 2. Eligibility\nThe Secretary shall award grants only if "
                       + "a condition applies and " * 100 + "all requirements are satisfied.",
    )
    out = StringIO()
    with pytest.raises(CommandError):
        call_command("audit_bill_summaries", require_source_coverage=True, stdout=out)
    report = json.loads(out.getvalue())
    assert report["counts"]["outline_only"] == 1
    assert report["analysis_missing"] == [{"id": bill.id, "bill": "HR 9"}]
