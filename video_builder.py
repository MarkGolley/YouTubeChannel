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
        self.scene_change_seconds = 6.0 if self.is_draft else 8.0
        self.frame_size = (self.settings.render_width, self.settings.render_height)
        self.margin = max(24, int(self.frame_size[0] * 0.05))
        self.subtitle_font_size = max(28, int(self.frame_size[1] * 0.043))
        self.encode_threads = min(8, max(2, os.cpu_count() or 4))

    def build_video(self, script_package: ScriptPackage, audio_path: Path) -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = self.settings.output_dir / "video" / f"video_{timestamp}.mp4"
        render_dir = self.settings.temp_dir / f"render_{timestamp}"
        render_dir.mkdir(parents=True, exist_ok=True)

        sections = self._compose_sections(script_package)

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
        used_video_files: set[Path] = set()
        used_image_files: set[Path] = set()
        try:
            section_durations = self._allocate_section_durations(
                total_duration=audio_clip.duration,
                section_texts=[f"{header}. {body}" for header, body in sections],
            )
            scenes = self._expand_scenes(
                sections=sections,
                durations=section_durations,
                max_scene_seconds=self.scene_change_seconds,
            )
            total_sections = len(scenes)
            for idx, scene in enumerate(scenes, start=1):
                header = scene["header"]
                body = scene["body"]
                section_duration = float(scene["duration"])
                base_clip = self._make_base_clip(
                    index=idx - 1,
                    scene_header=header,
                    duration=section_duration,
                    scene_text=body,
                    stock_videos_topic=topic_videos,
                    stock_videos_fallback=global_videos,
                    stock_images_topic=topic_images,
                    stock_images_fallback=global_images,
                    render_dir=render_dir,
                    used_video_files=used_video_files,
                    used_image_files=used_image_files,
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
        if header.strip().lower().startswith("intro"):
            return []
        if not self.overlay_text_enabled:
            return []

        cue_source = self._section_cue_text(header=header, body=body)
        if not cue_source:
            return []
        cue_chunks = self._split_caption_chunks(cue_source, target_words=7)
        if not cue_chunks:
            return []

        clips = []
        max_chunks = min(2, len(cue_chunks))
        base_duration = min(2.8, max(1.4, duration * 0.3))
        starts = [max(0.2, duration * 0.1), max(0.5, duration * 0.56)]
        for chunk_idx in range(max_chunks):
            start_t = starts[min(chunk_idx, len(starts) - 1)]
            remaining = duration - start_t - 0.1
            if remaining <= 0.6:
                continue
            chunk_duration = min(base_duration, remaining)
            subtitle_path = self._render_subtitle_card(
                index=index,
                chunk_index=chunk_idx,
                text=cue_chunks[chunk_idx],
                render_dir=render_dir,
            )
            clips.append(
                ImageClip(str(subtitle_path))
                .with_start(start_t)
                .with_duration(chunk_duration)
            )
        return clips

    def _make_base_clip(
        self,
        index: int,
        scene_header: str,
        duration: float,
        scene_text: str,
        stock_videos_topic: list[Path],
        stock_videos_fallback: list[Path],
        stock_images_topic: list[Path],
        stock_images_fallback: list[Path],
        render_dir: Path,
        used_video_files: set[Path],
        used_image_files: set[Path],
    ):
        if scene_header.strip().lower().startswith("intro"):
            intro_card_path = self._render_intro_card(render_dir)
            intro_clip = ImageClip(str(intro_card_path)).with_duration(duration).with_position("center")
            if self.is_draft:
                return intro_clip
            return intro_clip.with_effects([vfx.Resize(lambda t: 1.0 + 0.03 * (t / max(duration, 0.01)))])

        preferred_videos = stock_videos_topic or stock_videos_fallback
        preferred_images = stock_images_topic or stock_images_fallback

        if preferred_videos:
            video_scene = self._build_video_scene_clip(
                duration=duration,
                scene_text=scene_text,
                preferred_videos=preferred_videos,
                preferred_images=preferred_images,
                used_video_files=used_video_files,
                used_image_files=used_image_files,
                index=index,
                render_dir=render_dir,
            )
            if video_scene is not None:
                return video_scene

        image_scene = self._build_image_scene_clip(
            duration=duration,
            scene_text=scene_text,
            preferred_images=preferred_images,
            used_image_files=used_image_files,
        )
        if image_scene is not None:
            return image_scene

        bg_path = self._render_background_image(index, render_dir)
        clip = ImageClip(str(bg_path)).with_duration(duration).with_position("center")
        if self.is_draft:
            return clip
        return clip.with_effects([vfx.Resize(lambda t: 1.01 + 0.04 * (t / max(duration, 0.01)))])

    def _build_video_scene_clip(
        self,
        duration: float,
        scene_text: str,
        preferred_videos: list[Path],
        preferred_images: list[Path],
        used_video_files: set[Path],
        used_image_files: set[Path],
        index: int,
        render_dir: Path,
    ):
        ranked_videos = self._rank_related_files(
            files=preferred_videos,
            scene_text=scene_text,
            used_files=used_video_files,
        )
        if not ranked_videos:
            self.logger.info("scene_media_videos_exhausted")
            return None

        segments = []
        chosen_video_files: list[str] = []
        remaining = duration
        for stock_file in ranked_videos:
            if remaining <= 0.2:
                break
            try:
                source_clip = VideoFileClip(str(stock_file)).without_audio().resized(new_size=self.frame_size)
                available = max(0.0, source_clip.duration)
                if available <= 0.2:
                    source_clip.close()
                    continue
                take = min(available, remaining)
                max_start = max(0.0, available - take)
                start = random.uniform(0.0, max_start) if max_start > 0.0 else 0.0
                segment = source_clip.subclipped(start, start + take).with_duration(take)
                if not self.is_draft:
                    start_scale = random.uniform(1.0, 1.03)
                    end_scale = random.uniform(1.03, 1.08)
                    segment = segment.with_effects(
                        [vfx.Resize(lambda t: start_scale + (end_scale - start_scale) * (t / max(take, 0.01)))]
                    )
                segments.append(segment)
                used_video_files.add(stock_file.resolve())
                chosen_video_files.append(stock_file.name)
                remaining -= take
            except Exception:
                self.logger.exception("stock_footage_failed", extra={"file": str(stock_file)})

        if remaining > 0.3:
            image_filler = self._build_image_scene_clip(
                duration=remaining,
                scene_text=scene_text,
                preferred_images=preferred_images,
                used_image_files=used_image_files,
            )
            if image_filler is not None:
                segments.append(image_filler)
                remaining = 0.0

        if remaining > 0.3:
            bg_path = self._render_background_image(index + 1000, render_dir)
            segments.append(ImageClip(str(bg_path)).with_duration(remaining).with_position("center"))

        if not segments:
            return None
        self.logger.info(
            "scene_media_selected",
            extra={
                "media_kind": "video_montage",
                "video_files": chosen_video_files,
                "segments": len(segments),
            },
        )
        if len(segments) == 1:
            return segments[0].with_duration(duration)
        return concatenate_videoclips(segments, method="compose").with_duration(duration)

    def _build_image_scene_clip(
        self,
        duration: float,
        scene_text: str,
        preferred_images: list[Path],
        used_image_files: set[Path],
    ):
        if not preferred_images:
            return None
        stock_image = self._pick_related_file(
            files=preferred_images,
            scene_text=scene_text,
            used_files=used_image_files,
        )
        if stock_image is None:
            self.logger.info("scene_media_images_exhausted")
            return None
        try:
            clip = ImageClip(str(stock_image)).resized(new_size=self.frame_size).with_duration(duration)
            self.logger.info(
                "scene_media_selected",
                extra={
                    "media_kind": "image",
                    "image_file": stock_image.name,
                },
            )
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
            return None

    def _discover_stock_videos(self, topic: str) -> tuple[list[Path], list[Path]]:
        topic_dir = self._topic_dir(topic)
        return self._topic_and_global_lists(topic_dir, ("*.mp4", "*.mov", "*.mkv"))

    def _discover_stock_images(self, topic: str) -> tuple[list[Path], list[Path]]:
        topic_dir = self._topic_dir(topic)
        return self._topic_and_global_lists(topic_dir, ("*.jpg", "*.jpeg", "*.png", "*.webp"))

    def _render_intro_card(self, render_dir: Path) -> Path:
        width, height = self.frame_size
        image = Image.new("RGB", (width, height), color=(9, 15, 24))
        draw = ImageDraw.Draw(image)

        start, end = (8, 26, 44), (20, 88, 120)
        for y in range(height):
            ratio = y / max(height - 1, 1)
            color = tuple(int(start[i] + (end[i] - start[i]) * ratio) for i in range(3))
            draw.line([(0, y), (width, y)], fill=color, width=1)

        for _ in range(24):
            x = random.randint(-120, width - 40)
            y = random.randint(-80, height - 40)
            w = random.randint(100, 340)
            h = random.randint(70, 230)
            alpha = random.randint(15, 35)
            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            o_draw = ImageDraw.Draw(overlay)
            o_draw.rounded_rectangle([(x, y), (x + w, y + h)], radius=22, fill=(255, 255, 255, alpha))
            image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")

        panel_w = int(width * 0.78)
        panel_h = int(height * 0.45)
        panel_x = int((width - panel_w) / 2)
        panel_y = int((height - panel_h) / 2)
        panel = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        p_draw = ImageDraw.Draw(panel)
        p_draw.rounded_rectangle(
            [(panel_x, panel_y), (panel_x + panel_w, panel_y + panel_h)],
            radius=max(24, int(height * 0.03)),
            fill=(5, 10, 16, 185),
            outline=(180, 220, 245, 100),
            width=2,
        )
        image = Image.alpha_composite(image.convert("RGBA"), panel).convert("RGB")
        draw = ImageDraw.Draw(image)

        channel_name = (self.settings.channel_name or "Curiosity Signal").strip()
        tagline = (self.settings.niche.description or "Interesting science and world facts").strip()
        headline_font = self._load_font(max(48, int(height * 0.08)), bold=True)
        subtitle_font = self._load_font(max(24, int(height * 0.038)), bold=False)

        headline_lines = self._wrap_text(
            channel_name,
            font=headline_font,
            max_width=int(panel_w * 0.85),
            draw=draw,
        )[:2]
        headline_gap = int(headline_font.size * 1.15)
        headline_total_h = max(headline_gap, len(headline_lines) * headline_gap)
        headline_start_y = panel_y + int(panel_h * 0.24) - int(headline_total_h / 2)
        current_y = headline_start_y
        for line in headline_lines:
            text_w = draw.textlength(line, font=headline_font)
            text_x = int((width - text_w) / 2)
            draw.text((text_x, current_y), line, fill=(245, 250, 255), font=headline_font)
            current_y += headline_gap

        tagline_lines = self._wrap_text(
            tagline,
            font=subtitle_font,
            max_width=int(panel_w * 0.82),
            draw=draw,
        )[:2]
        tagline_gap = int(subtitle_font.size * 1.35)
        tagline_start_y = panel_y + int(panel_h * 0.66)
        for line in tagline_lines:
            text_w = draw.textlength(line, font=subtitle_font)
            text_x = int((width - text_w) / 2)
            draw.text((text_x, tagline_start_y), line, fill=(220, 236, 248), font=subtitle_font)
            tagline_start_y += tagline_gap

        output_path = render_dir / "intro_card.png"
        image.save(output_path)
        return output_path

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
        if header.strip().lower().startswith("intro"):
            return ""
        text = body.strip()
        if not text:
            return ""
        sentences = [part.strip() for part in text.replace("!", ".").replace("?", ".").split(".") if part.strip()]
        source = " ".join(sentences[:2]) if sentences else text
        words = source.split()
        short = " ".join(words[:18]) if words else source
        # Remove structure words if present.
        lower_header = header.strip().lower()
        if lower_header.startswith("fact") or lower_header in {"hook", "conclusion"}:
            return short
        return f"{short}"

    def _pick_related_file(
        self,
        files: list[Path],
        scene_text: str,
        used_files: set[Path] | None = None,
        allow_reuse_when_exhausted: bool = False,
    ) -> Path | None:
        ranked = self._rank_related_files(files, scene_text, used_files, allow_reuse_when_exhausted)
        if not ranked:
            return None
        selected = ranked[0]
        if used_files is not None:
            used_files.add(selected.resolve())
        return selected

    def _rank_related_files(
        self,
        files: list[Path],
        scene_text: str,
        used_files: set[Path] | None = None,
        allow_reuse_when_exhausted: bool = False,
    ) -> list[Path]:
        candidates = [file for file in files if file.exists()]
        if not candidates:
            return []
        if used_files is not None:
            unused = [file for file in candidates if file.resolve() not in used_files]
            if unused:
                candidates = unused
            elif not allow_reuse_when_exhausted:
                return []

        scene_tokens = self._tokenize(scene_text)
        if not scene_tokens:
            ranked = candidates[:]
            random.shuffle(ranked)
            return ranked

        scored = []
        for file in candidates:
            file_tokens = self._tokenize(file.stem.replace("__", " "))
            overlap = len(scene_tokens.intersection(file_tokens))
            score = overlap + random.random() * 0.01
            scored.append((score, file))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored]

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        tokens = {token for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if len(token) > 2}
        return tokens

    def _compose_sections(self, script_package: ScriptPackage) -> list[tuple[str, str]]:
        sections: list[tuple[str, str]] = []
        if self.settings.channel_intro_enabled and self.settings.channel_intro_text.strip():
            sections.append(("Intro", self.settings.channel_intro_text.strip()))
        sections.append(("Hook", script_package.hook))
        sections.extend((f"Fact {idx}", fact) for idx, fact in enumerate(script_package.facts, start=1))
        sections.append(("Conclusion", script_package.conclusion))
        return sections

    @staticmethod
    def _expand_scenes(
        sections: list[tuple[str, str]],
        durations: list[float],
        max_scene_seconds: float,
    ) -> list[dict]:
        scenes: list[dict] = []
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
