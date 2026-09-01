from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.db.database import MIGRATIONS, Database, utc_now
from app.db.repositories import AccountRepository, JobRepository
from app.domain.jobs import InvalidJobTransition, validate_transition
from app.services.ai import OpenAICompatibleProvider
from app.services.publishers import PublisherRegistry
from app.services.worker import LocalWorker


class MigrationTests(unittest.TestCase):
    def test_v1_database_migrates_without_losing_rows_and_creates_prebackup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "data" / "tinix_social.db"
            path.parent.mkdir(parents=True)
            connection = sqlite3.connect(path, isolation_level=None)
            for statement in MIGRATIONS[0][1].split(";"):
                if statement.strip():
                    connection.execute(statement)
            now = utc_now()
            connection.execute("INSERT INTO schema_version(version,applied_at) VALUES(1,?)", (now,))
            connection.execute(
                "INSERT INTO accounts(id,name,platform,profile_key,created_at,updated_at) VALUES('a1','Page','facebook','a1',?,?)",
                (now, now),
            )
            connection.execute(
                "INSERT INTO jobs(id,account_id,kind,status,payload_json,created_at,updated_at) VALUES('j1','a1','publish','queued','{}',?,?)",
                (now, now),
            )
            connection.close()

            database = Database(path, root / "backups")
            self.assertTrue(database.initialize())
            with database.connection() as migrated:
                self.assertEqual(migrated.execute("SELECT MAX(version) FROM schema_version").fetchone()[0], 4)
                self.assertEqual(migrated.execute("SELECT name FROM accounts WHERE id='a1'").fetchone()[0], "Page")
                job = migrated.execute("SELECT status,dry_run FROM jobs WHERE id='j1'").fetchone()
                self.assertEqual((job["status"], job["dry_run"]), ("queued", 1))
                tables = {row[0] for row in migrated.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertIn("content_items", tables)
                self.assertIn("publishing_targets", tables)
                self.assertIn("publish_job_events", tables)
            self.assertEqual(len(list((root / "backups").glob("tinix-pre-migration-v2-*.db"))), 1)
            self.assertTrue(database.integrity_check()["ok"])


class StateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.database = Database(root / "data" / "tinix_social.db", root / "backups")
        self.database.initialize()
        self.jobs = JobRepository(self.database, retry_base_seconds=10, retry_cap_seconds=30)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_invalid_transition_is_rejected(self) -> None:
        with self.assertRaises(InvalidJobTransition):
            validate_transition("queued", "succeeded")

    def test_retry_waits_for_next_attempt(self) -> None:
        job = self.jobs.create("ai_content", {"prompt": "x"}, None, None)
        self.jobs.claim_next()
        self.jobs.fail(job["id"], "temporary")
        failed = self.jobs.get(job["id"])
        self.assertEqual(failed["status"], "temporary_failure")
        self.assertIsNotNone(failed["next_attempt_at"])
        self.assertEqual(self.jobs.release_due(), 0)
        with self.database.connection() as connection:
            connection.execute("UPDATE jobs SET next_attempt_at='2000-01-01T00:00:00+00:00' WHERE id=?", (job["id"],))
        self.assertEqual(self.jobs.release_due(), 1)
        self.assertEqual(self.jobs.get(job["id"])["status"], "queued")

    def test_publish_recovery_after_commit_path_is_unknown(self) -> None:
        job = self.jobs.create("publish", {}, None, None)
        self.jobs.claim_next()
        self.jobs.transition(job["id"], "checking_login")
        self.jobs.transition(job["id"], "publishing")
        self.assertEqual(self.jobs.recover_interrupted(), 1)
        self.assertEqual(self.jobs.get(job["id"])["status"], "unknown_result")


class WorkerPublisherSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.database = Database(root / "data" / "tinix_social.db", root / "backups")
        self.database.initialize()
        self.accounts = AccountRepository(self.database)
        self.jobs = JobRepository(self.database)
        self.settings = SimpleNamespace(
            max_concurrent_jobs=1,
            job_poll_seconds=1,
            ai_api_key="",
            ai_base_url="https://example.invalid",
            ai_model="mock",
            ai_timeout_seconds=5,
            ai_max_retries=0,
        )
        self.worker = LocalWorker(
            self.settings,
            self.jobs,
            self.accounts,
            OpenAICompatibleProvider(self.settings),
            PublisherRegistry(),
        )
        await self.worker.start()

    async def asyncTearDown(self) -> None:
        await self.worker.stop()
        self.temp.cleanup()

    async def wait_for_terminal(self, job_id: str) -> dict:
        for _ in range(100):
            job = self.jobs.get(job_id)
            if job["status"] in {"dry_run_ready", "permanent_failure", "succeeded"}:
                return job
            await asyncio.sleep(0.02)
        self.fail("Job did not finish")

    async def test_preview_can_only_finish_as_dry_run_ready(self) -> None:
        account = self.accounts.create("Page", "facebook")
        job = self.jobs.create("publish", {"text": "hello"}, account["id"], None, dry_run=True)
        self.worker.notify()
        finished = await self.wait_for_terminal(job["id"])
        self.assertEqual(finished["status"], "dry_run_ready")

    async def test_unregistered_real_publisher_is_not_success(self) -> None:
        account = self.accounts.create("Page", "facebook")
        job = self.jobs.create("publish", {"text": "hello"}, account["id"], None, dry_run=False)
        self.worker.notify()
        finished = await self.wait_for_terminal(job["id"])
        self.assertEqual(finished["status"], "permanent_failure")
        self.assertEqual(finished["failure_code"], "unsupported")


if __name__ == "__main__":
    unittest.main()

