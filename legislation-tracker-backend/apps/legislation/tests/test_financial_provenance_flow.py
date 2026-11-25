"""Financial recovery publishes through real mixed-source preflight and worker."""

import copy

import pytest
from django.test import override_settings
from jsonschema import ValidationError
from rest_framework.test import APIClient

from apps.legislation.enhancements.providers.base import ProviderResult, ProviderUsage
from apps.legislation.enhancements.reader_cache import call_identity
from apps.legislation.enhancements.reader_capacity import fits
from apps.legislation.enhancements.reader_citations import citation_passages
from apps.legislation.enhancements.reader_discovery import validate_source_review
from apps.legislation.enhancements.reader_facts import factual_record_ids
from apps.legislation.enhancements.source_packet import build_enhancement_preflight
from apps.legislation.models import BillContract, EvidenceSpan
from apps.legislation.tasks import run_bill_enhancement_attempt
from apps.legislation.tests.test_enhancement_service import _valid_credential
from apps.legislation.tests.test_large_bill_planning_regression import _stored_document
from apps.legislation.tests.test_large_bill_staged_flow import (
    GRANT,
    RecordedModel,
    _confirmation,
    _cross_section_source,
)


class FinancialModel(RecordedModel):
    def __init__(self):
        super().__init__()
        self.summary_inputs = []

    def enhance_bill(self, *, request, **kwargs):
        targets = [
            (source, target)
            for source in request.source_snapshot
            for target in source.get("reader_targets", [])
        ]
        if not targets:
            return super().enhance_bill(request=request, **kwargs)
        assert fits(request.request_envelope)
        explanations = []
        for source, target in targets:
            quote = next(
                p for p in citation_passages(source) if "first fee" in p["text"]
            )
            explanations.append(
                {
                    "target_id": target["target_id"],
                    "status": "explained",
                    "text": "Applicants must pay the first fee instead of the second fee.",
                    "unresolved_reason": None,
                    "source_quotes": [
                        {
                            "source_ref": source["source_ref"],
                            "quote_id": quote["quote_id"],
                        }
                    ],
                }
            )
        key, _ = call_identity(request)
        assert key not in [call[1] for call in self.calls]
        self.calls.append(("target", key, request))
        return ProviderResult(
            {"schema_version": "1.4", "summary": [], "explanations": explanations},
            ProviderUsage(10, 5, 15),
            f"offline-{len(self.calls)}",
            "test",
        )

    def _map(self, request):
        output = super()._map(request)
        facts = {r["record_id"]: r for r in output.get("factual_records", [])}
        for source in request.source_snapshot:
            owned = source.get("review_quote_ids")
            quotes = []
            for passage in citation_passages(source):
                qid = passage["quote_id"]
                if (
                    not qid
                    or (owned is not None and qid not in owned)
                    or "first fee" not in passage["text"]
                ):
                    continue
                record_id = f"{source['source_ref']}:{qid}"
                quotes.append({"source_ref": source["source_ref"], "quote_id": qid})
                output["policy_checks"][record_id] = "explained"
                if record_id in facts:
                    facts[record_id]["claims"] = [
                        {
                            "actor": "Applicants",
                            "action": "Pay the first fee instead of the second fee",
                            "modality": "required",
                            "affected_people": [],
                            "timing": [],
                            "money": [],
                            "conditions": None,
                            "exceptions": [],
                            "evidence_ids": [record_id],
                        }
                    ]
            if quotes:
                output["policy_changes"].append(
                    {
                        "title": "Pay the first fee",
                        "text": "Applicants must pay the first fee instead of the second fee.",
                        "source_quotes": quotes,
                    }
                )
        # Deliberately omit the known fee from the financial inventory. Its
        # original NLP evidence must be recovered before dependency review.
        return output

    def _dependency(self, request):
        output = super()._dependency(request)
        for item_id, item in output["items"].items():
            if item_id.startswith("financial_items:") and len(item["text"]) > 1600:
                item["text"] = None
        return output

    def _summary(self, request):
        packet = request.request_envelope["source_packet"]
        self.summary_inputs.extend(copy.deepcopy(packet["validated_changes"]))
        quotes = [
            {"source_ref": source["source_ref"], "quote_id": passage["quote_id"]}
            for source in packet["sources"]
            for passage in source["citation_passages"]
            if passage["quote_id"] and "first fee" in passage["text"]
        ]
        if not quotes:
            return super()._summary(request)
        assert any(call[0] == "dependency" for call in self.calls)
        return {
            "schema_version": "1.4",
            "explanations": [],
            "summary": [
                {
                    "text": "Applicants must pay the first fee instead of the second fee.",
                    "source_quotes": quotes[:1],
                }
            ],
        }


@pytest.mark.django_db(transaction=True)
def test_real_worker_retains_financial_provenance_from_separate_target_sources(
    tmp_path, enhancement_owner, enhancement_settings, monkeypatch
):
    model = FinancialModel()
    monkeypatch.setattr("apps.legislation.tasks.get_provider", lambda _: model)

    def forbid_network(*args, **kwargs):
        pytest.fail("The financial provenance regression attempted a live API call")

    monkeypatch.setattr("httpx.Client.send", forbid_network)
    monkeypatch.setattr("requests.sessions.Session.request", forbid_network)
    fee_text = (
        "Applicants must pay the first fee instead of the second fee under section 2 of this Act. "
        + " ".join(
            f"Applicants in category {i} must pay the first fee instead of the second fee."
            for i in range(80)
        )
    )
    raw = _cross_section_source().replace(GRANT.encode(), fee_text.encode())
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
        document = _stored_document(raw, tmp_path, number="S 99996")
        start = document.extracted_text.index(fee_text)
        contract = BillContract.objects.create(
            bill=document.bill,
            document=document,
            contract_hash="financial-provenance",
            schema_version="2.1-legal-nlp",
            contract_json={
                "schema_version": "2.1-legal-nlp",
                "line_items": [],
                "definitions": [],
                "timeline_items": [],
                "financial_items": [
                    {
                        "id": "fee-rule",
                        "financial_action": "fee",
                        "display_text": "Applicants pay the first fee.",
                        "evidence_paths": ["financial_items[0].display_text"],
                    }
                ],
            },
        )
        EvidenceSpan.objects.create(
            bill=document.bill,
            document=document,
            contract=contract,
            field_path="financial_items[0].display_text",
            start_char=start,
            end_char=start + len(fee_text),
            quoted_text=fee_text,
        )
        document.bill.latest_contract = contract
        document.bill.save(update_fields=["latest_contract"])
        _valid_credential(enhancement_owner)
        plan = build_enhancement_preflight(document.bill, reuse_publication=False)
        scans = [s for s in plan.source_snapshot if s.get("discovery_source")]
        targets = [s for s in plan.source_snapshot if s.get("reader_targets")]
        assert targets and all(not s.get("discovery_source") for s in targets)
        assert all(not s.get("reader_targets") for s in scans)
        owner = next(s for s in scans if s["start_char"] <= start < s["end_char"])
        assert 1600 < len(owner["quoted_text"].encode()) < 8000
        assert owner.get("deferred_context_source_refs")
        assert all(fits(batch.request_envelope) for batch in plan.reader_batches)

        attempt = _confirmation(client, document.bill)
        model.attempt = attempt
        outcome = run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)
        attempt.refresh_from_db()
        attempt.enhancement.refresh_from_db()
        assert outcome["status"] == "succeeded", attempt.failure_detail
        review = attempt.enhancement.result_json["source_review"]
        recovered = next(
            item for item in review["financial_items"] if len(item["text"]) > 1600
        )
        assert recovered["text"] == fee_text
        assert all(
            q["source_ref"] == owner["source_ref"] for q in recovered["source_quotes"]
        )
        assert any(item["text"] == fee_text for item in model.summary_inputs)
        assert len(review["factual_records"]) == len(factual_record_ids(scans))
        assert {r["record_id"] for r in review["factual_records"]} == set(
            factual_record_ids(plan.source_snapshot)
        )
        validate_source_review(review, plan.source_snapshot)

        tampered = copy.deepcopy(review)
        next(item for item in tampered["financial_items"] if len(item["text"]) > 1600)[
            "text"
        ] += " An unsupported additional fee is required."
        with pytest.raises(ValidationError):
            validate_source_review(tampered, plan.source_snapshot)
