from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path

from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
    vfx,
)
from PIL import Image, ImageDraw, ImageFont

from config import Settings
from script_generator import ScriptPackage


class VideoBuilder:
    def __init__(self, settings: Settings, logger):
        self.settings = settings
        self.logger = logger
        self.frame_size = (self.settings.render_width, self.settings.render_height)

    def build_video(self, script_package: ScriptPackage, audio_path: Path) -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = self.settings.output_dir / "video" / f"video_{timestamp}.mp4"
        render_dir = self.settings.temp_dir / f"render_{timestamp}"
        render_dir.mkdir(parents=True, exist_ok=True)

        sections = [("Hook", script_package.hook)] + [
            (f"Fact {idx}", fact) for idx, fact in enumerate(script_package.facts, start=1)
        ] + [("Conclusion", script_package.conclusion)]

        stock_files = self._discover_stock_footage()
        self.logger.info(
            "video_build_started",
            extra={"audio_path": str(audio_path), "stock_files": len(stock_files)},
        )

        clips = []
        audio_clip = AudioFileClip(str(audio_path))
        try:
            section_duration = max(1.0, audio_clip.duration / max(1, len(sections)))
            for idx, (header, body) in enumerate(sections):
                base_clip = self._make_base_clip(
                    index=idx,
                    duration=section_duration,
                    stock_files=stock_files,
                    render_dir=render_dir,
                )
                overlay_path = self._render_overlay_image(
                    index=idx,
                    header=header,
                    body=body,
                    render_dir=render_dir,
                )
                overlay_clip = ImageClip(str(overlay_path)).with_duration(section_duration)
                composed = CompositeVideoClip(
                    [base_clip, overlay_clip],
                    size=self.frame_size,
                ).with_duration(section_duration)
                clips.append(composed)

            video_clip = concatenate_videoclips(clips, method="compose")
            video_clip = video_clip.with_audio(audio_clip).with_duration(audio_clip.duration)
            video_clip.write_videofile(
                str(output_path),
                fps=self.settings.video_fps,
                codec="libx264",
                audio_codec="aac",
                threads=4,
                preset=self.settings.video_preset,
                temp_audiofile=str(render_dir / "temp-audio.m4a"),
                remove_temp=True,
                logger=None,
            )
        finally:
            audio_clip.close()
            for clip in clips:
                clip.close()

        self.logger.info("video_build_finished", extra={"video_path": str(output_path)})
        return output_path

    def _make_base_clip(
        self,
        index: int,
        duration: float,
        stock_files: list[Path],
        render_dir: Path,
    ):
        if stock_files:
            stock_file = stock_files[index % len(stock_files)]
            try:
                clip = VideoFileClip(str(stock_file)).without_audio().resized(new_size=self.frame_size)
                if clip.duration < duration:
                    clip = clip.with_effects([vfx.Loop(duration=duration)])
                else:
                    max_start = max(0.0, clip.duration - duration)
                    start = random.uniform(0.0, max_start) if max_start > 0.0 else 0.0
                    clip = clip.subclipped(start, start + duration)
                return clip.with_duration(duration)
            except Exception:
                self.logger.exception("stock_footage_failed", extra={"file": str(stock_file)})

        bg_path = self._render_background_image(index, render_dir)
        clip = ImageClip(str(bg_path)).with_duration(duration).with_position("center")
        return clip.with_effects([vfx.Resize(lambda t: 1.0 + 0.06 * (t / max(duration, 0.01)))])

    def _discover_stock_footage(self) -> list[Path]:
        if not self.settings.stock_footage_dir.exists():
            return []
        files = []
        for pattern in ("*.mp4", "*.mov", "*.mkv"):
            files.extend(self.settings.stock_footage_dir.glob(pattern))
        return sorted(files)

    def _render_background_image(self, index: int, render_dir: Path) -> Path:
        width, height = self.frame_size
        image = Image.new("RGB", (width, height), color=(20, 24, 36))
        draw = ImageDraw.Draw(image)
        palette = [
            ((8, 33, 61), (29, 86, 151)),
            ((31, 45, 62), (13, 148, 136)),
            ((43, 44, 87), (244, 114, 182)),
            ((38, 50, 56), (245, 158, 11)),
        ]
        start, end = palette[index % len(palette)]
        for y in range(height):
            ratio = y / max(height - 1, 1)
            color = tuple(int(start[i] + (end[i] - start[i]) * ratio) for i in range(3))
            draw.line([(0, y), (width, y)], fill=color, width=1)

        for _ in range(15):
            radius = random.randint(70, 260)
            x = random.randint(-150, width + 150)
            y = random.randint(-150, height + 150)
            alpha = random.randint(25, 75)
            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            ov_draw = ImageDraw.Draw(overlay)
            ov_draw.ellipse(
                [(x - radius, y - radius), (x + radius, y + radius)],
                fill=(255, 255, 255, alpha),
            )
            image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")

        output_path = render_dir / f"background_{index:02d}.png"
        image.save(output_path)
        return output_path

    def _render_overlay_image(self, index: int, header: str, body: str, render_dir: Path) -> Path:
        width, height = self.frame_size
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        panel = (120, 120, width - 120, height - 140)
        draw.rounded_rectangle(panel, radius=32, fill=(6, 9, 14, 175))

        title_font = self._load_font(72, bold=True)
        body_font = self._load_font(52, bold=False)
        draw.text((170, 170), header, fill=(255, 222, 89, 255), font=title_font)

        wrapped = self._wrap_text(body, body_font, max_width=width - 320, draw=draw)
        y = 280
        for line in wrapped[:8]:
            draw.text((170, y), line, fill=(245, 247, 250, 255), font=body_font)
            y += 66

        output_path = render_dir / f"overlay_{index:02d}.png"
        overlay.save(output_path)
        return output_path

    @staticmethod
    def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
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
        candidates = []
        if bold:
            candidates.extend(
                [
                    Path("C:/Windows/Fonts/arialbd.ttf"),
                    Path("C:/Windows/Fonts/segoeuib.ttf"),
                    Path("C:/Windows/Fonts/calibrib.ttf"),
                ]
            )
        else:
            candidates.extend(
                [
                    Path("C:/Windows/Fonts/arial.ttf"),
                    Path("C:/Windows/Fonts/segoeui.ttf"),
                    Path("C:/Windows/Fonts/calibri.ttf"),
                ]
            )
        for path in candidates:
            if path.exists():
                return ImageFont.truetype(str(path), size=size)
        return ImageFont.load_default()
