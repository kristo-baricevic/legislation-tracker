# ruff: noqa: F401, F811
import pytest
from django.test import override_settings

from apps.legislation.enhancements.providers.base import (
    ProviderError,
    ProviderResult,
    ProviderUsage,
)
from apps.legislation.enhancements.source_packet import build_enhancement_preflight
from apps.legislation.models import BillEnhancementAttempt
from apps.legislation.tasks import run_bill_enhancement_attempt

from .test_enhancement_service import (
    enhancement_owner,
    enhancement_settings,
    source_bill,
)
from .test_enhancement_tasks import _pending_attempt


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "mode",
    [
        "success",
        "unknown",
        "revoked",
        "source_changed",
        "feature_disabled",
        "lease_lost",
    ],
)
def test_source_first_durable_dispatch(
    enhancement_owner, enhancement_settings, source_bill, monkeypatch, mode
):
    from apps.legislation.models import BillEnhancementStep

    calls = []

    class Provider:
        def generate_provisions(self, **kwargs):
            calls.append("generation")
            assert (
                BillEnhancementStep.objects.get(attempt=attempt, step_index=0).status
                == "dispatching"
            )
            if mode == "unknown":
                raise ProviderError("outcome_unknown", outcome_unknown=True)
            if mode == "revoked":
                attempt.credential.enabled = False
                attempt.credential.save()
            if mode == "source_changed":
                source_bill.documents.update(
                    extracted_text="SEC. 1. CHANGED\nDifferent law."
                )
            if mode == "feature_disabled":
                from django.conf import settings

                settings.LLM_SOURCE_FIRST_ENABLED = False
            if mode == "lease_lost":
                from django.utils import timezone

                BillEnhancementAttempt.objects.filter(pk=attempt.pk).update(
                    lease_expires_at=timezone.now()
                )
            unit = kwargs["request"].request_envelope["source_first_payload"]["units"][
                0
            ]
            output = {
                "provisions": [
                    {
                        "unit_id": unit["id"],
                        "status": "explained",
                        "summary": "The Secretary must publish a report within 90 days.",
                        "coverage_items": [
                            {
                                "item_id": item["id"],
                                "status": "explained",
                                "claim_indexes": [0],
                                "explanation_indexes": [0],
                                "reason": None,
                            }
                            for item in unit["source_checklist"]
                        ],
                        "details": [],
                        "unresolved_reason": None,
                        "claims": [
                            {
                                "actor": "The Secretary",
                                "action": "publish a report within 90 days",
                                "modality": "required",
                                "money": [],
                                "conditions": None,
                                "exceptions": [],
                                "evidence_ids": unit["own_passage_ids"],
                            }
                        ],
                    }
                ]
            }
            return ProviderResult(output, ProviderUsage(10, 10, 20), "resp", "test")

        def generate_synopsis(self, **kwargs):
            calls.append("synopsis")
            assert (
                BillEnhancementStep.objects.get(attempt=attempt, step_index=0).status
                == "succeeded"
            )
            ids = [
                x["unit_id"]
                for x in kwargs["request"].request_envelope["source_first_payload"][
                    "explanations"
                ]
            ]
            return ProviderResult(
                {
                    "text": "The Secretary must publish a report within 90 days.",
                    "explanation_ids": ids,
                },
                ProviderUsage(5, 5, 10),
                "synopsis",
                "test",
            )

    with enhancement_settings, override_settings(LLM_SOURCE_FIRST_ENABLED=True):
        document = source_bill.documents.first()
        document.extracted_text = (
            "SEC. 1. REPORT\nThe Secretary shall publish a report within 90 days."
        )
        document.save()
        preflight = build_enhancement_preflight(source_bill)
        assert preflight.output_schema_version == "2.0-source-first"
        assert preflight.source_manifest["budget"]["maximum_calls"] == 3
        attempt = _pending_attempt(enhancement_owner, source_bill)
        monkeypatch.setattr("apps.legislation.tasks.get_provider", lambda _: Provider())
        outcome = run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)
        attempt.refresh_from_db()
        attempt.enhancement.refresh_from_db()
        if mode == "success":
            assert outcome["status"] == "succeeded"
            assert attempt.enhancement.published_attempt_id == attempt.id
            assert attempt.enhancement.result_completeness == "complete"
            assert attempt.total_tokens == 30
        else:
            assert outcome["status"] != "succeeded"
            assert calls == ["generation"]
            assert attempt.enhancement.published_attempt_id is None
        assert (
            run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)["status"]
            == "not_claimed"
        )


@pytest.mark.django_db(transaction=True)
def test_partial_retry_promotes_without_regenerating_accepted_units(
    enhancement_owner, enhancement_settings, source_bill, monkeypatch
):
    from apps.legislation.enhancements.service import (
        retry_allowed,
        retry_enhancement_attempt,
    )

    requests = []
    phase = [0]

    class Provider:
        def generate_provisions(self, **kwargs):
            units = kwargs["request"].request_envelope["source_first_payload"]["units"]
            requests.append([u["id"] for u in units])
            rows = []
            for index, unit in enumerate(units):
                if phase[0] == 0 and (index == 1 or len(units) == 1):
                    rows.append(
                        {
                            "unit_id": unit["id"],
                            "status": "unresolved",
                            "summary": "",
                            "details": [],
                            "claims": [],
                            "unresolved_reason": "Needs review",
                        }
                    )
                else:
                    rows.append(
                        {
                            "unit_id": unit["id"],
                            "status": "explained",
                            "summary": "The Secretary must publish a report.",
                            "coverage_items": [
                                {
                                    "item_id": item["id"],
                                    "status": "explained",
                                    "claim_indexes": [0],
                                    "explanation_indexes": [0],
                                    "reason": None,
                                }
                                for item in unit["source_checklist"]
                            ],
                            "details": [],
                            "unresolved_reason": None,
                            "claims": [
                                {
                                    "actor": "The Secretary",
                                    "action": "publish a report",
                                    "modality": "required",
                                    "money": [],
                                    "conditions": None,
                                    "exceptions": [],
                                    "evidence_ids": unit["own_passage_ids"],
                                }
                            ],
                        }
                    )
            return ProviderResult(
                {"provisions": rows}, ProviderUsage(10, 10, 20), "resp", "test"
            )

        repair_provisions = generate_provisions

        def generate_synopsis(self, **kwargs):
            rows = kwargs["request"].request_envelope["source_first_payload"][
                "explanations"
            ]
            return ProviderResult(
                {"text": rows[0]["summary"], "explanation_ids": [rows[0]["unit_id"]]},
                ProviderUsage(5, 5, 10),
                "synopsis",
                "test",
            )

    with enhancement_settings, override_settings(LLM_SOURCE_FIRST_ENABLED=True):
        doc = source_bill.documents.first()
        doc.extracted_text = "SEC. 1. REPORT\nThe Secretary shall publish a report.\nSEC. 2. REPORT\nThe Secretary shall publish a report."
        doc.save()
        first = _pending_attempt(enhancement_owner, source_bill)
        monkeypatch.setattr("apps.legislation.tasks.get_provider", lambda _: Provider())
        run_bill_enhancement_attempt(first.pk, first.dispatch_token)
        first.refresh_from_db()
        enhancement = first.enhancement
        assert enhancement.result_completeness == "partial"
        assert retry_allowed(first)
        prior = enhancement.result_json
        preflight = build_enhancement_preflight(source_bill, reuse_result=prior)
        second = retry_enhancement_attempt(
            user=enhancement_owner,
            bill=source_bill,
            enhancement_id=enhancement.pk,
            confirmed={
                "source_fingerprint": preflight.source_fingerprint,
                "request_fingerprint": preflight.request_fingerprint,
                "credential_revision": first.credential_revision,
            },
        ).attempt
        phase[0] = 1
        run_bill_enhancement_attempt(second.pk, second.dispatch_token)
        enhancement.refresh_from_db()
        second.refresh_from_db()
        assert enhancement.result_completeness == "complete"
        assert enhancement.published_attempt_id == second.id
        assert enhancement.result_json["provisions"][0] == prior["provisions"][0]
        assert requests[-1] == [prior["provisions"][1]["unit_id"]]
        assert second.total_tokens == 30
        assert enhancement.total_tokens == 80


@pytest.mark.parametrize(
    "old_missing,new_missing,promote",
    [(["b"], [], True), (["b"], ["b"], False), ([], ["b"], False)],
)
def test_publication_transitions(old_missing, new_missing, promote):
    from apps.legislation.enhancements.source_first_worker import should_promote

    def output(missing):
        return {
            "schema_version": "2.0-source-first",
            "document_fingerprint": "pinned",
            "coverage": {"unresolved_unit_ids": missing},
            "provisions": [
                {"unit_id": "a", "status": "explained", "summary": "unchanged"},
                {"unit_id": "b", "status": "unresolved" if missing else "explained"},
            ],
        }

    assert should_promote(output(old_missing), output(new_missing)) is promote


@pytest.mark.django_db(transaction=True)
def test_postgres_duplicate_worker_cannot_dispatch_same_paid_step(
    enhancement_owner, enhancement_settings, source_bill, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from django.db import close_old_connections, connection

    from apps.legislation.models import BillEnhancementStep

    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL row locks")
    started, release = Event(), Event()
    calls = []

    class Provider:
        def generate_provisions(self, **kwargs):
            calls.append("generation")
            started.set()
            assert release.wait(10), "test worker was not released"
            unit = kwargs["request"].request_envelope["source_first_payload"]["units"][
                0
            ]
            return ProviderResult(
                {
                    "provisions": [
                        {
                            "unit_id": unit["id"],
                            "status": "explained",
                            "summary": "The Secretary must publish a report.",
                            "details": [],
                            "unresolved_reason": None,
                            "coverage_items": [
                                {
                                    "item_id": item["id"],
                                    "status": "explained",
                                    "claim_indexes": [0],
                                    "explanation_indexes": [0],
                                    "reason": None,
                                }
                                for item in unit["source_checklist"]
                            ],
                            "claims": [
                                {
                                    "actor": "The Secretary",
                                    "action": "publish a report",
                                    "modality": "required",
                                    "money": [],
                                    "conditions": None,
                                    "exceptions": [],
                                    "evidence_ids": unit["own_passage_ids"],
                                }
                            ],
                        }
                    ]
                },
                ProviderUsage(10, 10, 20),
                "first",
                "test",
            )

        def generate_synopsis(self, **kwargs):
            calls.append("synopsis")
            rows = kwargs["request"].request_envelope["source_first_payload"][
                "explanations"
            ]
            return ProviderResult(
                {"text": rows[0]["summary"], "explanation_ids": [rows[0]["unit_id"]]},
                ProviderUsage(5, 5, 10),
                "second",
                "test",
            )

    def run(attempt_id, token):
        close_old_connections()
        try:
            return run_bill_enhancement_attempt(attempt_id, token)
        finally:
            close_old_connections()

    with enhancement_settings, override_settings(LLM_SOURCE_FIRST_ENABLED=True):
        doc = source_bill.documents.first()
        doc.extracted_text = "SEC. 1. REPORT\nThe Secretary shall publish a report."
        doc.save()
        attempt = _pending_attempt(enhancement_owner, source_bill)
        monkeypatch.setattr("apps.legislation.tasks.get_provider", lambda _: Provider())
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run, attempt.pk, attempt.dispatch_token)
            try:
                assert started.wait(10)
                second = pool.submit(run, attempt.pk, attempt.dispatch_token)
                assert second.result(timeout=10)["status"] == "not_claimed"
            finally:
                release.set()
            assert first.result(timeout=10)["status"] == "succeeded"
        attempt.refresh_from_db()
        assert calls == ["generation", "synopsis"]
        assert BillEnhancementStep.objects.filter(attempt=attempt).count() == 2
        assert attempt.enhancement.published_attempt_id == attempt.id
        assert attempt.total_tokens == 30
