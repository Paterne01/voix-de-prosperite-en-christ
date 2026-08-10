from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .config import absolute_path
from .secrets import get_secret

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}

CAPTION_SYSTEM_PROMPT = """Tu écris pour la page chrétienne francophone « Voix de Prospérité en Christ ».
L'utilisateur a choisi un fichier (image ou vidéo) à publier manuellement. Le NOM du fichier
contient l'idée du message (ex. « pardon.jpeg », « provision-divine.mp4 »).

Écris une LÉGENDE en français oral, direct et chaleureux, au « tu », 1 à 3 phrases maximum,
en lien avec le thème du nom de fichier. La légende est le texte visible du post ; n'ajoute
aucun commentaire long. Ne promets jamais richesse, guérison ou résultat garanti. Reste
dans l'esprit des 7 piliers de la prospérité chrétienne (dignité, sagesse, libération,
productivité, restauration relationnelle, provision active, générosité).

Réponds EXCLUSIVEMENT avec la légende seule, sans guillemets, sans titre, sans hashtags."""


def pending_dir(config: dict) -> Path:
    path = absolute_path(config.get("paths", {}).get("pending", "assets/pending"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def kind_of(name: str) -> str | None:
    suffix = Path(name).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    return None


def list_pending(config: dict) -> list[dict]:
    directory = pending_dir(config)
    items = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        stat = path.stat()
        items.append({
            "name": path.name,
            "kind": kind_of(path.name),
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        })
    items.sort(key=lambda item: item["modified"], reverse=True)
    return items


def delete_pending(config: dict, name: str) -> bool:
    path = pending_dir(config) / name
    if path.is_file():
        path.unlink()
        return True
    return False


def humanize_filename(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[_-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem


def generate_caption(filename: str) -> str:
    """Légende générée par l'IA depuis le nom du fichier (repli : nom lisible)."""
    humanized = humanize_filename(filename)
    key = get_secret("gemini_api_key")
    if not key:
        return f"{humanized} — reçois cette parole et laisse-la agir dans ta journée. 🙏"
    try:
        from google import genai

        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{CAPTION_SYSTEM_PROMPT}\n\nNom du fichier : {filename}",
        )
        caption = (response.text or "").strip()
        return caption[:280] or f"{humanized} — reçois cette parole. 🙏"
    except Exception:
        return f"{humanized} — reçois cette parole et laisse-la agir dans ta journée. 🙏"
