from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Any, BinaryIO

from PIL import Image, UnidentifiedImageError

from app.core.config import Settings
from app.db.content_repositories import ContentRepository
from app.db.media_repositories import MediaAssetRepository
from app.runtime import LocalPathStorage, ManagedStorage


class MediaValidationError(ValueError):
    pass


class MediaService:
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}
    MAX_IMAGE_BYTES = 20 * 1024 * 1024
    MAX_VIDEO_BYTES = 1024 * 1024 * 1024

    def __init__(
        self, settings: Settings, contents: ContentRepository,
        assets: MediaAssetRepository | None = None, storage: ManagedStorage | None = None,
    ) -> None:
        self.storage = storage or LocalPathStorage(settings.media_dir)
        self.root = self.storage.root
        self.contents = contents
        self.assets = assets or MediaAssetRepository(contents.db)

    def _safe_absolute(self, relative_path: str) -> Path:
        try:return self.storage.safe_path(relative_path)
        except ValueError as exc:raise MediaValidationError(str(exc)) from exc

    def resolve_existing(self, relative_path: str) -> Path:
        try:return self.storage.resolve_existing(relative_path)
        except ValueError as exc:raise MediaValidationError(str(exc)) from exc

    def _kind(self, original_name: str, content_type: str | None) -> tuple[str, int, str]:
        extension = Path(original_name).suffix.lower()
        if extension in self.IMAGE_EXTENSIONS and (content_type or "").startswith("image/"):
            return "image", self.MAX_IMAGE_BYTES, extension
        if extension in self.VIDEO_EXTENSIONS and (content_type or "").startswith("video/"):
            return "video", self.MAX_VIDEO_BYTES, extension
        raise MediaValidationError("Chỉ hỗ trợ ảnh JPG/PNG/WebP/GIF hoặc video MP4/MOV/WebM/M4V.")

    def upload_asset(
        self, stream: BinaryIO, original_name: str, content_type: str | None,
        *, alt_text: str | None = None, source: str = "upload",
    ) -> dict[str, Any]:
        media_type, maximum, extension = self._kind(original_name, content_type)
        incoming = self._safe_absolute("_incoming")
        incoming.mkdir(parents=True, exist_ok=True)
        temporary = incoming / f"{uuid.uuid4().hex}{extension}.part"
        digest, size = hashlib.sha256(), 0
        destination: Path | None = None
        thumbnail_path: Path | None = None
        try:
            with temporary.open("wb") as target:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > maximum:
                        raise MediaValidationError(f"File vượt giới hạn {maximum // (1024 * 1024)} MB.")
                    digest.update(chunk); target.write(chunk)
            sha256 = digest.hexdigest()
            existing = self.assets.get_by_sha256(sha256)
            if existing:
                temporary.unlink(missing_ok=True)
                return existing
            library = self._safe_absolute(f"_library/{sha256[:2]}")
            library.mkdir(parents=True, exist_ok=True)
            destination = library / f"{sha256}{extension}"
            os.replace(temporary, destination)
            width = height = None
            thumbnail = None
            if media_type == "image":
                try:
                    with Image.open(destination) as image:
                        image.verify()
                    thumbnail_path = library / f"{sha256}.thumb.jpg"
                    with Image.open(destination) as image:
                        width, height = image.size
                        image.thumbnail((480, 480))
                        if image.mode not in ("RGB", "L"):
                            image = image.convert("RGB")
                        image.save(thumbnail_path, "JPEG", quality=82, optimize=True)
                    thumbnail = thumbnail_path.relative_to(self.root).as_posix()
                except (UnidentifiedImageError, OSError) as exc:
                    raise MediaValidationError("File ảnh không hợp lệ hoặc bị hỏng.") from exc
            else:
                with destination.open("rb") as video:
                    signature = video.read(16)
                if not (b"ftyp" in signature or signature.startswith(b"\x1aE\xdf\xa3")):
                    raise MediaValidationError("File video không có định dạng MP4/MOV/WebM hợp lệ.")
            return self.assets.create({
                "media_type": media_type,
                "relative_path": destination.relative_to(self.root).as_posix(),
                "thumbnail_relative_path": thumbnail,
                "original_name": Path(original_name).name[:255],
                "mime_type": content_type or "application/octet-stream",
                "size_bytes": size, "sha256": sha256, "width": width, "height": height,
                "alt_text": alt_text, "source": source,
            })
        except Exception:
            temporary.unlink(missing_ok=True)
            if destination: destination.unlink(missing_ok=True)
            if thumbnail_path: thumbnail_path.unlink(missing_ok=True)
            raise

    def attach_asset(self, content_id: str, asset_id: str, sort_order: int = 0, alt_text: str | None = None) -> dict[str, Any]:
        try:
            self.assets.attach(asset_id, content_id, sort_order, alt_text)
        except (KeyError, ValueError) as exc:
            raise MediaValidationError(str(exc)) from exc
        return self.contents.get(content_id)

    def save_upload(
        self, content_id: str, stream: BinaryIO, original_name: str,
        content_type: str | None, sort_order: int = 0,
    ) -> dict[str, Any]:
        if not self.contents.get(content_id):
            raise MediaValidationError("Không tìm thấy content.")
        asset = self.upload_asset(stream, original_name, content_type)
        return self.attach_asset(content_id, asset["id"], sort_order)

    def delete_managed(self, relative_paths: list[str]) -> int:
        deleted = 0
        for relative in relative_paths:
            try:
                path = self._safe_absolute(relative)
                if path.is_file() and not path.is_symlink():
                    path.unlink(); deleted += 1
            except (OSError, MediaValidationError):
                continue
        return deleted
