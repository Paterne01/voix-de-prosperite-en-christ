from __future__ import annotations

import random
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from .config import absolute_path, asset_dirs
from .content import ContentGenerator
from .content_declarations import DeclarationGenerator
from .database import HistoryDatabase
from .images import ImageService
from .meta import MetaPublisher
from .secrets import get_secret

_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg"}

# Formats pris en charge par le service.
FORMATS = ("video", "declaration")

# Durée cible des Shorts selon le format (déclaration = texte court : 20-25 s).
SHORT_DURATION = {"declaration": 22, "video": 60}


class PreparedPost(NamedTuple):
    content: object
    image_path: Path | None
    background: str | None
    bg_kind: str
    bg_path: str | None
    overlay_path: Path | None


class PublicationService:
    def __init__(self, config: dict, logger):
        self.config, self.logger = config, logger
        self.database = HistoryDatabase(absolute_path(config["paths"]["database"]))
        self.content_generator = ContentGenerator(self.database)
        self.declaration_generator = DeclarationGenerator(self.database)
        self.images = ImageService(config)

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def normalize_format(output_type: str) -> str:
        """Fait correspondre un type de sortie de la table post_formats au format interne."""
        return {"short_comment": "video", "image_text": "declaration"}.get(output_type, output_type)

    def _generator(self, format: str, prompt: str | None = None):
        if format == "declaration":
            return self.declaration_generator
        return self.content_generator

    def _find_audio(self, format: str) -> Path | None:
        """Choisit une piste audio aléatoire dans le dossier audio/ du format.

        Exclut la piste utilisée au post précédent pour ce format (suivie en
        SQLite) ; relance une erreur claire si le dossier est vide.
        """
        _, audio_dir = asset_dirs(self.config, format)
        if not audio_dir.is_dir():
            return None
        candidates = sorted(
            path for path in audio_dir.iterdir()
            if path.is_file() and path.suffix.lower() in _AUDIO_EXTENSIONS
        )
        if not candidates:
            raise RuntimeError(
                f"Aucune piste audio trouvée dans {audio_dir} — ajoute au "
                "moins un fichier audio avant de relancer."
            )
        last = self.database.last_audio(format)
        pool = [path for path in candidates if path.name != last] or candidates
        chosen = random.choice(pool)
        self.database.mark_audio(format, chosen.name)
        return chosen

    def _record_base(self, content, image_path, scheduled_for, started, *, background=None, format=None, format_name=None) -> dict:
        return {
            "created_at": started.isoformat(),
            "scheduled_for": scheduled_for,
            "pillar": content.pillar,
            "title": content.title,
            "topic": content.topic,
            "verse_reference": content.verse_reference,
            "cta": content.cta,
            "decor": content.decor,
            "image_prompt": content.image_prompt,
            "caption": content.caption,
            "comment_text": content.comment_text,
            "hashtags": " ".join(content.to_dict()["hashtags"]),
            "image_path": str(image_path) if image_path else None,
            "status": "prepared" if self._dry_run else "pending",
            "error": None,
            "format": format,
            "format_name": format_name,
            "background": background,
            "hook_type": getattr(content, "hook_type", "") or None,
            "engagement_score": getattr(content, "engagement_score", None),
        }

    # ── prepare ──────────────────────────────────────────────────────

    def prepare(self, mode: str | None = None, format: str = "video", prompt: str | None = None) -> PreparedPost:
        from .backgrounds import pick_background

        content = self._generator(format).generate(prompt=prompt)
        # Note d'engagement optionnelle (quota Gemini 20 req/j : activable via
        # config `engagement_score: true`, sinon aucun appel supplémentaire).
        score = None
        if self.config.get("engagement_score"):
            generator = self._generator(format)
            if hasattr(generator, "_score_engagement"):
                score = generator._score_engagement(content)
        if score is not None:
            content.engagement_score = score
        bg_name, bg_path, bg_kind = pick_background(self.config, self.database, format)
        image_path = self.images.create(content, mode=mode, background=bg_path, format=format)
        # Fond vidéo → on prépare un calque texte transparent à superposer dans ffmpeg.
        overlay_path = self.images.overlay(content, format=format) if bg_kind == "video" else None
        return PreparedPost(content, image_path, bg_name, bg_kind, bg_path, overlay_path)

    # ── publish ──────────────────────────────────────────────────────

    @staticmethod
    def is_pro_user() -> bool:
        """Version gratuite pour l'instant : aucun compte pro n'existe encore."""
        return True

    def publish(
        self, *, mode: str | None = None, scheduled_for: str | None = None,
        dry_run: bool = False, format: str = "video", prompt: str | None = None,
        networks: list[str] | None = None, format_name: str | None = None,
        tier: str = "free",
    ) -> dict:
        self._dry_run = dry_run
        if tier == "pro" and not self.is_pro_user():
            self.logger.info("Format pro ignoré — version gratuite (%s)", format_name)
            return {
                "id": None, "status": "skipped", "reason": "pro",
                "format": format, "format_name": format_name,
            }
        allowed = set(networks) if networks else None
        started = datetime.now(UTC)
        prepared = self.prepare(mode, format=format, prompt=prompt)
        content, image_path, background, bg_kind, bg_path, overlay_path = prepared

        publication_id = self.database.create(
            self._record_base(content, image_path, scheduled_for, started, background=background, format=format, format_name=format_name)
        )
        text_file = absolute_path(self.config["paths"]["texts"]) / f"publication_{publication_id}.txt"
        text_file.write_text(
            f"LÉGENDE\n{content.caption}\n\nCOMMENTAIRE\n{content.comment_text}",
            encoding="utf-8",
        )

        if dry_run:
            return {
                "id": publication_id,
                "status": "prepared",
                "format": format,
                "format_name": format_name,
                "content": content.to_dict(),
                "image_path": str(image_path) if image_path else None,
                "background": background,
            }

        if not image_path:
            msg = "Image en attente de validation manuelle : aucune publication envoyée."
            self.database.update(publication_id, status="awaiting_image", error=msg)
            return {"id": publication_id, "status": "awaiting_image", "message": msg}

        networks_out: dict[str, dict] = {}
        created_media: list[Path] = [image_path] if image_path else []
        if overlay_path:
            created_media.append(overlay_path)

        def wants(name: str) -> bool:
            return allowed is None or name in allowed

        if format == "declaration":
            # Facebook : image + texte, sans commentaire de détail.
            if wants("facebook"):
                self._publish_facebook_image(publication_id, image_path, content, networks_out)
            # YouTube / TikTok : une version Short (Ken Burns + audio format_b).
            video_path = self._build_video_for_format(
                image_path, networks_out, created_media, format=format,
                background_video=bg_path if bg_kind == "video" else None,
                overlay_path=overlay_path,
            )
            if video_path is None:
                media_reason = networks_out.get("media", {}).get("reason", "vidéo indisponible")
                if wants("youtube"):
                    networks_out.setdefault("youtube", {"status": "skipped", "reason": media_reason})
                if wants("tiktok"):
                    networks_out.setdefault("tiktok", {"status": "skipped", "reason": media_reason})
            else:
                if wants("youtube"):
                    self._publish_youtube(publication_id, video_path, content, networks_out)
                if wants("tiktok"):
                    self._publish_tiktok(publication_id, video_path, content, networks_out)
        else:
            video_path = self._build_video_for_format(
                image_path, networks_out, created_media, format=format,
                background_video=bg_path if bg_kind == "video" else None,
                overlay_path=overlay_path,
            )
            if video_path is None:
                self.logger.warning("Aucun média vidéo disponible : saut Facebook Reels / YouTube")
                media_reason = networks_out.get("media", {}).get("reason", "vidéo indisponible")
                if wants("facebook"):
                    networks_out.setdefault("facebook", {"status": "skipped", "reason": media_reason})
                if wants("youtube"):
                    networks_out.setdefault("youtube", {"status": "skipped", "reason": media_reason})
            else:
                if wants("facebook"):
                    self._publish_facebook_reels(publication_id, video_path, content, networks_out)
                if wants("youtube"):
                    self._publish_youtube(publication_id, video_path, content, networks_out)
                if wants("tiktok"):
                    self._publish_tiktok(publication_id, video_path, content, networks_out)

        overall = self._resolve_status(networks_out)
        errors = "; ".join(
            n["error"] for n in networks_out.values() if n.get("status") == "error"
        )
        self.database.update(
            publication_id, status=overall, error=errors if errors else None
        )
        self.logger.info(
            "Publication %s (%s) terminée : %s | %s",
            publication_id,
            format,
            overall,
            {k: v.get("status") for k, v in networks_out.items()},
        )

        if networks_out and all(v.get("status") == "ok" for v in networks_out.values()):
            self._purge(created_media)

        return {"id": publication_id, "status": overall, "format": format, **networks_out}

    # ── nettoyage ────────────────────────────────────────────────────

    def _purge(self, paths: list[Path]) -> None:
        from .cleanup import purge_published_media

        existing = [p for p in paths if p is not None and p.exists()]
        if not existing:
            return
        purge_published_media(existing, self.logger)
        self.logger.info(
            "Nettoyage : %s fichier(s) publié(s) supprimé(s)", len(existing)
        )

    # ── Facebook — image (format déclaration, sans commentaire) ──────

    def _publish_facebook_image(
        self, publication_id: int, image_path: Path, content, networks: dict
    ) -> None:
        if not self.config.get("publishers", {}).get("facebook", True):
            return
        token = get_secret("facebook_page_token")
        if not token or not self.config.get("page_id"):
            networks["facebook"] = {
                "status": "skipped",
                "reason": "jeton ou Page ID manquant",
            }
            return
        try:
            publisher = MetaPublisher(self.config, token, self.logger)
            publisher.validate()
            # Format déclaration : image + texte court, PAS de commentaire.
            post_id, url, _ = publisher.publish(
                image_path, content.caption, content.comment_text, with_comment=False
            )
            self.database.update(
                publication_id, facebook_post_id=post_id, facebook_url=url
            )
            networks["facebook"] = {"status": "ok", "id": post_id, "url": url}
            self.logger.info("Facebook (image) %s : %s", publication_id, post_id)
        except Exception as exc:
            self.logger.exception("Facebook image %s échoué", publication_id)
            networks["facebook"] = {"status": "error", "error": str(exc)}

    def _build_video_for_format(
        self, image_path: Path, networks: dict, created_media: list[Path],
        format: str = "video", background_video: str | None = None, overlay_path: Path | None = None,
    ) -> Path | None:
        try:
            audio = self._find_audio(format)
        except RuntimeError as exc:
            networks["media"] = {"status": "skipped", "reason": str(exc)}
            return None
        if not audio:
            networks["media"] = {
                "status": "skipped",
                "reason": "Aucun fichier audio dans le dossier audio/ du format.",
            }
            return None
        video_path = self._build_video(
            image_path, audio, format=format,
            background_video=background_video, overlay_path=overlay_path,
        )
        created_media.append(video_path)
        return video_path

    # ── Facebook — Reels (format vidéo) ──────────────────────────────

    def _publish_facebook_reels(
        self, publication_id: int, video_path: Path, content, networks: dict
    ) -> None:
        if not self.config.get("publishers", {}).get("facebook", True):
            return
        try:
            from .publishers.facebook_reels import FacebookReelsPublisher

            fb = FacebookReelsPublisher(self.config, self.logger)
            fb.validate()
            post_id, url, comment_url = fb.publish(
                media_path=str(video_path),
                text=content.caption,
                details=content.comment_text,
            )
            self.database.update(
                publication_id, facebook_post_id=post_id, facebook_url=url
            )
            networks["facebook"] = {
                "status": "ok", "id": post_id, "url": url, "comment_url": comment_url,
            }
            self.logger.info("Facebook (Reels) %s : %s", publication_id, post_id)
        except Exception as exc:
            self.logger.exception("Facebook Reels %s échoué", publication_id)
            networks["facebook"] = {"status": "error", "error": str(exc)}

    # ── YouTube ──────────────────────────────────────────────────────

    def _publish_youtube(
        self, publication_id: int, video_path: Path, content, networks: dict
    ) -> None:
        if not self.config.get("publishers", {}).get("youtube", False):
            return
        try:
            from .publishers.youtube import YouTubePublisher

            yt = YouTubePublisher(self.config, self.logger)
            video_id, url, comment_url = yt.publish(
                media_path=str(video_path),
                text=content.title,
                details=getattr(content, "youtube_description", None) or content.comment_text,
                tags=getattr(content, "hashtags", None) or None,
                comment=getattr(content, "youtube_comment", None),
            )
            self.database.update(
                publication_id, youtube_video_id=video_id, youtube_url=url,
                youtube_comment_url=comment_url,
            )
            networks["youtube"] = {
                "status": "ok", "id": video_id, "url": url, "comment_url": comment_url,
            }
            self.logger.info("YouTube %s : %s", publication_id, video_id)
        except Exception as exc:
            self.logger.exception("YouTube %s échoué", publication_id)
            networks["youtube"] = {"status": "error", "error": str(exc)}

    def _build_video(
        self, image_path: Path, audio: Path, format: str = "video",
        background_video: str | None = None, overlay_path: Path | None = None,
    ) -> Path:
        from .config import absolute_path
        from .video import build_short_video, build_short_video_from_video

        videos_dir = absolute_path(self.config["paths"].get("videos", "Videos"))
        max_duration = SHORT_DURATION.get(format, 60)
        if background_video and overlay_path:
            return build_short_video_from_video(
                background_video, overlay_path, audio,
                output_dir=videos_dir, max_duration=max_duration,
            )
        return build_short_video(image_path, audio, output_dir=videos_dir, max_duration=max_duration)

    # ── TikTok (Direct Post, format vidéo uniquement) ─────────────────

    def _publish_tiktok(
        self, publication_id: int, video_path: Path, content, networks: dict
    ) -> None:
        settings = self.config.get("publishers", {}).get("tiktok", {})
        if not isinstance(settings, dict) or not settings.get("enabled", False):
            return
        if not video_path or not video_path.exists():
            networks.setdefault("tiktok", {"status": "skipped", "reason": "vidéo indisponible"})
            return
        try:
            from .publishers.tiktok import TikTokPublisher

            publisher = TikTokPublisher(self.config, self.logger)
            state = publisher.validate()
            if state.get("status") == "skipped":
                networks["tiktok"] = {"status": "skipped", "reason": state.get("reason")}
                return
            publish_id, url, _ = publisher.publish(
                media_path=str(video_path),
                text=content.caption,
                details=content.comment_text,
            )
            self.database.update(
                publication_id, tiktok_publish_id=publish_id, tiktok_url=url
            )
            networks["tiktok"] = {"status": "ok", "id": publish_id, "url": url}
            self.logger.info("TikTok %s : %s", publication_id, publish_id)
        except Exception as exc:
            self.logger.exception("TikTok %s échoué", publication_id)
            networks["tiktok"] = {"status": "error", "error": str(exc)}

    # ── publication manuelle (Format C) ─────────────────────────────

    def publish_manual(
        self, *, media_path: str | Path, caption: str, comment: str = "",
        scheduled_for: str | None = None, dry_run: bool = False,
        networks: list[str] | None = None, filename: str | None = None,
        publication_id: int | None = None, format: str = "manual",
        format_name: str = "Manuel", consume_source: bool = True,
    ) -> dict:
        from .manual import generate_youtube_metadata, kind_of

        self._dry_run = dry_run
        media = Path(media_path)
        kind = kind_of(media.name)
        if kind not in ("image", "video"):
            raise ValueError(f"Type de fichier non pris en charge : {media.suffix}")
        if not media.exists():
            raise FileNotFoundError(f"Fichier introuvable : {media}")
        started = datetime.now(UTC)

        # Métadonnées YouTube optimisées (titre + tags + description) générées
        # depuis le nom du fichier et la légende. La légende reste le texte
        # visible Facebook/TikTok ; elle devient aussi la description YouTube.
        try:
            yt_meta = generate_youtube_metadata(media.name, caption)
        except Exception as exc:
            self.logger.warning("Métadonnées YouTube échouées pour %s : %s", media.name, exc)
            yt_meta = {"title": caption.splitlines()[0] if caption else media.stem, "tags": [], "description": caption}

        _title = (yt_meta.get("title") or caption.splitlines()[0] or media.stem)[:100]
        _caption = caption
        _comment = comment
        _yt_description = yt_meta.get("description") or _caption
        _tags = [t for t in yt_meta.get("tags") or [] if isinstance(t, str) and t.strip()]

        class _ManualContent:
            pillar = "Manuel"
            title = _title
            topic = media.name
            verse_reference = ""
            cta = ""
            decor = ""
            image_prompt = ""
            hashtags: list[str] = _tags
            caption = _caption
            comment_text = _comment
            youtube_description = _yt_description
            youtube_comment = _comment  # "" → aucun commentaire YouTube

            def to_dict(self) -> dict:
                return {
                    "title": self.title,
                    "caption": self.caption,
                    "comment_text": self.comment_text,
                    "hashtags": self.hashtags,
                    "youtube_description": self.youtube_description,
                }

        content = _ManualContent()
        if publication_id is None:
            publication_id = self.database.create(
                self._record_base(
                    content, media if kind == "image" else None, scheduled_for, started,
                    format=format, format_name=format_name,
                )
            )
            self.database.update(publication_id, source_filename=filename or media.name)
        else:
            # Reprise d'une publication existante (panneau de contrôle) : on
            # réutilise son identifiant et on conserve son contenu.
            self.database.update(
                publication_id, status="in_progress", error=None,
                format=format, format_name=format_name,
                image_path=str(media) if kind == "image" else None,
            )

        if dry_run:
            return {
                "id": publication_id, "status": "prepared", "format": "manual",
                "kind": kind, "content": content.to_dict(),
                "image_path": str(media),
            }

        allowed = set(networks) if networks else None

        def wants(name: str) -> bool:
            return allowed is None or name in allowed

        networks_out: dict[str, dict] = {}
        created_media: list[Path] = []

        try:
            if kind == "image":
                # Image → Short (audio format_b, 22 s), publié en Reels/Short.
                video_path = self._build_video(media, self._find_audio("declaration"), format="declaration")
            else:
                from .video import crop_to_short
                from .config import absolute_path as _abs

                video_path = crop_to_short(
                    media, output_dir=_abs(self.config["paths"].get("videos", "Videos"))
                )
            created_media.append(video_path)
        except Exception as exc:
            self.logger.exception("Préparation vidéo manuelle %s échouée", publication_id)
            self.database.update(publication_id, status="failed", error=str(exc))
            return {"id": publication_id, "status": "failed", "error": str(exc)}

        if wants("facebook"):
            self._publish_facebook_reels(publication_id, video_path, content, networks_out)
        if wants("youtube"):
            self._publish_youtube(publication_id, video_path, content, networks_out)
        if wants("tiktok"):
            self._publish_tiktok(publication_id, video_path, content, networks_out)

        overall = self._resolve_status(networks_out)
        errors = "; ".join(n["error"] for n in networks_out.values() if n.get("status") == "error")
        self.database.update(publication_id, status=overall, error=errors if errors else None)
        self.logger.info(
            "Publication manuelle %s (%s) terminée : %s | %s",
            publication_id, media.name, overall,
            {k: v.get("status") for k, v in networks_out.items()},
        )

        # Résidus nettoyés dès que la publication est confirmée sur au moins un
        # réseau (short recadré, calque, fichier source en attente). En cas
        # d'échec total, le fichier reste pour un nouvel essai au prochain créneau.
        if networks_out and any(v.get("status") == "ok" for v in networks_out.values()):
            self._purge(created_media)
            if consume_source:
                try:
                    media.unlink()  # le fichier source en attente est consommé
                except OSError as exc:
                    self.logger.warning("Impossible de supprimer le fichier source %s : %s", media, exc)

        return {"id": publication_id, "status": overall, "format": "manual", **networks_out}

    # ── reprise / annulation (tableau de bord) ──────────────────────

    def resume(
        self, *, publication_id: int, image_path: str | None = None,
        networks: list[str] | None = None, dry_run: bool = False,
    ) -> dict:
        """Reprend une publication en attente avec son contenu stocké, en
        réutilisant son identifiant. `image_path` (fichier uploadé) remplace
        l'image manquante si le statut était `awaiting_image`."""
        record = self.database.get(publication_id)
        if record is None:
            raise ValueError("Publication introuvable.")
        if record["status"] == "cancelled":
            raise ValueError("Publication annulée : impossible de reprendre.")
        media = Path(image_path) if image_path else None
        if media is None and record.get("image_path"):
            media = Path(record["image_path"])
        if media is None or not media.exists():
            raise ValueError("Aucune image disponible : fournissez une image pour reprendre.")
        return self.publish_manual(
            media_path=media,
            caption=record["caption"] or "",
            comment=record["comment_text"] or "",
            scheduled_for=record["scheduled_for"],
            dry_run=dry_run,
            networks=networks,
            publication_id=publication_id,
            format=record.get("format") or "manual",
            format_name=record.get("format_name") or "Reprise",
            consume_source=False,
        )

    # ── status ──────────────────────────────────────────────────────

    @staticmethod
    def _resolve_status(networks: dict[str, dict]) -> str:
        if not networks:
            return "skipped"
        ok = {n for n, v in networks.items() if v.get("status") == "ok"}
        errored = {n for n, v in networks.items() if v.get("status") == "error"}
        if ok and not errored:
            return "published"
        if ok and errored:
            return "partial"
        if errored:
            return "failed"
        return "skipped"
