from __future__ import annotations

import os
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
        self.is_draft = self.settings.run_profile == "draft"
        self.overlay_text_enabled = bool(self.settings.video_overlay_text_enabled)
        self.frame_size = (self.settings.render_width, self.settings.render_height)
        self.margin = max(24, int(self.frame_size[0] * 0.05))
        self.subtitle_font_size = max(28, int(self.frame_size[1] * 0.043))
        self.encode_threads = min(8, max(2, os.cpu_count() or 4))

    def build_video(self, script_package: ScriptPackage, audio_path: Path) -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = self.settings.output_dir / "video" / f"video_{timestamp}.mp4"
        render_dir = self.settings.temp_dir / f"render_{timestamp}"
        render_dir.mkdir(parents=True, exist_ok=True)

        sections = [("Hook", script_package.hook)] + [
            (f"Fact {idx}", fact) for idx, fact in enumerate(script_package.facts, start=1)
        ] + [("Conclusion", script_package.conclusion)]

        topic_videos, global_videos = self._discover_stock_videos(script_package.topic)
        topic_images, global_images = self._discover_stock_images(script_package.topic)
        stock_videos = topic_videos + global_videos
        stock_images = topic_images + global_images
        self.logger.info(
            "video_build_started",
            extra={
                "audio_path": str(audio_path),
                "stock_videos_topic": len(topic_videos),
                "stock_images_topic": len(topic_images),
                "stock_videos_fallback": len(global_videos),
                "stock_images_fallback": len(global_images),
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
            section_durations = self._allocate_section_durations(
                total_duration=audio_clip.duration,
                section_texts=[f"{header}. {body}" for header, body in sections],
            )
            scenes = self._expand_scenes(sections=sections, durations=section_durations)
            total_sections = len(scenes)
            for idx, scene in enumerate(scenes, start=1):
                header = scene["header"]
                body = scene["body"]
                section_duration = float(scene["duration"])
                base_clip = self._make_base_clip(
                    index=idx - 1,
                    duration=section_duration,
                    scene_text=body,
                    stock_videos_topic=topic_videos,
                    stock_videos_fallback=global_videos,
                    stock_images_topic=topic_images,
                    stock_images_fallback=global_images,
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
                threads=self.encode_threads,
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
        if not self.overlay_text_enabled:
            return []

        cue_text = self._section_cue_text(header=header, body=body)
        if not cue_text:
            return []
        subtitle_path = self._render_subtitle_card(
            index=index,
            chunk_index=0,
            text=cue_text,
            render_dir=render_dir,
        )
        overlay_duration = min(max(1.2, duration * 0.3), 2.2)
        return [ImageClip(str(subtitle_path)).with_duration(overlay_duration)]

    def _make_base_clip(
        self,
        index: int,
        duration: float,
        scene_text: str,
        stock_videos_topic: list[Path],
        stock_videos_fallback: list[Path],
        stock_images_topic: list[Path],
        stock_images_fallback: list[Path],
        render_dir: Path,
    ):
        preferred_videos = stock_videos_topic or stock_videos_fallback
        preferred_images = stock_images_topic or stock_images_fallback

        if preferred_videos:
            stock_file = self._pick_related_file(preferred_videos, scene_text)
            try:
                clip = VideoFileClip(str(stock_file)).without_audio().resized(new_size=self.frame_size)
                if clip.duration < duration:
                    clip = clip.with_effects([vfx.Loop(duration=duration)])
                else:
                    max_start = max(0.0, clip.duration - duration)
                    start = random.uniform(0.0, max_start) if max_start > 0.0 else 0.0
                    clip = clip.subclipped(start, start + duration)
                if not self.is_draft:
                    clip = clip.with_duration(duration).with_effects(
                        [vfx.Resize(lambda t: 1.02 + 0.04 * (t / max(duration, 0.01)))]
                    )
                else:
                    clip = clip.with_duration(duration)
                return clip
            except Exception:
                self.logger.exception("stock_footage_failed", extra={"file": str(stock_file)})

        if self.is_draft and preferred_images:
            stock_image = self._pick_related_file(preferred_images, scene_text)
            try:
                return ImageClip(str(stock_image)).resized(new_size=self.frame_size).with_duration(duration).with_position("center")
            except Exception:
                self.logger.exception("stock_image_failed", extra={"file": str(stock_image)})

        if preferred_images:
            stock_image = self._pick_related_file(preferred_images, scene_text)
            try:
                clip = ImageClip(str(stock_image)).resized(new_size=self.frame_size).with_duration(duration)
                if self.is_draft:
                    return clip.with_position("center")
                start_scale = random.uniform(1.03, 1.08)
                end_scale = random.uniform(1.10, 1.16)
                return (
                    clip.with_effects([vfx.Resize(lambda t: start_scale + (end_scale - start_scale) * (t / max(duration, 0.01)))])
                    .with_position("center")
                )
            except Exception:
                self.logger.exception("stock_image_failed", extra={"file": str(stock_image)})

        bg_path = self._render_background_image(index, render_dir)
        clip = ImageClip(str(bg_path)).with_duration(duration).with_position("center")
        if self.is_draft:
            return clip
        return clip.with_effects([vfx.Resize(lambda t: 1.01 + 0.04 * (t / max(duration, 0.01)))])

    def _discover_stock_videos(self, topic: str) -> tuple[list[Path], list[Path]]:
        topic_dir = self._topic_dir(topic)
        return self._topic_and_global_lists(topic_dir, ("*.mp4", "*.mov", "*.mkv"))

    def _discover_stock_images(self, topic: str) -> tuple[list[Path], list[Path]]:
        topic_dir = self._topic_dir(topic)
        return self._topic_and_global_lists(topic_dir, ("*.jpg", "*.jpeg", "*.png", "*.webp"))

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

    def _render_subtitle_card(self, index: int, chunk_index: int, text: str, render_dir: Path) -> Path:
        width, height = self.frame_size
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        panel_height = int(height * 0.14)
        panel_top = height - panel_height - self.margin
        draw.rounded_rectangle(
            (self.margin * 2, panel_top, width - (self.margin * 2), panel_top + panel_height),
            radius=int(panel_height * 0.16),
            fill=(5, 7, 12, 178),
        )

        font = self._load_font(self.subtitle_font_size, bold=True)
        wrapped = self._wrap_text(text, font=font, max_width=width - (self.margin * 4) - 80, draw=draw)
        line_gap = int(self.subtitle_font_size * 1.25)
        total_h = max(line_gap, len(wrapped) * line_gap)
        y = panel_top + int((panel_height - total_h) / 2)
        for line in wrapped[:1]:
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

    def _topic_and_global_lists(self, topic_dir: Path, patterns: tuple[str, ...]) -> tuple[list[Path], list[Path]]:
        files_topic: list[Path] = []
        files_global: list[Path] = []
        if topic_dir.exists():
            for pattern in patterns:
                files_topic.extend(topic_dir.glob(pattern))
        if self.settings.stock_footage_dir.exists():
            for pattern in patterns:
                files_global.extend(self.settings.stock_footage_dir.glob(pattern))

        seen = {path.resolve() for path in files_topic if path.exists()}
        fallback = sorted(path for path in files_global if path.exists() and path.resolve() not in seen)
        return sorted(files_topic), fallback

    def _topic_dir(self, topic: str) -> Path:
        slug = self._topic_slug(topic)
        return self.settings.stock_footage_dir / "topics" / slug

    @staticmethod
    def _topic_slug(value: str, max_len: int = 64) -> str:
        slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")
        while "__" in slug:
            slug = slug.replace("__", "_")
        return slug[:max_len] or "topic"

    @staticmethod
    def _section_cue_text(header: str, body: str) -> str:
        text = body.strip()
        if not text:
            return ""
        first_sentence = text.split(".")[0].strip()
        words = first_sentence.split()
        short = " ".join(words[:8]) if words else first_sentence
        # Remove structure words if present.
        lower_header = header.strip().lower()
        if lower_header.startswith("fact") or lower_header in {"hook", "conclusion"}:
            return short
        return f"{short}"

    def _pick_related_file(self, files: list[Path], scene_text: str) -> Path:
        if not files:
            raise ValueError("No files available to select from.")
        scene_tokens = self._tokenize(scene_text)
        if not scene_tokens:
            return random.choice(files)

        scored = []
        for file in files:
            file_tokens = self._tokenize(file.stem.replace("__", " "))
            overlap = len(scene_tokens.intersection(file_tokens))
            score = overlap + random.random() * 0.01
            scored.append((score, file))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        tokens = {token for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if len(token) > 2}
        return tokens

    @staticmethod
    def _expand_scenes(sections: list[tuple[str, str]], durations: list[float]) -> list[dict]:
        scenes: list[dict] = []
        max_scene_seconds = 12.0
        for (header, body), section_duration in zip(sections, durations):
            chunk_count = max(1, int((section_duration + max_scene_seconds - 0.01) // max_scene_seconds))
            chunks = VideoBuilder._split_text_for_chunks(body, chunk_count)
            chunk_duration = section_duration / max(1, len(chunks))
            for idx, chunk in enumerate(chunks):
                scene_header = header if idx == 0 else f"{header} (cont)"
                scenes.append(
                    {
                        "header": scene_header,
                        "body": chunk,
                        "duration": chunk_duration,
                    }
                )

        total_planned = sum(item["duration"] for item in scenes)
        total_target = sum(durations)
        if scenes:
            scenes[-1]["duration"] += total_target - total_planned
        return scenes

    @staticmethod
    def _split_text_for_chunks(text: str, chunks: int) -> list[str]:
        if chunks <= 1:
            return [text.strip()]
        words = text.split()
        if not words:
            return [""]
        bucket_size = max(1, len(words) // chunks)
        parts = []
        start = 0
        for _ in range(chunks - 1):
            end = min(len(words), start + bucket_size)
            parts.append(" ".join(words[start:end]).strip())
            start = end
        parts.append(" ".join(words[start:]).strip())
        return [part for part in parts if part]

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
