from __future__ import annotations

import base64
import hashlib
import secrets as pystd_secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

from ..secrets import get_secret, set_secret
from .base import BasePublisher

# ── OAuth TikTok (Login Kit + Content Posting API) ────────────────────
# Redirection enregistrée dans le portail développeur :
#   http://127.0.0.1:*/callback/   (le port est accepté par joker)
# L'application Flask locale reçoit donc le code OAuth sur /callback/.
AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
SCOPE = "video.publish,user.info.basic"

# ── Content Posting API (Direct Post) ─────────────────────────────────
INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
CREATOR_INFO_URL = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"

_MB = 1024 * 1024
_CHUNK_MIN = 5 * _MB
_CHUNK_DEFAULT = 8 * _MB
_CHUNK_MAX = 64 * _MB
_FILE_MAX = 4 * 1024 * 1024 * 1024  # 4 Go

def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def persist_token(payload: dict) -> None:
    """Stocke access/refresh token et leurs dates d'expiration dans le keyring."""
    now = int(time.time())
    set_secret("tiktok_access_token", payload["access_token"])
    refresh = payload.get("refresh_token")
    if refresh:
        set_secret("tiktok_refresh_token", refresh)
    set_secret(
        "tiktok_token_expires_at",
        str(now + int(payload.get("expires_in", 3600))),
    )
    set_secret(
        "tiktok_refresh_expires_at",
        str(now + int(payload.get("refresh_expires_in", 86400))),
    )


def clear_tokens() -> None:
    """Supprime les jetons TikTok du keyring (déconnexion)."""
    import keyring

    from ..secrets import SERVICE_NAME

    for name in (
        "tiktok_access_token", "tiktok_refresh_token",
        "tiktok_token_expires_at", "tiktok_refresh_expires_at",
    ):
        try:
            keyring.delete_password(SERVICE_NAME, name)
        except keyring.errors.PasswordDeleteError:
            pass


class TikTokOAuth:
    """Flux OAuth PKCE pour l'application desktop locale.

    L'état (code_verifier, redirect_uri) est gardé en mémoire côté Flask :
    un seul utilisateur local, pas besoin de stockage persistant.
    """

    def __init__(self) -> None:
        self._pending: dict[str, dict] = {}

    def build_authorize_url(self, client_key: str, redirect_uri: str) -> tuple[str, str]:
        state = _b64url(pystd_secrets.token_bytes(24))
        verifier = _b64url(pystd_secrets.token_bytes(64))
        # Quirk TikTok Desktop : le code_challenge est le SHA256 du verifier en HEXADÉCIMAL,
        # pas en base64url comme le standard PKCE (sinon erreur « code verifier is invalid »).
        challenge = hashlib.sha256(verifier.encode("ascii")).hexdigest()
        self._pending[state] = {"verifier": verifier, "redirect_uri": redirect_uri}
        params = {
            "client_key": client_key,
            "scope": SCOPE,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return AUTHORIZE_URL + "?" + urlencode(params), state

    def exchange(
        self,
        client_key: str,
        client_secret: str,
        code: str,
        state: str,
        redirect_uri: str,
    ) -> dict:
        pending = self._pending.pop(state, None)
        if pending is None:
            raise ValueError("État OAuth inconnu (page /callback/ expirée ou rechargée)")
        data = {
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code_verifier": pending["verifier"],
        }
        return _token_request(data)

    @staticmethod
    def refresh(client_key: str, client_secret: str, refresh_token: str) -> dict:
        data = {
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        return _token_request(data)


def _token_request(data: dict) -> dict:
    resp = requests.post(TOKEN_URL, data=data, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Requête de jeton TikTok refusée (HTTP {resp.status_code}) : {resp.text[:400]}"
        )
    payload = resp.json()
    if payload.get("error"):
        raise RuntimeError(
            f"TikTok a refusé le jeton : {payload.get('error')} — "
            f"{payload.get('error_description', '')}".strip()
        )
    if not payload.get("access_token"):
        raise RuntimeError(f"Réponse de jeton TikTok inattendue : {payload}")
    return payload


def _chunk_plan(size: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) conforme aux règles du Media Transfer Guide."""
    if size > _FILE_MAX:
        raise RuntimeError("Vidéo TikTok trop volumineuse (> 4 Go)")
    if size <= _CHUNK_MIN:
        return size, 1
    chunk = _CHUNK_DEFAULT
    count = (size + chunk - 1) // chunk
    # Le dernier chunk peut dépasser chunk_size (jusqu'à 128 Mo), tout reste valide.
    return chunk, count


def _mime_for(path: Path) -> str:
    return {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
    }.get(path.suffix.lower(), "video/mp4")


def _privacy_options(token: str) -> tuple[str, list[str]]:
    """Interroge creator_info/query : renvoie (creator_username, privacy_level_options)."""
    resp = requests.post(
        CREATOR_INFO_URL, headers=_bearer(token), timeout=30
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("error", {}).get("code") != "ok":
        raise RuntimeError(
            f"creator_info/query : {body.get('error', {}).get('code')} "
            f"{body.get('error', {}).get('message', '')}".strip()
        )
    data = body.get("data", {})
    return data.get("creator_username", ""), data.get("privacy_level_options", [])


class TikTokPublisher(BasePublisher):
    """Publication vidéo (Direct Post) sur TikTok via la Content Posting API.

    Flux : init (publish_id + upload_url) → PUT du fichier en chunks → attente
    du statut (status/fetch) jusqu'à PUBLISH_COMPLETE ou FAILED.

    Tant que l'app n'est pas auditée, TikTok ne permet que la publication vers
    un compte PRIVÉ (erreur unaudited_client_can_only_post_to_private_accounts).
    Le privacy_level par défaut est donc SELF_ONLY, à passer à
    PUBLIC_TO_EVERYONE une fois l'audit accepté.
    """

    name = "tiktok"

    def __init__(self, config: dict, logger):
        super().__init__(config, logger)
        settings = config.get("publishers", {}).get("tiktok", {})
        self.settings = settings if isinstance(settings, dict) else {}
        self.tiktok_cfg = config.get("tiktok", {})
        self.client_key = get_secret("tiktok_client_key")
        self.client_secret = get_secret("tiktok_client_secret")
        self.creator_username = ""

    # ── interface publique ───────────────────────────────────────────

    def validate(self) -> dict:
        if not get_secret("tiktok_access_token"):
            return {
                "status": "skipped",
                "reason": "Compte TikTok non connecté (bouton « Connecter TikTok »)",
            }
        if not self.client_key or not self.client_secret:
            return {
                "status": "skipped",
                "reason": "client_key / client_secret TikTok manquants",
            }
        try:
            username, _ = _privacy_options(self._access_token())
            self.creator_username = username
            return {"status": "ok", "creator": username or None}
        except RuntimeError as exc:
            return {"status": "error", "reason": str(exc)}

    def publish(
        self, *, media_path: str, text: str, details: str = ""
    ) -> tuple[str, str | None, str | None]:
        video_path = Path(media_path)
        if not video_path.is_file():
            raise RuntimeError(f"Fichier vidéo introuvable : {video_path}")

        retries = int(self.tiktok_cfg.get("max_retries", 3))
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                return self._publish_once(video_path, text)
            except _AuthExpired as exc:
                self._refresh_access_token()
                last_exc = exc
                self.logger.warning(
                    "TikTok jeton expiré (%s/%s), rafraîchi et nouvel essai",
                    attempt + 1,
                    retries,
                )
            except Exception as exc:
                last_exc = exc
                if attempt == retries - 1:
                    raise RuntimeError(
                        f"Publication TikTok impossible après {retries} essais : {exc}"
                    ) from exc
                self.logger.warning(
                    "TikTok échec (%s/%s) : %s", attempt + 1, retries, exc
                )
                time.sleep(2**attempt)
        raise AssertionError("Boucle TikTok inattendue")

    # ── flux Direct Post ─────────────────────────────────────────────

    def _publish_once(self, video_path: Path, text: str) -> tuple[str, str | None, str | None]:
        token = self._access_token()
        size = video_path.stat().st_size
        chunk_size, chunk_count = _chunk_plan(size)

        title = (text or "").strip()[:2200]
        privacy = self.tiktok_cfg.get("privacy_level", "SELF_ONLY")
        is_aigc = bool(self.tiktok_cfg.get("is_aigc", True))

        init_body = {
            "post_info": {
                "title": title,
                "privacy_level": privacy,
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
                "is_aigc": is_aigc,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chunk_size,
                "total_chunk_count": chunk_count,
            },
        }
        data = self._post(INIT_URL, token, json=init_body)
        publish_id = data.get("publish_id")
        upload_url = data.get("upload_url")
        if not publish_id:
            raise RuntimeError(f"init TikTok sans publish_id : {data}")

        if upload_url:
            self._upload_chunks(upload_url, video_path, chunk_size)

        post_ids = self._wait_for_publish(publish_id, token)
        url = self._post_url(post_ids)
        self.logger.info("TikTok publié : %s (publish_id %s)", url or "privé", publish_id)
        return publish_id, url, None

    def _post(self, url: str, token: str, *, json: dict) -> dict:
        resp = requests.post(url, headers=_bearer(token), json=json, timeout=60)
        if resp.status_code == 401:
            raise _AuthExpired("Access token TikTok invalide ou expiré (401)")
        if resp.status_code >= 400:
            try:
                body = resp.json()
                code = body.get("error", {}).get("code")
                message = body.get("error", {}).get("message", "")
                if code == "access_token_invalid":
                    raise _AuthExpired(f"Token TikTok refusé : {code}")
                raise RuntimeError(f"{url} → {code}: {message}".strip())
            except ValueError:
                resp.raise_for_status()
        resp.raise_for_status()
        body = resp.json()
        code = body.get("error", {}).get("code")
        if code != "ok":
            if code == "access_token_invalid":
                raise _AuthExpired(f"Token TikTok refusé : {code}")
            raise RuntimeError(
                f"{url} → {code}: {body.get('error', {}).get('message', '')}".strip()
            )
        return body.get("data", {})

    def _upload_chunks(self, upload_url: str, video_path: Path, chunk_size: int) -> None:
        size = video_path.stat().st_size
        sent = 0
        mime = _mime_for(video_path)
        with video_path.open("rb") as handle:
            while sent < size:
                chunk = handle.read(chunk_size)
                first, last = sent, sent + len(chunk) - 1
                resp = requests.put(
                    upload_url,
                    headers={
                        "Content-Type": mime,
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {first}-{last}/{size}",
                    },
                    data=chunk,
                    timeout=120,
                )
                if resp.status_code not in (201, 206):
                    raise RuntimeError(
                        f"Chunk TikTok {first}-{last} refusé (HTTP {resp.status_code}) : "
                        f"{resp.text[:300]}"
                    )
                sent += len(chunk)

    def _wait_for_publish(self, publish_id: str, token: str) -> list[int]:
        interval = int(self.tiktok_cfg.get("poll_interval_s", 5))
        timeout = int(self.tiktok_cfg.get("poll_timeout_s", 900))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = self._post(STATUS_URL, token, json={"publish_id": publish_id})
            status = data.get("status")
            if status == "PUBLISH_COMPLETE":
                return data.get("publicaly_available_post_id") or []
            if status == "FAILED":
                raise RuntimeError(
                    f"TikTok a refusé le post : {data.get('fail_reason')}"
                )
            time.sleep(interval)
        raise TimeoutError(f"TikTok : pas de statut final après {timeout}s (publish_id {publish_id})")

    def _post_url(self, post_ids: list[int]) -> str | None:
        if not self.creator_username or not post_ids:
            return None
        post_id = post_ids[0]
        return f"https://www.tiktok.com/@{self.creator_username}/video/{post_id}"

    # ── token ────────────────────────────────────────────────────────

    def _access_token(self) -> str:
        token = get_secret("tiktok_access_token")
        if not token:
            raise RuntimeError("Compte TikTok non connecté")
        expires_at = _parse_ts(get_secret("tiktok_token_expires_at"))
        if expires_at is None or time.time() > expires_at - 300:
            self._refresh_access_token()
            token = get_secret("tiktok_access_token")
        return token or ""

    def _refresh_access_token(self) -> None:
        refresh = get_secret("tiktok_refresh_token")
        if not self.client_key or not self.client_secret or not refresh:
            raise RuntimeError(
                "Jeton TikTok expiré : cliquez à nouveau sur « Connecter TikTok » "
                "pour ré-autoriser l'application."
            )
        payload = TikTokOAuth.refresh(self.client_key, self.client_secret, refresh)
        persist_token(payload)


class _AuthExpired(Exception):
    """Access token invalide ou expiré : le flux publish doit le rafraîchir et retenter."""


def _parse_ts(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
