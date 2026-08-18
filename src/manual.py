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
    """Supprime un fichier en attente, en réessayant si un processus le verrouille.

    Sur Windows, la suppression peut échouer avec WinError 32 (fichier utilisé
    par un autre processus, ex. ffprobe qui lit encore la durée). On réessaie
    pendant quelques secondes avant d'abandonner.
    """
    path = pending_dir(config) / name
    if not path.is_file():
        return True
    import time

    for attempt in range(6):
        try:
            path.unlink()
            return True
        except OSError:
            if attempt == 5:
                return False
            time.sleep(1.5)
    return False


def humanize_filename(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[_-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem


def _looks_complete(text: str, min_length: int = 40) -> bool:
    """Vrai quand un texte généré par l'IA semble complet (ni tronqué, ni vide).

    Une réponse coupée (finish=length ou sortie interrompue) finit souvent par
    une virgule, un tiret, un espace ou une préposition sans ponctuation finale.
    On refuse aussi les sorties minuscules qui ne tiennent pas une phrase.
    """
    t = (text or "").strip()
    if len(t) < min_length:
        return False
    last = t[-1]
    if last in ",;:-—–•|":
        return False
    # Une phrase française raisonnable se termine par une ponctuation forte
    # (ou une emoji / guillemet fermant pour les légendes religieuses).
    if last.isalpha() or last.isdigit():
        return False
    return True


def _validate_caption(raw) -> None:
    if not _looks_complete(str(raw), min_length=30):
        raise ValueError(f"Légende tronquée ou trop courte : {str(raw)[:60]!r}")


def generate_caption(filename: str) -> str:
    """Légende générée par l'IA depuis le nom du fichier (repli : nom lisible).

    La réponse est refusée si elle est trop courte ou visiblement coupée :
    chaque provider configuré est alors essayé, et si tous échouent on retombe
    sur une légende déterministe complète (jamais de texte tronqué publié).
    """
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
            validate=_validate_caption,
        )
        caption = str(raw).strip()
        return caption[:280]
    except Exception:
        return f"{humanized} — reçois cette parole et laisse-la agir dans ta journée. 🙏"


# Tags YouTube par défaut (repli si l'IA est indisponible).
_DEFAULT_YOUTUBE_TAGS = [
    "Voix de Prospérité en Christ", "foi", "Bible", "prospérité", "prière",
    "parole du jour", "sagesse divine", "motivation chrétienne",
]


def _validate_youtube_meta(data) -> None:
    """Refuse des métadonnées YouTube tronquées (titre coupé, description vide)."""
    if not isinstance(data, dict):
        raise ValueError(f"Métadonnées YouTube non JSON : {str(data)[:60]!r}")
    title = str(data.get("title") or "").strip()
    if len(title) < 15:
        raise ValueError(f"Titre YouTube trop court : {title!r}")
    description = str(data.get("description") or "").strip()
    if not _looks_complete(description, min_length=30):
        raise ValueError(f"Description YouTube tronquée : {description[:60]!r}")
    tags = data.get("tags") or []
    if not isinstance(tags, list) or not tags:
        raise ValueError("Métadonnées YouTube sans tags")


def generate_youtube_metadata(filename: str, caption: str, *, long_video: bool = False) -> dict:
    """Titre, tags et description optimisés pour YouTube, générés par l'IA
    depuis le nom du fichier + la légende.

    Retourne {"title", "tags", "description"}. La description reprend la
    légende (le texte visible Facebook/TikTok) ; les tags servent au champ
    « tags » de YouTube ; le titre est optimisé pour la recherche. Repli
    déterministe si l'IA est absente, échoue OU renvoie des métadonnées
    tronquées. `long_video` adapte le vocabulaire (Short vs vidéo classique).
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
            validate=_validate_youtube_meta,
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
