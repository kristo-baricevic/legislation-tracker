"""Size-based packing and lossless subdivision of reader requests."""
import copy
import math
from dataclasses import dataclass, replace

from .reader_targets import snapshot_targets
from .reader_citations import bounded_reader_schema, citation_passages
from .source_packet import canonical_json_bytes


@dataclass(frozen=True)
class _SizingRequest:
    source_snapshot: list
    request_envelope: dict
    request_bytes: bytes = b''
    estimated_input_tokens: int = 0


def pack_source_review(source, envelope):
    from .reader_capacity import fits, capacity
    from .source_packet import PreflightUnavailable
    pending = [_SizingRequest([source], envelope)]
    packed = []
    while pending:
        request = pending.pop(0)
        limits = capacity(envelope.get('provider'), envelope.get('requested_model'))
        allowance = source_output_allowance(request.source_snapshot, provider=envelope.get('provider'), model=envelope.get('requested_model'))
        request.request_envelope['max_output_tokens'] = min(allowance, limits['output_tokens'])
        if not fits(request.request_envelope):
            # Ownership splits do not remove legal context. Do not pretend they
            # can repair input overflow by silently throwing away conditions.
            raise PreflightUnavailable('Source context exceeds model capacity', reason='request_too_large')
        if allowance > limits['output_tokens']:
            children = split_reader_request(request)
            if not children:
                raise PreflightUnavailable('One source obligation exceeds output capacity', reason='request_too_large')
            pending[0:0] = children
        else:
            packed.append((request.source_snapshot, request.request_envelope))
    return packed


def source_output_allowance(sources, *, provider=None, model=None):
    """Budget the owned prose, citations and per-passage coverage decisions."""
    from .reader_capacity import capacity
    from .reader_discovery import money_candidates
    estimated = 200
    for source in sources:
        owned = source.get('review_quote_ids')
        passages = [p for p in citation_passages(source) if p['quote_id'] and (owned is None or p['quote_id'] in owned)]
        for p in passages:
            # Text size, not a fixed provision count. Dense money clauses also
            # need a separate financial explanation and amount field.
            size = len(p['text'].encode())
            estimated += 100 + min(650, max(200, size))
        estimated += 700 * len(money_candidates([source]))
    return max(8000, math.ceil(estimated / capacity(provider, model)['visible_fraction'] / 1000) * 1000)


def select_review_units(request, quote_ids):
    """Narrow output ownership; retain full legal context and stable citations.

    Do not trim arbitrary neighboring paragraphs: an exception anywhere in the
    section can govern the selected provision. Input overflow is not repaired by
    this operation; output overflow is repaired by reducing required findings.
    """
    from .reader_discovery import discovery_schema
    from .reader_capacity import capacity
    selected = copy.deepcopy(request.source_snapshot)
    selected[0]['review_quote_ids'] = list(quote_ids)
    envelope = copy.deepcopy(request.request_envelope)
    envelope['source_packet']['review_quote_ids'] = list(quote_ids)
    note = '\nReview only provisions introduced in review_quote_ids; all other passages are context. Cite a reviewed passage first for each item.'
    if note not in envelope['instructions']:
        envelope['instructions'] += note
    envelope['output_schema'] = discovery_schema(selected)
    provider, model = envelope.get('provider'), envelope.get('requested_model')
    envelope['max_output_tokens'] = min(capacity(provider, model)['output_tokens'], source_output_allowance(selected, provider=provider, model=model))
    encoded = canonical_json_bytes(envelope)
    return replace(request, source_snapshot=selected, request_envelope=envelope,
        request_bytes=encoded, estimated_input_tokens=len(encoded))


def target_output_bytes(target):
    length = max(len(target.get('original_text', '').encode()),
                 sum(b - a for a, b in target.get('evidence_ranges', [])))
    ceiling = 400 if target.get('kind') == 'line_item' else 900
    prose = min(ceiling * 4, max(200, length * 2))
    citations = min(12, max(1, math.ceil(length / 400)))
    return prose + citations * 85 + 240


def recover_output_limit(request):
    """Split first; an indivisible unit gets at most one larger output allowance.

    The durable dispatcher still checks the original confirmed token/call budget.
    Nothing increases that authorization or retries a timeout/unknown outcome.
    """
    children = split_reader_request(request)
    if children:
        return children
    from .reader_capacity import capacity, fits
    envelope = copy.deepcopy(request.request_envelope)
    maximum = capacity(envelope.get('provider'), envelope.get('requested_model'))['output_tokens']
    if envelope.get('max_output_tokens', maximum) >= maximum:
        return ()
    envelope['max_output_tokens'] = maximum
    if not fits(envelope, provider=envelope.get('provider'), model=envelope.get('requested_model')):
        return ()
    encoded = canonical_json_bytes(envelope)
    return (replace(request, request_envelope=envelope, request_bytes=encoded, estimated_input_tokens=len(encoded)),)


def split_reader_request(request):
    """Split obligations, not their governing source text or conditions."""
    sources = request.source_snapshot
    targets = snapshot_targets(sources)
    if request.request_envelope.get('source_review'):
        source = sources[0]
        allowed = source.get('review_quote_ids')
        passages = [p for p in citation_passages(source) if p['quote_id'] and (allowed is None or p['quote_id'] in allowed)]
        if len(passages) < 2:
            return ()
        weights = [len(p['text'].encode()) for p in passages]
        units = passages
    else:
        if len(targets) < 2:
            return ()
        weights = [target_output_bytes(t) for t in targets]
        units = targets
    # Closest weighted midpoint, always making progress on both sides.
    pivot = min(range(1, len(units)), key=lambda i: abs(sum(weights[:i]) - sum(weights) / 2))
    results = []
    for group in (units[:pivot], units[pivot:]):
        envelope = copy.deepcopy(request.request_envelope)
        if request.request_envelope.get('source_review'):
            results.append(select_review_units(request, [p['quote_id'] for p in group]))
            continue
        else:
            ids = {t['target_id'] for t in group}
            selected = []
            for s in sources:
                kept = [t for t in s.get('reader_targets', []) if t['target_id'] in ids]
                if kept:
                    selected.append({**s, 'reader_targets': kept})
            refs = {s['source_ref'] for s in selected}
            envelope['source_packet']['sources'] = [s for s in envelope['source_packet']['sources'] if s['source_ref'] in refs]
            for wire in envelope['source_packet']['sources']:
                if 'reader_targets' in wire:
                    wire['reader_targets'] = [t for t in wire['reader_targets'] if t['target_id'] in ids]
            envelope['source_packet']['target_citations'] = [t for t in envelope['source_packet']['target_citations'] if t['target_id'] in ids]
            envelope['output_schema'] = bounded_reader_schema(selected, group, {s['source_ref']: citation_passages(s) for s in selected})
        encoded = canonical_json_bytes(envelope)
        results.append(replace(request, source_snapshot=selected, request_envelope=envelope,
                               request_bytes=encoded, estimated_input_tokens=len(encoded)))
    return tuple(results)
