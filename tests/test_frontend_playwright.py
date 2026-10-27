from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
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
    def test_cross_origin_browser_form_cannot_create_backup(self) -> None:
        target = f"http://127.0.0.1:{self.port}"
        with urllib.request.urlopen(target + "/api/database/backups") as response:
            before = json.load(response)
        class AttackPage(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(f'<form method="post" action="{target}/api/database/backups"><button>Submit</button></form>'.encode())
            def log_message(self, *args):
                pass
        attacker = ThreadingHTTPServer(("127.0.0.1", 0), AttackPage)
        thread = threading.Thread(target=attacker.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=str(self.chrome))
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{attacker.server_port}/")
                with page.expect_response(target + "/api/database/backups") as attempted:
                    page.locator("button").click()
                self.assertEqual(attempted.value.status, 403)
                browser.close()
            with urllib.request.urlopen(target + "/api/database/backups") as response:
                self.assertEqual(json.load(response), before)
        finally:
            attacker.shutdown()
            attacker.server_close()
            thread.join(timeout=3)

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
            main_js = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "main.js"
            self.assertIn(f'./ai.js?v={__version__}', main_js.read_text(encoding="utf-8"))
            self.assertIn(f'./integrations.js?v={__version__}', main_js.read_text(encoding="utf-8"))
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
            page.locator("#managePostSignatures").click()
            page.locator("#postSignatureDialog").wait_for(state="visible")
            page.locator("#newPostSignature").click()
            page.fill("#postSignatureName", "Playwright Signature")
            page.fill("#postSignatureText", "Visit Tinix")
            page.fill("#postSignatureHashtags", "#campaign #tinix")
            page.locator("#savePostSignature").click()
            page.wait_for_function("() => [...document.querySelectorAll('#postSignatureSelect option')].some(option => option.value && option.textContent === 'Playwright Signature')")
            page.locator("#postSignatureDialog [data-close]").first.click()
            page.locator("#postSignatureSelect").select_option(label="Playwright Signature")
            page.locator("#insertPostSignature").click()
            self.assertIn("Visit Tinix", page.input_value("#postCaption"))
            self.assertIn("#campaign", page.input_value("#postHashtags"))
            page.locator("#btnSavePostRecord").click()
            page.wait_for_timeout(800)
            self.assertFalse(page.locator("#postDialog").is_visible())
            card = page.locator('.post-card', has_text="Playwright Post Title")
            self.assertTrue(card.is_visible())
            self.assertEqual(card.locator(".post-thumb-wrap").count(), 1)
            page.route("**/api/accounts", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps([
                    {"id": "account-a", "name": "Brand A", "platform": "facebook", "enabled": True},
                    {"id": "account-b", "name": "Brand B", "platform": "facebook", "enabled": True},
                    {"id": "account-x", "name": "Other Platform", "platform": "x", "enabled": True},
                ]),
            ))
            page.route("**/api/targets?enabled=true", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps([
                    {"id": "page-1", "account_id": "account-a", "platform": "facebook", "name": "Page 1", "target_type": "page", "enabled": True, "access_status": "accessible"},
                    {"id": "page-2", "account_id": "account-a", "platform": "facebook", "name": "Page 2", "target_type": "page", "enabled": True, "access_status": "unknown"},
                    {"id": "page-3", "account_id": "account-b", "platform": "facebook", "name": "Page 1", "target_type": "page", "enabled": True, "access_status": "accessible"},
                    {"id": "target-x", "account_id": "account-x", "platform": "x", "name": "X", "target_type": "profile", "enabled": True, "access_status": "accessible"},
                ]),
            ))
            page.route("**/api/target-groups", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps([{
                    "id": "group-pages", "name": "Campaign Pages", "target_ids": ["page-1", "page-2"],
                }]),
            ))
            preview_targets = [
                {"target_id": "page-1", "name": "Page 1", "account_name": "Brand A", "status": "ready", "caption": "Copy A", "hashtags": ["#one"], "transport": "chrome"},
                {"target_id": "page-2", "name": "Page 2", "account_name": "Brand A", "status": "ready", "caption": "Copy B", "hashtags": [], "transport": "chrome"},
                {"target_id": "page-3", "name": "Page 1", "account_name": "Brand B", "status": "ready", "caption": "Copy C", "hashtags": [], "transport": "chrome"},
                {"target_id": "target-x", "name": "X", "account_name": "Other Platform", "status": "ready", "caption": "Copy X", "hashtags": [], "transport": "chrome"},
            ]
            page.route("**/api/schedules/batch/preflight", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps({"ready": True, "targets": preview_targets}),
            ))
            page.route("**/api/schedules/batch", lambda route: route.fulfill(
                status=201, content_type="application/json", body="[]",
            ))
            card.locator('[data-post-action="schedule"]').click()
            page.locator("#quickScheduleDialog").wait_for(state="visible", timeout=5000)
            self.assertEqual(page.locator("#quickScheduleTargets option").count(), 4)
            self.assertEqual(page.locator("#quickScheduleTargets option:checked").count(), 4)
            self.assertIn("Brand A", page.locator("#quickScheduleTargets").inner_text())
            self.assertIn("Brand B", page.locator("#quickScheduleTargets").inner_text())
            self.assertEqual(page.locator("#quickScheduleAccount").count(), 0)
            page.locator("#quickScheduleTargets").evaluate("element => Array.from(element.options).forEach(option => option.selected = false)")
            page.locator("#quickScheduleTargetGroup").select_option("group-pages")
            page.locator("#applyTargetGroupMerge").click()
            self.assertEqual(page.locator("#quickScheduleTargets option:checked").count(), 2)
            page.locator("#quickScheduleTargets").evaluate("element => Array.from(element.options).forEach(option => option.selected = true)")
            page.locator("#quickScheduleTargets").dispatch_event("change")
            page.locator('[data-target-time="page-2"]').fill("2030-01-01T10:00")
            expected_target_time = page.locator('[data-target-time="page-2"]').evaluate("input => new Date(input.value).toISOString()")
            page.locator('#quickScheduleForm button[type="submit"]').click()
            page.get_by_text("Kết quả kiểm tra từng Page", exact=True).wait_for(timeout=5000)
            self.assertIn("Kết quả kiểm tra từng Page", page.locator("#quickSchedulePreview").inner_text())
            self.assertIn("#one", page.locator("#quickSchedulePreview").inner_text())
            self.assertIn("Tạo lịch cho 4 đích", page.locator('#quickScheduleForm button[type="submit"]').inner_text())
            with page.expect_request("**/api/schedules/batch") as schedule_request:
                page.locator('#quickScheduleForm button[type="submit"]').click()
            schedule_body = schedule_request.value.post_data_json
            self.assertEqual(set(schedule_body["target_ids"]), {"page-1", "page-2", "page-3", "target-x"})
            self.assertEqual(schedule_body["target_content_formats"]["target-x"], "post")
            self.assertEqual(schedule_body["target_scheduled_at"]["page-2"], expected_target_time)
            self.assertGreaterEqual(len(schedule_body["request_key"]), 16)
            page.locator("#quickScheduleDialog").wait_for(state="hidden")
            page.unroute("**/api/schedules/batch/preflight")
            page.unroute("**/api/schedules/batch")
            # Test Edit post and media persistence
            card.locator('button', has_text="Sửa").click()
            page.wait_for_timeout(300)
            self.assertTrue(page.locator("#postDialog").is_visible())
            self.assertEqual(page.input_value("#postTitle"), "Playwright Post Title")
            self.assertEqual(page.locator("#postMediaList .existing-media").count(), 1)
            page.locator("#postTargetMediaSelect").select_option("page-1")
            page.route("**/media-targets/page-1", lambda route: route.fulfill(
                status=200, content_type="application/json", body="{}",
            ))
            page.locator("#btnAttachTargetMedia").click()
            page.locator("#mediaManagerDialog").wait_for(state="visible")
            page.locator("[data-select-asset]").first.check()
            self.assertEqual(page.locator("#mediaManagerSelectionCount").inner_text(), "1 đã chọn")
            page.locator("#applySelectedMediaAssets").click()
            self.assertEqual(page.locator("#postTargetMediaList .target-media-item").count(), 1)
            self.assertFalse(page.locator("#mediaManagerDialog").is_visible())
            with page.expect_request("**/media-targets/page-1") as override_request:
                page.locator("#btnSavePostRecord").click()
            override_body = override_request.value.post_data_json
            self.assertEqual(len(override_body["asset_ids"]), 1)
            page.locator("#postDialog").wait_for(state="hidden", timeout=5000)
            page.unroute("**/media-targets/page-1")
            self.assertFalse(page.locator("#postDialog").is_visible())
            page.unroute("**/api/accounts")
            page.unroute("**/api/targets?enabled=true")
            page.unroute("**/api/target-groups")
            self.assertEqual(page.locator('#accountPlatform option[value="x"]').count(), 1)
            self.assertEqual(page.locator('#calendarPlatform option[value="x"]').count(), 1)
            self.assertEqual(page.locator('#analyticsPlatform option[value="x"]').count(), 1)
            self.assertEqual(page.locator("#aiX").count(), 1)
            # Test Tab 2 AI Brand Profile button and modal opening
            page.locator('#nav button[data-tab="ai"]').click()
            page.wait_for_timeout(200)
            self.assertEqual(page.locator("#aiImageEngine").count(), 0)
            self.assertEqual(page.locator("#aiImageFallback").count(), 0)
            self.assertEqual(page.locator("#aiImageQuality").count(), 0)
            self.assertTrue(page.locator("#aiImageControls").is_visible())
            self.assertTrue(page.locator("#aiImageSource").is_visible())
            self.assertEqual(page.locator("#aiImageAspectRatio option").count(), 6)
            self.assertEqual(page.locator("#aiImageCount option").count(), 3)
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
            account_id = page.locator("#accountList [data-account-row]").first.get_attribute("data-account-row")
            page.route("**/api/jobs?limit=100", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps([{
                    "id": "responsive-job", "kind": "publish", "account_id": account_id,
                    "status": "permanent_failure", "dry_run": True, "created_at": "2026-09-12T06:00:00+00:00",
                }]),
            ))
            page.set_viewport_size({"width": 320, "height": 900})
            page.locator('#nav button[data-tab="jobs"]').click()
            page.locator("#jobsTable tr").wait_for()
            jobs_wrap = page.locator("#tab-jobs .table-wrap")
            job_kind_cell = page.locator("#jobsTable td").nth(0)
            job_account_cell = page.locator("#jobsTable td").nth(1)
            self.assertEqual(page.locator("#selectAllJobs").evaluate("element => element.getBoundingClientRect().width"), 15)
            self.assertEqual(job_kind_cell.locator("input[type=checkbox]").evaluate("element => element.getBoundingClientRect().width"), 15)
            self.assertGreater(jobs_wrap.evaluate("element => element.scrollWidth"), jobs_wrap.evaluate("element => element.clientWidth"))
            self.assertTrue(job_kind_cell.evaluate("element => element.scrollWidth <= element.clientWidth"))
            self.assertTrue(job_account_cell.evaluate("element => element.scrollWidth <= element.clientWidth"))
            self.assertEqual(job_account_cell.inner_text(), "Imported UI Account")
            page.unroute("**/api/jobs?limit=100")
            page.set_viewport_size({"width": 1365, "height": 900})
            page.locator('#nav button[data-tab="accounts"]').click()
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
            self.assertEqual(account_actions.count(), 3)
            self.assertEqual(
                account_actions.evaluate_all("elements => elements.map(element => element.dataset.accountAction)"),
                ["connect-api", "chrome", "delete"],
            )
            self.assertEqual(account_actions.nth(0).inner_text(), "Kết nối Meta API")
            self.assertIn("Mở", page.locator('#accountList [data-account-action="chrome"]').inner_text())
            self.assertIn("Xóa", page.locator('#accountList [data-account-action="delete"]').inner_text())
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
            page.get_by_role("button", name="Mở", exact=True).first.click()
            page.wait_for_function("() => document.querySelector('#toast')?.textContent.includes('Đã đăng nhập')")
            self.assertEqual(open_flow, ["open", "check-login"])
            row = page.locator('#accountList [data-account-row]').first
            self.assertEqual(row.locator('[data-account-action]').evaluate_all("els => els.map(el => el.dataset.accountAction)"), ["connect-api", "chrome", "delete"])
            page.locator('#newAccount').click()
            page.locator('#accountName').fill('Auto open account')
            page.locator('#accountPlatform').select_option('tiktok')
            page.locator('#saveAccount').click()
            page.wait_for_function("() => document.querySelector('#toast')?.textContent.includes('Hãy đăng nhập account')")
            self.assertEqual(open_flow, ["open", "check-login", "open", "check-login"])
            self.assertIn("Hãy đăng nhập account", page.locator("#toast").inner_text())
            self.assertEqual(errors, [])
            browser.close()

    def test_youtube_detail_exposes_routing_preference_and_api_connection(self) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(self.chrome))
            page = browser.new_page(viewport={"width": 1365, "height": 900})
            page.goto(f"http://127.0.0.1:{self.port}/", wait_until="networkidle")
            account = page.evaluate("""async () => {
                const response = await fetch('/api/accounts', {
                    method: 'POST', headers: {'Content-Type': 'application/json', 'X-Tinix-Request': '1'},
                    body: JSON.stringify({name: 'YouTube routing', platform: 'youtube'}),
                });
                return response.json();
            }""")
            page.locator('#nav button[data-tab="accounts"]').click()
            row = page.locator(f'[data-account-row="{account["id"]}"]')
            row.wait_for(state="visible")
            row.click()
            routing = page.locator(f'[data-routing-account="{account["id"]}"]')
            routing.wait_for(state="visible")
            self.assertEqual(routing.input_value(), "chrome_preferred")
            self.assertEqual(row.locator(".api-connection-status").inner_text(), "YouTube API · Chưa kết nối")
            self.assertEqual(row.locator('[data-account-action="connect-api"]').inner_text(), "Kết nối API")
            with page.expect_response(
                lambda response: response.url.endswith(f'/api/accounts/{account["id"]}/routing-preference')
                and response.request.method == "PATCH"
            ) as saved:
                routing.select_option("official_api_preferred")
            self.assertEqual(saved.value.status, 200)
            browser.close()

    def test_calendar_release_detail_day_view_and_reschedule_dialog(self) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(self.chrome))
            page = browser.new_page(viewport={"width": 1365, "height": 900}, timezone_id="America/New_York")
            now = "2030-01-02T10:00:00+00:00"
            release = {
                "id": "release-demo", "job_id": "job-demo", "content_id": "content-demo",
                "account_id": "account-demo", "target_id": "target-demo", "platform": "facebook",
                "content_format": "post", "status": "scheduled", "scheduled_at": now,
                "target_name": "Demo Page", "account_name": "Demo Account",
            }
            release2 = {**release, "id": "release-demo-2", "job_id": "job-demo-2", "target_id": "target-demo-2", "target_name": "Second Page"}
            detail = {
                **release, "external_url": None, "verification_status": "pending", "verification_method": None,
                "publication_transport": "chrome", "payload_snapshot": {"title": "Frozen title", "caption": "Frozen snapshot"},
                "media_snapshot": [], "settings_snapshot": {}, "target": {"name": "Demo Page", "platform": "facebook"},
                "account": {"name": "Demo Account", "platform": "facebook"}, "events": [], "attempts": [], "artifacts": [],
            }
            job = {
                "id": "job-demo", "status": "scheduled", "dry_run": True, "commit_reached_at": None,
                "publication_release_id": "release-demo", "attempt_history": [], "events": [], "artifacts": [],
                "release": release, "result": {},
            }
            page.route("**/api/publication-releases?*", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps([release, release2]),
            ))
            page.route("**/api/publication-releases/release-demo", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps(detail),
            ))
            page.route("**/api/publication-releases/release-demo/schedule", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps({**release, "scheduled_at": "2030-01-03T11:30:00+00:00"}),
            ))
            page.route("**/api/publication-releases/reschedule-bulk", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps([release, release2]),
            ))
            page.route("**/api/jobs/job-demo", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps(job),
            ))
            page.goto(f"http://127.0.0.1:{self.port}/", wait_until="networkidle")
            page.locator('#nav button[data-tab="compose"]').click()
            page.locator("#calendarAnchor").fill("2030-01-02")
            page.locator("#calendarAnchor").dispatch_event("change")
            page.locator('[data-release="release-demo"]').wait_for()
            page.locator('[data-release="release-demo"]').click()
            page.get_by_text("Frozen snapshot", exact=False).wait_for()
            self.assertIn("Frozen snapshot", page.locator("#jobReleaseSnapshot").inner_text())
            page.locator("#jobDialog [data-close]").click()
            page.locator('[data-calendar-view="day"]').click()
            page.locator("#calendarGrid.day-view").wait_for()
            self.assertTrue(page.locator("#calendarGrid.day-view").is_visible())
            page.locator("[data-select-release]").nth(0).check()
            page.locator("[data-select-release]").nth(1).check()
            page.locator("#calendarBulkReschedule").click()
            self.assertTrue(page.locator("#calendarRescheduleDialog").is_visible())
            page.locator("#calendarRescheduleAt").fill("2030-11-03T01:30")
            page.locator("#calendarRescheduleForm [type=submit]").click()
            self.assertIn("Giờ này bị lặp", page.locator("#calendarRescheduleError").inner_text())
            page.locator("#calendarRescheduleAt").fill("2030-01-03T11:30")
            with page.expect_request("**/publication-releases/reschedule-bulk") as reschedule_request:
                page.locator("#calendarRescheduleForm [type=submit]").click()
            self.assertEqual(reschedule_request.value.post_data_json["release_ids"], ["release-demo", "release-demo-2"])
            self.assertTrue(reschedule_request.value.post_data_json["scheduled_at"].endswith("Z"))
            self.assertTrue(reschedule_request.value.post_data_json["timezone"])
            browser.close()

    def test_youtube_expired_connection_can_reauthorize_without_disconnect(self) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(self.chrome))
            page = browser.new_page(viewport={"width": 1365, "height": 900})
            account_ref: dict[str, str] = {}
            connection_state = {"status": "reauth_required"}
            connection_requests: list[tuple[str, str]] = []
            page.add_init_script(
                "window.__tinixOpenedUrl = null; window.open = url => { window.__tinixOpenedUrl = url; return null; };"
            )

            def provider_connections(route) -> None:
                rows = []
                if account_ref.get("id"):
                    rows.append({
                        "id": "reauth-youtube", "account_id": account_ref["id"],
                        "provider": "youtube", "transport": "official_api", "status": connection_state["status"],
                    })
                route.fulfill(status=200, content_type="application/json", body=json.dumps(rows))

            page.route("**/api/connections", provider_connections)
            page.route("**/api/integrations/platform-apps", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps([{
                    "id": "youtube-app", "provider": "google_youtube", "enabled": True,
                    "name": "YouTube Test",
                }]),
            ))

            def authorize(route) -> None:
                connection_requests.append((route.request.method, route.request.url))
                connection_state["status"] = "connected"
                route.fulfill(status=200, content_type="application/json", body=json.dumps({
                    "opened": True, "account_id": account_ref["id"], "provider": "youtube",
                }))

            page.route("**/api/accounts/*/connections/youtube/authorize/open", authorize)
            page.on("request", lambda request: connection_requests.append((request.method, request.url))
                    if "/api/accounts/" in request.url and "/connections/" in request.url else None)
            page.goto(f"http://127.0.0.1:{self.port}/", wait_until="networkidle")
            account = page.evaluate("""async () => {
                const response = await fetch('/api/accounts', {
                    method: 'POST', headers: {'Content-Type': 'application/json', 'X-Tinix-Request': '1'},
                    body: JSON.stringify({name: 'YouTube reauth', platform: 'youtube'}),
                });
                return response.json();
            }""")
            account_ref["id"] = account["id"]
            page.locator('#nav button[data-tab="accounts"]').click()
            row = page.locator(f'[data-account-row="{account["id"]}"]')
            row.wait_for(state="visible")
            reconnect = row.locator('[data-account-action="connect-api"]')
            self.assertEqual(reconnect.inner_text(), "Kết nối lại API")
            self.assertEqual(row.locator(".api-connection-status").inner_text(), "YouTube API · Cần kết nối lại")
            with page.expect_response(
                lambda response: response.url.endswith(
                    f'/api/accounts/{account["id"]}/connections/youtube/authorize/open'
                ) and response.request.method == "POST"
            ) as authorize_response:
                reconnect.click()
            self.assertEqual(authorize_response.value.status, 200)
            self.assertIsNone(page.evaluate("window.__tinixOpenedUrl"))
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            page.wait_for_function(
                "accountId => document.querySelector(`[data-account-row=\"${accountId}\"] .api-connection-status`)?.textContent.includes('Đã kết nối')",
                arg=account["id"],
            )
            self.assertEqual(row.locator(".api-connection-status").inner_text(), "YouTube API · Đã kết nối")
            self.assertEqual(row.locator('[data-account-action="connect-api"]').count(), 0)
            self.assertFalse(any(
                method == "DELETE" and "/connections/reauth-youtube" in url
                for method, url in connection_requests
            ))
            browser.close()

    def test_instagram_login_connect_and_expiry_refresh_controls(self) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(self.chrome))
            page = browser.new_page(viewport={"width": 1365, "height": 900})
            account_ref: dict[str, str] = {}
            connections: list[dict] = []
            refresh_requests: list[str] = []
            page.route("**/api/connections", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps(connections),
            ))
            page.route("**/api/integrations/platform-apps", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps([{
                    "id": "instagram-app", "provider": "instagram", "enabled": True,
                    "name": "Instagram Login Test",
                }]),
            ))

            def authorize(route) -> None:
                connections[:] = [{
                    "id": "instagram-connection", "account_id": account_ref["id"],
                    "provider": "instagram", "transport": "official_api", "status": "connected",
                    "expires_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
                    "refresh_metadata": {"username": "tinix.studio"},
                }]
                route.fulfill(status=200, content_type="application/json", body=json.dumps({
                    "opened": True, "account_id": account_ref["id"], "provider": "instagram",
                }))

            def refresh(route) -> None:
                refresh_requests.append(route.request.url)
                connections[0]["expires_at"] = (datetime.now(timezone.utc) + timedelta(days=60)).isoformat()
                route.fulfill(status=200, content_type="application/json", body=json.dumps(connections[0]))

            page.route("**/api/accounts/*/connections/instagram/authorize/open", authorize)
            page.route("**/api/accounts/*/connections/*/instagram/refresh", refresh)
            page.goto(f"http://127.0.0.1:{self.port}/", wait_until="networkidle")
            account = page.evaluate("""async () => {
                const response = await fetch('/api/accounts', {
                    method: 'POST', headers: {'Content-Type': 'application/json', 'X-Tinix-Request': '1'},
                    body: JSON.stringify({name: 'Instagram Login test', platform: 'instagram'}),
                });
                return response.json();
            }""")
            account_ref["id"] = account["id"]
            page.locator('#nav button[data-tab="accounts"]').click()
            row = page.locator(f'[data-account-row="{account["id"]}"]')
            row.wait_for(state="visible")
            connect = row.locator('[data-account-action="connect-api"]')
            self.assertEqual(connect.inner_text(), "Kết nối Instagram Login")
            with page.expect_response(lambda response: "/connections/instagram/authorize/open" in response.url):
                connect.click()
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            page.wait_for_function(
                "accountId => document.querySelector(`[data-account-row=\\\"${accountId}\\\"] .api-connection-status`)?.textContent.includes('@tinix.studio')",
                arg=account["id"],
            )
            self.assertEqual(row.locator(".api-connection-status").inner_text(), "Instagram Login · Đã kết nối · @tinix.studio")
            refresh_button = row.locator('[data-account-action="refresh-instagram-api"]')
            self.assertEqual(refresh_button.inner_text(), "Gia hạn token")
            with page.expect_response(lambda response: "/instagram/refresh" in response.url):
                refresh_button.click()
            page.wait_for_function(
                "accountId => !document.querySelector(`[data-account-row=\\\"${accountId}\\\"] [data-account-action=\\\"refresh-instagram-api\\\"]`)",
                arg=account["id"],
            )
            self.assertEqual(len(refresh_requests), 1)
            browser.close()

    def test_settings_show_readiness_and_recovery_bundle_controls(self) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(self.chrome))
            page = browser.new_page(viewport={"width": 1365, "height": 900})
            page.route("**/api/diagnostics/readiness", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps({
                    "status": "ready", "checks": [{
                        "id": "database", "label": "Database", "state": "ready", "detail": "SQLite is available.",
                    }],
                }),
            ))
            page.goto(f"http://127.0.0.1:{self.port}/", wait_until="networkidle")
            page.locator('#nav button[data-tab="settings"]').click()
            page.locator("#runReadiness").click()
            page.get_by_text("SQLite is available.", exact=True).wait_for()
            page.locator("#exportRecovery").click()
            self.assertTrue(page.locator("#recoveryExportDialog").is_visible())
            page.locator("#recoveryExportDialog [data-close]").click()
            page.locator("#restoreRecovery").click()
            self.assertTrue(page.locator("#recoveryRestoreDialog").is_visible())
            browser.close()

    def test_ai_studio_system_prompt_and_reference_image_controls(self) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(self.chrome))
            page = browser.new_page(viewport={"width": 1365, "height": 900})
            uploads = []

            def route_media_asset_upload(route) -> None:
                if route.request.method != "POST":
                    route.continue_()
                    return
                uploads.append(route.request.method)
                route.fulfill(status=201, content_type="application/json", body=json.dumps({
                    "id": "reference-image", "media_type": "image", "original_name": "reference.png",
                    "relative_path": "media-library/reference.png", "thumbnail_relative_path": "media-library/reference-thumb.jpg",
                }))

            page.route("**/api/media-assets", route_media_asset_upload)
            page.goto(f"http://127.0.0.1:{self.port}/", wait_until="networkidle")
            page.locator('#nav button[data-tab="ai"]').click()
            page.wait_for_function("() => document.querySelector('#aiPromptTemplate option[value=system-write]')")
            self.assertEqual(page.locator("#aiPromptTemplate").input_value(), "system-write")
            self.assertTrue(page.locator("#btnQuickEditPromptTemplate").is_visible())
            self.assertEqual(page.locator("#aiReferenceImageUpload").get_attribute("accept"), ".jpg,.jpeg,.png,.webp,.gif,.jfif,image/*")
            self.assertEqual(
                page.locator("#btnUploadReferenceImages").get_attribute("class"),
                page.locator("#btnChooseReferenceImages").get_attribute("class"),
            )
            page.evaluate("""() => {
                const transfer = new DataTransfer();
                transfer.items.add(new File(["image"], "reference.png", {type: "image/png"}));
                document.querySelector("#aiReferenceImageDropzone").dispatchEvent(
                    new DragEvent("dragover", {bubbles: true, cancelable: true, dataTransfer: transfer})
                );
            }""")
            self.assertTrue(page.locator("#aiReferenceImageDropzone").evaluate("element => element.classList.contains('is-dragging')"))
            page.locator("#aiReferenceImageDropzone").dispatch_event("dragleave")
            self.assertFalse(page.locator("#aiReferenceImageDropzone").evaluate("element => element.classList.contains('is-dragging')"))
            page.evaluate("""() => {
                const transfer = new DataTransfer();
                transfer.items.add(new File(["image"], "reference.png", {type: "image/png"}));
                document.querySelector("#aiReferenceImageDropzone").dispatchEvent(
                    new DragEvent("drop", {bubbles: true, cancelable: true, dataTransfer: transfer})
                );
            }""")
            page.wait_for_function("() => document.querySelectorAll('#aiReferenceImageList .ai-reference-image-card').length === 1")
            self.assertEqual(uploads, ["POST"])
            page.locator("#btnQuickAddPromptTemplate").click()
            self.assertTrue(page.locator("#promptTemplateDialog").is_visible())
            page.locator("#promptTemplateDialog [data-close]").first.click()
            page.locator("#btnChooseReferenceImages").click()
            self.assertTrue(page.locator("#referenceImageDialog").is_visible())
            browser.close()

    def test_image_source_options_display_media_creator_providers(self) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(self.chrome))
            page = browser.new_page(viewport={"width": 1365, "height": 900})
            provider = {
                "id": "local-sdxl", "label": "SDXL Local",
                "capabilities": {"imageModels": ["SDXL Base", "SDXL Turbo"]},
            }
            page.route("**/api/ai/image-options", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps({
                    "media_creator": {"available": True, "providers": [provider]},
                }),
            ))
            page.goto(f"http://127.0.0.1:{self.port}/", wait_until="networkidle")
            page.locator('#nav button[data-tab="ai"]').click()
            self.assertEqual(page.locator("#aiImageSource option").all_text_contents(), ["SDXL Local"])
            self.assertEqual(page.locator("#aiImageSource").input_value(), "local-sdxl")
            self.assertEqual(page.locator("#aiImageModel option").all_text_contents(), ["SDXL Base", "SDXL Turbo"])
            self.assertEqual(page.locator("#aiImageModel").input_value(), "SDXL Base")
            page.locator("#aiImageModel").select_option("SDXL Turbo")
            provider.update(
                id="local-sd3", label="SD 3 Local",
                capabilities={"imageModels": ["SD 3.5 Large"]},
            )
            page.locator('#nav button[data-tab="settings"]').click()
            page.locator('#nav button[data-tab="ai"]').click()
            page.wait_for_function("() => document.querySelector('#aiImageSource option')?.textContent === 'SD 3 Local'")
            self.assertEqual(page.locator("#aiImageSource").input_value(), "local-sd3")
            self.assertEqual(page.locator("#aiImageModel option").all_text_contents(), ["SD 3.5 Large"])
            self.assertEqual(page.locator("#aiImageModel").input_value(), "SD 3.5 Large")
            browser.close()

    def test_settings_only_shows_default_text_provider(self) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(self.chrome))
            page = browser.new_page(viewport={"width": 1365, "height": 900})
            page.route("**/api/integrations/catalog", lambda route: route.fulfill(
                status=200, content_type="application/json", body='{"ai_providers":[],"platform_apps":[]}',
            ))
            page.route("**/api/integrations/ai", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps({
                    "configs": [{
                        "id": "gemini-config", "name": "Gemini", "enabled": True,
                        "text_model": "gemini-2.5-flash", "text_model_display_name": "Gemini 2.5 Flash",
                        "image_model": "gemini-3.1-flash-lite-image", "image_model_display_name": "Nano Banana 2 Lite",
                    }],
                    "defaults": {"text_config_id": "gemini-config", "image_config_id": "gemini-config"},
                    "legacy_configured": False, "legacy": None,
                }),
            ))
            page.route("**/api/integrations/platform-apps", lambda route: route.fulfill(
                status=200, content_type="application/json", body="[]",
            ))
            page.goto(f"http://127.0.0.1:{self.port}/", wait_until="networkidle")
            page.locator('#nav button[data-tab="settings"]').click()
            page.wait_for_function("() => document.querySelector('#defaultTextProvider option[value=gemini-config]')?.textContent.includes('Gemini 2.5 Flash')")
            self.assertEqual(page.locator("#defaultTextProvider option[value=gemini-config]").inner_text(), "Gemini · Gemini 2.5 Flash")
            self.assertEqual(page.locator("#defaultImageProvider").count(), 0)
            browser.close()

    def test_ai_image_thumbnail_opens_fullsize_lightbox(self) -> None:
        image_one = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Jf8sAAAAASUVORK5CYII="
        image_two = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        history = [{
            "id": "history-image", "displayTime": "10:00", "operationLabel": "Viết mới",
            "inputs": {"platforms": ["facebook"]},
            "output": {"raw_json": "{}", "structured_content": {"image_prompt": "A studio product photo", "platform_variants": {}}, "content_id": None, "image_prompt": "A studio product photo"},
            "image": {"url": image_one, "images": [{"url": image_one}, {"url": image_two}], "prompt": "A studio product photo", "source_model": "Local Provider", "attached": False},
        }]
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(self.chrome))
            page = browser.new_page(viewport={"width": 1365, "height": 900})
            page.add_init_script("localStorage.setItem('tinix_ai_studio_history_v1', " + json.dumps(json.dumps(history)) + ");")
            page.route("**/api/ai/image-options", lambda route: route.fulfill(
                status=200, content_type="application/json", body='{"media_creator":{"available":true,"providers":[{"id":"local-provider","label":"Local Provider"}]}}',
            ))
            page.goto(f"http://127.0.0.1:{self.port}/", wait_until="networkidle")
            page.locator('#nav button[data-tab="ai"]').click()
            self.assertEqual(page.locator("#aiImageGallery button").count(), 2)
            page.locator("#aiImageGallery button").nth(1).click()
            self.assertTrue(page.locator("#aiImageLightboxDialog").is_visible())
            self.assertEqual(page.locator("#aiImageLightboxIndex").inner_text(), "2 / 2")
            self.assertTrue(page.locator("#aiImageLightboxPrev").is_enabled())
            self.assertFalse(page.locator("#aiImageLightboxNext").is_enabled())
            page.keyboard.press("ArrowLeft")
            self.assertEqual(page.locator("#aiImageLightboxIndex").inner_text(), "1 / 2")
            page.keyboard.press("Escape")
            page.locator("#aiImageLightboxDialog").wait_for(state="hidden")
            browser.close()

    def test_integration_buttons_open_dialog(self) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(self.chrome))
            page = browser.new_page(viewport={"width": 1365, "height": 900})
            errors: list[str] = []
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            # Isolate from the developer's .env legacy AI key: the real provider rejects it and would add a console 422.
            page.route("**/api/integrations/ai/legacy-models", lambda route: route.fulfill(
                status=200, content_type="application/json", body="[]",
            ))
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
            self.assertCountEqual(
                page.locator('#integrationDialog select[name="provider"] option').evaluate_all("items => items.map(item => item.value)"),
                ["meta", "instagram", "tiktok", "google_youtube", "x"],
            )
            self.assertEqual(errors, [])
            browser.close()


if __name__ == "__main__":
    unittest.main()
