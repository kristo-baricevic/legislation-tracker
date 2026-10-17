"""Deterministic provider used only by the explicitly gated E2E settings."""

from __future__ import annotations

import time

from ..schema import OUTPUT_SCHEMA_VERSION
from .base import CredentialCheck, ProviderResult, ProviderUsage


class E2EEnhancementProvider:
    provider_name = "e2e"

    def generate_provisions(self, *, api_key, request, timeout_seconds):
        time.sleep(0.5)
        rows = []
        for unit in request.request_envelope["source_first_payload"]["units"]:
            rows.append(
                {
                    "unit_id": unit["id"],
                    "status": "explained",
                    "summary": "The Secretary must award $100 in grants to rural hospitals.",
                    "details": [],
                    "unresolved_reason": None,
                    "coverage_items": [
                        {
                            "item_id": item["id"],
                            "status": "explained",
                            "claim_indexes": [0],
                            "explanation_indexes": [0],
                            "reason": None,
                        }
                        for item in unit["source_checklist"]
                    ],
                    "claims": [
                        {
                            "actor": "The Secretary",
                            "action": "award grants to rural hospitals",
                            "modality": "required",
                            "money": [
                                {
                                    "amount": "100",
                                    "currency": "USD",
                                    "measure": "grant",
                                    "comparator": "exact",
                                    "purpose": "Grants to rural hospitals",
                                    "period": None,
                                    "base": None,
                                }
                            ],
                            "conditions": None,
                            "exceptions": [],
                            "evidence_ids": unit["own_passage_ids"],
                        }
                    ],
                }
            )
        return ProviderResult(
            {"provisions": rows},
            ProviderUsage(10, 10, 20),
            "e2e-source-first",
            "e2e-model",
        )

    def repair_provisions(self, **kwargs):
        return self.generate_provisions(**kwargs)

    def generate_synopsis(self, *, api_key, request, timeout_seconds):
        rows = request.request_envelope["source_first_payload"]["explanations"]
        return ProviderResult(
            {
                "text": " ".join(r["summary"] for r in rows),
                "explanation_ids": [r["unit_id"] for r in rows],
            },
            ProviderUsage(5, 5, 10),
            "e2e-synopsis",
            "e2e-model",
        )

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
                "schema_version": OUTPUT_SCHEMA_VERSION,
                "overview": [
                    {
                        "text": (
                            "The bill directs the Secretary to award grants to "
                            "rural hospitals."
                        ),
                        "source_refs": [source_ref],
                        "source_quotes": [
                            {
                                "source_ref": source_ref,
                                "quote": request.source_snapshot[0]["quoted_text"][
                                    :800
                                ],
                            }
                        ],
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
