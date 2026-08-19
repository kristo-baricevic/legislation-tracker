"""Small, dependency-aware health checks for container and extension clients."""
import uuid

from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import connections
from django.http import JsonResponse


def check_database():
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()


def check_cache():
    key = f"healthcheck:{uuid.uuid4().hex}"
    value = "ok"
    cache.set(key, value, timeout=10)
    try:
        if cache.get(key) != value:
            raise RuntimeError("cache read did not return its health-check value")
    finally:
        cache.delete(key)


def check_storage():
    # A read-only probe confirms the configured storage connection without
    # leaving a health-check object in the documents bucket.
    default_storage.exists("healthcheck/.probe")


def live(request):
    """Process liveness: safe for restarts while dependencies are recovering."""
    return JsonResponse({"status": "ok"})


def ready(request):
    """Readiness: return 503 unless database, cache, and storage are usable."""
    checks = {}
    for name, check in (
        ("database", check_database),
        ("cache", check_cache),
        ("storage", check_storage),
    ):
        try:
            check()
        except Exception:
            checks[name] = "error"
        else:
            checks[name] = "ok"

    status = "ok" if all(value == "ok" for value in checks.values()) else "unavailable"
    return JsonResponse(
        {"status": status, "checks": checks},
        status=200 if status == "ok" else 503,
    )
