"""Bounded similarity work. Features, pairs and checkpoints commit together."""
import hashlib
import json

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.ingestion.models import IngestionWorkItem
from .models import Bill, BillContract, BillSimilarity, BillSimilarityState


def fingerprint(bill):
    from .tasks import SIMILARITY_METHOD
    # Contracts are content-addressed. Do not read/flatten their JSON just to
    # check freshness. Topic order and unrelated bill metadata are irrelevant.
    inputs = [SIMILARITY_METHOD, bill.title, bill.summary,
        bill.latest_contract_id,
        sorted(item.topic.slug for item in bill.bill_topics.all())]
    return hashlib.sha256(json.dumps(inputs, ensure_ascii=True).encode()).hexdigest()


def run_chunk(bill_id, *, chunk_size=100, work_item=None):
    from .tasks import _bill_similarity_features, _jaccard, SIMILARITY_METHOD, SIMILARITY_MIN_SCORE
    chunk_size = max(1, min(int(chunk_size), 100))
    with transaction.atomic():
        current = None
        if work_item is not None:
            current = IngestionWorkItem.objects.select_for_update().get(pk=work_item.pk)
            if (current.status != "processing" or current.dispatch_token != work_item.dispatch_token
                or not current.lease_expires_at or current.lease_expires_at <= timezone.now()):
                return {"bill_id": bill_id, "skipped": True, "reason": "superseded"}

        # Read a tentative cursor, then lock all involved bills in ID order.
        # If another delivery advanced/reset it, retry on the next delivery.
        tentative = BillSimilarityState.objects.filter(bill_id=bill_id).first()
        cursor = tentative.cursor if tentative else 0
        source = Bill.objects.prefetch_related("bill_topics__topic").filter(pk=bill_id).first()
        if source is None:
            return {"bill_id": bill_id, "skipped": True, "reason": "not_found"}
        source_fingerprint = fingerprint(source)
        if tentative and tentative.fingerprint != source_fingerprint:
            cursor = 0
        candidate_ids = list(Bill.objects.exclude(pk=bill_id).filter(pk__gt=cursor)
            .order_by("pk").values_list("pk", flat=True)[:chunk_size + 1])
        has_more = len(candidate_ids) > chunk_size
        candidate_ids = candidate_ids[:chunk_size]
        rows = list(Bill.objects.select_for_update().filter(pk__in=[bill_id, *candidate_ids])
            .order_by("pk").prefetch_related("bill_topics__topic"))
        states = BillSimilarityState.objects.in_bulk([row.pk for row in rows])
        source = next((row for row in rows if row.pk == bill_id), None)
        if source is None:
            return {"bill_id": bill_id, "skipped": True, "reason": "not_found"}
        state = states.get(bill_id)
        # Source changed or another job advanced while locks were acquired.
        locked_fingerprint = fingerprint(source)
        if (locked_fingerprint != source_fingerprint or
            (state and state.fingerprint == locked_fingerprint and state.cursor != cursor)):
            if current:
                _continue(current)
            return {"bill_id": bill_id, "has_more": True, "computed": 0, "removed": 0}
        if state and state.completed_fingerprint == locked_fingerprint:
            return {"bill_id": bill_id, "skipped": True, "reason": "unchanged"}

        revisions = {row.pk: fingerprint(row) for row in rows}
        dirty = [row for row in rows if row.pk not in states or
            states[row.pk].fingerprint != revisions[row.pk]]
        contracts = BillContract.objects.only("id", "contract_json").in_bulk(
            {row.latest_contract_id for row in dirty if row.latest_contract_id})
        new, changed = [], []
        for row in rows:
            revision = revisions[row.pk]
            cached = states.get(row.pk)
            if cached and cached.fingerprint == revision:
                continue
            if row.latest_contract_id:
                row.latest_contract = contracts[row.latest_contract_id]
            features = {key: sorted(value) for key, value in _bill_similarity_features(row).items()}
            if cached is None:
                cached = BillSimilarityState(bill_id=row.pk)
                states[row.pk] = cached
                new.append(cached)
            else:
                changed.append(cached)
            cached.fingerprint = revision
            cached.features = features
            cached.cursor = 0
            cached.completed_fingerprint = ""
        BillSimilarityState.objects.bulk_create(new, batch_size=100)
        BillSimilarityState.objects.bulk_update(changed,
            ["fingerprint", "features", "cursor", "completed_fingerprint"], batch_size=100)
        state = states[bill_id]
        left = {key: set(value) for key, value in state.features.items()}
        pairs, discard = [], []
        for candidate_id in candidate_ids:
            if candidate_id not in states:  # A concurrent deletion is harmless.
                continue
            right = {key: set(value) for key, value in states[candidate_id].features.items()}
            score = round(.6 * _jaccard(left["topics"], right["topics"])
                + .4 * _jaccard(left["tokens"], right["tokens"]), 6)
            if score < SIMILARITY_MIN_SCORE:
                discard.append(candidate_id)
            else:
                pairs.append(BillSimilarity(bill_a_id=min(bill_id, candidate_id),
                    bill_b_id=max(bill_id, candidate_id), method=SIMILARITY_METHOD,
                    similarity_score=score))
        BillSimilarity.objects.bulk_create(pairs, batch_size=100, update_conflicts=True,
            unique_fields=["bill_a", "bill_b", "method"], update_fields=["similarity_score", "computed_at"])
        removed = 0
        if discard:
            removed, _ = BillSimilarity.objects.filter(method=SIMILARITY_METHOD).filter(
                Q(bill_a_id=bill_id, bill_b_id__in=discard) |
                Q(bill_b_id=bill_id, bill_a_id__in=discard)).delete()
        state.cursor = candidate_ids[-1] if candidate_ids else cursor
        if not has_more:
            state.completed_fingerprint = state.fingerprint
        state.save(update_fields=["cursor", "completed_fingerprint"])
        if has_more and current:
            _continue(current)
        return {"bill_id": bill_id, "computed": len(pairs), "removed": removed, "has_more": has_more}


def _continue(work):
    # The durable dispatcher resets attempts and requeues changed payloads.
    work.payload_json = {**work.payload_json, "step": work.payload_json.get("step", 0) + 1}
    work.save(update_fields=["payload_json"])
