from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import BinaryIO, Any

from PIL import Image, UnidentifiedImageError

from app.core.config import Settings
from app.db.content_repositories import ContentRepository


class MediaValidationError(ValueError):
    pass


class MediaService:
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}
    MAX_IMAGE_BYTES = 20 * 1024 * 1024
    MAX_VIDEO_BYTES = 1024 * 1024 * 1024

    def __init__(self, settings: Settings, contents: ContentRepository) -> None:
        self.root = settings.media_dir.resolve()
        self.contents = contents

    def _safe_absolute(self, relative_path: str) -> Path:
        if Path(relative_path).is_absolute():
            raise MediaValidationError("Media path phải là đường dẫn tương đối.")
        resolved = (self.root / relative_path).resolve()
        if self.root not in resolved.parents:
            raise MediaValidationError("Media path nằm ngoài thư mục media.")
        return resolved

    def resolve_existing(self, relative_path: str) -> Path:
        path = self._safe_absolute(relative_path)
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(relative_path)
        return path

    def save_upload(
        self,
        content_id: str,
        stream: BinaryIO,
        original_name: str,
        content_type: str | None,
        sort_order: int = 0,
    ) -> dict[str, Any]:
        extension = Path(original_name).suffix.lower()
        if extension in self.IMAGE_EXTENSIONS and (content_type or "").startswith("image/"):
            media_type, maximum = "image", self.MAX_IMAGE_BYTES
        elif extension in self.VIDEO_EXTENSIONS and (content_type or "").startswith("video/"):
            media_type, maximum = "video", self.MAX_VIDEO_BYTES
        else:
            raise MediaValidationError("Chỉ hỗ trợ ảnh JPG/PNG/WebP/GIF hoặc video MP4/MOV/WebM/M4V.")

        content = self.contents.get(content_id)
        if not content:
            raise MediaValidationError("Không tìm thấy content.")
        existing_types = {item["media_type"] for item in content["media"]}
        if media_type == "video" and existing_types:
            raise MediaValidationError("Một content chỉ được chứa một video và không trộn video với ảnh.")
        if media_type == "image" and "video" in existing_types:
            raise MediaValidationError("Không thể thêm ảnh vào content đang có video.")

        directory = self._safe_absolute(content_id)
        directory.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}{extension}"
        destination = directory / filename
        temporary = destination.with_suffix(destination.suffix + ".part")
        digest, size = hashlib.sha256(), 0
        try:
            with temporary.open("wb") as target:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > maximum:
                        raise MediaValidationError(f"File vượt giới hạn {maximum // (1024 * 1024)} MB.")
                    digest.update(chunk)
                    target.write(chunk)
            os.replace(temporary, destination)
            thumbnail: str | None = None
            if media_type == "image":
                try:
                    with Image.open(destination) as image:
                        image.verify()
                    thumbnail_path = directory / f"{destination.stem}.thumb.jpg"
                    with Image.open(destination) as image:
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
            record = {
                "media_type": media_type,
                "relative_path": destination.relative_to(self.root).as_posix(),
                "thumbnail_relative_path": thumbnail,
                "original_name": Path(original_name).name[:255],
                "mime_type": content_type or "application/octet-stream",
                "size_bytes": size,
                "sha256": digest.hexdigest(),
                "sort_order": sort_order,
            }
            return self.contents.add_media(content_id, record)
        except Exception:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            for thumb in directory.glob(f"{destination.stem}.thumb.*"):
                thumb.unlink(missing_ok=True)
            raise

    def delete_managed(self, relative_paths: list[str]) -> int:
        deleted = 0
        for relative in relative_paths:
            try:
                path = self._safe_absolute(relative)
                if path.is_file() and not path.is_symlink():
                    path.unlink()
                    deleted += 1
            except (OSError, MediaValidationError):
                continue
        return deleted
