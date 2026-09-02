from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.api.content import router as content_router
from app.db.content_repositories import AIGenerationRepository, BrandProfileRepository, ContentRepository
from app.db.calendar_repositories import PostingSlotRepository
from app.db.database import Database
from app.db.publication_repositories import PublicationRepository
from app.db.notification_repositories import NotificationRepository
from app.db.media_repositories import MediaAssetRepository
from app.db.analytics_repositories import AnalyticsRepository
from app.db.automation_repositories import APITokenRepository, WebhookRepository
from app.api.v1 import router as v1_router
from app.core.secrets import SecretProtector
from app.runtime import LocalPathStorage
from app.db.repositories import AccountRepository, JobRepository, TargetRepository
from app.services.ai import MockAIProvider
from app.services.ai_studio import AIContentStudioService
from app.services.media import MediaService
from app.services.scheduling import SchedulingService
from app.services.profile_transfer import ChromeProfileTransferService


class WorkerStub:
    state = "idle"
    active_count = 0

    def notify(self) -> None:
        pass

    def cancel(self, job_id: str) -> None:
        pass


class ChromeStub:
    def open(self, account):
        return {"state": "ready", "port": 0}

    def status(self, account_id: str | None = None):
        return None if account_id else []

    def close(self, account_id: str) -> bool:
        return False

    def close_all(self) -> int:
        return 0


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        database = Database(root / "data" / "tinix_social.db", root / "backups")
        database.initialize()
        accounts = AccountRepository(database)
        jobs = JobRepository(database)
        targets = TargetRepository(database)
        contents = ContentRepository(database)
        brands = BrandProfileRepository(database)
        generations = AIGenerationRepository(database)
        publications = PublicationRepository(database)
        media_assets = MediaAssetRepository(database)
        analytics = AnalyticsRepository(database)
        api_tokens = APITokenRepository(database, root / "data")
        self.local_token = api_tokens.ensure_default()
        media_settings = SimpleNamespace(media_dir=root / "media")
        mock_ai = MockAIProvider()
        profile_settings = SimpleNamespace(
            data_dir=root / "data", max_chrome=2,
            chrome_profile_dir=root / "profiles", backup_dir=root / "backups", export_dir=root / "exports",
        )
        profile_settings.chrome_profile_dir.mkdir()
        profile_settings.export_dir.mkdir()
        services = SimpleNamespace(
            database=database,
            accounts=accounts,
            jobs=jobs,
            publications=publications,
            posting_slots=PostingSlotRepository(database),
            notifications=NotificationRepository(database),
            media_assets=media_assets,
            analytics=analytics,
            api_tokens=api_tokens,
            webhooks=WebhookRepository(database),
            storage=LocalPathStorage(root / "media"),
            secrets=SecretProtector(),
            targets=targets,
            contents=contents,
            brands=brands,
            media=MediaService(media_settings, contents, media_assets),
            ai_studio=AIContentStudioService(mock_ai, generations, brands, contents),
            scheduling=SchedulingService(jobs, accounts, targets, contents, publications=publications),
            chrome=ChromeStub(),
            worker=WorkerStub(),
            scheduler=SimpleNamespace(state="running"),
            settings=profile_settings,
            ai=SimpleNamespace(configured=False),
            analytics_collector=SimpleNamespace(),
            profile_transfer=ChromeProfileTransferService(
                profile_settings, database, accounts, path_in_use=lambda _: False
            ),
            application_lock=asyncio.Lock(),
        )
        app = FastAPI()
        app.state.services = services
        app.include_router(router)
        app.include_router(content_router)
        app.include_router(v1_router)
        self.services = services
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def test_account_crud_and_enable(self) -> None:
        created = self.client.post("/api/accounts", json={
            "name": "Main", "platform": "facebook", "username": "main-user",
            "email": "main@example.com", "password": "secret-password",
            "secret_2fa": "JBSWY3DPEHPK3PXP", "email_pass": "mail-secret", "cookie": "cookie-secret",
        })
        self.assertEqual(created.status_code, 201)
        self.assertNotIn("password", created.json())
        self.assertTrue(created.json()["has_password"])
        self.assertTrue(created.json()["has_2fa"])
        self.assertTrue(created.json()["has_email_password"])
        self.assertTrue(created.json()["has_cookie"])
        self.assertEqual(created.json()["username"], "main-user")
        self.assertEqual(created.json()["email"], "main@example.com")
        account_id = created.json()["id"]
        credentials = self.client.get(f"/api/accounts/{account_id}/credentials")
        self.assertEqual(credentials.status_code, 200)
        self.assertEqual(credentials.headers["cache-control"], "no-store")
        self.assertEqual(credentials.json(), {
            "password": "secret-password", "secret_2fa": "JBSWY3DPEHPK3PXP",
            "email_pass": "mail-secret", "cookie": "cookie-secret",
        })
        updated = self.client.put(
            f"/api/accounts/{account_id}", json={
                "name": "Renamed", "platform": "facebook", "username": "renamed-user",
                "email": "renamed@example.com", "password": "", "secret_2fa": "",
                "email_pass": "", "cookie": "",
            }
        )
        self.assertEqual(updated.json()["name"], "Renamed")
        stored = self.services.accounts.get(account_id)
        self.assertEqual(stored["username"], "renamed-user")
        self.assertEqual(stored["password"], "")
        self.assertEqual(stored["secret_2fa"], "")
        self.assertEqual(stored["email_pass"], "")
        self.assertEqual(stored["cookie"], "")
        disabled = self.client.patch(
            f"/api/accounts/{account_id}/enabled", json={"enabled": False, "reason": "manual"}
        )
        self.assertEqual(disabled.json()["enabled"], 0)
        deleted = self.client.delete(f"/api/accounts/{account_id}")
        self.assertEqual(deleted.status_code, 200)

    def test_profile_import_backup_export_and_restore_api(self) -> None:
        account = self.client.post("/api/accounts", json={"name": "Main", "platform": "facebook"}).json()
        source = Path(self.temp.name) / "foreign-profile"
        (source / "Default").mkdir(parents=True)
        (source / "Local State").write_text("{}", encoding="utf-8")
        (source / "Default" / "Preferences").write_text("{}", encoding="utf-8")
        (source / "Default" / "Cookies").write_text("session", encoding="utf-8")

        imported = self.client.post(
            f"/api/accounts/{account['id']}/profile/import", json={"source_path": str(source)}
        )
        self.assertEqual(imported.status_code, 200)
        backup = self.client.post(f"/api/accounts/{account['id']}/profile/backup")
        self.assertEqual(backup.status_code, 200)
        exported = self.client.post(f"/api/accounts/{account['id']}/profile/export")
        self.assertEqual(exported.status_code, 200)
        imported_bundle = self.client.post(
            "/api/profiles/import", json={"bundle_path": exported.json()["bundle_path"]}
        )
        self.assertEqual(imported_bundle.status_code, 200)
        self.assertEqual(imported_bundle.json()["accounts"][0]["name"], "Main")
        exported_all = self.client.post("/api/profiles/export")
        self.assertEqual(exported_all.status_code, 200)
        self.assertEqual(exported_all.json()["accounts_exported"], 2)
        imported_all = self.client.post(
            "/api/profiles/import", json={"bundle_path": exported_all.json()["archive_path"]}
        )
        self.assertEqual(imported_all.status_code, 200)
        self.assertEqual(imported_all.json()["accounts_imported"], 2)
        listed = self.client.get(f"/api/accounts/{account['id']}/profile/backups").json()
        self.assertEqual(listed[0]["name"], backup.json()["backup_name"])
        restored = self.client.post(
            f"/api/accounts/{account['id']}/profile/restore",
            json={"backup_name": backup.json()["backup_name"]},
        )
        self.assertEqual(restored.status_code, 200)

    def test_platform_catalog_distinguishes_mvp_from_scaffolds(self) -> None:
        response = self.client.get("/api/platforms")
        self.assertEqual(response.status_code, 200)
        platforms = {item["id"]: item for item in response.json()}
        self.assertEqual(set(platforms), {"facebook", "instagram", "tiktok", "youtube"})
        self.assertTrue(platforms["facebook"]["operational"])
        self.assertTrue(platforms["instagram"]["operational"])
        self.assertEqual(platforms["tiktok"]["capabilities"]["publishing"], "review_required")
        self.assertEqual(platforms["instagram"]["format_schemas"][1]["id"], "carousel")

    def test_posting_slots_and_next_slot_api(self) -> None:
        account = self.services.accounts.create("Main", "facebook")
        target = self.services.targets.sync(account["id"], "facebook", [{
            "external_id": "page-1", "name": "Page", "url": "https://facebook.com/page-1",
        }])[0]
        saved = self.client.put(f"/api/targets/{target['id']}/posting-slots", json={
            "timezone": "Asia/Bangkok", "slots": [{"weekday": 2, "minute_of_day": 600}],
        })
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()[0]["minute_of_day"], 600)
        next_slot = self.client.get(f"/api/targets/{target['id']}/next-slot")
        self.assertEqual(next_slot.status_code, 200)
        self.assertIn("+00:00", next_slot.json()["scheduled_at"])

    def test_notification_and_bulk_retry_api(self) -> None:
        account = self.services.accounts.create("Main", "facebook")
        job = self.services.jobs.create("publish", {}, account["id"], None, max_attempts=1)
        self.services.jobs.claim_next()
        self.services.jobs.fail(job["id"], "failure")
        notifications = self.client.get("/api/notifications?unread_only=true")
        self.assertEqual(notifications.status_code, 200)
        self.assertEqual(notifications.json()[0]["entity_id"], job["id"])
        preview = self.client.post("/api/jobs/retry-bulk", json={"job_ids": [job["id"]], "preview": True})
        self.assertEqual(preview.json()["eligible"], [job["id"]])
        retry = self.client.post(f"/api/jobs/{job['id']}/retry")
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json()["status"], "queued")

    def test_analytics_summary_marks_missing_data_unsupported(self) -> None:
        response = self.client.get("/api/analytics/summary?days=30")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["supported"])
        self.assertEqual(response.json()["metrics"], {})

    def test_v1_requires_token_and_enforces_read(self) -> None:
        self.assertEqual(self.client.get("/api/v1/platforms").status_code, 401)
        response = self.client.get(
            "/api/v1/platforms", headers={"Authorization": f"Bearer {self.local_token}"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 4)

    def test_runtime_endpoint_reports_contracts_and_vps_blockers(self) -> None:
        response = self.client.get("/api/runtime")
        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertTrue(report["contract_ready"])
        self.assertFalse(report["vps_deployable"])
        self.assertGreaterEqual(len(report["vps_blockers"]), 3)

    def test_account_update_rejects_platform_outside_catalog(self) -> None:
        account = self.client.post("/api/accounts", json={"name": "Main", "platform": "facebook"}).json()
        response = self.client.put(
            f"/api/accounts/{account['id']}", json={"name": "Main", "platform": "unknown"}
        )
        self.assertEqual(response.status_code, 422)

    def test_publish_job_defaults_to_safe_dry_run(self) -> None:
        account = self.client.post("/api/accounts", json={"name": "Main", "platform": "facebook"}).json()
        response = self.client.post(
            "/api/jobs",
            json={"kind": "publish", "account_id": account["id"], "payload": {"text": "Hello"}},
        )
        self.assertEqual(response.status_code, 201)
        job = response.json()
        self.assertEqual(job["dry_run"], 1)
        events = self.client.get(f"/api/jobs/{job['id']}/events")
        self.assertEqual(events.status_code, 200)
        self.assertEqual(events.json()[0]["event_type"], "created")

    def test_health_uses_lightweight_ping(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["database"]["result"], "ok")

    def test_content_revision_and_approval_api(self) -> None:
        created = self.client.post("/api/contents", json={
            "title": "Post", "caption": "Hello", "hashtags": ["#tinix"],
            "platform_variants": {"facebook": {"caption": "FB", "hashtags": []}},
        })
        self.assertEqual(created.status_code, 201)
        content_id = created.json()["id"]
        approval = self.client.post(f"/api/contents/{content_id}/request-approval")
        self.assertEqual(approval.status_code, 200)
        decided = self.client.post(
            f"/api/approvals/{approval.json()['id']}/decide", json={"approved": True}
        )
        self.assertEqual(decided.json()["status"], "approved")
        revisions = self.client.get(f"/api/contents/{content_id}/revisions")
        self.assertEqual(len(revisions.json()), 1)

    def test_mock_ai_api_creates_draft_without_external_call(self) -> None:
        response = self.client.post("/api/ai/generate", json={
            "operation": "write", "brief": "Launch", "platforms": ["facebook"], "save_draft": True,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["content"]["approval_status"], "draft")


if __name__ == "__main__":
    unittest.main()
