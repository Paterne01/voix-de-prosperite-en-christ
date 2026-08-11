from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import FORMAT_KEYS, absolute_path
from .secrets import get_secret
from .text_fit import fit_text_block

# Canevas vertical 9:16 (1080x1920) appliqué à TOUS les modes (local, cloud,
# manuel). _brand() force .resize((W, H)) juste avant l'enregistrement, donc
# aucune image ne peut sortir dans un autre ratio.
W, H = 1080, 1920

_IMAGE_BACKGROUND_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

# Pastille fixe du Format A (les détails sont publiés en commentaire).
COMMENT_PILL = "DÉTAILS EN COMMENTAIRE"

# Format B : les fonds sont des photos de prédicateurs, la zone haute (visage)
# doit rester dégagée. Le bloc texte est centré verticalement dans la bande
# médiane du post, sous le visage.
MID_BAND_TOP = 820
MID_BAND_BOTTOM = 1660
BLOCK_SPACING = 36


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/georgiab.ttf" if bold else "C:/Windows/Fonts/georgia.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _font_path(bold: bool = False) -> Path:
    candidates = [
        "C:/Windows/Fonts/georgiab.ttf" if bold else "C:/Windows/Fonts/georgia.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return Path(candidate)
    return Path("C:/Windows/Fonts/arial.ttf")


class ImageService:
    def __init__(self, config: dict):
        self.config = config

    # ── entrée publique ───────────────────────────────────────────────

    def create(
        self, content, *, mode: str | None = None, background: str | None = None,
        format: str = "video",
    ) -> Path | None:
        selected = mode or self.config["image_mode"]
        if selected == "manual":
            return None
        if selected == "cloud":
            image = self._cloud(content)
            if image:
                return self._save(self._brand(image, content, format))
            return None
        return self._local(content, background=background, format=format)

    def overlay(self, content, *, format: str = "video") -> Path:
        """PNG transparent 1080x1920 (titre, accroche, pastille CTA, logo).

        Sert de calque à superposer sur un fond VIDÉO dans ffmpeg : le fond
        n'est pas gravé dans l'image, seul le texte l'est.
        """
        image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        self._draw_branding(image, content, format)
        return self._save_png(image)

    # ── production de l'image brute ───────────────────────────────────

    def _cloud(self, content) -> Image.Image | None:
        cloud = self.config.get("cloud_image", {})
        token = get_secret("huggingface_token")
        if not cloud.get("enabled") or not token or cloud.get("provider") != "huggingface":
            return None
        try:
            from huggingface_hub import InferenceClient
            return InferenceClient(api_key=token).text_to_image(content.image_prompt, model=cloud["model"])
        except Exception:
            return None

    @staticmethod
    def _cover(image: Image.Image) -> Image.Image:
        """Met l'image en couverture 1080x1920 (crop centré), sans distorsion."""
        ratio = max(W / image.width, H / image.height)
        image = image.resize(
            (round(image.width * ratio), round(image.height * ratio)), Image.LANCZOS
        )
        left = (image.width - W) // 2
        top = (image.height - H) // 2
        return image.crop((left, top, left + W, top + H))

    def _local(self, content, *, background: str | None = None, format: str = "video") -> Path:
        image = self._fallback_background(background)
        return self._save(self._brand(image, content, format))

    def _fallback_background(self, background: str | None) -> Image.Image:
        """Fond d'image utilisable : ignore les vidéos (traitées dans video.py)."""
        if (
            background
            and Path(background).exists()
            and Path(background).suffix.lower() in _IMAGE_BACKGROUND_SUFFIXES
        ):
            return self._cover(Image.open(background).convert("RGB"))
        return self._geometric()

    def _geometric(self) -> Image.Image:
        """Fond géométrique de secours : identité premium cohérente, sans
        ressource externe, utilisé uniquement quand aucun fond n'est fourni."""
        image = Image.new("RGB", (W, H), "#071a36")
        draw = ImageDraw.Draw(image)
        draw.ellipse((-380, -280, 1000, 1500), fill="#12396b")
        draw.ellipse((320, 650, 1600, 2050), fill="#0a274c")
        draw.polygon(
            [(90, 1500), (420, 1020), (700, 1500), (980, 900), (1080, 1280), (1080, 1920), (90, 1920)],
            fill="#0b2440",
        )
        return image

    # ── habillage commun (tous modes) ────────────────────────────────

    def _brand(self, image: Image.Image, content, format: str = "video") -> Image.Image:
        image = image.convert("RGB").resize((W, H))
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.rectangle((0, 0, W, H), fill=(0, 0, 0, 90))
        image = Image.alpha_composite(image.convert("RGBA"), overlay)
        self._draw_branding(image, content, format)
        return image.convert("RGB")

    def _draw_branding(self, image: Image.Image, content, format: str = "video") -> None:
        """Dessine titre + accroche + pastille CTA + logo sur `image` (RGBA).

        Partagé par _brand (fond déjà composé) et overlay (fond transparent).
        Format B : texte descendu et centré au milieu du post (zone haute libre
        pour le visage du prédicateur) ; Format A : comportement historique.
        """
        draw = ImageDraw.Draw(image)
        if FORMAT_KEYS.get(format, "format_a") == "format_b":
            self._draw_branding_centered(draw, content)
        else:
            self._draw_branding_top(draw, content)
        self._draw_logo(image)

    def _draw_branding_top(self, draw: ImageDraw.ImageDraw, content) -> None:
        """Format A : habillage historique (titre en haut, à 300 px)."""
        cursor_y = self._draw_fitted(
            draw, content.title, x=90, y=300, box_width=900, box_height=540,
            bold=True, max_font=92, min_font=40, fill="#f7ead0",
        )

        # Accroche — suit la fin réelle du titre.
        if content.hook:
            cursor_y = self._draw_fitted(
                draw, content.hook, x=90, y=cursor_y + 40, box_width=900, box_height=400,
                bold=False, max_font=56, min_font=28, fill="#cfd9ea",
            )

        # Pastille — Format A : « Détails en commentaire » (le CTA du Format B
        # est géré dans _draw_branding_centered).
        pill_text = COMMENT_PILL
        if pill_text:
            self._draw_pill(draw, pill_text, y=cursor_y + 40)

    def _draw_branding_centered(self, draw: ImageDraw.ImageDraw, content) -> None:
        """Format B : bloc texte (titre, accroche, pastille CTA) descendu et
        centré verticalement dans la bande médiane du post.

        Le fond étant désormais une photo de prédicateur, la partie supérieure
        reste entièrement libre ; le bloc est d'abord mesuré, puis centré.
        """
        blocks: list[tuple[FittedText, str | None, bool]] = []
        title_fit = fit_text_block(
            draw, content.title, _font_path(True),
            box_width=900, box_height=540, max_font_size=92, min_font_size=40,
        )
        blocks.append((title_fit, "#f7ead0", False))
        if content.hook:
            hook_fit = fit_text_block(
                draw, content.hook, _font_path(False),
                box_width=900, box_height=400, max_font_size=56, min_font_size=28,
            )
            blocks.append((hook_fit, "#cfd9ea", False))
        pill_text = getattr(content, "cta", "") or content.closure
        if pill_text:
            pill_fit = fit_text_block(
                draw, pill_text, _font_path(True),
                box_width=820, box_height=130, max_font_size=34, min_font_size=20,
            )
            blocks.append((pill_fit, None, True))

        heights = [
            self._pill_height(fit) if is_pill else fit.line_height * len(fit.lines)
            for fit, _, is_pill in blocks
        ]
        total = sum(heights) + BLOCK_SPACING * (len(blocks) - 1)
        cursor_y = max(MID_BAND_TOP, (MID_BAND_TOP + MID_BAND_BOTTOM) // 2 - total // 2)

        for fit, fill, is_pill in blocks:
            if is_pill:
                cursor_y = self._draw_pill_from(draw, fit, y=cursor_y)
            else:
                cursor_y = self._draw_lines(draw, fit, x=90, y=cursor_y, fill=fill)
                cursor_y += BLOCK_SPACING

    def _draw_pill(self, draw: ImageDraw.ImageDraw, text: str, *, y: int) -> int:
        """Dessine la pastille (CTA / commentaire) et renvoie son bas."""
        fitted = fit_text_block(
            draw, text, _font_path(True),
            box_width=820, box_height=130, max_font_size=34, min_font_size=20,
        )
        return self._draw_pill_from(draw, fitted, y=y)

    @staticmethod
    def _pill_height(fitted: FittedText) -> int:
        return max(70, fitted.line_height * len(fitted.lines) + 18)

    @staticmethod
    def _draw_pill_from(draw: ImageDraw.ImageDraw, fitted: FittedText, *, y: int) -> int:
        """Dessine une pastille déjà ajustée et renvoie son bas."""
        pill_h = ImageService._pill_height(fitted)
        draw.rounded_rectangle((90, y, 990, y + pill_h), radius=18, fill="#b68a37")
        ty = y + (pill_h - fitted.line_height * len(fitted.lines)) // 2
        for line in fitted.lines:
            draw.text((120, ty), line, font=fitted.font, fill="#071a36")
            ty += fitted.line_height
        return y + pill_h

    def _draw_logo(self, image: Image.Image) -> None:
        """Logo réel en bas à gauche (80 px de haut, marges 40 px), alpha RGBA.

        Plus AUCUNE écriture du nom en texte : si le logo est absent, on ne
        dessine rien plutôt que de réintroduire le texte.
        """
        logo_path = absolute_path(self.config.get("logo_path", "")) if self.config.get("logo_path") else None
        if not logo_path or not logo_path.exists():
            return
        try:
            logo = Image.open(logo_path).convert("RGBA")
        except OSError:
            return
        ratio = 80 / logo.height
        logo = logo.resize((max(1, round(logo.width * ratio)), 80), Image.LANCZOS)
        base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        base.paste(logo, (40, H - 80 - 40), logo)
        image.alpha_composite(base)

    # ── dessin d'un bloc de texte ajusté ─────────────────────────────

    @staticmethod
    def _draw_fitted(
        draw, text: str, *, x: int, y: int, box_width: int, box_height: int,
        bold: bool, max_font: int, min_font: int, fill,
    ) -> int:
        """Dessine le bloc ajusté et retourne le Y situé juste après la dernière
        ligne, pour que les éléments suivants collent au texte réel."""
        fitted = fit_text_block(
            draw, text, _font_path(bold),
            box_width=box_width, box_height=box_height,
            max_font_size=max_font, min_font_size=min_font,
        )
        cursor_y = y
        for line in fitted.lines:
            draw.text((x, cursor_y), line, font=fitted.font, fill=fill)
            cursor_y += fitted.line_height
        return cursor_y

    # ── sauvegarde ───────────────────────────────────────────────────

    def _save(self, image: Image.Image) -> Path:
        target = absolute_path(self.config["paths"]["images"]) / f"post_{datetime.now():%Y%m%d_%H%M%S}.jpg"
        image.save(target, quality=94, optimize=True)
        return target

    def _save_png(self, image: Image.Image) -> Path:
        target = absolute_path(self.config["paths"]["images"]) / f"overlay_{datetime.now():%Y%m%d_%H%M%S}.png"
        image.save(target, optimize=True)
        return target
