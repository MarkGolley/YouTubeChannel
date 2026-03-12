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
    openai_tts_voice: str = "alloy"
    voice_provider: str = "openai"

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
            openai_tts_voice=os.getenv("OPENAI_TTS_VOICE", "alloy"),
            voice_provider=os.getenv("VOICE_PROVIDER", "openai"),
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
