from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
EXAMPLE_PATH = ROOT / "config.example.json"

# Associe un format de publication au sous-espace d'assets correspondant.
FORMAT_KEYS = {
    "video": "format_a",
    "declaration": "format_b",
    "short_comment": "format_a",
    "image_text": "format_b",
    "format_a": "format_a",
    "format_b": "format_b",
    "manual": "format_c",
    "format_c": "format_c",
}

# Les 7 points (piliers) de la prospérité chrétienne. Ce sont les THÈMES que
# chaque post doit servir. Par défaut, plan hebdomadaire : un point par jour.
DEFAULT_WEEK_PILLARS = {
    "monday": "Dignité",
    "tuesday": "Sagesse",
    "wednesday": "Libération",
    "thursday": "Productivité",
    "friday": "Restauration relationnelle",
    "saturday": "Provision Active",
    "sunday": "Générosité",
}


def weekday_pillar(config: dict[str, Any], when: datetime | None = None) -> str | None:
    """Pilier imposé pour un jour donné (défaut : aujourd'hui).

    Lit `config.content_plan` :
      - {"mode": "day_based"} (valeur par défaut) — renvoie le pilier du jour
        via `week` (dictionnaire jour -> pilier, clés anglaises monday..sunday) ;
      - {"mode": "random"} — renvoie None et les générateurs choisissent au hasard ;
      - {"mode": "day_based", "week": {...}} — plan personnalisé.
    En cas de plan invalide ou incomplet, on retombe sur DEFAULT_WEEK_PILLARS
    puis sur None (choix aléatoire) plutôt que de casser la génération.
    """
    plan = config.get("content_plan") or {}
    if not isinstance(plan, dict):
        plan = {}
    if book_mode(plan) == "random":
        return None
    week = plan.get("week")
    if not isinstance(week, dict) or not week:
        week = dict(DEFAULT_WEEK_PILLARS)
    day = (when or datetime.now()).strftime("%A").lower()
    return week.get(day) or DEFAULT_WEEK_PILLARS.get(day)


def book_mode(plan: dict[str, Any]) -> str:
    """Mode du plan de contenu : 'day_based' (défaut) ou 'random'."""
    return "random" if plan.get("mode") == "random" else "day_based"


def asset_dirs(config: dict[str, Any], format: str) -> tuple[Path, Path]:
    """(dossier_backgrounds, dossier_audio) du format demandé.

    La config embarque une table `paths.formats` (format_a / format_b) avec
    chacune un dossier backgrounds/ et audio/. Repli sur l'ancienne clé
    `paths.backgrounds` puis sur le défaut format_a pour ne rien casser.
    """
    key = FORMAT_KEYS.get(format, "format_a")
    formats = config.get("paths", {}).get("formats", {})
    entry = formats.get(key, {}) if isinstance(formats, dict) else {}
    default_bg = config.get("paths", {}).get("backgrounds", "assets/format_a/backgrounds")
    bg = absolute_path(entry.get("backgrounds") or default_bg)
    audio = absolute_path(entry.get("audio") or f"assets/{key}/audio")
    return bg, audio


def load_config() -> dict[str, Any]:
    """Load public configuration and create the working file on first run."""
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config.setdefault("manual_schedule", {
        "mode": "slots",
        "slots": ["04:00", "20:00"],
        "interval_hours": 4,
        "start_hour": "00:00",
        "networks": ["facebook", "youtube", "tiktok"],
    })
    for name in ("images", "texts", "logs", "manual_review", "backgrounds", "pending"):
        (ROOT / config["paths"][name]).mkdir(parents=True, exist_ok=True)
    formats = config.get("paths", {}).get("formats", {})
    if isinstance(formats, dict):
        for entry in formats.values():
            if isinstance(entry, dict):
                for sub in entry.values():
                    (ROOT / sub).mkdir(parents=True, exist_ok=True)
    # Format C (manuel) — dossier musique de fond
    (ROOT / "assets/format_c/audio").mkdir(parents=True, exist_ok=True)
    (ROOT / config["paths"]["database"]).parent.mkdir(parents=True, exist_ok=True)
    return config


def save_config(config: dict[str, Any]) -> None:
    """Persist only non-secret configuration."""
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def absolute_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def format_for(config: dict[str, Any], slot: str, default: str = "video") -> str:
    """Format (video | declaration) associé à un créneau horaire HH:MM."""
    return config.get("schedule_formats", {}).get(slot, default)
