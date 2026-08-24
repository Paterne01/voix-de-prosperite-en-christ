from __future__ import annotations

import subprocess
import tempfile
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import ROOT

SHORTS_MAX_SECONDS = 60

# Position du watermark (coin en bas à droite par défaut).
_WM_X = "W-w-40"
_WM_Y = "H-h-40"

# Taille cible du watermark PNG rendu depuis le texte.
_WM_CANVAS = 560, 140

# Extensions acceptées pour les clips intro/outro.
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".avi"}


def _is_image_file(path: Path) -> bool:
    return path.suffix.lower() in _IMAGE_EXTS


def _is_video_file(path: Path) -> bool:
    return path.suffix.lower() in _VIDEO_EXTS


def build_short_video(
    image_path: str | Path,
    audio_path: str | Path,
    output_dir: str | Path | None = None,
    max_duration: int = SHORTS_MAX_SECONDS,
    intro_path: str | Path | None = None,
    outro_path: str | Path | None = None,
    watermark_path: str | Path | None = None,
    watermark_text: str | None = None,
    intro_duration: int = 3,
    outro_duration: int = 3,
) -> Path:
    """Build a YouTube Short (1080×1920, max 60 s) from a still image + audio.

    Phase 1 : image animée (boucle Ken Burns) + audio, watermark (image PNG ou
    texte gravé via PIL) superposé en bas-droit. Phase 2 : intro/outro (clips
    vidéo OU images, converties en clip fixe de intro_duration/outro_duration s)
    concaténés, l'ensemble restant borné à max_duration.
    """
    image, audio = Path(image_path), Path(audio_path)
    if not image.exists():
        raise FileNotFoundError(f"Image introuvable : {image}")
    if not audio.exists():
        raise FileNotFoundError(f"Audio introuvable : {audio}")

    output_dir_p = Path(output_dir) if output_dir else ROOT / "Images"
    output = output_dir_p / f"short_{image.stem}.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)

    wm = _resolve_watermark(watermark_path, watermark_text)

    v_pad = _video_pad_chain("v0")
    seq, prev = 0, "v0"
    if wm is not None:
        ch, prev = _wm_image_chain(2, prev)
        v_pad.append(ch)
    chain = ";".join(v_pad)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image),
        "-i", str(audio),
        *(["-i", str(wm)] if wm is not None else []),
        "-filter_complex", chain,
        "-map", f"[{prev}]",
        "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac", "-b:a", "128k",
        "-t", str(max_duration),
        "-movflags", "+faststart",
        str(output),
    ]
    _run(cmd)

    intro_piece, outro_piece, temp_clips = _intro_outro_pieces(
        intro_path, outro_path, output_dir_p,
        intro_duration=intro_duration, outro_duration=outro_duration,
    )
    pieces: list[tuple[str, Path]] = []
    if intro_piece:
        pieces.append(("intro", intro_piece))
    pieces.append(("main", output))
    if outro_piece:
        pieces.append(("outro", outro_piece))
    try:
        if len(pieces) > 1:
            _concat_pieces(pieces, output, max_duration=max_duration)
    finally:
        for clip in temp_clips:
            try:
                clip.unlink(missing_ok=True)
            except OSError:
                pass
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
    intro_duration: int = 3,
    outro_duration: int = 3,
) -> Path:
    """Short 1080×1920 depuis un fond VIDÉO bouclé + calque texte (PNG transparent).

    Idem build_short_video : gravure du watermark puis concat intro/outro
    (vidéos ou images converties en clip fixe).
    """
    bg, overlay, audio = Path(background_video), Path(overlay_path), Path(audio_path)
    if not bg.exists():
        raise FileNotFoundError(f"Vidéo de fond introuvable : {bg}")
    if not overlay.exists():
        raise FileNotFoundError(f"Calque de texte introuvable : {overlay}")
    if not audio.exists():
        raise FileNotFoundError(f"Audio introuvable : {audio}")

    output_dir_p = Path(output_dir) if output_dir else ROOT / "Images"
    output = output_dir_p / f"short_{bg.stem}.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)

    wm = _resolve_watermark(watermark_path, watermark_text)

    chain = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,format=yuv420p[v0];"
        "[1:v]scale=1080:1920,format=rgba[ov];"
        "[v0][ov]overlay=0:0:format=auto[vb]"
    )
    prev = "vb"
    if wm is not None:
        ch, prev = _wm_image_chain(3, prev)
        chain += ";" + ch

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", str(bg),
        "-i", str(overlay),
        "-i", str(audio),
        *(["-i", str(wm)] if wm is not None else []),
        "-filter_complex", chain,
        "-map", f"[{prev}]",
        "-map", "2:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac", "-b:a", "128k",
        "-t", str(max_duration),
        "-movflags", "+faststart",
        str(output),
    ]
    _run(cmd)

    intro_piece, outro_piece, temp_clips = _intro_outro_pieces(
        intro_path, outro_path, output_dir_p,
        intro_duration=intro_duration, outro_duration=outro_duration,
    )
    pieces: list[tuple[str, Path]] = []
    if intro_piece:
        pieces.append(("intro", intro_piece))
    pieces.append(("main", output))
    if outro_piece:
        pieces.append(("outro", outro_piece))
    try:
        if len(pieces) > 1:
            _concat_pieces(pieces, output, max_duration=max_duration)
    finally:
        for clip in temp_clips:
            try:
                clip.unlink(missing_ok=True)
            except OSError:
                pass
    return output


def probe_duration(path: str | Path) -> float:
    """Durée en secondes d'un média (0.0 si non lisible)."""
    return _probe_duration(Path(path))


def crop_to_short(
    source: str | Path,
    output_dir: str | Path | None = None,
    max_duration: int = SHORTS_MAX_SECONDS,
    intro_path: str | Path | None = None,
    outro_path: str | Path | None = None,
    watermark_path: str | Path | None = None,
    watermark_text: str | None = None,
    intro_duration: int = 3,
    outro_duration: int = 3,
) -> Path:
    """Recadre une vidéo manuelle en 9:16 (1080×1920) pour publication en Short.

    Utilisé par le Format C (fichiers importés) : la vidéo source est
    normalisée en vertical, bornée à max_duration secondes, avec sa piste
    audio conservée, puis watermark + intro/outro sont appliqués comme pour
    les Shorts générés (même pipeline ffmpeg). Retourne le chemin du fichier
    produit.

    `max_duration` par défaut à 60 s mais l'appelant (service.publish_manual)
    passe `LONG_VIDEO_SECONDS` (90 s) pour les enseignements importés qui
    durent souvent 64-86 s. Les vidéos GÉNÉRÉES restent bornées à 60 s via
    leur propre paramètre.
    """
    src = Path(source)
    if not src.exists():
        raise FileNotFoundError(f"Vidéo introuvable : {src}")

    output_dir_p = Path(output_dir) if output_dir else ROOT / "Videos"
    output = output_dir_p / f"short_{src.stem}.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)

    # Phase 1 : normalisation 1080×1920 + watermark superposé
    wm = _resolve_watermark(watermark_path, watermark_text)
    if wm is not None:
        # Normalise avec watermark via filter_complex
        v_pad = _video_pad_chain("v0")
        ch, prev = _wm_image_chain(1, "v0")
        v_pad.append(ch)
        chain = ";".join(v_pad)
        src_str = str(src)
        cmd = [
            "ffmpeg", "-y",
            "-i", src_str,
            "-i", str(wm),
            "-filter_complex", chain,
            "-map", f"[{prev}]",
        ]
        if _has_audio(src):
            cmd += ["-map", "0:a", "-c:a", "aac", "-b:a", "128k"]
        else:
            cmd += ["-an"]
        cmd += [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
            "-t", str(max_duration) if max_duration else "9999",
            "-movflags", "+faststart",
            str(output),
        ]
        _run(cmd)
    else:
        _normalize_clip(src, output, dur=float(max_duration) if max_duration else None)

    # Phase 2 : intro/outro (images converties en clips ou vidéos telles quelles)
    intro_piece, outro_piece, temp_clips = _intro_outro_pieces(
        intro_path, outro_path, output_dir_p,
        intro_duration=intro_duration, outro_duration=outro_duration,
    )
    pieces: list[tuple[str, Path]] = []
    if intro_piece:
        pieces.append(("intro", intro_piece))
    pieces.append(("main", output))
    if outro_piece:
        pieces.append(("outro", outro_piece))
    try:
        if len(pieces) > 1:
            _concat_pieces(pieces, output, max_duration=max_duration)
    finally:
        for clip in temp_clips:
            try:
                clip.unlink(missing_ok=True)
            except OSError:
                pass
    return output


# ── helpers watermark / concat ──────────────────────────────────────


def watermark_to_path(value: str | Path) -> Path:
    """Fichier watermark : chemin relatif résolu depuis la racine du projet."""
    p = Path(value)
    if p.exists():
        return p
    return ROOT / p


def _resolve_watermark(watermark_path, watermark_text) -> Path | None:
    """Watermark à utiliser : le fichier image, sinon un PNG gravé du texte.

    Le texte prime sur le fichier s'il est fourni (le fichier peut être un
    PNG tampon de fallback). Un texte seul est rendu via PIL (gère la police
    système Windows sans dépendre de fontconfig).
    """
    if watermark_text and str(watermark_text).strip():
        png = _render_text_watermark(str(watermark_text).strip())
        if png is not None:
            return png
    if watermark_path:
        return watermark_to_path(watermark_path)
    return None


def _default_font(size: int):
    from PIL import ImageFont

    for path in (
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
    ):
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default()


def _render_text_watermark(text: str) -> Path | None:
    """Génère un PNG transparent (petit) contenant le texte du watermark."""
    try:
        canvas = Image.new("RGBA", _WM_CANVAS, (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        font = _default_font(56)
        # Bordure noire + texte blanc semi-transparent pour la lisibilité.
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
        except AttributeError:  # PIL < 8
            bbox = (0, 0, 0, 0)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x, y = 0, (_WM_CANVAS[1] - h) // 2 - bbox[1]
        draw.text((x - 2, y + 2), text, font=font, fill=(0, 0, 0, 140))
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 150))
        tmp = Path(tempfile.mkdtemp(prefix="vp_wm_")) / "watermark.png"
        canvas.save(tmp)
        return tmp
    except Exception:
        return None


def _intro_outro_pieces(
    intro_path: str | Path | None,
    outro_path: str | Path | None,
    output_dir: Path,
    intro_duration: int = 3,
    outro_duration: int = 3,
) -> tuple[Path | None, Path | None, list[Path]]:
    """Prépare les morceaux intro/outro avant concaténation.

    Un fichier IMAGE est d'abord converti en clip vidéo fixe (durée configurable)
    dans output_dir ; le clip temporaire est renvoyé dans temp_clips pour être
    supprimé après la concaténation (try/finally chez l'appelant). Un fichier
    vidéo est utilisé tel quel (comportement existant inchangé).
    """
    intro_piece, outro_piece = None, None
    temp_clips: list[Path] = []
    if intro_path:
        p = Path(intro_path)
        if _is_image_file(p):
            clip = _tmp_image_clip_path(output_dir, "intro")
            _image_to_clip(p, clip, duration_seconds=intro_duration)
            temp_clips.append(clip)
            intro_piece = clip
        else:
            intro_piece = p
    if outro_path:
        p = Path(outro_path)
        if _is_image_file(p):
            clip = _tmp_image_clip_path(output_dir, "outro")
            _image_to_clip(p, clip, duration_seconds=outro_duration)
            temp_clips.append(clip)
            outro_piece = clip
        else:
            outro_piece = p
    return intro_piece, outro_piece, temp_clips


def _tmp_image_clip_path(output_dir: Path, kind: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"tmp_{kind}_{uuid.uuid4().hex[:8]}.mp4"


def _image_to_clip(
    image_path: Path,
    output_path: Path,
    duration_seconds: int = 3,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> Path:
    """Convertit une image fixe en clip vidéo court (1080x1920).

    Fond noir si l'image ne remplit pas le cadre (pad, jamais de distorsion ni
    de crop), codec H.264, audio silencieux inclus pour que la concaténation
    ffmpeg ne plante pas sur un flux audio manquant. Durée par défaut : 3 s.
    """
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image_path),
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-vf",
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-t", str(duration_seconds),
        "-r", str(fps),
        str(output_path),
    ]
    _run(cmd)
    return output_path


def _video_pad_chain(label: str = "v0") -> list[str]:
    """Normalise l'entrée vidéo 0 en 1080×1920 yuv420p."""
    return [
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,format=yuv420p[{label}]"
    ]


def _wm_image_chain(wm_input: int, prev_label: str) -> tuple[str, str]:
    """Superpose une image watermark (entrée ffmpeg wm_input) en bas-droit.

    prev_label : label simple SANS crochets (ex. "v0"). Renvoie
    (chaîne de filtre, label simple de sortie).
    """
    out = f"wmv{wm_input}"
    return (
        f"[{wm_input}:v]format=rgba,scale=w=320:h=-1:force_original_aspect_ratio=decrease[wmw{wm_input}];"
        f"[{prev_label}][wmw{wm_input}]overlay={_WM_X}:{_WM_Y}:format=auto[{out}]",
        out,
    )


def _probe_duration(path: Path) -> float:
    """Durée d'un média en secondes (0.0 si non lisible)."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _has_audio(path: Path) -> bool:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True,
        )
        return bool(r.stdout.strip())
    except Exception:
        return False


def _concat_pieces(
    pieces: list[tuple[str, Path]],
    output: Path,
    max_duration: int = SHORTS_MAX_SECONDS,
) -> None:
    """Concatène (intro, main, outro) en bornant le total à max_duration.

    Chaque morceau est normalisé (1080×1920, 30 fps, yuv420p, AAC) pour que le
    concat ne plante pas sur des paramètres hétérogènes. Le main est raccourci
    si intro/outro dépassent la durée max. Les morceaux sans piste audio sont
    comblés par du silence.
    """
    main = next(p for kind, p in pieces if kind == "main")
    intro_d = _probe_duration(next((p for k, p in pieces if k == "intro"), None)) if any(k == "intro" for k, _ in pieces) else 0.0
    outro_d = _probe_duration(next((p for k, p in pieces if k == "outro"), None)) if any(k == "outro" for k, _ in pieces) else 0.0
    main_keep = max(2.0, max_duration - intro_d - outro_d)

    with tempfile.TemporaryDirectory(prefix="vp_concat_") as tmp:
        tmp = Path(tmp)
        norms: list[Path] = []
        for kind, path in pieces:
            norm = tmp / f"{kind}.mp4"
            dur = main_keep if kind == "main" else None
            _normalize_clip(path, norm, dur=dur)
            norms.append(norm)

        cmd = ["ffmpeg", "-y"]
        vlabels, alabels = [], []
        index = 0
        for norm in norms:
            cmd += ["-i", str(norm)]
            vlabels.append(f"[{index}:v:0]")
            if _has_audio(norm):
                alabels.append(f"[{index}:a:0]")
            else:
                d = _probe_duration(norm)
                cmd += ["-f", "lavfi", "-t", f"{d:.2f}",
                        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
                index += 1  # l'entrée silence prend aussi un index
                alabels.append(f"[{index}:a:0]")
            index += 1

        expr = "".join(v + a for v, a in zip(vlabels, alabels))
        expr += f"concat=n={len(norms)}:v=1:a=1[outv][outa]"
        cmd += [
            "-filter_complex", expr,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
            "-c:a", "aac", "-b:a", "128k",
            "-t", str(max_duration),
            "-movflags", "+faststart",
            str(output),
        ]
        _run(cmd)


def _normalize_clip(src: Path, dst: Path, dur: float | None = None) -> None:
    """Re-encode un clip en 1080×1920, 30 fps, yuv420p, éventuellement tronqué."""
    cmd = ["ffmpeg", "-y", "-i", str(src)]
    if dur is not None:
        cmd += ["-t", f"{dur:.2f}"]
    cmd += [
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,fps=30,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
    ]
    if _has_audio(src):
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-an"]
    cmd += [str(dst)]
    _run(cmd)


def _run(cmd: list[str]) -> None:
    try:
        r = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg a échoué : {e.stderr[-3000:]}") from e