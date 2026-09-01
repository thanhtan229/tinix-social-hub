from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.db.database import Database
from app.db.repositories import AccountRepository, JobRepository


class DatabaseAndQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db = Database(root / "data" / "tinix_social.db", root / "backups")
        self.db.initialize()
        self.accounts = AccountRepository(self.db)
        self.jobs = JobRepository(self.db)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_sqlite_pragmas_and_integrity(self) -> None:
        with self.db.connection() as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertTrue(self.db.integrity_check()["ok"])

    def test_only_one_job_per_account_can_be_claimed(self) -> None:
        account = self.accounts.create("Kênh chính", "facebook")
        first = self.jobs.create("publish", {"text": "A"}, account["id"], None)
        second = self.jobs.create("publish", {"text": "B"}, account["id"], None)
        claimed = self.jobs.claim_next()
        self.assertEqual(claimed["id"], first["id"])
        self.assertIsNone(self.jobs.claim_next())
        self.jobs.complete(first["id"], {"ok": True})
        self.assertEqual(self.jobs.claim_next()["id"], second["id"])

    def test_interrupted_job_is_recovered(self) -> None:
        job = self.jobs.create("ai_content", {"prompt": "x"}, None, None)
        self.assertEqual(self.jobs.claim_next()["id"], job["id"])
        self.assertEqual(self.jobs.recover_interrupted(), 1)
        self.assertEqual(self.jobs.get(job["id"])["status"], "queued")

    def test_backup_and_restore(self) -> None:
        self.accounts.create("Before", "instagram")
        backup = self.db.create_backup()
        self.accounts.create("After", "youtube")
        self.assertEqual(len(self.accounts.list()), 2)
        self.db.restore_backup(backup.name)
        self.assertEqual([item["name"] for item in self.accounts.list()], ["Before"])
        self.assertTrue(self.db.integrity_check()["ok"])


if __name__ == "__main__":
    unittest.main()

