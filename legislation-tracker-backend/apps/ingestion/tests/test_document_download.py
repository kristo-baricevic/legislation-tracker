import boto3
import pypdf
import pytest
import requests
from botocore.exceptions import ClientError

from apps.ingestion import document_download


class FakeStreamingResponse:
    def __init__(self, chunks, headers=None):
        self.chunks = chunks
        self.headers = headers or {}
        self.closed = False
        self.iterated = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        self.iterated = True
        yield from self.chunks

    def close(self):
        self.closed = True


def test_download_without_content_length_streams_within_the_decoded_byte_limit(
    monkeypatch,
):
    response = FakeStreamingResponse(
        [b"ab", b"cd"],
        headers={"Content-Type": "application/pdf; charset=binary"},
    )
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response)

    downloaded = document_download.download_url(
        "https://example.test/bill.pdf",
        max_bytes=4,
        spool_max_bytes=2,
    )
    with downloaded:
        assert downloaded.content_type == "application/pdf"
        assert downloaded.size == 4
        assert (
            downloaded.checksum
            == "88d4266fd4e6338d13b845fcf289579d209c897823b9217da3e161936f031589"
        )
        assert downloaded.file.read() == b"abcd"

    assert response.closed
    assert downloaded.file.closed


def test_download_rejects_excessive_declared_content_length_before_streaming(
    monkeypatch,
):
    response = FakeStreamingResponse(
        [b"abcde"],
        headers={"Content-Length": "5"},
    )
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response)

    with pytest.raises(document_download.DocumentByteLimitExceeded, match="5 bytes"):
        document_download.download_url(
            "https://example.test/bill.pdf",
            max_bytes=4,
        )

    assert not response.iterated
    assert response.closed


def test_download_rejects_decoded_chunk_overflow_and_closes_resources(monkeypatch):
    response = FakeStreamingResponse(
        [b"abc", b"de"],
        headers={"Content-Length": "4"},
    )
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response)

    with pytest.raises(
        document_download.DocumentByteLimitExceeded, match="more than 4"
    ):
        document_download.download_url(
            "https://example.test/compressed-bill.pdf",
            max_bytes=4,
        )

    assert response.iterated
    assert response.closed


def test_download_uses_the_configured_timeout(monkeypatch, settings):
    settings.DOCUMENT_DOWNLOAD_TIMEOUT_SECONDS = 7
    observed = {}

    def timeout(*args, **kwargs):
        observed.update(kwargs)
        raise requests.Timeout("read timed out")

    monkeypatch.setattr(requests, "get", timeout)

    with pytest.raises(requests.Timeout, match="read timed out"):
        document_download.download_url("https://example.test/bill.pdf")

    assert observed["timeout"] == 7
    assert observed["stream"] is True


def test_pdf_page_limit_is_enforced_before_page_text_is_extracted(monkeypatch):
    class Page:
        def extract_text(self):
            pytest.fail("page text must not be extracted after page limit rejection")

    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda stream: type("Reader", (), {"pages": [Page(), Page(), Page()]})(),
    )

    with pytest.raises(document_download.DocumentPageLimitExceeded, match="3 pages"):
        document_download.extract_text_from_pdf(
            b"%PDF-test",
            max_pages=2,
            max_text_chars=100,
        )


def test_pdf_extracted_text_limit_is_enforced_during_extraction(monkeypatch):
    class Page:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            return self.text

    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda stream: type(
            "Reader",
            (),
            {"pages": [Page("abcd"), Page("ef")]},
        )(),
    )

    with pytest.raises(
        document_download.DocumentTextLimitExceeded, match="5 characters"
    ):
        document_download.extract_text_from_pdf(
            b"%PDF-test",
            max_pages=2,
            max_text_chars=5,
        )


def test_malformed_pdf_is_rejected_instead_of_becoming_empty_text():
    with pytest.raises(document_download.MalformedDocumentError):
        document_download.extract_document_text(
            b"not a PDF",
            "application/pdf",
            "https://example.test/bill.pdf",
        )


def test_malformed_xml_is_rejected_instead_of_becoming_tag_stripped_text():
    with pytest.raises(document_download.MalformedDocumentError):
        document_download.extract_document_text(
            b"<bill><legis-body><section>truncated",
            "application/xml",
            "https://example.test/bill.xml",
        )


def test_empty_xml_is_rejected_instead_of_becoming_an_empty_success():
    with pytest.raises(document_download.MalformedDocumentError):
        document_download.extract_document_text(
            b"  \n\t",
            "application/xml",
            "https://example.test/bill.xml",
        )


def test_xml_extracted_text_limit_rejects_instead_of_truncating():
    payload = (
        b"<bill><legis-body><section><enum>1.</enum><text>abcdef</text>"
        b"</section></legis-body></bill>"
    )

    with pytest.raises(
        document_download.DocumentTextLimitExceeded, match="5 characters"
    ):
        document_download.extract_document_text(
            payload,
            "application/xml",
            "https://example.test/bill.xml",
            max_text_chars=5,
        )


def test_extract_congress_xml_preserves_full_structural_hierarchy():
    payload = b"""\
<bill>
  <legis-body>
    <division>
      <enum>A</enum>
      <header>Programs</header>
      <subchapter>
        <enum>I</enum>
        <header>Reports</header>
        <section>
          <enum>2.</enum>
          <header>Duties</header>
          <subsection>
            <enum>(a)</enum>
            <subparagraph>
              <enum>(1)</enum>
              <text>The Secretary shall publish a report.</text>
              <subitem>
                <enum>(AA)</enum>
                <text>The report shall include grant results.</text>
                <quoted-block>
                  <section>
                    <enum>7.</enum>
                    <header>Inserted requirement</header>
                    <paragraph>
                      <enum>(1)</enum>
                      <text>The Administrator shall notify Congress.</text>
                    </paragraph>
                  </section>
                </quoted-block>
              </subitem>
            </subparagraph>
          </subsection>
        </section>
      </subchapter>
    </division>
  </legis-body>
</bill>
"""

    text = document_download.extract_text_from_xml_or_html(payload, "application/xml")

    assert "DIVISION A Programs" in text
    assert "SUBCHAPTER I Reports" in text
    assert "SEC. 2. Duties" in text
    assert "(AA) The report shall include grant results." in text
    assert "SEC. 7. Inserted requirement" in text
    assert text.count("[[QUOTED_BLOCK_START]]") == 1
    assert text.count("[[QUOTED_BLOCK_END]]") == 1


def test_extract_congress_xml_does_not_truncate_late_sections():
    payload = (
        b"<bill><legis-body><section><enum>2.</enum><header>Long findings</header>"
        b"<text>"
        + (b"x" * 500_000)
        + b"</text></section><section><enum>3.</enum><header>Final duty</header>"
        b"<text>The Secretary shall publish the final report.</text>"
        b"</section></legis-body></bill>"
    )

    text = document_download.extract_text_from_xml_or_html(payload, "application/xml")

    assert "SEC. 3. Final duty" in text
    assert text.endswith("The Secretary shall publish the final report.")


def _missing_bucket_error():
    return ClientError(
        {
            "Error": {"Code": "404", "Message": "Not Found"},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        },
        "HeadBucket",
    )


def test_ensure_s3_bucket_omits_location_constraint_in_us_east_1(monkeypatch, settings):
    settings.USE_LOCAL_DOCUMENT_STORAGE = False
    settings.AWS_STORAGE_BUCKET_NAME = "legislation-tracker-test"
    settings.AWS_S3_ENDPOINT_URL = ""
    settings.AWS_S3_REGION_NAME = "us-east-1"

    class FakeClient:
        def __init__(self):
            self.create_calls = []

        def head_bucket(self, **kwargs):
            raise _missing_bucket_error()

        def create_bucket(self, **kwargs):
            self.create_calls.append(kwargs)

    client = FakeClient()
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)

    document_download.ensure_s3_bucket_exists()

    assert client.create_calls == [{"Bucket": "legislation-tracker-test"}]


def test_ensure_s3_bucket_keeps_location_constraint_outside_us_east_1(
    monkeypatch, settings
):
    settings.USE_LOCAL_DOCUMENT_STORAGE = False
    settings.AWS_STORAGE_BUCKET_NAME = "legislation-tracker-test"
    settings.AWS_S3_ENDPOINT_URL = ""
    settings.AWS_S3_REGION_NAME = "eu-west-1"

    class FakeClient:
        def __init__(self):
            self.create_calls = []

        def head_bucket(self, **kwargs):
            raise _missing_bucket_error()

        def create_bucket(self, **kwargs):
            self.create_calls.append(kwargs)

    client = FakeClient()
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)

    document_download.ensure_s3_bucket_exists()

    assert client.create_calls == [
        {
            "Bucket": "legislation-tracker-test",
            "CreateBucketConfiguration": {"LocationConstraint": "eu-west-1"},
        }
    ]
