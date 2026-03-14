from __future__ import annotations

import struct
import wave
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from config import Settings


class TTSProvider(ABC):
    @abstractmethod
    def synthesize(self, text: str, output_path: Path) -> Path:
        raise NotImplementedError


class OpenAITTSProvider(TTSProvider):
    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when VOICE_PROVIDER=openai")
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_tts_model
        self.voice = settings.openai_tts_voice
        self.audio_format = (settings.openai_tts_format or "wav").strip().lower()
        if self.audio_format not in {"wav", "mp3", "aac", "opus", "flac"}:
            self.audio_format = "wav"
        self.speed = min(4.0, max(0.25, settings.openai_tts_speed))
        self.instructions = settings.openai_tts_instructions

    def synthesize(self, text: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        response = self.client.audio.speech.create(
            model=self.model,
            voice=self.voice,
            input=text,
            instructions=self.instructions,
            response_format=self.audio_format,
            speed=self.speed,
        )
        response.stream_to_file(str(output_path))
        return output_path


class SilentTTSProvider(TTSProvider):
    def synthesize(self, text: str, output_path: Path) -> Path:
        duration_seconds = max(8, int(len(text.split()) / 2.6))
        wav_path = output_path.with_suffix(".wav")
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        self._generate_silence_file(wav_path, duration_seconds)
        return wav_path

    @staticmethod
    def _generate_silence_file(output_path: Path, duration_seconds: int, sample_rate: int = 22_050) -> None:
        frame_count = duration_seconds * sample_rate
        with wave.open(str(output_path), "w") as file:
            file.setnchannels(1)
            file.setsampwidth(2)
            file.setframerate(sample_rate)
            for i in range(frame_count):
                _ = i
                value = 0
                file.writeframesraw(struct.pack("<h", value))


class VoiceGenerator:
    def __init__(self, settings: Settings, logger):
        self.settings = settings
        self.logger = logger
        provider = settings.voice_provider.strip().lower()
        if provider == "openai":
            self.provider: TTSProvider = OpenAITTSProvider(settings)
        elif provider == "silent":
            self.provider = SilentTTSProvider()
        else:
            raise ValueError(f"Unsupported VOICE_PROVIDER: {settings.voice_provider}")

    def generate_narration(self, text: str, topic: str) -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        slug = self._slugify(topic)
        extension = self._audio_extension()
        output_path = self.settings.output_dir / "audio" / f"{slug}_{timestamp}{extension}"
        self.logger.info("narration_generation_started", extra={"output_path": str(output_path)})
        audio_path = self.provider.synthesize(text=text, output_path=output_path)
        diagnostics = self._audio_diagnostics(audio_path)
        self.logger.info(
            "narration_generation_finished",
            extra={
                "audio_path": str(audio_path),
                "audio_bytes": diagnostics["audio_bytes"],
                "audio_rms": diagnostics["audio_rms"],
            },
        )
        return audio_path

    @staticmethod
    def _slugify(value: str, limit: int = 60) -> str:
        cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        return cleaned[:limit] or "video"

    def _audio_extension(self) -> str:
        provider = self.settings.voice_provider.lower().strip()
        if provider != "openai":
            return ".wav"
        fmt = (self.settings.openai_tts_format or "wav").strip().lower()
        if fmt == "wav":
            return ".wav"
        if fmt in {"mp3", "aac", "opus", "flac"}:
            return f".{fmt}"
        return ".wav"

    @staticmethod
    def _audio_diagnostics(audio_path: Path) -> dict[str, float | int]:
        size = audio_path.stat().st_size if audio_path.exists() else 0
        rms = -1.0
        if audio_path.suffix.lower() == ".wav":
            try:
                with wave.open(str(audio_path), "rb") as file:
                    nframes = file.getnframes()
                    sample_width = file.getsampwidth()
                    if nframes > 0 and sample_width == 2:
                        raw = file.readframes(min(nframes, 22050 * 15))
                        total = len(raw) // 2
                        if total > 0:
                            samples = struct.unpack("<" + ("h" * total), raw)
                            squares = [float(sample) * float(sample) for sample in samples]
                            rms = (sum(squares) / max(1, len(squares))) ** 0.5
            except Exception:
                rms = -1.0
        return {"audio_bytes": int(size), "audio_rms": float(rms)}
