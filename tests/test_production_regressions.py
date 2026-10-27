from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.local_boundary import install_local_boundary
from app.api.v1 import public_account
from app.cleanup import cleanup_previous_sessions, owns_backend, owns_chrome
from app.db.content_repositories import AIGenerationRepository
from app.db.database import Database
from app.db.repositories import AccountRepository, JobRepository
from app.services.image_generation import ImageGenerationService
from app.services.media import MediaValidationError, resolve_publish_media
from app.services.publishers import PublisherRegistry
from app.services.worker import LocalWorker, Scheduler
from app.services.worker_lock import WorkerLock


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        install_local_boundary(app, "127.0.0.1")
        self.calls = 0

        @app.post("/api/database/backups")
        async def backup():
            self.calls += 1
            return {"created": True}

        @app.get("/api/accounts/1/credentials")
        async def credentials():
            self.calls += 1
            return {"password": "fixture"}

        @app.get("/api/health")
        async def health():
            return {"status": "ok"}

        @app.post("/api/v1/example")
        async def v1():
            return {"ok": True}

        self.client = TestClient(app, base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)

    def test_cross_origin_form_never_reaches_mutation(self):
        response = self.client.post("/api/database/backups", data={"x": "1"}, headers={"Origin": "https://attacker.example"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.calls, 0)

    def test_foreign_host_and_null_origin_cannot_read_credentials(self):
        for headers in ({"Host": "attacker.example"}, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                headers["X-Tinix-Request"] = "1"
                self.assertEqual(self.client.get("/api/accounts/1/credentials", headers=headers).status_code, 403)
        self.assertEqual(self.calls, 0)

    def test_local_ui_header_required_and_allowed(self):
        self.assertEqual(self.client.post("/api/database/backups").status_code, 403)
        self.assertEqual(self.client.get("/api/accounts/1/credentials").status_code, 403)
        headers = {"X-Tinix-Request": "1", "Origin": "http://127.0.0.1:8765"}
        self.assertEqual(self.client.post("/api/database/backups", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/accounts/1/credentials", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_v1_automation_does_not_require_browser_header(self):
        self.assertEqual(self.client.post("/api/v1/example", headers={"Authorization": "Bearer fixture"}).status_code, 200)

    def test_read_serializer_hides_all_account_secrets(self):
        secrets = {key: "fixture" for key in ("password", "secret_2fa", "email_pass", "cookie", "recovery_codes")}
        account = public_account({"id": "a", **secrets})
        self.assertFalse(set(account) & set(secrets))
        self.assertTrue(account["has_recovery_codes"])


class RestoreTests(unittest.TestCase):
    def test_backup_before_publish_cannot_replay_after_restore_or_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "data" / "tinix_social.db", root / "backups")
            database.initialize()
            jobs = JobRepository(database)
            account = AccountRepository(database).create("Fixture", "facebook")
            real = jobs.create("publish", {}, account["id"], None, dry_run=False)
            dry = jobs.create("publish", {}, None, None, dry_run=True)
            backup = database.create_backup()
            jobs.claim_next()
            jobs.transition(real["id"], "checking_login")
            jobs.transition(real["id"], "publishing")
            jobs.transition(real["id"], "verifying", commit_reached=True)
            jobs.complete(real["id"], {"outcome": "published", "post_url": "https://www.facebook.com/fixture/posts/1"})
            database.restore_backup(backup.name)
            restored = jobs.get(real["id"])
            self.assertEqual(restored["status"], "unknown_result")
            self.assertEqual(restored["failure_code"], "restore_reconciliation_required")
            self.assertTrue(restored["commit_reached_at"])
            with self.assertRaises(ValueError):
                jobs.retry(real["id"])
            fresh = JobRepository(Database(database.path, database.backup_dir))
            fresh.recover_interrupted()
            fresh.release_due()
            self.assertEqual(fresh.claim_next()["id"], dry["id"])
            self.assertIsNone(fresh.claim_next())


class OwnershipTests(unittest.TestCase):
    def test_cleanup_uses_exact_project_and_profile(self):
        root = Path(tempfile.gettempdir()) / "tinix-ownership-fixture"
        backend = SimpleNamespace(name=lambda: "python.exe", cmdline=lambda: ["python", "-m", "app"], cwd=lambda: str(root))
        self.assertTrue(owns_backend(backend, root))
        backend.cwd = lambda: str(root) + "-other"
        self.assertFalse(owns_backend(backend, root))
        chrome = SimpleNamespace(name=lambda: "chrome.exe", cmdline=lambda: ["chrome", f"--user-data-dir={root / 'profiles' / 'one'}"])
        self.assertTrue(owns_chrome(chrome, root / "profiles"))
        chrome.cmdline = lambda: ["chrome", f"--user-data-dir={root / 'profiles-other'}"]
        self.assertFalse(owns_chrome(chrome, root / "profiles"))

    def test_cleanup_ignores_unrelated_listener_and_reused_session_pid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            (root / "data" / "chrome_sessions.json").write_text(json.dumps({"a": {"pid": 99991}}))
            proc = SimpleNamespace(pid=99991, name=lambda: "python.exe", cmdline=lambda: ["python", "unrelated.py"], cwd=lambda: directory)
            settings = SimpleNamespace(project_root=root, chrome_profile_dir=root / "profiles", data_dir=root / "data", port=8765)
            with patch("app.cleanup.get_settings", return_value=settings), patch("app.cleanup.psutil.Process", return_value=proc), patch("app.cleanup.psutil.process_iter", return_value=[proc]), patch("app.cleanup.psutil.net_connections") as ports, patch("app.cleanup.terminate_processes", return_value=0) as terminate:
                cleanup_previous_sessions()
                ports.assert_not_called()
                self.assertEqual([call.args[0] for call in terminate.call_args_list], [[], []])

    def test_kernel_lock_released_on_process_death(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data" / "test.db"
            code = "from pathlib import Path; from app.services.worker_lock import WorkerLock; import time; lock=WorkerLock(Path(__import__('sys').argv[1])); lock.acquire(); print('locked',flush=True); time.sleep(30)"
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            process = subprocess.Popen([sys._base_executable, "-c", code, str(path)], stdout=subprocess.PIPE, text=True, creationflags=flags)
            lock = WorkerLock(path)
            try:
                self.assertEqual(process.stdout.readline().strip(), "locked")
                with self.assertRaises(RuntimeError):
                    lock.acquire()
                process.terminate()
                process.wait(timeout=10)
                lock.acquire()
                lock.release()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
                process.stdout.close()
                lock.release()


class QueueRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.database = Database(root / "data" / "tinix_social.db", root / "backups")
        self.database.initialize()
        self.jobs = JobRepository(self.database)
        self.accounts = AccountRepository(self.database)
        self.settings = SimpleNamespace(max_concurrent_jobs=1, job_poll_seconds=.03, scheduler_seconds=.03)
        self.worker = LocalWorker(self.settings, self.jobs, self.accounts, None, PublisherRegistry())
        self.scheduler = Scheduler(self.settings, self.jobs, self.worker)

    async def asyncTearDown(self):
        await self.scheduler.stop()
        await self.worker.stop()
        self.temp.cleanup()

    async def test_second_worker_cannot_recover_active_first_worker(self):
        await self.worker.start()
        job = self.jobs.create("publish", {}, None, None)
        self.worker._accepting = False
        self.jobs.claim_next()
        second = LocalWorker(self.settings, self.jobs, self.accounts, None, PublisherRegistry())
        with self.assertRaises(RuntimeError):
            await second.start()
        self.assertEqual(self.jobs.get(job["id"])["status"], "opening_browser")
        self.assertEqual(self.jobs.get(job["id"])["attempts"], 1)
        await self.worker.stop()
        await second.start()
        await second.stop()

    async def test_worker_and_scheduler_survive_actual_sqlite_lock(self):
        normal_connect = self.database.connect
        def fast_connect():
            connection = normal_connect()
            connection.execute("PRAGMA busy_timeout=25")
            return connection
        await self.worker.start()
        await self.worker.pause()
        lock = self.database.connect()
        lock.execute("BEGIN IMMEDIATE")
        try:
            with patch.object(self.database, "connect", side_effect=fast_connect):
                self.worker.resume()
                await self.scheduler.start()
                await asyncio.sleep(.18)
                self.assertFalse(self.worker._runner.done())
                self.assertFalse(self.scheduler._task.done())
                self.assertIn(self.worker.state, {"retrying", "degraded"})
                self.assertEqual(self.scheduler.state, "degraded")
                lock.execute("ROLLBACK")
                await asyncio.sleep(.4)
                self.assertEqual(self.worker.state, "idle")
                self.assertEqual(self.scheduler.state, "running")
                self.assertFalse(self.worker._runner.done())
        finally:
            if lock.in_transaction:
                lock.execute("ROLLBACK")
            lock.close()

    async def test_nontransient_queue_error_visible_as_failed(self):
        with patch.object(self.jobs, "claim_next", side_effect=sqlite3.OperationalError("no such table: jobs")):
            await self.worker.start()
            await asyncio.sleep(.08)
            self.assertEqual(self.worker.state, "failed")
            self.assertTrue(self.worker._runner.done())


class MediaIntegrityTests(unittest.TestCase):
    def test_same_size_substitution_missing_hash_and_size_change_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "video.mp4"
            original = b"original"
            path.write_bytes(original)
            media = SimpleNamespace(resolve_existing=lambda _: path)
            snapshot = {"relative_path": "video.mp4", "sha256": hashlib.sha256(original).hexdigest(), "size_bytes": len(original)}
            self.assertEqual(resolve_publish_media(media, snapshot), path)
            for changed in (b"replaced", b"longer video bytes"):
                path.write_bytes(changed)
                with self.assertRaises(MediaValidationError):
                    resolve_publish_media(media, snapshot)
            path.write_bytes(original)
            with self.assertRaises(MediaValidationError):
                resolve_publish_media(media, {"relative_path": "video.mp4"})


class ImageRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_resumes_saved_run_without_creating_another(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "data" / "test.db", root / "backups")
            database.initialize()
            generations = AIGenerationRepository(database)
            job_id = generations.start("fixture", "auto", "image", {"provider": "fixture", "prompt": "fixture"}, None, None)
            entered = asyncio.Event()
            class Creator:
                creates = 0
                finished = False
                async def create_run(self, **kwargs):
                    self.creates += 1
                    return kwargs["run_id"]
                async def run_status(self, run_id):
                    entered.set()
                    return {"status": "completed" if self.finished else "running", "terminal": self.finished, "results": [{"kind": "image", "mediaUrl": "fixture"}]}
            creator = Creator()
            first = ImageGenerationService(generations, None, creator, 5)
            first._schedule(job_id, generations.get(job_id)["request"])
            await asyncio.wait_for(entered.wait(), 2)
            await first.close()
            self.assertEqual(generations.get(job_id)["response"]["external_run_id"], job_id)
            second = ImageGenerationService(generations, None, creator, 5)
            creator.finished = True
            async def import_results(*args):
                return [{"asset": {"id": "fixture"}}]
            second._import_media_creator_results = import_results
            await second.start()
            await asyncio.gather(*list(second._tasks.values()))
            self.assertEqual(creator.creates, 1)
            self.assertEqual(generations.get(job_id)["status"], "completed")
            await second.close()

    async def test_missing_run_id_or_unknown_run_finishes_with_actionable_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "data" / "test.db", root / "backups")
            database.initialize()
            generations = AIGenerationRepository(database)
            first = generations.start("fixture", "auto", "image", {"prompt": "fixture"}, None, None)
            second = generations.start("fixture", "auto", "image", {"prompt": "fixture"}, None, None)
            generations.update_image_job(second, status="running", response={"external_run_id": "missing"})
            class Creator:
                async def run_status(self, run_id):
                    return {"status": "unknown", "terminal": False}
            service = ImageGenerationService(generations, None, Creator(), 5)
            await service.start()
            await asyncio.gather(*list(service._tasks.values()))
            for job_id in (first, second):
                self.assertEqual(generations.get(job_id)["status"], "failed")
                self.assertEqual(generations.get(job_id)["error_code"], "image_generation_interrupted")
            await service.close()
