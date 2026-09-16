from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.db.database import Database
from app.db.repositories import AccountRepository
from app.services.profile_transfer import ChromeProfileTransferService
from app.services.recovery_bundle import RecoveryBundleError, RecoveryBundleService


def make_profile(path: Path, cookie: str) -> None:
    (path / "Default").mkdir(parents=True)
    (path / "Local State").write_text("{}", encoding="utf-8")
    (path / "Default" / "Preferences").write_text("{}", encoding="utf-8")
    (path / "Default" / "Cookies").write_text(cookie, encoding="utf-8")


class RecoveryBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = SimpleNamespace(
            project_root=self.root,
            data_dir=self.root / "data",
            media_dir=self.root / "media",
            export_dir=self.root / "exports",
            backup_dir=self.root / "backups",
            chrome_profile_dir=self.root / "profiles",
        )
        for folder in (
            self.settings.data_dir, self.settings.media_dir, self.settings.export_dir,
            self.settings.backup_dir, self.settings.chrome_profile_dir,
        ):
            folder.mkdir(parents=True)
        self.database = Database(self.settings.data_dir / "tinix_social.db", self.settings.backup_dir)
        self.database.initialize()
        self.accounts = AccountRepository(self.database)
        self.account = self.accounts.create("Recovery account", "facebook")
        self.profile = self.settings.chrome_profile_dir / self.account["profile_key"]
        make_profile(self.profile, "original-session")
        (self.settings.media_dir / "campaign.txt").write_text("original-media", encoding="utf-8")
        (self.root / ".env").write_text("TINIX_AI_API_KEY=original\n", encoding="utf-8")
        profiles = ChromeProfileTransferService(
            self.settings, self.database, self.accounts, path_in_use=lambda _: False,
        )
        self.service = RecoveryBundleService(self.settings, self.database, profiles)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_password_encrypted_bundle_restores_database_media_profile_and_environment(self) -> None:
        exported = self.service.create_bundle("correct horse battery staple")
        bundle = Path(exported["bundle_path"])
        self.assertTrue(bundle.is_file())
        self.assertFalse(bundle.read_bytes().startswith(b"PK"))
        self.assertTrue(exported["environment_included"])

        created_after_backup = self.accounts.create("Created after backup", "youtube")
        (self.settings.media_dir / "campaign.txt").write_text("changed-media", encoding="utf-8")
        (self.profile / "Default" / "Cookies").write_text("changed-session", encoding="utf-8")
        (self.root / ".env").write_text("TINIX_AI_API_KEY=changed\n", encoding="utf-8")

        restored = self.service.restore_bundle(str(bundle), "correct horse battery staple")

        self.assertTrue(restored["restored"])
        self.assertIsNone(self.accounts.get(created_after_backup["id"]))
        self.assertEqual((self.settings.media_dir / "campaign.txt").read_text(encoding="utf-8"), "original-media")
        self.assertEqual((self.profile / "Default" / "Cookies").read_text(encoding="utf-8"), "original-session")
        self.assertEqual((self.root / ".env").read_text(encoding="utf-8"), "TINIX_AI_API_KEY=original\n")
        self.assertTrue(restored["safety_paths"])

    def test_bundle_requires_the_correct_password(self) -> None:
        exported = self.service.create_bundle("correct horse battery staple", include_environment=False)
        with self.assertRaisesRegex(RecoveryBundleError, "Mật khẩu không đúng"):
            self.service.restore_bundle(exported["bundle_path"], "wrong password")


if __name__ == "__main__":
    unittest.main()
