from __future__ import annotations

from pathlib import Path

import requests

from ..secrets import get_secret
from .base import BasePublisher


class FacebookReelsPublisher(BasePublisher):
    """Publie de vraies vidéos (Reels) sur la Page, via le même Page Access
    Token longue durée déjà utilisé pour les posts image actuels.

    ⚠️ Le nom du secret keyring est "facebook_page_token" (le même que celui
    utilisé par src/meta.py), et la version Graph est celle de la config
    (facebook.api_version, ex. v25.0).
    """

    name = "facebook_reels"

    def __init__(self, config: dict, logger):
        super().__init__(config, logger)
        self.page_id = config["page_id"]
        self.api_version = config["facebook"]["api_version"]
        self.token = get_secret("facebook_page_token")

    # ── interface publique ───────────────────────────────────────────

    def validate(self) -> dict:
        """Vérifie que le Page Access Token est valide pour cette Page."""
        resp = requests.get(
            f"https://graph.facebook.com/{self.api_version}/{self.page_id}",
            params={"fields": "id,name", "access_token": self.token},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def publish(
        self, *, media_path: str, text: str, details: str = ""
    ) -> tuple[str, str | None, str | None]:
        retries = int(self.config.get("facebook", {}).get("max_retries", 3))
        base = f"https://graph.facebook.com/{self.api_version}/{self.page_id}/video_reels"
        video_path = Path(media_path)
        description = (text or "")[:2200]

        for attempt in range(retries):
            try:
                post_id, reel_url = self._upload_and_finish(base, video_path, description)
                comment_url = self._post_comment(post_id, details)
                return post_id, reel_url, comment_url
            except requests.RequestException as exc:
                if attempt == retries - 1:
                    raise RuntimeError(
                        f"Publication Reel Facebook impossible après {retries} essais : {exc}"
                    ) from exc
                self.logger.warning(
                    "Échec Reel Facebook (%s/%s), nouvel essai : %s",
                    attempt + 1,
                    retries,
                    exc,
                )

        raise AssertionError("Boucle Reel Facebook inattendue")

    # ── étapes upload ────────────────────────────────────────────────

    def _upload_and_finish(self, base: str, video_path: Path, description: str) -> tuple[str, str]:
        # 1. Démarrage de la session d'upload
        start = requests.post(
            base,
            data={"upload_phase": "start", "access_token": self.token},
            timeout=30,
        )
        start.raise_for_status()
        video_id = start.json()["video_id"]

        # 2. Envoi du fichier vidéo (upload direct, adapté aux vidéos courtes
        #    — pas besoin de découpage par blocs à cette taille)
        upload_url = f"https://rupload.facebook.com/video-upload/{self.api_version}/{video_id}"
        with video_path.open("rb") as handle:
            transfer = requests.post(
                upload_url,
                headers={
                    "Authorization": f"OAuth {self.token}",
                    "offset": "0",
                    "file_size": str(video_path.stat().st_size),
                },
                data=handle.read(),
                timeout=120,
            )
        transfer.raise_for_status()

        # 3. Publication du Reel une fois l'upload terminé
        finish = requests.post(
            base,
            data={
                "upload_phase": "finish",
                "video_id": video_id,
                "description": description,
                "video_state": "PUBLISHED",
                "access_token": self.token,
            },
            timeout=30,
        )
        finish.raise_for_status()

        post_id = finish.json().get("id") or video_id
        return post_id, f"https://facebook.com/reel/{post_id}"

    def _post_comment(self, post_id: str, text: str) -> str | None:
        """Poste le commentaire détaillé sur le Reel. Un échec ne bloque jamais
        la publication de la vidéo. Retourne l'URL du commentaire si posté."""
        if not text:
            return None
        try:
            resp = requests.post(
                f"https://graph.facebook.com/{self.api_version}/{post_id}/comments",
                data={"message": text[:2200], "access_token": self.token},
                timeout=45,
            )
            resp.raise_for_status()
            comment_id = resp.json().get("id")
            return (
                f"https://www.facebook.com/{post_id}?comment_id={comment_id}"
                if comment_id
                else None
            )
        except requests.RequestException as exc:
            self.logger.warning(
                "Commentaire Reel Facebook non posté (%s) : %s", post_id, exc
            )
            return None
