# ruff: noqa: F401, F811
import pytest
from django.test import override_settings

from apps.legislation.enhancements.providers.base import (
    ProviderError,
    ProviderResult,
    ProviderUsage,
)
from apps.legislation.enhancements.service import confirmation_fingerprint
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
        "publication_source_changed",
        "model_limit_changed",
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
            if mode == "model_limit_changed":
                from django.conf import settings

                settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS = 2048
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

    with (
        enhancement_settings,
        override_settings(
            LLM_SOURCE_FIRST_ENABLED=True, LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS=8000
        ),
    ):
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
        from unittest.mock import Mock

        from apps.legislation import tasks
        from apps.legislation.enhancements import source_first_preflight

        build_graph = Mock(wraps=source_first_preflight.build_source_graph)
        pack_plan = Mock(wraps=source_first_preflight._plan_built_graph)
        monkeypatch.setattr(source_first_preflight, "build_source_graph", build_graph)
        monkeypatch.setattr(source_first_preflight, "_plan_built_graph", pack_plan)
        if mode == "publication_source_changed":
            finish = tasks._finish_enhancement_attempt

            def change_before_publication(**kwargs):
                source_bill.documents.update(
                    extracted_text="SEC. 1. The Secretary must publish a different report."
                )
                return finish(**kwargs)

            monkeypatch.setattr(
                tasks, "_finish_enhancement_attempt", change_before_publication
            )
        outcome = run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)
        attempt.refresh_from_db()
        attempt.enhancement.refresh_from_db()
        if mode == "success":
            assert outcome["status"] == "succeeded"
            assert attempt.enhancement.published_attempt_id == attempt.id
            assert attempt.enhancement.result_completeness == "complete"
            assert attempt.total_tokens == 30
            assert calls == ["generation", "synopsis"]
            build_graph.assert_called_once()
            pack_plan.assert_called_once()
        else:
            assert outcome["status"] != "succeeded"
            assert calls == (
                ["generation", "synopsis"]
                if mode == "publication_source_changed"
                else ["generation"]
            )
            assert attempt.enhancement.published_attempt_id is None
        assert (
            run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)["status"]
            == "not_claimed"
        )


@pytest.mark.django_db
def test_source_first_reuse_rechecks_stored_xml_without_realigning(
    source_bill,
    enhancement_owner,
    enhancement_settings,
    settings,
    tmp_path,
    monkeypatch,
):
    from unittest.mock import Mock

    from apps.ingestion.document_download import extract_document_text
    from apps.legislation.enhancements import xml_sections
    from apps.legislation.tasks import _worker_preflight

    settings.STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": tmp_path},
        }
    }
    raw = b'<bill><legis-body><section id="one"><enum>1.</enum><text>The Secretary shall publish a report.</text></section></legis-body></bill>'
    doc = source_bill.documents.get()
    doc.object_storage_key, doc.content_hash = "bill.xml", ""
    doc.extracted_text = extract_document_text(
        raw, "application/xml", doc.object_storage_key
    )
    doc.save()
    xml = tmp_path / doc.object_storage_key
    xml.write_bytes(raw)
    with enhancement_settings, override_settings(LLM_SOURCE_FIRST_ENABLED=True):
        attempt = _pending_attempt(enhancement_owner, source_bill)
        align = Mock(wraps=xml_sections.xml_boundaries)
        monkeypatch.setattr(xml_sections, "xml_boundaries", align)
        prepared, _, failure = _worker_preflight(attempt)
        assert failure is None
        assert _worker_preflight(attempt, cached_preflight=prepared)[0] is prepared
        align.assert_called_once()
        xml.write_bytes(raw.replace(b'id="one"', b'id="two"'))
        assert (
            _worker_preflight(attempt, cached_preflight=prepared)[2]
            == "source_unavailable"
        )
        xml.unlink()
        assert (
            _worker_preflight(attempt, cached_preflight=prepared)[2]
            == "source_unavailable"
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("rerun", [False, True])
def test_partial_retry_promotes_without_regenerating_accepted_units(
    enhancement_owner, enhancement_settings, source_bill, monkeypatch, rerun
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
        if rerun:
            from rest_framework.test import APIClient

            client = APIClient()
            client.force_authenticate(enhancement_owner)
            url = f"/api/bills/{source_bill.pk}/enhancements/"
            keys = (
                "source_fingerprint",
                "request_fingerprint",
                "credential_revision",
                "rerun_after",
            )
            phase[0] = 1
            run_bill_enhancement_attempt(first.pk, first.dispatch_token)
            published = first.enhancement_id
            estimate = client.get(url + "estimate/?rerun=1").data
            created = client.post(url, {k: estimate[k] for k in keys}, format="json")
            assert created.status_code == 202
            first = BillEnhancementAttempt.objects.get(
                enhancement_id=created.data["id"]
            )
            phase[0] = 0
        run_bill_enhancement_attempt(first.pk, first.dispatch_token)
        first.refresh_from_db()
        enhancement = first.enhancement
        assert enhancement.result_completeness == "partial"
        assert retry_allowed(first)
        prior = enhancement.result_json
        if rerun:
            latest = client.get(url + "latest/").data
            assert (latest["id"], latest["active_reader"]["id"]) == (
                enhancement.pk,
                published,
            )
            estimate = client.get(url + "estimate/").data
            assert estimate["matching_enhancement"]["id"] == enhancement.pk
        preflight = build_enhancement_preflight(source_bill, reuse_result=prior)
        confirmed = {
            "source_fingerprint": preflight.source_fingerprint,
            "request_fingerprint": confirmation_fingerprint(
                preflight, first.credential, enhancement.rerun_after
            ),
            **({"rerun_after": published} if rerun else {}),
            "credential_revision": first.credential_revision,
        }
        if not rerun:
            from apps.legislation.enhancements.service import EnhancementServiceError

            original = doc.extracted_text
            doc.extracted_text = original.replace(
                "publish a report", "publish a notice"
            )
            doc.save()
            with pytest.raises(EnhancementServiceError) as changed:
                retry_enhancement_attempt(
                    user=enhancement_owner,
                    bill=source_bill,
                    enhancement_id=enhancement.pk,
                    confirmed=confirmed,
                )
            assert (changed.value.code, changed.value.http_status) == (
                "preflight_changed",
                409,
            )
            assert enhancement.attempts.count() == 1
            doc.extracted_text = original
            doc.save()
        second = retry_enhancement_attempt(
            user=enhancement_owner,
            bill=source_bill,
            enhancement_id=enhancement.pk,
            confirmed=confirmed,
        ).attempt
        if rerun:
            assert estimate["request_fingerprint"] == confirmation_fingerprint(
                preflight, first.credential, published
            )
            assert second.reused_result_json == prior
        from apps.legislation.tasks import _worker_preflight

        prepared, _, failure = _worker_preflight(second)
        assert failure is None
        assert _worker_preflight(second, cached_preflight=prepared)[0] is prepared
        # A checkpoint reloads the attempt. Clearing the partial result changes
        # which units a fresh plan would dispatch under the prior confirmation.
        second.reused_result_json = None
        assert (
            _worker_preflight(second, cached_preflight=prepared)[2]
            == "source_unavailable"
        )
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
