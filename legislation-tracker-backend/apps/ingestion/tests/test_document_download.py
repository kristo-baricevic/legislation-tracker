import boto3
import pytest
from botocore.exceptions import ClientError

from apps.ingestion import document_download


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


def test_ensure_s3_bucket_omits_location_constraint_in_us_east_1(
    monkeypatch, settings
):
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
