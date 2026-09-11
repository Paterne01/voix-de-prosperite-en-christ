"""Voix off masculine — chaîne : edge-tts (Henri, neural) → Piper local (tom)
→ gTTS (dernier recours).

- edge-tts : la plus humaine (gratuit, voix masculine mûre fr-FR-HenriNeural).
- Piper `fr_FR-tom-medium` : synthèse LOCALE (aucun réseau, toujours dispo),
  voix d'homme française naturelle, bien au-dessus de gTTS.
- gTTS : repli ultime (sonorité robotique).
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

# Voix Piper locale (homme FR, embarquée : assets/tts_voices/).
PIPER_VOICE = "fr_FR-tom-medium"


def _piper_model_path() -> Path:
    from .config import ROOT

    return ROOT / "assets" / "tts_voices" / f"{PIPER_VOICE}.onnx"


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
    """Synthèse vocale homme : edge-tts → Piper local → gTTS (dernier recours)."""
    import asyncio

    text = (text or "").strip()
    if not text:
        raise ValueError("Texte vide pour la synthèse vocale")
    voice = (voice or VOICE or DEFAULT_VOICE).strip()
    # gTTS explicite demandé via config ("gTTS...") : honore le choix
    if voice.lower().startswith("gtts"):
        return _gtts(text, output_path)
    # Piper explicite demandé via config ("piper...") : voix locale directe
    if voice.lower().startswith("piper"):
        return _piper(text, output_path)
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
        pass
    try:
        return _piper(text, output_path)
    except Exception:
        return _gtts(text, output_path)


def _piper(text: str, output_path: str) -> str:
    """Voix Piper locale (fr_FR-tom-medium, homme) : WAV 22050 Hz, sans réseau."""
    import wave

    from piper import PiperVoice

    model = _piper_model_path()
    if not model.is_file():
        raise FileNotFoundError(f"Voix Piper absente : {model}")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wav_path = out.with_suffix(".wav") if out.suffix.lower() != ".wav" else out
    voice = PiperVoice.load(str(model))
    with wave.open(str(wav_path), "wb") as wav:
        voice.synthesize_wav(text, wav)
    return str(wav_path)


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
