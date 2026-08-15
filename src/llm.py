"""Client LLM unifié multi-fournisseurs (API compatible OpenAI /chat/completions).

Tous les fournisseurs majeurs (Gemini, OpenRouter, Ollama, Grok/xAI, NVIDIA
NIM, Z.ai/Zhipu, OpenAI) exposent un endpoint `/chat/completions` compatible
OpenAI. Ce module les regroupe sous une seule interface : l'app choisit un
fournisseur via `config.ai.provider`, mais peut basculer automatiquement sur un
autre fournisseur configuré quand le premier échoue (quota, panne, 5xx).

Priorité de génération du système (inchangée philosophie du projet) :
    fournisseur(s) LLM configuré(s)  →  Hugging Face  →  générateur local.

Le générateur local ne doit SERVIR QU'EN DERNIER RECOURS : chaque échec d'un
fournisseur remonte une exception pour que l'appelant bascule proprement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import requests

from .secrets import get_secret

# ── Registre des fournisseurs ────────────────────────────────────────────────
# Chaque entrée : nom de clé de secret (`api_key_secret`, None si clé inutile
# comme Ollama local), base_url par défaut et modèle par défaut. Tout est
# surchargeable dans `config.ai.providers.<nom>`.
PROVIDERS: dict[str, dict[str, Any]] = {
    "gemini": {
        "api_key_secret": "gemini_api_key",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash",
        "json_mode": True,
    },
    "openrouter": {
        "api_key_secret": "openrouter_api_key",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "json_mode": True,
    },
    "ollama": {
        "api_key_secret": None,  # local, pas de clé
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.1",
        "json_mode": True,
    },
    "grok": {
        "api_key_secret": "xai_api_key",
        "base_url": "https://api.x.ai/v1",
        "model": "grok-3-mini",
        "json_mode": True,
    },
    "nvidia": {
        "api_key_secret": "nvidia_api_key",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "meta-llama/Llama-3.3-70B-Instruct",
        "json_mode": True,
    },
    "zen": {
        "api_key_secret": "zai_api_key",
        "base_url": "https://api.z.ai/api/paas/v4",
        "model": "glm-4.5-flash",
        "json_mode": True,
    },
    "openai": {
        "api_key_secret": "openai_api_key",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "json_mode": True,
    },
    "deepseek": {
        "api_key_secret": "deepseek_api_key",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "json_mode": True,
    },
}

# Ordre de bascule par défaut quand un provider échoue. modifiable via
# `config.ai.fallback_order`.
DEFAULT_FALLBACK_ORDER = [
    "gemini", "openrouter", "grok", "nvidia", "zen", "deepseek", "ollama", "openai",
]

DEFAULT_MODEL = "gemini-2.5-flash"
REQUEST_TIMEOUT = 120
MAX_TOKENS = 1200


@dataclass
class Provider:
    name: str
    api_key: str | None = None
    api_key_secret: str | None = None
    base_url: str = ""
    model: str = ""
    json_mode: bool = True
    extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        return bool(self.api_key or self.api_key_secret is None)


def _resolve_provider_name(config: dict[str, Any]) -> str:
    ai = config.get("ai") or {}
    name = ai.get("provider", "gemini") or "gemini"
    return name if name in PROVIDERS else "gemini"


def to_provider(name: str, config: dict[str, Any]) -> Provider:
    """Construit le Provider depuis la config (surcharge via config.ai.providers)."""
    spec = dict(PROVIDERS.get(name, PROVIDERS["gemini"]))
    overrides = (config.get("ai") or {}).get("providers") or {}
    user = overrides.get(name) or {}
    spec.update({k: v for k, v in user.items() if v not in (None, "")})
    secret = spec["api_key_secret"]
    api_key = get_secret(secret) if secret else (user.get("api_key") or None)
    headers = dict(spec.get("extra_headers") or {})
    headers.update(user.get("headers") or {})
    return Provider(
        name=name,
        api_key=api_key,
        api_key_secret=secret,
        base_url=spec["base_url"].rstrip("/"),
        model=spec.get("model") or DEFAULT_MODEL,
        json_mode=bool(spec.get("json_mode", True)),
        extra_headers=headers,
    )


def ordered_providers(config: dict[str, Any]) -> list[Provider]:
    """Liste ordonnée des providers à essayer (configurés en premier).

    - Le provider principal (config.ai.provider) passe en tête s'il est présent et clé dispo.
    - Ensuite `config.ai.fallback_order` (ou l'ordre par défaut) : seuls ceux
      ayant une clé sont conservés (Ollama local n'en exige pas).
    - Dédupliqué, sans doublon.
    """
    ai = config.get("ai") or {}
    wanted = ai.get("fallback_order") or DEFAULT_FALLBACK_ORDER
    primary = _resolve_provider_name(config)
    order = [primary] + [n for n in wanted if n != primary]
    providers: list[Provider] = []
    for name in order:
        provider = to_provider(name, config)
        if provider.configured and provider.name not in {p.name for p in providers}:
            providers.append(provider)
    if not providers:
        providers.append(to_provider("gemini", config))
    return providers


def _headers(provider: Provider) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    headers.update(provider.extra_headers)
    if provider.api_key:
        headers["Authorization"] = f"Bearer {provider.api_key}"
        if provider.name in ("openrouter",):
            headers.setdefault("HTTP-Referer", "https://voix-prosperite.example")
            headers.setdefault("X-Title", "Voix de Prospérité en Christ")
    return headers


def _extract_json(raw: str) -> dict:
    text = (raw or "").strip().removeprefix("```json").removeprefix("```").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("Aucun objet JSON dans la réponse du fournisseur d'IA")
    return json.loads(text[start:end + 1])


def _error_body(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            return response.text[:500]
        except Exception:
            pass
    return str(exc)


class LLMError(RuntimeError):
    def __init__(self, message: str, provider: str, cause: Exception | None = None):
        super().__init__(message)
        self.provider = provider
        self.cause = cause


def chat(
    provider: Provider,
    system_prompt: str,
    prompt_text: str,
    *,
    json_mode: bool = True,
    temperature: float = 0.75,
    max_tokens: int = MAX_TOKENS,
    timeout: int = REQUEST_TIMEOUT,
) -> str:
    """Un appel de chat/completions sur un provider précis. Lève en cas d'échec."""
    payload: dict[str, Any] = {
        "model": provider.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt_text},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode and provider.json_mode:
        payload["response_format"] = {"type": "json_object"}
    url = f"{provider.base_url}/chat/completions"
    try:
        response = requests.post(url, headers=_headers(provider), json=payload, timeout=timeout)
        response.raise_for_status()
    except (requests.RequestException, Exception) as exc:
        raise LLMError(
            f"Échec {provider.name} ({provider.model}) : {_error_body(exc)}",
            provider.name,
            exc,
        ) from exc
    try:
        body = response.json()
    except json.JSONDecodeError as exc:  # pragma: no cover - réponse non JSON
        raise LLMError(f"Réponse non JSON de {provider.name}", provider.name, exc) from exc
    # Chemins de réponse : OpenAI standard + variations (choices → message → content).
    choices = body.get("choices") or []
    if not choices:
        error = body.get("error") or body
        raise LLMError(f"Réponse vide de {provider.name} : {str(error)[:300]}", provider.name)
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        finish = choices[0].get("finish_reason")
        detail = body.get("usage") or {}
        raise LLMError(
            f"Contenu vide de {provider.name} ({provider.model}, finish={finish}, usage={detail})",
            provider.name,
        )
    return content.strip()


def chat_json(
    provider: Provider,
    system_prompt: str,
    prompt_text: str,
    **kwargs: Any,
) -> dict:
    """Chat + extraction d'un objet JSON (tolère blocs ```json```)."""
    raw = chat(provider, system_prompt, prompt_text, json_mode=True, **kwargs)
    try:
        return _extract_json(raw)
    except ValueError as exc:
        raise LLMError(f"JSON invalide de {provider.name}", provider.name, exc) from exc


def generate_with_fallback(
    config: dict[str, Any],
    system_prompt: str,
    prompt_text: str,
    *,
    do_json: bool = True,
    temperature: float = 0.75,
    max_tokens: int = MAX_TOKENS,
) -> tuple[dict | str, str]:
    """Essaie chaque provider configuré dans l'ordre, renvoie (réponse, provider).

    `do_json=True` force un objet JSON ; sinon la réponse texte brute est
    renvoyée. Lève LLMError si TOUS les providers échouent.
    """
    providers = ordered_providers(config)
    last_error: Exception | None = None
    attempted: list[str] = []
    for provider in providers:
        attempted.append(provider.name)
        try:
            if do_json:
                data = chat_json(provider, system_prompt, prompt_text, temperature=temperature, max_tokens=max_tokens)
                return data, provider.name
            raw = chat(provider, system_prompt, prompt_text, json_mode=False, temperature=temperature, max_tokens=max_tokens)
            return raw, provider.name
        except Exception as exc:
            last_error = exc
    detail = " ; ".join(attempted) if attempted else "aucun provider configuré"
    raise LLMError(f"Tous les fournisseurs ont échoué ({detail}) : {last_error}", detail, last_error) from last_error


def check_provider(config: dict[str, Any], name: str | None = None, *, system_prompt: str = "Réponds uniquement par le mot OK.", prompt_text: str = "Dis OK.", timeout: int = 60) -> tuple[bool, str]:
    """Teste qu'un provider/réponse est joignable. (bool ok, message)."""
    provider = to_provider(name or _resolve_provider_name(config), config)
    if not provider.configured:
        return False, f"{provider.name}: aucune clé configurée"
    try:
        raw = chat(provider, system_prompt, prompt_text, json_mode=False, max_tokens=8, timeout=timeout)
        return True, f"{provider.name} ({provider.model}) OK : {raw[:40]!r}"
    except Exception as exc:
        return False, f"{provider.name} ({provider.model}) : {_error_body(exc)}"