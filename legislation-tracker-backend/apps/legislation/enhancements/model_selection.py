"""Account selection scoped to a single planning operation, never process-wide."""
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings


_target = ContextVar("enhancement_target", default=None)


def default_target():
    return settings.LLM_ENHANCEMENT_PROVIDER, settings.LLM_ENHANCEMENT_MODEL


def target():
    return _target.get() or default_target()


def catalog():
    pairs = dict.fromkeys([default_target(), ("anthropic", "claude-haiku-5-5"),
                           ("gemini", "gemini-4-hydrogen"), ("openrouter", "openrouter/free")])
    return [{"provider": p, "model": m, "free": (p, m) == ("openrouter", "openrouter/free")}
            for p, m in pairs]


def credential_target(credential):
    if credential is None:
        return default_target()
    return credential.provider, credential.selected_model or (
        default_target()[1] if credential.provider == default_target()[0] else "")


def selectable(pair):
    return any((entry["provider"], entry["model"]) == pair for entry in catalog())


@contextmanager
def planning_for(pair):
    token = _target.set(pair)
    try:
        yield
    finally:
        _target.reset(token)
