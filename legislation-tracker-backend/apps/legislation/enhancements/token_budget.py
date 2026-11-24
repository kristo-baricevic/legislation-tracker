"""Conservative envelope accounting shared by preflight and durable reservations."""
from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class RequestBudget:
    input_tokens: int
    estimator: str
    max_output_tokens: int
    requested_reasoning_effort: str | None
    visible_reserve: int
    context_margin: int
    capability_fingerprint: str


def plan_request(envelope, capabilities):
    from .source_packet import canonical_json_bytes

    input_tokens = len(canonical_json_bytes(envelope)) + 1024
    output = envelope.get("max_output_tokens", settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS)
    return RequestBudget(input_tokens, "UTF-8 bytes plus message allowance", output, envelope.get("reasoning_effort"),
                         int(output * capabilities.visible_fraction),
                         capabilities.context_tokens - input_tokens - output,
                         capabilities.fingerprint)
