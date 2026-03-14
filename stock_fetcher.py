from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import requests

from config import Settings


class PexelsStockFetcher:
    PHOTO_SEARCH_URL = "https://api.pexels.com/v1/search"
    VIDEO_SEARCH_URL = "https://api.pexels.com/videos/search"

    def __init__(self, settings: Settings, logger):
        self.settings = settings
        self.logger = logger

    def ensure_stock_assets(self, topic: str, seed_texts: Iterable[str]) -> None:
        if not self.settings.auto_fetch_stock:
            return
        if not self.settings.pexels_api_key:
            self.logger.warning(
                "pexels_api_key_missing",
                extra={"message_hint": "Set PEXELS_API_KEY to auto-download stock media."},
            )
            return

        topic_dir = self._topic_dir(topic)
        topic_dir.mkdir(parents=True, exist_ok=True)
        current_videos = self._list_files(topic_dir, ("*.mp4", "*.mov", "*.mkv"))
        current_images = self._list_files(topic_dir, ("*.jpg", "*.jpeg", "*.png", "*.webp"))
        need_videos = max(0, self.settings.topic_stock_min_videos - len(current_videos))
        need_images = max(0, self.settings.topic_stock_min_images - len(current_images))

        if need_videos == 0 and need_images == 0:
            self.logger.info(
                "stock_fetch_skipped_enough_topic_assets",
                extra={"topic": topic, "videos": len(current_videos), "images": len(current_images)},
            )
            return

        queries = self._build_queries(topic, seed_texts)
        self.logger.info(
            "stock_fetch_start",
            extra={
                "topic": topic,
                "topic_dir": str(topic_dir),
                "need_videos": need_videos,
                "need_images": need_images,
                "queries": queries[:4],
            },
        )
        for query in queries:
            if need_videos <= 0 and need_images <= 0:
                break
            if need_videos > 0:
                downloaded = self._download_videos(
                    query=query,
                    limit=min(need_videos, self.settings.pexels_videos_per_fetch),
                    target_dir=topic_dir,
                )
                need_videos -= downloaded
            if need_images > 0:
                downloaded = self._download_images(
                    query=query,
                    limit=min(need_images, self.settings.pexels_images_per_fetch),
                    target_dir=topic_dir,
                )
                need_images -= downloaded

        final_videos = len(self._list_files(topic_dir, ("*.mp4", "*.mov", "*.mkv")))
        final_images = len(self._list_files(topic_dir, ("*.jpg", "*.jpeg", "*.png", "*.webp")))
        self.logger.info(
            "stock_fetch_finished",
            extra={"topic": topic, "topic_dir": str(topic_dir), "videos": final_videos, "images": final_images},
        )

    def _download_videos(self, query: str, limit: int, target_dir: Path) -> int:
        if limit <= 0:
            return 0
        headers = {"Authorization": self.settings.pexels_api_key}
        params = {
            "query": query,
            "per_page": min(80, max(1, limit * 3)),
            "orientation": "landscape",
            "size": "large",
        }
        try:
            response = requests.get(
                self.VIDEO_SEARCH_URL,
                headers=headers,
                params=params,
                timeout=self.settings.pexels_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            self.logger.exception("pexels_video_search_failed", extra={"query": query})
            return 0

        downloaded = 0
        query_slug = self._query_slug(query)
        for video in payload.get("videos", []):
            if downloaded >= limit:
                break
            video_id = video.get("id")
            best_file = self._pick_video_file(video.get("video_files", []))
            if not video_id or not best_file:
                continue
            if list(target_dir.glob(f"*pexels_video_{video_id}.mp4")):
                continue
            file_path = target_dir / f"{query_slug}__pexels_video_{video_id}.mp4"
            if self._download_binary(best_file, file_path):
                downloaded += 1
        return downloaded

    def _download_images(self, query: str, limit: int, target_dir: Path) -> int:
        if limit <= 0:
            return 0
        headers = {"Authorization": self.settings.pexels_api_key}
        params = {
            "query": query,
            "per_page": min(80, max(1, limit * 3)),
            "orientation": "landscape",
            "size": "large",
        }
        try:
            response = requests.get(
                self.PHOTO_SEARCH_URL,
                headers=headers,
                params=params,
                timeout=self.settings.pexels_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            self.logger.exception("pexels_photo_search_failed", extra={"query": query})
            return 0

        downloaded = 0
        query_slug = self._query_slug(query)
        for photo in payload.get("photos", []):
            if downloaded >= limit:
                break
            photo_id = photo.get("id")
            src = photo.get("src", {})
            image_url = src.get("landscape") or src.get("large2x") or src.get("large")
            if not photo_id or not image_url:
                continue
            if list(target_dir.glob(f"*pexels_photo_{photo_id}.jpg")):
                continue
            file_path = target_dir / f"{query_slug}__pexels_photo_{photo_id}.jpg"
            if self._download_binary(image_url, file_path):
                downloaded += 1
        return downloaded

    def _download_binary(self, url: str, path: Path) -> bool:
        try:
            response = requests.get(url, timeout=self.settings.pexels_timeout_seconds, stream=True)
            response.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as file:
                for chunk in response.iter_content(chunk_size=1024 * 128):
                    if chunk:
                        file.write(chunk)
            self.logger.info("stock_asset_downloaded", extra={"path": str(path)})
            return True
        except Exception:
            self.logger.exception("stock_asset_download_failed", extra={"url": url})
            return False

    @staticmethod
    def _pick_video_file(video_files: list[dict]) -> str:
        best = None
        for file_obj in video_files:
            link = file_obj.get("link", "")
            if not link:
                continue
            width = int(file_obj.get("width") or 0)
            height = int(file_obj.get("height") or 0)
            area = width * height
            if area <= 0:
                continue
            if best is None or area > best[0]:
                best = (area, link)
        return best[1] if best else ""

    @staticmethod
    def _list_files(directory: Path, patterns: tuple[str, ...]) -> list[Path]:
        files: list[Path] = []
        for pattern in patterns:
            files.extend(directory.glob(pattern))
        return sorted(files)

    def _topic_dir(self, topic: str) -> Path:
        slug = self._topic_slug(topic)
        return self.settings.stock_footage_dir / "topics" / slug

    @staticmethod
    def _topic_slug(value: str, max_len: int = 64) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        slug = re.sub(r"_+", "_", slug)
        return (slug[:max_len] or "topic")

    @staticmethod
    def _query_slug(value: str, max_len: int = 36) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        slug = re.sub(r"_+", "_", slug)
        return (slug[:max_len] or "query")

    @staticmethod
    def _build_queries(topic: str, seed_texts: Iterable[str]) -> list[str]:
        base = [topic]
        base.extend(seed_texts)

        cleaned_entries = []
        for text in base:
            cleaned = re.sub(r"\s+", " ", str(text)).strip()
            if cleaned:
                cleaned_entries.append(cleaned)

        # Keep topic relevance high first, then fallback science B-roll queries.
        query_pool = [
            topic,
            f"{topic} close up",
            f"{topic} macro",
            f"{topic} nature",
            f"{topic} science",
        ]
        query_pool.extend(cleaned_entries[:5])
        query_pool.extend(
            [
                "science laboratory",
                "nature macro",
                "earth texture",
                "educational background",
            ]
        )

        final = []
        for query in query_pool:
            q = re.sub(r"\s+", " ", query).strip()
            if q and q.lower() not in {item.lower() for item in final}:
                final.append(q)
        return final[:12]
