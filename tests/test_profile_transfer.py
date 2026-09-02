from __future__ import annotations

import json
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
    (path / "Default" / "Cache").mkdir(parents=True)
    (path / "Local State").write_text("{}", encoding="utf-8")
    (path / "Default" / "Preferences").write_text("{}", encoding="utf-8")
    (path / "Default" / "Cookies").write_text(cookie, encoding="utf-8")
    (path / "Default" / "Cache" / "ignored.bin").write_bytes(b"cache")
    (path / "optimization_guide_model_store").mkdir()
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
        self.account = self.accounts.create("Main Account", "facebook")
        settings = SimpleNamespace(
            chrome_profile_dir=self.root / "profiles",
            backup_dir=self.root / "backups",
            export_dir=self.root / "exports",
        )
        settings.chrome_profile_dir.mkdir()
        settings.export_dir.mkdir()
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

    def test_export_and_import_all_profiles_in_one_zip(self) -> None:
        make_profile(self.target, "facebook-session")
        second = self.accounts.create("Video Account", "youtube")
        second_target = self.root / "profiles" / second["profile_key"]
        make_profile(second_target, "youtube-session")

        exported = self.service.export_all_profiles()
        archive = Path(exported["archive_path"])
        self.assertTrue(archive.is_file())
        self.assertEqual(exported["accounts_exported"], 2)
        with zipfile.ZipFile(archive) as bundle:
            manifest = json.loads(bundle.read("manifest.json"))
            self.assertEqual(manifest["bundle_format"], "tinix-profiles")
            self.assertEqual(manifest["profile_content"], "session-only-v1")
            self.assertEqual({item["account_name"] for item in manifest["accounts"]}, {"Main Account", "Video Account"})
            self.assertIn("profiles/0001/Default/Cookies", bundle.namelist())
            self.assertNotIn("profiles/0001/Default/Cache/ignored.bin", bundle.namelist())
            self.assertNotIn("profiles/0001/optimization_guide_model_store/model.tflite", bundle.namelist())

        imported = self.service.import_all_profiles(str(archive))
        self.assertEqual(imported["accounts_imported"], 2)
        imported_accounts = imported["accounts"]
        self.assertEqual({item["name"] for item in imported_accounts}, {"Main Account", "Video Account"})
        cookies = {
            item["name"]: (self.root / "profiles" / item["profile_key"] / "Default" / "Cookies").read_text(encoding="utf-8")
            for item in imported_accounts
        }
        self.assertEqual(cookies, {"Main Account": "facebook-session", "Video Account": "youtube-session"})

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
