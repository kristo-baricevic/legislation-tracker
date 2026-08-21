# ruff: noqa: F401, F811

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.legislation.enhancements.service import create_enhancement_attempt
from apps.legislation.enhancements.source_packet import build_enhancement_preflight
from apps.legislation.models import BillEnhancement, BillEnhancementAttempt

from .test_enhancement_service import (
    _confirmation,
    _valid_credential,
    enhancement_owner,
    enhancement_settings,
    source_bill,
)


@pytest.fixture
def enhancement_client(enhancement_owner):
    client = APIClient()
    client.force_authenticate(enhancement_owner)
    return client


def _assert_private(response):
    assert response["Cache-Control"] == "private, no-store"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "method,path_suffix",
    [
        ("get", "estimate/"),
        ("get", ""),
        ("get", "latest/"),
        ("post", ""),
    ],
)
def test_all_enhancement_routes_require_authentication(
    method,
    path_suffix,
    source_bill,
):
    response = getattr(APIClient(), method)(
        f"/api/bills/{source_bill.id}/enhancements/{path_suffix}",
        {},
        format="json",
    )
    assert response.status_code == 401
    _assert_private(response)


@pytest.mark.django_db
def test_estimate_reports_full_confirmation_and_credential_state(
    enhancement_client,
    enhancement_owner,
    source_bill,
    enhancement_settings,
):
    with enhancement_settings:
        credential = _valid_credential(enhancement_owner)
        preflight = build_enhancement_preflight(source_bill)
        response = enhancement_client.get(
            f"/api/bills/{source_bill.id}/enhancements/estimate/"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["can_enhance"] is True
    assert body["source_fingerprint"] == preflight.source_fingerprint
    assert body["request_fingerprint"] == preflight.request_fingerprint
    assert body["credential_revision"] == credential.revision
    assert body["estimated_input_tokens"] == preflight.estimated_input_tokens
    assert body["max_output_tokens"] == 4000
    assert "price" not in str(body).lower()
    _assert_private(response)


@pytest.mark.django_db
def test_estimate_distinguishes_a_disabled_credential(
    enhancement_client,
    enhancement_owner,
    source_bill,
    enhancement_settings,
):
    with enhancement_settings:
        credential = _valid_credential(enhancement_owner)
        credential.enabled = False
        credential.save(update_fields=["enabled"])
        response = enhancement_client.get(
            f"/api/bills/{source_bill.id}/enhancements/estimate/"
        )

    assert response.status_code == 200
    assert response.json()["can_enhance"] is False
    assert response.json()["unavailable_reason"] == "credential_disabled"


@pytest.mark.django_db
def test_create_deduplicates_and_private_history_never_exposes_internal_data(
    enhancement_client,
    enhancement_owner,
    source_bill,
    enhancement_settings,
):
    with enhancement_settings:
        credential = _valid_credential(enhancement_owner)
        confirmation = _confirmation(source_bill, credential)
        first = enhancement_client.post(
            f"/api/bills/{source_bill.id}/enhancements/",
            confirmation,
            format="json",
        )
        second = enhancement_client.post(
            f"/api/bills/{source_bill.id}/enhancements/",
            confirmation,
            format="json",
        )
        history = enhancement_client.get(f"/api/bills/{source_bill.id}/enhancements/")

    assert first.status_code == 202
    assert second.status_code == 200
    assert BillEnhancementAttempt.objects.count() == 1
    assert history.status_code == 200
    serialized = str(history.content)
    for private_name in (
        "source_snapshot_json",
        "source_manifest_json",
        "provider_response_id",
        "encrypted_envelope",
        "sk-test-enhancement",
    ):
        assert private_name not in serialized
    _assert_private(first)
    _assert_private(second)
    _assert_private(history)


@pytest.mark.django_db
def test_history_is_paginated_and_page_size_is_bounded(
    enhancement_client,
    enhancement_owner,
    source_bill,
):
    BillEnhancement.objects.bulk_create(
        [
            BillEnhancement(
                user=enhancement_owner,
                bill=source_bill,
                provider="openai",
                requested_model="test-model",
                reasoning_effort="none",
                prompt_version="test",
                output_schema_version="1.1",
                source_packet_version="test",
                source_fingerprint=f"{index:064x}",
                request_fingerprint=f"{index + 100:064x}",
                source_manifest_json={},
                source_snapshot_json=[],
            )
            for index in range(101)
        ]
    )

    first = enhancement_client.get(
        f"/api/bills/{source_bill.id}/enhancements/?page_size=1000"
    )
    second = enhancement_client.get(
        f"/api/bills/{source_bill.id}/enhancements/?page=6&page_size=20"
    )

    assert first.status_code == 200
    assert first.json()["count"] == 101
    assert len(first.json()["results"]) == 100
    assert first.json()["next"] is not None
    assert second.status_code == 200
    assert len(second.json()["results"]) == 1
    assert second.json()["previous"] is not None


@pytest.mark.django_db
def test_detail_expands_only_server_owned_cited_source_text(
    enhancement_client,
    enhancement_owner,
    source_bill,
    enhancement_settings,
):
    with enhancement_settings:
        credential = _valid_credential(enhancement_owner)
        created = create_enhancement_attempt(
            user=enhancement_owner,
            bill=source_bill,
            confirmed=_confirmation(source_bill, credential),
        )
        source_ref = created.enhancement.source_snapshot_json[0]["source_ref"]
        created.enhancement.result_json = {
            "schema_version": "1.1",
            "overview": [
                {
                    "text": "The bill requires a report.",
                    "source_refs": [source_ref],
                }
            ],
            "key_impacts": [],
            "obligations": [],
            "funding_and_timing": [],
            "uncertain_language": [],
        }
        created.enhancement.status = created.enhancement.Status.SUCCEEDED
        created.enhancement.successful_attempt = created.attempt
        created.enhancement.save(
            update_fields=["result_json", "status", "successful_attempt"]
        )
        created.attempt.status = created.attempt.Status.SUCCEEDED
        created.attempt.provider_response_id = "private-provider-id"
        created.attempt.save(update_fields=["status", "provider_response_id"])

        detail = enhancement_client.get(
            f"/api/bills/{source_bill.id}/enhancements/{created.enhancement.id}/"
        )

    assert detail.status_code == 200
    item = detail.json()["result"]["overview"][0]
    assert item["cited_sources"][0]["quoted_text"].startswith("SEC. 2.")
    assert item["cited_sources"][0]["label"] == "Cited source"
    assert "private-provider-id" not in str(detail.content)
    assert "verified evidence" not in str(detail.content).lower()
    _assert_private(detail)


@pytest.mark.django_db
def test_cross_user_detail_and_latest_are_hidden(
    enhancement_owner,
    source_bill,
    enhancement_settings,
):
    other = get_user_model().objects.create_user(
        username="api-other@example.com",
        email="api-other@example.com",
        password="password123",
    )
    other_client = APIClient()
    other_client.force_authenticate(other)
    with enhancement_settings:
        credential = _valid_credential(enhancement_owner)
        created = create_enhancement_attempt(
            user=enhancement_owner,
            bill=source_bill,
            confirmed=_confirmation(source_bill, credential),
        )
        detail = other_client.get(
            f"/api/bills/{source_bill.id}/enhancements/{created.enhancement.id}/"
        )
        latest = other_client.get(f"/api/bills/{source_bill.id}/enhancements/latest/")

    assert detail.status_code == 404
    assert latest.status_code == 404
    _assert_private(detail)
    _assert_private(latest)
