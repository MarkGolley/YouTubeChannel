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

        image = Image.new("RGB", self.SIZE, color=(12, 24, 42))
        draw = ImageDraw.Draw(image)
        self._draw_gradient(draw)
        self._draw_shapes(image)

        headline_font = self._load_font(88, bold=True)
        accent_font = self._load_font(40, bold=True)
        wrapped_title = self._wrap_text(
            title.upper(),
            draw=draw,
            font=headline_font,
            max_width=1100,
        )

        text_y = 180
        for line in wrapped_title[:4]:
            draw.text((90, text_y), line, fill=(255, 246, 209), font=headline_font, stroke_width=3, stroke_fill=(0, 0, 0))
            text_y += 110

        draw.rounded_rectangle((90, 90, 560, 156), radius=20, fill=(250, 204, 21))
        draw.text((112, 103), "SCIENCE + WORLD FACTS", fill=(13, 25, 42), font=accent_font)

        image.save(output_path)
        self.logger.info("thumbnail_generated", extra={"thumbnail_path": str(output_path)})
        return output_path

    def _draw_gradient(self, draw: ImageDraw.ImageDraw) -> None:
        width, height = self.SIZE
        start = (6, 24, 56)
        end = (0, 86, 117)
        for y in range(height):
            ratio = y / max(height - 1, 1)
            color = tuple(int(start[i] + (end[i] - start[i]) * ratio) for i in range(3))
            draw.line([(0, y), (width, y)], fill=color, width=1)

    def _draw_shapes(self, image: Image.Image) -> None:
        width, height = self.SIZE
        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        draw.ellipse((780, -100, 1380, 500), fill=(250, 204, 21, 55))
        draw.ellipse((-180, 350, 380, 900), fill=(244, 114, 182, 45))
        draw.rounded_rectangle((840, 500, 1220, 690), radius=28, fill=(2, 132, 199, 120))
        merged = Image.alpha_composite(image.convert("RGBA"), layer)
        image.paste(merged.convert("RGB"))

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
                Path("C:/Windows/Fonts/arialbd.ttf"),
                Path("C:/Windows/Fonts/segoeuib.ttf"),
                Path("C:/Windows/Fonts/calibrib.ttf"),
            ]
        else:
            candidates = [
                Path("C:/Windows/Fonts/arial.ttf"),
                Path("C:/Windows/Fonts/segoeui.ttf"),
                Path("C:/Windows/Fonts/calibri.ttf"),
            ]
        for path in candidates:
            if path.exists():
                return ImageFont.truetype(str(path), size=size)
        return ImageFont.load_default()
