from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.secrets import SecretProtector
from app.db.database import Database
from app.db.repositories import JobRepository
from app.runtime import DurableQueue, LocalPathStorage, ManagedStorage, SecretStore, StateDatabase, runtime_report


class BrowserFixture:
    def open(self,account):return {}
    def status(self,account_id=None):return []
    def close(self,account_id):return True
    def close_all(self):return 0


class RuntimeContractTests(unittest.TestCase):
    def test_local_adapters_satisfy_contracts_and_report_blockers(self)->None:
        with tempfile.TemporaryDirectory() as value:
            root=Path(value);database=Database(root/"db.sqlite",root/"backups");database.initialize()
            queue=JobRepository(database);storage=LocalPathStorage(root/"media");secret=SecretProtector();browser=BrowserFixture()
            self.assertIsInstance(database,StateDatabase);self.assertIsInstance(queue,DurableQueue)
            self.assertIsInstance(storage,ManagedStorage);self.assertIsInstance(secret,SecretStore)
            report=runtime_report(database=database,queue=queue,storage=storage,secrets=secret,browser=browser)
            self.assertTrue(report["contract_ready"]);self.assertFalse(report["vps_deployable"])

    def test_managed_storage_rejects_escape(self)->None:
        with tempfile.TemporaryDirectory() as value:
            storage=LocalPathStorage(Path(value)/"media")
            with self.assertRaises(ValueError):storage.safe_path("../secret")


if __name__=="__main__":unittest.main()
