"""Experimental OpenRouter transport. Validation and recovery belong to the worker."""

import asyncio

from openai import DefaultAsyncHttpxClient

from .openai_compatible import OpenAICompatibleEnhancementProvider


class LangChainOpenRouterProvider(OpenAICompatibleEnhancementProvider):
    provider_name = "openrouter"

    def __init__(
        self, *, model_factory=None, http_client_factory=DefaultAsyncHttpxClient
    ):
        super().__init__(base_url="https://openrouter.ai/api/v1")
        if model_factory is None:
            from langchain_openai import ChatOpenAI

            model_factory = ChatOpenAI
        self.model_factory = model_factory
        self.http_client_factory = http_client_factory

    def _send(self, *, api_key, timeout_seconds, model, messages, **options):
        from langsmith import tracing_context

        # Send the wire schema directly. The SDK parse endpoint raises before
        # returning usage on length/content-filter completions.
        if "response_format" in options:
            options.setdefault("extra_body", {})["response_format"] = options.pop(
                "response_format"
            )

        async def invoke():
            async with self.http_client_factory() as client:
                chat = self.model_factory(
                    model=model,
                    api_key=api_key,
                    base_url=self.base_url,
                    max_retries=0,
                    timeout=timeout_seconds,
                    use_responses_api=False,
                    cache=False,
                    http_async_client=client,
                )
                with tracing_context(enabled=False):
                    return await asyncio.wait_for(
                        chat.ainvoke(messages, **options), timeout_seconds
                    )

        reply = asyncio.run(invoke())
        metadata = reply.response_metadata
        return {
            "id": metadata.get("id", ""),
            "model": metadata.get("model_name", ""),
            "usage": metadata.get("token_usage"),
            "choices": [
                {
                    "finish_reason": metadata.get("finish_reason"),
                    "message": {
                        "content": reply.content,
                        "refusal": reply.additional_kwargs.get("refusal"),
                    },
                }
            ],
        }
