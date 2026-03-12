from __future__ import annotations

from datetime import datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import Settings


class YouTubeUploader:
    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

    def __init__(self, settings: Settings, logger):
        self.settings = settings
        self.logger = logger

    def upload(
        self,
        video_path: Path,
        thumbnail_path: Path,
        title: str,
        description: str,
        tags: list[str],
        publish_at_utc: datetime | None,
    ) -> dict:
        if self.settings.dry_run:
            self.logger.info(
                "dry_run_upload",
                extra={
                    "video_path": str(video_path),
                    "thumbnail_path": str(thumbnail_path),
                    "title": title,
                    "publish_at_utc": publish_at_utc.isoformat() if publish_at_utc else "",
                },
            )
            return {"video_id": "dry_run_video_id", "url": "https://youtube.com/watch?v=dry_run_video_id"}

        youtube = self._build_service()
        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags[:15],
                "categoryId": self.settings.youtube_category_id,
            },
            "status": {
                "privacyStatus": "private" if publish_at_utc else "public",
                "selfDeclaredMadeForKids": False,
            },
        }
        if publish_at_utc:
            body["status"]["publishAt"] = publish_at_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")

        insert_request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=MediaFileUpload(str(video_path), chunksize=-1, resumable=True),
        )

        response = None
        while response is None:
            _, response = insert_request.next_chunk()

        video_id = response["id"]
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumbnail_path)),
        ).execute()

        url = f"https://youtube.com/watch?v={video_id}"
        self.logger.info("upload_complete", extra={"video_id": video_id, "url": url})
        return {"video_id": video_id, "url": url}

    def _build_service(self):
        creds = self._get_credentials()
        return build("youtube", "v3", credentials=creds)

    def _get_credentials(self) -> Credentials:
        token_file = self.settings.youtube_token_file
        credentials_file = self.settings.youtube_credentials_file
        creds = None

        if token_file.exists():
            creds = Credentials.from_authorized_user_file(str(token_file), self.SCOPES)

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not credentials_file.exists():
                raise FileNotFoundError(
                    f"Missing OAuth credentials file: {credentials_file}. "
                    "Create a YouTube OAuth desktop client in Google Cloud and place JSON credentials there."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), self.SCOPES)
            creds = flow.run_local_server(port=0)

        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")
        return creds
