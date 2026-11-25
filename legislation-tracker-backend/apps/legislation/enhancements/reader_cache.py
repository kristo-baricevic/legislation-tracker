"""Content identity for public bill source reviews (never private prompts)."""

import copy
import hashlib
import re

from .source_packet import canonical_json_bytes

VALIDATOR_VERSION = 2
DEPENDENCY_TRANSPORT_VERSION = 2


def remap(value, references):
    if isinstance(value, dict):
        return {remap(k, references): remap(v, references) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [remap(v, references) for v in value]
    if isinstance(value, str):
        # Keys such as src_0042:p0001 and schema enum values need the same map.
        match = re.fullmatch(r"(src_\d{4})(:p\d{4,})?", value)
        return references.get(match[1], match[1]) + (match[2] or "") if match else value
    return value


def call_identity(
    request,
    *,
    execution_version=3,
    adapter="existing",
    dependency_transport_version=DEPENDENCY_TRANSPORT_VERSION,
):
    references = {}
    envelope = copy.deepcopy(request.request_envelope)
    planning_fields = {
        "context_source_refs",
        "context_quote_ids",
        "dependencies",
        "omitted_dependency_ranges",
    }
    sources = [
        copy.deepcopy(
            {
                key: value
                for key, value in source.items()
                if not envelope.get("source_review") or key not in planning_fields
            }
        )
        for source in request.source_snapshot
    ]
    if envelope.get("source_review"):
        references = {s["source_ref"]: f"src_{i:04d}" for i, s in enumerate(sources, 1)}
        # Keep all supplied context, instructions, schemas, existing changes,
        # and bill identity. Only non-semantic locations vary across versions.
        for source in [*sources, *envelope.get("source_packet", {}).get("sources", [])]:
            source.pop("start_char", None)
            source.pop("end_char", None)
            # Whole-plan source/dependency offsets remain in its fingerprint.
            # A reusable call is identified by the actual supplied context,
            # selected quote IDs and planner version, not unrelated positions.
            for key in planning_fields:
                source.pop(key, None)
        envelope, sources = remap(envelope, references), remap(sources, references)
    # Failed reservations from the old constrained prose decoder must not block
    # dispatch of the corrected transport.
    key = {
        "validator_version": VALIDATOR_VERSION,
        "execution_version": execution_version,
        "envelope": envelope,
        "sources": sources,
        "model": request.requested_model,
        "provider": request.provider,
        "reasoning": request.reasoning_effort,
    }
    if envelope.get("dependency_review") and dependency_transport_version != 1:
        # These envelopes already contained the right schema when adapters still
        # sent the legacy one. Invalidate only that transport's cached failures;
        # retain the exact map-call identity and its reusable validated facts.
        key["dependency_transport_version"] = dependency_transport_version
    if adapter != "existing":
        key["adapter"] = adapter
    return hashlib.sha256(canonical_json_bytes(key)).hexdigest(), references
