from __future__ import annotations

import pickle
import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from ..config import ROOT
from .base import BasePublisher

TOKEN_PATH = ROOT / "BaseDeDonnées" / "youtube_token.pickle"
# Tags YouTube par défaut quand aucun n'est fourni.
DEFAULT_TAGS = ["VoixDeProspéritéEnChrist", "foi", "Bible", "prospérité", "prière"]
# youtube.force-ssl : nécessaire pour poster le commentaire (commentThreads.insert).
# youtube.upload seul ne suffit pas — relancer scripts/youtube_auth_setup.py une fois
# pour que le nouveau scope soit accordé au token.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


class YouTubePublisher(BasePublisher):
    def __init__(self, config: dict, logger):
        super().__init__(config, logger)
        self.token_path = TOKEN_PATH
        self.credentials = self._load_credentials()

    # ── private helpers ──────────────────────────────────────────────

    def _load_credentials(self) -> Credentials:
        if not self.token_path.exists():
            msg = (
                "YouTube non authentifié. Lancez d'abord :\n"
                f"  python scripts\\youtube_auth_setup.py"
            )
            raise RuntimeError(msg)
        with self.token_path.open("rb") as f:
            creds: Credentials = pickle.load(f)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with self.token_path.open("wb") as f:
                pickle.dump(creds, f)
        return creds

    def _build_service(self):
        return build("youtube", "v3", credentials=self.credentials, cache_discovery=False)

    def _video_id_from_response(self, response: dict) -> str:
        return response.get("id", "")

    # ── interface publique ───────────────────────────────────────────

    def validate(self) -> dict:
        # Vérification légère et sans coût : le token existe, il est lisible et,
        # s'il est expiré, il se rafraîchit. On n'appelle pas channels.list car
        # cela exigerait un scope de lecture supplémentaire (ré-authentification)
        # alors que youtube.upload suffit déjà pour publier.
        creds = self._load_credentials()
        return {
            "status": "ok",
            "scopes": list(creds.scopes or []),
        }

    def publish(
        self, *, media_path: str, text: str, details: str = "",
        tags: list[str] | None = None, comment: str | None = None,
        long_video: bool = False,
    ) -> tuple[str, str | None, str | None]:
        retries = int(self.config.get("youtube", {}).get("max_retries", 3))
        privacy = self.config.get("youtube", {}).get("privacy_status", "public")
        title = (text or "Voix de Prospérité en Christ")[:100]
        tag_list = [
            tag.strip().lstrip("#").strip()[:40]
            for tag in (tags or DEFAULT_TAGS)
            if tag and tag.strip()
        ] or list(DEFAULT_TAGS)
        description = (details or text or "")[:4900]
        hashtags = " ".join(f"#{tag}" for tag in tag_list)
        if hashtags and hashtags not in description:
            description = (description.rstrip() + "\n\n" + hashtags) if description else hashtags

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tag_list,
            },
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
        }

        for attempt in range(retries):
            try:
                service = self._build_service()
                media = MediaFileUpload(media_path, chunksize=256 * 1024, resumable=True)
                request = service.videos().insert(
                    part="snippet,status", body=body, media_body=media
                )
                response = request.execute()
                video_id = self._video_id_from_response(response)
                self.logger.info(
                    "YouTube Short publié : %s", video_id
                )
                comment_text = comment if comment is not None else (details or text)
                comment_url = self._post_comment(service, video_id, comment_text)
                public_url = (
                    f"https://www.youtube.com/watch?v={video_id}"
                    if long_video
                    else f"https://www.youtube.com/shorts/{video_id}"
                )
                return (
                    video_id,
                    public_url,
                    comment_url,
                )

            except HttpError as exc:
                if attempt == retries - 1:
                    raise RuntimeError(
                        f"Publication YouTube impossible après {retries} essais : {exc}"
                    ) from exc
                self.logger.warning(
                    "YouTube échec (%s/%s) : %s", attempt + 1, retries, exc
                )
                time.sleep(2**attempt)

        raise AssertionError("Boucle YouTube inattendue")

    def _post_comment(self, service, video_id: str, text: str) -> str | None:
        """Poste le commentaire détaillé sur la vidéo. L'épinglage n'existe pas
        dans l'API publique : l'URL est renvoyée pour un épinglage manuel en un
        clic depuis l'interface Flask. Un échec de commentaire ne bloque jamais
        la publication de la vidéo."""
        if not text:
            return None
        try:
            response = (
                service.commentThreads()
                .insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "videoId": video_id,
                            "topLevelComment": {
                                "snippet": {"textOriginal": text[:4000]}
                            },
                        }
                    },
                )
                .execute()
            )
            comment_id = response.get("id")
            return (
                f"https://www.youtube.com/watch?v={video_id}&lc={comment_id}"
                if comment_id
                else None
            )
        except HttpError as exc:
            # 403/insufficient scope : l'utilisateur doit relancer
            # scripts/youtube_auth_setup.py (scope youtube.force-ssl).
            self.logger.warning(
                "Commentaire YouTube non posté (%s) : %s",
                video_id,
                exc,
            )
            return None
