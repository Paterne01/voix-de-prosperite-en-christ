from __future__ import annotations

import pytest

from src.llm import (
    LLMError,
    _extract_json,
    chat_json,
    generate_with_fallback,
    ordered_providers,
    to_provider,
)


def test_ordered_providers_primary_first(monkeypatch):
    config = {"ai": {"provider": "grok"}}
    monkeypatch.setattr("src.llm.get_secret", lambda name: "clé-de-test" if name == "xai_api_key" else None)
    names = [p.name for p in ordered_providers(config)]
    assert names[0] == "grok"


def test_ordered_providers_skips_without_key(monkeypatch):
    config = {"ai": {"provider": "gemini", "fallback_order": ["openrouter", "grok", "nvidia"]}}
    monkeypatch.setattr("src.llm.get_secret", lambda name: "k" if name == "gemini_api_key" else None)
    names = [p.name for p in ordered_providers(config)]
    assert names == ["gemini"]


def test_ordered_providers_requires_key(monkeypatch):
    config = {"ai": {"provider": "gemini"}}
    monkeypatch.setattr("src.llm.get_secret", lambda name: None)
    names = [p.name for p in ordered_providers(config)]
    assert names == ["gemini"]  # aucun provider sans clé n'est utilisé


def test_to_provider_uses_config_override():
    config = {"ai": {"providers": {"gemini": {"model": "custom-model", "base_url": "https://x.example/v1"}}}}
    provider = to_provider("gemini", config)
    assert provider.model == "custom-model"
    assert provider.base_url == "https://x.example/v1"


def test_extract_json_strips_code_fence_and_tolerates_text():
    data = _extract_json('```json\n{"a": 1}\n```')
    assert data == {"a": 1}
    data = _extract_json('Voici : {"a": 2} fin.')
    assert data == {"a": 2}


def test_generate_with_fallback_uses_next_provider_on_failure(monkeypatch):
    config = {"ai": {"provider": "gemini", "fallback_order": ["gemini", "openrouter"]}}
    monkeypatch.setattr("src.llm.get_secret", lambda name: ("k" if name in ("gemini_api_key", "openrouter_api_key") else None))
    calls: list[str] = []

    def fake_chat_json(provider, system, prompt, **kwargs):
        calls.append(provider.name)
        if provider.name == "gemini":
            raise LLMError("quota", "gemini")
        return {"ok": True}

    from src import llm as llm_module

    monkeypatch.setattr(llm_module, "chat_json", fake_chat_json)
    data, provider = generate_with_fallback(config, "sys", "user", do_json=True)
    assert provider == "openrouter"
    assert data == {"ok": True}
    assert calls == ["gemini", "openrouter"]


def test_generate_with_fallback_raises_when_all_fail(monkeypatch):
    config = {"ai": {"provider": "gemini"}}
    monkeypatch.setattr("src.llm.get_secret", lambda name: "k")

    def fake_chat_json(provider, system, prompt, **kwargs):
        raise LLMError("boom", provider.name)

    from src import llm as llm_module

    monkeypatch.setattr(llm_module, "chat_json", fake_chat_json)
    with pytest.raises(LLMError):
        generate_with_fallback(config, "sys", "user", do_json=True)


def test_generate_with_fallback_text_mode(monkeypatch):
    config = {"ai": {"provider": "grok"}}
    monkeypatch.setattr("src.llm.get_secret", lambda name: ("k" if name == "xai_api_key" else None))

    def fake_chat(provider, system, prompt, **kwargs):
        return "OK texte"

    from src import llm as llm_module

    monkeypatch.setattr(llm_module, "chat", fake_chat)
    data, provider = generate_with_fallback(config, "sys", "user", do_json=False)
    assert data == "OK texte"
    assert provider == "grok"


def test_chat_json_handles_invalid_json(monkeypatch):
    from src import llm as llm_module
    from src.llm import Provider

    provider = Provider(name="gemini", api_key="k", base_url="https://x/v1", model="m")
    monkeypatch.setattr(
        llm_module,
        "chat",
        lambda *a, **k: "ceci n'est pas du JSON",
    )
    with pytest.raises(LLMError):
        chat_json(provider, "sys", "user")


def test_configure_console_never_raises(monkeypatch):
    from src.console import configure_console

    def boom():
        raise RuntimeError("reconfigure impossible")

    monkeypatch.setattr("src.console.sys.stdout", type("S", (), {"reconfigure": boom})())
    configure_console()  # ne doit pas lever