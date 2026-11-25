from unittest.mock import Mock

import pytest

from apps.legislation.enhancements.providers.anthropic import (
    AnthropicEnhancementProvider,
)
from apps.legislation.enhancements.providers.gemini import GeminiEnhancementProvider
from apps.legislation.enhancements.providers.openai import OpenAIEnhancementProvider
from apps.legislation.enhancements.providers.session import provider_session


@pytest.mark.parametrize(
    "adapter",
    [
        OpenAIEnhancementProvider,
        AnthropicEnhancementProvider,
        GeminiEnhancementProvider,
    ],
)
def test_delivery_reuses_and_closes_native_clients_even_on_error(adapter):
    first, second = Mock(spec=["close"]), Mock(spec=["close"])
    factory = Mock(side_effect=[first, second])
    provider = adapter(client_factory=factory)
    with pytest.raises(RuntimeError), provider_session():
        for _ in range(3):
            assert provider._client(api_key="fixture", timeout_seconds=10) is first
        raise RuntimeError("delivery failed")
    first.close.assert_called_once_with()
    with provider_session():
        assert provider._client(api_key="fixture", timeout_seconds=10) is second
    second.close.assert_called_once_with()
    assert factory.call_count == 2


def test_async_transport_sees_delivery_and_closes_on_its_own_event_loop():
    import asyncio

    from apps.legislation.enhancements.providers.session import (
        delivery_client,
        in_provider_session,
        run_async,
    )

    closed_on = []

    class Transport:
        async def aclose(self):
            closed_on.append(asyncio.get_running_loop())

    class Adapter:
        @delivery_client
        def transport(self):
            return Transport()

    adapter = Adapter()

    async def invoke():
        assert in_provider_session()
        return adapter.transport(), asyncio.get_running_loop()

    with provider_session():
        first = run_async(invoke())
        assert run_async(invoke()) == first
        assert not closed_on
    assert closed_on == [first[1]]
