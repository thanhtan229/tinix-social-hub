from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db.analytics_repositories import AnalyticsRepository
from app.db.repositories import AppSettingsRepository
from app.services.api_analytics import YouTubeAPIAnalyticsCollector


logger = logging.getLogger(__name__)


class AnalyticsRefreshScheduler:
    """Opt-in, bounded refresh for providers with read-only collectors."""

    SETTING_KEY = "analytics.refresh"
    LAST_RUN_KEY = "analytics.refresh.last_run"
    DEFAULTS = {
        "enabled": False,
        "meta_enabled": False,
        "interval_hours": 24,
        "days": 30,
        "posts_per_run": 10,
        "channels_per_run": 10,
    }
    INTERVALS = {6, 12, 24, 48}
    WINDOWS = {7, 30, 90}

    def __init__(
        self, settings: AppSettingsRepository, analytics: AnalyticsRepository,
        collector: YouTubeAPIAnalyticsCollector,
        meta_collector: Any = None,
    ) -> None:
        self.settings = settings
        self.analytics = analytics
        self.collector = collector
        self.meta_collector = meta_collector
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def configuration(self) -> dict[str, Any]:
        saved = self.settings.get(self.SETTING_KEY, {})
        return {**self.DEFAULTS, **(saved if isinstance(saved, dict) else {})}

    def status(self) -> dict[str, Any]:
        config = self.configuration()
        last_run = self.settings.get(self.LAST_RUN_KEY)
        enabled = config.get("enabled") or config.get("meta_enabled")
        next_run = None
        if enabled:
            finished = (last_run or {}).get("finished_at") if isinstance(last_run, dict) else None
            try:
                candidate = datetime.fromisoformat(finished) + timedelta(hours=int(config["interval_hours"])) if finished else None
                if candidate and candidate.tzinfo is None:
                    candidate = candidate.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                candidate = None
            now = datetime.now(timezone.utc)
            if candidate is None or candidate <= now:
                candidate = now + timedelta(hours=int(config["interval_hours"]))
            next_run = candidate.isoformat()
        return {**config, "last_run": last_run, "next_run_at": next_run}

    def configure(self, values: dict[str, Any]) -> dict[str, Any]:
        merged = {**self.configuration(), **values}
        if not isinstance(merged["enabled"], bool):
            raise ValueError("Trạng thái tự động cập nhật phải là bật hoặc tắt.")
        if not isinstance(merged.get("meta_enabled", False), bool):
            raise ValueError("Trạng thái tự động cập nhật Meta phải là bật hoặc tắt.")
        if merged["interval_hours"] not in self.INTERVALS:
            raise ValueError("Chu kỳ cập nhật cần là 6, 12, 24 hoặc 48 giờ.")
        if merged["days"] not in self.WINDOWS:
            raise ValueError("Khoảng lịch sử cần là 7, 30 hoặc 90 ngày.")
        for key in ("posts_per_run", "channels_per_run"):
            if not isinstance(merged[key], int) or isinstance(merged[key], bool) or not 1 <= merged[key] <= 50:
                raise ValueError("Giới hạn mỗi lần chạy cần từ 1 đến 50.")
        self.settings.set(self.SETTING_KEY, merged)
        self.notify()
        return self.status()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="analytics-refresh-scheduler")

    def notify(self) -> None:
        self._wake.set()

    async def _run_once(self, config: dict[str, Any]) -> dict[str, Any]:
        started = datetime.now(timezone.utc).isoformat()
        result: dict[str, Any] = {
            "started_at": started, "finished_at": None,
            "posts_attempted": 0, "channels_attempted": 0,
            "succeeded": 0, "no_data": 0, "needs_action": 0, "failed": 0,
        }
        cooldown = int(config["interval_hours"])
        providers = []
        if config.get("enabled") and self.collector:
            providers.append(("youtube", "api_youtube_data_v3", self.collector))
        if config.get("meta_enabled") and self.meta_collector:
            providers.append(("facebook", "api_meta_graph", self.meta_collector))
        for platform, source, collector in providers:
            await self._collect_provider(result, platform, source, collector, cooldown, config)
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(self.settings.set, self.LAST_RUN_KEY, result)
        return result

    async def _collect_provider(
        self, result: dict[str, Any], platform: str, source: str,
        collector: Any, cooldown: int, config: dict[str, Any],
    ) -> None:
        post_ids = await asyncio.to_thread(
            self.analytics.due_release_ids, cooldown, int(config["posts_per_run"]), platform, source,
        )
        for release_id in post_ids:
            try:
                item = await collector.collect_release(release_id, int(config["days"]))
                result["posts_attempted"] += 1
                self._count_status(result, item.get("status"))
                if item.get("trend"):
                    self._count_status(result, item["trend"].get("status"))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Automatic %s post analytics collection failed for release %s", platform, release_id)
                result["posts_attempted"] += 1
                result["failed"] += 1
        target_ids = await asyncio.to_thread(
            self.analytics.due_channel_target_ids, cooldown, int(config["channels_per_run"]), platform, source,
        )
        for target_id in target_ids:
            try:
                item = await collector.collect_channel(target_id, int(config["days"]))
                result["channels_attempted"] += 1
                self._count_status(result, item.get("status"))
                if item.get("trend"):
                    self._count_status(result, item["trend"].get("status"))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Automatic %s channel analytics collection failed for target %s", platform, target_id)
                result["channels_attempted"] += 1
                result["failed"] += 1

    @staticmethod
    def _count_status(result: dict[str, Any], status: Any) -> None:
        if status in {"succeeded", "no_data"}:
            result[str(status)] += 1
        elif status in {"needs_scope", "needs_connection", "needs_reconciliation", "unsupported", "rate_limited"}:
            result["needs_action"] += 1
        else:
            result["failed"] += 1

    async def _run(self) -> None:
        while not self._stop.is_set():
            config = await asyncio.to_thread(self.configuration)
            if config.get("enabled") or config.get("meta_enabled"):
                try:
                    await self._run_once(config)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Automatic analytics refresh cycle failed")
            timeout = int(config.get("interval_hours", 24)) * 3600 if config.get("enabled") or config.get("meta_enabled") else 300
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task:
            await self._task
            self._task = None
