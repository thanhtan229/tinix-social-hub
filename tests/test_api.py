from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.api.content import router as content_router
from app.db.content_repositories import AIGenerationRepository, BrandProfileRepository, ContentRepository
from app.db.prompt_repositories import PromptTemplateRepository
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
from app.db.repositories import AppSettingsRepository, AccountRepository, ArtifactRepository, JobRepository, TargetRepository
from app.services.ai import MockAIProvider
from app.services.ai_studio import AIContentStudioService
from app.services.media import MediaService
from app.services.scheduling import SchedulingService
from app.services.analytics_scheduler import AnalyticsRefreshScheduler
from app.services.profile_transfer import ChromeProfileTransferService
from app.services.recovery_bundle import RecoveryBundleService
from app.services.maintenance import MaintenanceService
from app.services.integrations import IntegrationService
from app.db.integration_repositories import AIProviderConfigRepository, PlatformAppRepository


class WorkerStub:
    state = "idle"
    active_count = 0

    def __init__(self) -> None:
        self.resume_calls = 0

    def notify(self) -> None:
        pass

    def cancel(self, job_id: str) -> None:
        pass

    async def pause(self, timeout: float = 30) -> None:
        self.state = "paused"

    def resume(self) -> None:
        self.resume_calls += 1
        self.state = "idle"


class ChromeStub:
    def open(self, account):
        return {"state": "ready", "port": 0}

    def status(self, account_id: str | None = None):
        return None if account_id else []

    def close(self, account_id: str) -> bool:
        return False

    def close_all(self) -> int:
        return 0


class ImageGenerationStub:
    async def start(self):
        pass

    async def close(self):
        pass

    async def options(self):
        return {"media_creator": {"available": True, "providers": [{"id": "local-provider", "label": "Local Provider"}]}}

    async def create_job(self, body):
        return {"job_id": "image-job", "status": "queued", "engine": body["engine"], "provider": body["provider"], "model": body["provider"]}

    async def get_job(self, job_id):
        return {"job_id": job_id, "status": "completed", "images": [], "message": "done"} if job_id == "image-job" else None

    async def cancel(self, job_id):
        return job_id == "image-job"


class ApiTests(unittest.TestCase):
    def test_read_only_v1_token_never_returns_recovery_codes(self):
        account = self.services.accounts.create("Secret fixture", "facebook", {"recovery_codes": "fake-recovery", "password": "fake-password"})
        with self.services.database.connection() as connection:
            connection.execute("UPDATE api_tokens SET scopes_json='[\"read\"]'")
        response = self.client.get("/api/v1/accounts", headers={"Authorization": f"Bearer {self.local_token}"})
        self.assertEqual(response.status_code, 200)
        item = next(item for item in response.json() if item["id"] == account["id"])
        self.assertNotIn("recovery_codes", item)
        self.assertNotIn("password", item)
        self.assertTrue(item["has_recovery_codes"])

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
        prompts = PromptTemplateRepository(database)
        generations = AIGenerationRepository(database)
        publications = PublicationRepository(database)
        media_assets = MediaAssetRepository(database)
        analytics = AnalyticsRepository(database)
        app_settings = AppSettingsRepository(database)
        api_tokens = APITokenRepository(database, root / "data")
        self.local_token = api_tokens.ensure_default()
        media_settings = SimpleNamespace(media_dir=root / "media")
        mock_ai = MockAIProvider()
        profile_settings = SimpleNamespace(
            project_root=root, data_dir=root / "data", media_dir=root / "media", max_chrome=2,
            chrome_profile_dir=root / "profiles", backup_dir=root / "backups", export_dir=root / "exports",
            screenshot_dir=root / "screenshots", maintenance_seconds=21600,
        )
        profile_settings.chrome_profile_dir.mkdir()
        profile_settings.export_dir.mkdir()
        profile_settings.screenshot_dir.mkdir()
        profile_transfer = ChromeProfileTransferService(
            profile_settings, database, accounts, path_in_use=lambda _: False
        )
        recovery = RecoveryBundleService(profile_settings, database, profile_transfer)
        maintenance = MaintenanceService(
            profile_settings, profile_transfer, app_settings
        )
        integration_settings = SimpleNamespace(
            ai_api_key="", ai_base_url="", ai_model="", ai_image_model="",
            ai_timeout_seconds=5, ai_max_retries=0,
        )
        integrations = IntegrationService(
            integration_settings,
            AIProviderConfigRepository(database, SecretProtector()),
            PlatformAppRepository(database, SecretProtector()),
            app_settings,
        )
        services = SimpleNamespace(
            database=database,
            accounts=accounts,
            jobs=jobs,
            publications=publications,
            posting_slots=PostingSlotRepository(database),
            notifications=NotificationRepository(database),
            media_assets=media_assets,
            analytics=analytics,
            analytics_scheduler=AnalyticsRefreshScheduler(app_settings, analytics, collector=None),
            api_tokens=api_tokens,
            webhooks=WebhookRepository(database),
            storage=LocalPathStorage(root / "media"),
            secrets=SecretProtector(),
            targets=targets,
            contents=contents,
            brands=brands,
            prompts=prompts,
            media=MediaService(media_settings, contents, media_assets),
            ai_studio=AIContentStudioService(mock_ai, generations, brands, contents, prompts, MediaService(media_settings, contents, media_assets)),
            image_generation=ImageGenerationStub(),
            scheduling=SchedulingService(jobs, accounts, targets, contents, publications=publications),
            chrome=ChromeStub(),
            worker=WorkerStub(),
            scheduler=SimpleNamespace(state="running", maintenance_lock=asyncio.Lock()),
            settings=profile_settings,
            ai=SimpleNamespace(configured=False),
            analytics_collector=SimpleNamespace(),
            profile_transfer=profile_transfer,
            recovery=recovery,
            maintenance=maintenance,
            integrations=integrations,
            application_lock=asyncio.Lock(),
        )
        app = FastAPI()
        from app.api.local_boundary import install_local_boundary
        install_local_boundary(app, "127.0.0.1")
        app.state.services = services
        app.include_router(router)
        app.include_router(content_router)
        app.include_router(v1_router)
        self.services = services
        self.client = TestClient(app, base_url="http://127.0.0.1", headers={"X-Tinix-Request": "1"})

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def test_content_signatures_are_persisted_and_reject_duplicate_names(self) -> None:
        signature = {
            "id": "store-signature", "name": "Store", "text": "Tinix Social Hub",
            "hashtags": ["#tinix", "#tinix"],
        }
        saved = self.client.put("/api/content-signatures", json={"signatures": [signature]})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()[0]["hashtags"], ["#tinix"])
        self.assertEqual(self.client.get("/api/content-signatures").json(), saved.json())
        duplicate = self.client.put("/api/content-signatures", json={"signatures": [
            signature, {**signature, "id": "other-signature", "name": " store "},
        ]})
        self.assertEqual(duplicate.status_code, 422)
        self.assertEqual(self.client.get("/api/content-signatures").json(), saved.json())

    def test_target_group_api_persists_targets_and_defaults(self) -> None:
        account = self.services.accounts.create("Group account", "facebook")
        target = self.services.targets.sync(account["id"], "facebook", [{"external_id": "group-page", "name": "Page"}])[0]
        defaults = {"target_content_formats": {target["id"]: "post"}, "target_platform_settings": {}}
        created = self.client.post("/api/target-groups", json={"name": "Campaign", "defaults": defaults})
        self.assertEqual(created.status_code, 201)
        group_id = created.json()["id"]
        members = self.client.put(f"/api/target-groups/{group_id}/members", json={"target_ids": [target["id"], target["id"]]})
        self.assertEqual(members.status_code, 200)
        self.assertEqual(members.json()["target_ids"], [target["id"]])
        self.assertEqual(members.json()["defaults"], defaults)
        updated = self.client.put(f"/api/target-groups/{group_id}", json={
            "name": "Campaign v2", "description": "Reusable", "defaults": defaults,
        })
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name"], "Campaign v2")
        self.assertEqual(self.client.delete(f"/api/target-groups/{group_id}").status_code, 200)

    def test_release_detail_returns_frozen_snapshot_and_identity(self) -> None:
        account = self.services.accounts.create("Release account", "facebook")
        target = self.services.targets.sync(account["id"], "facebook", [{"external_id": "detail-page", "name": "Detail Page"}])[0]
        content = self.services.contents.create({
            "title": "Snapshot test", "caption": "Frozen copy", "platform_variants": {"facebook": {"caption": "Frozen copy"}},
        })
        job = self.services.scheduling.schedule(
            content["id"], account["id"], [target["id"]], None, True, 0, 0, "confirm",
        )[0]
        response = self.client.get(f"/api/publication-releases/{job['publication_release_id']}")
        self.assertEqual(response.status_code, 200)
        detail = response.json()
        self.assertEqual(detail["target"]["name"], "Detail Page")
        self.assertEqual(detail["account"]["name"], "Release account")
        self.assertEqual(detail["payload_snapshot"]["caption"], "Frozen copy")
        self.assertEqual(detail["job"]["id"], job["id"])
        self.assertNotIn("payload_json", detail["job"])

    def test_bulk_release_reschedule_api_updates_group_atomically(self) -> None:
        account = self.services.accounts.create("Bulk schedule account", "facebook")
        targets = self.services.targets.sync(account["id"], "facebook", [
            {"external_id": "bulk-page-a", "name": "Page A"},
            {"external_id": "bulk-page-b", "name": "Page B"},
        ])
        content = self.services.contents.create({
            "title": "Bulk schedule", "caption": "Caption", "hashtags": [],
            "platform_variants": {"facebook": {"caption": "Caption", "hashtags": []}},
        })
        jobs = self.services.scheduling.schedule(
            content["id"], account["id"], [target["id"] for target in targets],
            datetime.now(timezone.utc) + timedelta(days=1), True, 0, 0, "confirm",
        )
        release_ids = [job["publication_release_id"] for job in jobs]
        due = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        response = self.client.post("/api/publication-releases/reschedule-bulk", json={
            "release_ids": release_ids, "scheduled_at": due, "timezone": "Asia/Bangkok",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["scheduled_at"] for item in response.json()], [due, due])
        duplicate = self.client.post("/api/publication-releases/reschedule-bulk", json={
            "release_ids": [release_ids[0], release_ids[0]], "scheduled_at": due, "timezone": "Asia/Bangkok",
        })
        self.assertEqual(duplicate.status_code, 422)

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
        with self.services.database.connection() as connection:
            stored_row = connection.execute(
                "SELECT password,password_protected FROM accounts WHERE id=?", (account_id,)
            ).fetchone()
        self.assertEqual(stored_row["password"], "")
        self.assertTrue(stored_row["password_protected"].startswith("dpapi:"))
        credentials = self.client.get(f"/api/accounts/{account_id}/credentials")
        self.assertEqual(credentials.status_code, 200)
        self.assertEqual(credentials.headers["cache-control"], "no-store")
        self.assertEqual(credentials.json(), {
            "password": "secret-password", "secret_2fa": "JBSWY3DPEHPK3PXP",
            "email_pass": "mail-secret", "cookie": "cookie-secret", "recovery_codes": "",
        })
        partial = self.client.put(f"/api/accounts/{account_id}", json={
            "name": "Renamed without credentials", "platform": "facebook",
        })
        self.assertEqual(partial.status_code, 200)
        preserved = self.services.accounts.get(account_id)
        self.assertEqual(preserved["password"], "secret-password")
        self.assertEqual(preserved["email_pass"], "mail-secret")
        self.assertEqual(preserved["cookie"], "cookie-secret")
        updated = self.client.put(f"/api/accounts/{account_id}", json={
            "name": "Renamed", "platform": "facebook", "username": "renamed-user",
            "email": "renamed@example.com", "password": "", "secret_2fa": "", "email_pass": "", "cookie": "",
        })
        self.assertEqual(updated.json()["name"], "Renamed")
        stored = self.services.accounts.get(account_id)
        self.assertEqual(stored["username"], "renamed-user")
        self.assertEqual(stored["password"], "")
        self.assertEqual(stored["secret_2fa"], "")
        self.assertEqual(stored["email_pass"], "")
        self.assertEqual(stored["cookie"], "")
        disabled = self.client.patch(f"/api/accounts/{account_id}/enabled", json={"enabled": False, "reason": "manual"})
        self.assertEqual(disabled.json()["enabled"], 0)
        starred = self.client.patch(f"/api/accounts/{account_id}/star")
        self.assertEqual(starred.status_code, 200)
        self.assertTrue(starred.json()["starred"])
        self.assertFalse(self.client.patch(f"/api/accounts/{account_id}/star").json()["starred"])
        cleared = self.client.post(f"/api/accounts/{account_id}/clear-credentials")
        self.assertEqual(cleared.status_code, 200)
        self.assertFalse(cleared.json()["has_password"])
        self.assertEqual(self.client.delete(f"/api/accounts/{account_id}").status_code, 200)

    def test_image_job_routes_return_async_contract(self) -> None:
        options = self.client.get("/api/ai/image-options")
        self.assertEqual(options.status_code, 200)
        self.assertEqual(options.json()["media_creator"]["providers"][0]["id"], "local-provider")
        self.assertNotIn("direct_api", options.json())
        created = self.client.post("/api/ai/image-jobs", json={"prompt": "A product photo", "provider": "local-provider"})
        self.assertEqual(created.status_code, 202)
        self.assertEqual(created.json()["job_id"], "image-job")
        self.assertEqual(created.json()["engine"], "media_creator")
        rejected = self.client.post("/api/ai/image-jobs", json={"prompt": "A product photo", "provider": "local-provider", "engine": "direct_api"})
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(self.client.post("/api/ai/generate-image", json={"prompt": "A product photo"}).status_code, 404)
        status = self.client.get("/api/ai/image-jobs/image-job")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "completed")

    def test_prompt_template_crud_and_generation_selection(self) -> None:
        seeded = self.client.get("/api/prompt-templates")
        self.assertEqual(seeded.status_code, 200)
        self.assertTrue(any(item["id"] == "system-write" for item in seeded.json()))
        created = self.client.post("/api/prompt-templates", json={
            "name": "API Prompt", "system_prompt": "Viết theo cách thân thiện.", "enabled": True,
        })
        self.assertEqual(created.status_code, 201)
        prompt = created.json()
        updated = self.client.put(f"/api/prompt-templates/{prompt['id']}", json={
            "name": "API Prompt Updated", "system_prompt": "Viết ngắn gọn.", "enabled": True,
        })
        self.assertEqual(updated.status_code, 200)
        generated = self.client.post("/api/ai/generate", json={
            "prompt_template_id": prompt["id"], "brief": "Giới thiệu sản phẩm", "platforms": ["facebook"],
        })
        self.assertEqual(generated.status_code, 200)
        self.assertEqual(generated.json()["prompt_template"]["id"], prompt["id"])
        deleted = self.client.delete(f"/api/prompt-templates/{prompt['id']}")
        self.assertEqual(deleted.status_code, 200)
        cancelled = self.client.post("/api/ai/image-jobs/image-job/cancel", json={})
        self.assertEqual(cancelled.status_code, 200)
        self.assertTrue(cancelled.json()["cancelled"])

    def test_integration_crud_masks_secrets_and_sets_defaults(self) -> None:
        self.assertEqual(self.client.post("/api/integrations/ai/legacy-models").status_code, 422)
        created = self.client.post("/api/integrations/ai", json={
            "provider": "openai", "name": "Personal", "api_key": "test-key-a1b2",
            "text_model": "gpt-4o-mini",
        })
        self.assertEqual(created.status_code, 201)
        item = created.json()
        self.assertTrue(item["has_api_key"])
        self.assertEqual(item["key_hint"], "••••a1b2")
        self.assertNotIn("test-key-a1b2", str(item))
        listed = self.client.get("/api/integrations/ai")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["configs"][0]["id"], item["id"])
        defaults = self.client.put("/api/integrations/ai/defaults", json={"text_config_id": item["id"], "image_config_id": None})
        self.assertEqual(defaults.status_code, 200)
        blocked = self.client.delete(f"/api/integrations/ai/{item['id']}")
        self.assertEqual(blocked.status_code, 409)

    def test_platform_app_crud_never_returns_secret(self) -> None:
        created = self.client.post("/api/integrations/platform-apps", json={
            "provider": "google_youtube", "name": "Desktop", "client_id": "client-id",
            "client_secret": "platform-secret-9z", "redirect_uri": "http://127.0.0.1:8765/api/oauth/youtube/callback",
        })
        self.assertEqual(created.status_code, 201)
        item = created.json()
        self.assertTrue(item["has_client_secret"])
        self.assertNotIn("platform-secret-9z", str(item))
        tested = self.client.post(f"/api/integrations/platform-apps/{item['id']}/test")
        self.assertEqual(tested.status_code, 200)
        self.assertEqual(tested.json()["status"], "oauth_required")

    def test_meta_app_can_be_configured_without_oauth_secret_or_redirect(self) -> None:
        created = self.client.post("/api/integrations/platform-apps", json={
            "provider": "meta", "name": "Meta manual token", "client_id": "meta-app-id",
            "api_version": "v23.0", "enabled": True,
        })
        self.assertEqual(created.status_code, 201, created.text)
        item = created.json()
        self.assertFalse(item["has_client_secret"])
        self.assertEqual(item["redirect_uri"], "")
        tested = self.client.post(f"/api/integrations/platform-apps/{item['id']}/test")
        self.assertEqual(tested.status_code, 200, tested.text)
        self.assertEqual(tested.json()["status"], "manual_ready")

    def test_meta_system_user_connect_route_never_returns_submitted_token(self) -> None:
        account = self.client.post("/api/accounts", json={"name": "Page", "platform": "facebook"}).json()
        token = "system-user-secret-value-123456"
        meta_accounts = SimpleNamespace(connect_system_user=AsyncMock(return_value={
            "connected": True, "provider": "meta", "account_id": account["id"],
            "connection_id": "connection-1", "auth_method": "system_user",
            "page": {"id": "123456789", "name": "Tí Nị Studio", "target_id": "target-1", "binding_id": "binding-1"},
            "scopes": ["pages_manage_posts"], "can_publish": True,
        }))
        self.services.meta_accounts = meta_accounts
        response = self.client.post(f"/api/accounts/{account['id']}/connections/meta/system-user", json={
            "platform_app_id": "app-1", "access_token": token, "page_id": "123456789",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(token, response.text)
        meta_accounts.connect_system_user.assert_awaited_once_with(
            account["id"], "app-1", token, ["123456789"], [],
        )
        invalid = self.client.post(f"/api/accounts/{account['id']}/connections/meta/system-user", json={
            "platform_app_id": "app-1", "access_token": token, "page_id": "tiniphotos",
        })
        self.assertEqual(invalid.status_code, 422)

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

    def test_single_profile_export_uses_password_encryption(self) -> None:
        account = self.client.post("/api/accounts", json={"name": "Encrypted", "platform": "facebook"}).json()
        profile = self.services.settings.chrome_profile_dir / account["profile_key"]
        (profile / "Default").mkdir(parents=True)
        (profile / "Local State").write_text("{}", encoding="utf-8")
        (profile / "Default" / "Preferences").write_text("{}", encoding="utf-8")
        (profile / "Default" / "Cookies").write_text("session", encoding="utf-8")

        exported = self.client.post(
            f"/api/accounts/{account['id']}/profile/export", json={"password": "correct horse battery staple"}
        )
        self.assertEqual(exported.status_code, 200)
        self.assertTrue(exported.json()["package_encrypted"])
        self.assertEqual(Path(exported.json()["bundle_path"]).suffix, ".enc")
        imported = self.client.post("/api/profiles/import", json={
            "bundle_path": exported.json()["bundle_path"], "password": "correct horse battery staple",
        })
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(imported.json()["accounts_imported"], 1)

    def test_recovery_bundle_export_api_requires_password_and_encrypts_output(self) -> None:
        rejected = self.client.post("/api/recovery/export", json={"password": "short"})
        self.assertEqual(rejected.status_code, 422)
        exported = self.client.post("/api/recovery/export", json={
            "password": "correct horse battery staple", "include_environment": False,
        })
        self.assertEqual(exported.status_code, 200)
        bundle = Path(exported.json()["bundle_path"])
        self.assertTrue(bundle.is_file())
        self.assertFalse(bundle.read_bytes().startswith(b"PK"))

    def test_recovery_bundle_restore_api_replaces_current_database_safely(self) -> None:
        before = self.client.post("/api/accounts", json={"name": "Before recovery", "platform": "facebook"}).json()
        exported = self.client.post("/api/recovery/export", json={
            "password": "correct horse battery staple", "include_environment": False,
        })
        self.assertEqual(exported.status_code, 200)
        after = self.client.post("/api/accounts", json={"name": "After recovery", "platform": "youtube"}).json()

        restored = self.client.post("/api/recovery/restore", json={
            "bundle_path": exported.json()["bundle_path"], "password": "correct horse battery staple",
        })

        self.assertEqual(restored.status_code, 200)
        self.assertIsNotNone(self.services.accounts.get(before["id"]))
        self.assertIsNone(self.services.accounts.get(after["id"]))
        self.assertTrue(restored.json()["safety_paths"])

    def test_readiness_diagnostics_reports_local_prerequisites(self) -> None:
        result = self.client.get("/api/diagnostics/readiness")
        self.assertEqual(result.status_code, 200)
        checks = {item["id"]: item for item in result.json()["checks"]}
        self.assertEqual(checks["database"]["state"], "ready")
        self.assertIn("chrome", checks)
        self.assertIn("youtube_api", checks)

    def test_database_restore_rolls_back_when_credential_migration_fails(self) -> None:
        legacy = self.services.accounts.create("Legacy", "facebook")
        with self.services.database.connection() as connection:
            connection.execute(
                "UPDATE accounts SET password='legacy-password', secret_2fa_protected='malformed-protection' WHERE id=?",
                (legacy["id"],),
            )
        restore_source = self.services.database.create_backup()
        with self.services.database.connection() as connection:
            connection.execute(
                "UPDATE accounts SET password='', secret_2fa_protected='' WHERE id=?", (legacy["id"],)
            )
        current = self.services.accounts.create("Current", "facebook")

        restored = self.client.post("/api/database/restore", json={"name": restore_source.name})

        self.assertEqual(restored.status_code, 500)
        self.assertIn("hoàn nguyên", restored.json()["detail"])
        self.assertIsNotNone(self.services.accounts.get(current["id"]))
        self.assertEqual(self.services.worker.resume_calls, 1)

    def test_account_delete_can_keep_or_remove_profile_and_backups(self) -> None:
        kept = self.client.post("/api/accounts", json={"name": "Keep", "platform": "facebook"}).json()
        kept_profile = self.services.settings.chrome_profile_dir / kept["profile_key"]
        kept_profile.mkdir(parents=True)
        (kept_profile / "marker.txt").write_text("keep", encoding="utf-8")
        kept_result = self.client.delete(f"/api/accounts/{kept['id']}")
        self.assertEqual(kept_result.status_code, 200)
        self.assertFalse(kept_result.json()["profile_deleted"])
        self.assertTrue(kept_profile.is_dir())

        removed = self.client.post("/api/accounts", json={"name": "Remove", "platform": "facebook"}).json()
        removed_profile = self.services.settings.chrome_profile_dir / removed["profile_key"]
        removed_profile.mkdir(parents=True)
        (removed_profile / "marker.txt").write_text("remove", encoding="utf-8")
        removed_backup = self.services.settings.backup_dir / "chrome_profiles" / removed["id"]
        removed_backup.mkdir(parents=True)
        (removed_backup / "backup.txt").write_text("remove", encoding="utf-8")
        removed_result = self.client.delete(f"/api/accounts/{removed['id']}?delete_profile=true")
        self.assertEqual(removed_result.status_code, 200)
        self.assertTrue(removed_result.json()["profile_deleted"])
        self.assertTrue(removed_result.json()["backup_deleted"])
        self.assertFalse(removed_profile.exists())
        self.assertFalse(removed_backup.exists())

    def test_platform_catalog_distinguishes_mvp_from_scaffolds(self) -> None:
        response = self.client.get("/api/platforms")
        self.assertEqual(response.status_code, 200)
        platforms = {item["id"]: item for item in response.json()}
        self.assertEqual(set(platforms), {"facebook", "instagram", "tiktok", "youtube", "x"})
        self.assertTrue(platforms["facebook"]["operational"])
        self.assertTrue(platforms["instagram"]["operational"])
        self.assertEqual(platforms["tiktok"]["capabilities"]["publishing"], "review_required")
        self.assertEqual(platforms["youtube"]["capabilities"]["analytics"], "review_required")
        self.assertEqual(
            next(item for item in platforms["tiktok"]["transports"] if item["id"]=="official_api")["readiness"],
            "scaffold",
        )
        self.assertEqual(platforms["instagram"]["format_schemas"][1]["id"], "carousel")
        self.assertEqual(platforms["x"]["format_schemas"][0]["max_caption_length"], 280)

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

    def test_history_cleanup_requires_preview_and_protects_active_jobs(self) -> None:
        account = self.services.accounts.create("Main", "facebook")
        completed = self.services.jobs.create("publish", {}, account["id"], None)
        active = self.services.jobs.create("publish", {"slot": 2}, account["id"], None)
        with self.services.database.connection() as connection:
            connection.execute(
                "UPDATE jobs SET status='succeeded',created_at='2020-01-01T00:00:00+00:00' WHERE id=?",
                (completed["id"],),
            )

        preview = self.client.post("/api/jobs/history/cleanup", json={
            "mode": "all", "status_filter": "all", "preview": True,
        })
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["candidate_ids"], [completed["id"]])

        missing_confirmation = self.client.post("/api/jobs/history/cleanup", json={
            "mode": "all", "status_filter": "all", "preview": False,
            "candidate_ids": preview.json()["candidate_ids"],
        })
        self.assertEqual(missing_confirmation.status_code, 409)

        deleted = self.client.post("/api/jobs/history/cleanup", json={
            "mode": "all", "status_filter": "all", "preview": False, "confirm": True,
            "candidate_ids": preview.json()["candidate_ids"],
        })
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json()["deleted"], 1)
        self.assertIsNone(self.services.jobs.get(completed["id"]))
        self.assertIsNotNone(self.services.jobs.get(active["id"]))

    def test_analytics_summary_marks_missing_data_unsupported(self) -> None:
        response = self.client.get("/api/analytics/summary?days=30")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["supported"])
        self.assertEqual(response.json()["metrics"], {})

    def test_analytics_refresh_settings_are_disabled_by_default_and_persisted(self) -> None:
        initial=self.client.get("/api/analytics/refresh-settings")
        self.assertEqual(initial.status_code,200)
        self.assertFalse(initial.json()["enabled"])
        updated=self.client.put("/api/analytics/refresh-settings",json={
            "enabled":True,"interval_hours":12,"days":90,"posts_per_run":4,"channels_per_run":2,
        })
        self.assertEqual(updated.status_code,200)
        self.assertTrue(updated.json()["enabled"])
        self.assertEqual(updated.json()["interval_hours"],12)
        invalid=self.client.put("/api/analytics/refresh-settings",json={
            "enabled":True,"interval_hours":8,"days":90,"posts_per_run":4,"channels_per_run":2,
        })
        self.assertEqual(invalid.status_code,422)
        self.assertTrue(self.client.get("/api/analytics/refresh-settings").json()["enabled"])

    def test_release_listing_filters_and_pages_newest_first(self) -> None:
        account=self.services.accounts.create("Page","facebook")
        target=self.services.targets.sync(account["id"],"facebook",[
            {"external_id":"api-page-1","name":"Page","url":"https://facebook.com/api-page-1"},
        ])[0]
        content=self.services.contents.create({
            "title":"Post","caption":"Test","hashtags":[],"platform_variants":{"facebook":{"caption":"Test"}},
        })
        earlier=self.services.scheduling.schedule(
            content["id"],account["id"],[target["id"]],datetime.now(timezone.utc)+timedelta(days=1),
            True,0,0,"confirm",
        )[0]
        later=self.services.scheduling.schedule(
            content["id"],account["id"],[target["id"]],datetime.now(timezone.utc)+timedelta(days=2),
            True,0,0,"confirm",
        )[0]
        url=(f"/api/publication-releases?order=desc&limit=1&account_id={account['id']}"
             f"&target_id={target['id']}")
        page_one=self.client.get(url)
        page_two=self.client.get(url+"&offset=1")
        self.assertEqual(page_one.status_code,200)
        self.assertEqual(page_one.json()[0]["job_id"],later["id"])
        self.assertEqual(page_two.json()[0]["job_id"],earlier["id"])

    def test_channel_analytics_routes_read_and_refresh_target_metrics(self) -> None:
        account = self.services.accounts.create("YouTube", "youtube")
        target = self.services.targets.sync(account["id"], "youtube", [{
            "external_id": "UC_test123", "name": "Channel", "url": "https://youtube.com/channel/UC_test123",
        }])[0]

        async def collect(target_id: str, days: int = 30) -> dict[str, object]:
            return {"status": "succeeded", "source": "api_youtube_data_v3", "metrics": [],
                    "target_id": target_id, "days": days}

        self.services.api_analytics_collector = SimpleNamespace(collect_channel=collect)
        listing = self.client.get("/api/analytics/channels?platform=youtube")
        detail = self.client.get(f"/api/targets/{target['id']}/metrics")
        refresh = self.client.post(f"/api/targets/{target['id']}/collect-metrics?days=45")
        history = self.client.get(f"/api/analytics/channels/history?platform=youtube&target_id={target['id']}&days=30")
        summary = self.client.get(f"/api/analytics/channels/summary?platform=youtube&account_id={account['id']}")

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json(), [])
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json(), {"metrics": [], "history": [], "fetch_runs": []})
        self.assertEqual(refresh.status_code, 200)
        self.assertEqual(refresh.json()["source"], "api_youtube_data_v3")
        self.assertEqual(refresh.json()["days"], 45)
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json(), [])
        self.assertEqual(summary.status_code, 200)
        self.assertFalse(summary.json()["supported"])

    def test_v1_requires_token_and_enforces_read(self) -> None:
        self.assertEqual(self.client.get("/api/v1/platforms").status_code, 401)
        response = self.client.get(
            "/api/v1/platforms", headers={"Authorization": f"Bearer {self.local_token}"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 5)

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

    def test_direct_real_publish_job_is_rejected(self) -> None:
        account = self.client.post("/api/accounts", json={"name": "Main", "platform": "facebook"}).json()
        response = self.client.post(
            "/api/jobs",
            json={"kind": "publish", "account_id": account["id"], "payload": {"text": "Hello"}, "dry_run": False},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("safety gate", response.json()["detail"])

    def test_job_artifact_file_is_available_only_within_screenshot_directory(self) -> None:
        job = self.services.jobs.create("publish", {}, None, None)
        relative_path = f"{job['id']}/publisher-error.png"
        screenshot = self.services.settings.screenshot_dir / relative_path
        screenshot.parent.mkdir(parents=True)
        screenshot.write_bytes(b"evidence")
        artifact = ArtifactRepository(self.services.database).record(
            job["id"], "screenshot", relative_path, {"step": "publisher-error"},
        )

        response = self.client.get(f"/api/jobs/{job['id']}/artifacts/{artifact['id']}/file")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"evidence")
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}/artifacts/not-found/file").status_code, 404)

        outside = self.services.settings.project_root / "outside-screenshot.png"
        outside.write_bytes(b"outside")
        unsafe = ArtifactRepository(self.services.database).record(job["id"], "screenshot", "../outside-screenshot.png")
        self.assertEqual(
            self.client.get(f"/api/jobs/{job['id']}/artifacts/{unsafe['id']}/file").status_code, 404
        )

    def test_health_uses_lightweight_ping(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["database"]["result"], "ok")

    def test_profile_auto_cleanup_settings_api_persists_selection(self) -> None:
        defaults = self.client.get("/api/settings/profile-cleanup")
        self.assertEqual(defaults.status_code, 200)
        self.assertTrue(defaults.json()["enabled"])
        self.assertEqual(defaults.json()["threshold_gb"], 5)

        updated = self.client.put(
            "/api/settings/profile-cleanup",
            json={"enabled": False, "threshold_gb": 2},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertFalse(updated.json()["enabled"])
        self.assertEqual(updated.json()["threshold_gb"], 2)
        self.assertEqual(self.client.get("/api/settings/profile-cleanup").json(), updated.json())

        invalid = self.client.put(
            "/api/settings/profile-cleanup",
            json={"enabled": True, "threshold_gb": 0.1},
        )
        self.assertEqual(invalid.status_code, 422)

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

    def test_batch_schedule_api_creates_one_idempotent_plan_for_multiple_accounts(self) -> None:
        content = self.services.contents.create({"title": "Batch", "caption": "Hello", "hashtags": []})
        targets = []
        for name, external_id in (("Brand A", "101"), ("Brand B", "202")):
            account = self.services.accounts.create(name, "facebook")
            target = self.services.targets.sync(account["id"], "facebook", [{
                "external_id": external_id, "name": f"Page {external_id}",
                "url": f"https://facebook.com/{external_id}",
            }])[0]
            targets.append(target["id"])
        payload = {
            "content_id": content["id"], "target_ids": targets,
            "scheduled_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "target_scheduled_at": {targets[1]: (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()},
            "dry_run": True, "content_format": "post", "platform_settings": {},
            "request_key": "api-batch-request-001",
        }
        preview = self.client.post("/api/schedules/batch/preflight", json=payload)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertTrue(preview.json()["ready"])
        self.assertEqual(len(preview.json()["targets"]), 2)
        self.assertEqual(self.services.publications.list_plans(), [])
        first = self.client.post("/api/schedules/batch", json=payload)
        retry = self.client.post("/api/schedules/batch", json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(retry.status_code, 201, retry.text)
        self.assertEqual({job["id"] for job in first.json()}, {job["id"] for job in retry.json()})
        self.assertEqual({job["target_id"] for job in first.json()}, set(targets))
        due_by_target = {job["target_id"]: job["scheduled_at"] for job in first.json()}
        self.assertNotEqual(due_by_target[targets[0]], due_by_target[targets[1]])
        self.assertEqual(len(self.services.publications.list_plans()), 1)
        self.assertEqual(len(self.services.publications.list_releases()), 2)

        changed = dict(payload, target_ids=[targets[0]])
        conflict = self.client.post("/api/schedules/batch", json=changed)
        self.assertEqual(conflict.status_code, 422)
        self.assertEqual(len(self.services.publications.list_plans()), 1)

    def test_rich_posts_api_and_bulk_delete(self) -> None:
        p1 = self.client.post("/api/contents", json={
            "title": "Post 1", "caption": "Caption 1", "hashtags": ["#tag1"],
            "platform_variants": {"facebook": {"caption": "FB1", "hashtags": []}},
        }).json()
        p2 = self.client.post("/api/contents", json={
            "title": "Post 2", "caption": "Caption 2", "hashtags": ["#tag2"],
            "platform_variants": {"instagram": {"caption": "IG2", "hashtags": []}},
        }).json()

        # Duplicate test
        dup = self.client.post(f"/api/contents/{p1['id']}/duplicate")
        self.assertEqual(dup.status_code, 201)
        dup_data = dup.json()
        self.assertIn("bản sao", dup_data["title"])

        # List with filter
        listing = self.client.get("/api/contents?platform=facebook")
        self.assertEqual(listing.status_code, 200)
        items = listing.json()
        fb_ids = [item["id"] for item in items]
        self.assertIn(p1["id"], fb_ids)

        # Export test
        exported = self.client.get("/api/contents/export")
        self.assertEqual(exported.status_code, 200)
        self.assertIn("text/csv", exported.headers["content-type"])
        self.assertIn("Post 1", exported.text)

        # Bulk delete test
        del_resp = self.client.post("/api/contents/bulk-delete", json={
            "content_ids": [p1["id"], p2["id"], dup_data["id"]],
            "force": True,
        })
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(del_resp.json()["deleted_count"], 3)

    def test_brand_profiles_api_lifecycle(self) -> None:
        created = self.client.post("/api/brand-profiles", json={
            "name": "Test Brand",
            "tone": "Trang trọng",
            "pronouns": "Chúng tôi - Quý khách",
            "preferred_keywords": ["uy tín", "chất lượng"],
            "forbidden_keywords": ["kém chất lượng"],
            "sample_ctas": ["Liên hệ ngay"],
        })
        self.assertEqual(created.status_code, 201)
        profile_id = created.json()["id"]
        self.assertEqual(created.json()["name"], "Test Brand")

        listing = self.client.get("/api/brand-profiles")
        self.assertEqual(listing.status_code, 200)
        self.assertTrue(any(b["id"] == profile_id for b in listing.json()))

        updated = self.client.put(f"/api/brand-profiles/{profile_id}", json={
            "name": "Test Brand Updated",
            "tone": "Thân thiện",
            "pronouns": "Shop - Bạn",
            "preferred_keywords": ["tự động hóa"],
            "forbidden_keywords": [],
            "sample_ctas": ["Inbox shop"],
        })
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name"], "Test Brand Updated")
        self.assertEqual(updated.json()["tone"], "Thân thiện")

        deleted = self.client.delete(f"/api/brand-profiles/{profile_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["deleted"])

        not_found = self.client.delete(f"/api/brand-profiles/{profile_id}")
        self.assertEqual(not_found.status_code, 404)


if __name__ == "__main__":
    unittest.main()
