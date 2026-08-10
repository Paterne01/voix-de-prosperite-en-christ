from __future__ import annotations

import os
from pathlib import Path

import keyring

try:
    from dotenv import load_dotenv, set_key
except ImportError:  # python-dotenv absent : le fallback .env devient indisponible
    load_dotenv = None
    set_key = None

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

# Nom de la variable correspondante dans le fichier .env.
ENV_NAMES = {name: name.upper() for name in SECRET_NAMES}


def _env_path() -> Path:
    from .config import ROOT

    return ROOT / ".env"


def get_secret(name: str) -> str | None:
    """Secret depuis le trousseau natif (keyring), sinon le fichier .env local.

    Ordre de priorité : keyring > .env > None. keyring est cross-platform
    (Credential Manager, Keychain, Secret Service) mais peut être indisponible
    sur un serveur sans interface graphique : on retombe alors sur .env.
    """
    if name not in SECRET_NAMES:
        raise ValueError("Secret inconnu")
    try:
        value = keyring.get_password(SERVICE_NAME, name)
        if value:
            return value
    except Exception:
        pass  # trousseau indisponible → on essaie .env
    if load_dotenv is not None:
        load_dotenv(_env_path())
    return os.getenv(ENV_NAMES[name]) or None


def set_secret(name: str, value: str) -> None:
    """Enregistre le secret dans le trousseau natif, sinon dans .env.

    Retourne une erreur claire si aucun des deux supports n'est utilisable.
    """
    if name not in SECRET_NAMES or not value.strip():
        raise ValueError("Secret invalide")
    try:
        keyring.set_password(SERVICE_NAME, name, value.strip())
        return
    except Exception:
        pass
    if set_key is None:
        raise RuntimeError(
            "Impossible de stocker le secret : trousseau (keyring) indisponible "
            "et python-dotenv absent. Installez python-dotenv ou configurez un "
            "trousseau (apt install gnome-keyring sur Linux sans interface)."
        )
    load_dotenv(_env_path())
    set_key(str(_env_path()), ENV_NAMES[name], value.strip())


def secret_status() -> dict[str, bool]:
    return {name: bool(get_secret(name)) for name in SECRET_NAMES}
