"""
Celery app for legislation-tracker-backend.
Loads config from Django settings and autodiscovers tasks in installed apps.
"""
from celery import Celery

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
