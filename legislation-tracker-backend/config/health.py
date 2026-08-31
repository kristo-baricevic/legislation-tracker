"""Small, dependency-aware health checks for container and extension clients."""

import uuid
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import connections
from django.http import JsonResponse

from apps.accounts.llm_credentials import llm_feature_configuration_errors


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
    """Verify the backing bucket or local storage root, not a missing object."""
    connection = getattr(default_storage, "connection", None)
    bucket_name = getattr(default_storage, "bucket_name", None)
    client = getattr(getattr(connection, "meta", None), "client", None)
    if client is not None and bucket_name:
        client.head_bucket(Bucket=bucket_name)
        return

    location = getattr(default_storage, "location", None)
    if location:
        if not Path(location).is_dir():
            raise RuntimeError("local document storage directory is unavailable")
        return

    raise RuntimeError("storage backend does not support a readiness probe")


def check_llm_enhancements():
    """Report capability without decrypting a key or contacting a provider."""
    if not settings.LLM_ENHANCEMENTS_ENABLED:
        return "disabled"
    if llm_feature_configuration_errors(
        production=settings.LLM_ENHANCEMENT_PRODUCTION_SECURITY_REQUIRED
    ):
        raise RuntimeError("LLM enhancement configuration is unsafe")
    return "ok"


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

    try:
        checks["llm_enhancements"] = check_llm_enhancements()
    # Readiness must fail closed for any unsafe or malformed capability config.
    except Exception:  # noqa: BLE001
        checks["llm_enhancements"] = "error"

    status = (
        "ok"
        if all(value in {"ok", "disabled"} for value in checks.values())
        else "unavailable"
    )
    return JsonResponse(
        {"status": status, "checks": checks},
        status=200 if status == "ok" else 503,
    )
