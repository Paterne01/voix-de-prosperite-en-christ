"""Génération de texte via Hugging Face Inference (repli quand Gemini échoue).

Priorité du système pour la génération de contenu :
    Gemini  →  Hugging Face (ce module)  →  générateur local déterministe.

Le générateur local ne doit SERVIR QU'EN DERNIER RECOURS : tout échec de ce
module remonte une exception pour que l'appelant bascule proprement et
journalise le motif, jamais silencieusement.
"""

from __future__ import annotations

import json

# Modèle instruct multilingue (français correct) disponible sur l'API
# Inference de Hugging Face avec un simple jeton Bearer.
HF_TEXT_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"
HF_MAX_TOKENS = 900
HF_TEMPERATURE = 0.75


def _extract_json(text: str) -> dict:
    """Extrait le premier objet JSON du texte (tolère les blocs ``` json ```)."""
    text = (text or "").strip().removeprefix("```json").removeprefix("```").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("Aucun objet JSON dans la réponse Hugging Face")
    return json.loads(text[start:end + 1])


def hf_chat_block(system_prompt: str, prompt_text: str) -> str:
    """Enveloppe le prompt au format instruct de Mistral (system + user)."""
    return f"[INST] {system_prompt}\n\n{prompt_text} [/INST]"


def generate_text(
    *,
    system_prompt: str,
    prompt_text: str,
    token: str,
    model: str = HF_TEXT_MODEL,
    max_new_tokens: int = HF_MAX_TOKENS,
) -> str:
    """Un appel de génération de texte via Hugging Face. Lève en cas d'échec."""
    from huggingface_hub import InferenceClient

    client = InferenceClient(api_key=token)
    block = hf_chat_block(system_prompt, prompt_text)
    out = client.text_generation(
        prompt=block,
        model=model,
        max_new_tokens=max_new_tokens,
        temperature=HF_TEMPERATURE,
    )
    text = str(out).strip()
    if not text:
        raise ValueError("Réponse Hugging Face vide")
    return text


def generate_json(
    *,
    system_prompt: str,
    prompt_text: str,
    token: str,
    model: str = HF_TEXT_MODEL,
) -> dict:
    """Génère un objet JSON via Hugging Face (token/HF pas de retry local ici)."""
    raw = generate_text(
        system_prompt=system_prompt,
        prompt_text=prompt_text,
        token=token,
        model=model,
    )
    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise ValueError("La réponse Hugging Face n'est pas un objet JSON")
    return data