"""
Celery app for legislation-tracker-backend.
Loads config from Django settings and autodiscovers tasks in installed apps.
"""
import os

# So "celery -A config" works without exporting DJANGO_SETTINGS_MODULE each time
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

from celery import Celery
from celery.signals import task_failure

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Print at startup so it's always visible (runs when worker process loads config)
try:
    from django.conf import settings
    _key = getattr(settings, "CONGRESS_API_KEY", "") or ""
    if _key:
        print("[config] CONGRESS_API_KEY is set (length=%s)" % len(_key))
    else:
        print("[config] CONGRESS_API_KEY is NOT set — set it in .env and restart worker")
except Exception as e:
    print("[config] Could not check CONGRESS_API_KEY:", e)

# Beat schedule: poll Congress every 10 minutes
app.conf.beat_schedule = {
    "poll-congress": {
        "task": "apps.ingestion.tasks.poll_congress",
        "schedule": 600.0,  # every 10 minutes (in seconds)
        "kwargs": {"jurisdiction": "federal", "congress": 119},
    },
    "recompute-similarity-batch": {
        "task": "apps.legislation.tasks.recompute_similarity_batch",
        "schedule": 3600.0,  # every hour
        "kwargs": {"session": 119},
    },
    "poll-tracked-bills": {
        "task": "apps.ingestion.tasks.poll_tracked_bills",
        "schedule": 300.0,  # every 5 minutes (in seconds)
    },
    "dispatch-ingestion-work": {
        "task": "apps.ingestion.tasks.dispatch_ingestion_work",
        "schedule": 30.0,
    },
    "recover-stale-ingestion-work": {
        "task": "apps.ingestion.tasks.recover_stale_ingestion_work",
        "schedule": 300.0,
    },
}


@task_failure.connect
def _on_task_failure(sender, task_id, exception, args, kwargs, **kw):
    """Record failures from ingestion and legislation tasks (process_bill records itself)."""
    from apps.ingestion.tasks import _record_task_failure
    task_name = getattr(sender, "name", str(sender))
    if (
        not task_name
        or not task_name.startswith(("apps.ingestion.tasks.", "apps.legislation.tasks."))
        or task_name.endswith("process_bill")
    ):
        return
    bill_id = None
    if args and (task_name.endswith("process_bill_versions") or task_name.endswith("process_bill_votes")):
        try:
            bill_id = int(args[0])
        except (IndexError, TypeError, ValueError):
            pass
    try:
        _record_task_failure(task_id, task_name, args, kwargs, bill_id, exception)
    except Exception:
        pass


@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
