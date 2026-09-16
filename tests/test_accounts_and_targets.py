from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.db.database import Database
from app.db.repositories import AccountRepository, JobRepository, TargetRepository


class AccountAndTargetRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        database = Database(root / "data" / "tinix_social.db", root / "backups")
        database.initialize()
        self.database = database
        self.accounts = AccountRepository(database)
        self.targets = TargetRepository(database)
        self.jobs = JobRepository(database)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_profile_key_does_not_change_when_another_account_is_deleted(self) -> None:
        first = self.accounts.create("First", "facebook")
        second = self.accounts.create("Second", "facebook")
        original_key = second["profile_key"]
        self.assertTrue(self.accounts.delete_if_safe(first["id"]))
        self.assertEqual(self.accounts.get(second["id"])["profile_key"], original_key)

    def test_account_with_history_cannot_be_deleted(self) -> None:
        account = self.accounts.create("Page", "facebook")
        self.jobs.create("publish", {}, account["id"], None)
        self.assertFalse(self.accounts.delete_if_safe(account["id"]))

    def test_disabled_account_does_not_claim_jobs(self) -> None:
        account = self.accounts.create("Disabled", "facebook")
        self.accounts.set_enabled(account["id"], False, "manual")
        self.jobs.create("publish", {}, account["id"], None)
        self.assertIsNone(self.jobs.claim_next())

    def test_profile_locked_account_does_not_claim_jobs(self) -> None:
        account = self.accounts.create("Locked", "facebook")
        job = self.jobs.create("publish", {}, account["id"], None)
        with self.database.connection() as connection:
            connection.execute("UPDATE accounts SET profile_operation_locked=1 WHERE id=?", (account["id"],))
        self.assertIsNone(self.jobs.claim_next())
        self.assertEqual(self.jobs.get(job["id"])["status"], "queued")

    def test_target_sync_updates_by_external_id_without_duplicates(self) -> None:
        account = self.accounts.create("Page admin", "facebook")
        first = self.targets.sync(
            account["id"], "facebook",
            [{"external_id": "123", "name": "Old name", "url": "https://facebook.com/123"}],
        )
        second = self.targets.sync(
            account["id"], "facebook",
            [{"external_id": "123", "name": "New name", "url": "https://facebook.com/123"}],
        )
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["name"], "New name")
        self.assertEqual(first[0]["id"], second[0]["id"])

    def test_invalid_facebook_discovery_targets_are_removed(self) -> None:
        account = self.accounts.create("Page admin", "facebook")
        synced = self.targets.sync(account["id"], "facebook", [
            {"external_id": "url:latest", "name": "Meta Business Suite", "url": "https://facebook.com/latest"},
            {"external_id": "url:ad_center", "name": "Quảng cáo", "url": "https://facebook.com/ad_center"},
        ])
        self.assertEqual(synced, [])
        result = self.targets.remove_invalid_discovery_targets(
            account["id"], "facebook", frozenset({"url:latest", "url:ad_center"})
        )
        self.assertEqual(result, {"removed": 0, "preserved": 0})
        self.assertEqual(self.targets.list(account_id=account["id"]), [])

    def test_referenced_invalid_target_is_hidden_but_history_is_preserved(self) -> None:
        account = self.accounts.create("Page admin", "facebook")
        target_id = "legacy-navigation-target"
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO publishing_targets(id,account_id,platform,target_type,external_id,name,url,enabled,access_status,created_at,updated_at) "
                "VALUES(?,?, 'facebook','page','url:latest','Meta Business Suite','https://facebook.com/latest',1,'accessible',datetime('now'),datetime('now'))",
                (target_id, account["id"]),
            )
        self.jobs.create("publish", {}, account["id"], None, target_id=target_id)
        result = self.targets.remove_invalid_discovery_targets(
            account["id"], "facebook", frozenset({"url:latest"})
        )
        self.assertEqual(result, {"removed": 0, "preserved": 1})
        self.assertEqual(self.targets.list(account_id=account["id"]), [])
        self.assertEqual(self.targets.get(target_id)["access_status"], "invalid_discovery")

    def test_target_groups_have_unique_members(self) -> None:
        account = self.accounts.create("Admin", "facebook")
        target = self.targets.sync(
            account["id"], "facebook", [{"external_id": "1", "name": "Page", "url": None}]
        )[0]
        group = self.targets.create_group("Main")
        updated = self.targets.set_group_members(group["id"], [target["id"], target["id"]])
        self.assertEqual(updated["target_ids"], [target["id"]])


if __name__ == "__main__":
    unittest.main()
