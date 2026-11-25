from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.ingestion import tasks as ingestion_tasks
from apps.ingestion.models import IngestionWorkItem
from apps.legislation import tasks
from apps.legislation.models import Bill, BillSimilarity

pytestmark = pytest.mark.django_db


def bills(count):
    return [
        Bill.objects.create(
            jurisdiction="federal",
            session=119,
            bill_number=f"HR {i}",
            title="Hospital education grants",
            status="Introduced",
        )
        for i in range(count)
    ]


def test_similarity_has_independent_admission_and_one_job_per_bill():
    bill = bills(1)[0]
    first = tasks.enqueue_similarity(bill)
    bill.metadata_hash = "changed"
    bill.title = "New title"
    bill.save()
    assert tasks.enqueue_similarity(bill).pk == first.pk
    work = IngestionWorkItem.objects.create(
        kind="bill",
        dedupe_key="metadata",
        source_updated_at=timezone.now(),
        payload_json={},
    )
    with patch.object(
        ingestion_tasks.process_ingestion_work_item, "apply_async", return_value=None
    ) as send:
        ingestion_tasks.dispatch_ingestion_work()
        assert [c.kwargs["args"][0] for c in send.call_args_list] == [work.pk]
        send.reset_mock()
        ingestion_tasks.dispatch_similarity_work()
        assert send.call_args.kwargs["queue"] == "similarity"
        assert send.call_args.kwargs["args"][0] == first.pk
        ingestion_tasks.dispatch_similarity_work()
        assert send.call_count == 1


def test_features_reused_and_pair_writes_batched():
    rows = bills(12)
    with patch.object(
        tasks, "_bill_similarity_features", wraps=tasks._bill_similarity_features
    ) as features:
        with CaptureQueriesContext(connection) as queries:
            tasks._schedule_similarity_for_bill_impl(rows[0].pk)
    assert features.call_count == 12
    assert BillSimilarity.objects.count() == 11
    writes = [q for q in queries if q["sql"].startswith(("INSERT", "UPDATE", "DELETE"))]
    assert len(writes) <= 6
    assert sum(q["sql"].startswith("SELECT") for q in queries) <= 12


def test_revision_during_processing_runs_one_followup(monkeypatch):
    bill = bills(1)[0]
    work = tasks.enqueue_similarity(bill)

    def revise(_):
        for title in ("Second revision", "Third revision"):
            bill.title = title
            bill.save()
            assert tasks.enqueue_similarity(bill).pk == work.pk
        return {}

    with (
        patch.object(ingestion_tasks, "_process_durable_work", side_effect=revise),
        patch.object(ingestion_tasks.dispatch_similarity_work, "apply_async"),
    ):
        assert (
            ingestion_tasks.process_ingestion_work_item(work.pk)["status"] == "requeued"
        )
    with patch.object(ingestion_tasks.dispatch_similarity_work, "apply_async"):
        assert (
            ingestion_tasks.process_ingestion_work_item(work.pk)["status"]
            == "succeeded"
        )
    assert IngestionWorkItem.objects.filter(kind="similarity").count() == 1


def test_legacy_pending_revisions_collapse_without_losing_other_work():
    from importlib import import_module

    from django.apps import apps

    bill = bills(1)[0]
    for key, status in [("old", "pending"), ("new", "pending"), ("past", "succeeded")]:
        IngestionWorkItem.objects.create(
            kind="similarity",
            dedupe_key=key,
            payload_json={"bill_id": bill.pk},
            status=status,
            source_updated_at=timezone.now(),
        )
    import_module("apps.ingestion.migrations.0009_coalesce_similarity").coalesce(
        apps, None
    )
    pending = IngestionWorkItem.objects.get(kind="similarity", status="pending")
    assert tasks.enqueue_similarity(bill).pk == pending.pk
    assert IngestionWorkItem.objects.get(status="succeeded").dedupe_key == "past"


def test_completed_unchanged_bill_does_no_pair_work():
    rows = bills(2)
    tasks._schedule_similarity_for_bill_impl(rows[0].pk)
    with CaptureQueriesContext(connection) as queries:
        result = tasks._schedule_similarity_for_bill_impl(rows[0].pk)
    assert result.get("reason") == "unchanged"
    assert not any(q["sql"].startswith(("INSERT", "UPDATE", "DELETE")) for q in queries)


def test_checkpoint_resumes_and_changed_source_restarts():
    rows = bills(6)
    first = tasks._schedule_similarity_for_bill_impl(rows[0].pk, chunk_size=2)
    assert first["has_more"]
    assert BillSimilarity.objects.count() == 2
    second = tasks._schedule_similarity_for_bill_impl(rows[0].pk, chunk_size=2)
    assert second["has_more"]
    assert BillSimilarity.objects.count() == 4
    Bill.objects.filter(pk=rows[0].pk).update(title="Completely unrelated wildlife")
    tasks._schedule_similarity_for_bill_impl(rows[0].pk, chunk_size=2)
    assert BillSimilarity.objects.count() == 2
    while tasks._schedule_similarity_for_bill_impl(rows[0].pk, chunk_size=2).get(
        "has_more"
    ):
        pass
    assert not BillSimilarity.objects.exists()


def test_changed_candidate_removes_old_pair_even_if_other_bill_unchanged():
    rows = bills(2)
    for row in rows:
        tasks._schedule_similarity_for_bill_impl(row.pk)
    Bill.objects.filter(pk=rows[1].pk).update(title="Wildlife wilderness protection")
    tasks._schedule_similarity_for_bill_impl(rows[1].pk)
    assert not BillSimilarity.objects.exists()


def test_hourly_sweep_skips_completed_unchanged_inputs(monkeypatch):
    rows = bills(2)
    for row in rows:
        tasks._schedule_similarity_for_bill_impl(row.pk)
    monkeypatch.setattr(
        "apps.ingestion.tasks.dispatch_ingestion_work.delay", lambda: None
    )
    assert tasks.recompute_similarity_batch(session=119)["enqueued"] == 0
    Bill.objects.filter(pk=rows[1].pk).update(title="Wildlife wilderness protection")
    assert tasks.recompute_similarity_batch(session=119)["enqueued"] == 1


def test_hourly_sweep_does_not_duplicate_dispatched_work(monkeypatch):
    row = bills(1)[0]
    IngestionWorkItem.objects.create(
        kind="similarity",
        dedupe_key="existing",
        source_updated_at=timezone.now(),
        payload_json={"bill_id": row.pk},
        status="dispatched",
    )
    monkeypatch.setattr(ingestion_tasks.dispatch_ingestion_work, "delay", lambda: None)
    assert tasks.recompute_similarity_batch(session=119)["enqueued"] == 0


def test_durable_continuations_finish_without_spending_retry_budget(monkeypatch):
    rows = bills(103)
    monkeypatch.setattr(tasks, "SIMILARITY_DELIVERY_SECONDS", 0)
    monkeypatch.setattr(ingestion_tasks.dispatch_ingestion_work, "delay", lambda: None)
    work = tasks.enqueue_similarity(rows[0])
    assert ingestion_tasks.process_ingestion_work_item(work.pk)["status"] == "requeued"
    work.refresh_from_db()
    assert work.attempt_count == 0
    assert BillSimilarity.objects.count() == 100
    assert ingestion_tasks.process_ingestion_work_item(work.pk)["status"] == "succeeded"
    assert BillSimilarity.objects.count() == 102


def test_pair_failure_rolls_back_features_and_checkpoint():
    from apps.legislation.models import BillSimilarityState

    rows = bills(4)
    tasks._schedule_similarity_for_bill_impl(rows[0].pk, chunk_size=1)
    cursor = BillSimilarityState.objects.get(pk=rows[0].pk).cursor
    with patch.object(
        BillSimilarity.objects, "bulk_create", side_effect=RuntimeError("interrupted")
    ):
        with pytest.raises(RuntimeError, match="interrupted"):
            tasks._schedule_similarity_for_bill_impl(rows[0].pk, chunk_size=1)
    assert BillSimilarityState.objects.get(pk=rows[0].pk).cursor == cursor
    assert BillSimilarity.objects.count() == 1
    tasks._schedule_similarity_for_bill_impl(rows[0].pk, chunk_size=1)
    assert BillSimilarity.objects.count() == 2


def test_expired_delivery_cannot_write():
    from datetime import timedelta

    rows = bills(2)
    work = IngestionWorkItem.objects.create(
        kind="similarity",
        dedupe_key="expired",
        source_updated_at=timezone.now(),
        payload_json={"bill_id": rows[0].pk},
        status="processing",
        dispatch_token="old",
        lease_expires_at=timezone.now() - timedelta(seconds=1),
    )
    assert (
        tasks._schedule_similarity_for_bill_impl(rows[0].pk, work_item=work)["reason"]
        == "superseded"
    )
    assert not BillSimilarity.objects.exists()


def test_topics_and_summary_invalidate_features():
    from apps.legislation.models import BillTopic, Topic

    rows = bills(2)
    for row in rows:
        tasks._schedule_similarity_for_bill_impl(row.pk)
    topic = Topic.objects.create(slug="shared-test", name="Shared")
    for row in rows:
        BillTopic.objects.create(bill=row, topic=topic)
    tasks._schedule_similarity_for_bill_impl(rows[0].pk)
    assert BillSimilarity.objects.get().similarity_score == 1.0
    Bill.objects.filter(pk=rows[0].pk).update(summary="Unique distinctive addition")
    tasks._schedule_similarity_for_bill_impl(rows[0].pk)
    assert BillSimilarity.objects.get().similarity_score == 0.8


def test_new_bill_fills_pairs_without_recomputing_completed_bills():
    rows = bills(2)
    for row in rows:
        tasks._schedule_similarity_for_bill_impl(row.pk)
    added = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 3",
        title="Hospital education grants",
        status="Introduced",
    )
    tasks._schedule_similarity_for_bill_impl(added.pk)
    assert BillSimilarity.objects.count() == 3
    assert tasks._schedule_similarity_for_bill_impl(rows[0].pk)["reason"] == "unchanged"


def test_contract_change_invalidates_cached_features_and_keeps_scores():
    from apps.legislation.models import BillContract

    rows = bills(2)
    old = BillContract.objects.create(
        bill=rows[0],
        contract_hash="a" * 64,
        schema_version="test",
        contract_json={"text": "Hospital education grants"},
    )
    Bill.objects.filter(pk=rows[0].pk).update(latest_contract=old)
    tasks._schedule_similarity_for_bill_impl(rows[0].pk)
    assert BillSimilarity.objects.get().similarity_score == 0.4
    new = BillContract.objects.create(
        bill=rows[0],
        contract_hash="b" * 64,
        schema_version="test",
        contract_json={"text": "Wildlife wilderness protection"},
    )
    Bill.objects.filter(pk=rows[0].pk).update(latest_contract=new)
    tasks._schedule_similarity_for_bill_impl(rows[0].pk)
    assert BillSimilarity.objects.get().similarity_score == 0.2
    with CaptureQueriesContext(connection) as queries:
        tasks._schedule_similarity_for_bill_impl(rows[0].pk)
    assert not any('"legislation_billcontract"' in q["sql"] for q in queries)
