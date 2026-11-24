"""Opt-in private evidence for bill-reader calls. Never capture transport headers."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
import re

from django.conf import settings
from django.utils import timezone

_capture = ContextVar("bill_enhancement_capture", default=None)


@contextmanager
def capture_step(step, owner_id):
    def persist(payload):
        from apps.legislation.models import BillEnhancementDiagnostic
        now = timezone.now()
        BillEnhancementDiagnostic.objects.update_or_create(step=step, owner_id=owner_id, defaults={
            "expires_at": now + timedelta(days=settings.LLM_DIAGNOSTIC_RETENTION_DAYS), "payload": payload})
    with capture_transport(persist if owner_id and settings.LLM_DIAGNOSTIC_RETENTION_DAYS > 0 else None):
        yield


@contextmanager
def capture_transport(sink):
    token = _capture.set(sink)
    try:
        yield
    finally:
        _capture.reset(token)


def capture_visible(messages, response_format, text, finish_reason, response_id, model, key):
    sink = _capture.get()
    if sink is None:
        return
    def redact(value):
        if isinstance(value, str):
            return value.replace(key, "[redacted]") if key else value
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, dict):
            return {name: redact(item) for name, item in value.items()}
        return value
    if text:
        text = re.sub(r"<(think|thinking|reasoning)\b[^>]*>.*?(?:</\1>|$)", "[redacted]", text,
                      flags=re.IGNORECASE | re.DOTALL)
    sink(redact({"messages": messages, "response_format": response_format, "visible_output": text,
                 "finish_reason": finish_reason, "response_id": response_id, "model": model}))
