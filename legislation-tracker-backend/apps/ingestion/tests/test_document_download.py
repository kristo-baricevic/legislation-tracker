import boto3
import pytest
from botocore.exceptions import ClientError

from apps.ingestion import document_download


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
