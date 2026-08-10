from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import ImageDraw, ImageFont


@dataclass
class FittedText:
    lines: list[str]
    font: ImageFont.FreeTypeFont
    font_size: int
    line_height: int


def _wrap_at_word_boundaries(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        width = draw.textbbox((0, 0), candidate, font=font)[2]
        if width <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fit_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: Path,
    box_width: int,
    box_height: int,
    max_font_size: int = 64,
    min_font_size: int = 28,
) -> FittedText:
    """Trouve la plus grande taille de police (entre min_font_size et
    max_font_size) telle que `text`, une fois retourné à la ligne aux
    frontières de mots, tienne entièrement dans box_width x box_height.

    Ne coupe jamais un mot au milieu : si même min_font_size déborde encore
    en hauteur, les dernières lignes en trop sont retirées et la dernière
    ligne gardée se termine par "…" (jamais un mot tronqué).
    """
    for size in range(max_font_size, min_font_size - 1, -2):
        font = ImageFont.truetype(str(font_path), size)
        lines = _wrap_at_word_boundaries(draw, text, font, box_width)
        line_height = int(size * 1.25)
        total_height = line_height * len(lines)
        widest_line = max((draw.textbbox((0, 0), line, font=font)[2] for line in lines), default=0)
        if total_height <= box_height and widest_line <= box_width:
            return FittedText(lines=lines, font=font, font_size=size, line_height=line_height)

    # Dernier recours : taille minimale, on tronque proprement au mot le plus
    # loin qui rentre encore, jamais en plein milieu d'un mot.
    font = ImageFont.truetype(str(font_path), min_font_size)
    line_height = int(min_font_size * 1.25)
    max_lines = max(1, box_height // line_height)
    lines = _wrap_at_word_boundaries(draw, text, font, box_width)[:max_lines]
    if lines and len(lines) == max_lines:
        lines[-1] = lines[-1].rstrip() + "…"
    return FittedText(lines=lines, font=font, font_size=min_font_size, line_height=line_height)
