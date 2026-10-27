from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image, UnidentifiedImageError

from app.db.provider_repositories import ProviderConnectionRepository
from app.domain.jobs import JobStatus
from app.services.instagram_accounts import InstagramAccountService, InstagramGraphAPIError, INSTAGRAM_SCOPES
from app.services.instagram_media_delivery import InstagramMediaDelivery, InstagramMediaDeliveryError
from app.services.media import MediaService, MediaValidationError
from app.services.publishers import PublishContext, PublishOutcome, PublishResult, Publisher


class InstagramOfficialPublisher(Publisher):
    platform_id = "instagram"
    provider_id = "instagram"
    publication_transport = "official_api"
    provider_version = "instagram-graph-image-v1"
    selector_version = provider_version
    max_concurrent_jobs = 1
    supported_formats = frozenset({"image"})
    MAX_CAPTION_LENGTH = 2200
    MAX_CONTAINER_POLLS = 60
    MARKER_PREFIX = "ig-photo:"

    def __init__(
        self, connections: ProviderConnectionRepository, instagram_accounts: InstagramAccountService,
        media: MediaService, media_delivery: InstagramMediaDelivery, poll_interval_seconds: float = 2,
    ) -> None:
        self.connections = connections
        self.instagram_accounts = instagram_accounts
        self.media = media
        self.media_delivery = media_delivery
        self.poll_interval_seconds = poll_interval_seconds

    @classmethod
    def validate(cls, payload: dict[str, Any], settings: dict[str, Any]) -> list[str]:
        del settings
        errors: list[str] = []
        if payload.get("content_format") != "image":
            errors.append("Instagram Official API hiện chỉ hỗ trợ một ảnh.")
        media = payload.get("media") or []
        if len(media) != 1 or not isinstance(media[0], dict) or media[0].get("type") != "image":
            errors.append("Instagram Official API cần đúng một ảnh JPEG.")
        else:
            if (Path(str(media[0].get("relative_path") or "")).suffix.lower() not in {".jpg", ".jpeg"}
                    or str(media[0].get("mime_type") or "").lower() != "image/jpeg"):
                errors.append("Instagram Official API hiện chỉ nhận JPEG đúng MIME.")
            try:
                size_bytes = int(media[0].get("size_bytes") or 0)
            except (TypeError, ValueError):
                size_bytes = 0
            if size_bytes <= 0 or size_bytes > 8_000_000:
                errors.append("Ảnh Instagram phải lớn hơn 0 và không vượt 8 MB.")
            if not re.fullmatch(r"[a-fA-F0-9]{64}", str(media[0].get("sha256") or "")):
                errors.append("Ảnh Instagram thiếu mã SHA-256 của bản đã lên lịch.")
        if len(str(payload.get("caption") or "")) > cls.MAX_CAPTION_LENGTH:
            errors.append("Caption Instagram không được vượt quá 2.200 ký tự.")
        return errors

    def _connection(self, account_id: str, connection_id: str | None) -> dict[str, Any] | None:
        if not connection_id:
            return None
        connection = self.connections.get(connection_id)
        if (connection and connection.get("account_id") == account_id
                and connection.get("provider") == self.provider_id
                and connection.get("status") == "connected"):
            return connection
        return None

    @staticmethod
    def _marker(context: PublishContext) -> dict[str, Any] | None:
        raw = str(context.job.get("provider_request_id") or "")
        if not raw.startswith(InstagramOfficialPublisher.MARKER_PREFIX):
            return None
        try:
            value = json.loads(raw[len(InstagramOfficialPublisher.MARKER_PREFIX):])
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    async def _record(self, context: PublishContext, state: dict[str, Any], commit_possible: bool) -> None:
        if context.record_provider_request:
            marker = self.MARKER_PREFIX + json.dumps(state, separators=(",", ":"), sort_keys=True)
            if len(marker) > 500:
                raise ValueError("Instagram recovery marker vượt giới hạn lưu trữ của Tinix.")
            await context.record_provider_request(marker, commit_possible)

    async def _verify(self, connection_id: str, media_id: str) -> tuple[bool, str | None]:
        detail = await self.instagram_accounts.graph_request(
            connection_id, "GET", media_id, params={"fields": "id,media_type,permalink"},
        )
        permalink = str(detail.get("permalink") or "")
        parsed = urlparse(permalink)
        if (str(detail.get("id") or "") != media_id or detail.get("media_type") != "IMAGE"
                or parsed.scheme != "https" or parsed.hostname not in {"instagram.com", "www.instagram.com"}):
            return False, None
        return True, permalink

    async def publish(self, context: PublishContext) -> PublishResult:
        errors = self.validate(context.payload, context.payload.get("platform_settings") or {})
        if errors:
            return PublishResult(PublishOutcome.UNSUPPORTED, " ".join(errors))
        connection = await asyncio.to_thread(
            self._connection, str(context.account["id"]), context.connection_id,
        )
        if not connection:
            return PublishResult(PublishOutcome.LOGIN_REQUIRED, "Account chưa kết nối Instagram Login API.")
        required = set(INSTAGRAM_SCOPES)
        if not required.issubset(set(connection.get("scopes") or [])):
            return PublishResult(
                PublishOutcome.LOGIN_REQUIRED,
                "Kết nối Instagram cần quyền instagram_business_content_publish; hãy kết nối lại và cấp quyền.",
            )
        target_id = str(context.payload.get("target_external_id") or "")
        if target_id != str(connection.get("external_account_id") or ""):
            return PublishResult(PublishOutcome.UNSUPPORTED, "Instagram connection không khớp profile đã chọn.")
        item = (context.payload.get("media") or [])[0]
        try:
            image_path = await asyncio.to_thread(self.media.resolve_existing, str(item.get("relative_path") or ""))
        except (MediaValidationError, OSError) as exc:
            return PublishResult(PublishOutcome.UNSUPPORTED, str(exc))
        try:
            with Image.open(image_path) as image:
                if image.format != "JPEG" or image.width <= 0 or image.height <= 0:
                    return PublishResult(PublishOutcome.UNSUPPORTED, "File ảnh Instagram không phải JPEG hợp lệ.")
                image.verify()
        except (UnidentifiedImageError, OSError) as exc:
            return PublishResult(PublishOutcome.UNSUPPORTED, "File ảnh Instagram không đọc được.")
        if context.job.get("dry_run"):
            if await context.is_cancelled():
                raise asyncio.CancelledError
            return PublishResult(
                PublishOutcome.DRY_RUN_READY,
                "Đã kiểm tra Instagram identity, quyền và JPEG; dry-run chưa xác nhận R2 hoặc tạo container.",
                metadata={"instagram_user_id": target_id, "content_format": "image",
                          "media_delivery_configured": self.media_delivery.configured},
            )
        if not self.media_delivery.configured:
            return PublishResult(
                PublishOutcome.UNSUPPORTED,
                "Instagram API chưa sẵn sàng: cấu hình Cloudflare R2 trong file .env của Tinix.",
            )

        release_id = str(context.payload.get("publication_release_id") or context.job.get("publication_release_id") or context.job["id"])
        state = self._marker(context) or {"v": 1, "release": release_id, "sha": str(item.get("sha256") or "")}
        if state.get("release") != release_id or state.get("sha") != str(item.get("sha256") or ""):
            return PublishResult(PublishOutcome.UNSUPPORTED, "Checkpoint Instagram không khớp media đã duyệt.")
        if state.get("stage") == "publish_possible":
            return PublishResult(
                PublishOutcome.UNKNOWN_RESULT,
                "Instagram có thể đã nhận lệnh publish; cần kiểm tra profile trước khi thao tác tiếp.",
                metadata={"provider_request_id": str(state.get("container") or "")},
            )
        try:
            await self.instagram_accounts.access_token(connection["id"], str(context.account["id"]))
            if await context.is_cancelled():
                raise asyncio.CancelledError
            if not state.get("container"):
                await context.transition(JobStatus.UPLOADING.value, "instagram_media_delivery_started", False)
                media_url = await self.media_delivery.create_url(
                    image_path, release_id=release_id, sha256=str(item.get("sha256") or ""),
                    mime_type=str(item.get("mime_type") or ""),
                )
                response = await self.instagram_accounts.graph_request(
                    connection["id"], "POST", f"{target_id}/media",
                    data={"image_url": media_url.url, "caption": str(context.payload.get("caption") or "")},
                )
                container_id = str(response.get("id") or "")
                if not container_id.isdigit():
                    return PublishResult(PublishOutcome.UNSUPPORTED, "Instagram không trả container ID hợp lệ.")
                state = {**state, "container": container_id, "stage": "container_ready", "key": media_url.object_key}
                await self._record(context, state, False)
            else:
                container_id = str(state["container"])

            finished = False
            for _ in range(self.MAX_CONTAINER_POLLS):
                if await context.is_cancelled():
                    raise asyncio.CancelledError
                status = await self.instagram_accounts.graph_request(
                    connection["id"], "GET", container_id, params={"fields": "status_code,status"},
                )
                status_code = str(status.get("status_code") or "").upper()
                if status_code == "FINISHED":
                    finished = True
                    break
                if status_code in {"ERROR", "EXPIRED"}:
                    return PublishResult(
                        PublishOutcome.UNSUPPORTED,
                        "Instagram không xử lý được ảnh; container hết hạn hoặc lỗi.",
                        metadata={"container_id": container_id},
                    )
                await asyncio.sleep(self.poll_interval_seconds)
            if not finished:
                return PublishResult(
                    PublishOutcome.CHECKPOINT,
                    "Instagram vẫn đang xử lý media container. Hãy kiểm tra trạng thái trước khi gửi lại.",
                    metadata={"container_id": container_id},
                )
            if await context.is_cancelled():
                raise asyncio.CancelledError
            state = {**state, "stage": "publish_possible"}
            await self._record(context, state, True)
            await context.transition(JobStatus.PUBLISHING.value, "instagram_media_publish_started", True)
            published = await self.instagram_accounts.graph_request(
                connection["id"], "POST", f"{target_id}/media_publish",
                data={"creation_id": container_id},
            )
            media_id = str(published.get("id") or "")
            if not media_id.isdigit():
                return PublishResult(
                    PublishOutcome.UNKNOWN_RESULT,
                    "Instagram đã nhận lệnh publish nhưng không trả media ID; cần kiểm tra profile.",
                    metadata={"container_id": container_id},
                )
            await context.transition(JobStatus.VERIFYING.value, "instagram_media_publish_confirmed", True)
            try:
                verified, permalink = await self._verify(connection["id"], media_id)
            except Exception:
                verified, permalink = False, None
            if not verified:
                return PublishResult(
                    PublishOutcome.UNKNOWN_RESULT,
                    "Instagram trả media ID nhưng Tinix chưa xác minh được bài; không tự publish lại.",
                    metadata={"external_id": media_id, "container_id": container_id},
                )
            object_key = str(state.get("key") or "")
            if object_key:
                await self.media_delivery.delete(object_key)
            return PublishResult(
                PublishOutcome.PUBLISHED, "Đã đăng ảnh qua Instagram Official API.", post_url=permalink,
                metadata={"external_id": media_id, "container_id": container_id,
                          "external_account_id": target_id, "provider_version": self.provider_version},
            )
        except asyncio.CancelledError:
            raise
        except InstagramGraphAPIError as exc:
            if state.get("stage") == "publish_possible":
                return PublishResult(
                    PublishOutcome.UNKNOWN_RESULT,
                    "Mất xác nhận sau khi gửi publish tới Instagram; hãy kiểm tra profile trước khi đăng lại.",
                    metadata={"container_id": str(state.get("container") or ""), "graph_code": exc.graph_code},
                )
            if exc.status_code in {401, 403} or exc.graph_code == "190":
                return PublishResult(PublishOutcome.LOGIN_REQUIRED, "Instagram từ chối token hoặc quyền; hãy kết nối lại.")
            return PublishResult(
                PublishOutcome.UNSUPPORTED,
                f"Instagram Graph API từ chối yêu cầu (HTTP {exc.status_code}, mã {exc.graph_code or 'không rõ'}).",
            )
        except (InstagramMediaDeliveryError, RuntimeError, OSError, ValueError) as exc:
            if state.get("stage") == "publish_possible":
                return PublishResult(
                    PublishOutcome.UNKNOWN_RESULT,
                    "Không xác minh được phản hồi sau khi publish; cần kiểm tra profile trước khi đăng lại.",
                    metadata={"container_id": str(state.get("container") or "")},
                )
            return PublishResult(PublishOutcome.UNSUPPORTED, str(exc))
