from types import SimpleNamespace

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from config import health


def test_liveness_endpoint_does_not_depend_on_external_services():
    response = APIClient().get("/health/live/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_endpoint_reports_each_required_dependency(monkeypatch):
    monkeypatch.setattr(health, "check_database", lambda: None)
    monkeypatch.setattr(health, "check_cache", lambda: None)
    monkeypatch.setattr(health, "check_storage", lambda: None)

    response = APIClient().get("/health/")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {
            "database": "ok",
            "cache": "ok",
            "storage": "ok",
            "llm_enhancements": "disabled",
        },
    }


def test_readiness_endpoint_is_unavailable_when_a_dependency_fails(monkeypatch):
    monkeypatch.setattr(health, "check_database", lambda: None)
    monkeypatch.setattr(
        health, "check_cache", lambda: (_ for _ in ()).throw(RuntimeError("redis down"))
    )
    monkeypatch.setattr(health, "check_storage", lambda: None)

    response = APIClient().get("/health/")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {
            "database": "ok",
            "cache": "error",
            "storage": "ok",
            "llm_enhancements": "disabled",
        },
    }


def test_storage_check_raises_when_the_bucket_probe_fails(monkeypatch):
    class Client:
        def head_bucket(self, **kwargs):
            raise RuntimeError("bucket is unavailable")

    storage = SimpleNamespace(
        bucket_name="documents",
        connection=SimpleNamespace(meta=SimpleNamespace(client=Client())),
        exists=lambda name: False,
    )
    monkeypatch.setattr(health, "default_storage", storage)

    with pytest.raises(RuntimeError, match="bucket is unavailable"):
        health.check_storage()


def test_cors_does_not_trust_every_chrome_extension_by_default():
    assert settings.CORS_ALLOWED_ORIGIN_REGEXES == []
