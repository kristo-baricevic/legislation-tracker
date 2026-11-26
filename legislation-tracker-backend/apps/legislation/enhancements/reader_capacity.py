"""Conservative planning limits, optionally overridden for a provider/model pair.

UTF-8 bytes are an upper-bound input estimate, not an exact tokenizer count.
Unspecified reasoning means provider default, NOT disabled reasoning.
"""

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


def schema_fits(schema, provider):
    """Apply documented grammar limits to the nonrecursive staged wire schema."""
    if not schema or provider not in {"openai", "openrouter", "anthropic"}:
        return True
    from .providers.harness import staged_wire_schema

    unions = enums = properties = optional = 0
    pending = [(staged_wire_schema(schema), 0)]
    while pending:
        node, depth = pending.pop()
        fields = node.get("properties", {})
        properties += len(fields)
        optional += len(fields.keys() - node.get("required", [])) if fields else 0
        unions += int("anyOf" in node or isinstance(node.get("type"), list))
        choices = node.get("enum", [])
        enums += len(choices)
        if provider == "anthropic":
            if unions > 16 or optional > 24:
                return False
        elif properties > 5000 or enums > 1000 or depth > 10:
            return False
        pending.extend((v, depth + 1) for v in fields.values())
        if "items" in node:
            pending.append((node["items"], depth + 1))
        pending.extend((v, depth) for v in node.get("anyOf", []))
        pending.extend((v, depth) for v in node.get("$defs", {}).values())
    return True


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
        and schema_fits(envelope.get("output_schema"), pair[0])
        and budget.max_output_tokens <= limits.output_tokens
        and budget.context_margin >= 0
    )
