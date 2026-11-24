from .test_llm_settings_api import authenticated_client, llm_settings, user


def test_configured_native_models_available_with_openrouter_default(settings):
    from apps.legislation.enhancements.model_selection import selectable
    settings.LLM_ENHANCEMENT_PROVIDER = "openrouter"
    settings.LLM_ENHANCEMENT_MODEL = "openrouter/free"
    settings.LLM_READER_MODEL_CAPACITIES = {"openai/second": {"context_tokens": 40000}}
    assert selectable(("openai", "gpt-6-luna"))
    assert selectable(("openai", "second"))


def test_switching_back_preserves_provider_key(authenticated_client, llm_settings):
    client = authenticated_client
    base = "/api/settings/llm/"
    with llm_settings:
        for provider, model, secret in [
            ("openai", "gpt-5.6-luna", "first-1111"),
            ("openrouter", "openrouter/free", "second-2222"),
        ]:
            response = client.put(base + f"credentials/{provider}/", {
                "api_key": secret, "requested_model": model,
            }, format="json")
            assert response.status_code == 200
        response = client.put(base + "selection/", {
            "provider": "openai", "model": "gpt-5.6-luna",
        }, format="json")
        assert response.status_code == 200
        assert client.get(base).json()["key_suffix"] == "1111"
        assert client.delete(base + "credentials/openrouter/").status_code == 204
        assert client.get(base).json()["key_suffix"] == "1111"
        assert client.delete(base + "credentials/openai/").status_code == 204
        assert client.get(base + "selection/").json()["provider"] is None
