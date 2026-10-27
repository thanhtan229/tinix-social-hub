from __future__ import annotations

import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.db.calendar_repositories import PostingSlotRepository, SlotValidationError
from app.db.content_repositories import ContentRepository
from app.db.database import Database
from app.db.publication_repositories import PublicationRepository
from app.db.repositories import AccountRepository, JobRepository, TargetRepository
from app.services.scheduling import SchedulingService
from app.platforms.validation import PlatformValidationError, validate_publication


class CalendarAndSlotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.database = Database(root / "data" / "tinix_social.db", root / "backups")
        self.database.initialize()
        self.accounts = AccountRepository(self.database)
        self.targets = TargetRepository(self.database)
        self.contents = ContentRepository(self.database)
        self.jobs = JobRepository(self.database)
        self.publications = PublicationRepository(self.database)
        self.slots = PostingSlotRepository(self.database)
        self.account = self.accounts.create("Admin", "facebook")
        self.target = self.targets.sync(
            self.account["id"], "facebook",
            [{"external_id": "page-1", "name": "Page", "url": "https://facebook.com/page-1"}],
        )[0]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_slots_are_normalized_and_timezone_is_validated(self) -> None:
        slots = self.slots.replace(self.target["id"], "Asia/Bangkok", [
            {"weekday": 1, "minute_of_day": 540},
            {"weekday": 1, "minute_of_day": 540},
            {"weekday": 0, "minute_of_day": 600},
        ])
        self.assertEqual([(item["weekday"], item["minute_of_day"]) for item in slots], [(0, 600), (1, 540)])
        with self.assertRaises(SlotValidationError):
            self.slots.replace(self.target["id"], "Not/AZone", [])

    def test_find_next_skips_nonexistent_dst_wall_time(self) -> None:
        self.slots.replace(self.target["id"], "America/New_York", [
            {"weekday": 6, "minute_of_day": 150},  # Sunday 02:30
        ])
        after = datetime(2025, 3, 8, 12, tzinfo=timezone.utc)
        result = self.slots.find_next(self.target["id"], after)
        self.assertEqual(result, datetime(2025, 3, 16, 6, 30, tzinfo=timezone.utc))

    def test_find_next_requires_configured_slots(self) -> None:
        with self.assertRaises(SlotValidationError):
            self.slots.find_next(self.target["id"])

    def test_safe_release_can_be_rescheduled_with_audit(self) -> None:
        content = self.contents.create({
            "title": "Post", "caption": "Hello", "hashtags": [],
            "platform_variants": {"facebook": {"caption": "Hello", "hashtags": []}},
        })
        scheduling = SchedulingService(
            self.jobs, self.accounts, self.targets, self.contents, random.Random(1), self.publications
        )
        first_due = datetime.now(timezone.utc) + timedelta(hours=2)
        job = scheduling.schedule(
            content["id"], self.account["id"], [self.target["id"]], first_due, True, 0, 0, "confirm"
        )[0]
        second_due = datetime.now(timezone.utc) + timedelta(days=1)
        release = self.publications.reschedule_release(
            job["publication_release_id"], second_due.isoformat(), "Asia/Bangkok"
        )
        self.assertEqual(release["scheduled_at"], second_due.isoformat())
        self.assertEqual(self.jobs.get(job["id"])["scheduled_at"], second_due.isoformat())
        self.assertEqual(self.publications.release_events(release["id"])[0]["event_type"], "rescheduled")

    def test_bulk_reschedule_is_atomic_across_releases(self) -> None:
        content = self.contents.create({
            "title": "Batch post", "caption": "Hello", "hashtags": [],
            "platform_variants": {"facebook": {"caption": "Hello", "hashtags": []}},
        })
        scheduling = SchedulingService(
            self.jobs, self.accounts, self.targets, self.contents, random.Random(1), self.publications
        )
        first = scheduling.schedule(
            content["id"], self.account["id"], [self.target["id"]],
            datetime.now(timezone.utc) + timedelta(hours=2), True, 0, 0, "confirm"
        )[0]
        second = scheduling.schedule(
            content["id"], self.account["id"], [self.target["id"]],
            datetime.now(timezone.utc) + timedelta(hours=3), True, 0, 0, "confirm"
        )[0]
        due = datetime.now(timezone.utc) + timedelta(days=2)
        moved = self.publications.reschedule_releases(
            [first["publication_release_id"], second["publication_release_id"]], due.isoformat(), "Asia/Bangkok"
        )
        self.assertEqual([item["scheduled_at"] for item in moved], [due.isoformat(), due.isoformat()])

        original = self.publications.get_release(first["publication_release_id"])["scheduled_at"]
        with self.database.connection() as connection:
            connection.execute("UPDATE jobs SET status='succeeded' WHERE id=?", (second["id"],))
        with self.assertRaisesRegex(ValueError, "không release nào được đổi lịch"):
            self.publications.reschedule_releases(
                [first["publication_release_id"], second["publication_release_id"]],
                (due + timedelta(days=1)).isoformat(), "Asia/Bangkok",
            )
        self.assertEqual(self.publications.get_release(first["publication_release_id"])["scheduled_at"], original)

    def test_platform_format_validation_is_schema_driven(self) -> None:
        schema = validate_publication(
            "tiktok", "short_video", "Caption", [{"type": "video", "size_bytes": 10}],
            {"privacy": "private", "allow_comments": False},
        )
        self.assertEqual(schema.id, "short_video")
        with self.assertRaises(PlatformValidationError) as context:
            validate_publication("instagram", "carousel", "Caption", [{"type": "image"}], {})
        self.assertIn("2-10 media", str(context.exception))
        self.assertEqual(validate_publication("x", "post", "Hello X", [], {}).id, "post")
        with self.assertRaises(PlatformValidationError):
            validate_publication("x", "post", "x" * 281, [], {})

    def test_x_schedule_counts_hashtags_toward_character_limit(self) -> None:
        x_account = self.accounts.create("X profile", "x")
        x_target = self.targets.sync(
            x_account["id"], "x",
            [{"external_id": "tinix", "name": "Tinix", "url": "https://x.com/tinix"}],
        )[0]
        content = self.contents.create({
            "title": "Long X post", "caption": "x" * 275, "hashtags": ["#tinix"],
            "platform_variants": {},
        })
        scheduling = SchedulingService(
            self.jobs, self.accounts, self.targets, self.contents,
            random.Random(1), self.publications,
        )
        with self.assertRaisesRegex(ValueError, "280"):
            scheduling.schedule(
                content["id"], x_account["id"], [x_target["id"]],
                None, True, 0, 0, "confirm", "post", {},
            )


if __name__ == "__main__":
    unittest.main()
