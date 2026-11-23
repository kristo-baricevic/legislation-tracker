"""Conservative planning limits, optionally overridden for a provider/model pair.

UTF-8 bytes are an upper-bound input estimate, not an exact tokenizer count.
Unspecified reasoning means provider default, NOT disabled reasoning.
"""
from django.conf import settings
from .model_selection import target


def capacity(provider=None, model=None):
    provider, model = (provider, model) if provider and model else target()
    configured = getattr(settings, 'LLM_READER_MODEL_CAPACITIES', {}).get(f'{provider}/{model}', {})
    output = min(settings.LLM_READER_MAX_OUTPUT_TOKENS, int(configured.get('output_tokens', settings.LLM_READER_MAX_OUTPUT_TOKENS)))
    return {'output_tokens': output,
        'context_tokens': int(configured.get('context_tokens', settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS + output + 1024)),
        'visible_fraction': min(.9, max(.1, float(configured.get('visible_fraction', .5))))}


def fits(envelope, *, provider=None, model=None):
    from .source_packet import canonical_json_bytes, _within_limits
    encoded = canonical_json_bytes(envelope)
    limits = capacity(provider, model)
    output = envelope.get('max_output_tokens', settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS)
    # Reserve space for adapter message wrappers outside the JSON envelope.
    return (_within_limits(encoded) and output <= limits['output_tokens']
        and len(encoded) + output + 1024 <= limits['context_tokens'])
