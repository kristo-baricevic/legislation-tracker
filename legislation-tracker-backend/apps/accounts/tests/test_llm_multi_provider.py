from .test_llm_settings_api import authenticated_client, llm_settings, user


def test_configured_native_models_available_with_openrouter_default(settings):
    from apps.legislation.enhancements.model_selection import selectable
    settings.LLM_ENHANCEMENT_PROVIDER = "openrouter"
    settings.LLM_ENHANCEMENT_MODEL = "openrouter/free"
    settings.LLM_READER_MODEL_CAPACITIES = {"openai/second": {"context_tokens": 40000}}
    assert selectable(("openai", "gpt-6-luna"))
    assert selectable(("openai", "second"))


def test_reactivate_retained_default_key_without_replacing_it(authenticated_client, llm_settings, monkeypatch):
    base = "/api/settings/llm/"
    model = "example/structured:free"
    monkeypatch.setattr("apps.legislation.enhancements.openrouter_catalog.entries", lambda: {
        model: {"model": model, "provider": "openrouter", "free": True}})
    client = authenticated_client
    with llm_settings:
        default = {"provider": "openai", "requested_model": "gpt-5.6-luna"}
        original = client.put(base, {**default, "api_key": "first-1111"}, format="json")
        assert original.status_code == 200
        assert client.put(base, {"provider": "openrouter", "requested_model": model, "api_key": "second-2222"},
                          format="json").status_code == 200
        assert client.delete(base + "credentials/openrouter/").status_code == 204
        assert client.get(base).json()["configured"] is False
        activated = client.put(base, default, format="json")
        assert activated.status_code == 200
        assert activated.json()["revision"] == original.json()["revision"]
        assert client.get(base).json()["key_suffix"] == "1111"
        assert client.get(base + "selection/").json() == {"provider": "openai", "model": default["requested_model"]}


def test_switching_back_preserves_provider_key(authenticated_client, llm_settings, monkeypatch):
    model = "example/structured:free"
    monkeypatch.setattr("apps.legislation.enhancements.openrouter_catalog.entries", lambda: {
        model: {"model": model, "provider": "openrouter", "free": True}})
    client = authenticated_client
    base = "/api/settings/llm/"
    with llm_settings:
        for provider, model, secret in [
            ("openai", "gpt-5.6-luna", "first-1111"),
            ("openrouter", model, "second-2222"),
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
        monkeypatch.setattr("apps.legislation.enhancements.openrouter_catalog.entries", lambda: {})
        scoped = client.get(base + "credentials/openrouter/")
        assert scoped.status_code == 200
        assert scoped.json()["key_suffix"] == "2222"
        assert scoped.json()["requested_model"] == model
        assert client.delete(base + "credentials/openrouter/").status_code == 204
        assert client.get(base + "credentials/openrouter/").status_code == 404
        assert client.get(base).json()["key_suffix"] == "1111"
        assert client.delete(base + "credentials/openai/").status_code == 204
        assert client.get(base + "selection/").json()["provider"] is None
