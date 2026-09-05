from __future__ import annotations

import logging
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.logging import SecretRedactionFilter
from app.db.database import Database
from app.db.repositories import AppSettingsRepository
from app.services.maintenance import MaintenanceService


class ProfileTransferStub:
    def __init__(self, removable: int, chrome_running: int = 0) -> None:
        self.removable = removable
        self.chrome_running = chrome_running
        self.cleanup_calls = 0

    def profile_cleanup_preview(self):
        return {
            "profiles_scanned": 2,
            "bytes_removable": self.removable,
            "chrome_running": self.chrome_running,
        }

    def cleanup_profiles(self):
        self.cleanup_calls += 1
        return {
            "profiles_scanned": 2,
            "profiles_cleaned": 2,
            "directories_removed": 4,
            "files_removed": 20,
            "bytes_freed": self.removable,
        }


class MaintenanceTests(unittest.TestCase):
    def test_only_old_files_under_managed_root_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "old.png"
            fresh = root / "fresh.png"
            old.write_bytes(b"old")
            fresh.write_bytes(b"fresh")
            old_time = time.time() - 3600
            os.utime(old, (old_time, old_time))
            removed, failed = MaintenanceService.cleanup_files(root, older_than_seconds=60)
            self.assertEqual((removed, failed), (1, 0))
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())

    def make_service(self, root: Path, transfer: ProfileTransferStub) -> MaintenanceService:
        database = Database(root / "data" / "tinix.db", root / "backups")
        database.initialize()
        settings = SimpleNamespace(chrome_profile_dir=root, maintenance_seconds=21600)
        return MaintenanceService(settings, transfer, AppSettingsRepository(database))

    @patch("app.services.maintenance.shutil.disk_usage")
    def test_profile_cleanup_runs_at_default_five_gb_threshold(self, disk_usage) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transfer = ProfileTransferStub(5 * 1024 ** 3)
            service = self.make_service(Path(directory), transfer)
            disk_usage.return_value = SimpleNamespace(free=20 * 1024 ** 3)
            result = service.auto_cleanup_profiles()
            self.assertEqual(result["status"], "cleaned")
            self.assertEqual(result["trigger"], "size_threshold")
            self.assertEqual(transfer.cleanup_calls, 1)

    @patch("app.services.maintenance.shutil.disk_usage")
    def test_profile_cleanup_skips_when_both_limits_are_healthy(self, disk_usage) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transfer = ProfileTransferStub(4 * 1024 ** 3)
            service = self.make_service(Path(directory), transfer)
            disk_usage.return_value = SimpleNamespace(free=20 * 1024 ** 3)
            result = service.auto_cleanup_profiles()
            self.assertEqual(result["status"], "not_needed")
            self.assertEqual(transfer.cleanup_calls, 0)

    @patch("app.services.maintenance.shutil.disk_usage")
    def test_low_disk_triggers_cleanup_below_size_threshold(self, disk_usage) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transfer = ProfileTransferStub(1024 ** 3)
            service = self.make_service(Path(directory), transfer)
            disk_usage.return_value = SimpleNamespace(free=9 * 1024 ** 3)
            result = service.auto_cleanup_profiles()
            self.assertEqual(result["status"], "cleaned")
            self.assertEqual(result["trigger"], "disk_low")

    @patch("app.services.maintenance.shutil.disk_usage")
    def test_cleanup_is_deferred_while_chrome_is_running(self, disk_usage) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transfer = ProfileTransferStub(6 * 1024 ** 3, chrome_running=1)
            service = self.make_service(Path(directory), transfer)
            disk_usage.return_value = SimpleNamespace(free=20 * 1024 ** 3)
            result = service.auto_cleanup_profiles()
            self.assertEqual(result["status"], "deferred_chrome_running")
            self.assertEqual(transfer.cleanup_calls, 0)

    @patch("app.services.maintenance.shutil.disk_usage")
    def test_profile_cleanup_setting_persists_and_can_disable_automation(self, disk_usage) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transfer = ProfileTransferStub(20 * 1024 ** 3)
            service = self.make_service(Path(directory), transfer)
            disk_usage.return_value = SimpleNamespace(free=20 * 1024 ** 3)
            saved = service.update_profile_cleanup_settings(False, 2)
            self.assertFalse(saved["enabled"])
            self.assertEqual(saved["threshold_gb"], 2)
            self.assertEqual(service.auto_cleanup_profiles()["status"], "disabled")
            self.assertEqual(transfer.cleanup_calls, 0)


class LoggingSafetyTests(unittest.TestCase):
    def test_api_key_is_redacted_from_message_and_arguments(self) -> None:
        record = logging.LogRecord("test", logging.ERROR, __file__, 1, "Request failed for %s", ("secret-key",), None)
        filter_ = SecretRedactionFilter(["secret-key"])
        self.assertTrue(filter_.filter(record))
        self.assertNotIn("secret-key", record.getMessage())
        self.assertIn("[REDACTED]", record.getMessage())


if __name__ == "__main__":
    unittest.main()
