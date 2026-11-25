"""Hermetic defaults for pytest; no local Redis or broker is required."""

from .dev import *  # noqa: F401, F403

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "legislation-tracker-tests",
    }
}
CACHES["congress_coordination"] = CACHES["default"]
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
