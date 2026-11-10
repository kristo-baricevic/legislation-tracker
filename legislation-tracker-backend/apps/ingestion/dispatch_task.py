"""Bound scheduler notifications; durable database work is never discarded."""
import logging

from celery import Task
from django.core.cache import cache

logger = logging.getLogger(__name__)


class CoalescedDispatcherTask(Task):
    abstract = True

    def before_start(self, task_id, args, kwargs):
        # Research has a single admission slot and chains one bounded page at a
        # time. Release its queued-wakeup marker when consumed so a fast page can
        # schedule the next dispatch; ordinary ingestion keeps its cooldown.
        if (self.request.delivery_info or {}).get('routing_key') == 'research':
            try:
                cache.delete(f'dispatcher-wakeup:{self.name}:research')
            except Exception:
                logger.exception('Could not release research wake-up marker')

    def apply_async(self, args=None, kwargs=None, **options):
        # Separate research wake-ups from ordinary ingestion. Leave the atomic
        # cooldown in place after delivery so bursts cannot refill the broker.
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
