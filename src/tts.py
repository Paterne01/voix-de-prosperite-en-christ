"""Voix off gTTS (Google Text-to-Speech) — français naturel.

Remplace edge-tts : gTTS produit une voix française fluide (lang='fr',
tld='fr' = accent français). Si le réseau coupe, on retombe sur un bip
silencieux propre plutôt que de casser la publication.
"""
from __future__ import annotations

import re
from pathlib import Path

VOICE = "gTTS-fr (Google, accent français)"
_LANG = "fr"
_TLD = "fr"  # accent français ; fallback 'com' si indisponible


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


def text_to_speech(text: str, output_path: str) -> str:
    """Synthèse vocale gTTS -> MP3. Retourne le chemin."""
    from gtts import gTTS

    text = (text or "").strip()
    if not text:
        raise ValueError("Texte vide pour la synthèse vocale")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    chunks = _split_chunks(text)
    if len(chunks) == 1:
        try:
            gTTS(chunks[0], lang=_LANG, slow=False, tld=_TLD).save(str(out))
        except Exception:
            gTTS(chunks[0], lang=_LANG, slow=False).save(str(out))
        return str(out)
    # Texte long : un MP3 par morceau puis concat via ffmpeg
    import subprocess
    import tempfile

    parts: list[Path] = []
    tmpdir = Path(tempfile.mkdtemp(prefix="vp_gtts_"))
    try:
        for i, ch in enumerate(chunks):
            p = tmpdir / f"part_{i}.mp3"
            try:
                gTTS(ch, lang=_LANG, slow=False, tld=_TLD).save(str(p))
            except Exception:
                gTTS(ch, lang=_LANG, slow=False).save(str(p))
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
    title = (content.get("title") or "").strip()
    hook = (content.get("hook") or "").strip()
    if title and hook:
        return f"{title}. {hook}"
    return title or hook
