"""Bound scheduler notifications; durable database work is never discarded."""
import logging

from celery import Task
from django.core.cache import cache

logger = logging.getLogger(__name__)


class CoalescedDispatcherTask(Task):
    abstract = True

    def before_start(self, task_id, args, kwargs):
        # Coalesce queued notifications, not completed work. Once consumed,
        # a worker finishing a stage must be able to request an immediate refill.
        queue = (self.request.delivery_info or {}).get('routing_key') or self.app.conf.task_default_queue
        try:
            cache.delete(f'dispatcher-wakeup:{self.name}:{queue}')
        except Exception:
            logger.exception('Could not release dispatcher wake-up marker')

    def apply_async(self, args=None, kwargs=None, **options):
        # Separate research wake-ups from ordinary ingestion. Coalesce bursts
        # while a notification is waiting for delivery.
        # Expiry plus Beat's periodic wake recovers crashes/publish failures.
        queue = options.get("queue") or self.app.conf.task_default_queue
        key = f"dispatcher-wakeup:{self.name}:{queue}"
        try:
            if not cache.add(key, True, timeout=30):
                return None
        except Exception:
            logger.exception("Dispatcher wake-up unavailable; periodic scheduling will retry")
            return None
        return super().apply_async(args=args, kwargs=kwargs, **options)


class RefillIngestionTask(Task):
    abstract = True

    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        # Run after task transactions have committed, including early retry,
        # dead-letter and awaiting-source returns. Beat recovers hard kills.
        from .models import IngestionWorkItem
        from .tasks import dispatch_ingestion_work

        work_id = kwargs.get('work_item_id', args[0] if args else None)
        try:
            released = IngestionWorkItem.objects.filter(pk=work_id).exclude(
                kind__in=['representative_research', 'similarity']
            ).exclude(status__in=['processing', 'dispatched']).exists()
            if released:
                dispatch_ingestion_work.delay()
        except Exception:
            logger.exception('Could not refill ingestion workers; periodic dispatch will recover')
