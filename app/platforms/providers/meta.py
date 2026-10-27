from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.services.publishers import PublishContext, PublishOutcome, PublishResult, Publisher


class MetaPagePublisher(Publisher):
    """Facebook Page text/photo album/video/Reel publisher using a frozen Page binding."""

    platform_id = "facebook"
    provider_id = "meta"
    publication_transport = "official_api"
    provider_version = "graph-api-configured"
    selector_version = "meta-page-text-v1"
    max_concurrent_jobs = 1
    supported_formats = frozenset({"post", "photo", "multi_photo", "video", "reel"})

    def __init__(self, meta_accounts: Any, target_connections: Any, media: Any = None) -> None:
        self.meta_accounts = meta_accounts
        self.target_connections = target_connections
        self.media = media

    @classmethod
    def selector_version_for(cls, content_format: str) -> str:
        return {
            "photo": "meta-page-photo-v1",
            "multi_photo": "meta-page-photo-album-v1",
            "video": "meta-page-video-v1",
            "reel": "meta-page-reel-v1",
        }.get(content_format, cls.selector_version)

    @staticmethod
    def validate(payload: dict[str, Any], settings: dict[str, Any]) -> list[str]:
        del settings
        content_format = payload.get("content_format", "post")
        caption = str(payload.get("caption") or "")
        media = payload.get("media") or []
        if content_format == "post":
            errors: list[str] = []
            if not caption.strip():
                errors.append("Bài Facebook API cần có nội dung văn bản.")
            if len(caption) > 63_000:
                errors.append("Nội dung bài Facebook vượt giới hạn cho phép.")
            if media:
                errors.append("Bài chữ Facebook Page API không nhận media; hãy chọn định dạng Ảnh Facebook, Nhiều ảnh Facebook, Video Page thường hoặc Reel.")
            return errors
        if content_format in {"photo", "multi_photo"}:
            minimum, maximum = (1, 1) if content_format == "photo" else (2, 10)
            if not minimum <= len(media) <= maximum or any(item.get("type") != "image" for item in media):
                if content_format == "photo":
                    return ["Bài ảnh Facebook API cần đúng một file ảnh."]
                return ["Bài nhiều ảnh Facebook API cần từ 2 đến 10 file ảnh."]
            mime_by_extension = {
                ".jpg": {"image/jpeg"}, ".jpeg": {"image/jpeg"},
                ".png": {"image/png"}, ".bmp": {"image/bmp", "image/x-ms-bmp"},
                ".gif": {"image/gif"}, ".tif": {"image/tiff"}, ".tiff": {"image/tiff"},
            }
            for index, item in enumerate(media, 1):
                extension = Path(str(item.get("relative_path") or "")).suffix.lower()
                mime = str(item.get("mime_type") or "").lower()
                if extension not in mime_by_extension or mime not in mime_by_extension[extension]:
                    return [f"Ảnh {index}: Facebook Page API chỉ nhận JPEG, PNG, BMP, GIF hoặc TIFF đúng MIME."]
                try:
                    size = int(item.get("size_bytes") or 0)
                except (TypeError, ValueError):
                    size = 0
                if size <= 0 or size > 10 * 1024 * 1024:
                    return [f"Ảnh {index}: cần có kích thước hợp lệ và không vượt 10 MB."]
                if not re.fullmatch(r"[a-fA-F0-9]{64}", str(item.get("sha256") or "")):
                    return [f"Ảnh {index}: thiếu mã SHA-256 của bản đã lên lịch."]
            if len(caption) > 63_206:
                return ["Nội dung bài ảnh Facebook vượt giới hạn Tinix."]
            return []
        if content_format == "video":
            if len(media) != 1 or media[0].get("type") != "video":
                return ["Video Page thường cần đúng một file video MP4."]
            item = media[0]
            extension = Path(str(item.get("relative_path") or "")).suffix.lower()
            try:
                size = int(item.get("size_bytes") or 0)
            except (TypeError, ValueError):
                size = 0
            if extension != ".mp4" or str(item.get("mime_type") or "").lower() != "video/mp4":
                return ["Video Page thường qua API hiện chỉ nhận MP4."]
            if size <= 0:
                return ["Video Page thường thiếu kích thước file hợp lệ."]
            if not re.fullmatch(r"[a-fA-F0-9]{64}", str(item.get("sha256") or "")):
                return ["Video Page thường thiếu mã SHA-256 của bản đã lên lịch."]
            if len(caption) > 63_206:
                return ["Nội dung Video Page thường vượt giới hạn Tinix."]
            return []
        if content_format != "reel":
            return ["Facebook Page API chưa hỗ trợ định dạng này."]
        if len(media) != 1 or media[0].get("type") != "video":
            return ["Facebook Reel cần đúng một file video."]
        item = media[0]
        extension = Path(str(item.get("relative_path") or "")).suffix.lower()
        if extension not in {".mp4", ".mov", ".m4v"}:
            return ["Facebook Reel qua API chỉ nhận file MP4, MOV hoặc M4V."]
        try:
            size = int(item.get("size_bytes") or 0)
        except (TypeError, ValueError):
            size = 0
        if size <= 0 or size > 1024 * 1024 * 1024:
            return ["File Reel thiếu kích thước hợp lệ hoặc vượt giới hạn media của Tinix."]
        if not re.fullmatch(r"[a-fA-F0-9]{64}", str(item.get("sha256") or "")):
            return ["File Reel thiếu mã SHA-256 của bản đã lên lịch."]
        if len(caption) > 63_000:
            return ["Nội dung Reel vượt giới hạn văn bản của Facebook."]
        return []

    def _binding(self, context: PublishContext) -> dict[str, Any]:
        binding_id = context.payload.get("provider_target_binding_id")
        binding = self.target_connections.get(str(binding_id)) if binding_id else None
        if (not binding or binding.get("status") != "connected"
                or binding.get("connection_id") != context.connection_id
                or binding.get("target_id") != context.payload.get("target_id")
                or binding.get("external_target_id") != context.payload.get("provider_target_external_id")):
            raise RuntimeError("Meta Page binding không còn khớp với Page đã chọn; hãy đồng bộ quyền API.")
        return binding

    async def _reel_file(self, item: dict[str, Any]) -> tuple[Path, int]:
        if not self.media:
            raise RuntimeError("Meta Reel cần MediaService để đọc file đã được quản lý an toàn.")
        path = await asyncio.to_thread(self.media.resolve_existing, str(item["relative_path"]))
        size = int(item["size_bytes"])
        if not path.is_file() or path.is_symlink() or path.stat().st_size != size:
            raise RuntimeError("File Reel đã thay đổi hoặc không còn tồn tại sau khi lên lịch.")
        digest = await asyncio.to_thread(self._sha256, path)
        if digest.lower() != str(item["sha256"]).lower():
            raise RuntimeError("Nội dung file Reel đã đổi sau khi lên lịch; hãy tạo release mới.")
        await asyncio.to_thread(self._validate_reel_file, path)
        return path, size

    async def _photo_path(self, item: dict[str, Any]) -> Path:
        if not self.media:
            raise RuntimeError("Ảnh Facebook API cần MediaService để đọc file đã được quản lý an toàn.")
        path = await asyncio.to_thread(self.media.resolve_existing, str(item["relative_path"]))
        size = int(item["size_bytes"])
        if not path.is_file() or path.is_symlink() or path.stat().st_size != size:
            raise RuntimeError("File ảnh đã thay đổi hoặc không còn tồn tại sau khi lên lịch.")
        if await asyncio.to_thread(self._sha256, path) != str(item["sha256"]).lower():
            raise RuntimeError("Nội dung ảnh đã đổi sau khi lên lịch; hãy tạo release mới.")
        return path

    async def _photo_file(self, item: dict[str, Any]) -> tuple[Path, bytes]:
        path = await self._photo_path(item)
        size = int(item["size_bytes"])
        file_bytes = await asyncio.to_thread(path.read_bytes)
        if len(file_bytes) != size or hashlib.sha256(file_bytes).hexdigest() != str(item["sha256"]).lower():
            raise RuntimeError("Ảnh thay đổi trong lúc chuẩn bị upload; chưa gửi request tới Meta.")
        return path, file_bytes

    async def _page_video_file(self, item: dict[str, Any]) -> tuple[Path, int]:
        if not self.media:
            raise RuntimeError("Video Facebook API cần MediaService để đọc file đã được quản lý an toàn.")
        path = await asyncio.to_thread(self.media.resolve_existing, str(item["relative_path"]))
        size = int(item["size_bytes"])
        if not path.is_file() or path.is_symlink() or path.stat().st_size != size:
            raise RuntimeError("File video Page đã thay đổi hoặc không còn tồn tại sau khi lên lịch.")
        if await asyncio.to_thread(self._sha256, path) != str(item["sha256"]).lower():
            raise RuntimeError("Nội dung video Page đã đổi sau khi lên lịch; hãy tạo release mới.")
        await asyncio.to_thread(self._validate_page_video_file, path)
        return path, size

    @staticmethod
    def _page_video_marker(*, page_id: str, size: int, sha256: str, phase: str,
                           pending: bool = False, session_id: str | None = None,
                           start_offset: int | None = None, end_offset: int | None = None,
                           video_id: str | None = None) -> str:
        marker = {"kind": "page_video", "page_id": page_id, "size": size,
                  "sha256": sha256.lower(), "phase": phase, "pending": pending}
        if session_id:
            marker["session_id"] = session_id
        if start_offset is not None:
            marker["start_offset"] = start_offset
        if end_offset is not None:
            marker["end_offset"] = end_offset
        if video_id:
            marker["video_id"] = video_id
        return json.dumps(marker, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _validate_reel_file(path: Path) -> None:
        ffprobe = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
        if not ffprobe:
            raise RuntimeError("Tinix cần ffprobe (FFmpeg) để kiểm tra thông số Reel trước khi upload.")
        try:
            probe = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate:stream_side_data=rotation:format=duration",
                 "-of", "json", str(path)],
                capture_output=True, text=True, timeout=30, check=False,
            )
            if probe.returncode != 0:
                raise ValueError
            metadata = json.loads(probe.stdout)
            stream = next(item for item in metadata.get("streams", []) if item.get("width") and item.get("height"))
            width, height = int(stream["width"]), int(stream["height"])
            duration = float((metadata.get("format") or {}).get("duration") or 0)
            rotation = float(next((item.get("rotation") for item in stream.get("side_data_list", [])
                                   if item.get("rotation") is not None), 0))
            if int(abs(rotation)) % 180 == 90:
                width, height = height, width
            fps = 0.0
            for key in ("avg_frame_rate", "r_frame_rate"):
                try:
                    candidate_fps = float(Fraction(str(stream.get(key) or "0/1")))
                except (ValueError, ZeroDivisionError):
                    continue
                if candidate_fps > 0:
                    fps = candidate_fps
                    break
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError, StopIteration, json.JSONDecodeError, ZeroDivisionError) as exc:
            raise RuntimeError("Tinix không đọc được thông số video Reel; hãy kiểm tra file MP4/MOV.") from exc
        errors = []
        if abs(width / height - 9 / 16) > 0.01:
            errors.append("tỷ lệ cần gần 9:16")
        if width < 540 or height < 960:
            errors.append("độ phân giải tối thiểu 540×960")
        if fps < 23:
            errors.append("tốc độ hình tối thiểu 23 fps")
        if duration < 4 or duration > 60:
            errors.append("thời lượng từ 4 đến 60 giây")
        if errors:
            raise RuntimeError("Video chưa đạt điều kiện Reel của Meta: " + "; ".join(errors) + ".")

    @staticmethod
    def _validate_page_video_file(path: Path) -> None:
        ffprobe = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
        if not ffprobe:
            raise RuntimeError("Tinix cần ffprobe (FFmpeg) để xác nhận file video MP4 trước khi upload.")
        try:
            probe = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height:format=format_name,duration",
                 "-of", "json", str(path)],
                capture_output=True, text=True, timeout=30, check=False,
            )
            if probe.returncode != 0:
                raise ValueError
            metadata = json.loads(probe.stdout)
            stream = next(item for item in metadata.get("streams", [])
                          if int(item.get("width") or 0) > 0 and int(item.get("height") or 0) > 0)
            formats = set(str((metadata.get("format") or {}).get("format_name") or "").split(","))
            duration = float((metadata.get("format") or {}).get("duration") or 0)
            if "mp4" not in formats or duration <= 0:
                raise ValueError
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError,
                StopIteration, json.JSONDecodeError) as exc:
            raise RuntimeError("Tinix không đọc được video MP4; hãy kiểm tra file trước khi lên lịch.") from exc

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    async def publish(self, context: PublishContext) -> PublishResult:
        errors = self.validate(context.payload, context.payload.get("platform_settings") or {})
        if errors:
            return PublishResult(PublishOutcome.UNSUPPORTED, " ".join(errors))
        content_format = context.payload.get("content_format", "post")
        try:
            binding = self._binding(context)
        except (RuntimeError, KeyError) as exc:
            return PublishResult(PublishOutcome.LOGIN_REQUIRED, str(exc))
        if not self.meta_accounts.can_publish(binding.get("tasks") or []):
            return PublishResult(PublishOutcome.UNSUPPORTED, "Meta account chưa có Page task cho phép tạo nội dung.")

        item = None
        local_file = None
        file_size = 0
        photo_bytes = None
        photo_paths: list[Path] = []
        if content_format in {"reel", "video"}:
            item = (context.payload.get("media") or [])[0]
            try:
                local_file, file_size = (await self._reel_file(item) if content_format == "reel"
                                         else await self._page_video_file(item))
            except (OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
                return PublishResult(PublishOutcome.UNSUPPORTED, str(exc))
        elif content_format == "photo":
            item = (context.payload.get("media") or [])[0]
            try:
                local_file, photo_bytes = await self._photo_file(item)
            except (OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
                return PublishResult(PublishOutcome.UNSUPPORTED, str(exc))
        elif content_format == "multi_photo":
            try:
                photo_paths = [await self._photo_path(media_item)
                               for media_item in context.payload.get("media") or []]
            except (OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
                return PublishResult(PublishOutcome.UNSUPPORTED, str(exc))

        if context.job.get("dry_run"):
            if await context.is_cancelled():
                raise asyncio.CancelledError
            label = {"photo": "ảnh", "multi_photo": "album ảnh", "video": "video Page thường",
                     "reel": "Reel"}.get(content_format, "bài văn bản")
            return PublishResult(
                PublishOutcome.DRY_RUN_READY,
                f"Đã kiểm tra Page binding, quyền đăng đã lưu và {label}; chưa gửi nội dung lên Facebook.",
                metadata={"page_id": binding["external_target_id"], "content_format": content_format},
            )
        if await context.is_cancelled():
            raise asyncio.CancelledError
        if content_format == "reel":
            assert item is not None and local_file is not None
            return await self._publish_reel(context, binding, item, local_file, file_size)
        if content_format == "photo":
            assert item is not None and local_file is not None and photo_bytes is not None
            return await self._publish_photo(context, binding, item, local_file, photo_bytes)
        if content_format == "multi_photo":
            return await self._publish_photo_album(context, binding, context.payload.get("media") or [], photo_paths)
        if content_format == "video":
            assert item is not None and local_file is not None
            return await self._publish_page_video(context, binding, item, local_file, file_size)
        return await self._publish_text(context, binding)

    async def _verify_photo(self, context: PublishContext, binding: dict[str, Any], photo_id: str,
                            post_id: str | None = None) -> tuple[bool, str | None]:
        if not photo_id.isdigit():
            return False, None
        target_id = binding["external_target_id"]
        detail = await self.meta_accounts.graph_request(
            context.connection_id, binding["id"], "GET", photo_id,
            params={"fields": "id,from,link"},
        )
        owner_id = str((detail.get("from") or {}).get("id") or "")
        if str(detail.get("id") or "") != photo_id or owner_id != target_id:
            return False, None
        post_url = detail.get("link")
        if post_id and re.fullmatch(r"\d+(?:_\d+)?", post_id):
            try:
                post = await self.meta_accounts.graph_request(
                    context.connection_id, binding["id"], "GET", post_id,
                    params={"fields": "id,from,permalink_url"},
                )
                post_owner = str((post.get("from") or {}).get("id") or "")
                if str(post.get("id") or "") == post_id and post_owner == target_id:
                    post_url = post.get("permalink_url") or post_url
            except Exception:
                pass
        return True, post_url

    @staticmethod
    def _photo_album_snapshot(items: list[dict[str, Any]]) -> str:
        ordered_hashes = [str(item.get("sha256") or "").lower() for item in items]
        return hashlib.sha256(json.dumps(ordered_hashes, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _photo_album_marker(state: dict[str, Any]) -> str:
        marker = json.dumps(state, separators=(",", ":"), sort_keys=True)
        if len(marker) > 500:
            raise ValueError("Meta photo-album recovery marker exceeds the durable provider-request limit.")
        return marker

    async def _verify_photo_album_post(
        self, context: PublishContext, binding: dict[str, Any], post_id: str,
    ) -> tuple[bool, str | None]:
        if not re.fullmatch(r"\d+(?:_\d+)?", post_id):
            return False, None
        detail = await self.meta_accounts.graph_request(
            context.connection_id, binding["id"], "GET", post_id,
            params={"fields": "id,from,permalink_url"},
        )
        owner_id = str((detail.get("from") or {}).get("id") or "")
        if str(detail.get("id") or "") != post_id or owner_id != str(binding["external_target_id"]):
            return False, None
        return True, detail.get("permalink_url")

    async def _publish_photo_album(
        self, context: PublishContext, binding: dict[str, Any],
        items: list[dict[str, Any]], paths: list[Path],
    ) -> PublishResult:
        marker_text = str(context.job.get("provider_request_id") or "")
        page_id = str(binding["external_target_id"])
        snapshot = self._photo_album_snapshot(items)

        def unknown(message: str, external_id: str | None = None) -> PublishResult:
            return PublishResult(
                PublishOutcome.UNKNOWN_RESULT, message,
                metadata={"provider_request_id": marker_text[:500], "page_id": page_id,
                          "content_format": "multi_photo",
                          **({"external_id": external_id} if external_id else {})},
            )

        if marker_text:
            try:
                state = json.loads(marker_text)
                ids = state.get("ids")
                next_index = state.get("n")
                pending_index = state.get("u")
                if (state.get("k") != "page_photo_album" or state.get("p") != page_id
                        or state.get("s") != snapshot or not isinstance(ids, list)
                        or any(not isinstance(value, str) or not value.isdigit() for value in ids)
                        or len(ids) > len(items) or len(set(ids)) != len(ids)
                        or type(next_index) is not int or next_index != len(ids)):
                    raise ValueError("Marker không khớp với snapshot/Page hoặc tiến độ.")
            except (ValueError, TypeError, json.JSONDecodeError, AttributeError):
                return unknown("Không thể khôi phục an toàn tiến độ album ảnh; cần đối soát thủ công, không upload lại.")
            if pending_index is not None:
                return unknown("Meta có thể đã nhận một ảnh nhưng Tinix chưa lưu được photo ID; không upload lại.")
            if context.job.get("provider_request_commit_possible"):
                post_id = str(state.get("post") or "")
                if state.get("ph") == "published" and post_id:
                    try:
                        verified, post_url = await self._verify_photo_album_post(context, binding, post_id)
                    except Exception:
                        verified, post_url = False, None
                    if verified:
                        return PublishResult(
                            PublishOutcome.PUBLISHED, "Bài nhiều ảnh Facebook đã được xác minh sau khi khôi phục.",
                            post_url=post_url,
                            metadata={"external_id": post_id, "post_id": post_id, "photo_ids": ids,
                                      "page_id": page_id, "content_format": "multi_photo",
                                      "provider_request_id": marker_text},
                        )
                return unknown("Meta có thể đã nhận bài nhiều ảnh nhưng Tinix chưa xác minh được; không tự đăng lại.",
                               str(state.get("post") or "") or None)
            if state.get("ph") not in {"uploading", "ready"}:
                return unknown("Trạng thái album Meta không thể tiếp tục an toàn; cần đối soát thủ công.")
            if state.get("ph") == "ready" and len(ids) != len(items):
                return unknown("Marker album thiếu ảnh đã upload; không tạo bài thiếu ảnh.")
        else:
            state = {"k": "page_photo_album", "p": page_id, "s": snapshot,
                     "ids": [], "n": 0, "u": None, "ph": "uploading", "post": None}

        async def persist(*, commit_possible: bool) -> bool:
            nonlocal marker_text
            try:
                marker_text = self._photo_album_marker(state)
            except ValueError:
                return False
            if context.record_provider_request:
                await context.record_provider_request(marker_text, commit_possible)
            return True

        try:
            first_upload_index = int(state["n"])
            for index in range(first_upload_index, len(items)):
                if await context.is_cancelled():
                    raise asyncio.CancelledError
                item = items[index]
                file_bytes = await asyncio.to_thread(paths[index].read_bytes)
                if (len(file_bytes) != int(item["size_bytes"])
                        or hashlib.sha256(file_bytes).hexdigest() != str(item["sha256"]).lower()):
                    return PublishResult(PublishOutcome.UNSUPPORTED,
                                         f"Ảnh {index + 1} đổi trong lúc chuẩn bị upload; chưa gửi request tới Meta.")
                if index == first_upload_index:
                    await context.transition("uploading", "meta_photo_album_upload_started", False)
                state["u"] = index
                if not await persist(commit_possible=False):
                    return unknown("Không thể lưu checkpoint album; chưa tiếp tục upload ảnh.")
                created = await self.meta_accounts.publish_local_photo(
                    context.connection_id, binding["id"], page_id, paths[index].name,
                    str(item["mime_type"]), file_bytes, "", published=False,
                )
                photo_id = str(created.get("id") or "")
                if not photo_id.isdigit() or photo_id in state["ids"]:
                    return unknown(f"Meta không trả photo ID hợp lệ cho ảnh {index + 1}; không upload lại.")
                state["ids"].append(photo_id)
                state["n"] = index + 1
                state["u"] = None
                if not await persist(commit_possible=False):
                    return unknown("Meta đã nhận một ảnh nhưng checkpoint không vừa giới hạn lưu; không tiếp tục album.")

            if len(state["ids"]) != len(items):
                return unknown("Không có đủ ảnh đã upload để tạo bài; không đăng album thiếu ảnh.")
            state["ph"] = "ready"
            if not await persist(commit_possible=False):
                return unknown("Không thể lưu checkpoint trước khi tạo bài; chưa gửi lệnh publish.")
            if await context.is_cancelled():
                raise asyncio.CancelledError

            state["ph"] = "publishing"
            await context.transition("publishing", "meta_photo_album_publish_started", False)
            await context.transition("verifying", "meta_photo_album_commit_started", True)
            if not await persist(commit_possible=True):
                return unknown("Không thể lưu commit marker; chưa gửi lệnh publish.")
            created = await self.meta_accounts.publish_page_photo_album(
                context.connection_id, binding["id"], page_id,
                str(context.payload.get("caption") or "").strip(), state["ids"],
            )
            post_id = str(created.get("id") or "")
            if not re.fullmatch(r"\d+(?:_\d+)?", post_id):
                return unknown("Meta nhận yêu cầu album nhưng không trả ID bài; không tự gửi lại.")
            state["ph"] = "published"
            state["post"] = post_id
            if not await persist(commit_possible=True):
                return unknown("Meta đã trả ID bài nhưng Tinix chưa lưu được trạng thái; không tự đăng lại.", post_id)
            verified, post_url = await self._verify_photo_album_post(context, binding, post_id)
            if not verified:
                return unknown("Bài nhiều ảnh đã được tạo nhưng chưa xác minh đúng Page; không tự đăng lại.", post_id)
            return PublishResult(
                PublishOutcome.PUBLISHED, "Đã đăng và xác minh bài nhiều ảnh Facebook Page qua API.",
                post_url=post_url,
                metadata={"external_id": post_id, "post_id": post_id, "photo_ids": list(state["ids"]),
                          "provider_request_id": marker_text, "page_id": page_id,
                          "content_format": "multi_photo"},
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return unknown(f"Không xác định được kết quả upload/publish album Meta; không tự gửi lại. {str(exc)[:200]}",
                           str(state.get("post") or "") or None)

    async def _publish_photo(self, context: PublishContext, binding: dict[str, Any], item: dict[str, Any],
                             path: Path, file_bytes: bytes) -> PublishResult:
        marker = str(context.job.get("provider_request_id") or "")
        if context.job.get("provider_request_commit_possible"):
            try:
                recovery = json.loads(marker)
                if recovery.get("kind") != "page_photo":
                    raise ValueError("Provider marker không phải ảnh Page.")
                photo_id = str(recovery.get("photo_id") or "")
                post_id = str(recovery.get("post_id") or "") or None
                verified, post_url = await self._verify_photo(context, binding, photo_id, post_id)
                if verified:
                    return PublishResult(PublishOutcome.PUBLISHED, "Ảnh Facebook đã đăng và được xác minh sau khi khôi phục.",
                                         post_url=post_url,
                                         metadata={"external_id": post_id or photo_id, "photo_id": photo_id,
                                                   "post_id": post_id, "page_id": binding["external_target_id"],
                                                   "content_format": "photo"})
            except (ValueError, TypeError, KeyError, RuntimeError):
                pass
            return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                 "Meta có thể đã nhận bài ảnh nhưng Tinix chưa xác minh được sau khi khôi phục; không tự đăng lại.",
                                 metadata={"provider_request_id": marker[:500]})

        correlation_id = str(context.job.get("id") or "meta-page-photo")
        try:
            await context.transition("uploading", "meta_photo_upload_started", False)
            await context.transition("publishing", "meta_photo_publish_started", False)
            await context.transition("verifying", "meta_photo_commit_started", True)
            if context.record_provider_request:
                await context.record_provider_request(f"meta-page-photo:{correlation_id}", True)
            created = await self.meta_accounts.publish_local_photo(
                context.connection_id, binding["id"], binding["external_target_id"],
                path.name, str(item["mime_type"]), file_bytes,
                str(context.payload.get("caption") or "").strip(),
            )
            photo_id = str(created.get("id") or "")
            post_id = str(created.get("post_id") or "") or None
            if not photo_id.isdigit():
                return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                     "Meta đã nhận yêu cầu ảnh nhưng không trả ID ảnh; không tự gửi lại.",
                                     metadata={"provider_request_id": correlation_id})
            marker = json.dumps({"kind": "page_photo", "photo_id": photo_id, "post_id": post_id},
                                separators=(",", ":"), sort_keys=True)
            if context.record_provider_request:
                await context.record_provider_request(marker, True)
            verified, post_url = await self._verify_photo(context, binding, photo_id, post_id)
            if not verified:
                return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                     "Ảnh đã được Meta tạo nhưng chưa xác minh đúng Page; không tự gửi lại.",
                                     metadata={"external_id": post_id or photo_id, "photo_id": photo_id,
                                               "post_id": post_id, "provider_request_id": marker})
            return PublishResult(PublishOutcome.PUBLISHED, "Đã đăng và xác minh ảnh Facebook Page qua API.",
                                 post_url=post_url,
                                 metadata={"external_id": post_id or photo_id, "photo_id": photo_id,
                                           "post_id": post_id, "provider_request_id": marker,
                                           "page_id": binding["external_target_id"], "content_format": "photo"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                 f"Không xác định được kết quả đăng ảnh Meta; không tự gửi lại. {str(exc)[:200]}",
                                 metadata={"provider_request_id": marker or correlation_id})

    async def _verify_page_video(self, context: PublishContext, binding: dict[str, Any],
                                 video_id: str) -> tuple[bool, str | None]:
        for attempt in range(4):
            try:
                detail = await self.meta_accounts.graph_request(
                    context.connection_id, binding["id"], "GET", video_id,
                    params={"fields": "id,from,permalink_url,status"},
                )
                verified, post_url = self._verified_video_detail(detail, binding, video_id)
                if verified:
                    return True, post_url
            except (RuntimeError, ValueError, TypeError):
                pass
            if attempt < 3:
                await asyncio.sleep(2)
        return False, None

    @staticmethod
    def _verified_video_detail(detail: dict[str, Any], binding: dict[str, Any],
                               video_id: str) -> tuple[bool, str | None]:
        if (str(detail.get("id") or "") != video_id
                or str((detail.get("from") or {}).get("id") or "")
                != str(binding["external_target_id"])):
            return False, None
        publishing = ((detail.get("status") or {}).get("publishing_phase") or {})
        if str(publishing.get("publish_status") or "").lower() != "published":
            return False, None
        permalink = str(detail.get("permalink_url") or "")
        if permalink.startswith("/") and not permalink.startswith("//"):
            permalink = f"https://www.facebook.com{permalink}"
        parsed = urlparse(permalink)
        post_url = (permalink if parsed.scheme == "https"
                    and parsed.hostname in {"facebook.com", "www.facebook.com"} else None)
        return True, post_url

    async def _publish_page_video(
        self, context: PublishContext, binding: dict[str, Any], item: dict[str, Any],
        path: Path, file_size: int,
    ) -> PublishResult:
        page_id = str(binding["external_target_id"])
        file_sha = str(item["sha256"]).lower()
        correlation_id = str(context.job.get("id") or "meta-page-video")
        marker_text = str(context.job.get("provider_request_id") or "")
        marker: dict[str, Any] = {}
        try:
            if context.job.get("provider_request_commit_possible"):
                saved = json.loads(marker_text)
                video_id = str(saved.get("video_id") or "")
                if (saved.get("kind") == "page_video" and saved.get("page_id") == page_id
                        and saved.get("size") == file_size and saved.get("sha256") == file_sha
                        and saved.get("phase") == "complete" and video_id.isdigit()):
                    return PublishResult(
                        PublishOutcome.PUBLISHED, "Video Page đã được Meta xác nhận và khôi phục sau restart.",
                        post_url=saved.get("post_url"),
                        metadata={"external_id": video_id, "provider_request_id": marker_text,
                                  "page_id": page_id, "content_format": "video"},
                    )
                if (saved.get("kind") == "page_video" and saved.get("page_id") == page_id
                        and saved.get("size") == file_size and saved.get("sha256") == file_sha
                        and saved.get("phase") in {"finishing", "finish_accepted"} and video_id.isdigit()):
                    verified, post_url = await self._verify_page_video(context, binding, video_id)
                    if verified:
                        return PublishResult(
                            PublishOutcome.PUBLISHED, "Video Page đã được xác minh sau khi khôi phục.",
                            post_url=post_url,
                            metadata={"external_id": video_id, "provider_request_id": marker_text,
                                      "page_id": page_id, "content_format": "video"},
                        )
                return PublishResult(
                    PublishOutcome.UNKNOWN_RESULT,
                    "Meta có thể đã nhận lệnh hoàn tất video Page nhưng chưa xác minh được kết quả; không tự đăng lại.",
                    metadata={"provider_request_id": marker_text[:500]},
                )

            if marker_text:
                try:
                    marker = json.loads(marker_text)
                except (TypeError, ValueError):
                    return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                         "Session video Page đã lưu không hợp lệ; không tạo video khác.",
                                         metadata={"provider_request_id": marker_text[:500]})
                if (not isinstance(marker, dict) or marker.get("kind") != "page_video"
                        or marker.get("page_id") != page_id or marker.get("size") != file_size
                        or marker.get("sha256") != file_sha):
                    return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                         "Session video Page không khớp Page hoặc file đã đóng băng; không tạo video khác.",
                                         metadata={"provider_request_id": marker_text[:500]})
                if marker.get("pending"):
                    return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                         "Chunk video cuối chưa có xác nhận sau restart; cần đối soát, không gửi lại chunk.",
                                         metadata={"provider_request_id": marker_text[:500]})

            await context.transition("uploading", "meta_page_video_upload_started", False)
            session_id = str(marker.get("session_id") or "")
            if not session_id:
                marker_text = self._page_video_marker(
                    page_id=page_id, size=file_size, sha256=file_sha, phase="starting",
                )
                if context.record_provider_request:
                    await context.record_provider_request(marker_text, False)
                started = await self.meta_accounts.page_video_request(
                    context.connection_id, binding["id"], page_id,
                    {"upload_phase": "start", "file_size": str(file_size)},
                )
                session_id = str(started.get("upload_session_id") or "")
                video_id = str(started.get("video_id") or "")
                try:
                    start_offset = int(started.get("start_offset"))
                    end_offset = int(started.get("end_offset"))
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("Meta không trả offset cho upload session video Page.") from exc
                if (not session_id.isdigit() or not video_id.isdigit() or video_id == session_id
                        or not 0 <= start_offset <= end_offset <= file_size
                        or (start_offset < file_size and end_offset <= start_offset)):
                    raise RuntimeError("Meta trả video ID, upload session hoặc offset video Page không hợp lệ.")
                marker = {"kind": "page_video", "page_id": page_id, "size": file_size,
                          "sha256": file_sha, "phase": "uploading", "pending": False,
                          "session_id": session_id, "video_id": video_id, "start_offset": start_offset,
                          "end_offset": end_offset}
                marker_text = json.dumps(marker, separators=(",", ":"), sort_keys=True)
                if context.record_provider_request:
                    await context.record_provider_request(marker_text, False)
            else:
                if marker.get("phase") != "uploading":
                    return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                         "Session video Page chưa ở trạng thái upload có thể tiếp tục; không tạo video khác.",
                                         metadata={"provider_request_id": marker_text[:500]})
                video_id = str(marker.get("video_id") or "")
                try:
                    start_offset = int(marker["start_offset"])
                    end_offset = int(marker["end_offset"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise RuntimeError("Session video Page thiếu offset đã xác nhận.") from exc
                if (not session_id.isdigit() or not video_id.isdigit() or video_id == session_id
                        or not 0 <= start_offset <= end_offset <= file_size
                        or (start_offset < file_size and end_offset <= start_offset)):
                    raise RuntimeError("Session video Page có video ID hoặc offset không hợp lệ.")

            while start_offset < file_size:
                if await context.is_cancelled():
                    try:
                        await self.meta_accounts.page_video_request(
                            context.connection_id, binding["id"], page_id,
                            {"upload_phase": "cancel", "upload_session_id": session_id},
                        )
                    except Exception:
                        pass
                    raise asyncio.CancelledError
                chunk_size = end_offset - start_offset
                if chunk_size > 64 * 1024 * 1024:
                    raise RuntimeError("Meta yêu cầu chunk video vượt giới hạn bộ nhớ an toàn của Tinix.")
                with path.open("rb") as source:
                    source.seek(start_offset)
                    chunk = await asyncio.to_thread(source.read, chunk_size)
                if (len(chunk) != chunk_size or path.stat().st_size != file_size
                        or path.is_symlink()):
                    raise RuntimeError("File video Page đổi trong lúc upload; Tinix dừng trước khi publish.")

                marker = {"kind": "page_video", "page_id": page_id, "size": file_size,
                          "sha256": file_sha, "phase": "uploading", "pending": True,
                          "session_id": session_id, "video_id": video_id, "start_offset": start_offset,
                          "end_offset": end_offset}
                marker_text = json.dumps(marker, separators=(",", ":"), sort_keys=True)
                if context.record_provider_request:
                    await context.record_provider_request(marker_text, False)
                transferred = await self.meta_accounts.page_video_request(
                    context.connection_id, binding["id"], page_id,
                    {"upload_phase": "transfer", "upload_session_id": session_id,
                     "start_offset": str(start_offset)},
                    file_chunk=(path.name, chunk),
                )
                try:
                    next_start = int(transferred.get("start_offset"))
                    next_end = int(transferred.get("end_offset"))
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("Meta không trả offset tiếp theo sau khi nhận chunk video Page.") from exc
                if (next_start != end_offset or not next_start <= next_end <= file_size
                        or (next_start < file_size and next_end <= next_start)):
                    raise RuntimeError("Meta trả offset tiếp theo không hợp lệ; không gửi lại chunk.")
                start_offset, end_offset = next_start, next_end
                marker = {"kind": "page_video", "page_id": page_id, "size": file_size,
                          "sha256": file_sha, "phase": "uploading", "pending": False,
                          "session_id": session_id, "video_id": video_id, "start_offset": start_offset,
                          "end_offset": end_offset}
                marker_text = json.dumps(marker, separators=(",", ":"), sort_keys=True)
                if context.record_provider_request:
                    await context.record_provider_request(marker_text, False)

            if (path.stat().st_size != file_size
                    or await asyncio.to_thread(self._sha256, path) != file_sha):
                return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                     "File video Page đổi trong lúc tải; chưa gửi lệnh publish.",
                                     metadata={"provider_request_id": marker_text[:500]})
            if await context.is_cancelled():
                try:
                    await self.meta_accounts.page_video_request(
                        context.connection_id, binding["id"], page_id,
                        {"upload_phase": "cancel", "upload_session_id": session_id},
                    )
                except Exception:
                    pass
                raise asyncio.CancelledError

            await context.transition("publishing", "meta_page_video_publish_started", False)
            await context.transition("verifying", "meta_page_video_commit_started", True)
            marker = {"kind": "page_video", "page_id": page_id, "size": file_size,
                      "sha256": file_sha, "phase": "finishing", "pending": True,
                      "session_id": session_id, "video_id": video_id, "start_offset": file_size,
                      "end_offset": file_size}
            marker_text = json.dumps(marker, separators=(",", ":"), sort_keys=True)
            if context.record_provider_request:
                await context.record_provider_request(marker_text, True)
            caption = str(context.payload.get("caption") or "").strip()
            finished = await self.meta_accounts.page_video_request(
                context.connection_id, binding["id"], page_id,
                {"upload_phase": "finish", "upload_session_id": session_id,
                 "published": "true", **({"description": caption} if caption else {})},
            )
            returned_video_id = str(finished.get("video_id") or finished.get("id") or "")
            if (finished.get("success") is False
                    or (returned_video_id and returned_video_id != video_id)
                    or (not returned_video_id and finished.get("success") is not True)):
                return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                     "Meta đã nhận lệnh hoàn tất nhưng chưa xác nhận video ID; không tự publish lại.",
                                     metadata={"provider_request_id": marker_text[:500]})
            marker = {"kind": "page_video", "page_id": page_id, "size": file_size,
                      "sha256": file_sha, "phase": "finish_accepted", "pending": False,
                      "session_id": session_id, "start_offset": file_size,
                      "end_offset": file_size, "video_id": video_id}
            marker_text = json.dumps(marker, separators=(",", ":"), sort_keys=True)
            if context.record_provider_request:
                await context.record_provider_request(marker_text, True)
            verified, post_url = await self._verify_page_video(context, binding, video_id)
            if not verified:
                return PublishResult(
                    PublishOutcome.UNKNOWN_RESULT,
                    "Meta đã nhận video nhưng chưa xác minh được bài công khai trên đúng Page; không tự đăng lại.",
                    metadata={"external_id": video_id, "provider_request_id": marker_text,
                              "page_id": page_id, "content_format": "video"},
                )
            marker["phase"] = "complete"
            if post_url:
                marker["post_url"] = post_url
            marker_text = json.dumps(marker, separators=(",", ":"), sort_keys=True)
            if context.record_provider_request:
                await context.record_provider_request(marker_text, True)
            return PublishResult(
                PublishOutcome.PUBLISHED, "Đã đăng và xác minh video trên Facebook Page.",
                post_url=post_url,
                metadata={"external_id": video_id, "provider_request_id": marker_text,
                          "page_id": page_id, "content_format": "video"},
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                 f"Không xác định được kết quả upload/publish video Page; không tự gửi lại. {str(exc)[:200]}",
                                 metadata={"provider_request_id": marker_text or correlation_id})

    async def _publish_text(self, context: PublishContext, binding: dict[str, Any]) -> PublishResult:
        correlation_id = str(context.job.get("id") or "meta-page-publish")
        try:
            await context.transition("publishing", "meta_page_publish_started", False)
            await context.transition("verifying", "meta_page_commit_started", True)
            if context.record_provider_request:
                await context.record_provider_request(correlation_id, True)
            created = await self.meta_accounts.graph_request(
                context.connection_id, binding["id"], "POST",
                f"{binding['external_target_id']}/feed",
                data={"message": str(context.payload["caption"]).strip()},
            )
            post_id = str(created.get("id") or "")
            if not post_id:
                return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                     "Meta nhận yêu cầu nhưng không trả ID bài đăng; không tự gửi lại.",
                                     metadata={"provider_request_id": correlation_id})
            detail = await self.meta_accounts.graph_request(
                context.connection_id, binding["id"], "GET", post_id,
                params={"fields": "id,from,permalink_url"},
            )
            post_page_id = str((detail.get("from") or {}).get("id") or "")
            if str(detail.get("id") or "") != post_id or post_page_id != binding["external_target_id"]:
                return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                     "Meta trả bài đăng nhưng không thể xác minh đúng Page; không tự gửi lại.",
                                     metadata={"external_id": post_id, "provider_request_id": correlation_id})
            return PublishResult(PublishOutcome.PUBLISHED, "Đã đăng bài văn bản lên Facebook Page qua API.",
                                 post_url=detail.get("permalink_url"),
                                 metadata={"external_id": post_id, "provider_request_id": correlation_id,
                                           "page_id": post_page_id})
        except Exception as exc:
            return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                 f"Không xác định được kết quả đăng Meta; không tự gửi lại. {str(exc)[:250]}",
                                 metadata={"provider_request_id": correlation_id})

    async def _publish_reel(
        self, context: PublishContext, binding: dict[str, Any], item: dict[str, Any],
        local_file: Path, file_size: int,
    ) -> PublishResult:
        correlation_id = str(context.job.get("id") or "meta-page-reel")
        upload_url = str(context.job.get("provider_request_id") or "")
        video_id = ""
        try:
            if upload_url:
                parsed = urlparse(upload_url)
                match = re.fullmatch(r"/video-upload/v\d+\.\d+/(\d+)", parsed.path)
                if (parsed.scheme != "https" or parsed.hostname != "rupload.facebook.com"
                        or parsed.port or parsed.query or parsed.fragment or not match):
                    return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                         "Session Reel đã lưu không hợp lệ; không tạo session khác.",
                                         metadata={"provider_request_id": upload_url[:500]})
                video_id = match.group(1)
                status = await self.meta_accounts.graph_request(
                    context.connection_id, binding["id"], "GET", video_id,
                    params={"fields": "id,from,permalink_url,status"},
                )
                if str(status.get("id") or "") != video_id:
                    return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                         "Không thể khôi phục đúng session Reel cũ; không tạo session khác.",
                                         metadata={"provider_request_id": video_id})
                previous_status = status.get("status") or {}
                if ((previous_status.get("publishing_phase") or {}).get("status") == "complete"):
                    verified, post_url = self._verified_video_detail(status, binding, video_id)
                    if verified:
                        return PublishResult(PublishOutcome.PUBLISHED, "Reel cũ đã publish và được xác minh sau restart.",
                                             post_url=post_url,
                                             metadata={"external_id": video_id, "provider_request_id": video_id,
                                                       "page_id": binding["external_target_id"],
                                                       "content_format": "reel"})
                    return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                         "Reel đã xử lý xong nhưng chưa xác minh được đúng Page và trạng thái đã đăng.",
                                         metadata={"external_id": video_id, "provider_request_id": video_id})
                upload_complete = ((previous_status.get("uploading_phase") or {}).get("status") == "complete")
                if context.job.get("provider_request_commit_possible"):
                    return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                         "Meta chưa xác nhận Reel đã publish sau restart; cần kiểm tra thủ công, không tự gửi lại.",
                                         metadata={"external_id": video_id, "provider_request_id": video_id})
                if not upload_complete:
                    return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                         "Meta chưa xác nhận upload Reel hoàn tất sau restart; không upload lại hay tạo Reel mới.",
                                         metadata={"provider_request_id": video_id})
            else:
                started = await self.meta_accounts.graph_request(
                    context.connection_id, binding["id"], "POST",
                    "me/video_reels", data={"upload_phase": "start"},
                )
                video_id = str(started.get("video_id") or "")
                upload_url = str(started.get("upload_url") or "")
                upload_complete = False
            parsed = urlparse(upload_url)
            if (not video_id.isdigit() or parsed.scheme != "https"
                    or parsed.hostname != "rupload.facebook.com" or parsed.port or parsed.query or parsed.fragment
                    or not re.fullmatch(rf"/video-upload/v\d+\.\d+/{re.escape(video_id)}", parsed.path)):
                return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                     "Meta không trả upload session hợp lệ; không tự tạo lại Reel.",
                                     metadata={"provider_request_id": correlation_id})
            if not context.job.get("provider_request_id") and context.record_provider_request:
                await context.record_provider_request(upload_url, False)
            await context.transition("uploading", "meta_reel_upload_started", False)
            if not upload_complete:
                await self.meta_accounts.upload_local_reel(
                    context.connection_id, binding["id"], upload_url, local_file, file_size,
                )
            if (local_file.stat().st_size != file_size
                    or await asyncio.to_thread(self._sha256, local_file) != str(item["sha256"]).lower()):
                return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                     "File Reel đổi trong lúc tải lên; chưa gửi lệnh publish.",
                                     metadata={"provider_request_id": correlation_id, "video_id": video_id})
            if await context.is_cancelled():
                raise asyncio.CancelledError
            await context.transition("publishing", "meta_reel_publish_started", False)
            await context.transition("verifying", "meta_reel_commit_started", True)
            if context.record_provider_request:
                await context.record_provider_request(upload_url, True)
            await self.meta_accounts.graph_request(
                context.connection_id, binding["id"], "POST",
                "me/video_reels",
                data={"video_id": video_id, "upload_phase": "finish", "video_state": "PUBLISHED",
                      **({"description": str(context.payload.get("caption") or "").strip()}
                         if str(context.payload.get("caption") or "").strip() else {})},
            )
            # Reconcile the same upload session only. Never create a second session after commit.
            for attempt in range(8):
                status = await self.meta_accounts.graph_request(
                    context.connection_id, binding["id"], "GET", video_id,
                    params={"fields": "id,from,permalink_url,status"},
                )
                publishing = ((status.get("status") or {}).get("publishing_phase") or {}).get("status")
                verified, post_url = self._verified_video_detail(status, binding, video_id)
                if publishing == "complete" and verified:
                    return PublishResult(PublishOutcome.PUBLISHED, "Đã đăng và xác minh Facebook Reel.",
                                         post_url=post_url,
                                         metadata={"external_id": video_id, "provider_request_id": video_id,
                                                   "page_id": binding["external_target_id"],
                                                   "content_format": "reel"})
                if attempt < 7:
                    await asyncio.sleep(min(2 ** attempt, 8))
            return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                 "Facebook đang xử lý Reel nhưng chưa xác nhận hoàn tất; không tự gửi lại.",
                                 metadata={"external_id": video_id, "provider_request_id": video_id,
                                           "page_id": binding["external_target_id"]})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return PublishResult(PublishOutcome.UNKNOWN_RESULT,
                                 f"Không xác định được kết quả upload/publish Reel; không tự gửi lại. {str(exc)[:200]}",
                                 metadata={"provider_request_id": video_id or correlation_id,
                                           **({"external_id": video_id} if video_id else {})})

    async def verify(self, external_id: str, context: PublishContext) -> Any:
        binding = self._binding(context)
        if context.payload.get("content_format") == "reel":
            return await self.meta_accounts.graph_request(
                context.connection_id, binding["id"], "GET", external_id,
                params={"fields": "id,status"},
            )
        return await self.meta_accounts.graph_request(
            context.connection_id, binding["id"], "GET", external_id,
            params={"fields": "id,from,permalink_url"},
        )
