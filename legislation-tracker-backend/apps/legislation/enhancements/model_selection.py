"""Account selection scoped to a single planning operation, never process-wide."""
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings


_target = ContextVar("enhancement_target", default=None)
_owned_target = ContextVar("enhancement_owned_token_target", default=None)


def owned_token_target():
    pinned = _owned_target.get()
    return settings.LLM_READER_OWNED_TOKEN_TARGET if pinned is None else pinned


def default_target():
    return settings.LLM_ENHANCEMENT_PROVIDER, settings.LLM_ENHANCEMENT_MODEL


def target():
    return _target.get() or default_target()


def reasoning_effort():
    """Keep default OpenRouter reasoning bounded and visible in estimates.

    The legacy `none` meant provider default, not disabled. That left free
    reasoning models consuming the complete output allowance without an answer.
    Explicit configured efforts remain unchanged.
    """
    effort = settings.LLM_ENHANCEMENT_REASONING_EFFORT
    return 'low' if target()[0] == 'openrouter' and effort == 'none' else effort


def catalog():
    pairs = dict.fromkeys([default_target(), ("anthropic", "claude-haiku-5-5"),
                           ("gemini", "gemini-4-hydrogen")])
    if default_target()[0] != "openai":
        pairs[("openai", "gpt-6-luna")] = None
    for pair in settings.LLM_READER_MODEL_CAPACITIES:
        provider, separator, model = pair.partition("/")
        if separator and model and provider in {"openai", "anthropic", "gemini"}:
            pairs[(provider, model)] = None
    from .openrouter_catalog import entries
    metadata = entries()
    pairs.update(dict.fromkeys(("openrouter", model) for model in metadata))
    excluded = set(settings.LLM_OPENROUTER_EXCLUDED_MODELS) | {"openrouter/free"}
    choices = []
    for provider, model in pairs:
        if provider == "openrouter":
            if model in excluded or (model.endswith(":free") and model not in metadata):
                continue
            if model in metadata:
                choices.append(metadata[model])
                continue
        choices.append({"provider": provider, "model": model, "free": False})
    return choices


def credential_target(credential):
    if credential is None:
        return default_target()
    return credential.provider, credential.selected_model or (
        default_target()[1] if credential.provider == default_target()[0] else "")


def selectable(pair):
    return any((entry["provider"], entry["model"]) == pair for entry in catalog())


@contextmanager
def planning_for(pair, *, owned_target=None):
    from .openrouter_catalog import catalog_scope
    token = _target.set(pair)
    chunk_token = _owned_target.set(owned_target) if owned_target is not None else None
    try:
        with catalog_scope():
            yield
    finally:
        _target.reset(token)
        if chunk_token is not None:
            _owned_target.reset(chunk_token)
