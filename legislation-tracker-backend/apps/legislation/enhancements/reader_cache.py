"""Content identity for public bill source reviews (never private prompts)."""
import copy
import hashlib
import re

from .source_packet import canonical_json_bytes

VALIDATOR_VERSION = 2


def remap(value, references):
    if isinstance(value, dict):
        return {remap(k, references): remap(v, references) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [remap(v, references) for v in value]
    if isinstance(value, str):
        # Keys such as src_0042:p0001 and schema enum values need the same map.
        match = re.fullmatch(r'(src_\d{4})(:p\d{4,})?', value)
        return references.get(match[1], match[1]) + (match[2] or '') if match else value
    return value


def call_identity(request):
    references = {}
    envelope = copy.deepcopy(request.request_envelope)
    sources = copy.deepcopy(request.source_snapshot)
    if envelope.get('source_review'):
        references = {s['source_ref']: f'src_{i:04d}' for i, s in enumerate(sources, 1)}
        # Keep all supplied context, instructions, schemas, existing changes,
        # and bill identity. Only non-semantic locations vary across versions.
        for source in [*sources, *envelope.get('source_packet', {}).get('sources', [])]:
            source.pop('start_char', None)
            source.pop('end_char', None)
        envelope, sources = remap(envelope, references), remap(sources, references)
    key = {'validator_version': VALIDATOR_VERSION, 'execution_version': 2, 'envelope': envelope,
           'sources': sources, 'model': request.requested_model,
           'provider': request.provider, 'reasoning': request.reasoning_effort}
    return hashlib.sha256(canonical_json_bytes(key)).hexdigest(), references
