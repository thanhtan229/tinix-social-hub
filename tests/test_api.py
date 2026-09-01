from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.db.database import Database
from app.db.repositories import AccountRepository, JobRepository, TargetRepository


class WorkerStub:
    state = "idle"
    active_count = 0

    def notify(self) -> None:
        pass

    def cancel(self, job_id: str) -> None:
        pass


class ChromeStub:
    def status(self, account_id: str | None = None):
        return None if account_id else []

    def close(self, account_id: str) -> bool:
        return False

    def close_all(self) -> int:
        return 0


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        database = Database(root / "data" / "tinix_social.db", root / "backups")
        database.initialize()
        services = SimpleNamespace(
            database=database,
            accounts=AccountRepository(database),
            jobs=JobRepository(database),
            targets=TargetRepository(database),
            chrome=ChromeStub(),
            worker=WorkerStub(),
            scheduler=SimpleNamespace(state="running"),
            settings=SimpleNamespace(data_dir=root / "data", max_chrome=2),
            ai=SimpleNamespace(configured=False),
        )
        app = FastAPI()
        app.state.services = services
        app.include_router(router)
        self.services = services
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def test_account_crud_and_enable(self) -> None:
        created = self.client.post("/api/accounts", json={"name": "Main", "platform": "facebook"})
        self.assertEqual(created.status_code, 201)
        account_id = created.json()["id"]
        updated = self.client.put(
            f"/api/accounts/{account_id}", json={"name": "Renamed", "platform": "facebook"}
        )
        self.assertEqual(updated.json()["name"], "Renamed")
        disabled = self.client.patch(
            f"/api/accounts/{account_id}/enabled", json={"enabled": False, "reason": "manual"}
        )
        self.assertEqual(disabled.json()["enabled"], 0)
        deleted = self.client.delete(f"/api/accounts/{account_id}")
        self.assertEqual(deleted.status_code, 200)

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

    def test_health_uses_lightweight_ping(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["database"]["result"], "ok")


if __name__ == "__main__":
    unittest.main()

