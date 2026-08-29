from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


class HistoryDatabase:
    def __init__(self, path: Path):
        self.path = path
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self.connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS publications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    scheduled_for TEXT,
                    pillar TEXT NOT NULL,
                    title TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    verse_reference TEXT NOT NULL,
                    cta TEXT NOT NULL,
                    decor TEXT NOT NULL,
                    image_prompt TEXT NOT NULL,
                    caption TEXT NOT NULL,
                    comment_text TEXT NOT NULL,
                    hashtags TEXT NOT NULL,
                    image_path TEXT,
                    facebook_post_id TEXT,
                    facebook_url TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    format TEXT,
                    background TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_publications_created ON publications(created_at)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS format_state (
                    format TEXT PRIMARY KEY,
                    last_audio TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS post_formats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    schedule TEXT NOT NULL,
                    output_type TEXT NOT NULL,
                    networks TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    tier TEXT NOT NULL DEFAULT 'free',
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS overlays (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    overlay_type TEXT NOT NULL,
                    file_path TEXT,
                    text_content TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    format_scope TEXT NOT NULL DEFAULT 'all',
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_overlays_type ON overlays(overlay_type, active)")
            try:
                conn.execute("ALTER TABLE post_formats ADD COLUMN tier TEXT NOT NULL DEFAULT 'free'")
            except sqlite3.OperationalError:
                pass
            for col in (
                "youtube_video_id", "youtube_url", "youtube_comment_id", "youtube_comment_url",
                "tiktok_publish_id", "tiktok_url",
                "format", "background", "format_name", "source_filename",
                "hook_type", "engagement_score",
            ):
                try:
                    conn.execute(f"ALTER TABLE publications ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError:
                    pass
            for col, typ in (
                ("publish_delay_seconds", "INTEGER"),
                ("publish_attempted_at", "TEXT"),
            ):
                try:
                    conn.execute(f"ALTER TABLE publications ADD COLUMN {col} {typ}")
                except sqlite3.OperationalError:
                    pass

    def recent_values(self, column: str, days: int = 90) -> set[str]:
        allowed = {"title", "topic", "verse_reference", "cta", "decor", "hook_type", "comment_text"}
        if column not in allowed:
            raise ValueError("Colonne non autorisée")
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with self.connect() as conn:
            rows = conn.execute(f"SELECT {column} FROM publications WHERE created_at >= ?", (cutoff,)).fetchall()
        return {str(row[column]).strip().casefold() for row in rows}

    def recent_backgrounds(self, days: int = 90) -> set[str]:
        """Noms des fonds déjà utilisés sur la fenêtre donnée (exclusion 90 j)."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT background FROM publications WHERE created_at >= ? AND background IS NOT NULL",
                (cutoff,),
            ).fetchall()
        return {str(row["background"]).strip() for row in rows}

    def last_audio(self, format: str) -> str | None:
        """Nom de la dernière piste audio utilisée pour ce format (anti-doublon)."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT last_audio FROM format_state WHERE format = ?", (format,)
            ).fetchone()
        return row["last_audio"] if row else None

    def mark_audio(self, format: str, name: str) -> None:
        """Mémorise la piste audio choisie pour ce format."""
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO format_state (format, last_audio) VALUES (?, ?) "
                "ON CONFLICT(format) DO UPDATE SET last_audio = excluded.last_audio",
                (format, name),
            )

    def create(self, record: dict) -> int:
        fields = [
            "created_at", "scheduled_for", "pillar", "title", "topic", "verse_reference", "cta", "decor",
            "image_prompt", "caption", "comment_text", "hashtags", "image_path", "facebook_post_id",
            "facebook_url", "youtube_video_id", "youtube_url", "youtube_comment_id", "youtube_comment_url",
            "tiktok_publish_id", "tiktok_url",
            "status", "error", "format", "background", "format_name", "source_filename",
            "hook_type", "engagement_score", "publish_delay_seconds", "publish_attempted_at",
        ]
        values = [record.get(field) for field in fields]
        with self.connect() as conn:
            cursor = conn.execute(
                f"INSERT INTO publications ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", values
            )
            return int(cursor.lastrowid)

    def update(self, publication_id: int, **values: str | None) -> None:
        if not values:
            return
        allowed = {"image_path", "facebook_post_id", "facebook_url", "youtube_video_id", "youtube_url", "youtube_comment_id", "youtube_comment_url", "tiktok_publish_id", "tiktok_url", "status", "error", "format", "background", "format_name", "source_filename", "publish_delay_seconds", "publish_attempted_at"}
        if set(values) - allowed:
            raise ValueError("Champ non autorisé")
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self.connect() as conn:
            conn.execute(f"UPDATE publications SET {assignments} WHERE id = ?", [*values.values(), publication_id])

    def recent(self, limit: int = 30) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM publications ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def get(self, publication_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM publications WHERE id = ?", (publication_id,)).fetchone()
        return dict(row) if row else None

    def pending(self, statuses: tuple[str, ...] = ("awaiting_image", "failed", "prepared", "skipped")) -> list[dict]:
        """Publications en attente d'une action (image manquante, échec, brouillon)."""
        marks = ",".join("?" for _ in statuses)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM publications WHERE status IN ({marks}) ORDER BY id DESC",
                statuses,
            ).fetchall()
        return [dict(row) for row in rows]

    def cancel(self, publication_id: int) -> None:
        """Annule une publication en attente (elle disparaît du panneau de contrôle)."""
        self.update(publication_id, status="cancelled", error="Annulée depuis le tableau de bord")

    def needs_catch_up(self, schedule_time: str) -> bool:
        today = datetime.now().date().isoformat()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM publications WHERE scheduled_for LIKE ? "
                "AND status IN ('published', 'partial') LIMIT 1",
                (f"{today}T{schedule_time}%",),
            ).fetchone()
        return row is None

    def missing_facebook_today(self) -> list[dict]:
        """Publications du jour déjà publiées ailleurs (YT/TikTok) mais SANS
        post Facebook : cibles du rattrapage Facebook seul."""
        today = datetime.now().date().isoformat()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM publications WHERE scheduled_for LIKE ? "
                "AND facebook_post_id IS NULL "
                "AND status IN ('published', 'partial')",
                (f"{today}%",),
            ).fetchall()
        return [dict(row) for row in rows]

    def manual_slot_done(self, day: str, slot: str) -> bool:
        """Vrai si un contenu manuel a déjà été réservé/publié pour ce créneau ce jour-là.

        Inclut 'pending' (en cours de publication) pour éviter la race condition :
        deux ticks concurrents (APScheduler toutes les 5 min + tâche Windows toutes
        les 10 min) dans la fenêtre 19:55-20:20 réservaient chacun un fichier
        différent pour le même créneau 20:00 → 2 posts YouTube/Facebook. Dès qu'un
        tick crée l'enregistrement 'pending', le suivant doit s'arrêter.
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM publications WHERE scheduled_for LIKE ? AND format = 'manual' "
                "AND status IN ('published', 'partial', 'pending', 'in_progress') LIMIT 1",
                (f"{day}T{slot}%",),
            ).fetchone()
        return row is not None

    def manual_source_published(self, filename: str) -> bool:
        """Vrai si un fichier importé a DÉJÀ été publié avec succès (anti-doublon).

        Couvre les statuts réussis (published/partial) mais aussi les créneaux
        en cours (in_progress/pending) : deux tours manuels qui se chevauchent
        ne doivent pas publier le même fichier deux fois.
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM publications WHERE source_filename = ? AND format = 'manual' "
                "AND status IN ('published', 'partial', 'in_progress', 'pending') LIMIT 1",
                (filename,),
            ).fetchone()
        return row is not None

    def count_today_published(self) -> int:
        """Nombre de posts publiés aujourd'hui (tous formats)."""
        today = datetime.now().date().isoformat()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM publications WHERE substr(created_at,1,10)=? AND status IN ('published','partial')",
                (today,),
            ).fetchone()
        return int(row[0]) if row else 0

    def today_stats(self, limit: int = 3) -> dict:
        today = datetime.now().date().isoformat()
        with self.connect() as conn:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM publications WHERE substr(created_at,1,10)=? AND status IN ('published','partial')",
                (today,),
            ).fetchone()[0]
        return {"posts_today": int(cnt), "limit": int(limit)}

    # ── formats personnalisables ─────────────────────────────────────

    @staticmethod
    def _decode_json(value: str):
        import json
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return []

    def list_formats(self, only_active: bool = False) -> list[dict]:
        sql = "SELECT * FROM post_formats"
        if only_active:
            sql += " WHERE active = 1"
        sql += " ORDER BY id"
        with self.connect() as conn:
            rows = conn.execute(sql).fetchall()
        formats = []
        for row in rows:
            item = dict(row)
            # schedule/networks sont stockés en JSON : renvoyer des listes réelles,
            # sinon un `set('["facebook", ...]')` publierait vers zéro réseau.
            item["schedule"] = self._decode_json(item.get("schedule") or "[]")
            item["networks"] = self._decode_json(item.get("networks") or "[]")
            formats.append(item)
        return formats

    def get_format(self, format_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM post_formats WHERE id = ?", (format_id,)).fetchone()
        return dict(row) if row else None

    def create_format(self, name: str, prompt: str, schedule: list[str], output_type: str, networks: list[str], active: bool = True, tier: str = "free") -> int:
        import json
        from datetime import datetime
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO post_formats (name, prompt, schedule, output_type, networks, active, tier, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    name, prompt,
                    json.dumps(schedule, ensure_ascii=False),
                    output_type,
                    json.dumps(networks, ensure_ascii=False),
                    1 if active else 0,
                    tier or "free",
                    datetime.now(UTC).isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def update_format(self, format_id: int, *, name: str, prompt: str, schedule: list[str], output_type: str, networks: list[str], active: bool, tier: str | None = None) -> None:
        import json
        tier = tier or "free"
        with self.connect() as conn:
            conn.execute(
                "UPDATE post_formats SET name = ?, prompt = ?, schedule = ?, output_type = ?, networks = ?, active = ?, tier = ? WHERE id = ?",
                (
                    name, prompt,
                    json.dumps(schedule, ensure_ascii=False),
                    output_type,
                    json.dumps(networks, ensure_ascii=False),
                    1 if active else 0,
                    tier,
                    format_id,
                ),
            )

    def delete_format(self, format_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM post_formats WHERE id = ?", (format_id,))

    # ── overlays (intro/outro vidéo, watermark, texte image) ─────────

    OVERLAY_TYPES = ("intro", "outro", "watermark", "image_text")

    def list_overlays(self, overlay_type: str | None = None) -> list[dict]:
        sql = "SELECT * FROM overlays"
        params: tuple = ()
        if overlay_type:
            sql += " WHERE overlay_type = ?"
            params = (overlay_type,)
        sql += " ORDER BY overlay_type, id"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_overlay(self, overlay_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM overlays WHERE id = ?", (overlay_id,)).fetchone()
        return dict(row) if row else None

    def create_overlay(
        self, *, name: str, overlay_type: str, file_path: str | None = None,
        text_content: str | None = None, active: bool = True, format_scope: str = "all",
    ) -> int:
        if overlay_type not in self.OVERLAY_TYPES:
            raise ValueError(f"Type d'overlay inconnu : {overlay_type}")
        with self.connect() as conn:
            if active:
                # Exclusif par (type, périmètre) : on peut avoir un intro "all"
                # et un intro "video" actifs en même temps, mais pas deux intros
                # "video". Conserve les overlays avec leurs paramètres pour
                # switcher selon la saison/circonstance.
                conn.execute(
                    "UPDATE overlays SET active = 0 WHERE overlay_type = ? AND format_scope = ?",
                    (overlay_type, format_scope),
                )
            cursor = conn.execute(
                "INSERT INTO overlays (name, overlay_type, file_path, text_content, active, format_scope, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    name, overlay_type, file_path, text_content,
                    1 if active else 0, format_scope,
                    datetime.now(UTC).isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def update_overlay(
        self, overlay_id: int, *, name: str, overlay_type: str,
        file_path: str | None = None, text_content: str | None = None,
        active: bool = True, format_scope: str = "all",
    ) -> None:
        if overlay_type not in self.OVERLAY_TYPES:
            raise ValueError(f"Type d'overlay inconnu : {overlay_type}")
        with self.connect() as conn:
            if active:
                conn.execute(
                    "UPDATE overlays SET active = 0 WHERE overlay_type = ? AND format_scope = ? AND id != ?",
                    (overlay_type, format_scope, overlay_id),
                )
            conn.execute(
                "UPDATE overlays SET name = ?, overlay_type = ?, file_path = ?, "
                "text_content = ?, active = ?, format_scope = ? WHERE id = ?",
                (
                    name, overlay_type, file_path, text_content,
                    1 if active else 0, format_scope, overlay_id,
                ),
            )

    def delete_overlay(self, overlay_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM overlays WHERE id = ?", (overlay_id,))

    def set_overlay_active(self, overlay_id: int, active: bool) -> None:
        """Active/désactive un overlay ; l'activation est exclusive par
        (type, périmètre) — ex. un intro "video" et un intro "declaration"
        peuvent être actifs en même temps, mais pas deux intros "video".
        Tous les overlays restent enregistrés avec leurs paramètres pour
        switcher selon la saison/circonstance."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT overlay_type, format_scope FROM overlays WHERE id = ?", (overlay_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Overlay introuvable.")
            if active:
                conn.execute(
                    "UPDATE overlays SET active = 0 WHERE overlay_type = ? AND format_scope = ?",
                    (row["overlay_type"], row["format_scope"]),
                )
                conn.execute("UPDATE overlays SET active = 1 WHERE id = ?", (overlay_id,))
            else:
                conn.execute("UPDATE overlays SET active = 0 WHERE id = ?", (overlay_id,))

    def active_overlays(self, overlay_type: str | None = None, format: str | None = None) -> list[dict]:
        """Overlays actifs, optionnellement filtrés par type et/ou format.

        format_scope : "all" → toutes les productions ; "video" / "declaration"
        → uniquement celles de ce format.
        """
        sql = "SELECT * FROM overlays WHERE active = 1"
        params: list = []
        if overlay_type:
            sql += " AND overlay_type = ?"
            params.append(overlay_type)
        if format:
            sql += " AND (format_scope = 'all' OR format_scope = ?)"
            params.append(format)
        sql += " ORDER BY id"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def single_active_overlay(self, overlay_type: str, format: str | None = None) -> dict | None:
        """Le plus récent overlay actif du type, ou None si aucun.

        Priorise le périmètre exact (ex. "video") sur "all" : si un intro
        "video" et un intro "all" sont actifs, une génération format "video"
        utilisera l'intro "video", tandis qu'une génération "declaration"
        retombera sur "all". Tous les overlays restent enregistrés pour
        switcher selon la période.
        """
        rows = self.active_overlays(overlay_type=overlay_type, format=format)
        if not rows:
            return None
        if format:
            exact = [r for r in rows if r["format_scope"] == format]
            if exact:
                return exact[-1]
            # fallback : périmètre "all"
            generic = [r for r in rows if r["format_scope"] == "all"]
            if generic:
                return generic[-1]
        return rows[-1]

    def seed_default_formats(self, schedule: list[str]) -> None:
        """Crée les deux formats par défaut si la table est vide (migration)."""
        with self.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM post_formats").fetchone()[0]
        if count:
            return
        self.create_format(
            "Clés de la Prospérité",
            "",
            [s for s in schedule if s in ("08:00", "16:00")],
            "short_comment",
            ["facebook", "youtube", "tiktok"],
            True,
        )
        self.create_format(
            "Déclarations prophétiques",
            "",
            [s for s in schedule if s in ("00:00", "12:00")],
            "image_text",
            ["facebook", "youtube", "tiktok"],
            True,
        )
