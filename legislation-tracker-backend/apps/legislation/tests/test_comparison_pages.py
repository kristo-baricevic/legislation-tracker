import pytest
from unittest.mock import patch
from rest_framework.test import APIClient
from apps.legislation.models import Bill, BillDocument
from apps.legislation import comparison

pytestmark = pytest.mark.django_db

def test_passage_page_reuses_parsed_documents_and_bounds_work():
    bill = Bill.objects.create(jurisdiction="federal", session=119, bill_number="HR 16404")
    before = BillDocument.objects.create(bill=bill, version_label="before", extracted_text="SEC. 1. Test.\nOld text.\nSEC. 2. Other.\nOld words.")
    after = BillDocument.objects.create(bill=bill, version_label="after", extracted_text="SEC. 1. Test.\nNew text.\nSEC. 2. Other.\nNew words.")
    keys = [row.section_key for row in comparison.compare_document_sections(before=before, after=after).sections]
    assert len(keys) >= 2
    path = f"/api/bills/{bill.pk}/comparisons/documents/section/"
    client = APIClient()
    with patch.object(comparison, "_section_map", wraps=comparison._section_map) as parse:
        response = client.get(path, {"before": before.pk, "after": after.pk, "section_keys": keys})
    assert response.status_code == 200
    assert [row["section_key"] for row in response.data["results"]] == keys
    assert all(row["operations"] for row in response.data["results"])
    assert parse.call_count == 2
    assert client.get(path, {"before": before.pk, "after": after.pk, "section_keys": ["x"] * 6}).status_code == 400
    assert client.get(path, {"before": before.pk, "after": after.pk, "section_keys": keys, "section_key": keys[0]}).status_code == 400
    other = Bill.objects.create(jurisdiction="federal", session=119, bill_number="HR 16405")
    foreign = BillDocument.objects.create(bill=other)
    assert client.get(path, {"before": before.pk, "after": foreign.pk, "section_keys": keys}).status_code == 404
