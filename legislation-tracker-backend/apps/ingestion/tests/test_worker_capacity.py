from unittest.mock import patch

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.ingestion.models import IngestionWorkItem
from apps.ingestion.tasks import dispatch_ingestion_work, dispatch_similarity_work


@pytest.mark.django_db
@pytest.mark.parametrize('kind,setting', [
    ('similarity', 'SIMILARITY_WORK_CONCURRENCY'),
    ('representative_research', 'RESEARCH_WORK_CONCURRENCY'),
])
def test_dispatch_fills_slots_without_overbooking(kind, setting):
    for i in range(4):
        IngestionWorkItem.objects.create(kind=kind, dedupe_key=str(i),
            source_updated_at=timezone.now(), payload_json={})
    dispatch = dispatch_similarity_work if kind == 'similarity' else dispatch_ingestion_work
    with override_settings(**{setting: 2}), patch(
        'apps.ingestion.tasks.process_ingestion_work_item.apply_async', return_value=None
    ):
        dispatch()
        assert IngestionWorkItem.objects.filter(status='dispatched').count() == 2
        dispatch()
        assert IngestionWorkItem.objects.filter(status='dispatched').count() == 2
        first = IngestionWorkItem.objects.filter(status='dispatched').first()
        first.status = 'succeeded'
        first.save()
        dispatch()
        assert IngestionWorkItem.objects.filter(status='dispatched').count() == 2


@pytest.mark.django_db
def test_each_stage_has_independent_admission_and_queue():
    kinds = ['bill', 'bill_versions', 'bill_votes', 'bill_relationships',
             'document_download', 'document_contract', 'metadata_contract',
             'topic_update', 'search_index', 'representative_detail',
             'roll_call_vote', 'committee_roster']
    for i in range(100):
        IngestionWorkItem.objects.create(kind='bill', dedupe_key=str(i),
            source_updated_at=timezone.now(), payload_json={}, status='processing')
    for kind in kinds:
        for i in range(3):
            IngestionWorkItem.objects.create(kind=kind, dedupe_key='pending'+str(i),
                source_updated_at=timezone.now(), payload_json={})
    with patch('apps.ingestion.tasks.process_ingestion_work_item.apply_async', return_value=None) as send:
        dispatch_ingestion_work()
    assert IngestionWorkItem.objects.filter(kind='bill',status='dispatched').count() == 0
    for kind in kinds[1:]:
        assert IngestionWorkItem.objects.filter(kind=kind,status='dispatched').count() == 2
    for call in send.call_args_list:
        work = IngestionWorkItem.objects.get(pk=call.kwargs['args'][0])
        assert call.kwargs['queue'] == work.kind
