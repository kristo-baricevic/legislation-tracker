"""Persist recovery decisions independently of paid API attempts."""
from dataclasses import replace

from django.db import transaction
from django.utils import timezone

from apps.legislation.models import BillEnhancementAttempt, BillEnhancementWorkUnit
from .providers.base import ProviderError
from .source_packet import canonical_json_bytes


class ReaderWorkPlan:
    def __init__(self, attempt, run_token, preflight):
        self.attempt_id, self.run_token, self.preflight = attempt.pk, run_token, preflight

    def _fence(self):
        attempt = BillEnhancementAttempt.objects.select_for_update().get(pk=self.attempt_id)
        if attempt.status != 'running' or attempt.run_token != self.run_token or not attempt.lease_expires_at or attempt.lease_expires_at <= timezone.now():
            raise ProviderError('outcome_unknown', outcome_unknown=True)

    def _create(self, key, index, request, parent=''):
        return BillEnhancementWorkUnit.objects.create(attempt_id=self.attempt_id, node_key=key,
            parent_key=parent, batch_index=index, request_json={
                'sources': request.source_snapshot, 'envelope': request.request_envelope})

    def _request(self, row):
        envelope = row.request_json['envelope']
        encoded = canonical_json_bytes(envelope)
        return (row.batch_index, replace(self.preflight, source_snapshot=row.request_json['sources'],
            request_envelope=envelope, request_bytes=encoded, estimated_input_tokens=len(encoded)), row.node_key)

    def initialize(self, requests):
        with transaction.atomic():
            self._fence()
            rows = BillEnhancementWorkUnit.objects.filter(attempt_id=self.attempt_id)
            if not rows.exists():
                for order, (index, request) in enumerate(requests):
                    self._create(f'{order:06d}', index, request)
            return [self._request(row) for row in rows.exclude(status='expanded').order_by('node_key')]

    def saved_result(self, key):
        row = BillEnhancementWorkUnit.objects.get(attempt_id=self.attempt_id, node_key=key)
        return row.result_json if row.status == 'validated' else None

    def complete(self, key, output):
        with transaction.atomic():
            self._fence()
            row = BillEnhancementWorkUnit.objects.get(attempt_id=self.attempt_id, node_key=key)
            if row.status == 'expanded' or (row.status == 'validated' and row.result_json != output):
                raise ProviderError('invalid_output', validation_code='work_plan_changed')
            row.result_json, row.status = output, 'validated'
            row.save(update_fields=['result_json', 'status'])

    def expand(self, key, index, children, *, reason, validated_outputs=None):
        with transaction.atomic():
            self._fence()
            parent = BillEnhancementWorkUnit.objects.get(attempt_id=self.attempt_id, node_key=key)
            if parent.status != 'pending' or not children:
                raise ProviderError('invalid_output', validation_code='work_plan_changed')
            rows = [self._create(f'{key}.{i:04d}', index, child, parent=key) for i, child in enumerate(children)]
            for row, output in zip(rows, validated_outputs or []):
                if output is not None:
                    row.status, row.result_json = 'validated', output
                    row.save(update_fields=['status', 'result_json'])
            parent.status, parent.reason = 'expanded', reason
            parent.save(update_fields=['status', 'reason'])
            return [self._request(row) for row in rows]
