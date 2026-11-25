"""Summarize a recorded arm without dispatching or loading provider credentials."""

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ComparisonResult:
    source: str
    adapter: str
    model: str
    variant: int
    configuration_hash: str
    calls: int
    retries: int
    elapsed_seconds: float
    input_tokens: int | None
    visible_output_tokens: int | None
    reasoning_tokens: int | None
    cost: Decimal | None
    outcomes: dict


def run_comparison(case, adapter, model, variant, budget):
    calls = case["dispatches"]
    config = {
        "adapter": adapter,
        "model": model,
        "variant": variant,
        "budget": budget,
        "source": case["manifest"]["xml_sha256"],
        "settings": case.get("settings", {}),
    }
    fingerprint = hashlib.sha256(
        json.dumps(config, sort_keys=True).encode()
    ).hexdigest()

    def total(field):
        values = [call.get(field) for call in calls]
        if any(value is None for value in values):
            return None
        return sum(values)

    costs = [call.get("cost_usd") for call in calls]
    return ComparisonResult(
        source=config["source"],
        adapter=adapter,
        model=model,
        variant=variant,
        configuration_hash=fingerprint,
        calls=len(calls),
        retries=sum(bool(call.get("retry")) for call in calls),
        elapsed_seconds=case["elapsed_seconds"],
        input_tokens=total("input_tokens"),
        visible_output_tokens=total("visible_output_tokens"),
        reasoning_tokens=total("reasoning_tokens"),
        cost=(
            None
            if None in costs
            else sum((Decimal(str(value)) for value in costs), Decimal(0))
        ),
        outcomes=case["outcomes"],
    )
