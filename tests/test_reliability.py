from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.db.database import Database
from app.db.notification_repositories import NotificationRepository
from app.db.repositories import AccountRepository, JobRepository


class ReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.database = Database(root / "data" / "tinix_social.db", root / "backups")
        self.database.initialize()
        self.jobs = JobRepository(self.database, retry_base_seconds=1)
        self.account = AccountRepository(self.database).create("Main", "facebook")
        self.notifications = NotificationRepository(self.database)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_failure_notification_and_safe_manual_retry(self) -> None:
        job = self.jobs.create("publish", {}, self.account["id"], None, max_attempts=1)
        claimed = self.jobs.claim_next()
        self.assertEqual(claimed["id"], job["id"])
        self.jobs.fail(job["id"], "selector missing", "selector")
        failed = self.jobs.get(job["id"])
        self.assertEqual(failed["status"], "permanent_failure")
        notices = self.notifications.list(unread_only=True)
        self.assertEqual(notices[0]["notification_type"], "failed")
        retried = self.jobs.retry(job["id"])
        self.assertEqual(retried["status"], "queued")
        self.assertEqual(self.jobs.events(job["id"])[-1]["event_type"], "manual_retry")

    def test_unknown_result_cannot_retry_and_requires_finalize(self) -> None:
        job = self.jobs.create("publish", {}, self.account["id"], None)
        self.jobs.claim_next()
        self.jobs.transition(job["id"], "checking_login")
        self.jobs.transition(job["id"], "publishing")
        self.jobs.transition(job["id"], "verifying", commit_reached=True)
        self.jobs.transition(job["id"], "unknown_result")
        with self.assertRaises(ValueError):
            self.jobs.retry(job["id"])
        final = self.jobs.finalize_unknown(job["id"], True, "Đã kiểm tra trên UI", "https://example.test/post")
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(final["result"]["manual_verification"], True)

    def test_detail_contains_attempt_events_and_health(self) -> None:
        job = self.jobs.create("publish", {}, self.account["id"], None)
        self.jobs.claim_next()
        detail = self.jobs.detail(job["id"])
        self.assertEqual(len(detail["attempt_history"]), 1)
        self.assertGreaterEqual(len(detail["events"]), 2)
        self.assertEqual(self.jobs.health_counts()["needs_attention"], 0)


if __name__ == "__main__":
    unittest.main()
