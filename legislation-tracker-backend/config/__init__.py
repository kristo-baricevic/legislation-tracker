"""
Load Celery app when Django starts so that shared_task decorators use it.
"""
from .celery import app as celery_app

__all__ = ("celery_app",)
