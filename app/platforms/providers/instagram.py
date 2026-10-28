from __future__ import annotations

import asyncio
import hashlib
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
    supported_formats = frozenset({"image", "carousel"})
    MAX_CAPTION_LENGTH = 2200
    MAX_CONTAINER_POLLS = 60
    MIN_CAROUSEL_ITEMS = 2
    MAX_CAROUSEL_ITEMS = 10
    MARKER_PREFIX = "ig-photo:"
    CAROUSEL_MARKER_VERSION = 2

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
        fmt = payload.get("content_format")
        media = payload.get("media") or []
        if fmt == "image":
            if len(media) != 1:
                errors.append("Instagram Official API cần đúng một ảnh JPEG.")
        elif fmt == "carousel":
            if not cls.MIN_CAROUSEL_ITEMS <= len(media) <= cls.MAX_CAROUSEL_ITEMS:
                errors.append("Carousel Instagram cần từ 2 đến 10 ảnh JPEG.")
        else:
            errors.append("Instagram Official API chỉ hỗ trợ một ảnh hoặc carousel ảnh.")
        for item in media:
            errors.extend(cls._media_errors(item))
        if len(str(payload.get("caption") or "")) > cls.MAX_CAPTION_LENGTH:
            errors.append("Caption Instagram không được vượt quá 2.200 ký tự.")
        return errors

    @staticmethod
    def _media_errors(item: Any) -> list[str]:
        if not isinstance(item, dict) or item.get("type") != "image":
            return ["Instagram Official API chỉ nhận ảnh JPEG."]
        errors: list[str] = []
        if (Path(str(item.get("relative_path") or "")).suffix.lower() not in {".jpg", ".jpeg"}
                or str(item.get("mime_type") or "").lower() != "image/jpeg"):
            errors.append("Instagram Official API hiện chỉ nhận JPEG đúng MIME.")
        try:
            size_bytes = int(item.get("size_bytes") or 0)
        except (TypeError, ValueError):
            size_bytes = 0
        if size_bytes <= 0 or size_bytes > 8_000_000:
            errors.append("Ảnh Instagram phải lớn hơn 0 và không vượt 8 MB.")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", str(item.get("sha256") or "")):
            errors.append("Ảnh Instagram thiếu mã SHA-256 của bản đã lên lịch.")
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

    async def _verify(self, connection_id: str, media_id: str, expected_type: str = "IMAGE") -> tuple[bool, str | None]:
        detail = await self.instagram_accounts.graph_request(
            connection_id, "GET", media_id, params={"fields": "id,media_type,permalink"},
        )
        permalink = str(detail.get("permalink") or "")
        parsed = urlparse(permalink)
        if (str(detail.get("id") or "") != media_id or detail.get("media_type") != expected_type
                or parsed.scheme != "https" or parsed.hostname not in {"instagram.com", "www.instagram.com"}):
            return False, None
        return True, permalink

    async def _container_status(self, connection_id: str, container_id: str, context: PublishContext) -> str:
        """Poll a media container until Instagram reports FINISHED, an error, or the poll budget ends."""
        for _ in range(self.MAX_CONTAINER_POLLS):
            if await context.is_cancelled():
                raise asyncio.CancelledError
            status = await self.instagram_accounts.graph_request(
                connection_id, "GET", container_id, params={"fields": "status_code,status"},
            )
            status_code = str(status.get("status_code") or "").upper()
            if status_code == "FINISHED":
                return "FINISHED"
            if status_code in {"ERROR", "EXPIRED"}:
                return "ERROR"
            await asyncio.sleep(self.poll_interval_seconds)
        return "PENDING"

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
        items = list(context.payload.get("media") or [])
        image_paths: list[Path] = []
        for item in items:
            try:
                image_path = await asyncio.to_thread(self.media.resolve_existing, str(item.get("relative_path") or ""))
            except (MediaValidationError, OSError) as exc:
                return PublishResult(PublishOutcome.UNSUPPORTED, str(exc))
            try:
                with Image.open(image_path) as image:
                    if image.format != "JPEG" or image.width <= 0 or image.height <= 0:
                        return PublishResult(PublishOutcome.UNSUPPORTED, "File ảnh Instagram không phải JPEG hợp lệ.")
                    image.verify()
            except (UnidentifiedImageError, OSError):
                return PublishResult(PublishOutcome.UNSUPPORTED, "File ảnh Instagram không đọc được.")
            image_paths.append(image_path)
        fmt = str(context.payload.get("content_format") or "image")
        if context.job.get("dry_run"):
            if await context.is_cancelled():
                raise asyncio.CancelledError
            return PublishResult(
                PublishOutcome.DRY_RUN_READY,
                "Đã kiểm tra Instagram identity, quyền và JPEG; dry-run chưa xác nhận R2 hoặc tạo container.",
                metadata={"instagram_user_id": target_id, "content_format": fmt,
                          "media_count": len(items), "media_delivery_configured": self.media_delivery.configured},
            )
        if not self.media_delivery.configured:
            return PublishResult(
                PublishOutcome.UNSUPPORTED,
                "Instagram API chưa sẵn sàng: cấu hình Cloudflare R2 trong file .env của Tinix.",
            )
        release_id = str(context.payload.get("publication_release_id") or context.job.get("publication_release_id") or context.job["id"])
        if fmt == "carousel":
            return await self._publish_carousel(context, connection, target_id, items, image_paths, release_id)
        return await self._publish_single(context, connection, target_id, items[0], image_paths[0], release_id)

    async def _publish_single(
        self, context: PublishContext, connection: dict[str, Any], target_id: str,
        item: dict[str, Any], image_path: Path, release_id: str,
    ) -> PublishResult:
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

            status = await self._container_status(connection["id"], container_id, context)
            if status == "ERROR":
                return PublishResult(
                    PublishOutcome.UNSUPPORTED,
                    "Instagram không xử lý được ảnh; container hết hạn hoặc lỗi.",
                    metadata={"container_id": container_id},
                )
            if status == "PENDING":
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
        except (InstagramGraphAPIError, InstagramMediaDeliveryError, RuntimeError, OSError, ValueError) as exc:
            return self._failure_result(state, exc)

    async def _publish_carousel(
        self, context: PublishContext, connection: dict[str, Any], target_id: str,
        items: list[dict[str, Any]], image_paths: list[Path], release_id: str,
    ) -> PublishResult:
        # One digest covers every item, so a checkpoint can only resume the exact approved set in order.
        digest = hashlib.sha256("".join(str(item.get("sha256") or "") for item in items).encode()).hexdigest()
        state = self._marker(context) or {
            "v": self.CAROUSEL_MARKER_VERSION, "release": release_id, "sha": digest,
            "children": [], "container": "", "stage": "children",
        }
        if (state.get("v") != self.CAROUSEL_MARKER_VERSION or state.get("release") != release_id
                or state.get("sha") != digest):
            return PublishResult(PublishOutcome.UNSUPPORTED, "Checkpoint Instagram carousel không khớp media đã duyệt.")
        if state.get("stage") == "publish_possible":
            return PublishResult(
                PublishOutcome.UNKNOWN_RESULT,
                "Instagram có thể đã nhận lệnh publish carousel; cần kiểm tra profile trước khi thao tác tiếp.",
                metadata={"provider_request_id": str(state.get("container") or "")},
            )
        children = [str(child) for child in state.get("children") or []]
        uploaded_keys: list[str] = []
        try:
            await self.instagram_accounts.access_token(connection["id"], str(context.account["id"]))
            if not state.get("container"):
                if not children:
                    await context.transition(JobStatus.UPLOADING.value, "instagram_media_delivery_started", False)
                for index in range(len(children), len(items)):
                    if await context.is_cancelled():
                        raise asyncio.CancelledError
                    item = items[index]
                    media_url = await self.media_delivery.create_url(
                        image_paths[index], release_id=release_id, sha256=str(item.get("sha256") or ""),
                        mime_type=str(item.get("mime_type") or ""),
                    )
                    uploaded_keys.append(media_url.object_key)
                    response = await self.instagram_accounts.graph_request(
                        connection["id"], "POST", f"{target_id}/media",
                        data={"image_url": media_url.url, "is_carousel_item": "true"},
                    )
                    child_id = str(response.get("id") or "")
                    if not child_id.isdigit():
                        return PublishResult(PublishOutcome.UNSUPPORTED, "Instagram không trả container ID cho ảnh carousel.")
                    children.append(child_id)
                    state = {**state, "children": children}
                    await self._record(context, state, False)
                for child_id in children:
                    status = await self._container_status(connection["id"], child_id, context)
                    if status == "ERROR":
                        return PublishResult(
                            PublishOutcome.UNSUPPORTED,
                            "Instagram không xử lý được một ảnh carousel; container hết hạn hoặc lỗi.",
                            metadata={"container_id": child_id},
                        )
                    if status == "PENDING":
                        return PublishResult(
                            PublishOutcome.CHECKPOINT,
                            "Instagram vẫn đang xử lý ảnh carousel. Hãy kiểm tra trạng thái trước khi gửi lại.",
                            metadata={"container_id": child_id},
                        )
                if await context.is_cancelled():
                    raise asyncio.CancelledError
                response = await self.instagram_accounts.graph_request(
                    connection["id"], "POST", f"{target_id}/media",
                    data={"media_type": "CAROUSEL", "children": ",".join(children),
                          "caption": str(context.payload.get("caption") or "")},
                )
                container_id = str(response.get("id") or "")
                if not container_id.isdigit():
                    return PublishResult(PublishOutcome.UNSUPPORTED, "Instagram không trả container ID carousel hợp lệ.")
                state = {**state, "container": container_id, "stage": "container_ready"}
                await self._record(context, state, False)
            else:
                container_id = str(state["container"])

            status = await self._container_status(connection["id"], container_id, context)
            if status == "ERROR":
                return PublishResult(
                    PublishOutcome.UNSUPPORTED,
                    "Instagram không xử lý được carousel; container hết hạn hoặc lỗi.",
                    metadata={"container_id": container_id},
                )
            if status == "PENDING":
                return PublishResult(
                    PublishOutcome.CHECKPOINT,
                    "Instagram vẫn đang xử lý carousel. Hãy kiểm tra trạng thái trước khi gửi lại.",
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
                    "Instagram đã nhận lệnh publish carousel nhưng không trả media ID; cần kiểm tra profile.",
                    metadata={"container_id": container_id},
                )
            await context.transition(JobStatus.VERIFYING.value, "instagram_media_publish_confirmed", True)
            try:
                verified, permalink = await self._verify(connection["id"], media_id, expected_type="CAROUSEL_ALBUM")
            except Exception:
                verified, permalink = False, None
            if not verified:
                return PublishResult(
                    PublishOutcome.UNKNOWN_RESULT,
                    "Instagram trả media ID carousel nhưng Tinix chưa xác minh được bài; không tự publish lại.",
                    metadata={"external_id": media_id, "container_id": container_id},
                )
            for key in uploaded_keys:
                await self.media_delivery.delete(key)
            return PublishResult(
                PublishOutcome.PUBLISHED, "Đã đăng carousel qua Instagram Official API.", post_url=permalink,
                metadata={"external_id": media_id, "container_id": container_id, "children": children,
                          "external_account_id": target_id, "provider_version": self.provider_version},
            )
        except asyncio.CancelledError:
            raise
        except (InstagramGraphAPIError, InstagramMediaDeliveryError, RuntimeError, OSError, ValueError) as exc:
            return self._failure_result(state, exc)

    @staticmethod
    def _failure_result(state: dict[str, Any], exc: Exception) -> PublishResult:
        """Map a provider failure to an outcome; anything after the publish call is unknown, never retried."""
        if isinstance(exc, InstagramGraphAPIError):
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
        if state.get("stage") == "publish_possible":
            return PublishResult(
                PublishOutcome.UNKNOWN_RESULT,
                "Không xác minh được phản hồi sau khi publish; cần kiểm tra profile trước khi đăng lại.",
                metadata={"container_id": str(state.get("container") or "")},
            )
        return PublishResult(PublishOutcome.UNSUPPORTED, str(exc))
