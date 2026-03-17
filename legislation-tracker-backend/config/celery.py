"""
Celery app for legislation-tracker-backend.
Loads config from Django settings and autodiscovers tasks in installed apps.
"""
from celery import Celery
from celery.signals import task_failure

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Beat schedule: poll Congress every 10 minutes
app.conf.beat_schedule = {
    "poll-congress": {
        "task": "apps.ingestion.tasks.poll_congress",
        "schedule": 600.0,  # every 10 minutes (in seconds)
        "options": {"kwargs": {"jurisdiction": "federal", "congress": 119}},
    },
}


@task_failure.connect
def _on_task_failure(sender, task_id, exception, args, kwargs, **kw):
    """Record final task failure to IngestionTaskFailure for ingestion tasks (except process_bill which records itself)."""
    from apps.ingestion.tasks import _record_task_failure
    task_name = getattr(sender, "name", str(sender))
    if not task_name or "ingestion" not in task_name or task_name.endswith("process_bill"):
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
