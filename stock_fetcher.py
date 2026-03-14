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

        current_videos = self._list_files(("*.mp4", "*.mov", "*.mkv"))
        current_images = self._list_files(("*.jpg", "*.jpeg", "*.png", "*.webp"))
        need_videos = max(0, self.settings.stock_min_videos - len(current_videos))
        need_images = max(0, self.settings.stock_min_images - len(current_images))

        if need_videos == 0 and need_images == 0:
            self.logger.info(
                "stock_fetch_skipped_enough_assets",
                extra={"videos": len(current_videos), "images": len(current_images)},
            )
            return

        queries = self._build_queries(topic, seed_texts)
        self.logger.info(
            "stock_fetch_start",
            extra={"need_videos": need_videos, "need_images": need_images, "queries": queries[:4]},
        )
        for query in queries:
            if need_videos <= 0 and need_images <= 0:
                break
            if need_videos > 0:
                downloaded = self._download_videos(query, min(need_videos, self.settings.pexels_videos_per_fetch))
                need_videos -= downloaded
            if need_images > 0:
                downloaded = self._download_images(query, min(need_images, self.settings.pexels_images_per_fetch))
                need_images -= downloaded

        final_videos = len(self._list_files(("*.mp4", "*.mov", "*.mkv")))
        final_images = len(self._list_files(("*.jpg", "*.jpeg", "*.png", "*.webp")))
        self.logger.info(
            "stock_fetch_finished",
            extra={"videos": final_videos, "images": final_images},
        )

    def _download_videos(self, query: str, limit: int) -> int:
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
        for video in payload.get("videos", []):
            if downloaded >= limit:
                break
            video_id = video.get("id")
            best_file = self._pick_video_file(video.get("video_files", []))
            if not video_id or not best_file:
                continue
            file_path = self.settings.stock_footage_dir / f"pexels_video_{video_id}.mp4"
            if file_path.exists():
                continue
            if self._download_binary(best_file, file_path):
                downloaded += 1
        return downloaded

    def _download_images(self, query: str, limit: int) -> int:
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
        for photo in payload.get("photos", []):
            if downloaded >= limit:
                break
            photo_id = photo.get("id")
            src = photo.get("src", {})
            image_url = src.get("landscape") or src.get("large2x") or src.get("large")
            if not photo_id or not image_url:
                continue
            file_path = self.settings.stock_footage_dir / f"pexels_photo_{photo_id}.jpg"
            if file_path.exists():
                continue
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

    def _list_files(self, patterns: tuple[str, ...]) -> list[Path]:
        files: list[Path] = []
        for pattern in patterns:
            files.extend(self.settings.stock_footage_dir.glob(pattern))
        return sorted(files)

    @staticmethod
    def _build_queries(topic: str, seed_texts: Iterable[str]) -> list[str]:
        base = [topic]
        for text in seed_texts:
            cleaned = re.sub(r"\s+", " ", str(text)).strip()
            if cleaned:
                base.append(cleaned)

        tokens = []
        for entry in base:
            words = [w for w in re.findall(r"[a-zA-Z]+", entry.lower()) if len(w) > 2]
            tokens.extend(words[:6])

        dedup = []
        seen = set()
        for token in tokens:
            if token in seen:
                continue
            seen.add(token)
            dedup.append(token)

        query_pool = [
            topic,
            f"{topic} science",
            f"{topic} abstract background",
            f"{topic} nature",
            "space science",
            "deep ocean",
            "laboratory research",
            "world map timelapse",
        ]
        query_pool.extend(" ".join(dedup[i : i + 3]) for i in range(0, min(len(dedup), 12), 3))

        final = []
        for query in query_pool:
            query = query.strip()
            if query and query not in final:
                final.append(query)
        return final[:10]
