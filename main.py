from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from config import Settings
from logger import get_logger
from scheduler import PipelineScheduler
from script_generator import ScriptGenerator, ScriptPackage
from stock_fetcher import PexelsStockFetcher
from thumbnail_generator import ThumbnailGenerator
from topic_generator import TopicGenerator
from video_builder import VideoBuilder
from voice_generator import VoiceGenerator
from youtube_uploader import YouTubeUploader


class VideoAutomationApp:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = get_logger(settings.logs_dir)
        self.topic_generator = TopicGenerator(settings, self.logger)
        self.script_generator = ScriptGenerator(settings, self.logger)
        self.voice_generator = VoiceGenerator(settings, self.logger)
        self.stock_fetcher = PexelsStockFetcher(settings, self.logger)
        self.video_builder = VideoBuilder(settings, self.logger)
        self.thumbnail_generator = ThumbnailGenerator(settings, self.logger)
        self.youtube_uploader = YouTubeUploader(settings, self.logger)

    def run_once(self, fresh: bool = False, resume: bool = True) -> None:
        attempts = self.settings.max_generation_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                self.logger.info("pipeline_start", extra={"attempt": attempt, "fresh": fresh, "resume": resume})
                if self.settings.voice_provider.strip().lower() == "silent":
                    self.logger.warning(
                        "voice_provider_silent_mode",
                        extra={"message_hint": "Narration will be silent in output by design."},
                    )
                if resume and not fresh and self._resume_pending_if_available():
                    return

                self.logger.info("stage_start", extra={"stage": "topic_generation"})
                topic = self.topic_generator.generate_topic()
                self._save_pending_job(stage="topic_ready", topic=topic)

                self.logger.info("stage_start", extra={"stage": "script_generation", "topic": topic})
                script_package = self.script_generator.generate(topic)
                self._save_pending_job(
                    stage="script_ready",
                    topic=topic,
                    script_package=script_package,
                )

                self.logger.info("stage_start", extra={"stage": "stock_fetch"})
                self.stock_fetcher.ensure_stock_assets(
                    topic=topic,
                    seed_texts=[script_package.hook, *script_package.facts, script_package.conclusion],
                )

                self.logger.info("stage_start", extra={"stage": "voice_generation"})
                audio_path = self.voice_generator.generate_narration(script_package.narration_text, topic)
                self._save_pending_job(
                    stage="audio_ready",
                    topic=topic,
                    script_package=script_package,
                    audio_path=audio_path,
                )

                self.logger.info("stage_start", extra={"stage": "video_render"})
                video_path = self.video_builder.build_video(script_package, audio_path)
                self._save_pending_job(
                    stage="video_ready",
                    topic=topic,
                    script_package=script_package,
                    audio_path=audio_path,
                    video_path=video_path,
                )

                self.logger.info("stage_start", extra={"stage": "thumbnail_generation"})
                thumbnail_path = self.thumbnail_generator.generate_thumbnail(script_package.title)
                self._save_pending_job(
                    stage="thumbnail_ready",
                    topic=topic,
                    script_package=script_package,
                    audio_path=audio_path,
                    video_path=video_path,
                    thumbnail_path=thumbnail_path,
                )

                self._upload_and_finalize(
                    topic=topic,
                    script_package=script_package,
                    audio_path=audio_path,
                    video_path=video_path,
                    thumbnail_path=thumbnail_path,
                )
                return
            except Exception:
                self.logger.exception("pipeline_failed", extra={"attempt": attempt})
                if attempt == attempts:
                    raise

    def print_status(self) -> None:
        pending = self._load_pending_job()
        if not pending:
            print("No pending job. Use: python main.py --once")
            return

        stage = pending.get("stage", "unknown")
        topic = pending.get("topic", "")
        audio_path = pending.get("audio_path", "")
        video_path = pending.get("video_path", "")
        thumbnail_path = pending.get("thumbnail_path", "")

        print("Pending job found:")
        print(f"- Stage: {stage}")
        print(f"- Topic: {topic}")
        print(f"- Audio: {audio_path}")
        print(f"- Video: {video_path}")
        print(f"- Thumbnail: {thumbnail_path}")
        print("Resume command: python main.py --once --resume")
        print("Start fresh command: python main.py --once --fresh")

    def _resume_pending_if_available(self) -> bool:
        pending = self._load_pending_job()
        if not pending:
            return False

        stage = str(pending.get("stage", "")).strip()
        topic = str(pending.get("topic", "")).strip()
        script_data = pending.get("script_package") or {}
        if not topic or not isinstance(script_data, dict):
            self.logger.warning("pending_job_invalid", extra={"reason": "missing_topic_or_script"})
            return False

        script_package = ScriptPackage(**script_data)
        audio_path = self._to_path(pending.get("audio_path"))
        video_path = self._to_path(pending.get("video_path"))
        thumbnail_path = self._to_path(pending.get("thumbnail_path"))

        self.logger.info("pending_job_resume_start", extra={"stage": stage, "topic": topic})

        if audio_path is None or not audio_path.exists():
            self.logger.info("stage_start", extra={"stage": "voice_generation_resume"})
            audio_path = self.voice_generator.generate_narration(script_package.narration_text, topic)
            self._save_pending_job(
                stage="audio_ready",
                topic=topic,
                script_package=script_package,
                audio_path=audio_path,
            )

        if video_path is None or not video_path.exists():
            self.logger.info("stage_start", extra={"stage": "stock_fetch_resume"})
            self.stock_fetcher.ensure_stock_assets(
                topic=topic,
                seed_texts=[script_package.hook, *script_package.facts, script_package.conclusion],
            )
            self.logger.info("stage_start", extra={"stage": "video_render_resume"})
            video_path = self.video_builder.build_video(script_package, audio_path)
            self._save_pending_job(
                stage="video_ready",
                topic=topic,
                script_package=script_package,
                audio_path=audio_path,
                video_path=video_path,
            )

        if thumbnail_path is None or not thumbnail_path.exists():
            self.logger.info("stage_start", extra={"stage": "thumbnail_generation_resume"})
            thumbnail_path = self.thumbnail_generator.generate_thumbnail(script_package.title)
            self._save_pending_job(
                stage="thumbnail_ready",
                topic=topic,
                script_package=script_package,
                audio_path=audio_path,
                video_path=video_path,
                thumbnail_path=thumbnail_path,
            )

        self._upload_and_finalize(
            topic=topic,
            script_package=script_package,
            audio_path=audio_path,
            video_path=video_path,
            thumbnail_path=thumbnail_path,
        )
        return True

    def _upload_and_finalize(
        self,
        topic: str,
        script_package: ScriptPackage,
        audio_path: Path,
        video_path: Path,
        thumbnail_path: Path,
    ) -> None:
        self.logger.info("stage_start", extra={"stage": "youtube_upload"})
        publish_at = self._compute_publish_at_utc()
        upload_result = self.youtube_uploader.upload(
            video_path=video_path,
            thumbnail_path=thumbnail_path,
            title=script_package.title,
            description=script_package.description,
            tags=script_package.tags,
            publish_at_utc=publish_at,
        )
        self.script_generator.archive_script(
            script_package=script_package,
            video_path=video_path,
            audio_path=audio_path,
            thumbnail_path=thumbnail_path,
            upload_result=upload_result,
        )
        self._clear_pending_job()
        self.logger.info(
            "pipeline_success",
            extra={
                "topic": topic,
                "video_path": str(video_path),
                "video_id": upload_result.get("video_id", ""),
            },
        )

    def _save_pending_job(
        self,
        stage: str,
        topic: str,
        script_package: ScriptPackage | None = None,
        audio_path: Path | None = None,
        video_path: Path | None = None,
        thumbnail_path: Path | None = None,
    ) -> None:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "topic": topic,
            "script_package": self._script_to_dict(script_package),
            "audio_path": str(audio_path) if audio_path else "",
            "video_path": str(video_path) if video_path else "",
            "thumbnail_path": str(thumbnail_path) if thumbnail_path else "",
        }
        self.settings.pending_job_file.parent.mkdir(parents=True, exist_ok=True)
        self.settings.pending_job_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.logger.info("pending_job_saved", extra={"stage": stage, "path": str(self.settings.pending_job_file)})

    def _load_pending_job(self) -> dict[str, Any] | None:
        path = self.settings.pending_job_file
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
            return None
        except Exception:
            self.logger.exception("pending_job_read_failed", extra={"path": str(path)})
            return None

    def _clear_pending_job(self) -> None:
        path = self.settings.pending_job_file
        if path.exists():
            path.unlink()
            self.logger.info("pending_job_cleared", extra={"path": str(path)})

    def _compute_publish_at_utc(self) -> datetime | None:
        if not self.settings.auto_schedule_upload:
            return None

        now_local = datetime.now(ZoneInfo(self.settings.timezone))
        publish_local = now_local + timedelta(days=self.settings.publish_days_ahead)
        publish_local = publish_local.replace(
            hour=self.settings.schedule_hour,
            minute=self.settings.schedule_minute,
            second=0,
            microsecond=0,
        )
        if publish_local <= now_local:
            publish_local += timedelta(days=1)

        return publish_local.astimezone(timezone.utc)

    @staticmethod
    def _script_to_dict(script_package: ScriptPackage | None) -> dict[str, Any]:
        if script_package is None:
            return {}
        return {
            "topic": script_package.topic,
            "hook": script_package.hook,
            "facts": script_package.facts,
            "conclusion": script_package.conclusion,
            "title": script_package.title,
            "description": script_package.description,
            "tags": script_package.tags,
            "narration_text": script_package.narration_text,
        }

    @staticmethod
    def _to_path(value: Any) -> Path | None:
        if not value:
            return None
        return Path(str(value))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automated faceless YouTube video pipeline")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run pipeline once and exit",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from pending checkpoint if available (default behavior)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore pending checkpoint and generate a fresh video",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show pending checkpoint status and exit",
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        help="Use draft profile (faster, lower quality)",
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help="Use production profile (slower, higher quality)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.draft and args.production:
        raise ValueError("Use only one of --draft or --production.")

    settings = Settings.from_env()
    profile_override = "draft" if args.draft else "production" if args.production else None
    active_profile = settings.apply_profile(profile_override)
    settings.ensure_directories()
    app = VideoAutomationApp(settings)
    app.logger.info(
        "runtime_profile",
        extra={
            "profile": active_profile,
            "render_width": settings.render_width,
            "render_height": settings.render_height,
            "video_fps": settings.video_fps,
            "video_preset": settings.video_preset,
            "voice_provider": settings.voice_provider,
            "dry_run": settings.dry_run,
        },
    )

    if args.status:
        app.print_status()
        return

    if args.once:
        app.run_once(fresh=args.fresh, resume=(args.resume or not args.fresh))
        return

    scheduler = PipelineScheduler(settings, app.logger)
    scheduler.start(lambda: app.run_once(fresh=False, resume=True))


if __name__ == "__main__":
    main()
