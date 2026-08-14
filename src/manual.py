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

YOUTUBE_META_SYSTEM_PROMPT = """Tu es un spécialiste du SEO YouTube pour la chaîne chrétienne francophone
« Voix de Prospérité en Christ » (7 piliers : dignité, sagesse, libération, productivité,
restauration relationnelle, provision active, générosité).

À partir du NOM du fichier (qui contient l'idée du message) et de la LÉGENDE fournie, produis
les métadonnées optimales pour publier la vidéo (Short ou vidéo classique, selon la nature indiquée) :
- "title" : un titre accrocheur en français, 15 mots maximum, jamais de promesse de richesse,
  guérison ou résultat garanti ;
- "tags" : 6 à 10 mots-clés de recherche en français, courts, sans « # », liés au thème
  (ex. "foi", "prière", "prospérité divine", "parole du jour") ;
- "description" : la légende enrichie en 2-3 phrases au « tu », chaleureuse et directe,
  sans promesse garantie.

Réponds EXCLUSIVEMENT avec un objet JSON valide :
{"title":"...","tags":["...","..."],"description":"..."}"""


def _extract_json(text: str) -> dict:
    """Extrait le premier objet JSON du texte (tolère les blocs ```json … ```)."""
    import json

    text = text.strip().removeprefix("```json").removeprefix("```").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("Aucun objet JSON dans la réponse de l'IA")
    return json.loads(text[start:end + 1])


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
    items.sort(key=lambda item: item["modified"])
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


# Tags YouTube par défaut (repli si l'IA est indisponible).
_DEFAULT_YOUTUBE_TAGS = [
    "Voix de Prospérité en Christ", "foi", "Bible", "prospérité", "prière",
    "parole du jour", "sagesse divine", "motivation chrétienne",
]


def generate_youtube_metadata(filename: str, caption: str, *, long_video: bool = False) -> dict:
    """Titre, tags et description optimisés pour YouTube, générés par l'IA
    depuis le nom du fichier + la légende.

    Retourne {"title", "tags", "description"}. La description reprend la
    légende (le texte visible Facebook/TikTok) ; les tags servent au champ
    « tags » de YouTube ; le titre est optimisé pour la recherche. Repli
    déterministe si l'IA est absente ou échoue. `long_video` adapte le
    vocabulaire (Short vs vidéo classique).
    """
    humanized = humanize_filename(filename)
    fallback = {
        "title": (caption.splitlines()[0] if caption else humanized)[:100] or humanized[:100],
        "tags": list(_DEFAULT_YOUTUBE_TAGS),
        "description": caption or humanized,
    }
    key = get_secret("gemini_api_key")
    if not key:
        return fallback
    try:
        from google import genai

        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=(
                f"{YOUTUBE_META_SYSTEM_PROMPT}\n\n"
                f"Nature de la vidéo : {'vidéo classique (pas un Short)' if long_video else 'Short'}\n"
                f"Nom du fichier : {filename}\nLégende : {caption}"
            ),
        )
        data = _extract_json(response.text or "")
        title = str(data.get("title", "")).strip() or fallback["title"]
        tags = [
            str(t).strip().lstrip("#").strip()[:40]
            for t in data.get("tags", [])
        ]
        tags = [t for t in tags if t][:15] or fallback["tags"]
        description = str(data.get("description", "")).strip() or fallback["description"]
        return {"title": title[:100], "tags": tags, "description": description[:4900]}
    except Exception:
        return fallback
