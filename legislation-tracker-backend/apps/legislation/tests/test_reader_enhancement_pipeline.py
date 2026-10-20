# ruff: noqa: F401, F811
import pytest

from apps.legislation.models import BillContract, EvidenceSpan
from apps.legislation.enhancements.source_packet import build_enhancement_preflight, PreflightUnavailable
from apps.legislation.enhancements.reader_targets import snapshot_targets
from apps.legislation.enhancements.providers.base import ProviderResult, ProviderUsage
from apps.legislation.enhancements.serializers import enhancement_payload
from apps.legislation.tests.test_enhancement_tasks import _pending_attempt
from apps.legislation.tests.test_enhancement_service import enhancement_owner, enhancement_settings, source_bill
from apps.legislation.tasks import run_bill_enhancement_attempt


def install_reader(bill):
    document = bill.documents.get()
    text = document.extracted_text
    lines = [{"id": f"line-{i}", "display_text": "Publish a report within 90 days.",
              "evidence_paths": [f"line_items[{i}].display_text"]} for i in range(10)]
    c = BillContract.objects.create(bill=bill, document=document, contract_hash="reader-hash",
        schema_version="2.1-legal-nlp", contract_json={"schema_version": "2.1-legal-nlp",
            "line_items": lines, "financial_items": [], "definitions": [], "timeline_items": []})
    for i in range(10):
        EvidenceSpan.objects.create(bill=bill, document=document, contract=c,
            field_path=f"line_items[{i}].display_text", start_char=0, end_char=len(text), quoted_text=text)
    bill.latest_contract = c
    bill.save()
    return c


@pytest.mark.django_db
def test_reader_preflight_pins_contract_and_exposes_all_targets(source_bill, enhancement_settings):
    from django.test import override_settings
    c = install_reader(source_bill)
    with enhancement_settings:
        p = build_enhancement_preflight(source_bill)
        assert p.output_schema_version == "1.4"
        assert p.source_manifest["reader"]["selected_count"] == 10
        assert p.source_manifest["reader"]["unavailable_count"] == 0
        assert len(p.reader_batches) == 2
        # Shared enclosing text appears once per request, not once per target.
        assert len(p.reader_batches[0].source_snapshot) == 1
        assert len(snapshot_targets(p.reader_batches[0].source_snapshot)) == 8
        assert p.source_manifest["budget"]["maximum_calls"] == 3
        wire_source = p.request_envelope["source_packet"]["sources"][0]
        assert "citation_passages" in wire_source
        assert "quoted_text" not in wire_source  # Do not send the text twice.
        assert wire_source["citation_passages"][0]["quote_id"] == "p0001"
        c.contract_hash = "new-contract"
        c.save()
        assert build_enhancement_preflight(source_bill).source_fingerprint != p.source_fingerprint
        with override_settings(LLM_READER_MAX_CALLS=1), pytest.raises(PreflightUnavailable):
            build_enhancement_preflight(source_bill)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("mode", ["success", "missing", "revoked", "changed"])
def test_reader_pipeline_publishes_only_complete_current_targets(
    source_bill, enhancement_owner, enhancement_settings, monkeypatch, mode
):
    from apps.accounts.models import LLMCredential
    c = install_reader(source_bill)
    requests = []
    class Provider:
        def enhance_bill(self, *, request, **kwargs):
            requests.append(request)
            targets = snapshot_targets(request.source_snapshot)
            output = {"schema_version": "1.4", "summary": [], "explanations": []}
            if not targets:
                s = request.source_snapshot[0]
                output["summary"] = [{"text": "Requires a report within 90 days.",
                    "source_quotes": [{"source_ref": s["source_ref"], "quote_id": "p0001"}]}]
            for s in request.source_snapshot:
                for t in s.get("reader_targets", []):
                    output["explanations"].append({"target_id": t["target_id"],
                        "status": "explained", "text": "Publish a report within 90 days.",
                        "unresolved_reason": None,
                        "source_quotes": [{"source_ref": s["source_ref"], "quote_id": "p0001"}]})
            if targets and mode == "missing":
                output["explanations"].pop()
            if targets and mode == "revoked":
                LLMCredential.objects.filter(user=enhancement_owner).update(enabled=False)
            if targets and mode == "changed":
                c.contract_hash = "changed"
                c.save()
            return ProviderResult(output, ProviderUsage(10, 5, 15), "reader-response", "test")
    monkeypatch.setattr("apps.legislation.tasks.get_provider", lambda _: Provider())
    with enhancement_settings:
        a = _pending_attempt(enhancement_owner, source_bill)
        a.dispatch_token = "reader-test"
        a.save()
        outcome = run_bill_enhancement_attempt(a.pk, a.dispatch_token)
    a.refresh_from_db()
    a.enhancement.refresh_from_db()
    if mode == "success":
        assert outcome["status"] == "succeeded"
        assert len(requests) == 3
        assert a.total_tokens == 45
        payload = enhancement_payload(a.enhancement, detail=True)
        assert len(payload["result"]["explanations"]) == 10
        assert payload["result"]["explanations"][0]["contract_id"] == c.pk
        assert payload["result"]["explanations"][0]["cited_sources"]
    else:
        assert outcome["status"] != "succeeded"
        assert a.enhancement.result_json is None
        assert len(requests) == 2


@pytest.mark.django_db
def test_source_compatibility_does_not_depend_on_execution_format(source_bill):
    from apps.legislation.enhancements.views import _source_compatible
    from types import SimpleNamespace
    import hashlib
    c = install_reader(source_bill)
    d = source_bill.documents.get()
    saved = SimpleNamespace(source_manifest_json={
        "document_id": d.pk, "document_content_hash": hashlib.sha256(d.extracted_text.encode()).hexdigest(),
        "contract_id": c.pk, "contract_hash": c.contract_hash},
        request_fingerprint="old-format", output_schema_version="1.4")
    assert _source_compatible(saved, source_bill)
    saved.source_manifest_json["contract_hash"] = "other"
    assert not _source_compatible(saved, source_bill)
