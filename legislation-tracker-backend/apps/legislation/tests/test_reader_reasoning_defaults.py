from django.test import override_settings
from apps.legislation.enhancements.model_selection import planning_for
from apps.legislation.enhancements.source_packet import _request_envelope
from types import SimpleNamespace


def test_openrouter_default_is_bounded_and_disclosed_in_request_identity():
    bill = SimpleNamespace(id=15778, bill_number='S 4387', title='Protect Moms From Domestic Violence Act',
        jurisdiction='federal', session=119, status='Introduced', introduced_at=None)
    with override_settings(LLM_ENHANCEMENT_REASONING_EFFORT='none'), planning_for(('openrouter', 'openrouter/free')):
        envelope = _request_envelope(bill, [], truncated=False)
    assert envelope['reasoning_effort'] == 'low'
