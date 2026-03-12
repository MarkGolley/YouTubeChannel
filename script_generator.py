from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

from config import Settings


@dataclass
class ScriptPackage:
    topic: str
    hook: str
    facts: list[str]
    conclusion: str
    title: str
    description: str
    tags: list[str]
    narration_text: str


class ScriptGenerator:
    def __init__(self, settings: Settings, logger):
        self.settings = settings
        self.logger = logger
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    def generate(self, topic: str) -> ScriptPackage:
        package = self._generate_with_llm(topic)
        if package is None:
            package = self._fallback_script(topic)
        self.logger.info("script_generated", extra={"topic": topic, "title": package.title})
        return package

    def archive_script(
        self,
        script_package: ScriptPackage,
        video_path: Path,
        audio_path: Path,
        thumbnail_path: Path,
        upload_result: dict,
    ) -> None:
        record = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "script": asdict(script_package),
            "assets": {
                "video_path": str(video_path),
                "audio_path": str(audio_path),
                "thumbnail_path": str(thumbnail_path),
            },
            "upload_result": upload_result,
        }
        archive_file = self.settings.script_archive_file
        archive_file.parent.mkdir(parents=True, exist_ok=True)
        with archive_file.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=True) + "\n")

    def _generate_with_llm(self, topic: str) -> ScriptPackage | None:
        if self.client is None:
            return None

        prompt = (
            "Create a concise, engaging YouTube script package in JSON for this topic:\n"
            f"{topic}\n\n"
            "Requirements:\n"
            "- Channel type: interesting science and world facts\n"
            "- 2 to 4 minute video length\n"
            "- Structure: Hook, Fact 1..Fact 5, Conclusion\n"
            "- Facts should be accurate and easy to understand\n"
            "- Tone: educational but entertaining\n"
            "- Monetization-safe language\n"
            "- Create SEO-optimized but natural metadata\n"
            "Return JSON only with this schema:\n"
            "{\n"
            '  "hook": "...",\n'
            '  "facts": ["...", "...", "...", "...", "..."],\n'
            '  "conclusion": "...",\n'
            '  "title": "...",\n'
            '  "description": "...",\n'
            '  "tags": ["...", "..."]\n'
            "}"
        )
        try:
            completion = self.client.chat.completions.create(
                model=self.settings.openai_text_model,
                temperature=0.7,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert educational YouTube scriptwriter and SEO editor.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            content = completion.choices[0].message.content or "{}"
            payload = json.loads(content)
            hook = str(payload.get("hook", "")).strip()
            facts = [str(item).strip() for item in payload.get("facts", []) if str(item).strip()]
            conclusion = str(payload.get("conclusion", "")).strip()
            title = str(payload.get("title", "")).strip()
            description = str(payload.get("description", "")).strip()
            tags = [str(item).strip() for item in payload.get("tags", []) if str(item).strip()]
            if len(facts) < 5:
                return None
            narration_text = self._build_narration_text(hook, facts, conclusion)
            return ScriptPackage(
                topic=topic,
                hook=hook,
                facts=facts[:5],
                conclusion=conclusion,
                title=title[:100],
                description=description[:5000],
                tags=(tags or self.settings.default_tags)[:15],
                narration_text=narration_text,
            )
        except Exception:
            self.logger.exception("script_generation_failed", extra={"topic": topic})
            return None

    def _fallback_script(self, topic: str) -> ScriptPackage:
        facts = [
            "Scientists often discover major breakthroughs while trying to solve unrelated problems.",
            "Many deep-ocean and space discoveries are inferred from indirect evidence first, then confirmed years later.",
            "Human perception of size and distance in nature is frequently counterintuitive, leading to surprising facts.",
            "Simple scientific tools have repeatedly outperformed complex theories in early-stage discoveries.",
            "Global collaboration dramatically increases discovery speed in modern science.",
        ]
        hook = f"What if some of the wildest facts about {topic.lower()} are actually true?"
        conclusion = "If you want more surprising science and world facts, follow for the next list."
        title = topic if len(topic) <= 95 else topic[:95].rstrip() + "..."
        description = (
            f"In this video, we explore {topic.lower()} with 5 surprising facts. "
            "These curiosity-driven science insights are clear, accurate, and made for a general audience."
        )
        tags = (self.settings.default_tags + [topic.lower(), "facts"])[:15]
        narration_text = self._build_narration_text(hook, facts, conclusion)
        return ScriptPackage(
            topic=topic,
            hook=hook,
            facts=facts,
            conclusion=conclusion,
            title=title,
            description=description,
            tags=tags,
            narration_text=narration_text,
        )

    @staticmethod
    def _build_narration_text(hook: str, facts: list[str], conclusion: str) -> str:
        lines = [f"Hook: {hook}"]
        for index, fact in enumerate(facts, start=1):
            lines.append(f"Fact {index}: {fact}")
        lines.append(f"Conclusion: {conclusion}")
        return "\n\n".join(lines)
