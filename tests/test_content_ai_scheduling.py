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


class AIStudioTests(ContentFixture):
    def test_mock_generation_saves_draft_and_usage(self) -> None:
        generations = AIGenerationRepository(self.database)
        studio = AIContentStudioService(MockAIProvider(), generations, self.brands, self.contents)
        result = asyncio.run(studio.generate("write", "New product", None, ["facebook"], True))
        self.assertEqual(result["content"]["approval_status"], "draft")
        self.assertEqual(result["structured_content"]["topic"], "Mock topic")
        with self.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM ai_generations").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT total_tokens FROM ai_usage").fetchone()[0], 2)


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

    def test_real_schedule_requires_current_approval(self) -> None:
        with self.assertRaises(SchedulingError):
            self.scheduling.schedule(
                self.content["id"], self.account["id"], [self.target["id"]], None, False, 0, 0, "confirm"
            )

    def test_approved_schedule_is_idempotent(self) -> None:
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

    def test_dry_run_is_allowed_for_draft(self) -> None:
        jobs = self.scheduling.schedule(
            self.content["id"], self.account["id"], [self.target["id"]], None, True, 0, 0, "confirm"
        )
        self.assertEqual(jobs[0]["status"], "queued")
        self.assertEqual(jobs[0]["dry_run"], 1)

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
