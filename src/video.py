from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import ROOT

SHORTS_MAX_SECONDS = 60

# Coins possibles pour le watermark texte.
_WATERMARK_POSITIONS = {
    "bottom-right": "(w-tw-40):(h-th-40)",
    "bottom-left": "40:(h-th-40)",
    "top-right": "(w-tw-40):40",
    "top-left": "40:40",
}


def build_short_video(
    image_path: str | Path,
    audio_path: str | Path,
    output_dir: str | Path | None = None,
    max_duration: int = SHORTS_MAX_SECONDS,
    intro_path: str | Path | None = None,
    outro_path: str | Path | None = None,
    watermark_path: str | Path | None = None,
    watermark_text: str | None = None,
) -> Path:
    """Build a YouTube Short (1080×1920, max 60 s) from a still image + audio.

    Phase 1 : image animée (boucle) + audio, avec le watermark (image PNG ou
    texte drawtext) gravé dedans. Phase 2 : intro/outro (clips vidéo) ajoutés
    par concat, l'ensemble restant borné à max_duration.
    """
    image, audio = Path(image_path), Path(audio_path)
    if not image.exists():
        raise FileNotFoundError(f"Image introuvable : {image}")
    if not audio.exists():
        raise FileNotFoundError(f"Audio introuvable : {audio}")

    output = (
        Path(output_dir) if output_dir else ROOT / "Images"
    ) / f"short_{image.stem}.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)

    wm = watermark_to_path(watermark_path) if watermark_path else None

    # ── Phase 1 : le short de base (sans intro/outro) ────────────────
    vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    if wm is not None:
        vf += _wm_image_chain(1)
    if watermark_text:
        vf += _wm_text_chain(watermark_text, 2 if wm is not None else 1)
    vf += ",format=yuv420p"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image),
        "-i", str(audio),
        *(["-i", str(wm)] if wm is not None else []),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac", "-b:a", "128k",
        "-vf", vf,
        "-t", str(max_duration),
        "-movflags", "+faststart",
        str(output),
    ]
    _run(cmd)

    # ── Phase 2 : intro / outro par concat ───────────────────────────
    pieces = []
    if intro_path:
        pieces.append(("intro", Path(intro_path)))
    pieces.append(("main", output))
    if outro_path:
        pieces.append(("outro", Path(outro_path)))
    if len(pieces) == 1:
        return output
    _concat_with_overlays(pieces, output, max_duration=max_duration)
    return output


def build_short_video_from_video(
    background_video: str | Path,
    overlay_path: str | Path,
    audio_path: str | Path,
    output_dir: str | Path | None = None,
    max_duration: int = SHORTS_MAX_SECONDS,
    intro_path: str | Path | None = None,
    outro_path: str | Path | None = None,
    watermark_path: str | Path | None = None,
    watermark_text: str | None = None,
) -> Path:
    """Short 1080×1920 depuis un fond VIDÉO bouclé + calque texte (PNG transparent).

    Idem build_short_video : gravure du watermark puis concat intro/outro.
    """
    bg, overlay, audio = Path(background_video), Path(overlay_path), Path(audio_path)
    if not bg.exists():
        raise FileNotFoundError(f"Vidéo de fond introuvable : {bg}")
    if not overlay.exists():
        raise FileNotFoundError(f"Calque de texte introuvable : {overlay}")
    if not audio.exists():
        raise FileNotFoundError(f"Audio introuvable : {audio}")

    output = (
        Path(output_dir) if output_dir else ROOT / "Images"
    ) / f"short_{bg.stem}.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)

    wm = watermark_to_path(watermark_path) if watermark_path else None

    chain = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,format=yuv420p[v0];"
        "[1:v]scale=1080:1920[ov];"
        "[v0][ov]overlay=0:0:format=auto[vb]"
    )
    n_wm = 0
    if wm is not None:
        n_wm = 1
        chain += _wm_image_chain(2, prev_label="vb")  # input 2 = watermark
    if watermark_text:
        n_wm += 1
        chain += _wm_text_chain(watermark_text, n_wm, prev_label=("vb" if wm is None else "v_wm"))
    chain += _wm_out_to_vlabel(n_wm, "vb")

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", str(bg),
        "-i", str(overlay),
        "-i", str(audio),
        *(["-i", str(wm)] if wm is not None else []),
        "-filter_complex", chain,
        "-map", "2:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac", "-b:a", "128k",
        "-t", str(max_duration),
        "-movflags", "+faststart",
        str(output),
    ]
    _run(cmd)

    pieces = []
    if intro_path:
        pieces.append(("intro", Path(intro_path)))
    pieces.append(("main", output))
    if outro_path:
        pieces.append(("outro", Path(outro_path)))
    if len(pieces) == 1:
        return output
    _concat_with_overlays(pieces, output, max_duration=max_duration)
    return output


# ── helpers watermark / concat ──────────────────────────────────────


def watermark_to_path(value: str | Path) -> Path:
    """Fichier watermark : chemin relatif résolu depuis la racine du projet."""
    p = Path(value)
    if p.exists():
        return p
    resolved = ROOT / p
    return resolved


def _wm_text_chain(text: str, label: int, prev_label: str = "v") -> str:
    escaped = (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )
    pos = _WATERMARK_POSITIONS["bottom-right"]
    return (
        f";[{prev_label}]drawtext=text='{escaped}':fontsize=34:fontcolor=white@0.55:"
        f"x={pos},setpts=PTS-STARTPTS,format=yuv420p[v{label}]"
    )


def _wm_image_chain(label: int, prev_label: str = "v") -> str:
    """Superpose une image watermark (label=index d'entrée ffmpeg) en bas-droit."""
    return (
        f";[{label}:v]scale=w=180:h=-1:force_original_aspect_ratio=decrease,"
        f"format=rgba[wm{label}];"
        f"[{prev_label}][wm{label}]overlay=W-w-40:H-h-40:format=auto[v_wm{label}]"
    )


def _wm_out_to_vlabel(n_wm: int, base_label: str) -> str:
    """Dernier label produit par les watermark (ou le label de base si aucun)."""
    if n_wm == 0:
        return ""
    return f"[v_wm{n_wm}]"