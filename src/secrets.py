from __future__ import annotations

import keyring

SERVICE_NAME = "voix-prosperite-en-christ"
SECRET_NAMES = (
    "gemini_api_key",
    "facebook_page_token",
    "huggingface_token",
    "tiktok_client_key",
    "tiktok_client_secret",
    "tiktok_access_token",
    "tiktok_refresh_token",
    "tiktok_token_expires_at",
    "tiktok_refresh_expires_at",
)


def get_secret(name: str) -> str | None:
    if name not in SECRET_NAMES:
        raise ValueError("Secret inconnu")
    return keyring.get_password(SERVICE_NAME, name)


def set_secret(name: str, value: str) -> None:
    if name not in SECRET_NAMES or not value.strip():
        raise ValueError("Secret invalide")
    keyring.set_password(SERVICE_NAME, name, value.strip())


def secret_status() -> dict[str, bool]:
    return {name: bool(get_secret(name)) for name in SECRET_NAMES}
