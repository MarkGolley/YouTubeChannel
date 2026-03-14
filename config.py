from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _csv_env(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class NicheConfig:
    description: str = "Interesting science and world facts"
    audience: str = "General audience"
    topic_rules: list[str] = field(
        default_factory=lambda: [
            "Curiosity-driven",
            "Evergreen",
            "Searchable",
            "Monetization-safe",
            "Understandable by non-experts",
        ]
    )
    min_facts: int = 5
    max_facts: int = 10
    target_minutes_min: int = 2
    target_minutes_max: int = 4


@dataclass
class Settings:
    openai_api_key: str
    openai_text_model: str = "gpt-4.1-mini"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "verse"
    openai_tts_speed: float = 1.03
    openai_tts_instructions: str = (
        "You are a high-retention YouTube science narrator. Sound warm, curious, and engaging, "
        "with varied pace and emphasis. Use natural pauses, slight excitement on surprising points, "
        "and avoid flat monotone delivery."
    )
    voice_provider: str = "openai"
    pexels_api_key: str = ""
    auto_fetch_stock: bool = True
    stock_min_videos: int = 10
    stock_min_images: int = 20
    topic_stock_min_videos: int = 4
    topic_stock_min_images: int = 8
    pexels_videos_per_fetch: int = 4
    pexels_images_per_fetch: int = 6
    pexels_timeout_seconds: int = 30
    run_profile: str = "production"
    video_overlay_text_enabled: bool = True
    channel_name: str = "Curiosity Signal"
    channel_intro_enabled: bool = True
    channel_intro_text: str = (
        "Welcome to another video from Curiosity Signal, your home of fascinating science content."
    )

    timezone: str = "UTC"
    schedule_hour: int = 10
    schedule_minute: int = 0
    run_once_on_start: bool = False
    auto_schedule_upload: bool = True
    publish_days_ahead: int = 1

    target_video_seconds_min: int = 120
    target_video_seconds_max: int = 240
    max_generation_retries: int = 2
    render_width: int = 1920
    render_height: int = 1080
    video_fps: int = 24
    video_preset: str = "medium"

    output_dir: Path = Path("output")
    temp_dir: Path = Path("output/temp")
    logs_dir: Path = Path("logs")
    state_dir: Path = Path("state")
    assets_dir: Path = Path("assets")
    stock_footage_dir: Path = Path("assets/stock")
    secrets_dir: Path = Path("secrets")
    topic_history_file: Path = Path("state/topic_history.json")
    script_archive_file: Path = Path("state/script_archive.jsonl")
    pending_job_file: Path = Path("state/pending_job.json")

    youtube_credentials_file: Path = Path("secrets/client_secret.json")
    youtube_token_file: Path = Path("secrets/token.json")
    youtube_category_id: str = "27"
    default_tags: list[str] = field(
        default_factory=lambda: [
            "science facts",
            "world facts",
            "interesting facts",
            "educational videos",
            "curiosity",
        ]
    )
    dry_run: bool = True

    niche: NicheConfig = field(default_factory=NicheConfig)

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        return cls(
            openai_api_key=openai_api_key,
            openai_text_model=os.getenv("OPENAI_TEXT_MODEL", "gpt-4.1-mini"),
            openai_tts_model=os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
            openai_tts_voice=os.getenv("OPENAI_TTS_VOICE", "verse"),
            openai_tts_speed=_float_env("OPENAI_TTS_SPEED", 1.03),
            openai_tts_instructions=os.getenv(
                "OPENAI_TTS_INSTRUCTIONS",
                (
                    "You are a high-retention YouTube science narrator. Sound warm, curious, and engaging, "
                    "with varied pace and emphasis. Use natural pauses, slight excitement on surprising points, "
                    "and avoid flat monotone delivery."
                ),
            ),
            voice_provider=os.getenv("VOICE_PROVIDER", "openai"),
            pexels_api_key=os.getenv("PEXELS_API_KEY", "").strip(),
            auto_fetch_stock=_bool_env("AUTO_FETCH_STOCK", True),
            stock_min_videos=_int_env("STOCK_MIN_VIDEOS", 10),
            stock_min_images=_int_env("STOCK_MIN_IMAGES", 20),
            topic_stock_min_videos=_int_env("TOPIC_STOCK_MIN_VIDEOS", _int_env("STOCK_MIN_VIDEOS", 10)),
            topic_stock_min_images=_int_env("TOPIC_STOCK_MIN_IMAGES", _int_env("STOCK_MIN_IMAGES", 20)),
            pexels_videos_per_fetch=_int_env("PEXELS_VIDEOS_PER_FETCH", 4),
            pexels_images_per_fetch=_int_env("PEXELS_IMAGES_PER_FETCH", 6),
            pexels_timeout_seconds=_int_env("PEXELS_TIMEOUT_SECONDS", 30),
            run_profile=os.getenv("RUN_PROFILE", "production"),
            video_overlay_text_enabled=_bool_env("VIDEO_OVERLAY_TEXT_ENABLED", True),
            channel_name=os.getenv("CHANNEL_NAME", "Curiosity Signal"),
            channel_intro_enabled=_bool_env("CHANNEL_INTRO_ENABLED", True),
            channel_intro_text=os.getenv(
                "CHANNEL_INTRO_TEXT",
                "Welcome to another video from Curiosity Signal, your home of fascinating science content.",
            ),
            timezone=os.getenv("TIMEZONE", "UTC"),
            schedule_hour=_int_env("SCHEDULE_HOUR", 10),
            schedule_minute=_int_env("SCHEDULE_MINUTE", 0),
            run_once_on_start=_bool_env("RUN_ONCE_ON_START", False),
            auto_schedule_upload=_bool_env("AUTO_SCHEDULE_UPLOAD", True),
            publish_days_ahead=_int_env("PUBLISH_DAYS_AHEAD", 1),
            target_video_seconds_min=_int_env("VIDEO_SECONDS_MIN", 120),
            target_video_seconds_max=_int_env("VIDEO_SECONDS_MAX", 240),
            max_generation_retries=_int_env("MAX_GENERATION_RETRIES", 2),
            render_width=_int_env("RENDER_WIDTH", 1920),
            render_height=_int_env("RENDER_HEIGHT", 1080),
            video_fps=_int_env("VIDEO_FPS", 24),
            video_preset=os.getenv("VIDEO_PRESET", "medium"),
            output_dir=Path(os.getenv("OUTPUT_DIR", "output")),
            temp_dir=Path(os.getenv("TEMP_DIR", "output/temp")),
            logs_dir=Path(os.getenv("LOGS_DIR", "logs")),
            state_dir=Path(os.getenv("STATE_DIR", "state")),
            assets_dir=Path(os.getenv("ASSETS_DIR", "assets")),
            stock_footage_dir=Path(os.getenv("STOCK_FOOTAGE_DIR", "assets/stock")),
            secrets_dir=Path(os.getenv("SECRETS_DIR", "secrets")),
            topic_history_file=Path(os.getenv("TOPIC_HISTORY_FILE", "state/topic_history.json")),
            script_archive_file=Path(os.getenv("SCRIPT_ARCHIVE_FILE", "state/script_archive.jsonl")),
            pending_job_file=Path(os.getenv("PENDING_JOB_FILE", "state/pending_job.json")),
            youtube_credentials_file=Path(
                os.getenv("YOUTUBE_CREDENTIALS_FILE", "secrets/client_secret.json")
            ),
            youtube_token_file=Path(os.getenv("YOUTUBE_TOKEN_FILE", "secrets/token.json")),
            youtube_category_id=os.getenv("YOUTUBE_CATEGORY_ID", "27"),
            default_tags=_csv_env(
                "DEFAULT_TAGS",
                [
                    "science facts",
                    "world facts",
                    "interesting facts",
                    "educational videos",
                    "curiosity",
                ],
            ),
            dry_run=_bool_env("DRY_RUN", True),
            niche=NicheConfig(
                description=os.getenv("NICHE_DESCRIPTION", "Interesting science and world facts"),
                audience=os.getenv("NICHE_AUDIENCE", "General audience"),
            ),
        )

    def ensure_directories(self) -> None:
        for directory in (
            self.output_dir,
            self.temp_dir,
            self.logs_dir,
            self.state_dir,
            self.assets_dir,
            self.stock_footage_dir,
            self.secrets_dir,
            self.output_dir / "audio",
            self.output_dir / "video",
            self.output_dir / "thumbnail",
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def apply_profile(self, profile_override: str | None = None) -> str:
        profile = (profile_override or self.run_profile or "production").strip().lower()
        if profile in {"draft", "dev", "quick"}:
            self.run_profile = "draft"
            self.render_width = 640
            self.render_height = 360
            self.video_fps = 12
            self.video_preset = "ultrafast"
            self.stock_min_videos = min(self.stock_min_videos, 2)
            self.stock_min_images = min(self.stock_min_images, 4)
            self.topic_stock_min_videos = min(self.topic_stock_min_videos, 2)
            self.topic_stock_min_images = min(self.topic_stock_min_images, 4)
            self.pexels_videos_per_fetch = min(self.pexels_videos_per_fetch, 1)
            self.pexels_images_per_fetch = min(self.pexels_images_per_fetch, 2)
            return self.run_profile

        if profile in {"production", "prod", "full"}:
            self.run_profile = "production"
            self.render_width = 1920
            self.render_height = 1080
            self.video_fps = 24
            self.video_preset = "medium"
            self.stock_min_videos = max(self.stock_min_videos, 10)
            self.stock_min_images = max(self.stock_min_images, 20)
            self.topic_stock_min_videos = max(self.topic_stock_min_videos, 4)
            self.topic_stock_min_images = max(self.topic_stock_min_images, 8)
            self.pexels_videos_per_fetch = max(self.pexels_videos_per_fetch, 4)
            self.pexels_images_per_fetch = max(self.pexels_images_per_fetch, 6)
            return self.run_profile

        raise ValueError(f"Unsupported RUN_PROFILE: {profile}")
