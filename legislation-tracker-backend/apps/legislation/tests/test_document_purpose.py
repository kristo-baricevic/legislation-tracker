from io import BytesIO, StringIO
import json
from types import SimpleNamespace

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command

from apps.ingestion.document_download import extract_document_purpose
from apps.legislation.serializers import BillDocumentSerializer


XML = b"""<bill><form><official-title>To amend title XVIII of the Social Security Act
to exclude certain sales of principal residences from income related monthly adjustment
amount calculations under Medicare.</official-title></form>
<legis-body><section><header>Short title</header><text>The Medicare Protection Act.</text></section></legis-body></bill>"""


def test_extracts_version_specific_purpose_without_changing_stream_position():
    stream = BytesIO(XML)
    stream.seek(12)
    result = extract_document_purpose(stream, "application/xml", None)
    assert "exclude certain sales of principal residences" in result
    assert "under Medicare." in result
    assert "Short title" not in result
    assert stream.tell() == 12


def test_never_uses_an_amendment_heading_or_short_title_as_the_purpose():
    assert extract_document_purpose(
        b"<bill><legis-body><official-title>To ban medical care.</official-title></legis-body></bill>",
        "application/xml", None,
    ) == ""
    assert extract_document_purpose(b"<bill><form><short-title>Protection Act</short-title></form></bill>",
                                    "application/xml", None) == ""


@pytest.mark.parametrize("purpose,expected", [
    ("To improve end-of-life care.", "improve end-of-life care."),
    ("A bill to increase the supply of housing in America.", "increase the supply of housing in America."),
    ("For the relief of Maria Cordova.", "For the relief of Maria Cordova."),
])
def test_preserves_short_and_private_bill_purposes(purpose, expected):
    from apps.legislation.source_summary import purpose_summary
    assert expected in purpose_summary(purpose)


def test_rejects_entity_expansion_in_source_metadata():
    assert extract_document_purpose(
        b'<!DOCTYPE bill [<!ENTITY injected "To ban medical care.">]><bill><form>'
        b'<official-title>&injected;</official-title></form></bill>', "application/xml", None,
    ) == ""


def test_extracts_gpo_html_purpose_before_enacting_clause_without_notes():
    html = b"""<html><body><pre>[Public Law 119-39]
An Act

To amend the Internal Revenue Code to require additional
information on math and clerical error notices. &lt;&lt;NOTE: Nov. 25,
2025 - [H.R. 998]&gt;&gt;

Be it enacted by the Senate and House of Representatives of the
United States of America in Congress assembled,
SECTION 1. SHORT TITLE.
This Act may be cited as the Test Act.
</pre></body></html>"""
    assert extract_document_purpose(html, "text/html", None) == (
        "To amend the Internal Revenue Code to require additional "
        "information on math and clerical error notices."
    )


def test_serializer_uses_source_purpose_instead_of_headings_only_fallback():
    doc = SimpleNamespace(source_purpose="To exclude certain sales of principal residences from Medicare premium calculations.",
                          extracted_text="SEC. 1. Short title\nThis Act may be cited as the Protection Act.",
                          raw_text=None)
    summary = BillDocumentSerializer().get_reader_summary(doc)
    assert "exclude certain sales of principal residences" in summary
    assert "Medicare premium calculations" in summary
    assert "sections cover" not in summary


@pytest.mark.django_db
def test_backfill_preserves_text_hash_and_offsets_and_is_repeatable(settings, tmp_path):
    from apps.legislation.models import Bill, BillDocument
    settings.MEDIA_ROOT = tmp_path
    settings.STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}}
    bill = Bill.objects.create(jurisdiction="federal", session=119, bill_number="HR 3007")
    key = default_storage.save("purpose.xml", ContentFile(XML))
    doc = BillDocument.objects.create(bill=bill, version_label="Introduced", is_active_version=True,
                                     object_storage_key=key, content_type="application/xml",
                                     extracted_text="Exact existing text.", content_hash="a" * 64)
    out = StringIO()
    call_command("backfill_document_purposes", execute=True, stdout=out)
    doc.refresh_from_db()
    assert "exclude certain sales" in doc.source_purpose
    assert doc.extracted_text == "Exact existing text."
    assert doc.content_hash == "a" * 64
    assert json.loads(out.getvalue())["updated"] == 1
    out = StringIO()
    call_command("backfill_document_purposes", execute=True, stdout=out)
    assert json.loads(out.getvalue())["updated"] == 0
