from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db.database import Database, utc_now
from app.services.profile_transfer import ChromeProfileTransferService, ProfileTransferError


class RecoveryBundleError(RuntimeError):
    pass


class RecoveryBundleService:
    """Create password-protected, whole-app recovery bundles for one Windows user."""

    FORMAT = "tinix-recovery"
    VERSION = 1
    MAX_FILES = 250_000
    MAX_BYTES = 100 * 1024 * 1024 * 1024

    def __init__(
        self, settings: Any, database: Database, profile_transfer: ChromeProfileTransferService,
    ) -> None:
        self.settings = settings
        self.database = database
        self.profile_transfer = profile_transfer
        self.export_root = (settings.export_dir / "recovery").resolve()
        self.export_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

    @staticmethod
    def _remove(path: Path) -> None:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    @classmethod
    def _copy_tree(
        cls, source: Path, destination: Path, *, excluded_roots: tuple[Path, ...] = (),
    ) -> tuple[int, int]:
        if not source.is_dir() or ChromeProfileTransferService._is_reparse(source):
            raise RecoveryBundleError(f"Thư mục không an toàn hoặc không tồn tại: {source}")
        destination.mkdir(parents=True, exist_ok=False)
        files = 0
        size = 0

        def copy_directory(current_source: Path, current_destination: Path) -> None:
            nonlocal files, size
            with os.scandir(current_source) as entries:
                for entry in entries:
                    item = Path(entry.path)
                    if any(cls._is_within(item, excluded) for excluded in excluded_roots):
                        continue
                    if ChromeProfileTransferService._is_reparse(item):
                        raise RecoveryBundleError(f"Dữ liệu chứa symlink/junction không an toàn: {item}")
                    target = current_destination / entry.name
                    if entry.is_dir(follow_symlinks=False):
                        target.mkdir()
                        copy_directory(item, target)
                    elif entry.is_file(follow_symlinks=False):
                        item_size = entry.stat(follow_symlinks=False).st_size
                        files += 1
                        size += item_size
                        if files > cls.MAX_FILES or size > cls.MAX_BYTES:
                            raise RecoveryBundleError("Dữ liệu recovery vượt giới hạn an toàn 100 GB hoặc 250.000 file.")
                        shutil.copy2(item, target)

        copy_directory(source, destination)
        return files, size

    @staticmethod
    def _file_digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _tree_stats(path: Path) -> tuple[int, int]:
        if not path.exists():
            return 0, 0
        if path.is_file():
            return 1, path.stat().st_size
        files = 0
        size = 0
        for item in path.rglob("*"):
            if item.is_file():
                files += 1
                size += item.stat().st_size
        return files, size

    def _ensure_profiles_available(self) -> None:
        profiles: list[Path] = []
        for account in self.profile_transfer.accounts.list():
            _, profile = self.profile_transfer._account_and_target(account["id"])
            if profile.exists():
                profiles.append(profile)
        try:
            self.profile_transfer._ensure_available(*profiles)
        except ProfileTransferError as exc:
            raise RecoveryBundleError(str(exc)) from exc

    def create_bundle(self, password: str, *, include_environment: bool = True) -> dict[str, Any]:
        if not password:
            raise RecoveryBundleError("Cần đặt mật khẩu để tạo gói recovery.")
        self._ensure_profiles_available()
        database_snapshot = self.database.create_backup(reason="recovery", keep=1000)
        staging = Path(tempfile.mkdtemp(prefix=".tinix-recovery-", dir=self.export_root))
        temporary_zip = self.export_root / f".{uuid.uuid4()}.tinix-recovery.zip"
        temporary_encrypted = self.export_root / f".{uuid.uuid4()}.tinix-recovery.enc"
        destination = self.export_root / f"Tinix-Social-Hub-recovery-{self._timestamp()}.tinix-recovery.enc"
        components: dict[str, dict[str, Any]] = {}
        try:
            staged_data = staging / "data"
            data_files, data_size = self._copy_tree(
                self.settings.data_dir, staged_data,
                excluded_roots=(self.settings.backup_dir, self.database.path),
            )
            database_target = staged_data / "tinix_social.db"
            shutil.copy2(database_snapshot, database_target)
            components["data"] = {
                "files": data_files + 1,
                "bytes": data_size + database_target.stat().st_size,
                "database_sha256": self._file_digest(database_target),
            }
            for key, source in (("media", self.settings.media_dir), ("chrome_profiles", self.settings.chrome_profile_dir)):
                target = staging / key
                if source.exists():
                    files, size = self._copy_tree(source, target)
                else:
                    target.mkdir()
                    files, size = 0, 0
                components[key] = {"files": files, "bytes": size}
            environment = self.settings.project_root / ".env"
            if include_environment and environment.is_file():
                shutil.copy2(environment, staging / ".env")
                components["environment"] = {"included": True, "sha256": self._file_digest(staging / ".env")}
            else:
                components["environment"] = {"included": False}
            from app import __version__
            manifest = {
                "bundle_format": self.FORMAT,
                "format_version": self.VERSION,
                "source_app": "Tinix Social Hub",
                "source_app_version": __version__,
                "exported_at": utc_now(),
                "package_encryption": "password_aes_256_gcm",
                "components": components,
            }
            (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            with zipfile.ZipFile(temporary_zip, "w", zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=6) as archive:
                for item in staging.rglob("*"):
                    if item.is_file():
                        archive.write(item, item.relative_to(staging).as_posix())
            ChromeProfileTransferService._encrypt_archive(temporary_zip, temporary_encrypted, password)
            temporary_zip.unlink()
            os.replace(temporary_encrypted, destination)
        except ProfileTransferError as exc:
            raise RecoveryBundleError(str(exc)) from exc
        finally:
            if temporary_zip.exists():
                temporary_zip.unlink()
            if temporary_encrypted.exists():
                temporary_encrypted.unlink()
            shutil.rmtree(staging, ignore_errors=True)
        files, size = self._tree_stats(destination)
        return {
            "bundle_path": str(destination), "archive_path": str(destination),
            "files_copied": sum(item.get("files", 0) for item in components.values()),
            "bytes_copied": sum(item.get("bytes", 0) for item in components.values()),
            "bundle_size": size, "environment_included": components["environment"]["included"],
            "package_encrypted": True,
        }

    def _read_bundle(self, bundle_path: str, password: str) -> tuple[Path, Path, dict[str, Any]]:
        source = Path(os.path.expandvars(os.path.expanduser(bundle_path))).resolve()
        if not source.is_file() or ChromeProfileTransferService._is_reparse(source):
            raise RecoveryBundleError("Gói recovery không tồn tại hoặc không an toàn.")
        workspace = Path(tempfile.mkdtemp(prefix="tinix-recovery-import-"))
        archive = workspace / "bundle.zip"
        extracted = workspace / "extracted"
        extracted.mkdir()
        try:
            ChromeProfileTransferService._decrypt_encrypted_archive(source, archive, password)
            ChromeProfileTransferService._extract_archive(archive, extracted)
            manifest = json.loads((extracted / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ProfileTransferError) as exc:
            shutil.rmtree(workspace, ignore_errors=True)
            raise RecoveryBundleError(str(exc) or "Không thể đọc gói recovery.") from exc
        if not isinstance(manifest, dict) or manifest.get("bundle_format") != self.FORMAT or manifest.get("format_version") != self.VERSION:
            shutil.rmtree(workspace, ignore_errors=True)
            raise RecoveryBundleError("Định dạng gói recovery không được hỗ trợ.")
        database_file = extracted / "data" / "tinix_social.db"
        expected_hash = ((manifest.get("components") or {}).get("data") or {}).get("database_sha256")
        if not database_file.is_file() or not isinstance(expected_hash, str) or self._file_digest(database_file) != expected_hash:
            shutil.rmtree(workspace, ignore_errors=True)
            raise RecoveryBundleError("Database trong gói recovery không vượt qua kiểm tra checksum.")
        try:
            with closing(sqlite3.connect(database_file)) as connection:
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RecoveryBundleError("Database trong gói recovery không đạt integrity check.")
        except sqlite3.Error as exc:
            shutil.rmtree(workspace, ignore_errors=True)
            raise RecoveryBundleError("Không thể kiểm tra database trong gói recovery.") from exc
        return workspace, extracted, manifest

    def restore_bundle(self, bundle_path: str, password: str) -> dict[str, Any]:
        self._ensure_profiles_available()
        workspace, extracted, manifest = self._read_bundle(bundle_path, password)
        token = uuid.uuid4().hex
        applied: list[tuple[Path, Path | None]] = []
        nearby_paths: list[Path] = []
        try:
            components = ((manifest.get("components") or {}).get("environment") or {})
            targets = (
                ("data", self.settings.data_dir),
                ("media", self.settings.media_dir),
                ("chrome_profiles", self.settings.chrome_profile_dir),
            )
            for name, target in targets:
                incoming = extracted / name
                incoming.mkdir(parents=True, exist_ok=True)
                nearby = target.parent / f".{target.name}.tinix-recovery-{token}"
                nearby_paths.append(nearby)
                self._copy_tree(incoming, nearby)
                safety = target.parent / f".{target.name}.before-recovery-{self._timestamp()}"
                if target.exists():
                    os.replace(target, safety)
                else:
                    safety = None
                applied.append((target, safety))
                os.replace(nearby, target)
            if components.get("included"):
                incoming = extracted / ".env"
                if not incoming.is_file():
                    raise RecoveryBundleError("Gói recovery thiếu file cấu hình đã khai báo.")
                target = self.settings.project_root / ".env"
                nearby = target.parent / f".{target.name}.tinix-recovery-{token}"
                nearby_paths.append(nearby)
                shutil.copy2(incoming, nearby)
                safety = target.parent / f".{target.name}.before-recovery-{self._timestamp()}"
                if target.exists():
                    os.replace(target, safety)
                else:
                    safety = None
                applied.append((target, safety))
                os.replace(nearby, target)
            return {
                "restored": True,
                "source_app_version": manifest.get("source_app_version"),
                "safety_paths": [str(safety) for _, safety in applied if safety],
                "_rollback": [(str(target), str(safety) if safety else "") for target, safety in applied],
            }
        except Exception as exc:
            for target, safety in reversed(applied):
                self._remove(target)
                if safety and safety.exists():
                    os.replace(safety, target)
            if isinstance(exc, RecoveryBundleError):
                raise
            raise RecoveryBundleError("Khôi phục recovery bundle thất bại; dữ liệu đã được hoàn nguyên.") from exc
        finally:
            for nearby in nearby_paths:
                self._remove(nearby)
            shutil.rmtree(workspace, ignore_errors=True)

    def rollback_restore(self, result: dict[str, Any]) -> None:
        records = result.get("_rollback")
        if not isinstance(records, list):
            raise RecoveryBundleError("Không có thông tin hoàn nguyên recovery bundle.")
        allowed = {
            self.settings.data_dir.resolve(), self.settings.media_dir.resolve(),
            self.settings.chrome_profile_dir.resolve(), (self.settings.project_root / ".env").resolve(),
        }
        for raw_target, raw_safety in reversed(records):
            target = Path(raw_target).resolve()
            safety = Path(raw_safety).resolve() if raw_safety else None
            if target not in allowed:
                raise RecoveryBundleError("Đường dẫn hoàn nguyên recovery bundle không hợp lệ.")
            self._remove(target)
            if safety and safety.exists():
                os.replace(safety, target)
