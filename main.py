from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import Settings
from logger import get_logger
from scheduler import PipelineScheduler
from script_generator import ScriptGenerator
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
        self.video_builder = VideoBuilder(settings, self.logger)
        self.thumbnail_generator = ThumbnailGenerator(settings, self.logger)
        self.youtube_uploader = YouTubeUploader(settings, self.logger)

    def run_once(self) -> None:
        attempts = self.settings.max_generation_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                self.logger.info("pipeline_start", extra={"attempt": attempt})
                topic = self.topic_generator.generate_topic()
                script_package = self.script_generator.generate(topic)
                audio_path = self.voice_generator.generate_narration(
                    script_package.narration_text,
                    topic,
                )
                video_path = self.video_builder.build_video(script_package, audio_path)
                thumbnail_path = self.thumbnail_generator.generate_thumbnail(script_package.title)
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
                self.logger.info(
                    "pipeline_success",
                    extra={
                        "topic": topic,
                        "video_path": str(video_path),
                        "video_id": upload_result.get("video_id", ""),
                    },
                )
                return
            except Exception:
                self.logger.exception("pipeline_failed", extra={"attempt": attempt})
                if attempt == attempts:
                    raise

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automated faceless YouTube video pipeline")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run the pipeline once and exit",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = Settings.from_env()
    settings.ensure_directories()
    app = VideoAutomationApp(settings)

    if args.once:
        app.run_once()
        return

    scheduler = PipelineScheduler(settings, app.logger)
    scheduler.start(app.run_once)


if __name__ == "__main__":
    main()
