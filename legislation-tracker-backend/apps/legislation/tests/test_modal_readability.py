from types import SimpleNamespace

from apps.legislation.comparison import _section_map
from apps.legislation.serializers import BillDocumentSerializer


def test_nested_comparison_keys_do_not_repeat_ancestry():
    doc = SimpleNamespace(
        extracted_text="DIVISION A. Funding\nTITLE I. Programs\nSEC. 101. Grants\n(a) The Secretary shall award grants.\n(b) The Secretary shall report annually.",
        raw_text="",
    )
    sections, _, _ = _section_map(doc)
    assert sections
    for key in sections:
        assert key.count("division a#1") <= 1


def test_document_summary_uses_appropriation_statement_and_scope():
    doc = SimpleNamespace(
        extracted_text="SEC. 5. Statement of appropriations\nThe following sums in this Act are appropriated, out of any money in the Treasury not otherwise appropriated, for the fiscal year ending September 30, 2026.\nDIVISION A Department of Homeland Security Appropriations\nTITLE I\nSEC. 101. Reports\nThe Secretary shall submit a report.",
        raw_text="",
    )
    summary = BillDocumentSerializer().get_reader_summary(doc)
    assert (
        summary
        == "This bill would provide funding for Department of Homeland Security for the fiscal year ending September 30, 2026."
    )


def test_document_summary_does_not_invent_appropriations_from_title_only():
    doc = SimpleNamespace(
        extracted_text="SEC. 1. Short title\nThis Act may be cited as the Appropriations Act.\nSEC. 2. Reports\nThe Secretary shall report on funding.",
        raw_text="",
    )
    assert BillDocumentSerializer().get_reader_summary(doc) == (
        "Bill text: The Secretary shall report on funding."
    )
