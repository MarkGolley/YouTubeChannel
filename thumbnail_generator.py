from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import Settings


class ThumbnailGenerator:
    SIZE = (1280, 720)

    def __init__(self, settings: Settings, logger):
        self.settings = settings
        self.logger = logger

    def generate_thumbnail(self, title: str) -> Path:
        output_path = self.settings.output_dir / "thumbnail" / f"thumb_{datetime.utcnow():%Y%m%d_%H%M%S}.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        image = Image.new("RGB", self.SIZE, color=(8, 14, 24))
        draw = ImageDraw.Draw(image)
        self._draw_background(draw)
        self._draw_highlight_shapes(image)

        badge_font = self._load_font(40, bold=True)
        title_font = self._load_font(102, bold=True)
        subtitle_font = self._load_font(44, bold=True)

        hook = self._make_hook_text(title)
        wrapped_hook = self._wrap_text(hook, draw=draw, font=title_font, max_width=1040)

        draw.rounded_rectangle((78, 72, 520, 150), radius=18, fill=(248, 196, 52))
        draw.text((104, 89), "CURIOUS FACTS", fill=(8, 14, 24), font=badge_font)

        y = 200
        for line in wrapped_hook[:3]:
            draw.text((88, y), line, fill=(247, 249, 252), font=title_font, stroke_width=4, stroke_fill=(0, 0, 0))
            y += 120

        draw.text((90, 610), "SCIENCE + WORLD MYSTERIES", fill=(144, 224, 239), font=subtitle_font)

        image.save(output_path)
        self.logger.info("thumbnail_generated", extra={"thumbnail_path": str(output_path)})
        return output_path

    def _draw_background(self, draw: ImageDraw.ImageDraw) -> None:
        width, height = self.SIZE
        start = (5, 18, 32)
        end = (17, 65, 98)
        for y in range(height):
            ratio = y / max(height - 1, 1)
            color = tuple(int(start[i] + (end[i] - start[i]) * ratio) for i in range(3))
            draw.line([(0, y), (width, y)], fill=color, width=1)

        draw.rectangle((0, 0, int(width * 0.42), height), fill=(0, 0, 0, 58))

    def _draw_highlight_shapes(self, image: Image.Image) -> None:
        width, height = self.SIZE
        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        draw.ellipse((820, -120, 1460, 520), fill=(255, 201, 60, 65))
        draw.ellipse((760, 330, 1320, 900), fill=(56, 189, 248, 70))
        draw.rounded_rectangle((890, 120, 1220, 280), radius=24, fill=(15, 23, 42, 130))
        merged = Image.alpha_composite(image.convert("RGBA"), layer)
        image.paste(merged.convert("RGB"))

    @staticmethod
    def _make_hook_text(title: str) -> str:
        words = [word for word in title.replace("?", "").replace(":", "").split() if word.strip()]
        if not words:
            return "WILD FACTS"
        if len(words) <= 7:
            return " ".join(words).upper()
        return " ".join(words[:7]).upper()

    @staticmethod
    def _wrap_text(text: str, draw: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            current = word
        if current:
            lines.append(current)
        return lines

    @staticmethod
    def _load_font(size: int, bold: bool) -> ImageFont.FreeTypeFont:
        if bold:
            candidates = [
                Path("C:/Windows/Fonts/segoeuib.ttf"),
                Path("C:/Windows/Fonts/arialbd.ttf"),
                Path("C:/Windows/Fonts/calibrib.ttf"),
            ]
        else:
            candidates = [
                Path("C:/Windows/Fonts/segoeui.ttf"),
                Path("C:/Windows/Fonts/arial.ttf"),
                Path("C:/Windows/Fonts/calibri.ttf"),
            ]
        for path in candidates:
            if path.exists():
                return ImageFont.truetype(str(path), size=size)
        return ImageFont.load_default()
