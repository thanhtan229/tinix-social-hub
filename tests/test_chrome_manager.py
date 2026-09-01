from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import psutil

from app.services.chrome import ChromeManager, ManagedChrome


class ChromeOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.settings = SimpleNamespace(
            data_dir=root / "data",
            chrome_profile_dir=root / "profiles",
            chrome_path="",
            max_chrome=2,
        )
        self.settings.data_dir.mkdir(parents=True)
        self.settings.chrome_profile_dir.mkdir(parents=True)
        self.manager = ChromeManager(self.settings)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def session(self) -> ManagedChrome:
        profile = self.settings.chrome_profile_dir / "account-1"
        profile.mkdir(exist_ok=True)
        return ManagedChrome("account-1", 1234, 15555, str(profile), "2026-01-01T00:00:00+00:00")

    @patch("app.services.chrome.psutil.Process")
    def test_owns_only_process_with_exact_profile_argument(self, process_factory: Mock) -> None:
        process = process_factory.return_value
        process.is_running.return_value = True
        process.status.return_value = psutil.STATUS_RUNNING
        process.cmdline.return_value = ["chrome.exe", f"--user-data-dir={self.session().profile}"]
        self.assertTrue(self.manager._owns(self.session()))

    @patch("app.services.chrome.psutil.Process")
    def test_pid_reuse_with_different_profile_is_rejected(self, process_factory: Mock) -> None:
        process = process_factory.return_value
        process.is_running.return_value = True
        process.status.return_value = psutil.STATUS_RUNNING
        process.cmdline.return_value = ["chrome.exe", "--user-data-dir=C:\\unrelated-profile"]
        self.assertFalse(self.manager._owns(self.session()))

    def test_port_allocation_is_stable_when_free(self) -> None:
        first = self.manager._port_for("stable-profile")
        second = self.manager._port_for("stable-profile")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
