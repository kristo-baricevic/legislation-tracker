"""Deterministic provider used only by the explicitly gated E2E settings."""

from __future__ import annotations

import time

from .base import CredentialCheck, ProviderResult, ProviderUsage


class E2EEnhancementProvider:
    provider_name = "e2e"

    def validate_credential(
        self,
        *,
        api_key: str,
        requested_model: str,
        timeout_seconds: int,
    ) -> CredentialCheck:
        return CredentialCheck(valid=api_key.startswith("e2e-"))

    def enhance_bill(self, *, api_key: str, request, timeout_seconds: int):
        # Keep the real broker/worker/poll path observable in Playwright.
        time.sleep(0.5)
        source_ref = request.source_snapshot[0]["source_ref"]
        return ProviderResult(
            output={
                "schema_version": "1.1",
                "overview": [
                    {
                        "text": (
                            "The bill directs the Secretary to award grants to "
                            "rural hospitals."
                        ),
                        "source_refs": [source_ref],
                    }
                ],
                "key_impacts": [],
                "obligations": [],
                "funding_and_timing": [],
                "uncertain_language": [],
            },
            usage=ProviderUsage(
                input_tokens=request.estimated_input_tokens,
                output_tokens=24,
                total_tokens=request.estimated_input_tokens + 24,
            ),
            response_id="e2e-response",
            resolved_model="e2e-model-v1",
        )
