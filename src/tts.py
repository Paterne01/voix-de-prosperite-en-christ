"""Voix off masculine neurale (edge-tts) — homme 25-50 ans, grave et inspirant.

gTTS ne propose qu'une seule voix fixe par langue (sonorité féminine, sans
choix possible) : pour une voix d'homme profonde, on utilise edge-tts neural
avec une voix masculine FR (défaut : fr-FR-HenriNeural, mûre et posée).
Repli automatique sur gTTS si le réseau coupe.
"""
from __future__ import annotations

import re
from pathlib import Path

# Voix masculine FR dispo (edge-tts) : fr-FR-HenriNeural (défaut, mûre),
# fr-FR-AlainNeural, fr-FR-ClaudeNeural, fr-FR-JeromeNeural, fr-FR-MauriceNeural.
DEFAULT_VOICE = "fr-FR-HenriNeural"
VOICE = DEFAULT_VOICE
# Débit légèrement ralenti (solennel) + ton un peu plus grave, sans robotiser.
RATE = "-5%"
PITCH = "-2Hz"


def _split_chunks(text: str, max_chars: int = 400) -> list[str]:
    """Découpe un long texte en morceaux < max_chars sur frontières de phrases."""
    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    chunks, cur = [], ""
    for s in sentences:
        if len(cur) + len(s) + 1 <= max_chars:
            cur = f"{cur} {s}".strip()
        else:
            if cur:
                chunks.append(cur)
            cur = s
    if cur:
        chunks.append(cur)
    return chunks or [text]


def text_to_speech(text: str, output_path: str, voice: str | None = None) -> str:
    """Synthèse vocale homme (edge-tts neural) -> MP3. Repli gTTS si échec."""
    import asyncio

    text = (text or "").strip()
    if not text:
        raise ValueError("Texte vide pour la synthèse vocale")
    voice = (voice or VOICE or DEFAULT_VOICE).strip()
    # gTTS explicite demandé via config ("gTTS...") : honore le choix
    if voice.lower().startswith("gtts"):
        return _gtts(text, output_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        import edge_tts

        async def _run() -> None:
            comm = edge_tts.Communicate(text, voice, rate=RATE, pitch=PITCH)
            await comm.save(str(out))

        asyncio.run(_run())
        return str(out)
    except Exception:
        return _gtts(text, output_path)


def _gtts(text: str, output_path: str) -> str:
    """Repli gTTS (voix Google standard)."""
    from gtts import gTTS

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    chunks = _split_chunks(text)
    if len(chunks) == 1:
        try:
            gTTS(chunks[0], lang="fr", slow=False, tld="fr").save(str(out))
        except Exception:
            gTTS(chunks[0], lang="fr", slow=False).save(str(out))
        return str(out)
    import subprocess
    import tempfile

    parts: list[Path] = []
    tmpdir = Path(tempfile.mkdtemp(prefix="vp_gtts_"))
    try:
        for i, ch in enumerate(chunks):
            p = tmpdir / f"part_{i}.mp3"
            try:
                gTTS(ch, lang="fr", slow=False, tld="fr").save(str(p))
            except Exception:
                gTTS(ch, lang="fr", slow=False).save(str(p))
            parts.append(p)
        lst = tmpdir / "list.txt"
        lst.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-c", "copy", str(out)],
            check=True, capture_output=True, text=True,
        )
    finally:
        for p in parts:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
    return str(out)


def build_narration_text(content: dict, format: str = "video") -> str:
    """Texte LU par la voix off = UNIQUEMENT le texte affiché à l'écran.

    - Format A (video) : titre + accroche (ce qui est gravé sur l'image).
      Les points / vérité / CTA du commentaire NE sont PAS lus.
    - Format B (declaration) : déclaration + clôture (texte de l'image).
    """
    if format == "declaration" or content.get("declaration"):
        decl = content.get("declaration") or content.get("title") or content.get("hook") or content.get("caption") or ""
        closure = content.get("closure") or ""
        # La déclaration contient déjà le verset ; on ajoute la clôture
        return " ".join(p.strip() for p in (decl, closure) if p and p.strip())
    # Format A : la légende ENTIÈRE (titre + accroche + phrase "détail en
    # commentaire") — jamais les points du commentaire, mais on tease pour
    # inciter à ouvrir les commentaires.
    caption = (content.get("caption") or "").strip()
    if caption:
        return caption
    title = (content.get("title") or "").strip()
    hook = (content.get("hook") or "").strip()
    if title and hook:
        return f"{title}. {hook}"
    return title or hook
