from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import Settings
from app.db.repositories import AccountRepository, JobRepository
from app.services.ai import OpenAICompatibleProvider
from app.services.publishers import PublisherRegistry


logger = logging.getLogger(__name__)


class LocalWorker:
    def __init__(
        self,
        settings: Settings,
        jobs: JobRepository,
        accounts: AccountRepository,
        ai: OpenAICompatibleProvider,
        publishers: PublisherRegistry,
    ) -> None:
        self.settings = settings
        self.jobs = jobs
        self.accounts = accounts
        self.ai = ai
        self.publishers = publishers
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._runner: asyncio.Task[None] | None = None
        self._active: set[asyncio.Task[None]] = set()
        self._accepting = True
        self.state = "stopped"

    async def start(self) -> None:
        recovered = await asyncio.to_thread(self.jobs.recover_interrupted)
        if recovered:
            logger.warning("Recovered %s interrupted jobs", recovered)
        self.state = "idle"
        self._runner = asyncio.create_task(self._run(), name="local-worker")

    def notify(self) -> None:
        self._wake.set()

    async def _run(self) -> None:
        while not self._stop.is_set():
            self._active = {task for task in self._active if not task.done()}
            slots = self.settings.max_concurrent_jobs - len(self._active) if self._accepting else 0
            claimed = 0
            for _ in range(max(0, slots)):
                job = await asyncio.to_thread(self.jobs.claim_next)
                if not job:
                    break
                task = asyncio.create_task(self._execute(job), name=f"job-{job['id']}")
                self._active.add(task)
                claimed += 1
            self.state = "working" if self._active else "idle"
            if claimed:
                await asyncio.sleep(0)
                continue
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.settings.job_poll_seconds)
            except asyncio.TimeoutError:
                pass

    async def _execute(self, job: dict[str, Any]) -> None:
        try:
            if await asyncio.to_thread(self.jobs.is_cancel_requested, job["id"]):
                await asyncio.to_thread(self.jobs.mark_cancelled, job["id"])
                return
            if job["kind"] == "ai_content":
                content = await self.ai.generate(job["payload"].get("prompt", ""), job["payload"].get("system", "Bạn là trợ lý nội dung mạng xã hội."))
                result = {"content": content}
            elif job["kind"] == "publish":
                account = await asyncio.to_thread(self.accounts.get, job["account_id"])
                if not account:
                    raise RuntimeError("Account không còn tồn tại.")
                result = await self.publishers.get(account["platform"]).publish(account, job["payload"])
            else:
                raise ValueError(f"Loại job không được hỗ trợ: {job['kind']}")
            if await asyncio.to_thread(self.jobs.is_cancel_requested, job["id"]):
                await asyncio.to_thread(self.jobs.mark_cancelled, job["id"])
            else:
                await asyncio.to_thread(self.jobs.complete, job["id"], result)
        except asyncio.CancelledError:
            if await asyncio.to_thread(self.jobs.is_cancel_requested, job["id"]):
                await asyncio.to_thread(self.jobs.mark_cancelled, job["id"])
            else:
                await asyncio.to_thread(self.jobs.fail, job["id"], "Job bị gián đoạn khi ứng dụng tắt.")
            raise
        except Exception as exc:
            logger.exception("Job %s failed", job["id"])
            await asyncio.to_thread(self.jobs.fail, job["id"], str(exc))
        finally:
            self.notify()

    async def stop(self, timeout: float = 20) -> None:
        self.state = "stopping"
        self._accepting = False
        self._stop.set()
        self._wake.set()
        if self._runner:
            await self._runner
        if self._active:
            done, pending = await asyncio.wait(self._active, timeout=timeout)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        self.state = "stopped"

    async def pause(self, timeout: float = 30) -> None:
        self._accepting = False
        self.state = "paused"
        self._wake.set()
        deadline = asyncio.get_running_loop().time() + timeout
        while self.active_count and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)
        if self.active_count:
            raise TimeoutError("Worker chưa thể tạm dừng vì job hiện tại chưa kết thúc.")

    def resume(self) -> None:
        self._accepting = True
        self.state = "idle"
        self._wake.set()

    @property
    def active_count(self) -> int:
        return sum(not task.done() for task in self._active)

    def cancel(self, job_id: str) -> None:
        for task in self._active:
            if task.get_name() == f"job-{job_id}" and not task.done():
                task.cancel()


class Scheduler:
    def __init__(self, settings: Settings, jobs: JobRepository, worker: LocalWorker) -> None:
        self.settings = settings
        self.jobs = jobs
        self.worker = worker
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.maintenance_lock = asyncio.Lock()
        self.state = "stopped"

    async def start(self) -> None:
        self.state = "running"
        self._task = asyncio.create_task(self._run(), name="scheduler")

    async def _run(self) -> None:
        while not self._stop.is_set():
            async with self.maintenance_lock:
                released = await asyncio.to_thread(self.jobs.release_due)
            if released:
                self.worker.notify()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.scheduler_seconds)
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
        self.state = "stopped"
