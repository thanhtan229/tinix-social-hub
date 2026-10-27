from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import contextmanager
from typing import Any

from app.core.config import Settings
from app.db.repositories import AccountRepository, JobRepository
from app.domain.jobs import JobStatus
from app.services.ai import OpenAICompatibleProvider
from app.services.publishers import PublishContext, PublishOutcome, PublisherRegistry
from app.services.publisher_router import PublisherRouter
from app.services.worker_lock import WorkerLock


logger = logging.getLogger(__name__)


def is_database_busy(exc: sqlite3.OperationalError) -> bool:
    code = getattr(exc, "sqlite_errorcode", None)
    return (code is not None and code & 255 in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}) or str(exc).lower() in {
        "database is locked", "database table is locked", "database schema is locked",
    }


async def wait_for_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


class LocalWorker:
    def __init__(
        self,
        settings: Settings,
        jobs: JobRepository,
        accounts: AccountRepository,
        ai: OpenAICompatibleProvider,
        publishers: PublisherRegistry,
        publisher_router: PublisherRouter | None = None,
    ) -> None:
        self.settings = settings
        self.jobs = jobs
        self.accounts = accounts
        self.ai = ai
        self.publishers = publishers
        self.publisher_router = publisher_router or PublisherRouter(publishers)
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._runner: asyncio.Task[None] | None = None
        self._active: set[asyncio.Task[None]] = set()
        self._accepting = True
        self._claim_lock = asyncio.Lock()
        self.state = "stopped"
        self._ownership = WorkerLock(jobs.db.path)

    async def start(self) -> None:
        if self._runner and not self._runner.done():
            return
        self._ownership.acquire()
        try:
            recovered = await asyncio.to_thread(self.jobs.recover_interrupted)
        except BaseException:
            self._ownership.release()
            raise
        self._stop.clear()
        self._accepting = True
        if recovered:
            logger.warning("Recovered %s interrupted jobs", recovered)
        self.state = "idle"
        self._runner = asyncio.create_task(self._run(), name="local-worker")

    def notify(self) -> None:
        self._wake.set()

    @contextmanager
    def exclusive_database(self):
        if self._ownership.held:
            yield
            return
        ownership = WorkerLock(self.jobs.db.path)
        ownership.acquire()
        try:
            yield
        finally:
            ownership.release()

    async def _run(self) -> None:
        retry_delay = 0.25
        while not self._stop.is_set():
            self._active = {task for task in self._active if not task.done()}
            slots = self.settings.max_concurrent_jobs - len(self._active) if self._accepting else 0
            claimed = 0
            for _ in range(max(0, slots)):
                try:
                    async with self._claim_lock:
                        if not self._accepting or self._stop.is_set():
                            break
                        job = await asyncio.to_thread(self.jobs.claim_next)
                        if job:
                            task = asyncio.create_task(self._execute(job), name=f"job-{job['id']}")
                            self._active.add(task)
                except sqlite3.OperationalError as exc:
                    if not is_database_busy(exc):
                        self.state = "failed"
                        logger.exception("Worker database failure")
                        return
                    self.state = "degraded"
                    logger.warning("Worker waiting for SQLite writer: %s", exc)
                    await wait_for_stop(self._stop, retry_delay)
                    retry_delay = min(retry_delay * 2, 5)
                    break
                except Exception:
                    self.state = "failed"
                    logger.exception("Worker claim failed")
                    return
                retry_delay = 0.25
                if not job:
                    break
                claimed += 1
            if self.state == "degraded":
                self.state = "retrying"
                continue
            self.state = "working" if self._active else ("idle" if self._accepting else "paused")
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
                if not account["enabled"]:
                    await asyncio.to_thread(
                        self.jobs.transition, job["id"], JobStatus.PERMANENT_FAILURE,
                        event_type="account_disabled", error="Account đang bị tắt.", failure_code="account_disabled",
                    )
                    return
                detail = await asyncio.to_thread(self.jobs.detail, job["id"])
                release = (detail or {}).get("release") or {}
                route = self.publisher_router.resolve(
                    account,
                    content_format=str(job["payload"].get("content_format") or "post"),
                    dry_run=bool(job["dry_run"]),
                    preference=job["payload"].get("routing_preference") or release.get("requested_routing_policy"),
                    frozen_transport=release.get("publication_transport"),
                    frozen_connection_id=release.get("connection_id"),
                    frozen_connection_scopes_hash=release.get("connection_scopes_hash"),
                    target_external_id=job["payload"].get("target_external_id"),
                    target_id=job["payload"].get("target_id"),
                    frozen_provider_target_binding_id=job["payload"].get("provider_target_binding_id"),
                    frozen_provider_target_external_id=job["payload"].get("provider_target_external_id"),
                )
                await asyncio.to_thread(
                    self.jobs.record_route, job["id"], transport=route.transport, reason=route.reason,
                    provider=route.provider, provider_version=getattr(route.publisher, "provider_version", None),
                    connection_id=route.connection_id,
                )
                await asyncio.to_thread(
                    self.jobs.transition, job["id"], JobStatus.CHECKING_LOGIN,
                    event_type="publisher_started", metadata={"transport": route.transport, "routing_reason": route.reason},
                )
                publisher = route.publisher
                if publisher is None or route.reason == "frozen_connection_unavailable":
                    await asyncio.to_thread(
                        self.jobs.transition, job["id"], JobStatus.LOGIN_REQUIRED,
                        event_type="frozen_connection_unavailable",
                        error="Kết nối hoặc quyền API đã thay đổi kể từ lúc duyệt dry-run; hãy kết nối lại và chạy dry-run mới.",
                        failure_code="frozen_connection_unavailable",
                    )
                    return

                async def publisher_transition(target: str, event_type: str, commit_reached: bool = False) -> None:
                    await asyncio.to_thread(
                        self.jobs.transition, job["id"], target,
                        event_type=event_type, commit_reached=commit_reached,
                    )

                async def record_provider_request(request_id: str, commit_possible: bool = False) -> None:
                    await asyncio.to_thread(
                        self.jobs.record_provider_request, job["id"], request_id,
                        commit_possible=commit_possible,
                    )

                provider_request = None
                get_provider_request = getattr(self.jobs, "latest_provider_request", None)
                if get_provider_request:
                    provider_request = await asyncio.to_thread(get_provider_request, job["id"])
                publisher_job = dict(job)
                if provider_request:
                    publisher_job["provider_request_id"] = provider_request.get("provider_request_id")
                    publisher_job["provider_request_commit_possible"] = bool(provider_request.get("commit_possible"))
                publish_result = await publisher.publish(
                    PublishContext(
                        job=publisher_job,
                        account=account,
                        payload=job["payload"],
                        is_cancelled=lambda: asyncio.to_thread(self.jobs.is_cancel_requested, job["id"]),
                        transition=publisher_transition,
                        record_provider_request=record_provider_request,
                        connection_id=route.connection_id,
                    )
                )
                result = {
                    "outcome": publish_result.outcome.value,
                    "message": publish_result.message,
                    "post_url": publish_result.post_url,
                    "metadata": {**publish_result.metadata, "transport": route.transport, "provider": route.provider},
                }
                if publish_result.outcome == PublishOutcome.DRY_RUN_READY:
                    current = await asyncio.to_thread(self.jobs.get, job["id"])
                    if current["status"] == JobStatus.CHECKING_LOGIN.value:
                        await asyncio.to_thread(self.jobs.transition, job["id"], JobStatus.PUBLISHING, event_type="dry_run_payload_ready")
                    await asyncio.to_thread(self.jobs.dry_run_ready, job["id"], result)
                    return
                if publish_result.outcome == PublishOutcome.UNSUPPORTED:
                    await asyncio.to_thread(
                        self.jobs.transition, job["id"], JobStatus.PERMANENT_FAILURE,
                        event_type="unsupported", error=publish_result.message, failure_code="unsupported",
                    )
                    return
                if publish_result.outcome == PublishOutcome.LOGIN_REQUIRED:
                    await asyncio.to_thread(self.jobs.transition, job["id"], JobStatus.LOGIN_REQUIRED, event_type="login_required")
                    return
                if publish_result.outcome == PublishOutcome.CHECKPOINT:
                    await asyncio.to_thread(self.jobs.transition, job["id"], JobStatus.CHECKPOINT, event_type="checkpoint")
                    return
                if publish_result.outcome == PublishOutcome.UNKNOWN_RESULT:
                    await asyncio.to_thread(
                        self.jobs.transition, job["id"], JobStatus.UNKNOWN_RESULT,
                        event_type="unknown_result", error=publish_result.message,
                        result=result,
                    )
                    return
                current = await asyncio.to_thread(self.jobs.get, job["id"])
                if current["status"] == JobStatus.CHECKING_LOGIN.value:
                    await asyncio.to_thread(self.jobs.transition, job["id"], JobStatus.PUBLISHING, event_type="payload_ready")
                    await asyncio.to_thread(self.jobs.transition, job["id"], JobStatus.VERIFYING, event_type="publish_submitted", commit_reached=True)
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
        self._ownership.release()

    async def pause(self, timeout: float = 30) -> None:
        self._accepting = False
        self.state = "paused"
        self._wake.set()
        async with self._claim_lock:
            pass
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
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self.state = "running"
        self._task = asyncio.create_task(self._run(), name="scheduler")

    async def _run(self) -> None:
        retry_delay = 0.25
        while not self._stop.is_set():
            try:
                async with self.maintenance_lock:
                    released = await asyncio.to_thread(self.jobs.release_due)
            except sqlite3.OperationalError as exc:
                if not is_database_busy(exc):
                    self.state = "failed"
                    logger.exception("Scheduler database failure")
                    return
                self.state = "degraded"
                logger.warning("Scheduler waiting for SQLite writer: %s", exc)
                await wait_for_stop(self._stop, retry_delay)
                retry_delay = min(retry_delay * 2, 5)
                continue
            except Exception:
                self.state = "failed"
                logger.exception("Scheduler release failed")
                return
            retry_delay = 0.25
            self.state = "running"
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
