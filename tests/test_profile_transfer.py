from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.db.database import Database
from app.db.repositories import AccountRepository, JobRepository
from app.services.profile_transfer import ChromeProfileTransferService, ProfileTransferError


def make_profile(path: Path, cookie: str) -> Path:
    (path / "Default" / "Cache").mkdir(parents=True)
    (path / "Local State").write_text("{}", encoding="utf-8")
    (path / "Default" / "Preferences").write_text("{}", encoding="utf-8")
    (path / "Default" / "Cookies").write_text(cookie, encoding="utf-8")
    (path / "Default" / "Cache" / "ignored.bin").write_bytes(b"cache")
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
        self.assertEqual((Path(exported["export_path"]) / "Default" / "Cookies").read_text(), "session-v2")

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
