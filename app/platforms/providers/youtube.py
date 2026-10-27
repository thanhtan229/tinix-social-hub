from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.db.provider_repositories import ProviderConnectionRepository
from app.domain.jobs import JobStatus
from app.services.media import MediaService, MediaValidationError
from app.services.provider_accounts import ProviderAccountService
from app.services.publishers import PublishContext, PublishOutcome, PublishResult, Publisher


class YouTubeOfficialPublisher(Publisher):
    """YouTube Data API v3 publisher using a resumable upload session."""

    platform_id = "youtube"
    provider_id = "youtube"
    publication_transport = "official_api"
    provider_version = "youtube-data-v3"
    selector_version = provider_version
    max_concurrent_jobs = 2
    supported_formats = frozenset({"video", "short"})
    initiate_url = "https://www.googleapis.com/upload/youtube/v3/videos"
    verify_url = "https://www.googleapis.com/youtube/v3/videos"

    def __init__(
        self,
        settings: Settings,
        connections: ProviderConnectionRepository,
        provider_accounts: ProviderAccountService,
        media: MediaService,
    ) -> None:
        self.settings = settings
        self.connections = connections
        self.provider_accounts = provider_accounts
        self.media = media

    def _connection(self, account_id: str, connection_id: str | None = None) -> dict[str, Any] | None:
        if connection_id:
            connection = self.connections.get(connection_id)
            if (
                connection and connection.get("account_id") == account_id
                and connection.get("provider") == "youtube" and connection.get("status") == "connected"
            ):
                return connection
            return None
        return next((item for item in self.connections.list(account_id=account_id, transport="official_api")
                     if item.get("provider") == "youtube" and item.get("status") == "connected"), None)

    @staticmethod
    def _validate(payload: dict[str, Any]) -> tuple[Path | None, list[str]]:
        errors: list[str] = []
        if payload.get("content_format") not in {"video", "short"}:
            errors.append("YouTube API chỉ hỗ trợ định dạng video hoặc short.")
        media = payload.get("media") or []
        videos = [item for item in media if item.get("type") == "video"]
        if len(media) != 1 or len(videos) != 1:
            errors.append("YouTube API yêu cầu đúng một file video.")
        title = str(payload.get("title") or "").strip()
        if not title:
            errors.append("Video YouTube cần có tiêu đề.")
        if len(title) > 100:
            errors.append("Tiêu đề YouTube không được vượt quá 100 ký tự.")
        platform_settings = payload.get("platform_settings") or {}
        privacy = str(platform_settings.get("privacy_status") or platform_settings.get("privacy") or "private")
        if privacy not in {"private", "unlisted", "public"}:
            errors.append("privacy_status phải là private, unlisted hoặc public.")
        return (Path(videos[0]["relative_path"]) if videos else None), errors

    @staticmethod
    async def _file_chunks(path: Path, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        handle = await asyncio.to_thread(path.open, "rb")
        try:
            while True:
                chunk = await asyncio.to_thread(handle.read, chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    @staticmethod
    def _safe_upload_url(value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.hostname != "www.googleapis.com":
            raise RuntimeError("YouTube trả về upload URL không hợp lệ.")
        return value

    async def publish(self, context: PublishContext) -> PublishResult:
        relative, errors = self._validate(context.payload)
        if errors:
            return PublishResult(PublishOutcome.UNSUPPORTED, " ".join(errors))
        connection = await asyncio.to_thread(
            self._connection, str(context.account["id"]), context.connection_id,
        )
        if not connection:
            return PublishResult(PublishOutcome.LOGIN_REQUIRED, "Account chưa kết nối YouTube API.")
        scopes = set(connection.get("scopes") or [])
        required_scopes = {
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
        }
        if not required_scopes.issubset(scopes):
            return PublishResult(
                PublishOutcome.LOGIN_REQUIRED,
                "Kết nối YouTube API thiếu quyền upload hoặc đọc để xác minh bài đăng; hãy cấp quyền lại.",
            )
        target_external_id = str(context.payload.get("target_external_id") or "").strip()
        if target_external_id and connection.get("external_account_id") != target_external_id:
            return PublishResult(
                PublishOutcome.UNSUPPORTED,
                "Kết nối YouTube API không khớp channel đích đã chọn.",
            )
        try:
            from app.services.media import resolve_publish_media
            path = await asyncio.to_thread(resolve_publish_media, self.media, context.payload["media"][0])
        except MediaValidationError as exc:
            return PublishResult(PublishOutcome.UNSUPPORTED, str(exc))

        await context.transition(JobStatus.UPLOADING.value, "youtube_api_payload_validated", False)
        if context.job.get("dry_run"):
            await context.transition(JobStatus.PUBLISHING.value, "youtube_api_dry_run_ready", False)
            return PublishResult(
                PublishOutcome.DRY_RUN_READY,
                "YouTube API dry-run hợp lệ; chưa tạo upload session và chưa gửi video.",
                metadata={"provider_version": self.provider_version, "size_bytes": path.stat().st_size},
            )
        if await context.is_cancelled():
            raise asyncio.CancelledError

        try:
            token = await self.provider_accounts.access_token(connection["id"])
        except (KeyError, RuntimeError):
            return PublishResult(PublishOutcome.LOGIN_REQUIRED, "Kết nối YouTube hết hạn hoặc cần cấp quyền lại.")

        settings = context.payload.get("platform_settings") or {}
        description = "\n\n".join(part for part in (
            str(context.payload.get("caption") or "").strip(),
            " ".join(context.payload.get("hashtags") or []),
        ) if part).strip()
        body = {
            "snippet": {
                "title": str(context.payload.get("title") or "").strip(),
                "description": description,
                "categoryId": str(settings.get("category_id") or "22"),
            },
            "status": {
                "privacyStatus": str(settings.get("privacy_status") or settings.get("privacy") or "private"),
                "selfDeclaredMadeForKids": bool(settings.get("made_for_kids", False)),
            },
        }
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Upload-Content-Length": str(path.stat().st_size),
            "X-Upload-Content-Type": mime_type,
            "Content-Type": "application/json; charset=UTF-8",
        }
        async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
            try:
                initiated = await client.post(
                    self.initiate_url,
                    params={"uploadType": "resumable", "part": "snippet,status", "notifySubscribers": "false"},
                    headers=headers,
                    json=body,
                )
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Không thể tạo YouTube upload session: {exc}") from exc
            if initiated.status_code in {401, 403}:
                await asyncio.to_thread(
                    self.connections.set_status, connection["id"], "reauth_required",
                    error_code=f"youtube_{initiated.status_code}", error_message=initiated.text,
                )
                return PublishResult(PublishOutcome.LOGIN_REQUIRED, "YouTube từ chối quyền truy cập; cần kết nối lại.")
            initiated.raise_for_status()
            upload_url = self._safe_upload_url(initiated.headers.get("Location", ""))
            request_id = initiated.headers.get("X-GUploader-UploadID") or upload_url.rsplit("upload_id=", 1)[-1]
            if context.record_provider_request:
                await context.record_provider_request(request_id, False)

            await context.transition(JobStatus.PUBLISHING.value, "youtube_upload_session_created", False)
            if await context.is_cancelled():
                raise asyncio.CancelledError
            await context.transition(JobStatus.VERIFYING.value, "youtube_upload_started", True)
            if context.record_provider_request:
                await context.record_provider_request(request_id, True)
            try:
                uploaded = await client.put(
                    upload_url,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": mime_type,
                             "Content-Length": str(path.stat().st_size)},
                    content=self._file_chunks(path),
                )
            except httpx.HTTPError:
                return PublishResult(
                    PublishOutcome.UNKNOWN_RESULT,
                    "Mất kết nối sau khi bắt đầu upload; cần kiểm tra YouTube Studio trước khi xử lý tiếp.",
                    metadata={"provider_request_id": request_id, "provider_version": self.provider_version},
                )
            if uploaded.status_code == 308 or uploaded.status_code >= 500:
                return PublishResult(
                    PublishOutcome.UNKNOWN_RESULT,
                    "YouTube chưa xác nhận kết quả upload; không tự động đăng lại để tránh trùng video.",
                    metadata={"provider_request_id": request_id, "provider_version": self.provider_version},
                )
            uploaded.raise_for_status()
            video_id = str(uploaded.json().get("id") or "").strip()
            if not video_id:
                return PublishResult(PublishOutcome.UNKNOWN_RESULT, "YouTube không trả về video id.")
            verified = await client.get(
                self.verify_url,
                params={"part": "id,status", "id": video_id},
                headers={"Authorization": f"Bearer {token}"},
            )
            if verified.status_code >= 500:
                return PublishResult(
                    PublishOutcome.UNKNOWN_RESULT,
                    "Video đã được gửi nhưng bước xác minh YouTube tạm thời thất bại.",
                    metadata={"external_id": video_id, "provider_request_id": request_id},
                )
            verified.raise_for_status()
            if not (verified.json().get("items") or []):
                return PublishResult(
                    PublishOutcome.UNKNOWN_RESULT,
                    "YouTube đã nhận upload nhưng chưa nhìn thấy video khi xác minh.",
                    metadata={"external_id": video_id, "provider_request_id": request_id},
                )
        return PublishResult(
            PublishOutcome.PUBLISHED,
            "Đã đăng video qua YouTube Data API.",
            post_url=f"https://www.youtube.com/watch?v={video_id}",
            metadata={
                "external_id": video_id,
                "external_account_id": connection.get("external_account_id"),
                "provider_request_id": request_id,
                "provider_version": self.provider_version,
            },
        )
