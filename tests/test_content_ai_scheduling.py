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
from app.db.provider_repositories import ProviderConnectionRepository
from app.db.prompt_repositories import PromptTemplateRepository
from app.db.publication_repositories import PublicationRepository
from app.db.repositories import AccountRepository, JobRepository, TargetRepository
from app.services.ai import MockAIProvider
from app.services.ai_studio import AIContentStudioService
from app.services.media import MediaService, MediaValidationError
from app.core.secrets import SecretProtector
from app.db.media_repositories import MediaAssetInUseError
from app.platforms.providers.meta import MetaPagePublisher
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
    def test_composition_survives_legacy_updates_duplicate_and_revision_restore(self) -> None:
        composition = {
            "version": 1,
            "global_content": {"caption": "Global", "hashtags": ["#all"], "cta": ""},
            "platform_overrides": {"facebook": {"caption": "Facebook", "hashtags": ["#fb"], "cta": ""}},
            "target_overrides": {"page-b": {"caption": "Page B", "hashtags": [], "cta": ""}},
        }
        content = self.contents.create({"title": "Launch", "caption": "Global", "composition": composition})
        original_revision = self.contents.revisions(content["id"])[0]

        # Clients predating the composition field may update ordinary content fields.
        updated = self.contents.update(content["id"], {
            "title": "Launch v2", "caption": "Legacy edit", "hashtags": [], "platform_variants": {},
        })
        self.assertEqual(updated["composition"], composition)

        duplicate = self.contents.duplicate(content["id"])
        self.assertEqual(duplicate["composition"], composition)

        restored = self.contents.restore_revision(content["id"], original_revision["id"])
        self.assertEqual(restored["composition"], composition)

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

    def test_media_changes_create_revisions_and_restore_media_references(self) -> None:
        content = self.create_content()
        initial_revision = self.contents.revisions(content["id"])[0]["id"]
        approval = self.contents.request_approval(content["id"])
        self.contents.decide_approval(approval["id"], True)

        asset = self.media.upload_asset(self.image_stream(), "revision.png", "image/png")
        self.media.attach_asset(content["id"], asset["id"])
        current = self.contents.get(content["id"])
        attached_revision = self.contents.revisions(content["id"])[0]
        self.assertEqual(current["approval_status"], "draft")
        self.assertEqual(current["current_revision"], 2)
        self.assertEqual(len(current["media"]), 1)
        with self.database.connection() as connection:
            stored = connection.execute("SELECT snapshot_json FROM content_revisions WHERE id=?", (attached_revision["id"],)).fetchone()[0]
        self.assertIn(asset["id"], stored)

        self.media.assets.detach(asset["id"], content["id"])
        self.assertEqual(self.contents.get(content["id"])["media"], [])
        restored = self.contents.restore_revision(content["id"], attached_revision["id"])
        self.assertEqual(len(restored["media"]), 1)
        with self.assertRaises(MediaAssetInUseError):
            self.media.assets.delete(asset["id"])

        restored = self.contents.restore_revision(content["id"], initial_revision)
        self.assertEqual(restored["media"], [])

    def test_duplicate_keeps_media_in_its_current_revision(self) -> None:
        content = self.contents.create({"title": "With media", "caption": "Copy"})
        self.contents.add_media(content["id"], {
            "media_type": "image", "relative_path": "fixture/image.png", "original_name": "image.png",
            "mime_type": "image/png", "size_bytes": 10, "sha256": "b" * 64,
        })
        duplicate = self.contents.duplicate(content["id"])
        self.assertEqual(len(duplicate["media"]), 1)
        with self.database.connection() as connection:
            snapshot = connection.execute(
                "SELECT snapshot_json FROM content_revisions WHERE content_id=? ORDER BY revision_number DESC LIMIT 1",
                (duplicate["id"],),
            ).fetchone()[0]
        self.assertIn("image.png", snapshot)

    def test_target_media_override_is_versioned_restorable_and_protected(self) -> None:
        content = self.contents.create({"title": "Target media", "caption": "Copy"})
        account = AccountRepository(self.database).create("Media account", "facebook")
        target = TargetRepository(self.database).sync(
            account["id"], "facebook", [{"external_id": "page-media", "name": "Media Page"}],
        )[0]
        asset = self.media.upload_asset(self.image_stream(), "page.png", "image/png")
        initial_revision = self.contents.revisions(content["id"])[0]["id"]

        updated = self.media.assets.set_target_override(content["id"], target["id"], [asset["id"]])
        self.assertEqual([item["asset_id"] for item in updated["target_media_overrides"][target["id"]]], [asset["id"]])
        self.assertEqual(updated["media"], [])
        self.assertEqual(updated["current_revision"], 2)
        self.assertEqual(self.media.assets.get(asset["id"])["reference_count"], 1)
        unchanged = self.media.assets.set_target_override(content["id"], target["id"], [asset["id"]])
        self.assertEqual(unchanged["current_revision"], 2)
        attached_revision = self.contents.revisions(content["id"])[0]["id"]

        empty = self.media.assets.set_target_override(content["id"], target["id"], [])
        self.assertEqual(empty["target_media_overrides"][target["id"]], [])
        restored = self.contents.restore_revision(content["id"], attached_revision)
        self.assertEqual([item["asset_id"] for item in restored["target_media_overrides"][target["id"]]], [asset["id"]])
        with self.assertRaises(MediaAssetInUseError):
            self.media.assets.delete(asset["id"])

        inherited = self.media.assets.set_target_override(content["id"], target["id"], [], inherit=True)
        self.assertNotIn(target["id"], inherited["target_media_overrides"])
        restored_initial = self.contents.restore_revision(content["id"], initial_revision)
        self.assertNotIn(target["id"], restored_initial["target_media_overrides"])


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

    def test_meta_media_preflight_receives_frozen_file_metadata(self) -> None:
        connection = ProviderConnectionRepository(self.database, SecretProtector()).upsert(
            account_id=self.account["id"], provider="meta", status="connected",
            scopes=["pages_manage_posts"],
        )
        publisher = SimpleNamespace(
            validate=MetaPagePublisher.validate,
            selector_version_for=MetaPagePublisher.selector_version_for,
            provider_version="meta-graph-v26.0",
        )
        route = SimpleNamespace(
            reason="official_api_only", transport="official_api", provider="meta",
            publisher=publisher, connection_id=connection["id"], connection_scopes_hash="scopes-1",
            provider_target_binding_id="binding-1", provider_target_external_id="123",
        )
        self.scheduling.publisher_router = SimpleNamespace(resolve=lambda *args, **kwargs: route)
        for content_format, media_items in (
            ("photo", [("image", "fixture/test.png", "image/png")]),
            ("multi_photo", [("image", "fixture/test.png", "image/png"),
                             ("image", "fixture/test-2.png", "image/png")]),
            ("video", [("video", "fixture/test.mp4", "video/mp4")]),
        ):
            with self.subTest(content_format=content_format):
                content = self.contents.create({"title": content_format, "caption": "Test"})
                for media_type, filename, mime_type in media_items:
                    self.contents.add_media(content["id"], {
                        "media_type": media_type, "relative_path": filename,
                        "original_name": Path(filename).name, "mime_type": mime_type,
                        "size_bytes": 1024, "sha256": "a" * 64,
                    })
                preview = self.scheduling.schedule_batch(
                    content_id=content["id"], target_ids=[self.target["id"]],
                    scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    dry_run=True, missed_policy="confirm", content_format=content_format,
                    platform_settings={}, routing_preference="official_api_only", preflight_only=True,
                )
                self.assertTrue(preview["ready"], preview["targets"])
                job = self.scheduling.schedule(
                    content["id"], self.account["id"], [self.target["id"]], None, True,
                    0, 0, "confirm", content_format, {}, "official_api_only",
                )[0]
                self.assertEqual(len(job["payload"]["media"]), len(media_items))
                self.assertEqual([item["mime_type"] for item in job["payload"]["media"]],
                                 [item[2] for item in media_items])

    def test_schedule_resolves_content_per_target_and_preserves_empty_overrides(self) -> None:
        self.targets.sync(
            self.account["id"], "facebook",
            [{"external_id": "124", "name": "Second Page", "url": "https://facebook.com/124"}],
        )
        second = next(item for item in self.targets.list(account_id=self.account["id"]) if item["external_id"] == "124")
        composition = {
            "version": 1,
            "global_content": {"caption": "Global copy", "hashtags": ["#global"], "cta": "Global CTA"},
            "platform_overrides": {},
            "target_overrides": {
                self.target["id"]: {"caption": "", "hashtags": [], "cta": ""},
                second["id"]: {"caption": "Page two", "hashtags": ["#two"], "cta": "CTA two"},
            },
        }
        self.content = self.contents.update(self.content["id"], {
            "title": self.content["title"], "caption": "Global copy", "hashtags": ["#global"],
            "platform_variants": {}, "composition": composition,
        })

        jobs = self.scheduling.schedule(
            self.content["id"], self.account["id"], [self.target["id"], second["id"]],
            None, True, 0, 0, "confirm",
        )
        by_target = {job["target_id"]: job["payload"] for job in jobs}
        self.assertEqual(by_target[self.target["id"]]["caption"], "")
        self.assertEqual(by_target[self.target["id"]]["hashtags"], [])
        self.assertEqual(by_target[self.target["id"]]["cta"], "")
        self.assertEqual(by_target[second["id"]]["caption"], "Page two")
        self.assertEqual(by_target[second["id"]]["hashtags"], ["#two"])
        self.assertEqual(by_target[second["id"]]["cta"], "CTA two")

    def test_batch_schedule_is_atomic_and_idempotent_across_accounts(self) -> None:
        second_account = self.accounts.create("Admin 2", "facebook")
        second_target = self.targets.sync(second_account["id"], "facebook", [{
            "external_id": "456", "name": "Partner Page", "url": "https://facebook.com/456",
        }])[0]
        third_target = self.targets.sync(self.account["id"], "facebook", [{
            "external_id": "789", "name": "Campaign Page", "url": "https://facebook.com/789",
        }])[0]
        due = datetime.now(timezone.utc) + timedelta(hours=1)
        second_due = due + timedelta(hours=1)
        target_scheduled_at = {second_target["id"]: second_due}
        request_key = "batch-request-0001"
        preview = self.scheduling.schedule_batch(
            content_id=self.content["id"], target_ids=[self.target["id"], second_target["id"], third_target["id"]],
            scheduled_at=due, dry_run=True, missed_policy="confirm", content_format="post",
            platform_settings={}, target_scheduled_at=target_scheduled_at, request_key=request_key,
            delay_seconds=20, random_delay_seconds=5, preflight_only=True,
        )
        self.assertTrue(preview["ready"])
        self.assertEqual(len(preview["targets"]), 3)
        self.assertEqual(self.publications.list_plans(), [])
        invalid_preview = self.scheduling.schedule_batch(
            content_id=self.content["id"], target_ids=[self.target["id"], "missing-target"],
            scheduled_at=due, dry_run=True, missed_policy="confirm", content_format="post",
            platform_settings={}, preflight_only=True,
        )
        self.assertFalse(invalid_preview["ready"])
        self.assertEqual({item["status"] for item in invalid_preview["targets"]}, {"ready", "error"})
        self.assertEqual(self.publications.list_plans(), [])

        first = self.scheduling.schedule_batch(
            content_id=self.content["id"], target_ids=[self.target["id"], second_target["id"], third_target["id"]],
            scheduled_at=due, dry_run=True, missed_policy="confirm", content_format="post",
            platform_settings={}, request_key=request_key, target_scheduled_at=target_scheduled_at,
            delay_seconds=20, random_delay_seconds=5,
        )
        retry = self.scheduling.schedule_batch(
            content_id=self.content["id"], target_ids=[self.target["id"], second_target["id"], third_target["id"]],
            scheduled_at=due, dry_run=True, missed_policy="confirm", content_format="post",
            platform_settings={}, request_key=request_key, target_scheduled_at=target_scheduled_at,
            delay_seconds=20, random_delay_seconds=5,
        )
        self.assertEqual({job["id"] for job in first}, {job["id"] for job in retry})
        self.assertEqual({job["target_id"] for job in first}, {self.target["id"], second_target["id"], third_target["id"]})
        due_by_target = {job["target_id"]: job["scheduled_at"] for job in first}
        self.assertEqual(due_by_target[self.target["id"]], due.isoformat())
        self.assertEqual(due_by_target[second_target["id"]], second_due.isoformat())
        preview_due_by_target = {item["target_id"]: item.get("scheduled_at") for item in preview["targets"]}
        self.assertEqual(due_by_target[third_target["id"]], preview_due_by_target[third_target["id"]])
        self.assertEqual(len(self.publications.list_plans()), 1)
        self.assertEqual(len(self.publications.list_releases()), 3)

        with self.assertRaises(SchedulingError):
            self.scheduling.schedule_batch(
                content_id=self.content["id"], target_ids=[self.target["id"], "missing-target"],
                scheduled_at=due, dry_run=True, missed_policy="confirm", content_format="post",
                platform_settings={}, request_key="batch-request-0002",
            )
        self.assertEqual(len(self.publications.list_plans()), 1)
        self.assertEqual(len(self.publications.list_releases()), 3)

        with self.assertRaisesRegex(SchedulingError, "đã được dùng"):
            self.scheduling.schedule_batch(
                content_id=self.content["id"], target_ids=[second_target["id"]],
                scheduled_at=due, dry_run=True, missed_policy="confirm", content_format="post",
                platform_settings={}, request_key=request_key,
            )

    def test_batch_schedule_resolves_distinct_platform_formats_and_settings(self) -> None:
        tiktok_account = self.accounts.create("TikTok Brand", "tiktok")
        tiktok_target = self.targets.sync(tiktok_account["id"], "tiktok", [{
            "external_id": "tinix-channel", "name": "Tinix Channel", "url": "https://www.tiktok.com/@tinix",
            "target_type": "channel",
        }])[0]
        content = self.contents.create({"title": "Cross platform", "caption": "Campaign caption", "hashtags": ["#tinix"]})
        self.contents.add_media(content["id"], {
            "media_type": "video", "relative_path": "fixture/campaign.mp4", "original_name": "campaign.mp4",
            "mime_type": "video/mp4", "size_bytes": 1024, "sha256": "c" * 64,
        })
        jobs = self.scheduling.schedule_batch(
            content_id=content["id"], target_ids=[self.target["id"], tiktok_target["id"]],
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1), dry_run=True,
            missed_policy="confirm", content_format="post", platform_settings={},
            target_content_formats={self.target["id"]: "post", tiktok_target["id"]: "short_video"},
            target_platform_settings={tiktok_target["id"]: {"privacy": "private", "allow_comments": False}},
            request_key="cross-platform-0001",
        )
        by_target = {job["target_id"]: job["payload"] for job in jobs}
        self.assertEqual(by_target[self.target["id"]]["content_format"], "post")
        self.assertEqual(by_target[tiktok_target["id"]]["content_format"], "short_video")
        self.assertEqual(by_target[tiktok_target["id"]]["platform_settings"]["privacy"], "private")
        self.assertIs(by_target[tiktok_target["id"]]["platform_settings"]["allow_comments"], False)
        self.assertEqual(by_target[tiktok_target["id"]]["media"][0]["type"], "video")

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

    def test_dry_run_evidence_is_bound_to_connection_and_granted_scopes(self) -> None:
        job = self._complete_dry_run()
        release_id = job["publication_release_id"]
        api_connection = ProviderConnectionRepository(self.database, SecretProtector()).upsert(
            account_id=self.account["id"], provider="youtube", status="connected",
            scopes=["youtube.upload"],
        )
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE publication_releases SET publication_transport='official_api',provider='youtube',"
                "provider_version='youtube-data-v3',selector_version='youtube-data-v3',connection_id=?,"
                "connection_scopes_hash='scopes-v1' WHERE id=?",
                (api_connection["id"], release_id),
            )
        evidence = self.publications.dry_run_evidence(
            account_id=self.account["id"], target_id=self.target["id"], content_format="post",
            transport="official_api", selector_version="youtube-data-v3", provider_version="youtube-data-v3",
            connection_id=api_connection["id"], connection_scopes_hash="scopes-v1",
        )
        changed_scope = self.publications.dry_run_evidence(
            account_id=self.account["id"], target_id=self.target["id"], content_format="post",
            transport="official_api", selector_version="youtube-data-v3", provider_version="youtube-data-v3",
            connection_id=api_connection["id"], connection_scopes_hash="scopes-v2",
        )
        changed_connection = self.publications.dry_run_evidence(
            account_id=self.account["id"], target_id=self.target["id"], content_format="post",
            transport="official_api", selector_version="youtube-data-v3", provider_version="youtube-data-v3",
            connection_id="connection-other", connection_scopes_hash="scopes-v1",
        )
        self.assertEqual(evidence["id"], release_id)
        self.assertIsNone(changed_scope)
        self.assertIsNone(changed_connection)

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
        detail = self.publications.release_detail(release["id"])
        self.assertEqual(detail["target"]["name"], "Main Page")
        self.assertEqual(detail["account"]["name"], "Admin")
        self.assertEqual(detail["payload_snapshot"]["caption"], "Facebook caption")
        self.assertNotIn("payload_snapshot_json", detail)
        self.assertNotIn("result_json", detail["job"])

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

    def test_release_listing_supports_newest_first_offset_and_target_filters(self) -> None:
        earlier = self.scheduling.schedule(
            self.content["id"], self.account["id"], [self.target["id"]],
            datetime.now(timezone.utc) + timedelta(days=1), True, 0, 0, "confirm",
        )[0]
        later = self.scheduling.schedule(
            self.content["id"], self.account["id"], [self.target["id"]],
            datetime.now(timezone.utc) + timedelta(days=2), True, 0, 0, "confirm",
        )[0]
        newest = self.publications.list_releases(
            platform="facebook", account_id=self.account["id"], target_id=self.target["id"],
            order="desc", limit=1, offset=0,
        )
        next_page = self.publications.list_releases(
            platform="facebook", account_id=self.account["id"], target_id=self.target["id"],
            order="desc", limit=1, offset=1,
        )
        self.assertEqual(newest[0]["job_id"], later["id"])
        self.assertEqual(next_page[0]["job_id"], earlier["id"])
        self.assertEqual(self.publications.list_releases(account_id="missing-account"), [])

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
