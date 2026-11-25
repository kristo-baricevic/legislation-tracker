"""Exercise bounded dependency review through the real enhancement lifecycle.

Only the upstream model is simulated. Confirmation, source planning, database
reservations, worker recovery, citation validation and publication are real.
"""

import copy
from collections import Counter
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.legislation.enhancements.providers.base import ProviderResult, ProviderUsage
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
        "action": "Provide a non-Federal matching contribution"
        if matching
        else "Award grants to qualifying schools",
        "modality": "required",
        "money": [
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
        else [],
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

    def enhance_bill(self, *, request, **kwargs):
        assert fits(request.request_envelope), "Worker dispatched an oversized request"
        key, _ = call_identity(request)
        assert key not in [call[1] for call in self.calls], (
            "A validated request was charged twice"
        )
        envelope = request.request_envelope
        if envelope.get("dependency_review"):
            kind, output = "dependency", self._dependency(request)
        elif envelope.get("source_review"):
            kind, output = "map", self._map(request)
        else:
            kind, output = "summary", self._summary(request)
        self.calls.append((kind, key, request))
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
                            "text": "section 1 of this Act"
                            if matching
                            else "section 2 of this Act",
                            "target": "section 1 of this Act"
                            if matching
                            else "section 2 of this Act",
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
                            "title": "Match school grants"
                            if matching
                            else "Award school grants",
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
                    items[item_id]["text"] = (
                        "The Secretary must award grants to qualifying schools, requiring a non-Federal matching contribution equal to 50 percent of the grant amount."
                    )
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
        assert any(call[0] == "dependency" for call in self.calls), (
            "Summary preceded dependency review"
        )
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
@pytest.mark.parametrize("mode", ["complete", "crash", "malformed", "unresolved"])
def test_large_dependency_finishes_or_reports_real_gap_without_repaying(
    tmp_path, enhancement_owner, enhancement_settings, monkeypatch, mode
):
    from apps.legislation.enhancements.reader_work import ReaderWorkPlan

    model = RecordedModel(
        malformed=mode == "malformed", unresolved=mode == "unresolved"
    )
    monkeypatch.setattr("apps.legislation.tasks.get_provider", lambda _: model)

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
        if mode in {"malformed", "unresolved"}:
            assert outcome["status"] == "failed", attempt.failure_detail
            assert attempt.enhancement.result_json is None
            assert not any(call[0] == "summary" for call in model.calls)
            assert any(call[0] == "map" for call in model.calls)
            if mode == "unresolved":
                assert any(call[0] == "dependency" for call in model.calls)
                assert attempt.failure_detail["code"] == "reader_coverage_incomplete"
            else:
                assert not any(call[0] == "dependency" for call in model.calls)
                assert attempt.failure_detail["code"] in {
                    "schema_minItems",
                    "reader_coverage_incomplete",
                }
            return

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
        assert all(
            count == 1 for count in Counter(call[1] for call in model.calls).values()
        )
        if mode == "crash":
            assert sum(call[1] == first_key for call in model.calls) == 1
