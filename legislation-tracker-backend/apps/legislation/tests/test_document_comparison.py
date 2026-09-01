import pytest

from apps.legislation.comparison import (
    compare_document_section,
    compare_document_sections,
)
from apps.legislation.models import Bill, BillDocument


@pytest.mark.django_db
def test_document_comparison_matches_federal_sections_by_label_not_position():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 909",
        title="Document diff bill",
        status="Introduced",
    )
    before = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        extracted_text="SEC. 1. REPORTS\nThe agency shall report.\nSEC. 2. GRANTS\nThe agency may grant funds.",
    )
    after = BillDocument.objects.create(
        bill=bill,
        version_label="Engrossed",
        extracted_text="SEC. 2. GRANTS\nThe agency may grant funds.\nSEC. 1. REPORTS\nThe agency shall submit a report.",
    )

    diff = compare_document_sections(before=before, after=after)

    assert [(item.section_key, item.operation) for item in diff.sections] == [
        ("sec. 1#1", "modified"),
    ]


@pytest.mark.django_db
def test_document_comparison_scopes_duplicate_subsection_labels_to_their_parent_path():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 910",
        title="Nested section diff bill",
        status="Introduced",
    )
    before = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        extracted_text=(
            "SEC. 1. FIRST\n"
            "(a) First provision.\n"
            "SEC. 2. SECOND\n"
            "(a) Second provision."
        ),
    )
    after = BillDocument.objects.create(
        bill=bill,
        version_label="Reported",
        extracted_text=(
            "SEC. 1. FIRST\n"
            "(a) First provision.\n"
            "(a) Added provision.\n"
            "SEC. 2. SECOND\n"
            "(a) Second provision."
        ),
    )

    diff = compare_document_sections(before=before, after=after)

    assert [(item.section_key, item.operation) for item in diff.sections] == [
        ("sec. 1#1", "modified"),
        ("sec. 1#1/(a)#2", "added"),
    ]


@pytest.mark.django_db
def test_document_comparison_reports_source_truncation_instead_of_hiding_tail_changes():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 911",
        title="Long document diff bill",
        status="Introduced",
    )
    prefix = "A" * 50_000
    before = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        extracted_text=prefix + "\n\nold tail",
    )
    after = BillDocument.objects.create(
        bill=bill,
        version_label="Reported",
        extracted_text=prefix + "\n\nnew tail",
    )

    diff = compare_document_sections(before=before, after=after)

    assert diff.truncated is True
    assert "source_text_limit" in diff.truncation_reasons


@pytest.mark.django_db
def test_document_line_comparison_reports_only_an_exceeded_operation_limit():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 912",
        title="Line diff limit bill",
        status="Introduced",
    )
    before_lines = [f"shared {index}" for index in range(1_001)]
    after_lines = list(before_lines)
    for index in range(0, 1_001, 2):
        after_lines[index] = f"changed {index}"
    before = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        extracted_text="\n".join(before_lines),
    )
    after = BillDocument.objects.create(
        bill=bill,
        version_label="Reported",
        extracted_text="\n".join(after_lines),
    )

    diff = compare_document_section(
        before=before,
        after=after,
        section_key="paragraph-1",
    )

    assert len(diff.operations) == 500
    assert diff.truncated is True
    assert "operation_limit" in diff.truncation_reasons
