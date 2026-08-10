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
            try:
                conn.execute("ALTER TABLE post_formats ADD COLUMN tier TEXT NOT NULL DEFAULT 'free'")
            except sqlite3.OperationalError:
                pass
            for col in (
                "youtube_video_id", "youtube_url", "youtube_comment_id", "youtube_comment_url",
                "tiktok_publish_id", "tiktok_url",
                "format", "background", "format_name", "source_filename",
            ):
                try:
                    conn.execute(f"ALTER TABLE publications ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError:
                    pass

    def recent_values(self, column: str, days: int = 90) -> set[str]:
        allowed = {"title", "topic", "verse_reference", "cta", "decor"}
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
        allowed = {"image_path", "facebook_post_id", "facebook_url", "youtube_video_id", "youtube_url", "youtube_comment_id", "youtube_comment_url", "tiktok_publish_id", "tiktok_url", "status", "error", "format", "background", "format_name", "source_filename"}
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
                "SELECT 1 FROM publications WHERE scheduled_for LIKE ? AND status = 'published' LIMIT 1",
                (f"{today}T{schedule_time}%",),
            ).fetchone()
        return row is None

    def manual_slot_done(self, day: str, slot: str) -> bool:
        """Vrai si un contenu manuel a déjà été publié pour ce créneau ce jour-là."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM publications WHERE scheduled_for LIKE ? AND format = 'manual' "
                "AND status IN ('published', 'partial') LIMIT 1",
                (f"{day}T{slot}%",),
            ).fetchone()
        return row is not None

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
