from __future__ import annotations

import base64
import binascii
import json
import os
import re
import shutil
import struct
import tempfile
import uuid
import zipfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from app.core.config import Settings
from app.core.secrets import SecretProtector
from app.db.database import Database, utc_now
from app.db.repositories import AccountRepository


class ProfileTransferError(RuntimeError):
    pass


class ChromeProfileTransferService:
    """Copy Chrome user-data directories without ever sharing a live profile."""

    CACHE_DIRECTORIES = frozenset({
        "cache", "code cache", "gpucache", "shadercache", "grshadercache",
        "dawncache", "crashpad", "component_crx_cache",
    })
    CLEANUP_DIRECTORIES = CACHE_DIRECTORIES | frozenset({
        "browsermetrics", "cache_storage", "cachestorage", "crash reports",
        "media cache", "optimization_guide_model_store", "safe browsing",
        "wasmttsengine",
    })
    SESSION_ROOT_FILES = frozenset({"local state"})
    SESSION_PROFILE_FILES = frozenset({
        "cookies", "cookies-journal", "cookies-shm", "cookies-wal",
        "preferences", "secure preferences",
    })
    SESSION_PROFILE_DIRECTORIES = frozenset({
        "indexeddb", "local storage", "session storage", "webstorage",
    })
    LOCK_FILES = frozenset({"singletonlock", "singletoncookie", "singletonsocket", "lockfile"})
    REPARSE_POINT = 0x400
    BUNDLE_FORMAT = "tinix-profile"
    BUNDLE_VERSION = 1
    COLLECTION_FORMAT = "tinix-profiles"
    COLLECTION_VERSION = 1
    CREDENTIAL_PROTECTION_PORTABLE_V2 = "portable_aes_256_gcm_v2"
    CREDENTIAL_PROTECTION_DPAPI = "windows_dpapi"
    ENVELOPE_FORMAT = "tinix-credential-envelope"
    ENVELOPE_VERSION = 2
    ENVELOPE_SALT_BYTES = 16
    ENVELOPE_NONCE_BYTES = 12
    MIN_PASSWORD_LENGTH = 12
    PACKAGE_ENCRYPTION_ALGORITHM = "password_aes_256_gcm"
    ENCRYPTED_MAGIC = b"TINIX-PROFILES-ENC-v1\n"
    ENCRYPTED_ALGORITHM = "AES-256-GCM"
    ENCRYPTED_KDF = "PBKDF2-HMAC-SHA256"
    ENCRYPTED_KDF_ITERATIONS = 600_000
    ENCRYPTED_CHUNK_BYTES = 1024 * 1024
    ENCRYPTED_HEADER_LIMIT = 4096
    MAX_ARCHIVE_FILES = 250_000
    MAX_ARCHIVE_BYTES = 100 * 1024 * 1024 * 1024
    ACCOUNT_FIELD_LIMITS = {
        "username": 500, "email": 500, "password": 2_000,
        "secret_2fa": 500, "email_pass": 2_000, "cookie": 200_000,
        "recovery_codes": 10_000,
    }

    def __init__(
        self,
        settings: Settings,
        database: Database,
        accounts: AccountRepository,
        secrets: SecretProtector | None = None,
        path_in_use: Callable[[Path], bool] | None = None,
    ) -> None:
        self.settings = settings
        self.db = database
        self.accounts = accounts
        self.secrets = secrets or accounts.secrets
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
    def _validate_package_password(cls, password: str | None, *, required: bool = True) -> str:
        if required:
            if not password or not isinstance(password, str) or len(password.strip()) < cls.MIN_PASSWORD_LENGTH:
                raise ProfileTransferError(
                    f"Xuất thông tin xác thực yêu cầu mật khẩu gói tối thiểu {cls.MIN_PASSWORD_LENGTH} ký tự."
                )
            return password
        if password is not None:
            if not isinstance(password, str) or not password.strip():
                raise ProfileTransferError("Mật khẩu gói không được để trống.")
        return password or ""

    @classmethod
    def _credential_aad(
        cls,
        *,
        bundle_format: str,
        format_version: int,
        account_name: str,
        platform: str,
        profile_path: str,
        source_account_id: str,
        field: str,
    ) -> bytes:
        return (
            f"tinix-credential-envelope-v2|bundle:{bundle_format}|version:{format_version}"
            f"|account:{account_name}|platform:{platform}|path:{profile_path}"
            f"|id:{source_account_id}|field:{field}"
        ).encode("utf-8")

    @classmethod
    def _validate_account_metadata(cls, metadata: dict[str, Any]) -> dict[str, Any]:
        result = dict(metadata)
        for field, limit in cls.ACCOUNT_FIELD_LIMITS.items():
            value = metadata.get(field, "")
            if value is None:
                value = ""
            if not isinstance(value, str) or len(value) > limit:
                raise ProfileTransferError(f"Trường {field} trong ZIP không hợp lệ.")
            result[field] = value
        return result

    def _encrypt_account_credentials(
        self,
        account: dict[str, Any],
        *,
        cipher: AESGCM,
        bundle_format: str,
        format_version: int,
        profile_path: str,
    ) -> dict[str, dict[str, str]]:
        envelope: dict[str, dict[str, str]] = {}
        account_name = str(account.get("name") or account.get("account_name") or "").strip()
        platform = str(account.get("platform") or "").strip().lower()
        source_account_id = str(account.get("id") or account.get("source_account_id") or "").strip()
        for field in AccountRepository.CREDENTIAL_FIELDS:
            value = account.get(field)
            if not value:
                continue
            text = str(value)
            if len(text) > self.ACCOUNT_FIELD_LIMITS[field]:
                raise ProfileTransferError(f"Trường {field} vượt quá độ dài tối đa cho phép.")
            nonce = os.urandom(self.ENVELOPE_NONCE_BYTES)
            aad = self._credential_aad(
                bundle_format=bundle_format,
                format_version=format_version,
                account_name=account_name,
                platform=platform,
                profile_path=profile_path,
                source_account_id=source_account_id,
                field=field,
            )
            ciphertext = cipher.encrypt(nonce, text.encode("utf-8"), aad)
            envelope[field] = {
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            }
        return envelope

    def _account_metadata_for_export(
        self,
        account: dict[str, Any],
        *,
        include_credentials: bool,
        envelope_cipher: AESGCM | None = None,
        bundle_format: str = "",
        format_version: int = 1,
        profile_path: str = "",
    ) -> dict[str, Any]:
        metadata = {
            "account_name": account["name"],
            "platform": account["platform"],
            "username": account.get("username") or "",
            "email": account.get("email") or "",
        }
        if include_credentials:
            if not envelope_cipher:
                raise ProfileTransferError("Thiếu thông tin mã hóa cho phong bì xác thực.")
            metadata["credentials_envelope"] = self._encrypt_account_credentials(
                account,
                cipher=envelope_cipher,
                bundle_format=bundle_format,
                format_version=format_version,
                profile_path=profile_path,
            )
        return metadata

    def _prepare_envelope_cipher(
        self,
        manifest: dict[str, Any],
        password: str | None,
        *,
        was_package_encrypted: bool,
    ) -> AESGCM | None:
        if not isinstance(manifest, dict):
            raise ProfileTransferError("Manifest gói profile không hợp lệ.")
        protection = manifest.get("credential_protection")
        if protection != self.CREDENTIAL_PROTECTION_PORTABLE_V2:
            return None
        if not was_package_encrypted or manifest.get("package_encryption") != self.PACKAGE_ENCRYPTION_ALGORITHM:
            raise ProfileTransferError(
                "Gói profile chứa thông tin xác thực portable phải được mã hóa toàn bộ bằng mật khẩu."
            )
        if not password:
            raise ProfileTransferError("Gói profile đã mã hóa cần mật khẩu để tiếp tục.")

        envelope = manifest.get("credential_envelope")
        if not isinstance(envelope, dict):
            raise ProfileTransferError("Gói profile thiếu thông tin phong bì xác thực (credential envelope).")
        if (
            envelope.get("format") != self.ENVELOPE_FORMAT
            or type(envelope.get("version")) is not int
            or envelope.get("version") != self.ENVELOPE_VERSION
            or envelope.get("algorithm") != self.ENCRYPTED_ALGORITHM
            or envelope.get("kdf") != self.ENCRYPTED_KDF
            or type(envelope.get("iterations")) is not int
            or envelope.get("iterations") != self.ENCRYPTED_KDF_ITERATIONS
        ):
            raise ProfileTransferError("Định dạng phong bì xác thực (credential envelope) không được hỗ trợ.")
        try:
            salt = base64.b64decode(envelope["salt"], validate=True)
            if len(salt) != self.ENVELOPE_SALT_BYTES:
                raise ValueError
        except Exception as exc:
            raise ProfileTransferError("Thông tin mã hóa phong bì xác thực không hợp lệ.") from exc

        envelope_key = self._derive_bundle_key(password, salt, envelope["iterations"])
        return AESGCM(envelope_key)

    def _decode_export_credentials(
        self,
        metadata: dict[str, Any],
        manifest: dict[str, Any],
        *,
        password: str | None = None,
        was_package_encrypted: bool = False,
        envelope_cipher: AESGCM | None = None,
    ) -> dict[str, Any]:
        if not isinstance(manifest, dict) or not isinstance(metadata, dict):
            raise ProfileTransferError("Manifest hoặc metadata account trong gói profile không hợp lệ.")
        result = dict(metadata)
        protection = manifest.get("credential_protection")
        contains_flag = manifest.get("contains_account_secrets")
        if type(contains_flag) is not bool:
            raise ProfileTransferError("Cờ credential trong manifest không hợp lệ.")
        contains_secrets = contains_flag
        if contains_secrets != bool(protection):
            raise ProfileTransferError("Manifest gói profile có khai báo credential mâu thuẫn.")
        has_top_envelope = manifest.get("credential_envelope") is not None
        if has_top_envelope != (protection == self.CREDENTIAL_PROTECTION_PORTABLE_V2):
            raise ProfileTransferError("Manifest gói profile có phong bì credential mâu thuẫn.")

        for field in AccountRepository.CREDENTIAL_FIELDS:
            if field in result:
                raise ProfileTransferError(f"Gói profile chứa trường {field} dạng không mã hóa.")

        if not contains_secrets and not protection:
            if "credentials_protected" in result or "credentials_envelope" in result:
                raise ProfileTransferError("Gói profile chứa thông tin xác thực bất thường.")
            return self._validate_account_metadata(result)

        if protection == self.CREDENTIAL_PROTECTION_DPAPI:
            if "credentials_envelope" in result:
                raise ProfileTransferError("Gói DPAPI không được chứa phong bì credential portable.")
            protected = result.pop("credentials_protected", None)
            if protected is None:
                return self._validate_account_metadata(result)
            if not isinstance(protected, dict):
                raise ProfileTransferError("Credential trong gói profile không hợp lệ.")
            for field in AccountRepository.CREDENTIAL_FIELDS:
                encoded = protected.get(field, "")
                if not isinstance(encoded, str) or len(encoded) > 500_000:
                    raise ProfileTransferError("Credential trong gói profile không hợp lệ.")
                if encoded:
                    try:
                        result[field] = self.secrets.unprotect_secret(encoded)
                    except (ValueError, OSError) as exc:
                        raise ProfileTransferError(
                            "Credential trong gói chỉ có thể được Import bởi cùng tài khoản Windows đã Export."
                        ) from exc
            return self._validate_account_metadata(result)

        if protection == self.CREDENTIAL_PROTECTION_PORTABLE_V2:
            if "credentials_protected" in result:
                raise ProfileTransferError("Gói portable không được chứa credential DPAPI.")
            if not was_package_encrypted or manifest.get("package_encryption") != self.PACKAGE_ENCRYPTION_ALGORITHM:
                raise ProfileTransferError(
                    "Gói profile chứa thông tin xác thực portable phải được mã hóa toàn bộ bằng mật khẩu."
                )
            if not envelope_cipher:
                raise ProfileTransferError("Gói profile chứa thông tin xác thực cần mật khẩu để giải mã.")

            envelope_data = result.pop("credentials_envelope", None)
            if envelope_data is None:
                return self._validate_account_metadata(result)
            if not isinstance(envelope_data, dict):
                raise ProfileTransferError("Thông tin phong bì xác thực của tài khoản không hợp lệ.")
            if set(envelope_data) - set(AccountRepository.CREDENTIAL_FIELDS):
                raise ProfileTransferError("Phong bì chứa trường credential không được hỗ trợ.")

            account_name = str(result.get("account_name") or "").strip()
            platform = str(result.get("platform") or "").strip().lower()
            profile_path = str(result.get("profile_path") or "").replace("\\", "/").strip("/")
            source_account_id = str(result.get("source_account_id") or "").strip()
            bundle_format = str(manifest.get("bundle_format") or "")
            format_version = int(manifest.get("format_version") or 0)

            for field in AccountRepository.CREDENTIAL_FIELDS:
                entry = envelope_data.get(field)
                if entry is None:
                    continue
                if (
                    not isinstance(entry, dict)
                    or set(entry) != {"nonce", "ciphertext"}
                    or not isinstance(entry.get("nonce"), str)
                    or not isinstance(entry.get("ciphertext"), str)
                ):
                    raise ProfileTransferError(f"Cấu trúc phong bì của trường {field} không hợp lệ.")
                try:
                    nonce = base64.b64decode(entry["nonce"], validate=True)
                    ciphertext = base64.b64decode(entry["ciphertext"], validate=True)
                except (ValueError, TypeError, binascii.Error) as exc:
                    raise ProfileTransferError(f"Dữ liệu mã hóa của trường {field} không hợp lệ.") from exc
                if len(nonce) != self.ENVELOPE_NONCE_BYTES or len(ciphertext) <= 16:
                    raise ProfileTransferError(f"Độ dài mã hóa của trường {field} không hợp lệ.")

                aad = self._credential_aad(
                    bundle_format=bundle_format,
                    format_version=format_version,
                    account_name=account_name,
                    platform=platform,
                    profile_path=profile_path,
                    source_account_id=source_account_id,
                    field=field,
                )
                try:
                    plain_bytes = envelope_cipher.decrypt(nonce, ciphertext, aad)
                    plain_text = plain_bytes.decode("utf-8")
                except InvalidTag as exc:
                    raise ProfileTransferError(
                        "Mật khẩu không đúng hoặc thông tin xác thực đã bị thay đổi."
                    ) from exc
                except UnicodeDecodeError as exc:
                    raise ProfileTransferError(
                        "Thông tin xác thực trong gói profile bị hỏng."
                    ) from exc

                if len(plain_text) > self.ACCOUNT_FIELD_LIMITS[field]:
                    raise ProfileTransferError(f"Trường {field} trong gói profile vượt giới hạn độ dài.")
                result[field] = plain_text

            return self._validate_account_metadata(result)

        raise ProfileTransferError(f"Cơ chế bảo vệ thông tin xác thực không được hỗ trợ: {protection}.")

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

    @classmethod
    def _copy_session_profile(cls, source: Path, destination: Path) -> tuple[int, int]:
        """Copy only Chrome state required to carry a signed-in web session."""
        files = 0
        total = 0
        destination.mkdir(parents=True, exist_ok=False)

        def copy_file(source_file: Path, destination_file: Path) -> None:
            nonlocal files, total
            if not source_file.is_file() or cls._is_reparse(source_file):
                return
            destination_file.parent.mkdir(parents=True, exist_ok=True)
            size = source_file.stat(follow_symlinks=False).st_size
            shutil.copy2(source_file, destination_file)
            files += 1
            total += size

        for item in source.iterdir():
            if item.is_file() and item.name.lower() in cls.SESSION_ROOT_FILES:
                copy_file(item, destination / item.name)

        profile_directories = [source / "Default", *source.glob("Profile *")]
        for profile in profile_directories:
            if not profile.is_dir() or cls._is_reparse(profile):
                continue
            target_profile = destination / profile.name
            target_profile.mkdir(parents=True, exist_ok=True)
            for item in profile.iterdir():
                lowered = item.name.lower()
                if item.is_file() and lowered in cls.SESSION_PROFILE_FILES:
                    copy_file(item, target_profile / item.name)
                elif item.is_dir() and lowered == "network":
                    for network_file in item.iterdir():
                        if network_file.is_file() and network_file.name.lower() in cls.SESSION_PROFILE_FILES:
                            copy_file(network_file, target_profile / item.name / network_file.name)
                elif item.is_dir() and lowered in cls.SESSION_PROFILE_DIRECTORIES:
                    copied_files, copied_size = cls._copy_tree(item, target_profile / item.name)
                    files += copied_files
                    total += copied_size

        cls._validate_profile(destination)
        return files, total

    @classmethod
    def _cleanup_candidates(cls, profile: Path) -> list[tuple[Path, int, int]]:
        candidates: list[tuple[Path, int, int]] = []

        def directory_size(path: Path) -> tuple[int, int]:
            count = 0
            size = 0
            for root, directories, filenames in os.walk(path, followlinks=False):
                directories[:] = [name for name in directories if not cls._is_reparse(Path(root) / name)]
                for name in filenames:
                    item = Path(root) / name
                    if cls._is_reparse(item):
                        continue
                    try:
                        size += item.stat(follow_symlinks=False).st_size
                        count += 1
                    except OSError:
                        continue
            return count, size

        def visit(current: Path) -> None:
            with os.scandir(current) as entries:
                for entry in entries:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    item = Path(entry.path)
                    if cls._is_reparse(item):
                        continue
                    if entry.name.lower() in cls.CLEANUP_DIRECTORIES:
                        count, size = directory_size(item)
                        candidates.append((item, count, size))
                    else:
                        visit(item)

        visit(profile)
        return candidates

    def profile_cleanup_preview(self) -> dict[str, Any]:
        profiles = []
        total_files = 0
        total_bytes = 0
        chrome_running = 0
        for account in self.accounts.list():
            _, profile = self._account_and_target(account["id"])
            if not profile.exists():
                continue
            self._validate_profile(profile)
            candidates = self._cleanup_candidates(profile)
            files = sum(item[1] for item in candidates)
            size = sum(item[2] for item in candidates)
            running = self.path_in_use(profile)
            chrome_running += int(running)
            total_files += files
            total_bytes += size
            profiles.append({
                "account_id": account["id"], "account_name": account["name"],
                "files": files, "bytes": size, "chrome_running": running,
            })
        return {
            "profiles_scanned": len(profiles), "chrome_running": chrome_running,
            "files_removable": total_files, "bytes_removable": total_bytes,
            "profiles": profiles,
        }

    def cleanup_profiles(self) -> dict[str, Any]:
        preview = self.profile_cleanup_preview()
        if preview["chrome_running"]:
            raise ProfileTransferError("Chrome đang sử dụng một hoặc nhiều profile. Hãy đóng tất cả Chrome trước khi dọn dẹp.")
        removed_directories = 0
        removed_files = 0
        bytes_freed = 0
        profiles_cleaned = 0
        for account in self.accounts.list():
            _, profile = self._account_and_target(account["id"])
            if not profile.exists():
                continue
            self._validate_profile(profile)
            self._ensure_available(profile)
            candidates = self._cleanup_candidates(profile)
            if candidates:
                profiles_cleaned += 1
            for path, files, size in candidates:
                shutil.rmtree(path)
                removed_directories += 1
                removed_files += files
                bytes_freed += size
        return {
            "profiles_scanned": preview["profiles_scanned"],
            "profiles_cleaned": profiles_cleaned,
            "directories_removed": removed_directories,
            "files_removed": removed_files,
            "bytes_freed": bytes_freed,
        }

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

    def _read_bundle(self, bundle_path: str, password: str | None = None) -> tuple[Path, dict[str, Any], Path]:
        bundle = Path(os.path.expandvars(os.path.expanduser(bundle_path))).resolve()
        if not bundle.is_absolute() or not bundle.is_dir() or self._is_reparse(bundle):
            raise ProfileTransferError("Gói Tinix profile không tồn tại hoặc không an toàn.")
        manifest_path = bundle / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProfileTransferError("Gói profile thiếu manifest.json hợp lệ.") from exc
        if not isinstance(manifest, dict):
            raise ProfileTransferError("Manifest gói profile không hợp lệ.")
        if (
            manifest.get("bundle_format") != self.BUNDLE_FORMAT
            or type(manifest.get("format_version")) is not int
            or manifest.get("format_version") != self.BUNDLE_VERSION
        ):
            raise ProfileTransferError("Định dạng gói Tinix profile không được hỗ trợ.")
        name = str(manifest.get("account_name") or "").strip()
        platform = str(manifest.get("platform") or "").strip().lower()
        if not name or len(name) > 100:
            raise ProfileTransferError("Tên account trong manifest không hợp lệ.")
        if platform not in {"facebook", "instagram", "tiktok", "youtube", "x"}:
            raise ProfileTransferError(f"Nền tảng trong gói chưa được Social Hub hỗ trợ: {platform or 'trống'}.")
        profile = (bundle / "chrome-profile").resolve()
        if profile.parent != bundle:
            raise ProfileTransferError("Đường dẫn Chrome profile trong gói không hợp lệ.")
        self._validate_profile(profile)
        envelope_cipher = self._prepare_envelope_cipher(manifest, password, was_package_encrypted=False)
        decoded = self._decode_export_credentials(
            manifest,
            manifest,
            password=password,
            was_package_encrypted=False,
            envelope_cipher=envelope_cipher,
        )
        return bundle, decoded, profile

    def import_bundle(self, bundle_path: str, password: str | None = None) -> dict[str, Any]:
        source = Path(os.path.expandvars(os.path.expanduser(bundle_path))).resolve()
        if source.is_file():
            result = self.import_all_profiles(str(source), password=password)
            if not result.get("accounts"):
                raise ProfileTransferError("Gói profile không có account nào để import.")
            account = result["accounts"][0]
            target = (self.settings.chrome_profile_dir / account["profile_key"]).resolve()
            return {
                "profile_path": str(target),
                "backup_name": None,
                "files_copied": 0,
                "bytes_copied": 0,
                "account": account,
                "source_app": result.get("source_app"),
                "source_account_id": account.get("id"),
            }
        _, manifest, profile = self._read_bundle(bundle_path, password=password)
        account = self.accounts.create(manifest["account_name"], manifest["platform"], metadata=manifest)
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

    @classmethod
    def _extract_archive(cls, archive: Path, destination: Path) -> None:
        if not archive.is_absolute() or not archive.is_file() or cls._is_reparse(archive):
            raise ProfileTransferError("File ZIP Tinix profile không tồn tại hoặc không an toàn.")
        try:
            with zipfile.ZipFile(archive) as bundle:
                entries = bundle.infolist()
                if len(entries) > cls.MAX_ARCHIVE_FILES:
                    raise ProfileTransferError("File ZIP chứa quá nhiều mục.")
                declared_size = sum(item.file_size for item in entries)
                if declared_size > cls.MAX_ARCHIVE_BYTES:
                    raise ProfileTransferError("File ZIP vượt giới hạn dung lượng giải nén 100 GB.")
                seen: set[str] = set()
                copied = 0
                root = destination.resolve()
                for item in entries:
                    relative = item.filename.replace("\\", "/").strip("/")
                    parts = [part for part in relative.split("/") if part]
                    if not parts:
                        continue
                    if any(part in {".", ".."} for part in parts) or ":" in parts[0]:
                        raise ProfileTransferError("File ZIP chứa đường dẫn không an toàn.")
                    key = "/".join(parts).lower()
                    if key in seen:
                        raise ProfileTransferError("File ZIP chứa đường dẫn trùng lặp.")
                    seen.add(key)
                    mode = (item.external_attr >> 16) & 0o170000
                    if mode == 0o120000:
                        raise ProfileTransferError("File ZIP chứa symlink không an toàn.")
                    target = (root.joinpath(*parts)).resolve()
                    if root not in target.parents and target != root:
                        raise ProfileTransferError("File ZIP chứa đường dẫn vượt ra ngoài thư mục giải nén.")
                    if item.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(item) as source, target.open("wb") as output:
                        while chunk := source.read(1024 * 1024):
                            copied += len(chunk)
                            if copied > cls.MAX_ARCHIVE_BYTES:
                                raise ProfileTransferError("File ZIP vượt giới hạn dung lượng giải nén 100 GB.")
                            output.write(chunk)
        except (zipfile.BadZipFile, OSError) as exc:
            raise ProfileTransferError("Không đọc được file ZIP Tinix profile.") from exc

    @classmethod
    def _is_encrypted_collection(cls, source: Path) -> bool:
        if not source.is_absolute() or not source.is_file() or cls._is_reparse(source):
            raise ProfileTransferError("Gói profile không tồn tại hoặc không an toàn.")
        try:
            with source.open("rb") as payload:
                return payload.read(len(cls.ENCRYPTED_MAGIC)) == cls.ENCRYPTED_MAGIC
        except OSError as exc:
            raise ProfileTransferError("Không thể đọc gói profile.") from exc

    @classmethod
    def _derive_bundle_key(cls, password: str, salt: bytes, iterations: int) -> bytes:
        if not password:
            raise ProfileTransferError("Gói profile đã mã hóa cần mật khẩu để tiếp tục.")
        if len(salt) != 16 or iterations != cls.ENCRYPTED_KDF_ITERATIONS:
            raise ProfileTransferError("Thông tin mã hóa của gói profile không hợp lệ.")
        return PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations,
        ).derive(password.encode("utf-8"))

    @classmethod
    def _encryption_header(cls, salt: bytes, nonce_prefix: bytes) -> bytes:
        return json.dumps(
            {
                "algorithm": cls.ENCRYPTED_ALGORITHM,
                "kdf": cls.ENCRYPTED_KDF,
                "iterations": cls.ENCRYPTED_KDF_ITERATIONS,
                "salt": base64.b64encode(salt).decode("ascii"),
                "nonce_prefix": base64.b64encode(nonce_prefix).decode("ascii"),
                "chunk_size": cls.ENCRYPTED_CHUNK_BYTES,
            }, separators=(",", ":"), sort_keys=True,
        ).encode("ascii")

    @classmethod
    def _parse_encryption_header(cls, raw: bytes) -> tuple[bytes, bytes, int]:
        if not raw or len(raw) > cls.ENCRYPTED_HEADER_LIMIT:
            raise ProfileTransferError("Thông tin mã hóa của gói profile không hợp lệ.")
        try:
            header = json.loads(raw.decode("ascii"))
            salt = base64.b64decode(header["salt"], validate=True)
            nonce_prefix = base64.b64decode(header["nonce_prefix"], validate=True)
            iterations = int(header["iterations"])
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
            raise ProfileTransferError("Thông tin mã hóa của gói profile không hợp lệ.") from exc
        if not isinstance(header, dict):
            raise ProfileTransferError("Thông tin mã hóa của gói profile không hợp lệ.")
        if (
            header.get("algorithm") != cls.ENCRYPTED_ALGORITHM
            or header.get("kdf") != cls.ENCRYPTED_KDF
            or header.get("chunk_size") != cls.ENCRYPTED_CHUNK_BYTES
            or len(nonce_prefix) != 8
        ):
            raise ProfileTransferError("Gói profile sử dụng định dạng mã hóa không được hỗ trợ.")
        return salt, nonce_prefix, iterations

    @classmethod
    def _encrypt_archive(cls, source: Path, destination: Path, password: str) -> None:
        salt, nonce_prefix = os.urandom(16), os.urandom(8)
        header = cls._encryption_header(salt, nonce_prefix)
        cipher = AESGCM(cls._derive_bundle_key(password, salt, cls.ENCRYPTED_KDF_ITERATIONS))
        try:
            with source.open("rb") as plain, destination.open("xb") as encrypted:
                encrypted.write(cls.ENCRYPTED_MAGIC)
                encrypted.write(header + b"\n")
                for index in range(0x1_0000_0000):
                    chunk = plain.read(cls.ENCRYPTED_CHUNK_BYTES)
                    if not chunk:
                        encrypted.write(struct.pack(">I", 0))
                        break
                    counter = struct.pack(">I", index)
                    protected = cipher.encrypt(nonce_prefix + counter, chunk, header + counter)
                    encrypted.write(struct.pack(">I", len(protected)))
                    encrypted.write(protected)
                else:
                    raise ProfileTransferError("Gói profile vượt giới hạn mã hóa.")
        except OSError as exc:
            raise ProfileTransferError("Không thể ghi gói profile đã mã hóa.") from exc

    @classmethod
    def _decrypt_encrypted_archive(cls, source: Path, destination: Path, password: str) -> None:
        try:
            with source.open("rb") as encrypted:
                if encrypted.read(len(cls.ENCRYPTED_MAGIC)) != cls.ENCRYPTED_MAGIC:
                    raise ProfileTransferError("Gói profile mã hóa không hợp lệ.")
                header = encrypted.readline(cls.ENCRYPTED_HEADER_LIMIT + 1).rstrip(b"\r\n")
                if len(header) > cls.ENCRYPTED_HEADER_LIMIT:
                    raise ProfileTransferError("Thông tin mã hóa của gói profile không hợp lệ.")
                salt, nonce_prefix, iterations = cls._parse_encryption_header(header)
                cipher = AESGCM(cls._derive_bundle_key(password, salt, iterations))
                copied = 0
                with destination.open("xb") as plain:
                    for index in range(0x1_0000_0000):
                        raw_length = encrypted.read(4)
                        if len(raw_length) != 4:
                            raise ProfileTransferError("Gói profile mã hóa bị thiếu dữ liệu.")
                        length = struct.unpack(">I", raw_length)[0]
                        if length == 0:
                            if encrypted.read(1):
                                raise ProfileTransferError("Gói profile mã hóa có dữ liệu dư.")
                            break
                        if length > cls.ENCRYPTED_CHUNK_BYTES + 16:
                            raise ProfileTransferError("Gói profile mã hóa có block không hợp lệ.")
                        protected = encrypted.read(length)
                        if len(protected) != length:
                            raise ProfileTransferError("Gói profile mã hóa bị thiếu dữ liệu.")
                        counter = struct.pack(">I", index)
                        try:
                            chunk = cipher.decrypt(nonce_prefix + counter, protected, header + counter)
                        except InvalidTag as exc:
                            raise ProfileTransferError("Mật khẩu không đúng hoặc gói profile đã bị thay đổi.") from exc
                        copied += len(chunk)
                        if copied > cls.MAX_ARCHIVE_BYTES:
                            raise ProfileTransferError("Gói profile vượt giới hạn dung lượng 100 GB.")
                        plain.write(chunk)
                    else:
                        raise ProfileTransferError("Gói profile vượt giới hạn mã hóa.")
        except OSError as exc:
            raise ProfileTransferError("Không thể đọc gói profile đã mã hóa.") from exc

    def _read_collection(
        self,
        root: Path,
        password: str | None = None,
        *,
        was_package_encrypted: bool = False,
    ) -> tuple[dict[str, Any], list[tuple[dict[str, Any], Path]]]:
        try:
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProfileTransferError("File ZIP thiếu manifest.json hợp lệ.") from exc
        if not isinstance(manifest, dict):
            raise ProfileTransferError("Manifest gói profile không hợp lệ.")
        if (
            manifest.get("bundle_format") != self.COLLECTION_FORMAT
            or type(manifest.get("format_version")) is not int
            or manifest.get("format_version") != self.COLLECTION_VERSION
        ):
            raise ProfileTransferError("Định dạng ZIP đa profile không được hỗ trợ.")
        raw_accounts = manifest.get("accounts")
        if not isinstance(raw_accounts, list) or not raw_accounts or len(raw_accounts) > 10_000:
            raise ProfileTransferError("Danh sách account trong ZIP không hợp lệ.")

        envelope_cipher = self._prepare_envelope_cipher(
            manifest, password, was_package_encrypted=was_package_encrypted
        )

        result: list[tuple[dict[str, Any], Path]] = []
        profiles_root = (root / "profiles").resolve()
        for raw in raw_accounts:
            if not isinstance(raw, dict):
                raise ProfileTransferError("Metadata account trong ZIP không hợp lệ.")
            name = str(raw.get("account_name") or "").strip()
            platform = str(raw.get("platform") or "").strip().lower()
            profile_key = str(raw.get("profile_path") or "").replace("\\", "/").strip("/")
            if not name or len(name) > 100 or platform not in {"facebook", "instagram", "tiktok", "youtube", "x"}:
                raise ProfileTransferError("Tên hoặc nền tảng account trong ZIP không hợp lệ.")
            profile = (root / profile_key).resolve()
            if profiles_root not in profile.parents or profile == profiles_root:
                raise ProfileTransferError("Đường dẫn profile trong manifest không hợp lệ.")
            self._validate_profile(profile)
            decoded = self._decode_export_credentials(
                {**raw, "account_name": name, "platform": platform, "profile_path": profile_key},
                manifest,
                password=password,
                was_package_encrypted=was_package_encrypted,
                envelope_cipher=envelope_cipher,
            )
            result.append((decoded, profile))
        return manifest, result

    def export_all_profiles(
        self, include_credentials: bool = False, password: str | None = None,
    ) -> dict[str, Any]:
        if include_credentials:
            password = self._validate_package_password(password, required=True)
        else:
            self._validate_package_password(password, required=False)

        accounts = self.accounts.list()
        if not accounts:
            raise ProfileTransferError("App chưa có account để Export.")
        sources: list[tuple[dict[str, Any], Path]] = []
        for account in accounts:
            _, source = self._account_and_target(account["id"])
            try:
                self._validate_profile(source)
                self._ensure_available(source)
            except ProfileTransferError as exc:
                raise ProfileTransferError(f"Không thể Export account “{account['name']}”: {exc}") from exc
            sources.append((account, source))

        from app import __version__
        encrypted = bool(password)
        extension = ".tinix-profiles.enc" if encrypted else ".tinix-profiles.zip"
        destination = self.export_root / f"Tinix-Social-Hub-all-profiles-{self._timestamp()}{extension}"
        staging = Path(tempfile.mkdtemp(prefix=".tinix-profiles-", dir=self.export_root))
        temporary_zip = self.export_root / f".{uuid.uuid4()}.tinix-profiles.zip"
        temporary_encrypted = self.export_root / f".{uuid.uuid4()}.tinix-profiles.enc"
        files = 0
        size = 0
        manifest_accounts: list[dict[str, Any]] = []

        envelope_cipher: AESGCM | None = None
        envelope_manifest: dict[str, Any] | None = None
        if include_credentials:
            envelope_salt = os.urandom(self.ENVELOPE_SALT_BYTES)
            envelope_key = self._derive_bundle_key(password, envelope_salt, self.ENCRYPTED_KDF_ITERATIONS)
            envelope_cipher = AESGCM(envelope_key)
            envelope_manifest = {
                "format": self.ENVELOPE_FORMAT,
                "version": self.ENVELOPE_VERSION,
                "algorithm": self.ENCRYPTED_ALGORITHM,
                "kdf": self.ENCRYPTED_KDF,
                "iterations": self.ENCRYPTED_KDF_ITERATIONS,
                "salt": base64.b64encode(envelope_salt).decode("ascii"),
            }

        try:
            for index, (account, source) in enumerate(sources, 1):
                relative = f"profiles/{index:04d}"
                copied_files, copied_size = self._copy_session_profile(source, staging / relative)
                files += copied_files
                size += copied_size
                manifest_accounts.append({
                    **self._account_metadata_for_export(
                        account,
                        include_credentials=include_credentials,
                        envelope_cipher=envelope_cipher,
                        bundle_format=self.COLLECTION_FORMAT,
                        format_version=self.COLLECTION_VERSION,
                        profile_path=relative,
                    ),
                    "source_account_id": account["id"],
                    "profile_path": relative,
                })
            manifest = {
                "bundle_format": self.COLLECTION_FORMAT,
                "format_version": self.COLLECTION_VERSION,
                "source_app": "Tinix Social Hub",
                "source_app_version": __version__,
                "profile_content": "session-only-v1",
                "contains_account_secrets": include_credentials,
                "credential_protection": self.CREDENTIAL_PROTECTION_PORTABLE_V2 if include_credentials else None,
                "package_encryption": self.PACKAGE_ENCRYPTION_ALGORITHM if encrypted else None,
                "credential_envelope": envelope_manifest if include_credentials else None,
                "exported_at": utc_now(),
                "accounts": manifest_accounts,
            }
            (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            with zipfile.ZipFile(temporary_zip, "w", zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=6) as archive:
                for item in staging.rglob("*"):
                    if item.is_file():
                        archive.write(item, item.relative_to(staging).as_posix())
            if encrypted:
                self._encrypt_archive(temporary_zip, temporary_encrypted, password or "")
                temporary_zip.unlink()
                os.replace(temporary_encrypted, destination)
            else:
                os.replace(temporary_zip, destination)
        except Exception:
            if temporary_zip.exists():
                temporary_zip.unlink()
            if temporary_encrypted.exists():
                temporary_encrypted.unlink()
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return {
            "archive_path": str(destination), "bundle_path": str(destination),
            "accounts_exported": len(manifest_accounts), "files_copied": files, "bytes_copied": size,
            "credentials_included": include_credentials,
            "credential_protection": self.CREDENTIAL_PROTECTION_PORTABLE_V2 if include_credentials else None,
            "package_encrypted": encrypted,
            "package_encryption": self.PACKAGE_ENCRYPTION_ALGORITHM if encrypted else None,
        }

    def import_all_profiles(self, bundle_path: str, password: str | None = None) -> dict[str, Any]:
        source = Path(os.path.expandvars(os.path.expanduser(bundle_path))).resolve()
        if source.is_dir():
            imported = self.import_bundle(bundle_path, password=password)
            return {"accounts_imported": 1, "accounts": [imported["account"]], "source_app": imported.get("source_app")}
        workspace = Path(tempfile.mkdtemp(prefix="tinix-profiles-import-"))
        extraction = workspace / "extracted"
        extraction.mkdir()
        created: list[dict[str, Any]] = []
        try:
            archive = source
            was_encrypted = self._is_encrypted_collection(source)
            if was_encrypted:
                archive = workspace / "bundle.zip"
                self._decrypt_encrypted_archive(source, archive, password or "")
            self._extract_archive(archive, extraction)
            manifest, entries = self._read_collection(
                extraction, password=password, was_package_encrypted=was_encrypted
            )
            for metadata, profile in entries:
                account = self.accounts.create(metadata["account_name"], metadata["platform"], metadata=metadata)
                created.append(account)
                self.import_profile(account["id"], str(profile))
            return {
                "accounts_imported": len(created), "accounts": [self.accounts.get(item["id"]) for item in created],
                "source_app": manifest.get("source_app"),
            }
        except Exception:
            for account in reversed(created):
                target = (self.settings.chrome_profile_dir / account["profile_key"]).resolve()
                if target.exists() and target.parent == self.settings.chrome_profile_dir.resolve():
                    shutil.rmtree(target)
                self.accounts.delete_if_safe(account["id"])
            raise
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

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
        _, target = self._account_and_target(account_id)
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

    def export_profile(
        self, account_id: str, include_credentials: bool = False, password: str | None = None,
    ) -> dict[str, Any]:
        if include_credentials:
            password = self._validate_package_password(password, required=True)
        else:
            self._validate_package_password(password, required=False)

        account, source = self._account_and_target(account_id)
        if password:
            destination = self.export_root / (
                f"{self._safe_label(account['name'])}-{self._timestamp()}.tinix-profiles.enc"
            )

            def encrypted_action() -> dict[str, Any]:
                self._validate_profile(source)
                self._ensure_available(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                staging = Path(tempfile.mkdtemp(prefix=".tinix-profile-", dir=destination.parent))
                temporary_zip = self.export_root / f".{uuid.uuid4()}.tinix-profiles.zip"
                temporary_encrypted = self.export_root / f".{uuid.uuid4()}.tinix-profiles.enc"
                try:
                    profile_path = "profiles/0001"
                    files, size = self._copy_session_profile(source, staging / profile_path)
                    from app import __version__

                    envelope_cipher: AESGCM | None = None
                    envelope_manifest: dict[str, Any] | None = None
                    if include_credentials:
                        envelope_salt = os.urandom(self.ENVELOPE_SALT_BYTES)
                        envelope_key = self._derive_bundle_key(password, envelope_salt, self.ENCRYPTED_KDF_ITERATIONS)
                        envelope_cipher = AESGCM(envelope_key)
                        envelope_manifest = {
                            "format": self.ENVELOPE_FORMAT,
                            "version": self.ENVELOPE_VERSION,
                            "algorithm": self.ENCRYPTED_ALGORITHM,
                            "kdf": self.ENCRYPTED_KDF,
                            "iterations": self.ENCRYPTED_KDF_ITERATIONS,
                            "salt": base64.b64encode(envelope_salt).decode("ascii"),
                        }

                    manifest = {
                        "bundle_format": self.COLLECTION_FORMAT,
                        "format_version": self.COLLECTION_VERSION,
                        "source_app": "Tinix Social Hub",
                        "source_app_version": __version__,
                        "profile_content": "session-only-v1",
                        "contains_account_secrets": include_credentials,
                        "credential_protection": self.CREDENTIAL_PROTECTION_PORTABLE_V2 if include_credentials else None,
                        "package_encryption": self.PACKAGE_ENCRYPTION_ALGORITHM,
                        "credential_envelope": envelope_manifest if include_credentials else None,
                        "exported_at": utc_now(),
                        "accounts": [{
                            **self._account_metadata_for_export(
                                account,
                                include_credentials=include_credentials,
                                envelope_cipher=envelope_cipher,
                                bundle_format=self.COLLECTION_FORMAT,
                                format_version=self.COLLECTION_VERSION,
                                profile_path=profile_path,
                            ),
                            "source_account_id": account["id"],
                            "profile_path": profile_path,
                        }],
                    }
                    (staging / "manifest.json").write_text(
                        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    with zipfile.ZipFile(
                        temporary_zip, "w", zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=6,
                    ) as archive:
                        for item in staging.rglob("*"):
                            if item.is_file():
                                archive.write(item, item.relative_to(staging).as_posix())
                    self._encrypt_archive(temporary_zip, temporary_encrypted, password)
                    temporary_zip.unlink()
                    os.replace(temporary_encrypted, destination)
                except Exception:
                    if temporary_zip.exists():
                        temporary_zip.unlink()
                    if temporary_encrypted.exists():
                        temporary_encrypted.unlink()
                    raise
                finally:
                    shutil.rmtree(staging, ignore_errors=True)
                return {
                    "export_path": str(destination), "bundle_path": str(destination),
                    "files_copied": files, "bytes_copied": size,
                    "credentials_included": include_credentials,
                    "credential_protection": self.CREDENTIAL_PROTECTION_PORTABLE_V2 if include_credentials else None,
                    "package_encrypted": True,
                    "package_encryption": self.PACKAGE_ENCRYPTION_ALGORITHM,
                }

            return self._run(account_id, "export", source, destination, encrypted_action)

        destination = self.export_root / f"{self._safe_label(account['name'])}-{self._timestamp()}.tinix-profile"

        def action() -> dict[str, Any]:
            self._validate_profile(source)
            self._ensure_available(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
            try:
                profile_destination = staging / "chrome-profile"
                files, size = self._copy_session_profile(source, profile_destination)
                self._validate_profile(profile_destination)
                from app import __version__
                manifest = {
                    "bundle_format": self.BUNDLE_FORMAT,
                    "format_version": self.BUNDLE_VERSION,
                    **self._account_metadata_for_export(account, include_credentials=False),
                    "source_app": "Tinix Social Hub",
                    "source_app_version": __version__,
                    "profile_content": "session-only-v1",
                    "contains_account_secrets": False,
                    "credential_protection": None,
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
                "credentials_included": False,
                "credential_protection": None,
                "package_encrypted": False,
                "package_encryption": None,
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
