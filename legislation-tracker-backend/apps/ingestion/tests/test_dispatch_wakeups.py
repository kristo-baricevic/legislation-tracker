from django.core.cache import cache
from apps.ingestion.tasks import dispatch_ingestion_work
from apps.legislation.tasks import run_bill_enhancement_attempt
from celery import Task
import pytest


def test_burst_of_wakeups_publishes_one_message_per_queue():
    cache.clear()
    with dispatch_ingestion_work.app.connection_for_write() as connection:
        normal = connection.SimpleQueue("celery")
        research = connection.SimpleQueue("research")
        normal.clear()
        research.clear()
        try:
            for _ in range(100):
                dispatch_ingestion_work.delay()
            dispatch_ingestion_work.apply_async(kwargs={"batch_size": 0}, queue="research")
            assert normal.qsize() == 1
            assert research.qsize() == 1
        finally:
            normal.clear()
            research.clear()
            cache.clear()


def test_enhancement_delivery_does_not_enter_ingestion_queue():
    with run_bill_enhancement_attempt.app.connection_for_write() as connection:
        normal = connection.SimpleQueue("celery")
        enhancements = connection.SimpleQueue("enhancements")
        normal.clear()
        enhancements.clear()
        try:
            run_bill_enhancement_attempt.apply_async(args=[999, "test-token"])
            assert normal.qsize() == 0
            assert enhancements.qsize() == 1
        finally:
            normal.clear()
            enhancements.clear()


def test_failed_wakeup_can_be_published_after_cooldown(monkeypatch):
    cache.clear()
    with dispatch_ingestion_work.app.connection_for_write() as connection:
        queue = connection.SimpleQueue("celery")
        queue.clear()
        try:
            with monkeypatch.context() as scoped:
                def fail(*args, **kwargs):
                    raise ConnectionError("broker unavailable")
                scoped.setattr(Task, "apply_async", fail)
                with pytest.raises(ConnectionError):
                    dispatch_ingestion_work.delay()
            dispatch_ingestion_work.delay()
            assert queue.qsize() == 0
            cache.touch("dispatcher-wakeup:apps.ingestion.tasks.dispatch_ingestion_work:celery", timeout=-1)
            dispatch_ingestion_work.delay()
            assert queue.qsize() == 1
        finally:
            queue.clear()
            cache.clear()
