"""Durable, fenced reader-call cache. Ambiguous dispatches are never replayed."""
import hashlib
from django.db import transaction
from django.utils import timezone
from apps.legislation.models import BillEnhancementAttempt, BillEnhancementStep
from .source_packet import canonical_json_bytes
from .providers.base import ProviderError, ProviderResult, ProviderUsage
from .reader_citations import resolve_reader_citations
from .reader_targets import snapshot_targets
from .reader_discovery import resolve_discovery
from jsonschema import ValidationError
from .diagnostics import validation_diagnostic


class DurableReaderProvider:
    def __init__(self, provider, attempt, run_token, maximum_calls):
        self.provider, self.attempt, self.run_token = provider, attempt, run_token
        self.maximum_calls = maximum_calls

    def enhance_bill(self, *, api_key, request, timeout_seconds):
        fingerprint = hashlib.sha256(canonical_json_bytes({
            'envelope': request.request_envelope, 'sources': request.source_snapshot,
            'model': request.requested_model, 'reasoning': request.reasoning_effort})).hexdigest()
        with transaction.atomic():
            current = BillEnhancementAttempt.objects.select_for_update().get(pk=self.attempt.pk)
            if current.status != 'running' or current.run_token != self.run_token or current.lease_expires_at <= timezone.now():
                raise ProviderError('outcome_unknown', outcome_unknown=True)
            # Same enhancement means the same confirmed document, targets and plan.
            cached = BillEnhancementStep.objects.filter(attempt__enhancement_id=current.enhancement_id,
                request_fingerprint=fingerprint, status='validated').order_by('-pk').first()
            if cached:
                return ProviderResult(cached.result_json, ProviderUsage(0, 0, 0), cached.response_id,
                                      cached.diagnostics.get('resolved_model', request.requested_model))
            existing = BillEnhancementStep.objects.filter(attempt=current, request_fingerprint=fingerprint).first()
            if existing:
                if existing.diagnostics.get('code') == 'provider_output_limit':
                    raise ProviderError('invalid_output', validation_code='provider_output_limit', usage=ProviderUsage(0, 0, 0))
                raise ProviderError('outcome_unknown', outcome_unknown=True)
            count = current.steps.count()
            if count >= self.maximum_calls:
                raise ProviderError('request_too_large', usage=ProviderUsage(0, 0, 0))
            step = BillEnhancementStep.objects.create(attempt=current, step_index=count,
                stage='reader', request_fingerprint=fingerprint, status='dispatching')
        try:
            response = self.provider.enhance_bill(api_key=api_key, request=request, timeout_seconds=timeout_seconds)
            validator = resolve_discovery if request.request_envelope.get('source_review') else None
            if validator:
                validator(response.output, request.source_snapshot)
            else:
                resolve_reader_citations(response.output, snapshot_targets(request.source_snapshot), request.source_snapshot)
        except Exception as exc:
            usage = getattr(exc, 'usage', locals().get('response', ProviderResult({}, ProviderUsage(), '', '')).usage)
            # Store no unvalidated prose or raw exception bodies.
            step.status = 'failed'
            step.diagnostics = {'code': getattr(exc, 'validation_code', '')}
            step.input_tokens, step.output_tokens, step.total_tokens = usage.input_tokens, usage.output_tokens, usage.total_tokens
            step.save()
            if isinstance(exc, ValidationError):
                detail = validation_diagnostic(exc)
                raise ProviderError('invalid_output', validation_code=detail['code'], validation_detail=detail, usage=usage) from None
            raise
        step.status = 'validated'
        step.diagnostics = {'resolved_model': response.resolved_model}
        step.result_json, step.response_id = response.output, response.response_id
        step.input_tokens, step.output_tokens, step.total_tokens = response.usage.input_tokens, response.usage.output_tokens, response.usage.total_tokens
        step.save()
        return response
