"""Conservative planning limits, optionally overridden for a provider/model pair.

UTF-8 bytes are an upper-bound input estimate, not an exact tokenizer count.
Unspecified reasoning means provider default, NOT disabled reasoning.
"""

from django.conf import settings

from .model_selection import target


def capacity(provider=None, model=None):
    provider, model = (provider, model) if provider and model else target()
    from .model_capabilities import resolve_capabilities

    limits = resolve_capabilities(provider, model)
    return {
        "output_tokens": limits.output_tokens,
        "context_tokens": limits.context_tokens,
        "visible_fraction": limits.visible_fraction,
    }


def fits(envelope, *, provider=None, model=None):
    from .source_packet import _within_limits, canonical_json_bytes

    encoded = canonical_json_bytes(envelope)
    from .model_capabilities import resolve_capabilities
    from .token_budget import plan_request

    pair = (provider, model) if provider and model else target()
    limits = resolve_capabilities(*pair)
    budget = plan_request(envelope, limits)
    return (
        _within_limits(encoded)
        and budget.max_output_tokens <= limits.output_tokens
        and budget.context_margin >= 0
    )
