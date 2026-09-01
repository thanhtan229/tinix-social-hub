from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import psutil

from app.core.config import Settings
from app.db.database import Database, utc_now
from app.db.repositories import AccountRepository


class ProfileTransferError(RuntimeError):
    pass


class ChromeProfileTransferService:
    """Copy Chrome user-data directories without ever sharing a live profile."""

    CACHE_DIRECTORIES = {
        "cache", "code cache", "gpucache", "shadercache", "grshadercache",
        "dawncache", "crashpad", "component_crx_cache",
    }
    LOCK_FILES = {"singletonlock", "singletoncookie", "singletonsocket", "lockfile"}
    REPARSE_POINT = 0x400
    BUNDLE_FORMAT = "tinix-profile"
    BUNDLE_VERSION = 1

    def __init__(
        self,
        settings: Settings,
        database: Database,
        accounts: AccountRepository,
        path_in_use: Callable[[Path], bool] | None = None,
    ) -> None:
        self.settings = settings
        self.db = database
        self.accounts = accounts
        self.path_in_use = path_in_use or self._chrome_uses_path
        self.backup_root = (settings.backup_dir / "chrome_profiles").resolve()
        self.export_root = (settings.export_dir / "chrome_profiles").resolve()
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self.export_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _same_path(left: Path, right: Path) -> bool:
        return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))

    @classmethod
    def _is_reparse(cls, path: Path) -> bool:
        try:
            info = path.stat(follow_symlinks=False)
            return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & cls.REPARSE_POINT)
        except OSError as exc:
            raise ProfileTransferError(f"Không thể đọc đường dẫn: {path}") from exc

    @classmethod
    def _chrome_uses_path(cls, path: Path) -> bool:
        for process in psutil.process_iter(["name", "cmdline"]):
            try:
                if "chrome" not in (process.info.get("name") or "").lower():
                    continue
                for argument in process.info.get("cmdline") or []:
                    if argument.lower().startswith("--user-data-dir="):
                        current = Path(argument.split("=", 1)[1].strip('"'))
                        if cls._same_path(current, path):
                            return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        return False

    def _account_and_target(self, account_id: str) -> tuple[dict[str, Any], Path]:
        account = self.accounts.get(account_id)
        if not account:
            raise KeyError(account_id)
        target = (self.settings.chrome_profile_dir / account["profile_key"]).resolve()
        root = self.settings.chrome_profile_dir.resolve()
        if target.parent != root:
            raise ProfileTransferError("Đường dẫn profile account không hợp lệ.")
        return account, target

    @classmethod
    def _validate_profile(cls, path: Path) -> None:
        if not path.is_absolute() or not path.is_dir():
            raise ProfileTransferError("Thư mục profile không tồn tại hoặc không phải đường dẫn tuyệt đối.")
        if cls._is_reparse(path):
            raise ProfileTransferError("Không hỗ trợ profile là symlink/junction/reparse point.")
        markers = [path / "Local State", path / "Default" / "Preferences"]
        markers.extend(path.glob("Profile */Preferences"))
        if not any(marker.is_file() for marker in markers):
            raise ProfileTransferError("Không nhận diện được Chrome user-data directory (thiếu Local State/Preferences).")

    @classmethod
    def _copy_tree(cls, source: Path, destination: Path) -> tuple[int, int]:
        files = 0
        total = 0
        destination.mkdir(parents=True, exist_ok=False)

        def copy_directory(current_source: Path, current_destination: Path) -> None:
            nonlocal files, total
            with os.scandir(current_source) as entries:
                for entry in entries:
                    source_item = Path(entry.path)
                    lowered = entry.name.lower()
                    if lowered in cls.LOCK_FILES:
                        continue
                    if cls._is_reparse(source_item):
                        raise ProfileTransferError(f"Profile chứa symlink/junction không an toàn: {source_item}")
                    if entry.is_dir(follow_symlinks=False):
                        if lowered in cls.CACHE_DIRECTORIES:
                            continue
                        destination_item = current_destination / entry.name
                        destination_item.mkdir()
                        copy_directory(source_item, destination_item)
                    elif entry.is_file(follow_symlinks=False):
                        size = entry.stat(follow_symlinks=False).st_size
                        shutil.copy2(source_item, current_destination / entry.name)
                        files += 1
                        total += size

        copy_directory(source, destination)
        return files, total

    @staticmethod
    def _safe_label(value: str) -> str:
        clean = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
        return clean[:60] or "profile"

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")

    def _begin_audit(self, account_id: str, operation: str, source: Path | None, destination: Path | None) -> str:
        operation_id = str(uuid.uuid4())
        with self.db.connection() as connection:
            connection.execute(
                "INSERT INTO chrome_profile_operations(id,account_id,operation,status,source_path,destination_path,created_at) VALUES(?,?,?,?,?,?,?)",
                (operation_id, account_id, operation, "running", str(source) if source else None,
                 str(destination) if destination else None, utc_now()),
            )
        return operation_id

    def _finish_audit(
        self, operation_id: str, status: str, *, backup_name: str | None = None,
        files: int = 0, size: int = 0, error: str | None = None,
    ) -> None:
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE chrome_profile_operations SET status=?,backup_name=?,files_copied=?,bytes_copied=?,error=?,finished_at=? WHERE id=?",
                (status, backup_name, files, size, error, utc_now(), operation_id),
            )

    def _ensure_available(self, *paths: Path) -> None:
        for path in paths:
            if path.exists() and self.path_in_use(path):
                raise ProfileTransferError(f"Chrome đang sử dụng profile: {path}. Hãy đóng Chrome trước.")

    def _backup_destination(self, account_id: str, label: str) -> Path:
        folder = (self.backup_root / account_id).resolve()
        if folder.parent != self.backup_root:
            raise ProfileTransferError("Đường dẫn backup không hợp lệ.")
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{self._timestamp()}-{self._safe_label(label)}"

    def _copy_to_unique(self, source: Path, destination: Path) -> tuple[int, int]:
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
        staging.rmdir()
        try:
            files, size = self._copy_tree(source, staging)
            self._validate_profile(staging)
            if destination.exists():
                raise ProfileTransferError(f"Đích đã tồn tại: {destination}")
            os.replace(staging, destination)
            return files, size
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise

    def _read_bundle(self, bundle_path: str) -> tuple[Path, dict[str, Any], Path]:
        bundle = Path(os.path.expandvars(os.path.expanduser(bundle_path))).resolve()
        if not bundle.is_absolute() or not bundle.is_dir() or self._is_reparse(bundle):
            raise ProfileTransferError("Gói Tinix profile không tồn tại hoặc không an toàn.")
        manifest_path = bundle / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProfileTransferError("Gói profile thiếu manifest.json hợp lệ.") from exc
        if manifest.get("bundle_format") != self.BUNDLE_FORMAT or manifest.get("format_version") != self.BUNDLE_VERSION:
            raise ProfileTransferError("Định dạng gói Tinix profile không được hỗ trợ.")
        name = str(manifest.get("account_name") or "").strip()
        platform = str(manifest.get("platform") or "").strip().lower()
        if not name or len(name) > 100:
            raise ProfileTransferError("Tên account trong manifest không hợp lệ.")
        if platform not in {"facebook", "instagram", "tiktok", "youtube"}:
            raise ProfileTransferError(f"Nền tảng trong gói chưa được Social Hub hỗ trợ: {platform or 'trống'}.")
        profile = (bundle / "chrome-profile").resolve()
        if profile.parent != bundle:
            raise ProfileTransferError("Đường dẫn Chrome profile trong gói không hợp lệ.")
        self._validate_profile(profile)
        return bundle, manifest, profile

    def import_bundle(self, bundle_path: str) -> dict[str, Any]:
        _, manifest, profile = self._read_bundle(bundle_path)
        account = self.accounts.create(manifest["account_name"], manifest["platform"])
        target = (self.settings.chrome_profile_dir / account["profile_key"]).resolve()
        try:
            transfer = self.import_profile(account["id"], str(profile))
        except Exception:
            self.accounts.delete_if_safe(account["id"])
            if target.exists() and target.parent == self.settings.chrome_profile_dir.resolve():
                shutil.rmtree(target)
            raise
        return {
            **transfer,
            "account": self.accounts.get(account["id"]),
            "source_app": manifest.get("source_app"),
            "source_account_id": manifest.get("source_account_id"),
        }

    def _run(self, account_id: str, operation: str, source: Path | None, destination: Path | None, action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        self.accounts.begin_profile_operation(account_id)
        operation_id = ""
        try:
            operation_id = self._begin_audit(account_id, operation, source, destination)
            result = action()
            self._finish_audit(
                operation_id, "succeeded", backup_name=result.get("backup_name"),
                files=result.get("files_copied", 0), size=result.get("bytes_copied", 0),
            )
            return {"operation_id": operation_id, "operation": operation, **result}
        except Exception as exc:
            if operation_id:
                self._finish_audit(operation_id, "failed", error=str(exc))
            raise
        finally:
            self.accounts.end_profile_operation(account_id)

    def import_profile(self, account_id: str, source_path: str) -> dict[str, Any]:
        account, target = self._account_and_target(account_id)
        source = Path(os.path.expandvars(os.path.expanduser(source_path))).resolve()

        def action() -> dict[str, Any]:
            self._validate_profile(source)
            if self._same_path(source, target):
                raise ProfileTransferError("Nguồn Import trùng với profile hiện tại.")
            self._ensure_available(source, target)
            staging = Path(tempfile.mkdtemp(prefix=f".{account_id}-import-", dir=target.parent))
            staging.rmdir()
            backup: Path | None = None
            try:
                files, size = self._copy_tree(source, staging)
                self._validate_profile(staging)
                if target.exists():
                    if any(target.iterdir()):
                        self._validate_profile(target)
                        backup = self._backup_destination(account_id, "before-import")
                        os.replace(target, backup)
                    else:
                        target.rmdir()
                os.replace(staging, target)
                return {
                    "profile_path": str(target), "backup_name": backup.name if backup else None,
                    "files_copied": files, "bytes_copied": size,
                }
            except Exception:
                if backup and backup.exists() and not target.exists():
                    os.replace(backup, target)
                if staging.exists():
                    shutil.rmtree(staging)
                raise

        return self._run(account_id, "import", source, target, action)

    def export_profile(self, account_id: str) -> dict[str, Any]:
        account, source = self._account_and_target(account_id)
        destination = self.export_root / f"{self._safe_label(account['name'])}-{self._timestamp()}.tinix-profile"

        def action() -> dict[str, Any]:
            self._validate_profile(source)
            self._ensure_available(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
            try:
                profile_destination = staging / "chrome-profile"
                files, size = self._copy_tree(source, profile_destination)
                self._validate_profile(profile_destination)
                from app import __version__
                manifest = {
                    "bundle_format": self.BUNDLE_FORMAT,
                    "format_version": self.BUNDLE_VERSION,
                    "account_name": account["name"],
                    "platform": account["platform"],
                    "source_app": "Tinix Social Hub",
                    "source_app_version": __version__,
                    "source_account_id": account["id"],
                    "exported_at": utc_now(),
                }
                (staging / "manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                if destination.exists():
                    raise ProfileTransferError(f"Đích đã tồn tại: {destination}")
                os.replace(staging, destination)
            except Exception:
                if staging.exists():
                    shutil.rmtree(staging)
                raise
            return {
                "export_path": str(destination), "bundle_path": str(destination),
                "files_copied": files, "bytes_copied": size,
            }

        return self._run(account_id, "export", source, destination, action)

    def backup_profile(self, account_id: str) -> dict[str, Any]:
        _, source = self._account_and_target(account_id)
        destination = self._backup_destination(account_id, "manual")

        def action() -> dict[str, Any]:
            self._validate_profile(source)
            self._ensure_available(source)
            files, size = self._copy_to_unique(source, destination)
            return {"backup_name": destination.name, "backup_path": str(destination), "files_copied": files, "bytes_copied": size}

        return self._run(account_id, "backup", source, destination, action)

    def restore_profile(self, account_id: str, backup_name: str) -> dict[str, Any]:
        _, target = self._account_and_target(account_id)
        source = (self.backup_root / account_id / backup_name).resolve()
        expected_parent = (self.backup_root / account_id).resolve()
        if source.parent != expected_parent:
            raise ProfileTransferError("Tên backup không hợp lệ.")

        def action() -> dict[str, Any]:
            self._validate_profile(source)
            self._ensure_available(source, target)
            staging = Path(tempfile.mkdtemp(prefix=f".{account_id}-restore-", dir=target.parent))
            staging.rmdir()
            previous: Path | None = None
            try:
                files, size = self._copy_tree(source, staging)
                self._validate_profile(staging)
                if target.exists():
                    if any(target.iterdir()):
                        self._validate_profile(target)
                        previous = self._backup_destination(account_id, "before-restore")
                        os.replace(target, previous)
                    else:
                        target.rmdir()
                os.replace(staging, target)
                return {
                    "profile_path": str(target), "restored_from": backup_name,
                    "backup_name": previous.name if previous else None,
                    "files_copied": files, "bytes_copied": size,
                }
            except Exception:
                if previous and previous.exists() and not target.exists():
                    os.replace(previous, target)
                if staging.exists():
                    shutil.rmtree(staging)
                raise

        return self._run(account_id, "restore", source, target, action)

    def list_backups(self, account_id: str) -> list[dict[str, Any]]:
        self._account_and_target(account_id)
        folder = (self.backup_root / account_id).resolve()
        if not folder.exists():
            return []
        result = []
        for path in sorted((item for item in folder.iterdir() if item.is_dir()), reverse=True):
            stat = path.stat()
            result.append({
                "name": path.name, "path": str(path), "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            })
        return result

    def history(self, account_id: str, limit: int = 30) -> list[dict[str, Any]]:
        self._account_and_target(account_id)
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM chrome_profile_operations WHERE account_id=? ORDER BY created_at DESC LIMIT ?",
                (account_id, max(1, min(limit, 100))),
            )]
