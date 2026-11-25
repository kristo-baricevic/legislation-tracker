"""SDK clients and their event loop live for one credential-scoped delivery."""

import asyncio
import inspect
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar, copy_context
from functools import wraps

_current = ContextVar("enhancement_delivery_clients", default=None)


@contextmanager
def provider_session():
    with ExitStack() as stack:
        runner = stack.enter_context(asyncio.Runner())
        token = _current.set(({}, stack, runner))
        try:
            yield
        finally:
            _current.reset(token)


def run_async(operation):
    session = _current.get()
    return (
        session[2].run(operation, context=copy_context())
        if session
        else asyncio.run(operation)
    )


def in_provider_session():
    return _current.get() is not None


def delivery_client(factory):
    @wraps(factory)
    def get(provider, **kwargs):
        session = _current.get()
        if session is None:
            return factory(provider, **kwargs)
        clients, stack, runner = session
        key = (provider, factory, tuple(sorted(kwargs.items())))
        if key not in clients:
            client = factory(provider, **kwargs)
            clients[key] = client

            def close():
                method = getattr(client, "aclose", None) or getattr(
                    client, "close", None
                )
                if method:
                    result = method()
                    if inspect.isawaitable(result):
                        runner.run(result)

            stack.callback(close)
        return clients[key]

    return get
