from __future__ import annotations

import subprocess
from pathlib import Path

from .config import ROOT

SHORTS_MAX_SECONDS = 60


def build_short_video(
    image_path: str | Path,
    audio_path: str | Path,
    output_dir: str | Path | None = None,
    max_duration: int = SHORTS_MAX_SECONDS,
) -> Path:
    """Build a YouTube Short (1080×1920, max 60 s) from a still image + audio.

    Utilisé pour les fonds IMAGE : Ken Burns simple (image animée) par boucle
    d'image + audio. Les fonds vidéo passent par build_short_video_from_video().
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

    # -loop 1 répète l'image ; -t coupe le tout à max_duration.
    cmd = [
        "ffmpeg",
        "-y",
        "-loop", "1",
        "-i", str(image),
        "-i", str(audio),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "28",
        "-c:a", "aac",
        "-b:a", "128k",
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,format=yuv420p",
        "-t", str(max_duration),
        "-movflags", "+faststart",
        str(output),
    ]
    _run(cmd)
    return output


def build_short_video_from_video(
    background_video: str | Path,
    overlay_path: str | Path,
    audio_path: str | Path,
    output_dir: str | Path | None = None,
    max_duration: int = SHORTS_MAX_SECONDS,
) -> Path:
    """Short 1080×1920 depuis un fond VIDÉO bouclé + calque texte (PNG transparent).

    La vidéo fond est mise en boucle (-stream_loop -1) si elle est plus courte
    que la durée cible, puis rognée en 9:16 ; le calque (titre/CTA/logo) est
    superposé par-dessus ; l'audio est mixé en fond.
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

    cmd = [
        "ffmpeg",
        "-y",
        "-stream_loop", "-1",
        "-i", str(bg),
        "-i", str(overlay),
        "-i", str(audio),
        "-filter_complex",
        (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,format=yuv420p[v0];"
            "[1:v]scale=1080:1920[ov];"
            "[v0][ov]overlay=0:0:format=auto[v]"
        ),
        "-map", "[v]",
        "-map", "2:a",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "28",
        "-c:a", "aac",
        "-b:a", "128k",
        "-t", str(max_duration),
        "-movflags", "+faststart",
        str(output),
    ]
    _run(cmd)
    return output


def crop_to_short(
    input_video: str | Path,
    output_dir: str | Path | None = None,
    max_duration: int = SHORTS_MAX_SECONDS,
) -> Path:
    """Recadre une vidéo existante en Short 9:16 (1080×1920), son original conservé.

    Si la vidéo source est déjà 9:16 elle est simplement transcodée ; sinon elle
    est rognée (crop) au centre. L'audio est conservé s'il existe, sinon un
    silence est ajouté pour que le fichier reste lisible partout.
    """
    src = Path(input_video)
    if not src.exists():
        raise FileNotFoundError(f"Vidéo introuvable : {src}")
    output = (
        Path(output_dir) if output_dir else ROOT / "Videos"
    ) / f"short_cropped_{src.stem}.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(src)],
        capture_output=True, text=True,
    )
    has_audio = bool(probe.stdout.strip())

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(src),
    ]
    audio_inputs = []
    if has_audio:
        audio_inputs = ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-f", "lavfi", "-t", str(max_duration), "-i", "anullsrc=r=44100:cl=stereo"]
        audio_inputs = ["-map", "1:a", "-c:a", "aac", "-b:a", "128k"]
    cmd += [
        "-filter_complex",
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,format=yuv420p,setpts=PTS-STARTPTS[v]",
        "-map", "[v]",
        *audio_inputs,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "28",
        "-t", str(max_duration),
        "-movflags", "+faststart",
        str(output),
    ]
    _run(cmd)
    return output


def _run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffmpeg introuvable. Installez-le via winget install Gyan.FFmpeg "
            "ou https://ffmpeg.org et ajoutez-le au PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"ffmpeg a échoué (code {exc.returncode}) : {exc.stderr}"
        ) from exc
