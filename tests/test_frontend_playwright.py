from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright


def find_chrome() -> Path | None:
    candidates = []
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        if os.getenv(variable):
            candidates.append(Path(os.environ[variable]) / "Google" / "Chrome" / "Application" / "chrome.exe")
    return next((path for path in candidates if path.is_file()), None)


class FrontendPlaywrightSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.chrome = find_chrome()
        if not cls.chrome:
            raise unittest.SkipTest("Google Chrome is not installed")
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        env = os.environ.copy()
        env.update({
            "TINIX_OPEN_BROWSER": "false",
            "TINIX_PORT": str(cls.port),
            "TINIX_DATA_DIR": str(root / "data"),
            "TINIX_BACKUP_DIR": str(root / "backups"),
            "TINIX_LOG_DIR": str(root / "logs"),
            "TINIX_MEDIA_DIR": str(root / "media"),
            "TINIX_EXPORT_DIR": str(root / "exports"),
            "TINIX_SCREENSHOT_DIR": str(root / "screenshots"),
            "TINIX_CHROME_PROFILE_DIR": str(root / "profiles"),
        })
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        cls.server = subprocess.Popen(
            [sys.executable, "-m", "app"], cwd=Path(__file__).resolve().parents[1], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags,
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/api/health", timeout=1) as response:
                    if json.load(response)["status"] == "ok":
                        return
            except Exception:
                time.sleep(0.2)
        cls.server.terminate()
        raise RuntimeError("Test server did not start")

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "server"):
            cls.server.terminate()
            try:
                cls.server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.server.kill()
        if hasattr(cls, "temp"):
            cls.temp.cleanup()

    def test_all_tabs_load_without_console_errors(self) -> None:
        errors: list[str] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(self.chrome))
            page = browser.new_page(viewport={"width": 1365, "height": 900})
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            response = page.goto(f"http://127.0.0.1:{self.port}/", wait_until="networkidle")
            self.assertEqual(response.status, 200)
            self.assertEqual(page.locator("#nav button").count(), 9)
            self.assertEqual(page.locator("#platformRoadmap .platform-card").count(), 4)
            self.assertEqual(page.locator("#platformRoadmap .operational").count(), 4)
            self.assertEqual(page.locator("#platformRoadmap .scaffolded").count(), 0)
            self.assertEqual(page.locator("#version").inner_text(), "v1.0.0-rc.11")
            for name in (
                "Tổng quan", "AI Content Studio", "Kho nội dung", "Media Library", "Calendar",
                "Hàng đợi & Lịch sử", "Analytics", "Tài khoản & Page", "Cài đặt",
            ):
                page.get_by_role("button", name=name, exact=True).click()
                page.wait_for_timeout(150)
            page.get_by_role("button", name="Tài khoản & Page", exact=True).click()
            self.assertEqual(page.locator("[data-profile-action]").count(), 5)
            self.assertEqual(page.locator("[data-profile-action]:disabled").count(), 4)
            self.assertTrue(page.get_by_role("button", name="Import Profiles ZIP", exact=True).is_enabled())
            self.assertIn(".tinix-profiles.zip", page.locator("#profileHelp").inner_text())
            archive = Path(self.temp.name) / "frontend-import.tinix-profiles.zip"
            manifest = {
                "bundle_format": "tinix-profiles",
                "format_version": 1,
                "source_app": "Tinix UI regression test",
                "accounts": [{
                    "account_name": "Imported UI Account",
                    "platform": "facebook",
                    "profile_path": "profiles/0001",
                }],
            }
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("manifest.json", json.dumps(manifest))
                bundle.writestr("profiles/0001/Local State", "{}")
                bundle.writestr("profiles/0001/Default/Preferences", "{}")
                bundle.writestr("profiles/0001/Default/Cookies", "session")
            page.get_by_role("button", name="Import Profiles ZIP", exact=True).click()
            self.assertTrue(page.locator("#profileImportDialog").is_visible())
            page.locator("#profileArchivePath").fill(str(archive))
            with page.expect_response(lambda item: item.url.endswith("/api/profiles/import")) as response:
                page.get_by_role("button", name="Bắt đầu Import", exact=True).click()
            self.assertEqual(response.value.status, 200)
            page.locator("#profileImportDialog").wait_for(state="hidden")
            self.assertFalse(page.locator("#profileImportDialog").is_visible())
            self.assertIn("Imported UI Account", page.locator("#accountList").inner_text())
            account_actions = page.locator("#accountList [data-account-action]")
            self.assertEqual(account_actions.count(), 4)
            self.assertEqual(
                account_actions.all_inner_texts(),
                ["Mở", "Đóng", "Sửa", "Xóa"],
            )
            self.assertEqual(errors, [])
            browser.close()


if __name__ == "__main__":
    unittest.main()
