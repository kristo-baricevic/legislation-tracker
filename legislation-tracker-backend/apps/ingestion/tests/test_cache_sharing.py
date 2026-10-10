"""Opt-in isolated real Redis command-to-HTTP contract; never uses configured Redis."""

import os
import shutil
import subprocess
import sys
import uuid

import pytest


def test_isolated_redis_command_snapshot_and_lock_cross_process(tmp_path):
    binary = shutil.which("redis-server")
    isolated_url = os.environ.get("TELEMETRY_TEST_REDIS_URL")
    if isolated_url and isolated_url != "redis://127.0.0.1:15449/0":
        pytest.fail("Only the dedicated isolated Redis test port is permitted")
    if not binary and not isolated_url:
        pytest.skip("redis-server unavailable; no shared-cache validation claimed")
    socket_path = str(tmp_path / "redis.sock")
    if not isolated_url:
        subprocess.run(
            [
                "rtk",
                "proxy",
                binary,
                "--port",
                "0",
                "--unixsocket",
                socket_path,
                "--daemonize",
                "yes",
                "--save",
                "",
                "--appendonly",
                "no",
                "--dir",
                str(tmp_path),
                "--pidfile",
                str(tmp_path / "redis.pid"),
            ],
            check=True,
        )
    import redis

    server = (
        redis.Redis.from_url(isolated_url)
        if isolated_url
        else redis.Redis(unix_socket_path=socket_path)
    )
    location = isolated_url or f"unix://{socket_path}"
    cache_prefix = "telemetry-test-" + uuid.uuid4().hex
    prefix = f"""
import django
from django.conf import settings
import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.test'
django.setup()
settings.CACHES = {{'default': {{'BACKEND': 'django.core.cache.backends.redis.RedisCache', 'LOCATION': '{location}', 'KEY_PREFIX': '{cache_prefix}'}}}}
"""
    writer = prefix + """
from django.core.management import call_command
from django.utils import timezone
import apps.ingestion.management.commands.check_ingestion_readiness as command
command.scan_inventory = lambda *args: {'complete': True, 'checked_completed_at': timezone.now().isoformat(), 'missing_unqueued_metadata': 3, 'pages_examined': 0}
command.observe_discoverable = lambda *args, **kwargs: {'ready_to_start': None, 'incremental_discoverable_count_available': False}
call_command('check_ingestion_readiness', congress=119)
"""
    reader = prefix + """
from types import SimpleNamespace
from rest_framework.test import APIRequestFactory, force_authenticate
from apps.ingestion.telemetry_views import SourceReadinessView
from django.core.cache import cache
from apps.ingestion.source_inventory import snapshot_key
request = APIRequestFactory().get('/?congress=119')
force_authenticate(request, user=SimpleNamespace(is_staff=True, is_authenticated=True))
response = SourceReadinessView.as_view()(request)
assert response.data['available']
assert response.data['missing_unqueued_metadata'] == 3
assert response.data['ready_to_start'] is None
assert not cache.add(snapshot_key('federal', 119) + ':scan', True, 180)
print('Cross-process command snapshot and scan lock verified')
"""
    try:
        env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.test"}
        subprocess.run(
            ["rtk", "proxy", sys.executable, "-c", writer],
            check=True,
            env=env,
            capture_output=True,
        )
        result = subprocess.run(
            ["rtk", "proxy", sys.executable, "-c", reader],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )
        assert "verified" in result.stdout
    finally:
        server.delete(
            f"{cache_prefix}:1:ingestion-readiness:federal:119:hr,s",
            f"{cache_prefix}:1:ingestion-readiness:federal:119:hr,s:scan",
        )
        if not isolated_url:
            server.shutdown(nosave=True)
