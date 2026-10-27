from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import boto3
from botocore.config import Config

from app.core.config import Settings
from app.core.logging import secret_registry


class InstagramMediaDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class InstagramMediaUrl:
    url: str
    object_key: str
    expires_in: int


class InstagramMediaDelivery:
    """Copies one validated local JPEG to a private R2 bucket and signs a short GET URL."""

    PREFIX = "tinix-instagram-tmp"
    # Stay below the provider's 8 MB ceiling using decimal bytes.
    MAX_IMAGE_BYTES = 8_000_000

    def __init__(self, settings: Settings, client_factory: Callable[..., Any] = boto3.client) -> None:
        self.settings = settings
        self.client_factory = client_factory
        if settings.instagram_r2_secret_access_key:
            secret_registry.add(settings.instagram_r2_secret_access_key)

    @property
    def configured(self) -> bool:
        return all((
            self.settings.instagram_r2_account_id,
            self.settings.instagram_r2_bucket,
            self.settings.instagram_r2_access_key_id,
            self.settings.instagram_r2_secret_access_key,
        ))

    def _client(self) -> Any:
        if not self.configured:
            raise InstagramMediaDeliveryError(
                "Instagram API cần cấu hình Cloudflare R2 trước khi gửi ảnh."
            )
        account_id = self.settings.instagram_r2_account_id
        if not re.fullmatch(r"[a-fA-F0-9]{32}", account_id):
            raise InstagramMediaDeliveryError("Cloudflare R2 Account ID không hợp lệ.")
        return self.client_factory(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=self.settings.instagram_r2_access_key_id,
            aws_secret_access_key=self.settings.instagram_r2_secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )

    @classmethod
    def _validate_image(cls, path: Path, expected_sha256: str, mime_type: str) -> int:
        if path.suffix.lower() not in {".jpg", ".jpeg"} or mime_type.lower() != "image/jpeg":
            raise InstagramMediaDeliveryError("Instagram API hiện chỉ nhận một ảnh JPEG.")
        if path.is_symlink() or not path.is_file():
            raise InstagramMediaDeliveryError("Không tìm thấy file ảnh Instagram trong storage cục bộ.")
        size = path.stat().st_size
        if size <= 0 or size > cls.MAX_IMAGE_BYTES:
            raise InstagramMediaDeliveryError("Ảnh Instagram phải lớn hơn 0 và không vượt 8 MB.")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        if not re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha256) or digest.hexdigest() != expected_sha256.lower():
            raise InstagramMediaDeliveryError("Ảnh Instagram đã thay đổi so với bản đã duyệt.")
        return size

    async def create_url(
        self, path: Path, *, release_id: str, sha256: str, mime_type: str,
    ) -> InstagramMediaUrl:
        return await asyncio.to_thread(
            self._create_url, path, release_id=release_id, sha256=sha256, mime_type=mime_type,
        )

    def _create_url(self, path: Path, *, release_id: str, sha256: str, mime_type: str) -> InstagramMediaUrl:
        size = self._validate_image(path, sha256, mime_type)
        safe_release = re.sub(r"[^A-Za-z0-9_-]", "", release_id)[:80]
        if not safe_release:
            raise InstagramMediaDeliveryError("Release Instagram không hợp lệ.")
        key = f"{self.PREFIX}/{safe_release}/{sha256.lower()}.jpg"
        bucket = self.settings.instagram_r2_bucket
        ttl = self.settings.instagram_r2_url_ttl_seconds
        try:
            client = self._client()
            with path.open("rb") as image:
                client.put_object(
                    Bucket=bucket, Key=key, Body=image, ContentLength=size,
                    ContentType="image/jpeg", CacheControl="private, no-store",
                )
            url = str(client.generate_presigned_url(
                "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=ttl,
            ))
        except InstagramMediaDeliveryError:
            raise
        except Exception as exc:
            raise InstagramMediaDeliveryError(
                "Tinix không tải được ảnh lên Cloudflare R2. Kiểm tra bucket và quyền API token."
            ) from exc
        account_id = self.settings.instagram_r2_account_id.lower()
        host = (urlparse(url).hostname or "").lower()
        if (urlparse(url).scheme != "https" or not (
            host == f"{account_id}.r2.cloudflarestorage.com"
            or host.endswith(f".{account_id}.r2.cloudflarestorage.com")
        )):
            raise InstagramMediaDeliveryError("Cloudflare R2 tạo URL media không hợp lệ.")
        return InstagramMediaUrl(url=url, object_key=key, expires_in=ttl)

    async def delete(self, object_key: str) -> None:
        await asyncio.to_thread(self._delete, object_key)

    def _delete(self, object_key: str) -> None:
        if not self.configured or not object_key.startswith(f"{self.PREFIX}/"):
            return
        try:
            self._client().delete_object(Bucket=self.settings.instagram_r2_bucket, Key=object_key)
        except Exception:
            # The bucket lifecycle rule is the fallback for temporary media cleanup.
            return
