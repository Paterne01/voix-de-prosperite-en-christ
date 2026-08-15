"""Tests de generate_with_retry : documentation de la règle « crédits »."""

from src.llm import LLMError, generate_with_retry


def _config():
    return {
        "ai": {
            "provider": "gemini",
            "model": "gemini-2.0-flash",
            "fallback_order": ["openrouter", "ollama"],
            "providers": {
                "gemini": {"base_url": "g"},
                "openrouter": {"base_url": "o"},
                "ollama": {"base_url": "h", "model": "llama3"},
            },
        }
    }


def _secrets(key):
    return "k" if key in ("gemini_api_key", "openrouter_api_key") else None


def test_reessaye_autre_provider_quand_credits_epuises(monkeypatch):
    monkeypatch.setattr("src.llm.get_secret", _secrets)
    calls = []

    def fake_chat_json(provider, system_prompt, prompt_text, **kwargs):
        calls.append(provider.name)
        if provider.name == "gemini":
            raise LLMError("429 quota dépassé", provider.name)
        return {"ok": True, "source": provider.name}

    monkeypatch.setattr("src.llm.chat_json", fake_chat_json)
    data, provider = generate_with_retry(
        _config(),
        "sys",
        lambda avoid: "user",
        do_json=True,
    )
    assert provider == "openrouter"
    assert data["source"] == "openrouter"
    assert calls == ["gemini", "openrouter"]


def test_local_n_atteint_que_si_tous_echouent(monkeypatch):
    supply = {
        "gemini": LLMError("429 quota dépassé", "gemini"),
        "openrouter": LLMError("402 payment required", "openrouter"),
        "ollama": LLMError("connection refused", "ollama"),
    }
    monkeypatch.setattr(
        "src.llm.chat_json",
        lambda provider, s, p, **kw: _raises(supply[provider.name]),
    )
    try:
        generate_with_retry(_config(), "sys", lambda avoid: "user", do_json=True)
        assert False, "devrait lever LLMError"
    except LLMError as exc:
        assert "Tous les fournisseurs ont échoué" in str(exc)


def test_provider_en_quota_ecarte_pas_retente(monkeypatch):
    monkeypatch.setattr("src.llm.get_secret", _secrets)
    calls = []

    def fake_chat_json(provider, system_prompt, prompt_text, **kwargs):
        calls.append(provider.name)
        if provider.name == "gemini":
            raise LLMError("rate limit", provider.name)
        return {"ok": True}

    monkeypatch.setattr("src.llm.chat_json", fake_chat_json)
    data, provider = generate_with_retry(
        _config(),
        "sys",
        lambda avoid: "user",
        do_json=True,
    )
    assert data["ok"] is True
    # Gemini ne doit PAS être re-tenté après son 1er échec (crédits) : seulement
    # openrouter est retenté après un brouillon rejeté (ici il réussit du 1er coup).
    assert calls == ["gemini", "openrouter"]


def test_brouillon_rejete_retente_avec_feedback(monkeypatch):
    monkeypatch.setattr("src.llm.get_secret", _secrets)
    calls = []

    def fake_chat_json(provider, system_prompt, prompt_text, **kwargs):
        calls.append((provider.name, "avoid" if "rejeté" in prompt_text else "clean"))
        if "rejeté" not in prompt_text:
            raise LLMError("JSON invalide de gemini", "gemini")
        return {"ok": True, "source": provider.name}

    monkeypatch.setattr("src.llm.chat_json", fake_chat_json)
    data, provider = generate_with_retry(
        _config(),
        "sys",
        lambda avoid: "user" if not avoid else f"corrige (rejeté: {avoid})",
        do_json=True,
    )
    assert data["ok"] is True
    # gemini (JSON invalide) est écarté ; openrouter prend le relais et reçoit
    # le feedback de correction (avoid) dans son prompt.
    assert calls == [("gemini", "clean"), ("openrouter", "avoid")]


def _raises(exc):
    raise exc