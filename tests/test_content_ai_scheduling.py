from __future__ import annotations

import asyncio
import io
import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from app.db.content_repositories import AIGenerationRepository, BrandProfileRepository, ContentRepository
from app.db.database import Database
from app.db.prompt_repositories import PromptTemplateRepository
from app.db.publication_repositories import PublicationRepository
from app.db.repositories import AccountRepository, JobRepository, TargetRepository
from app.services.ai import MockAIProvider
from app.services.ai_studio import AIContentStudioService
from app.services.media import MediaService, MediaValidationError
from app.db.media_repositories import MediaAssetInUseError
from app.services.scheduling import SchedulingError, SchedulingService


class ContentFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.root = root
        self.database = Database(root / "data" / "tinix_social.db", root / "backups")
        self.database.initialize()
        self.contents = ContentRepository(self.database)
        self.brands = BrandProfileRepository(self.database)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_content(self):
        return self.contents.create({
            "title": "Launch",
            "caption": "Original",
            "hashtags": ["#tinix"],
            "platform_variants": {"facebook": {"caption": "Facebook caption", "hashtags": ["#fb"]}},
        })


class ContentRepositoryTests(ContentFixture):
    def test_update_creates_revision_and_invalidates_approval(self) -> None:
        content = self.create_content()
        approval = self.contents.request_approval(content["id"])
        self.contents.decide_approval(approval["id"], True)
        self.assertEqual(self.contents.get(content["id"])["approval_status"], "approved")
        updated = self.contents.update(content["id"], {
            "title": "Launch v2", "caption": "Changed", "hashtags": [], "platform_variants": {}
        })
        self.assertEqual(updated["approval_status"], "draft")
        self.assertEqual(updated["current_revision"], 2)
        self.assertEqual(len(self.contents.revisions(content["id"])), 2)

    def test_restore_revision_creates_new_revision(self) -> None:
        content = self.create_content()
        first_revision = self.contents.revisions(content["id"])[0]
        self.contents.update(content["id"], {
            "title": "Changed", "caption": "Changed", "hashtags": [], "platform_variants": {}
        })
        restored = self.contents.restore_revision(content["id"], first_revision["id"])
        self.assertEqual(restored["title"], "Launch")
        self.assertEqual(restored["current_revision"], 3)


class MediaServiceTests(ContentFixture):
    def setUp(self) -> None:
        super().setUp()
        self.media = MediaService(SimpleNamespace(media_dir=self.root / "media"), self.contents)

    @staticmethod
    def image_stream() -> io.BytesIO:
        stream = io.BytesIO()
        Image.new("RGB", (800, 600), "green").save(stream, "PNG")
        stream.seek(0)
        return stream

    def test_image_is_streamed_and_thumbnail_created(self) -> None:
        content = self.create_content()
        updated = self.media.save_upload(content["id"], self.image_stream(), "photo.png", "image/png")
        record = updated["media"][0]
        self.assertTrue(self.media.resolve_existing(record["relative_path"]).is_file())
        self.assertTrue(self.media.resolve_existing(record["thumbnail_relative_path"]).is_file())

    def test_path_traversal_is_rejected(self) -> None:
        with self.assertRaises(MediaValidationError):
            self.media.resolve_existing("../outside.txt")

    def test_invalid_image_is_removed(self) -> None:
        content = self.create_content()
        with self.assertRaises(MediaValidationError):
            self.media.save_upload(content["id"], io.BytesIO(b"not an image"), "photo.png", "image/png")
        self.assertEqual(list((self.root / "media" / content["id"]).glob("*")), [])

    def test_library_deduplicates_and_preserves_references(self) -> None:
        first, second = self.create_content(), self.create_content()
        first_result = self.media.save_upload(first["id"], self.image_stream(), "first.png", "image/png")
        second_result = self.media.save_upload(second["id"], self.image_stream(), "second.png", "image/png")
        assets = self.media.assets.list()
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["reference_count"], 2)
        self.assertEqual(first_result["media"][0]["relative_path"], second_result["media"][0]["relative_path"])
        with self.assertRaises(MediaAssetInUseError):
            self.media.assets.delete(assets[0]["id"])

    def test_asset_metadata_tags_and_orphan_filter(self) -> None:
        asset = self.media.upload_asset(self.image_stream(), "photo.png", "image/png", alt_text="Original")
        updated = self.media.assets.update(asset["id"], "Banner", [" Campaign ", "campaign", "Green"], None)
        self.assertEqual(updated["tags"], ["campaign", "green"])
        self.assertEqual(self.media.assets.list(orphan_only=True)[0]["alt_text"], "Banner")


class BrandProfileRepositoryTests(ContentFixture):
    def test_brand_profile_crud_and_delete(self) -> None:
        created = self.brands.create({
            "name": "Tinix Hub",
            "tone": "Chuyên nghiệp",
            "pronouns": "Tinix - Bạn",
            "preferred_keywords": ["tự động hóa", "uy tín"],
            "forbidden_keywords": ["lừa đảo"],
            "sample_ctas": ["Đăng ký ngay!"],
        })
        self.assertEqual(created["name"], "Tinix Hub")
        self.assertEqual(created["preferred_keywords"], ["tự động hóa", "uy tín"])

        updated = self.brands.update(created["id"], {
            "name": "Tinix Social Hub",
            "tone": "Năng động",
            "pronouns": "Tinix - Bạn",
            "preferred_keywords": ["tiết kiệm thời gian"],
            "forbidden_keywords": [],
            "sample_ctas": ["Bắt đầu ngay!"],
        })
        self.assertEqual(updated["name"], "Tinix Social Hub")
        self.assertEqual(updated["tone"], "Năng động")

        self.assertTrue(self.brands.delete(created["id"]))
        self.assertIsNone(self.brands.get(created["id"]))
        self.assertFalse(self.brands.delete(created["id"]))


class PromptTemplateRepositoryTests(ContentFixture):
    def setUp(self) -> None:
        super().setUp()
        self.prompts = PromptTemplateRepository(self.database)

    def test_seeded_prompts_and_custom_crud(self) -> None:
        self.assertEqual(self.prompts.get("system-write")["operation"], "write")
        created = self.prompts.create({"name": "Ưu đãi cuối tuần", "system_prompt": "Ưu tiên lợi ích cụ thể.", "enabled": True})
        self.assertTrue(created["enabled"])
        updated = self.prompts.update(created["id"], {
            "name": "Ưu đãi cuối tuần mới", "system_prompt": "Ưu tiên lợi ích và CTA.", "enabled": False,
        })
        self.assertFalse(updated["enabled"])
        self.assertNotIn(created["id"], [item["id"] for item in self.prompts.list(enabled_only=True)])
        self.assertTrue(self.prompts.delete(created["id"]))


class AIStudioTests(ContentFixture):
    def test_mock_generation_saves_draft_and_usage(self) -> None:
        generations = AIGenerationRepository(self.database)
        studio = AIContentStudioService(MockAIProvider(), generations, self.brands, self.contents)
        result = asyncio.run(studio.generate("write", "New product", None, ["facebook"], True))
        self.assertEqual(result["content"]["approval_status"], "draft")
        self.assertEqual(result["structured_content"]["topic"], "Mock topic")
        self.assertTrue(bool(result["structured_content"]["image_prompt"]))
        with self.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM ai_generations").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT total_tokens FROM ai_usage").fetchone()[0], 2)

    def test_generation_uses_selected_prompt_and_attaches_reference_image(self) -> None:
        class RecordingProvider(MockAIProvider):
            def __init__(self) -> None:
                super().__init__()
                self.images = []

            async def generate_structured(self, prompt, system, images=None):
                self.images = images or []
                self.system = system
                self.prompt = prompt
                return await super().generate_structured(prompt, system, images)

        media = MediaService(SimpleNamespace(media_dir=self.root / "media"), self.contents)
        asset = media.upload_asset(MediaServiceTests.image_stream(), "reference.png", "image/png", alt_text="Sản phẩm màu xanh")
        provider = RecordingProvider()
        studio = AIContentStudioService(
            provider, AIGenerationRepository(self.database), self.brands, self.contents,
            PromptTemplateRepository(self.database), media,
        )
        result = asyncio.run(studio.generate(
            None, "Ra mắt sản phẩm", None, ["facebook"], True,
            prompt_template_id="system-write", media_asset_ids=[asset["id"]],
        ))
        self.assertIn("Tạo một bài viết mới", provider.system)
        self.assertIn("<MEDIA_CONTEXT>", provider.prompt)
        self.assertEqual(len(provider.images), 1)
        self.assertTrue(provider.images[0].data_url.startswith("data:image/jpeg;base64,"))
        self.assertEqual(result["content"]["media"][0]["asset_id"], asset["id"])

class SchedulingTests(ContentFixture):
    def setUp(self) -> None:
        super().setUp()
        self.accounts = AccountRepository(self.database)
        self.targets = TargetRepository(self.database)
        self.jobs = JobRepository(self.database)
        self.publications = PublicationRepository(self.database)
        self.scheduling = SchedulingService(
            self.jobs, self.accounts, self.targets, self.contents, random.Random(1), self.publications
        )
        self.account = self.accounts.create("Admin", "facebook")
        self.target = self.targets.sync(
            self.account["id"], "facebook",
            [{"external_id": "123", "name": "Main Page", "url": "https://facebook.com/123"}],
        )[0]
        self.content = self.create_content()

    def _complete_dry_run(self) -> dict:
        job = self.scheduling.schedule(
            self.content["id"], self.account["id"], [self.target["id"]], None, True, 0, 0, "confirm"
        )[0]
        self.assertEqual(self.jobs.claim_next()["id"], job["id"])
        self.jobs.transition(job["id"], "checking_login")
        self.jobs.transition(job["id"], "publishing")
        self.jobs.dry_run_ready(job["id"], {"post_url": None})
        return job

    def test_real_schedule_requires_current_approval(self) -> None:
        with self.assertRaises(SchedulingError):
            self.scheduling.schedule(
                self.content["id"], self.account["id"], [self.target["id"]], None, False, 0, 0, "confirm"
            )

    def test_real_schedule_requires_current_route_dry_run(self) -> None:
        approval = self.contents.request_approval(self.content["id"])
        self.contents.decide_approval(approval["id"], True)
        with self.assertRaisesRegex(SchedulingError, "dry-run thành công"):
            self.scheduling.schedule(
                self.content["id"], self.account["id"], [self.target["id"]], None, False, 0, 0, "confirm"
            )
        self.assertEqual(self.publications.list_releases(), [])

    def test_real_schedule_rejects_dry_run_with_stale_selector(self) -> None:
        dry_run = self._complete_dry_run()
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE publication_releases SET selector_version='facebook-web-v0' WHERE job_id=?",
                (dry_run["id"],),
            )
        approval = self.contents.request_approval(self.content["id"])
        self.contents.decide_approval(approval["id"], True)
        with self.assertRaisesRegex(SchedulingError, "dry-run thành công"):
            self.scheduling.schedule(
                self.content["id"], self.account["id"], [self.target["id"]], None, False, 0, 0, "confirm"
            )

    def test_later_same_route_dry_run_resolves_old_permanent_failure_health(self) -> None:
        failed = self.scheduling.schedule(
            self.content["id"], self.account["id"], [self.target["id"]], None, True, 0, 0, "confirm"
        )[0]
        self.assertEqual(self.jobs.claim_next()["id"], failed["id"])
        self.jobs.transition(failed["id"], "checking_login")
        self.jobs.transition(failed["id"], "permanent_failure", error="selector missing", failure_code="selector")
        self.assertEqual(self.jobs.health_counts()["needs_attention"], 1)

        self.contents.update(self.content["id"], {
            "title": "Launch retry", "caption": "Updated after failure", "hashtags": ["#tinix"],
            "platform_variants": {"facebook": {"caption": "Facebook retry", "hashtags": ["#fb"]}},
        })
        self._complete_dry_run()
        self.assertEqual(self.jobs.health_counts()["needs_attention"], 0)

    def test_approved_schedule_is_idempotent(self) -> None:
        self._complete_dry_run()
        approval = self.contents.request_approval(self.content["id"])
        self.contents.decide_approval(approval["id"], True)
        due = datetime.now(timezone.utc) + timedelta(hours=1)
        first = self.scheduling.schedule(
            self.content["id"], self.account["id"], [self.target["id"]], due, False, 0, 0, "confirm"
        )
        second = self.scheduling.schedule(
            self.content["id"], self.account["id"], [self.target["id"]], due, False, 0, 0, "confirm"
        )
        self.assertEqual(first[0]["id"], second[0]["id"])
        self.assertEqual(first[0]["dry_run"], 0)

    def test_publisher_verified_result_marks_release_verified(self) -> None:
        self._complete_dry_run()
        approval = self.contents.request_approval(self.content["id"])
        self.contents.decide_approval(approval["id"], True)
        job = self.scheduling.schedule(
            self.content["id"], self.account["id"], [self.target["id"]], None, False, 0, 0, "confirm"
        )[0]
        self.assertEqual(self.jobs.claim_next()["id"], job["id"])
        self.jobs.transition(job["id"], "checking_login")
        self.jobs.transition(job["id"], "publishing")
        self.jobs.transition(job["id"], "verifying", commit_reached=True)
        self.jobs.complete(job["id"], {
            "outcome": "published", "post_url": "https://www.facebook.com/page/posts/123",
        })

        release = self.publications.get_release(job["publication_release_id"])
        self.assertEqual(release["status"], "succeeded")
        self.assertEqual(release["verification_status"], "verified")
        self.assertEqual(release["verification_method"], "publisher")
        self.assertIsNotNone(release["verified_at"])

    def test_dry_run_is_allowed_for_draft(self) -> None:
        jobs = self.scheduling.schedule(
            self.content["id"], self.account["id"], [self.target["id"]], None, True, 0, 0, "confirm"
        )
        self.assertEqual(jobs[0]["status"], "queued")
        self.assertEqual(jobs[0]["dry_run"], 1)

    def test_system_navigation_target_is_rejected_even_if_legacy_row_is_enabled(self) -> None:
        target_id = "legacy-facebook-navigation"
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO publishing_targets(id,account_id,platform,target_type,external_id,name,url,enabled,access_status,created_at,updated_at) "
                "VALUES(?,?, 'facebook','page','url:latest','Meta Business Suite','https://facebook.com/latest',1,'accessible',datetime('now'),datetime('now'))",
                (target_id, self.account["id"]),
            )
        with self.assertRaisesRegex(SchedulingError, "liên kết điều hướng"):
            self.scheduling.schedule(
                self.content["id"], self.account["id"], [target_id], None, True, 0, 0, "confirm"
            )

    def test_instagram_dry_run_schedule_uses_provider_variant(self) -> None:
        account = self.accounts.create("Instagram", "instagram")
        target = self.targets.sync(account["id"], "instagram", [{
            "external_id": "profile", "name": "Profile", "url": "https://www.instagram.com/profile/",
            "target_type": "profile",
        }])[0]
        content = self.contents.create({
            "title": "IG", "caption": "Base", "hashtags": [],
            "platform_variants": {"instagram": {"caption": "Instagram caption", "hashtags": ["#ig"]}},
        })
        self.contents.add_media(content["id"], {
            "media_type": "image", "relative_path": "fixture.png", "original_name": "fixture.png",
            "mime_type": "image/png", "size_bytes": 10, "sha256": "a" * 64,
        })
        job = self.scheduling.schedule(
            content["id"], account["id"], [target["id"]], None, True, 0, 0, "confirm", "image", {}
        )[0]
        self.assertEqual(job["payload"]["caption"], "Instagram caption")
        self.assertEqual(job["payload"]["content_format"], "image")

    def test_schedule_creates_frozen_plan_release_and_job_link(self) -> None:
        jobs = self.scheduling.schedule(
            self.content["id"], self.account["id"], [self.target["id"]], None, True, 0, 0, "confirm"
        )
        plans = self.publications.list_plans()
        self.assertEqual(len(plans), 1)
        self.assertEqual(len(plans[0]["releases"]), 1)
        release = plans[0]["releases"][0]
        self.assertEqual(jobs[0]["publication_release_id"], release["id"])
        self.assertEqual(release["publication_transport"], "chrome")
        self.assertEqual(release["selector_version"], "facebook-web-v1")
        self.assertEqual(release["payload_snapshot"]["caption"], "Facebook caption")
        self.assertEqual(release["content_revision_id"], self.contents.revisions(self.content["id"])[0]["id"])

        self.contents.update(self.content["id"], {
            "title": "Changed later", "caption": "Changed later", "hashtags": [], "platform_variants": {}
        })
        frozen = self.publications.get_release(release["id"])
        self.assertEqual(frozen["payload_snapshot"]["caption"], "Facebook caption")

    def test_plan_and_release_are_idempotent_with_schedule(self) -> None:
        first = self.scheduling.schedule(
            self.content["id"], self.account["id"], [self.target["id"]], None, True, 0, 0, "confirm"
        )
        second = self.scheduling.schedule(
            self.content["id"], self.account["id"], [self.target["id"]], None, True, 0, 0, "confirm"
        )
        self.assertEqual(first[0]["id"], second[0]["id"])
        self.assertEqual(len(self.publications.list_plans()), 1)
        self.assertEqual(len(self.publications.list_releases()), 1)

    def test_job_state_is_aggregated_to_plan(self) -> None:
        job = self.scheduling.schedule(
            self.content["id"], self.account["id"], [self.target["id"]], None, True, 0, 0, "confirm"
        )[0]
        claimed = self.jobs.claim_next()
        self.assertEqual(claimed["id"], job["id"])
        plan_id = self.publications.get_release(job["publication_release_id"])["plan_id"]
        self.assertEqual(self.publications.get_plan(plan_id)["status"], "active")
        self.jobs.transition(job["id"], "checking_login")
        self.jobs.transition(job["id"], "publishing")
        self.jobs.dry_run_ready(job["id"], {"post_url": None})
        self.assertEqual(self.publications.get_plan(plan_id)["status"], "completed")


if __name__ == "__main__":
    unittest.main()
