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

from PIL import Image
from playwright.sync_api import sync_playwright

from app import __version__


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
            try:
                cls.temp.cleanup()
            except Exception:
                pass

    def test_all_tabs_load_without_console_errors(self) -> None:
        errors: list[str] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(self.chrome))
            page = browser.new_page(viewport={"width": 1365, "height": 900})
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            response = page.goto(f"http://127.0.0.1:{self.port}/", wait_until="networkidle")
            self.assertEqual(response.status, 200)
            self.assertEqual(page.locator("#nav button").count(), 8)
            self.assertEqual(page.locator("#platformRoadmap .platform-card").count(), 5)
            self.assertEqual(page.locator("#platformRoadmap .operational").count(), 5)
            self.assertEqual(page.locator("#platformRoadmap .scaffolded").count(), 0)
            self.assertEqual(page.locator("#version").inner_text(), f"v{__version__}")
            for tab, name in (
                ("overview", "Tổng quan"), ("ai", "AI Content Studio"),
                ("posts", "Kho bài viết"),
                ("compose", "Calendar"), ("jobs", "Hàng đợi & Lịch sử"),
                ("analytics", "Analytics"), ("accounts", "Tài khoản & Page"),
                ("settings", "Cài đặt"),
            ):
                button = page.locator(f'#nav button[data-tab="{tab}"]')
                self.assertIn(name, button.inner_text())
                button.click()
                page.wait_for_timeout(150)
            page.locator('#nav button[data-tab="posts"]').click()
            self.assertTrue(page.locator("#postsStatsBanner").is_visible())
            self.assertTrue(page.locator("#postsGrid").is_visible())
            page.locator("#btnViewTable").click()
            self.assertTrue(page.locator("#postsTableWrap").is_visible())
            page.locator("#btnViewGrid").click()
            self.assertTrue(page.locator("#postsGrid").is_visible())
            # Test '+ Tạo bài viết' button click and dialog opening
            page.locator("#newPost").click()
            page.wait_for_timeout(200)
            self.assertTrue(page.locator("#postDialog").is_visible())
            test_img = Path(self.temp.name) / "test_pw_upload.png"
            Image.new("RGB", (120, 120), color="blue").save(test_img, "PNG")
            page.set_input_files("#postMediaInput", str(test_img))
            page.wait_for_timeout(300)
            self.assertEqual(page.locator("#postMediaList .pending-upload img").count(), 1)
            page.fill("#postTitle", "Playwright Post Title")
            page.fill("#postCaption", "Playwright Caption Content")
            page.fill("#postHashtags", "#tinix #playwright")
            page.fill("#postCta", "Order now")
            page.locator("#btnSavePostRecord").click()
            page.wait_for_timeout(800)
            self.assertFalse(page.locator("#postDialog").is_visible())
            card = page.locator('.post-card', has_text="Playwright Post Title")
            self.assertTrue(card.is_visible())
            self.assertEqual(card.locator(".post-thumb-wrap").count(), 1)
            # Test Edit post and media persistence
            card.locator('button', has_text="Sửa").click()
            page.wait_for_timeout(300)
            self.assertTrue(page.locator("#postDialog").is_visible())
            self.assertEqual(page.input_value("#postTitle"), "Playwright Post Title")
            self.assertEqual(page.locator("#postMediaList .existing-media").count(), 1)
            page.locator("#postDialog [data-close]").first.click()
            page.wait_for_timeout(200)
            self.assertFalse(page.locator("#postDialog").is_visible())
            self.assertEqual(page.locator('#accountPlatform option[value="x"]').count(), 1)
            self.assertEqual(page.locator('#calendarPlatform option[value="x"]').count(), 1)
            self.assertEqual(page.locator('#analyticsPlatform option[value="x"]').count(), 1)
            self.assertEqual(page.locator("#aiX").count(), 1)
            # Test Tab 2 AI Brand Profile button and modal opening
            page.locator('#nav button[data-tab="ai"]').click()
            page.wait_for_timeout(200)
            self.assertTrue(page.locator("#btnQuickAddBrand").is_visible())
            page.locator("#btnQuickAddBrand").click()
            page.wait_for_timeout(300)
            self.assertTrue(page.locator("#brandProfileDialog").is_visible())
            self.assertIn("Tinix Social Hub", page.locator("#bpName").get_attribute("placeholder"))
            page.locator("#bpName").fill("Playwright Brand")
            page.locator("#bpTone").fill("Hào hứng, chuyên nghiệp")
            page.locator("#btnSaveBrandProfile").click()
            page.wait_for_timeout(500)
            self.assertFalse(page.locator("#brandProfileDialog").is_visible())
            self.assertIn("Playwright Brand", page.locator("#aiBrand").inner_text())
            self.assertTrue(page.locator("#btnQuickEditBrand").is_visible())
            page.locator("#btnQuickEditBrand").click()
            page.wait_for_timeout(300)
            self.assertTrue(page.locator("#brandProfileDialog").is_visible())
            self.assertEqual(page.locator("#bpName").input_value(), "Playwright Brand")
            page.locator("#brandProfileDialog [data-close]").first.click()
            page.wait_for_timeout(200)
            self.assertFalse(page.locator("#brandProfileDialog").is_visible())

            page.locator('#nav button[data-tab="accounts"]').click()
            self.assertEqual(page.locator("[data-profile-action]").count(), 2)
            self.assertEqual(page.locator("[data-profile-action]:disabled").count(), 1)
            self.assertTrue(page.get_by_role("button", name="Import Profiles", exact=True).is_enabled())
            self.assertEqual(page.locator(".profile-manager").count(), 0)
            self.assertEqual(page.locator(".accounts-panel [data-profile-action]").count(), 2)
            self.assertEqual(page.locator("#targetSyncStatus").count(), 1)
            archive = Path(self.temp.name) / "frontend-import.tinix-profiles.zip"
            manifest = {
                "bundle_format": "tinix-profiles",
                "format_version": 1,
                "source_app": "Tinix UI regression test",
                "accounts": [{
                    "account_name": "Imported UI Account",
                    "platform": "facebook",
                    "username": "ui-user",
                    "email": "ui@example.com",
                    "password": "visible-password",
                    "secret_2fa": "VISIBLE2FA",
                    "email_pass": "visible-mail-password",
                    "cookie": "visible-cookie",
                    "profile_path": "profiles/0001",
                }],
            }
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("manifest.json", json.dumps(manifest))
                bundle.writestr("profiles/0001/Local State", "{}")
                bundle.writestr("profiles/0001/Default/Preferences", "{}")
                bundle.writestr("profiles/0001/Default/Cookies", "session")
            page.get_by_role("button", name="Import Profiles", exact=True).click()
            self.assertTrue(page.locator("#profileImportDialog").is_visible())
            page.locator("#profileArchivePath").fill(str(archive))
            with page.expect_response(lambda item: item.url.endswith("/api/profiles/import")) as response:
                page.get_by_role("button", name="Bắt đầu Import", exact=True).click()
            self.assertEqual(response.value.status, 200)
            page.locator("#profileImportDialog").wait_for(state="hidden")
            self.assertFalse(page.locator("#profileImportDialog").is_visible())
            self.assertIn("Imported UI Account", page.locator("#accountList").inner_text())
            self.assertEqual(page.locator("#accountList .account-table tbody tr").count(), 1)
            self.assertEqual(page.locator("#accountList .account-index").last.inner_text(), "1")
            self.assertEqual(page.locator("#accountResultCount").inner_text(), "Hiển thị 1/1")
            account_row = page.locator("#accountList .account-table tbody tr").first
            account_row.locator("td").nth(1).click()
            self.assertIn("selected", account_row.get_attribute("class"))
            self.assertIn("Account: Imported UI Account", page.locator("#targetAccountFilter").inner_text())
            self.assertIn("chưa có page hoặc kênh", page.locator("#targetList").inner_text().lower())
            account_row.locator("td").nth(1).click()
            self.assertNotIn("selected", account_row.get_attribute("class"))
            self.assertEqual(page.locator("#targetAccountFilter").inner_text(), "Tất cả account")
            self.assertEqual(page.locator('[data-account-platform="facebook"] b').inner_text(), "1")
            page.locator('[data-account-platform="facebook"]').click()
            self.assertTrue(page.locator('[data-account-platform="facebook"]').get_attribute("class").endswith("active"))
            page.locator('[data-account-platform=""]').click()
            page.locator("#accountSearch").fill("không tồn tại")
            self.assertEqual(page.locator("#accountList .account-table tbody tr").count(), 0)
            self.assertIn("Không có account phù hợp", page.locator("#accountList").inner_text())
            page.locator("#accountSearch").fill("")
            page.locator("#accountStatusFilter").select_option("logged_in")
            self.assertEqual(page.locator("#accountList .account-table tbody tr").count(), 0)
            page.locator("#accountStatusFilter").select_option("")
            platform_icon = page.locator('#accountList .platform-icon[aria-label="Nền tảng facebook"]')
            self.assertEqual(platform_icon.count(), 1)
            self.assertEqual(platform_icon.locator("svg").count(), 1)
            self.assertNotIn("facebook ·", page.locator("#accountList").inner_text())
            unknown_badge = page.locator("#accountList .badge.unknown")
            self.assertEqual(unknown_badge.count(), 1)
            self.assertEqual(unknown_badge.evaluate("element => getComputedStyle(element).color"), "rgb(95, 99, 104)")
            account_actions = page.locator("#accountList [data-account-action]")
            self.assertEqual(account_actions.count(), 2)
            self.assertIn("Xóa", account_actions.first.inner_text())
            self.assertIn("Mở Chrome", account_actions.last.inner_text())
            sync_flow: list[str] = []

            def fake_target_sync(route):
                sync_flow.append("sync")
                route.fulfill(status=200, content_type="application/json", body=json.dumps([
                    {"external_id": "page-1", "name": "Page hợp lệ"},
                    {"external_id": "url:latest", "name": "Meta Business Suite"},
                ]))

            def fake_account_close(route):
                sync_flow.append("close")
                route.fulfill(status=200, content_type="application/json", body='{"closed":true}')

            page.route("**/api/accounts/*/sync-targets", fake_target_sync)
            page.route("**/api/accounts/*/chrome/close", fake_account_close)
            # Click row to select and reveal detail & sync button
            account_row.locator("td").nth(1).click()
            page.get_by_role("button", name="Quét Page/Kênh", exact=True).click()
            page.locator("#targetSyncStatus").wait_for(state="visible")
            page.get_by_text("Chrome đã đóng.", exact=False).wait_for()
            self.assertEqual(sync_flow, ["sync", "close"])
            self.assertIn("tìm thấy 1 Page/Kênh", page.locator("#targetSyncStatus").inner_text())
            page.unroute("**/api/accounts/*/sync-targets", fake_target_sync)
            page.unroute("**/api/accounts/*/chrome/close", fake_account_close)

            # Direct editing on the right panel
            page.locator("#detailName").wait_for(state="visible")
            self.assertEqual(page.locator("#detailName").input_value(), "Imported UI Account")
            self.assertEqual(page.locator("#detailEmail").input_value(), "ui@example.com")
            self.assertEqual(page.locator("#detailPassword").input_value(), "visible-password")
            self.assertEqual(page.locator("#detail2fa").input_value(), "VISIBLE2FA")

            # Test Show/Hide button toggle
            page.locator('[data-toggle-type="detailPassword"]').click()
            self.assertEqual(page.locator("#detailPassword").get_attribute("type"), "text")
            page.locator('[data-toggle-type="detailPassword"]').click()
            self.assertEqual(page.locator("#detailPassword").get_attribute("type"), "password")

            # Inline edit account name
            page.locator("#detailName").fill("Renamed UI Account")
            with page.expect_response(lambda item: "/api/accounts/" in item.url and item.request.method == "PUT") as edit_response:
                page.locator("#detailName").evaluate("el => el.dispatchEvent(new Event('change'))")
            self.assertEqual(edit_response.value.status, 200)
            page.locator("#detailSaveStatus").get_by_text("Saved").wait_for()
            self.assertIn("Renamed UI Account", page.locator("#accountList").inner_text())
            page.locator('#accountList [data-account-action="delete"]').first.click()
            page.locator("#deleteAccountDialog").wait_for(state="visible")
            self.assertTrue(page.get_by_role("button", name="Chỉ xóa account", exact=True).is_visible())
            self.assertTrue(page.get_by_role("button", name="Xóa account và profile", exact=True).is_visible())
            page.locator("#deleteAccountDialog").get_by_role("button", name="Hủy", exact=True).click()
            page.locator("#deleteAccountDialog").wait_for(state="hidden")
            open_flow: list[str] = []

            def fake_open(route):
                open_flow.append("open")
                route.fulfill(status=200, content_type="application/json", body='{"state":"ready"}')

            def fake_login_check(route):
                open_flow.append("check-login")
                route.fulfill(status=200, content_type="application/json", body='{"login_status":"logged_in"}')

            page.route("**/api/accounts/*/chrome/open", fake_open)
            page.route("**/api/accounts/*/check-login", fake_login_check)
            page.get_by_role("button", name="Mở Chrome", exact=True).first.click()
            page.wait_for_function("() => document.querySelector('#toast')?.textContent.includes('Đã đăng nhập')")
            self.assertEqual(open_flow, ["open", "check-login"])
            self.assertIn("Đã đăng nhập", page.locator("#toast").inner_text())
            self.assertEqual(errors, [])
            browser.close()

    def test_integration_buttons_open_dialog(self) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(self.chrome))
            page = browser.new_page(viewport={"width": 1365, "height": 900})
            errors: list[str] = []
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            page.goto(f"http://127.0.0.1:{self.port}/", wait_until="networkidle")
            page.locator('#nav button[data-tab="settings"]').click()
            page.locator("#addAiProvider").click()
            page.wait_for_timeout(100)
            self.assertTrue(page.locator("#integrationDialog").is_visible(), errors)
            self.assertEqual(page.locator('#integrationDialog select[name="provider"] option').count(), 4)
            self.assertEqual(page.locator('#integrationDialog select[name="provider"] option[value="gemini"]').count(), 1)
            self.assertEqual(page.locator('#integrationDialog select[name="provider"] option[value="deepseek"]').count(), 1)
            self.assertEqual(page.locator('#integrationDialog select[name="provider"] option[value="openai"]').count(), 1)
            self.assertEqual(page.locator('#integrationDialog select[name="provider"] option[value="openai-compatible"]').count(), 1)
            self.assertTrue(page.locator('#integrationDialog select[name="text_model"]').is_visible())
            page.locator('#integrationDialog select[name="provider"]').select_option("openai-compatible")
            self.assertTrue(page.locator('#integrationDialog input[name="base_url"]').is_visible())
            self.assertTrue(page.locator('#integrationDialog input[name="text_model_custom"]').is_visible())
            page.locator("#integrationDialog [data-close]").click()
            page.locator("#addAiProvider").click()
            page.route("**/api/integrations/ai/discover-models", lambda route: route.fulfill(
                status=200, content_type="application/json", body='[{"model_id":"gemini-fast","display_name":"Gemini Fast","capabilities":["text"]},{"model_id":"gemini-pro","display_name":"Gemini Pro","capabilities":["text"]},{"model_id":"gemini-image","display_name":"Gemini Image","capabilities":["image"]}]',
            ))
            page.locator('#integrationDialog input[name="api_key"]').fill("gemini-test-key")
            page.wait_for_function("() => [...document.querySelectorAll('#integrationDialog select[name=text_model] option')].some(option => option.textContent === '✓ Gemini Fast')")
            self.assertEqual(page.locator('#integrationDialog select[name="text_model"] option').all_text_contents(), ["✓ Gemini Fast", "✓ Gemini Pro", "✓ Gemini Image", "Model tùy chỉnh…"])
            page.unroute("**/api/integrations/ai/discover-models")
            page.locator("#integrationDialog [data-close]").click()
            page.locator("#addPlatformApp").click()
            page.wait_for_timeout(100)
            self.assertTrue(page.locator("#integrationDialog").is_visible(), errors)
            self.assertEqual(page.locator('#integrationDialog select[name="provider"] option').count(), 4)
            self.assertEqual(errors, [])
            browser.close()


if __name__ == "__main__":
    unittest.main()
