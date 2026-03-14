from __future__ import annotations

import random
import threading
import time
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
        self.margin = max(24, int(self.frame_size[0] * 0.05))
        self.title_font_size = max(34, int(self.frame_size[1] * 0.055))
        self.subtitle_font_size = max(28, int(self.frame_size[1] * 0.043))
        self.tag_font_size = max(24, int(self.frame_size[1] * 0.03))

    def build_video(self, script_package: ScriptPackage, audio_path: Path) -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = self.settings.output_dir / "video" / f"video_{timestamp}.mp4"
        render_dir = self.settings.temp_dir / f"render_{timestamp}"
        render_dir.mkdir(parents=True, exist_ok=True)

        sections = [("Hook", script_package.hook)] + [
            (f"Fact {idx}", fact) for idx, fact in enumerate(script_package.facts, start=1)
        ] + [("Conclusion", script_package.conclusion)]

        stock_videos = self._discover_stock_videos()
        stock_images = self._discover_stock_images()
        self.logger.info(
            "video_build_started",
            extra={
                "audio_path": str(audio_path),
                "stock_videos": len(stock_videos),
                "stock_images": len(stock_images),
            },
        )
        if not stock_videos and stock_images:
            self.logger.warning(
                "stock_videos_missing",
                extra={"message_hint": "Using still images with motion. Add mp4 clips for better quality."},
            )
        if not stock_videos and not stock_images:
            self.logger.warning(
                "stock_assets_missing",
                extra={"message_hint": "No stock media found. Using generated backgrounds only."},
            )

        clips = []
        audio_clip = AudioFileClip(str(audio_path))
        video_clip = None
        heartbeat_stop = None
        try:
            durations = self._allocate_section_durations(
                total_duration=audio_clip.duration,
                section_texts=[f"{header}. {body}" for header, body in sections],
            )
            total_sections = len(sections)
            for idx, ((header, body), section_duration) in enumerate(zip(sections, durations), start=1):
                base_clip = self._make_base_clip(
                    index=idx - 1,
                    duration=section_duration,
                    stock_videos=stock_videos,
                    stock_images=stock_images,
                    render_dir=render_dir,
                )

                overlay_clips = self._build_section_overlays(
                    index=idx - 1,
                    header=header,
                    body=body,
                    duration=section_duration,
                    render_dir=render_dir,
                )
                composed = CompositeVideoClip(
                    [base_clip] + overlay_clips,
                    size=self.frame_size,
                ).with_duration(section_duration)
                clips.append(composed)
                self.logger.info(
                    "video_scene_ready",
                    extra={
                        "scene_index": idx,
                        "scene_total": total_sections,
                        "scene_label": header,
                        "progress_pct": round((idx / total_sections) * 100, 1),
                    },
                )

            video_clip = concatenate_videoclips(clips, method="compose")
            video_clip = video_clip.with_audio(audio_clip).with_duration(audio_clip.duration)
            heartbeat_stop = self._start_heartbeat(
                step_name="video_encode",
                interval_seconds=12,
                extra={"target_file": str(output_path)},
            )
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
            if heartbeat_stop is not None:
                heartbeat_stop.set()
            if video_clip is not None:
                video_clip.close()
            audio_clip.close()
            for clip in clips:
                clip.close()

        self.logger.info("video_build_finished", extra={"video_path": str(output_path)})
        return output_path

    def _build_section_overlays(
        self,
        index: int,
        header: str,
        body: str,
        duration: float,
        render_dir: Path,
    ) -> list:
        overlay_clips = []

        label_path = self._render_header_label(index=index, header=header, render_dir=render_dir)
        overlay_clips.append(ImageClip(str(label_path)).with_duration(duration))

        chunks = self._split_caption_chunks(body, target_words=8)
        if not chunks:
            chunks = [body]
        chunk_duration = max(0.8, duration / len(chunks))
        for chunk_idx, chunk in enumerate(chunks):
            subtitle_path = self._render_subtitle_card(
                index=index,
                chunk_index=chunk_idx,
                text=chunk,
                render_dir=render_dir,
            )
            clip = (
                ImageClip(str(subtitle_path))
                .with_start(chunk_idx * chunk_duration)
                .with_duration(chunk_duration + 0.05)
            )
            overlay_clips.append(clip)

        return overlay_clips

    def _make_base_clip(
        self,
        index: int,
        duration: float,
        stock_videos: list[Path],
        stock_images: list[Path],
        render_dir: Path,
    ):
        if stock_videos:
            stock_file = random.choice(stock_videos)
            try:
                clip = VideoFileClip(str(stock_file)).without_audio().resized(new_size=self.frame_size)
                if clip.duration < duration:
                    clip = clip.with_effects([vfx.Loop(duration=duration)])
                else:
                    max_start = max(0.0, clip.duration - duration)
                    start = random.uniform(0.0, max_start) if max_start > 0.0 else 0.0
                    clip = clip.subclipped(start, start + duration)
                clip = clip.with_duration(duration).with_effects(
                    [vfx.Resize(lambda t: 1.02 + 0.04 * (t / max(duration, 0.01)))]
                )
                return clip
            except Exception:
                self.logger.exception("stock_footage_failed", extra={"file": str(stock_file)})

        if stock_images:
            stock_image = random.choice(stock_images)
            try:
                clip = ImageClip(str(stock_image)).resized(new_size=self.frame_size).with_duration(duration)
                start_scale = random.uniform(1.03, 1.08)
                end_scale = random.uniform(1.10, 1.16)
                return clip.with_effects(
                    [vfx.Resize(lambda t: start_scale + (end_scale - start_scale) * (t / max(duration, 0.01)))]
                ).with_position("center")
            except Exception:
                self.logger.exception("stock_image_failed", extra={"file": str(stock_image)})

        bg_path = self._render_background_image(index, render_dir)
        clip = ImageClip(str(bg_path)).with_duration(duration).with_position("center")
        return clip.with_effects([vfx.Resize(lambda t: 1.01 + 0.04 * (t / max(duration, 0.01)))])

    def _discover_stock_videos(self) -> list[Path]:
        if not self.settings.stock_footage_dir.exists():
            return []
        files = []
        for pattern in ("*.mp4", "*.mov", "*.mkv"):
            files.extend(self.settings.stock_footage_dir.glob(pattern))
        return sorted(files)

    def _discover_stock_images(self) -> list[Path]:
        if not self.settings.stock_footage_dir.exists():
            return []
        files = []
        for pattern in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
            files.extend(self.settings.stock_footage_dir.glob(pattern))
        return sorted(files)

    def _render_background_image(self, index: int, render_dir: Path) -> Path:
        width, height = self.frame_size
        image = Image.new("RGB", (width, height), color=(10, 16, 25))
        draw = ImageDraw.Draw(image)
        palette = [
            ((4, 19, 32), (11, 52, 90)),
            ((7, 25, 41), (24, 94, 112)),
            ((21, 18, 34), (80, 47, 112)),
            ((22, 24, 30), (82, 97, 116)),
        ]
        start, end = palette[index % len(palette)]
        for y in range(height):
            ratio = y / max(height - 1, 1)
            color = tuple(int(start[i] + (end[i] - start[i]) * ratio) for i in range(3))
            draw.line([(0, y), (width, y)], fill=color, width=1)

        for _ in range(30):
            x = random.randint(0, width)
            y = random.randint(0, height)
            w = random.randint(80, 360)
            h = random.randint(80, 260)
            alpha = random.randint(12, 35)
            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            o_draw = ImageDraw.Draw(overlay)
            o_draw.rounded_rectangle([(x, y), (x + w, y + h)], radius=26, fill=(255, 255, 255, alpha))
            image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")

        output_path = render_dir / f"background_{index:02d}.png"
        image.save(output_path)
        return output_path

    def _render_header_label(self, index: int, header: str, render_dir: Path) -> Path:
        width, height = self.frame_size
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        font = self._load_font(self.tag_font_size, bold=True)
        label_w = int(width * 0.3)
        label_h = int(height * 0.09)
        left = self.margin
        top = self.margin
        draw.rounded_rectangle(
            (left, top, left + label_w, top + label_h),
            radius=int(label_h * 0.25),
            fill=(0, 0, 0, 150),
        )
        draw.text(
            (left + int(label_w * 0.08), top + int(label_h * 0.2)),
            header.upper(),
            font=font,
            fill=(255, 219, 112, 255),
        )

        output_path = render_dir / f"header_{index:02d}.png"
        image.save(output_path)
        return output_path

    def _render_subtitle_card(self, index: int, chunk_index: int, text: str, render_dir: Path) -> Path:
        width, height = self.frame_size
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        panel_height = int(height * 0.24)
        panel_top = height - panel_height - self.margin
        draw.rounded_rectangle(
            (self.margin, panel_top, width - self.margin, panel_top + panel_height),
            radius=int(panel_height * 0.16),
            fill=(5, 7, 12, 178),
        )

        font = self._load_font(self.subtitle_font_size, bold=True)
        wrapped = self._wrap_text(text, font=font, max_width=width - (self.margin * 2) - 80, draw=draw)
        line_gap = int(self.subtitle_font_size * 1.25)
        total_h = max(line_gap, len(wrapped) * line_gap)
        y = panel_top + int((panel_height - total_h) / 2)
        for line in wrapped[:3]:
            line_width = draw.textlength(line, font=font)
            x = int((width - line_width) / 2)
            draw.text((x, y), line, fill=(245, 247, 250, 255), font=font)
            y += line_gap

        output_path = render_dir / f"subtitle_{index:02d}_{chunk_index:02d}.png"
        image.save(output_path)
        return output_path

    def _start_heartbeat(self, step_name: str, interval_seconds: int, extra: dict | None = None):
        stop_event = threading.Event()
        payload = extra or {}
        start_time = time.time()

        def _loop() -> None:
            while not stop_event.wait(interval_seconds):
                elapsed = round(time.time() - start_time, 1)
                self.logger.info(
                    "progress_heartbeat",
                    extra={"step": step_name, "elapsed_seconds": elapsed, **payload},
                )

        threading.Thread(target=_loop, daemon=True).start()
        return stop_event

    @staticmethod
    def _allocate_section_durations(total_duration: float, section_texts: list[str]) -> list[float]:
        if not section_texts:
            return []
        weights = [max(4, len(text.split())) for text in section_texts]
        total_weight = sum(weights)
        durations = [(total_duration * weight / total_weight) for weight in weights]
        adjustment = total_duration - sum(durations)
        durations[-1] += adjustment
        return durations

    @staticmethod
    def _split_caption_chunks(text: str, target_words: int = 8) -> list[str]:
        words = text.split()
        if not words:
            return []
        chunks = []
        current = []
        for word in words:
            current.append(word)
            if len(current) >= target_words:
                chunks.append(" ".join(current))
                current = []
        if current:
            chunks.append(" ".join(current))
        return chunks

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
                    Path("C:/Windows/Fonts/segoeuib.ttf"),
                    Path("C:/Windows/Fonts/arialbd.ttf"),
                    Path("C:/Windows/Fonts/calibrib.ttf"),
                ]
            )
        else:
            candidates.extend(
                [
                    Path("C:/Windows/Fonts/segoeui.ttf"),
                    Path("C:/Windows/Fonts/arial.ttf"),
                    Path("C:/Windows/Fonts/calibri.ttf"),
                ]
            )
        for path in candidates:
            if path.exists():
                return ImageFont.truetype(str(path), size=size)
        return ImageFont.load_default()
