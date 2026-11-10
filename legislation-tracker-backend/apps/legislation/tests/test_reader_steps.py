# ruff: noqa: F401, F811
from datetime import timedelta
from dataclasses import replace
import pytest
from django.utils import timezone
from apps.legislation.enhancements.reader_steps import DurableReaderProvider
from apps.legislation.enhancements.providers.base import ProviderResult, ProviderUsage, ProviderError
from apps.legislation.enhancements.source_packet import build_enhancement_preflight
from apps.legislation.tests.test_reader_enhancement_pipeline import install_reader
from apps.legislation.tests.test_enhancement_tasks import _pending_attempt
from apps.legislation.tests.test_enhancement_service import source_bill, enhancement_owner, enhancement_settings


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('crash', [False, True])
def test_reader_step_persists_success_and_never_blindly_replays_a_dispatch(
        source_bill, enhancement_owner, enhancement_settings, crash):
    install_reader(source_bill)
    with enhancement_settings:
        p = build_enhancement_preflight(source_bill)
        refs = {s['source_ref'] for s in p.request_envelope['source_packet']['sources']}
        p = replace(p, source_snapshot=[s for s in p.source_snapshot if s['source_ref'] in refs])
        a = _pending_attempt(enhancement_owner, source_bill)
        a.status, a.run_token, a.lease_expires_at = 'running', 'run', timezone.now() + timedelta(minutes=10)
        a.save()
        class Provider:
            calls = 0
            def enhance_bill(self, **kwargs):
                self.calls += 1
                if crash:
                    raise KeyboardInterrupt('simulate process death after dispatch')
                return ProviderResult({'schema_version': '1.4', 'summary': [{'text': 'Requires a report.',
                    'source_quotes': [{'source_ref': p.source_snapshot[0]['source_ref'], 'quote_id': 'p0001'}]}], 'explanations': []}, ProviderUsage(10, 5, 15), 'response', 'test')
        real = Provider()
        wrapper = DurableReaderProvider(real, a, 'run', 2)
        if crash:
            with pytest.raises(KeyboardInterrupt):
                wrapper.enhance_bill(api_key='test', request=p, timeout_seconds=1)
            with pytest.raises(ProviderError) as error:
                wrapper.enhance_bill(api_key='test', request=p, timeout_seconds=1)
            assert error.value.outcome_unknown
            assert a.steps.get().status == 'dispatching'
        else:
            first = wrapper.enhance_bill(api_key='test', request=p, timeout_seconds=1)
            saved = a.steps.get()
            assert saved.status == 'validated' and saved.result_json == first.output
            second = wrapper.enhance_bill(api_key='test', request=p, timeout_seconds=1)
            assert second.output == first.output and second.usage.total_tokens == 0
            assert second.resolved_model == first.resolved_model
            from apps.legislation.enhancements.source_first_worker import step_usage
            assert step_usage(a.pk).total_tokens == 15
        assert real.calls == 1
