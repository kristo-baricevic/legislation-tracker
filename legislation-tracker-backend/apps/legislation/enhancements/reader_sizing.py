"""Size-based packing and lossless subdivision of reader requests."""
import copy
import math
from dataclasses import replace

from .reader_targets import snapshot_targets
from .reader_citations import bounded_reader_schema, citation_passages
from .source_packet import canonical_json_bytes


def target_output_bytes(target):
    length = max(len(target.get('original_text', '').encode()),
                 sum(b - a for a, b in target.get('evidence_ranges', [])))
    ceiling = 400 if target.get('kind') == 'line_item' else 900
    prose = min(ceiling * 4, max(200, length * 2))
    citations = min(12, max(1, math.ceil(length / 400)))
    return prose + citations * 85 + 240


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
            from .reader_discovery import discovery_schema
            selected = [copy.deepcopy(source)]
            selected[0]['review_quote_ids'] = [p['quote_id'] for p in group]
            envelope['source_packet']['review_quote_ids'] = selected[0]['review_quote_ids']
            envelope['instructions'] += '\nReview only provisions introduced in review_quote_ids; all other passages are context. Cite a reviewed passage first for each item.'
            envelope['output_schema'] = discovery_schema(selected)
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
