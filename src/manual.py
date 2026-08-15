from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .config import absolute_path
from .llm import ordered_providers

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
    from .config import load_config

    humanized = humanize_filename(filename)
    try:
        config = load_config()
        if not ordered_providers(config):
            raise RuntimeError("Aucun provider LLM configuré")
        from .llm import generate_with_fallback

        raw, _provider = generate_with_fallback(
            config,
            CAPTION_SYSTEM_PROMPT,
            f"Nom du fichier : {filename}",
            do_json=False,
            max_tokens=120,
        )
        caption = str(raw).strip()
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
    from .config import load_config

    humanized = humanize_filename(filename)
    fallback = {
        "title": (caption.splitlines()[0] if caption else humanized)[:100] or humanized[:100],
        "tags": list(_DEFAULT_YOUTUBE_TAGS),
        "description": caption or humanized,
    }
    try:
        config = load_config()
        if not ordered_providers(config):
            return fallback
        from .llm import generate_with_fallback

        data, _provider = generate_with_fallback(
            config,
            YOUTUBE_META_SYSTEM_PROMPT,
            (
                f"Nature de la vidéo : {'vidéo classique (pas un Short)' if long_video else 'Short'}\n"
                f"Nom du fichier : {filename}\nLégende : {caption}"
            ),
            do_json=True,
            max_tokens=300,
        )
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
