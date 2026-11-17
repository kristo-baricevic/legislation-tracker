import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.legislation.enhancements.service import create_enhancement_attempt
from apps.legislation.models import BillEnhancementAttempt
from .test_enhancement_service import enhancement_owner, enhancement_settings, source_bill, _valid_credential, _confirmation


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
        saved.status = "succeeded"; saved.result_json = {"schema_version": "1.1", "overview": []}
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
