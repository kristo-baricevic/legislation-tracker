"""Durable, fenced reader-call cache. Ambiguous dispatches are never replayed."""
from django.db import transaction
from django.conf import settings
from django.utils import timezone
from apps.legislation.models import BillEnhancementAttempt, BillEnhancementStep, BillEnhancementCallCache
from .reader_cache import call_identity, remap
from .providers.base import ProviderError, ProviderResult, ProviderUsage
from .reader_citations import resolve_reader_citations
from .reader_targets import snapshot_targets
from .reader_discovery import resolve_discovery
from jsonschema import ValidationError
from .diagnostics import validation_diagnostic, output_error


def _validate_response(output, request):
    if request.request_envelope.get('source_review'):
        return resolve_discovery(output, request.source_snapshot)
    targets = snapshot_targets(request.source_snapshot)
    valid = resolve_reader_citations(output, targets, request.source_snapshot)
    if (targets and valid['summary']) or (not targets and not valid['summary']):
        raise output_error('reader_coverage_incomplete', ['summary'])
    return valid


class ReaderDeliveryComplete(Exception):
    """Yield only between calls; completed calls remain durably reusable."""


class DurableReaderProvider:
    def __init__(self, provider, attempt, run_token, maximum_calls):
        self.provider, self.attempt, self.run_token = provider, attempt, run_token
        self.maximum_calls = maximum_calls
        self.paid_calls = 0

    def enhance_bill(self, *, api_key, request, timeout_seconds):
        fingerprint, references = call_identity(request)
        with transaction.atomic():
            current = BillEnhancementAttempt.objects.select_for_update().get(pk=self.attempt.pk)
            if current.status != 'running' or current.run_token != self.run_token or current.lease_expires_at <= timezone.now():
                raise ProviderError('outcome_unknown', outcome_unknown=True)
            # A unique durable reservation serializes callers across attempts
            # and users. It survives deletion of the originating user's run.
            cached, created = BillEnhancementCallCache.objects.get_or_create(fingerprint=fingerprint)
            cached = BillEnhancementCallCache.objects.select_for_update().get(pk=fingerprint)
            if not created:
                if cached.status == 'validated':
                    output = remap(cached.result_json, {v: k for k, v in references.items()})
                    _validate_response(output, request)
                    return ProviderResult(output, ProviderUsage(0, 0, 0), cached.response_id, cached.resolved_model)
                if cached.diagnostic_code == 'provider_output_limit':
                    raise ProviderError('invalid_output', validation_code='provider_output_limit', usage=ProviderUsage(0, 0, 0))
                if cached.status == 'dispatching':
                    raise ProviderError('outcome_unknown', outcome_unknown=True)
            existing = BillEnhancementStep.objects.filter(attempt=current, request_fingerprint=fingerprint).first()
            if existing:
                if existing.status == 'failed' and cached.status == 'failed' and existing.diagnostics.get('code'):
                    raise ProviderError('invalid_output', validation_code=existing.diagnostics['code'], usage=ProviderUsage(0, 0, 0))
                raise ProviderError('outcome_unknown', outcome_unknown=True)
            if self.paid_calls >= max(1, settings.LLM_READER_CALLS_PER_DELIVERY):
                raise ReaderDeliveryComplete()
            count = current.steps.count()
            if count >= self.maximum_calls:
                raise ProviderError('request_too_large', usage=ProviderUsage(0, 0, 0))
            step = BillEnhancementStep.objects.create(attempt=current, step_index=count,
                stage='reader', request_fingerprint=fingerprint, status='dispatching')
            cached.status = 'dispatching'
            cached.save(update_fields=['status', 'updated_at'])
        try:
            self.paid_calls += 1
            response = self.provider.enhance_bill(api_key=api_key, request=request, timeout_seconds=timeout_seconds)
            _validate_response(response.output, request)
        except Exception as exc:
            usage = getattr(exc, 'usage', locals().get('response', ProviderResult({}, ProviderUsage(), '', '')).usage)
            # Store no unvalidated prose or raw exception bodies.
            step.status = 'failed'
            code = validation_diagnostic(exc)['code'] if isinstance(exc, ValidationError) else getattr(exc, 'validation_code', '')
            step.diagnostics = {'code': code}
            step.input_tokens, step.output_tokens, step.total_tokens = usage.input_tokens, usage.output_tokens, usage.total_tokens
            # Unknown outcomes remain reserved. Only a known, completed invalid
            # response may be retried after a separate user confirmation.
            with transaction.atomic():
                step.save()
                if isinstance(exc, ValidationError) or (isinstance(exc, ProviderError) and not exc.outcome_unknown):
                    cached.status = 'failed'
                    cached.diagnostic_code = code
                    cached.save(update_fields=['status', 'diagnostic_code', 'updated_at'])
            if isinstance(exc, ValidationError):
                detail = validation_diagnostic(exc)
                raise ProviderError('invalid_output', validation_code=detail['code'], validation_detail=detail, usage=usage) from None
            raise
        step.status = 'validated'
        step.diagnostics = {'resolved_model': response.resolved_model}
        step.result_json, step.response_id = response.output, response.response_id
        step.input_tokens, step.output_tokens, step.total_tokens = response.usage.input_tokens, response.usage.output_tokens, response.usage.total_tokens
        with transaction.atomic():
            step.save()
            cached.status = 'validated'
            cached.result_json = remap(response.output, references)
            cached.response_id, cached.resolved_model = response.response_id, response.resolved_model
            cached.save()
        return response
