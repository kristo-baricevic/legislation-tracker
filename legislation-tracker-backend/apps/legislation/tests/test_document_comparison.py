import pytest

from apps.legislation.comparison import compare_document_sections
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
