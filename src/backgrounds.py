from __future__ import annotations

import random
from pathlib import Path

from .config import asset_dirs

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}


def pick_background(config: dict, database, format: str = "video") -> tuple[str | None, str | None, str]:
    """Choisit un fond aléatoire (image OU vidéo) dans le dossier backgrounds/
    du format concerné, en excluant les fonds déjà utilisés sur 90 jours.

    Returns
    -------
    (nom_du_fond, chemin_absolu, type) — (None, None, "image") si aucun fond.
    type vaut "image" ou "video" selon l'extension retenue.
    """
    directory, _ = asset_dirs(config, format)
    if not directory.is_dir():
        return None, None, "image"

    candidates: list[Path] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in _IMAGE_EXTENSIONS or suffix in _VIDEO_EXTENSIONS:
            candidates.append(path)
    if not candidates:
        return None, None, "image"

    recent = database.recent_backgrounds(days=90)
    pool = [path for path in candidates if path.name not in recent]
    if not pool:
        pool = candidates

    chosen = random.choice(pool)
    kind = "video" if chosen.suffix.lower() in _VIDEO_EXTENSIONS else "image"
    return chosen.name, str(chosen), kind
