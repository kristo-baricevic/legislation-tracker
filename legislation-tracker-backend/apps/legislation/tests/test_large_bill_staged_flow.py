"""Exercise bounded dependency review through the real enhancement lifecycle.

Only the upstream model is simulated. Confirmation, source planning, database
reservations, worker recovery, citation validation and publication are real.
"""

import copy
import hashlib
import os
import subprocess
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import connection
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.legislation.enhancements.providers.base import (
    ProviderError,
    ProviderResult,
    ProviderUsage,
)
from apps.legislation.enhancements.reader_cache import call_identity
from apps.legislation.enhancements.reader_capacity import fits
from apps.legislation.enhancements.reader_citations import citation_passages
from apps.legislation.enhancements.reader_discovery import (
    money_candidates,
    policy_passages,
)
from apps.legislation.enhancements.source_packet import build_enhancement_preflight
from apps.legislation.models import BillEnhancementAttempt, BillEnhancementCallCache
from apps.legislation.tasks import (
    recover_stale_bill_enhancement_attempts,
    run_bill_enhancement_attempt,
)
from apps.legislation.tests.test_enhancement_service import _valid_credential
from apps.legislation.tests.test_large_bill_planning_regression import _stored_document

GRANT = "The Secretary shall award grants to qualifying schools under section 2 of this Act."
MATCHING = "A grant under section 1 of this Act is subject to a non-Federal matching contribution equal to 50 percent of the grant amount."


def _cross_section_source():
    directory = "".join(
        f'<paragraph id="directory-{i}"><enum>({i})</enum><text>'
        f"Program directory entry {i} describes a public administrative category. "
        + "This directory provides background administrative descriptions. " * 8
        + "</text></paragraph>"
        for i in range(1, 261)
    )
    return (
        '<bill><legis-body><section id="grants"><enum>1.</enum><header>School grants</header>'
        f"<text>{GRANT}</text></section>"
        '<section id="requirements"><enum>2.</enum><header>Grant requirements</header>'
        '<subsection id="directory"><enum>(a)</enum><header>Directory</header>'
        f"{directory}</subsection>"
        '<subsection id="matching"><enum>(b)</enum><header>Matching contribution</header>'
        f"<text>{MATCHING}</text></subsection>"
        "</section></legis-body></bill>"
    ).encode()


def _quote(record_id):
    source_ref, quote_id = record_id.split(":", 1)
    return {"source_ref": source_ref, "quote_id": quote_id}


def _claim(record_id, *, matching=False):
    return {
        "actor": "Grant recipients" if matching else "The Secretary",
        "action": (
            "Provide a non-Federal matching contribution"
            if matching
            else "Award grants to qualifying schools"
        ),
        "modality": "required",
        "money": (
            [
                {
                    "amount": "50",
                    "currency": None,
                    "measure": "percent",
                    "comparator": None,
                    "purpose": "non-Federal matching contribution",
                    "period": None,
                    "base": "grant amount",
                }
            ]
            if matching
            else []
        ),
        "conditions": None,
        "exceptions": [],
        "affected_people": ["qualifying schools"],
        "timing": [],
        "evidence_ids": [record_id],
    }


class RecordedModel:
    def __init__(self, *, malformed=False, unresolved=False):
        self.malformed = malformed
        self.unresolved = unresolved
        self.calls = []
        self.attempt = None
        self.invalid_calls = set()
        self.fault = None

    def enhance_bill(self, *, request, **kwargs):
        assert fits(request.request_envelope), "Worker dispatched an oversized request"
        key, _ = call_identity(request)
        assert key in self.invalid_calls or key not in [
            call[1] for call in self.calls
        ], "A validated request was charged twice"
        envelope = request.request_envelope
        if envelope.get("dependency_review"):
            kind, output = "dependency", self._dependency(request)
        elif envelope.get("source_review"):
            kind, output = "map", self._map(request)
        else:
            kind, output = "summary", self._summary(request)
        self.invalid_calls.discard(key)
        if (kind == "map" and self.malformed) or (
            kind == "dependency" and self.unresolved
        ):
            self.invalid_calls.add(key)
        self.calls.append((kind, key, request))
        if self.fault and kind == "dependency":
            fault, self.fault = self.fault, None
            raise ProviderError(
                "outcome_unknown" if fault == "timeout" else "invalid_output",
                outcome_unknown=fault == "timeout",
                validation_code=(
                    "provider_timeout"
                    if fault == "timeout"
                    else "provider_output_limit"
                ),
                usage=(
                    ProviderUsage() if fault == "timeout" else ProviderUsage(10, 5, 15)
                ),
            )
        return ProviderResult(
            output, ProviderUsage(10, 5, 15), f"offline-{len(self.calls)}", "test"
        )

    def _map(self, request):
        policies, financial, records = [], [], []
        explained = set()
        for source in request.source_snapshot:
            owned = source.get("review_quote_ids")
            for passage in citation_passages(source):
                qid = passage["quote_id"]
                if not qid or (owned is not None and qid not in owned):
                    continue
                record_id = f"{source['source_ref']}:{qid}"
                record = {
                    "record_id": record_id,
                    "claims": [],
                    "definitions": [],
                    "references": [],
                }
                matching = (
                    "matching contribution equal to 50 percent" in passage["text"]
                )
                grant = "Secretary shall award grants" in passage["text"]
                if grant or matching:
                    explained.add(record_id)
                    record["claims"] = [_claim(record_id, matching=matching)]
                    record["references"] = [
                        {
                            "text": (
                                "section 1 of this Act"
                                if matching
                                else "section 2 of this Act"
                            ),
                            "target": (
                                "section 1 of this Act"
                                if matching
                                else "section 2 of this Act"
                            ),
                            "relation": "condition",
                            "evidence_ids": [record_id],
                        }
                    ]
                    text = (
                        "Grant recipients must provide a non-Federal matching contribution equal to 50 percent of the grant amount."
                        if matching
                        else "The Secretary must award grants to qualifying schools under the requirements in section 2."
                    )
                    policies.append(
                        {
                            "title": (
                                "Match school grants"
                                if matching
                                else "Award school grants"
                            ),
                            "text": text,
                            "source_quotes": [_quote(record_id)],
                        }
                    )
                    if matching:
                        financial.append(
                            {
                                "label": "School grant matching",
                                "amount_display": "50 percent non-Federal match",
                                "text": text,
                                "fiscal_years": [],
                                "source_quotes": [_quote(record_id)],
                            }
                        )
                if source.get("factual_map"):
                    records.append(record)
        result = {
            "financial_items": financial,
            "additional_changes": [],
            "money_checks": {
                key: "financial" if key in explained else "not_financial"
                for key in money_candidates(request.source_snapshot)
            },
            "policy_changes": policies,
            "policy_checks": {
                key: "explained" if key in explained else "context"
                for key in policy_passages(request.source_snapshot)
            },
        }
        if any(source.get("factual_map") for source in request.source_snapshot):
            result["factual_records"] = [] if self.malformed else records
        return result

    def _dependency(self, request):
        envelope = request.request_envelope
        packet = envelope["source_packet"]
        metadata = envelope["dependency_review"]
        rows = packet["review_items"]
        items = {item_id: copy.deepcopy(row["value"]) for item_id, row in rows.items()}
        checks = {}
        for record in packet["dependency_records"]:
            record_id = record["record_id"]
            matching = any(
                money.get("amount") == "50"
                for claim in record["claims"]
                for money in claim["money"]
            )
            targets = [
                item_id
                for item_id, value in items.items()
                if "award grants" in value.get("text", "").lower()
            ]
            if self.unresolved:
                checks[record_id] = {
                    "status": "unresolved",
                    "item_ids": [],
                    "reason": "The relation between the supplied provisions is ambiguous.",
                }
            elif matching and targets:
                checks[record_id] = {
                    "status": "applies",
                    "item_ids": targets,
                    "reason": None,
                }
                for item_id in targets:
                    items[item_id][
                        "text"
                    ] = "The Secretary must award grants to qualifying schools, requiring a non-Federal matching contribution equal to 50 percent of the grant amount."
                    citation = _quote(record_id)
                    if citation not in items[item_id]["source_quotes"]:
                        items[item_id]["source_quotes"].append(citation)
            else:
                checks[record_id] = {
                    "status": "not_applicable",
                    "item_ids": [],
                    "reason": "This record does not add a condition to these items.",
                }
        return {"page_id": metadata["page_id"], "record_checks": checks, "items": items}

    def _summary(self, request):
        assert any(
            call[0] == "dependency" for call in self.calls
        ), "Summary preceded dependency review"
        assert self.attempt is not None
        pending_maps = [
            unit
            for unit in self.attempt.work_units.filter(status="pending")
            if unit.request_json["envelope"].get("source_review")
        ]
        assert not pending_maps, "Summary preceded source-map completion"
        quotes = [
            {"source_ref": source["source_ref"], "quote_id": passage["quote_id"]}
            for source in request.request_envelope["source_packet"]["sources"]
            for passage in source["citation_passages"]
            if passage["quote_id"] and "50 percent" in passage["text"]
        ]
        assert quotes
        return {
            "schema_version": "1.4",
            "explanations": [],
            "summary": [
                {
                    "text": "School grants require a non-Federal contribution equal to 50 percent of the grant amount.",
                    "source_quotes": quotes,
                }
            ],
        }


def _confirmation(client, bill, enhancement_id=None):
    url = f"/api/bills/{bill.pk}/enhancements/"
    estimate = client.get(url + "estimate/")
    assert estimate.status_code == 200, estimate.data
    assert estimate.data["can_enhance"], estimate.data
    body = {
        key: estimate.data[key]
        for key in ("source_fingerprint", "request_fingerprint", "credential_revision")
    }
    if "rerun_after" in estimate.data:
        body["rerun_after"] = estimate.data["rerun_after"]
    response = client.post(
        url if enhancement_id is None else f"{url}{enhancement_id}/retry/",
        body,
        format="json",
    )
    assert response.status_code == 202, response.data
    return (
        BillEnhancementAttempt.objects.filter(enhancement_id=response.data["id"])
        .order_by("-sequence")
        .first()
    )


class SimulatedWorkerCrash(BaseException):
    pass


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "mode",
    [
        "complete",
        "crash",
        "malformed",
        "unresolved",
        "truncated",
        "timeout",
        "local_depth",
    ],
)
def test_large_dependency_finishes_or_reports_real_gap_without_repaying(
    tmp_path, enhancement_owner, enhancement_settings, monkeypatch, mode, request
):
    from apps.legislation.enhancements.reader_work import ReaderWorkPlan

    model = RecordedModel(
        malformed=mode == "malformed", unresolved=mode == "unresolved"
    )
    model.fault = mode if mode in {"timeout", "truncated"} else None
    monkeypatch.setattr("apps.legislation.tasks.get_provider", lambda _: model)

    if mode == "local_depth":
        from apps.legislation.enhancements import reader_steps

        validate = reader_steps._validate_response

        def fail_first_validation(output, request):
            if not model.invalid_calls:
                key, _ = call_identity(request)
                model.invalid_calls.add(key)
                monkeypatch.setattr(reader_steps, "_validate_response", validate)
                raise RecursionError("local schema validation exhausted")
            return validate(output, request)

        monkeypatch.setattr(reader_steps, "_validate_response", fail_first_validation)

    def forbid_network(*args, **kwargs):
        pytest.fail("The staged integration test attempted a real HTTP request")

    monkeypatch.setattr("httpx.Client.send", forbid_network)
    monkeypatch.setattr("requests.sessions.Session.request", forbid_network)
    client = APIClient()
    client.force_authenticate(enhancement_owner)
    with (
        enhancement_settings,
        override_settings(
            STORAGES={
                "default": {
                    "BACKEND": "django.core.files.storage.FileSystemStorage",
                    "OPTIONS": {"location": tmp_path},
                }
            },
            LLM_READER_OWNED_TOKEN_TARGET=0,
            LLM_SOURCE_FIRST_ENABLED=False,
            LLM_READER_MAX_CALLS=0,
            LLM_READER_CALLS_PER_DELIVERY=500,
        ),
    ):
        document = _stored_document(_cross_section_source(), tmp_path, number="S 99997")
        assert len(document.extracted_text.encode()) > 120_000
        _valid_credential(enhancement_owner)
        plan = build_enhancement_preflight(document.bill, reuse_publication=False)
        deferred = [
            source
            for source in plan.source_snapshot
            if source.get("deferred_context_source_refs")
        ]
        assert deferred, "Fixture no longer exercises an oversized required dependency"
        assert all(fits(batch.request_envelope) for batch in plan.reader_batches)
        attempt = _confirmation(client, document.bill)
        model.attempt = attempt

        if mode == "crash":
            complete = ReaderWorkPlan.complete
            crashed = False

            def crash_after_durable_response(self, key, output):
                nonlocal crashed
                if not crashed and "factual_records" in output:
                    crashed = True
                    assert BillEnhancementCallCache.objects.filter(
                        status="validated"
                    ).exists()
                    raise SimulatedWorkerCrash()
                return complete(self, key, output)

            monkeypatch.setattr(
                ReaderWorkPlan, "complete", crash_after_durable_response
            )
            with pytest.raises(SimulatedWorkerCrash):
                run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)
            first_key = model.calls[0][1]
            attempt.refresh_from_db()
            assert attempt.steps.filter(status="validated").count() == 1
            attempt.lease_expires_at = timezone.now() - timedelta(seconds=1)
            attempt.save(update_fields=["lease_expires_at"])
            recover_stale_bill_enhancement_attempts()
            attempt = _confirmation(client, document.bill, attempt.enhancement_id)
            model.attempt = attempt

        outcome = run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)
        attempt.refresh_from_db()
        attempt.enhancement.refresh_from_db()
        if mode == "timeout":
            assert outcome["status"] == "outcome_unknown"
            assert (
                BillEnhancementCallCache.objects.filter(status="dispatching").count()
                == 1
            )
            assert sum(stage == "dependency" for stage, _, _ in model.calls) == 1
            count = len(model.calls)
            url = f"/api/bills/{document.bill_id}/enhancements/"
            estimate = client.get(url + "estimate/").data
            assert estimate["unavailable_reason"] == "reconciliation_required"
            assert (
                run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)[
                    "status"
                ]
                == "not_claimed"
            )
            print(
                "RECOVERY",
                mode,
                dict(Counter(stage for stage, _, _ in model.calls)),
                "retry_calls",
                len(model.calls) - count,
            )
            assert Counter(stage for stage, _, _ in model.calls) == {
                "map": 84,
                "dependency": 1,
            }
            assert len(model.calls) == count
            return
        if mode in {"malformed", "unresolved", "local_depth"}:
            assert outcome["status"] == "failed", attempt.failure_detail
            assert attempt.enhancement.result_json is None
            assert not any(call[0] == "summary" for call in model.calls)
            assert any(call[0] == "map" for call in model.calls)
            if mode == "unresolved":
                assert any(call[0] == "dependency" for call in model.calls)
                assert attempt.failure_detail["code"] == "reader_coverage_incomplete"
            elif mode == "local_depth":
                step = attempt.steps.get()
                row = BillEnhancementCallCache.objects.get(pk=step.request_fingerprint)
                assert (step.status, row.status) == ("failed", "failed")
                assert step.response_id == row.response_id == "offline-1"
                assert step.total_tokens == 15
            else:
                assert not any(call[0] == "dependency" for call in model.calls)
                assert attempt.failure_detail["code"] in {
                    "schema_minItems",
                    "reader_coverage_incomplete",
                }
            completed = [key for stage, key, _ in model.calls if stage == "map"]
            model.unresolved = model.malformed = False
            previous_count = len(model.calls)
            attempt = _confirmation(client, document.bill, attempt.enhancement_id)
            model.attempt = attempt
            outcome = run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)
            attempt.refresh_from_db()
            attempt.enhancement.refresh_from_db()
            if mode == "unresolved":
                assert all(
                    key not in completed
                    for stage, key, _ in model.calls[previous_count:]
                )

        assert outcome["status"] == "succeeded", attempt.failure_detail
        result = attempt.enhancement.result_json
        assert "50 percent" in result["summary"][0]["text"]
        policies = result["source_review"].get(
            "policy_drafts", result["source_review"].get("policy_changes", [])
        )
        grant = next(
            item for item in policies if "award grants" in item["text"].lower()
        )
        assert "50 percent" in grant["text"]
        assert any(
            "matching contribution equal to 50 percent" in quote["quote"]
            for quote in grant["source_quotes"]
        )
        latest = client.get(f"/api/bills/{document.bill_id}/enhancements/latest/")
        assert latest.status_code == 200
        assert [
            (s["text"], s["source_quotes"])
            for s in latest.data["active_reader"]["result"]["summary"]
        ] == [(s["text"], s["source_quotes"]) for s in result["summary"]]
        if mode == "complete" and os.environ.get("STAGED_READER_CLIENT"):
            server = request.getfixturevalue("live_server")
            login = APIClient().post(
                "/api/auth/session/",
                {"email": enhancement_owner.email, "password": "password123"},
                format="json",
            )
            assert login.status_code == 200
            cookies = "; ".join(
                f"{name}={cookie.value}" for name, cookie in login.cookies.items()
            )
            script = (
                Path(__file__).resolve().parents[4]
                / "legislation-tracker-client"
                / "scripts"
                / "check-staged-reader.cjs"
            )
            subprocess.run(
                ["node", str(script), server.url, str(document.bill_id)],
                check=True,
                env={**os.environ, "STAGED_READER_SESSION": cookies},
                timeout=90,
            )
        if mode == "truncated":
            assert (
                attempt.steps.filter(
                    status="failed", diagnostics__code="provider_output_limit"
                ).count()
                == 1
            )
        assert sum(1 for _ in model.calls) == sum(
            a.steps.count() for a in attempt.enhancement.attempts.all()
        )
        stages = [call[0] for call in model.calls]
        assert stages.index("dependency") > max(
            i for i, stage in enumerate(stages) if stage == "map"
        )
        assert stages.index("summary") > max(
            i for i, stage in enumerate(stages) if stage == "dependency"
        )
        assert not attempt.work_units.exclude(
            status__in=["validated", "expanded"]
        ).exists()
        assert Counter(stages) == {
            "map": 85 if mode in {"malformed", "local_depth"} else 84,
            "dependency": {"unresolved": 20, "truncated": 21}.get(mode, 19),
            "summary": 1,
        }
        if mode in {"malformed", "unresolved", "local_depth"}:
            assert len(stages) - previous_count == (20 if mode == "unresolved" else 104)
        print(
            "RECOVERY",
            mode,
            dict(Counter(stages)),
            "retry_calls",
            (
                len(stages) - previous_count
                if mode in {"malformed", "unresolved", "local_depth"}
                else None
            ),
        )
        if mode in {"malformed", "unresolved", "local_depth"}:
            assert len(model.calls) > previous_count
            return
        assert all(
            count == 1 for count in Counter(call[1] for call in model.calls).values()
        )
        if mode == "crash":
            assert sum(call[1] == first_key for call in model.calls) == 1


@pytest.mark.django_db(transaction=True)
def test_pinned_pg_confirmation(tmp_path, enhancement_settings, enhancement_owner):
    from apps.legislation.tasks import _claim_enhancement_attempt

    if connection.vendor != "postgresql" or not os.environ.get("LARGE_BILL_XML_PATH"):
        pytest.skip("requires PostgreSQL and pinned S.1071 XML")
    client = APIClient()
    client.force_authenticate(enhancement_owner)
    with (
        enhancement_settings,
        override_settings(
            STORAGES={
                "default": {
                    "BACKEND": "django.core.files.storage.FileSystemStorage",
                    "OPTIONS": {"location": tmp_path},
                }
            },
            LLM_READER_OWNED_TOKEN_TARGET=0,
            LLM_READER_MAX_CALLS=0,
            LLM_ENHANCEMENT_MAX_REQUEST_BYTES=120000,
            LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS=100000,
            LLM_READER_MAX_OUTPUT_TOKENS=24000,
        ),
    ):
        raw = Path(os.environ["LARGE_BILL_XML_PATH"]).read_bytes()
        assert (
            hashlib.sha256(raw).hexdigest()
            == "69702b764640a8bd86dbc23717cd3161b091668792d6b066a55a42d8e3a64299"
        )
        doc = _stored_document(raw, tmp_path)
        _valid_credential(enhancement_owner)
        url = f"/api/bills/{doc.bill_id}/enhancements/"
        estimate = client.get(url + "estimate/")
        assert estimate.status_code == 200
        assert estimate.data["can_enhance"]
        body = {
            key: estimate.data[key]
            for key in (
                "source_fingerprint",
                "request_fingerprint",
                "credential_revision",
            )
        }
        response = client.post(url, body, format="json")
        assert response.status_code == 202, response.data
        attempt = BillEnhancementAttempt.objects.get(enhancement_id=response.data["id"])
        budget = attempt.enhancement.source_manifest_json["budget"]
        assert estimate.data["aggregate_budget"] == budget
        assert attempt.status == "pending" and not attempt.steps.exists()
        assert 0 < budget["planned_calls"] < budget["maximum_calls"] < 20000
        assert (
            attempt.estimated_input_tokens
            == budget["maximum_input"]
            == estimate.data["estimated_input_tokens"]
        )
        assert _claim_enhancement_attempt(attempt.pk, attempt.dispatch_token)
        attempt.refresh_from_db()
        assert attempt.status == "running"
        print("S1071_AUTHORIZED", budget)


@pytest.mark.django_db
def test_aggregate_token_receipts_survive_attempt_completion(
    source_bill, enhancement_owner, enhancement_settings
):
    from apps.legislation.tasks import _finish_enhancement_attempt

    from .test_dependency_cache_identity import _running_attempt

    with enhancement_settings:
        attempt = _running_attempt(enhancement_owner, source_bill)
        usage = ProviderUsage(2**31, 2**31, 2**32)
        assert _finish_enhancement_attempt(
            attempt_id=attempt.pk,
            run_token=attempt.run_token,
            attempt_status="failed",
            failure_category="invalid_output",
            usage=usage,
        )
        attempt.refresh_from_db()
        for row in (attempt, attempt.enhancement):
            assert (row.input_tokens, row.output_tokens, row.total_tokens) == (
                2**31,
                2**31,
                2**32,
            )
