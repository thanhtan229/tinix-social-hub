from __future__ import annotations

import base64
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from app.db.database import Database
from app.db.repositories import AccountRepository, JobRepository
from app.services.profile_transfer import (
    ChromeProfileTransferService,
    ProfileTransferError,
)


def make_profile(path: Path, cookie: str) -> Path:
    (path / "Default" / "Cache").mkdir(parents=True, exist_ok=True)
    (path / "Local State").write_text("{}", encoding="utf-8")
    (path / "Default" / "Preferences").write_text("{}", encoding="utf-8")
    (path / "Default" / "Cookies").write_text(cookie, encoding="utf-8")
    (path / "Default" / "Cache" / "ignored.bin").write_bytes(b"cache")
    (path / "optimization_guide_model_store").mkdir(exist_ok=True)
    (path / "optimization_guide_model_store" / "model.tflite").write_bytes(b"model-cache")
    (path / "SingletonLock").write_text("locked", encoding="utf-8")
    return path


class ProfileTransferTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = Database(self.root / "data" / "tinix_social.db", self.root / "backups")
        self.database.initialize()
        self.accounts = AccountRepository(self.database)
        self.jobs = JobRepository(self.database)
        self.account = self.accounts.create("Main Account", "facebook", metadata={
            "username": "main-user", "email": "main@example.com", "password": "fb-password",
            "secret_2fa": "JBSWY3DPEHPK3PXP", "email_pass": "mail-password", "cookie": "db-cookie",
        })
        settings = SimpleNamespace(
            chrome_profile_dir=self.root / "profiles",
            backup_dir=self.root / "backups",
            export_dir=self.root / "exports",
        )
        settings.chrome_profile_dir.mkdir(exist_ok=True)
        settings.export_dir.mkdir(exist_ok=True)
        self.service = ChromeProfileTransferService(settings, self.database, self.accounts, path_in_use=lambda _: False)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @property
    def target(self) -> Path:
        return self.root / "profiles" / self.account["profile_key"]

    def test_import_export_backup_and_restore_keep_recoverable_copies(self) -> None:
        source = make_profile(self.root / "external" / "fb_2", "session-v1")
        imported = self.service.import_profile(self.account["id"], str(source))
        self.assertEqual((self.target / "Default" / "Cookies").read_text(), "session-v1")
        self.assertFalse((self.target / "Default" / "Cache" / "ignored.bin").exists())
        self.assertFalse((self.target / "SingletonLock").exists())
        self.assertGreaterEqual(imported["files_copied"], 3)

        backup = self.service.backup_profile(self.account["id"])
        (self.target / "Default" / "Cookies").write_text("session-v2", encoding="utf-8")
        exported = self.service.export_profile(self.account["id"])
        bundle = Path(exported["bundle_path"])
        self.assertEqual((bundle / "chrome-profile" / "Default" / "Cookies").read_text(), "session-v2")
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["account_name"], manifest["platform"]), ("Main Account", "facebook"))

        imported_bundle = self.service.import_bundle(str(bundle))
        imported_account = imported_bundle["account"]
        imported_target = self.root / "profiles" / imported_account["profile_key"]
        self.assertEqual(imported_account["name"], "Main Account")
        self.assertEqual(imported_account["platform"], "facebook")
        self.assertEqual((imported_target / "Default" / "Cookies").read_text(), "session-v2")

        restored = self.service.restore_profile(self.account["id"], backup["backup_name"])
        self.assertEqual(restored["restored_from"], backup["backup_name"])
        self.assertEqual((self.target / "Default" / "Cookies").read_text(), "session-v1")
        self.assertTrue(restored["backup_name"].endswith("before-restore"))
        self.assertEqual(self.service.history(self.account["id"])[0]["status"], "succeeded")
        self.assertEqual(self.accounts.get(self.account["id"])["profile_operation_locked"], 0)

    def test_import_rejects_invalid_or_live_profile(self) -> None:
        invalid = self.root / "invalid"
        invalid.mkdir()
        with self.assertRaises(ProfileTransferError):
            self.service.import_profile(self.account["id"], str(invalid))

        source = make_profile(self.root / "external" / "fb_9", "session")
        busy_service = ChromeProfileTransferService(
            self.service.settings, self.database, self.accounts, path_in_use=lambda path: path == source.resolve()
        )
        with self.assertRaisesRegex(ProfileTransferError, "Chrome đang sử dụng"):
            busy_service.import_profile(self.account["id"], str(source))
        self.assertEqual(self.accounts.get(self.account["id"])["profile_operation_locked"], 0)

    def test_export_omits_credentials_by_default(self) -> None:
        make_profile(self.target, "facebook-session")
        exported = self.service.export_all_profiles()
        with zipfile.ZipFile(exported["archive_path"]) as bundle:
            manifest = json.loads(bundle.read("manifest.json"))
        self.assertFalse(manifest["contains_account_secrets"])
        self.assertIsNone(manifest.get("credential_protection"))
        self.assertIsNone(manifest.get("credential_envelope"))
        account = manifest["accounts"][0]
        self.assertNotIn("credentials_protected", account)
        self.assertNotIn("credentials_envelope", account)
        self.assertNotIn("password", account)

    def test_export_requires_strong_password_when_credentials_included(self) -> None:
        make_profile(self.target, "facebook-session")
        # Bulk export missing or short password
        with self.assertRaisesRegex(ProfileTransferError, "tối thiểu 12 ký tự"):
            self.service.export_all_profiles(include_credentials=True)
        with self.assertRaisesRegex(ProfileTransferError, "tối thiểu 12 ký tự"):
            self.service.export_all_profiles(include_credentials=True, password="")
        with self.assertRaisesRegex(ProfileTransferError, "tối thiểu 12 ký tự"):
            self.service.export_all_profiles(include_credentials=True, password="short-pass")

        # Single account export missing or short password
        with self.assertRaisesRegex(ProfileTransferError, "tối thiểu 12 ký tự"):
            self.service.export_profile(self.account["id"], include_credentials=True)
        with self.assertRaisesRegex(ProfileTransferError, "tối thiểu 12 ký tự"):
            self.service.export_profile(self.account["id"], include_credentials=True, password="short")

    def test_export_and_import_all_profiles_portable_v2(self) -> None:
        make_profile(self.target, "facebook-session")
        second = self.accounts.create("Video Account", "youtube", metadata={
            "username": "creator", "email": "creator@example.com", "password": "yt-password",
        })
        second_target = self.root / "profiles" / second["profile_key"]
        make_profile(second_target, "youtube-session")

        password = "strong-package-password-v2"
        exported = self.service.export_all_profiles(include_credentials=True, password=password)
        archive = Path(exported["archive_path"])
        self.assertTrue(archive.is_file())
        self.assertEqual(archive.suffix, ".enc")
        self.assertEqual(exported["accounts_exported"], 2)
        self.assertEqual(exported["credential_protection"], "portable_aes_256_gcm_v2")
        self.assertTrue(exported["package_encrypted"])

        # Decrypt outer archive to inspect manifest
        inner_zip = self.root / "decrypted_check.zip"
        self.service._decrypt_encrypted_archive(archive, inner_zip, password)
        with zipfile.ZipFile(inner_zip) as bundle:
            manifest = json.loads(bundle.read("manifest.json"))
            self.assertEqual(manifest["bundle_format"], "tinix-profiles")
            self.assertEqual(manifest["profile_content"], "session-only-v1")
            self.assertTrue(manifest["contains_account_secrets"])
            self.assertEqual(manifest["credential_protection"], "portable_aes_256_gcm_v2")
            self.assertEqual(manifest["package_encryption"], "password_aes_256_gcm")
            envelope = manifest["credential_envelope"]
            self.assertEqual(envelope["format"], "tinix-credential-envelope")
            self.assertEqual(envelope["version"], 2)
            self.assertEqual(envelope["algorithm"], "AES-256-GCM")
            self.assertEqual(envelope["kdf"], "PBKDF2-HMAC-SHA256")
            self.assertEqual(envelope["iterations"], 600_000)
            self.assertEqual(len(base64.b64decode(envelope["salt"])), 16)

            main_metadata = next(item for item in manifest["accounts"] if item["account_name"] == "Main Account")
            self.assertEqual(main_metadata["email"], "main@example.com")
            # Plaintext credentials must NEVER appear in manifest
            self.assertNotIn("password", main_metadata)
            self.assertNotIn("secret_2fa", main_metadata)
            self.assertNotIn("credentials_protected", main_metadata)
            # Credentials must be in versioned envelope with fresh nonces
            cred_env = main_metadata["credentials_envelope"]
            self.assertIn("password", cred_env)
            self.assertIn("secret_2fa", cred_env)
            self.assertEqual(len(base64.b64decode(cred_env["password"]["nonce"])), 12)
            self.assertGreater(len(base64.b64decode(cred_env["password"]["ciphertext"])), 16)

        imported = self.service.import_all_profiles(str(archive), password=password)
        self.assertEqual(imported["accounts_imported"], 2)
        imported_accounts = imported["accounts"]
        self.assertEqual({item["name"] for item in imported_accounts}, {"Main Account", "Video Account"})
        cookies = {
            item["name"]: (self.root / "profiles" / item["profile_key"] / "Default" / "Cookies").read_text(encoding="utf-8")
            for item in imported_accounts
        }
        self.assertEqual(cookies, {"Main Account": "facebook-session", "Video Account": "youtube-session"})

        imported_main = next(item for item in imported_accounts if item["name"] == "Main Account")
        self.assertEqual(imported_main["email"], "main@example.com")
        self.assertEqual(imported_main["password"], "fb-password")
        self.assertEqual(imported_main["secret_2fa"], "JBSWY3DPEHPK3PXP")
        self.assertEqual(imported_main["cookie"], "db-cookie")

        imported_video = next(item for item in imported_accounts if item["name"] == "Video Account")
        self.assertEqual(imported_video["password"], "yt-password")

    def test_export_and_import_single_account_portable_v2(self) -> None:
        make_profile(self.target, "single-session")
        password = "strong-single-account-pass"
        exported = self.service.export_profile(self.account["id"], include_credentials=True, password=password)
        archive = Path(exported["export_path"])
        self.assertTrue(archive.is_file())
        self.assertEqual(archive.suffix, ".enc")
        self.assertEqual(exported["credential_protection"], "portable_aes_256_gcm_v2")

        imported = self.service.import_all_profiles(str(archive), password=password)
        self.assertEqual(imported["accounts_imported"], 1)
        account = imported["accounts"][0]
        self.assertEqual(account["name"], "Main Account")
        self.assertEqual(account["password"], "fb-password")
        self.assertEqual(account["secret_2fa"], "JBSWY3DPEHPK3PXP")
        profile = self.root / "profiles" / account["profile_key"]
        self.assertEqual((profile / "Default" / "Cookies").read_text(encoding="utf-8"), "single-session")

    def test_password_encrypted_export_requires_the_correct_password(self) -> None:
        make_profile(self.target, "facebook-session")
        exported = self.service.export_all_profiles(password="correct horse battery staple")
        archive = Path(exported["archive_path"])
        self.assertEqual(archive.suffix, ".enc")
        self.assertTrue(exported["package_encrypted"])
        self.assertFalse(archive.read_bytes().startswith(b"PK"))
        with self.assertRaisesRegex(ProfileTransferError, "cần mật khẩu"):
            self.service.import_all_profiles(str(archive))
        with self.assertRaisesRegex(ProfileTransferError, "Mật khẩu không đúng"):
            self.service.import_all_profiles(str(archive), password="not-the-password")

        imported = self.service.import_all_profiles(str(archive), password="correct horse battery staple")
        self.assertEqual(imported["accounts_imported"], 1)
        profile = self.root / "profiles" / imported["accounts"][0]["profile_key"]
        self.assertEqual((profile / "Default" / "Cookies").read_text(encoding="utf-8"), "facebook-session")

    def test_tampered_envelope_or_metadata_rejected(self) -> None:
        make_profile(self.target, "facebook-session")
        password = "strong-tamper-test-password"
        exported = self.service.export_all_profiles(include_credentials=True, password=password)
        archive = Path(exported["archive_path"])

        # Decrypt outer archive to manipulate inner zip
        workspace = self.root / "tamper_workspace"
        workspace.mkdir()
        plain_zip = workspace / "plain.zip"
        self.service._decrypt_encrypted_archive(archive, plain_zip, password)

        extracted = workspace / "extracted"
        self.service._extract_archive(plain_zip, extracted)
        manifest_file = extracted / "manifest.json"
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

        def repack_and_test(mutated_manifest: dict, regex: str) -> None:
            manifest_file.write_text(json.dumps(mutated_manifest), encoding="utf-8")
            tampered_zip = workspace / "tampered.zip"
            if tampered_zip.exists():
                tampered_zip.unlink()
            with zipfile.ZipFile(tampered_zip, "w") as z:
                for item in extracted.rglob("*"):
                    if item.is_file():
                        z.write(item, item.relative_to(extracted).as_posix())
            tampered_enc = workspace / "tampered.enc"
            if tampered_enc.exists():
                tampered_enc.unlink()
            self.service._encrypt_archive(tampered_zip, tampered_enc, password)
            with self.assertRaisesRegex(ProfileTransferError, regex):
                self.service.import_all_profiles(str(tampered_enc), password=password)

        # 1. Tamper ciphertext byte
        mutated = json.loads(json.dumps(manifest))
        raw_ct = base64.b64decode(mutated["accounts"][0]["credentials_envelope"]["password"]["ciphertext"])
        flipped = bytes([raw_ct[0] ^ 0xFF]) + raw_ct[1:]
        mutated["accounts"][0]["credentials_envelope"]["password"]["ciphertext"] = base64.b64encode(flipped).decode("ascii")
        repack_and_test(mutated, "Mật khẩu không đúng hoặc thông tin xác thực đã bị thay đổi")

        # 2. Tamper account name (bound via AAD)
        mutated = json.loads(json.dumps(manifest))
        mutated["accounts"][0]["account_name"] = "Different Account"
        repack_and_test(mutated, "Mật khẩu không đúng hoặc thông tin xác thực đã bị thay đổi")

        # 3. Swap ciphertext across fields (bound via AAD)
        mutated = json.loads(json.dumps(manifest))
        env = mutated["accounts"][0]["credentials_envelope"]
        env["email_pass"] = env["password"]
        repack_and_test(mutated, "Mật khẩu không đúng hoặc thông tin xác thực đã bị thay đổi")

        # 4. Tamper envelope version
        mutated = json.loads(json.dumps(manifest))
        mutated["credential_envelope"]["version"] = 99
        repack_and_test(mutated, "không được hỗ trợ")

        # 5. Malformed envelope salt
        mutated = json.loads(json.dumps(manifest))
        mutated["credential_envelope"]["salt"] = base64.b64encode(b"too-short").decode("ascii")
        repack_and_test(mutated, "không hợp lệ")

        # 6. Empty malformed field entries must not silently drop credentials
        mutated = json.loads(json.dumps(manifest))
        mutated["accounts"][0]["credentials_envelope"]["password"] = {}
        repack_and_test(mutated, "Cấu trúc phong bì")

        # 7. Contradictory credential flags are rejected
        mutated = json.loads(json.dumps(manifest))
        mutated["contains_account_secrets"] = False
        repack_and_test(mutated, "mâu thuẫn")

        # 8. KDF iteration type confusion (float == int in Python) is rejected
        mutated = json.loads(json.dumps(manifest))
        mutated["credential_envelope"]["iterations"] = 600_000.0
        repack_and_test(mutated, "không được hỗ trợ")

        # 9. Boolean format versions must not pass as integer version 1
        mutated = json.loads(json.dumps(manifest))
        mutated["format_version"] = True
        repack_and_test(mutated, "không được hỗ trợ")

    def test_unencrypted_portable_bundle_rejected(self) -> None:
        make_profile(self.target, "facebook-session")
        password = "strong-unencrypted-test-pass"
        exported = self.service.export_all_profiles(include_credentials=True, password=password)
        archive = Path(exported["archive_path"])

        plain_zip = self.root / "unencrypted.tinix-profiles.zip"
        self.service._decrypt_encrypted_archive(archive, plain_zip, password)
        # Attempt to import an unencrypted zip containing portable credential envelope
        with self.assertRaisesRegex(ProfileTransferError, "phải được mã hóa toàn bộ"):
            self.service.import_all_profiles(str(plain_zip), password=password)

    def test_unencrypted_plaintext_credentials_rejected(self) -> None:
        raw_zip = self.root / "plaintext_secrets.zip"
        extracted = self.root / "plain_staging"
        extracted.mkdir()
        make_profile(extracted / "profiles" / "0001", "session")
        manifest = {
            "bundle_format": "tinix-profiles",
            "format_version": 1,
            "contains_account_secrets": False,
            "credential_protection": None,
            "accounts": [{
                "account_name": "Plain Account",
                "platform": "facebook",
                "profile_path": "profiles/0001",
                "password": "leak-plaintext-pass",
            }],
        }
        (extracted / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with zipfile.ZipFile(raw_zip, "w") as z:
            for item in extracted.rglob("*"):
                if item.is_file():
                    z.write(item, item.relative_to(extracted).as_posix())

        with self.assertRaisesRegex(ProfileTransferError, "dạng không mã hóa"):
            self.service.import_all_profiles(str(raw_zip))

    def test_legacy_v1_dpapi_bundle_import_compatibility(self) -> None:
        staging = self.root / "legacy_v1_staging"
        staging.mkdir()
        make_profile(staging / "profiles" / "0001", "legacy-session")
        v1_dpapi_pass = self.service.secrets.protect_secret("v1-secret-password")
        manifest = {
            "bundle_format": "tinix-profiles",
            "format_version": 1,
            "contains_account_secrets": True,
            "credential_protection": "windows_dpapi",
            "accounts": [{
                "account_name": "Legacy V1 Account",
                "platform": "facebook",
                "profile_path": "profiles/0001",
                "credentials_protected": {
                    "password": v1_dpapi_pass,
                },
            }],
        }
        (staging / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        archive = self.root / "legacy_v1.tinix-profiles.zip"
        with zipfile.ZipFile(archive, "w") as z:
            for item in staging.rglob("*"):
                if item.is_file():
                    z.write(item, item.relative_to(staging).as_posix())

        # Successful import for same Windows user
        imported = self.service.import_all_profiles(str(archive))
        self.assertEqual(imported["accounts_imported"], 1)
        account = imported["accounts"][0]
        self.assertEqual(account["name"], "Legacy V1 Account")
        self.assertEqual(account["password"], "v1-secret-password")

        # Rejection when DPAPI ciphertext is corrupt / from different user
        manifest["accounts"][0]["credentials_protected"]["password"] = "dpapi:corrupt-data"
        (staging / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        corrupt_archive = self.root / "corrupt_legacy.tinix-profiles.zip"
        with zipfile.ZipFile(corrupt_archive, "w") as z:
            for item in staging.rglob("*"):
                if item.is_file():
                    z.write(item, item.relative_to(staging).as_posix())

        with self.assertRaisesRegex(ProfileTransferError, "cùng tài khoản Windows"):
            self.service.import_all_profiles(str(corrupt_archive))

    def test_all_or_nothing_rollback_on_import_failure(self) -> None:
        staging = self.root / "rollback_staging"
        staging.mkdir()
        # Profile 1 is valid
        make_profile(staging / "profiles" / "0001", "session-ok")
        # Profile 2 is corrupted / missing required Chrome markers
        bad_profile = staging / "profiles" / "0002"
        bad_profile.mkdir(parents=True)
        (bad_profile / "empty.txt").write_text("not a chrome profile")

        manifest = {
            "bundle_format": "tinix-profiles",
            "format_version": 1,
            "contains_account_secrets": False,
            "credential_protection": None,
            "accounts": [
                {
                    "account_name": "Good Account",
                    "platform": "facebook",
                    "profile_path": "profiles/0001",
                },
                {
                    "account_name": "Bad Account",
                    "platform": "instagram",
                    "profile_path": "profiles/0002",
                },
            ],
        }
        (staging / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        archive = self.root / "rollback_test.zip"
        with zipfile.ZipFile(archive, "w") as z:
            for item in staging.rglob("*"):
                if item.is_file():
                    z.write(item, item.relative_to(staging).as_posix())

        initial_count = len(self.accounts.list())
        with self.assertRaises(ProfileTransferError):
            self.service.import_all_profiles(str(archive))

        # Rollback check: no new accounts in DB
        self.assertEqual(len(self.accounts.list()), initial_count)
        # No profile directories created for the failed accounts
        account_keys = {acc["profile_key"] for acc in self.accounts.list()}
        for child in (self.root / "profiles").iterdir():
            if child.is_dir():
                self.assertIn(child.name, account_keys)

    def test_cleanup_preview_and_execute_keep_session_state(self) -> None:
        make_profile(self.target, "keep-session")
        (self.target / "Default" / "Local Storage" / "leveldb").mkdir(parents=True)
        (self.target / "Default" / "Local Storage" / "leveldb" / "state").write_text("keep")

        preview = self.service.profile_cleanup_preview()
        self.assertEqual(preview["profiles_scanned"], 1)
        self.assertGreaterEqual(preview["bytes_removable"], len(b"cache") + len(b"model-cache"))

        result = self.service.cleanup_profiles()
        self.assertEqual(result["profiles_cleaned"], 1)
        self.assertFalse((self.target / "Default" / "Cache").exists())
        self.assertFalse((self.target / "optimization_guide_model_store").exists())
        self.assertEqual((self.target / "Default" / "Cookies").read_text(), "keep-session")
        self.assertEqual((self.target / "Default" / "Local Storage" / "leveldb" / "state").read_text(), "keep")

    def test_import_rejects_zip_path_traversal(self) -> None:
        archive = self.root / "unsafe.tinix-profiles.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("../outside.txt", "unsafe")
        with self.assertRaisesRegex(ProfileTransferError, "không an toàn"):
            self.service.import_all_profiles(str(archive))
        self.assertFalse((self.root / "outside.txt").exists())

    def test_profile_operation_is_blocked_by_unfinished_job_and_blocks_new_jobs(self) -> None:
        self.jobs.create("publish", {}, self.account["id"], None)
        with self.assertRaisesRegex(RuntimeError, "job chưa kết thúc"):
            self.accounts.begin_profile_operation(self.account["id"])

        other = self.accounts.create("Other", "facebook")
        self.accounts.begin_profile_operation(other["id"])
        try:
            with self.assertRaisesRegex(RuntimeError, "đang được bảo trì"):
                self.jobs.create("publish", {}, other["id"], None)
        finally:
            self.accounts.end_profile_operation(other["id"])

    def test_interrupted_profile_lock_is_recovered_on_startup(self) -> None:
        self.accounts.begin_profile_operation(self.account["id"])
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO chrome_profile_operations(id,account_id,operation,status,created_at) VALUES('op',?,'backup','running','now')",
                (self.account["id"],),
            )
        self.assertEqual(self.accounts.recover_profile_operations(), 1)
        self.assertEqual(self.accounts.get(self.account["id"])["profile_operation_locked"], 0)
        with self.database.connection() as connection:
            operation = connection.execute("SELECT status,error FROM chrome_profile_operations WHERE id='op'").fetchone()
        self.assertEqual(operation["status"], "failed")
        self.assertIn("Ứng dụng dừng", operation["error"])


if __name__ == "__main__":
    unittest.main()
