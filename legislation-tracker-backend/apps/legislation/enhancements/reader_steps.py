"""Durable, fenced reader-call cache. Ambiguous dispatches are never replayed."""
from dataclasses import replace
from django.db import transaction
from django.conf import settings
from django.utils import timezone
from apps.legislation.models import BillEnhancementAttempt, BillEnhancementStep, BillEnhancementCallCache
from .reader_cache import call_identity, remap
from .providers.base import ProviderError, ProviderResult, ProviderUsage
from .reader_citations import recover_reader_items, resolve_reader_citations
from .reader_targets import snapshot_targets
from .reader_discovery import resolve_discovery
from jsonschema import ValidationError
from .diagnostics import validation_diagnostic, provider_failure_diagnostic, output_error
from .reader_partial import PartialReviewReady, validated_components


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


class ReaderBudgetPaused(Exception):
    """No further dispatch is authorized; keep the durable pending work."""


class DurableReaderProvider:
    durable = True
    def __init__(self, provider, attempt, run_token, maximum_calls):
        self.provider, self.attempt, self.run_token = provider, attempt, run_token
        self.maximum_calls = maximum_calls
        self.paid_calls = 0
        self.cache_hits = 0

    def progress(self):
        from django.db.models import Count, Q
        calls = self.attempt.steps.aggregate(dispatched_calls=Count('pk'),
            validated_calls=Count('pk', filter=Q(status='validated')))
        units = self.attempt.work_units.aggregate(validated_units=Count('pk', filter=Q(status='validated')),
            pending_units=Count('pk', filter=Q(status='pending')))
        return {**calls, **units, 'cache_hits_this_delivery': self.cache_hits}

    def _pin(self, request, resolved_model):
        if (request.provider, request.requested_model) != ('openrouter', 'openrouter/free'):
            return
        # The router selects the initial free model. All subsequent *new* calls
        # use that exact ID; existing validated public results remain reusable.
        if not resolved_model or not resolved_model.endswith(':free'):
            raise ProviderError('model_access_denied', validation_code='free_model_not_resolved')
        BillEnhancementAttempt.objects.filter(pk=self.attempt.pk, run_token=self.run_token,
            status='running', pinned_model='').update(pinned_model=resolved_model)

    def enhance_bill(self, *, api_key, request, timeout_seconds):
        try:
            return self._enhance_bill(api_key=api_key, request=request, timeout_seconds=timeout_seconds)
        except (PartialReviewReady, ProviderError) as exc:
            # Cached recovery is signalled by an exception. Pin outside the
            # reservation transaction so its rollback does not discard the pin.
            if exc.resolved_model:
                self._pin(request, exc.resolved_model)
            raise

    def _enhance_bill(self, *, api_key, request, timeout_seconds):
        adapter = self.attempt.execution_config.get("adapter", "existing")
        logical_fingerprint, references = call_identity(request, adapter=adapter)
        with transaction.atomic():
            current = BillEnhancementAttempt.objects.select_for_update().get(pk=self.attempt.pk)
            if current.status != 'running' or current.run_token != self.run_token or current.lease_expires_at <= timezone.now():
                raise ProviderError('outcome_unknown', outcome_unknown=True)
            dispatch_request = request
            if (request.provider, request.requested_model) == ('openrouter', 'openrouter/free') and current.pinned_model:
                dispatch_request = replace(request, requested_model=current.pinned_model)
            fingerprint, _ = call_identity(dispatch_request, adapter=adapter)
            # A restart may happen after the router resolved the first call but
            # before its work-node checkpoint. Reuse that exact reservation.
            prior_step = current.steps.filter(diagnostics__logical_fingerprint=logical_fingerprint).first()
            if prior_step:
                fingerprint = prior_step.request_fingerprint
            else:
                legacy_key, _ = call_identity(dispatch_request, execution_version=2)
                legacy = BillEnhancementCallCache.objects.filter(
                    fingerprint=legacy_key).first()
                if legacy and legacy.status == 'dispatching':
                    raise ProviderError('outcome_unknown', outcome_unknown=True)
                if adapter == 'existing' and legacy and legacy.status == 'validated':
                    output = remap(legacy.result_json, {v: k for k, v in references.items()})
                    try:
                        _validate_response(output, request)
                    except ValidationError:
                        pass  # Invalid old prose must be regenerated, never reused.
                    else:
                        self._pin(request, legacy.resolved_model)
                        self.cache_hits += 1
                        return ProviderResult(output, ProviderUsage(0, 0, 0), legacy.response_id, legacy.resolved_model)
            # A unique durable reservation serializes callers across attempts
            # and users. It survives deletion of the originating user's run.
            cached, created = BillEnhancementCallCache.objects.get_or_create(fingerprint=fingerprint)
            cached = BillEnhancementCallCache.objects.select_for_update().get(pk=fingerprint)
            if not created:
                if cached.status == 'partial':
                    partial = remap(cached.result_json, {v: k for k, v in references.items()})
                    # Recheck each retained component under today's validator.
                    from .reader_sizing import select_review_units
                    retained = []
                    pending = list(partial['pending'])
                    for ids, output in partial['parts']:
                        try:
                            _validate_response(output, select_review_units(request, ids))
                        except ValidationError:
                            pending.extend(ids)
                        else:
                            retained.append([ids, output])
                    if retained:
                        self.cache_hits += 1
                        raise PartialReviewReady(retained, list(dict.fromkeys(pending)), ProviderUsage(0, 0, 0), cached.resolved_model)
                    cached.status, cached.diagnostic_code = 'failed', ''
                if cached.status == 'validated':
                    output = remap(cached.result_json, {v: k for k, v in references.items()})
                    try:
                        _validate_response(output, request)
                    except ValidationError:
                        # Revalidate old cached responses under current rules.
                        # Recompute only this invalid call, keeping valid siblings.
                        cached.status = 'failed'
                        cached.diagnostic_code = ''
                    else:
                        self._pin(request, cached.resolved_model)
                        self.cache_hits += 1
                        return ProviderResult(output, ProviderUsage(0, 0, 0), cached.response_id, cached.resolved_model)
                if (cached.status == 'failed' and request.request_envelope.get('source_review') and
                        cached.diagnostic_code in {'reader_policy_wording', 'reader_coverage_incomplete', 'reader_amount_conflict', 'reader_target_invalid'}):
                    from .reader_sizing import split_reader_request
                    # Resume directly at the bounded correction or its smaller
                    # children; don't regenerate a known rejected parent first.
                    if not request.request_envelope.get('policy_retry') or split_reader_request(request):
                        raise ProviderError('invalid_output', validation_code=cached.diagnostic_code, usage=ProviderUsage(0, 0, 0), resolved_model=cached.resolved_model)
                if cached.status == 'failed' and request.request_envelope.get('source_packet', {}).get('validated_changes'):
                    from .reader_summary import SUMMARY_FALLBACK_CODES
                    if cached.diagnostic_code in SUMMARY_FALLBACK_CODES:
                        raise ProviderError('invalid_output', validation_code=cached.diagnostic_code, usage=ProviderUsage(0, 0, 0))
                if cached.diagnostic_code == 'provider_output_limit':
                    failure = ProviderError('invalid_output', validation_code='provider_output_limit',
                        usage=ProviderUsage(0, 0, 0), resolved_model=cached.resolved_model)
                    previous = cached.result_json or {}
                    failure.call_usage = ProviderUsage(output_tokens=previous.get('output_tokens'),
                                                      reasoning_tokens=previous.get('reasoning_tokens'))
                    raise failure
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
                # Undo the new cache reservation when no API call was made.
                if created:
                    cached.delete()
                raise ReaderBudgetPaused()
            from .reader_capacity import fits
            from .source_packet import canonical_json_bytes
            if not fits(request.request_envelope, provider=dispatch_request.provider, model=dispatch_request.requested_model):
                raise ProviderError('request_too_large', validation_code='model_capacity_exceeded')
            from .model_capabilities import resolve_capabilities
            from .token_budget import plan_request
            planned = plan_request(request.request_envelope, resolve_capabilities(dispatch_request.provider, dispatch_request.requested_model))
            reserved_input, reserved_output = planned.input_tokens, planned.max_output_tokens
            budget = request.source_manifest.get('budget', {})
            rows = list(current.steps.values('input_tokens', 'output_tokens', 'diagnostics'))
            for name, reservation in (('input', reserved_input), ('output', reserved_output)):
                spent = sum(row[f'{name}_tokens'] if row[f'{name}_tokens'] is not None
                    else row['diagnostics'].get(f'reserved_{name}', budget.get(f'maximum_{name}', 0)) for row in rows)
                ceiling = budget.get(f'maximum_{name}')
                if ceiling is not None and spent + reservation > ceiling:
                    raise ReaderBudgetPaused()
            from .service import attempt_credential_failure
            failure = attempt_credential_failure(current)
            if failure:
                raise ProviderError(failure)
            step = BillEnhancementStep.objects.create(attempt=current, step_index=count,
                stage='reader', request_fingerprint=fingerprint, status='dispatching', diagnostics={
                    'logical_fingerprint': logical_fingerprint, 'requested_model': dispatch_request.requested_model,
                    'reasoning_effort': request.reasoning_effort, 'reserved_input': reserved_input,
                    'reserved_output': reserved_output},
                unit_ids=[f"{s['source_ref']}:{i}" for s in request.source_snapshot for i in s.get('review_quote_ids', [])])
            cached.status = 'dispatching'
            cached.save(update_fields=['status', 'updated_at'])
        try:
            self.paid_calls += 1
            from .private_diagnostics import capture_step
            with capture_step(step, current.enhancement.user_id):
                response = self.provider.enhance_bill(api_key=api_key, request=dispatch_request, timeout_seconds=timeout_seconds)
            if (request.provider, request.requested_model) == ('openrouter', 'openrouter/free') and current.pinned_model and response.resolved_model != current.pinned_model:
                raise ProviderError('invalid_output', validation_code='pinned_model_changed', usage=response.usage)
            self._pin(request, response.resolved_model)
            if not request.request_envelope.get('source_review'):
                response = replace(response, output=recover_reader_items(response.output,
                    snapshot_targets(request.source_snapshot), request.source_snapshot))
            _validate_response(response.output, request)
        except Exception as exc:
            if isinstance(exc, ProviderError) and exc.resolved_model:
                self._pin(request, exc.resolved_model)
            usage = getattr(exc, 'usage', locals().get('response', ProviderResult({}, ProviderUsage(), '', '')).usage)
            parts, pending = ([], [])
            if isinstance(exc, ValidationError) and request.request_envelope.get('source_review') and 'response' in locals():
                parts, pending = validated_components(response.output, request.source_snapshot)
            # Store no unvalidated prose or raw exception bodies.
            step.status = 'failed'
            code = validation_diagnostic(exc)['code'] if isinstance(exc, ValidationError) else getattr(exc, 'validation_code', '')
            step.diagnostics.update(validation_diagnostic(exc) if isinstance(exc, ValidationError)
                                else provider_failure_diagnostic(exc) if isinstance(exc, ProviderError)
                                else {'code': code})
            step.diagnostics.update(reasoning_tokens=usage.reasoning_tokens, visible_output_tokens=usage.visible_output_tokens)
            if getattr(exc, 'resolved_model', ''):
                step.diagnostics['resolved_model'] = exc.resolved_model
            step.input_tokens, step.output_tokens, step.total_tokens = usage.input_tokens, usage.output_tokens, usage.total_tokens
            # Unknown outcomes remain reserved. Only a known, completed invalid
            # response may be retried after a separate user confirmation.
            with transaction.atomic():
                step.save()
                if isinstance(exc, ValidationError) or (isinstance(exc, ProviderError) and not exc.outcome_unknown):
                    cached.status = 'partial' if parts else 'failed'
                    cached.diagnostic_code = code
                    cached.resolved_model = (getattr(exc, 'resolved_model', '') or
                        (response.resolved_model if 'response' in locals() else ''))
                    if code == 'provider_output_limit':
                        cached.result_json = {'output_tokens': usage.output_tokens, 'reasoning_tokens': usage.reasoning_tokens}
                    if parts:
                        cached.result_json = remap({'parts': parts, 'pending': pending}, references)
                    cached.save(update_fields=['status', 'diagnostic_code', 'result_json', 'resolved_model', 'updated_at'])
            if parts:
                raise PartialReviewReady(parts, pending, usage, cached.resolved_model) from None
            if isinstance(exc, ValidationError):
                detail = validation_diagnostic(exc)
                raise ProviderError('invalid_output', validation_code=detail['code'], validation_detail=detail, usage=usage) from None
            raise
        step.status = 'validated'
        step.diagnostics.update(resolved_model=response.resolved_model,
            reasoning_tokens=response.usage.reasoning_tokens, visible_output_tokens=response.usage.visible_output_tokens)
        step.result_json, step.response_id = response.output, response.response_id
        step.input_tokens, step.output_tokens, step.total_tokens = response.usage.input_tokens, response.usage.output_tokens, response.usage.total_tokens
        with transaction.atomic():
            step.save()
            cached.status = 'validated'
            cached.result_json = remap(response.output, references)
            cached.response_id, cached.resolved_model = response.response_id, response.resolved_model
            cached.save()
        return response
