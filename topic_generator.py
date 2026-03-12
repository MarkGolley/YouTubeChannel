from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

from config import Settings


class TopicGenerator:
    def __init__(self, settings: Settings, logger):
        self.settings = settings
        self.logger = logger
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    def generate_topic(self) -> str:
        history = self._load_history()
        topic = self._generate_with_llm(history)
        if not topic:
            topic = self._fallback_topic(history)
        if self._is_duplicate(topic, history):
            topic = self._fallback_topic(history)
        self._save_topic(topic, history)
        self.logger.info("topic_selected", extra={"topic": topic})
        return topic

    def _generate_with_llm(self, history: list[str]) -> str:
        if self.client is None:
            return ""

        recent_topics = history[-50:]
        prompt = (
            "Generate one YouTube topic for a faceless channel focused on interesting science and world facts.\n"
            "Rules:\n"
            "- Curiosity-driven and searchable\n"
            "- Evergreen and understandable by general audience\n"
            "- Monetization-safe\n"
            "- Should naturally fit a 2-4 minute video with 5-10 facts\n"
            "Avoid these recent topics:\n"
            f"{json.dumps(recent_topics, ensure_ascii=True)}\n\n"
            "Return JSON only in this schema: {\"topic\": \"...\"}"
        )
        try:
            completion = self.client.chat.completions.create(
                model=self.settings.openai_text_model,
                temperature=0.9,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": "You generate high-performing educational YouTube topics.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            content = completion.choices[0].message.content or "{}"
            payload = json.loads(content)
            topic = str(payload.get("topic", "")).strip()
            return topic
        except Exception:
            self.logger.exception("topic_generation_failed")
            return ""

    def _fallback_topic(self, history: list[str]) -> str:
        templates = [
            "7 science facts about {subject} that sound impossible",
            "5 accidental discoveries that changed science forever",
            "8 deep ocean facts that scientists still cannot explain",
            "6 mysterious world discoveries with scientific clues",
            "9 strange facts about {subject} most people never hear",
        ]
        subjects = [
            "space",
            "the human brain",
            "the deep ocean",
            "Earth's atmosphere",
            "ancient civilizations",
            "extreme weather",
            "volcanoes and earthquakes",
            "animals with unusual abilities",
        ]
        normalized = {self._normalize(item) for item in history}
        for _ in range(40):
            topic = random.choice(templates).format(subject=random.choice(subjects))
            if self._normalize(topic) not in normalized:
                return topic
        return f"7 surprising science facts #{len(history) + 1}"

    def _load_history(self) -> list[str]:
        history_file = self.settings.topic_history_file
        if not history_file.exists():
            return []
        try:
            payload: Any = json.loads(history_file.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                return [str(item).strip() for item in payload if str(item).strip()]
            return []
        except Exception:
            self.logger.exception("topic_history_read_failed", extra={"path": str(history_file)})
            return []

    def _save_topic(self, topic: str, history: list[str]) -> None:
        if topic not in history:
            history.append(topic)
        self._write_history(history)

    def _write_history(self, history: list[str]) -> None:
        history_file = self.settings.topic_history_file
        history_file.parent.mkdir(parents=True, exist_ok=True)
        history_file.write_text(json.dumps(history[-1000:], indent=2), encoding="utf-8")

    def _is_duplicate(self, topic: str, history: list[str]) -> bool:
        normalized = self._normalize(topic)
        return normalized in {self._normalize(item) for item in history}

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", value.lower())).strip()
