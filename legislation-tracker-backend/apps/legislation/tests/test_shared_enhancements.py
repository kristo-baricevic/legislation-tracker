import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.legislation.enhancements.service import create_enhancement_attempt
from apps.legislation.models import BillEnhancementAttempt
from .test_enhancement_service import enhancement_owner, enhancement_settings, source_bill, _valid_credential, _confirmation


@pytest.mark.django_db
def test_source_first_xml_outage_and_changed_section_ids(source_bill, monkeypatch):
    from apps.legislation.models import BillEnhancement, BillProcessingCache
    from apps.legislation.enhancements import shared, xml_sections
    from apps.legislation.enhancements.source_graph import document_fingerprint
    from apps.legislation.enhancements.source_packet import PreflightUnavailable

    doc = source_bill.documents.get()
    from unittest.mock import Mock
    doc.object_storage_key = "source.xml"
    doc.content_hash = "a" * 64
    doc.save()
    section = ("section-A", 0, 10, "Sec. 1", "Heading")
    sections = (section,)
    saved = BillEnhancement.objects.create(bill=source_bill, status="succeeded", result_json={},
        output_schema_version="2.0-source-first", result_completeness="complete",
        source_manifest_json={"document_id": doc.pk, "document_version_label": doc.version_label,
            "document_content_hash": doc.reader_text_hash, "source_kind": "pinned_passages"},
        source_fingerprint=document_fingerprint(str(doc.pk), doc.version_label, doc.reader_text_hash, sections))
    def outage(*args):
        raise PreflightUnavailable("temporarily unavailable")
    monkeypatch.setattr(xml_sections, "stored_xml_sections", outage)
    assert not shared._reader_result_valid(saved)
    assert not BillProcessingCache.objects.filter(kind="reader-validation").exists()
    read = Mock(return_value=sections)
    monkeypatch.setattr(xml_sections, "stored_xml_sections", read)
    monkeypatch.setattr(shared, "_source_first_result_valid", lambda *args: True)
    assert shared.shared_enhancement(source_bill).pk == saved.pk
    assert shared._reader_result_valid(saved)
    read.assert_called_once()
    doc.content_hash = "b" * 64
    doc.save()
    read.return_value = (("section-B", *section[1:]),)
    assert shared.shared_enhancement(source_bill) is None
    assert not shared._reader_result_valid(saved)


@pytest.mark.django_db
def test_pending_source_first_poll_reuses_xml_alignment(source_bill, enhancement_owner, monkeypatch):
    from unittest.mock import Mock
    from apps.legislation.models import BillEnhancement
    from apps.legislation.enhancements import xml_sections
    from apps.legislation.enhancements.source_graph import document_fingerprint

    doc = source_bill.documents.get()
    doc.content_hash, doc.object_storage_key = "c" * 64, "poll.xml"
    doc.save()
    sections = (("id", 0, 10, "Sec. 1", "Heading"),)
    read = Mock(return_value=sections)
    monkeypatch.setattr(xml_sections, "stored_xml_sections", read)
    saved = BillEnhancement.objects.create(user=enhancement_owner, bill=source_bill, status="pending",
        output_schema_version="2.0-source-first", source_manifest_json={"document_id": doc.pk,
            "document_version_label": doc.version_label, "source_kind": "pinned_passages"},
        source_fingerprint=document_fingerprint(str(doc.pk), doc.version_label, doc.reader_text_hash, sections))
    client = APIClient()
    client.force_authenticate(enhancement_owner)
    for route in ("latest", saved.pk, "latest"):
        response = client.get(f"/api/bills/{source_bill.pk}/enhancements/{route}/")
        assert response.status_code == 200 and response.data["source_compatible"]
    read.assert_called_once()


@pytest.mark.django_db
def test_large_html_result_is_visible_and_reused_without_an_nlp_contract(
        enhancement_owner, enhancement_settings, source_bill):
    from django.test import override_settings
    from apps.legislation.enhancements.source_packet import build_enhancement_preflight
    from .test_reader_financial_integrity import review
    from apps.legislation.enhancements.reader_discovery import resolve_discovery

    document = source_bill.documents.get()
    document.content_type = "text/html"
    document.object_storage_key = "public-law.html"
    document.extracted_text = "".join(
        f"SEC. {i}. Reports\n" + "".join(
            f"The agency shall publish report {i}-{j} for the public.\n" for j in range(100))
        for i in range(12))
    document.save()
    other = get_user_model().objects.create_user(username="html-reader")
    client = APIClient()
    client.force_authenticate(other)

    with enhancement_settings, override_settings(LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS=50000, LLM_READER_MAX_CALLS=0):
        credential = _valid_credential(enhancement_owner)
        confirmation = _confirmation(source_bill, credential)
        saved = create_enhancement_attempt(user=enhancement_owner, bill=source_bill, confirmed=confirmation).enhancement
        plan = build_enhancement_preflight(source_bill)
        assert plan.output_schema_version == "1.4"
        assert plan.source_manifest["contract_id"] is None
        sources, output = review()
        saved.source_snapshot_json = sources
        saved.result_json = {"schema_version": "1.4", "summary": [], "explanations": [],
            "source_review": {"reviewed_sources": [s["source_ref"] for s in sources],
                              **resolve_discovery(output, sources)}}
        saved.status = "succeeded"
        saved.save()
        response = client.get(f"/api/bills/{source_bill.pk}/enhancements/latest/")
        assert response.status_code == 200
        assert response.data["source_compatible"] is True
        assert response.data["active_reader"]["id"] == saved.pk
        assert response.data["active_reader"]["result"]["source_review"]["financial_items"]
        reused = create_enhancement_attempt(user=other, bill=source_bill, confirmed=confirmation)
        assert not reused.created
        assert reused.enhancement.pk == saved.pk
        assert BillEnhancementAttempt.objects.count() == 1

        client.force_authenticate(enhancement_owner)
        url = f"/api/bills/{source_bill.pk}/enhancements/"
        estimate = client.get(url + "estimate/?rerun=1").data
        assert estimate["can_enhance"] and estimate["rerun_after"] == saved.pk
        body = {key: estimate[key] for key in ("source_fingerprint", "request_fingerprint", "credential_revision", "rerun_after")}
        assert client.post(url, {**body, "request_fingerprint": confirmation["request_fingerprint"]}, format="json").status_code == 409
        rerun = client.post(url, body, format="json")
        assert rerun.status_code == 202 and rerun.data["id"] != saved.pk
        assert rerun.data["active_reader"]["id"] == saved.pk
        assert client.get(url + "latest/").data["id"] == rerun.data["id"]
        assert client.post(url, body, format="json").data["id"] == rerun.data["id"]
        assert BillEnhancementAttempt.objects.count() == 2


def test_reader_discovery_rejects_unsourced_arabic_word():
    from jsonschema import ValidationError
    from apps.legislation.enhancements.reader_discovery import resolve_discovery
    from .test_reader_financial_integrity import review
    sources, output = review()
    output["financial_items"][0]["text"] = "Applies on or بعد?"
    with pytest.raises(ValidationError, match="Arabic word"):
        resolve_discovery(output, sources)


@pytest.mark.django_db
def test_old_success_with_wrong_money_cannot_bypass_new_validation(enhancement_owner, enhancement_settings, source_bill):
    from .test_reader_enhancement_pipeline import install_reader
    from .test_reader_financial_integrity import review
    from apps.legislation.enhancements.reader_discovery import resolve_discovery
    from apps.legislation.enhancements.shared import shared_enhancement
    install_reader(source_bill, count=0)
    sources, output = review()
    with enhancement_settings:
        credential = _valid_credential(enhancement_owner)
        saved = create_enhancement_attempt(user=enhancement_owner, bill=source_bill,
            confirmed=_confirmation(source_bill, credential)).enhancement
        resolved = resolve_discovery(output, sources)
        saved.source_snapshot_json = sources
        saved.status = 'succeeded'
        saved.result_json = {'schema_version': '1.4', 'summary': [], 'explanations': [],
            'source_review': {'reviewed_sources': ['src_0001'], **resolved}}
        saved.result_json['source_review']['financial_items'][0]['amount_display'] = '$1 billion'
        saved.save()
        assert shared_enhancement(source_bill, include_active=False) is None
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as queries:
            assert shared_enhancement(source_bill, include_active=False) is None
        # A cached validation verdict must not reload or serialize either large JSON field.
        assert not any('"legislation_billenhancement"."source_snapshot_json"' in q["sql"].split(" FROM ")[0]
            or '"legislation_billenhancement"."result_json"' in q["sql"].split(" FROM ")[0] for q in queries)
        client = APIClient()
        client.force_authenticate(enhancement_owner)
        for suffix in ("latest/", f"{saved.pk}/"):
            response = client.get(f"/api/bills/{source_bill.pk}/enhancements/{suffix}")
            assert response.status_code == 200
            assert response.data["result"] is None
            assert response.data["active_reader"] is None


@pytest.mark.django_db
def test_saved_policy_drafts_are_repaired_before_validation(enhancement_owner, enhancement_settings, source_bill):
    from copy import deepcopy
    from .test_reader_enhancement_pipeline import install_reader
    from apps.legislation.enhancements.reader_discovery import discovery_sources, resolve_discovery
    from apps.legislation.enhancements.shared import shared_enhancement
    from apps.legislation.enhancements.serializers import enhancement_payload
    install_reader(source_bill, count=0)
    sources = discovery_sources('SEC. 1. Schools\nThe Secretary may provide services to eligible schools.', 1)
    sources[0]['policy_review'] = True
    review = resolve_discovery({'financial_items': [], 'additional_changes': [], 'money_checks': {},
        'policy_checks': {'src_0001:p0001': 'explained'}, 'policy_changes': [{
            'title': 'School services', 'text': 'The Secretary may provide services to eligible schools.',
            'source_quotes': [{'source_ref': 'src_0001', 'quote_id': 'p0001'}]}]}, sources)
    review['reviewed_sources'] = ['src_0001']
    review['policy_drafts'] = deepcopy(review['policy_changes'])
    review['policy_changes'][0]['text'] = 'The Secretary must provide services to every school.'
    with enhancement_settings:
        credential = _valid_credential(enhancement_owner)
        saved = create_enhancement_attempt(user=enhancement_owner, bill=source_bill,
            confirmed=_confirmation(source_bill, credential)).enhancement
        saved.source_snapshot_json = sources
        saved.status = 'succeeded'
        saved.result_json = {'schema_version': '1.4', 'summary': [], 'explanations': [], 'source_review': review}
        saved.save()
        reusable = shared_enhancement(source_bill, include_active=False)
        assert reusable is not None
        result = enhancement_payload(reusable, detail=True, viewer=enhancement_owner)['result']
        assert result['source_review']['policy_changes'][0]['text'] == review['policy_drafts'][0]['text']
        saved.refresh_from_db()
        assert saved.result_json['source_review']['policy_changes'][0]['text'] == review['policy_changes'][0]['text']


@pytest.mark.django_db
def test_two_users_share_one_pending_paid_job(enhancement_owner, enhancement_settings, source_bill):
    other = get_user_model().objects.create_user(username="shared-reader")
    with enhancement_settings:
        credential = _valid_credential(enhancement_owner)
        confirmation = _confirmation(source_bill, credential)
        first = create_enhancement_attempt(user=enhancement_owner, bill=source_bill, confirmed=confirmation)
        second = create_enhancement_attempt(user=other, bill=source_bill, confirmed=confirmation)
    assert second.created is False
    assert second.enhancement.pk == first.enhancement.pk
    assert BillEnhancementAttempt.objects.count() == 1


@pytest.mark.django_db
def test_changed_bill_text_is_not_reused(enhancement_owner, enhancement_settings, source_bill):
    other = get_user_model().objects.create_user(username="new-version-reader")
    with enhancement_settings:
        owner_key = _valid_credential(enhancement_owner)
        first = create_enhancement_attempt(user=enhancement_owner, bill=source_bill, confirmed=_confirmation(source_bill, owner_key))
        document = source_bill.documents.get()
        document.extracted_text += " The report must be public."
        document.save()
        other_key = _valid_credential(other)
        second = create_enhancement_attempt(user=other, bill=source_bill, confirmed=_confirmation(source_bill, other_key))
    assert second.created
    assert second.enhancement.pk != first.enhancement.pk


@pytest.mark.django_db
def test_failed_output_is_not_reused_and_cannot_spend_another_users_key(enhancement_owner, enhancement_settings, source_bill):
    other = get_user_model().objects.create_user(username="retry-reader")
    client = APIClient(); client.force_authenticate(other)
    with enhancement_settings:
        credential = _valid_credential(enhancement_owner)
        confirmation = _confirmation(source_bill, credential)
        first = create_enhancement_attempt(user=enhancement_owner, bill=source_bill, confirmed=confirmation)
        first.enhancement.status = "failed"; first.enhancement.save()
        response = client.post(f"/api/bills/{source_bill.pk}/enhancements/{first.enhancement.pk}/retry/", confirmation, format="json")
        assert response.status_code == 404
        assert client.get(f"/api/bills/{source_bill.pk}/enhancements/latest/").status_code == 404
        other_key = _valid_credential(other)
        second = create_enhancement_attempt(user=other, bill=source_bill, confirmed=_confirmation(source_bill, other_key))
    assert second.created
    assert second.attempt.credential_id == other_key.pk


@pytest.mark.django_db
def test_shared_result_needs_no_key_and_hides_payer_history(enhancement_owner, enhancement_settings, source_bill):
    other = get_user_model().objects.create_user(username="shared-reader")
    client = APIClient(); client.force_authenticate(other)
    with enhancement_settings:
        credential = _valid_credential(enhancement_owner)
        confirmation = _confirmation(source_bill, credential)
        first = create_enhancement_attempt(user=enhancement_owner, bill=source_bill, confirmed=confirmation)
        saved = first.enhancement
        saved.status = "succeeded"
        saved.result_json = {"schema_version": saved.output_schema_version, "overview": [], "key_impacts": [],
                             "obligations": [], "funding_and_timing": [], "uncertain_language": [], "glossary": []}
        saved.save()
        second = create_enhancement_attempt(user=other, bill=source_bill, confirmed=confirmation)
        response = client.get(f"/api/bills/{source_bill.pk}/enhancements/latest/")
        estimate = client.get(f"/api/bills/{source_bill.pk}/enhancements/estimate/")
    assert not second.created
    assert response.status_code == 200
    assert response.data["result"] == saved.result_json
    assert response.data["attempts"] == []
    assert response.data["latest_attempt"] is None
    assert "credential_revision" not in str(response.data)
    assert estimate.data["matching_enhancement"]["id"] == saved.pk
    assert not estimate.data["can_enhance"]
    assert BillEnhancementAttempt.objects.count() == 1
    enhancement_owner.delete()
    saved.refresh_from_db()
    assert saved.user_id is None
    assert client.get(f"/api/bills/{source_bill.pk}/enhancements/latest/").data["result"] == saved.result_json
