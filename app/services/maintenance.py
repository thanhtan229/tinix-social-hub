from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from app.core.config import Settings


logger = logging.getLogger(__name__)


class MaintenanceService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.state = "stopped"
        self.last_result: dict[str, Any] | None = None

    @staticmethod
    def cleanup_files(root: Path, older_than_seconds: int) -> tuple[int, int]:
        root = root.resolve()
        cutoff = time.time() - older_than_seconds
        removed, failed = 0, 0
        if not root.is_dir():
            return removed, failed
        for path in root.rglob("*"):
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                resolved = path.resolve()
                if root not in resolved.parents or resolved.stat().st_mtime >= cutoff:
                    continue
                resolved.unlink()
                removed += 1
            except OSError:
                failed += 1
        return removed, failed

    def run_once(self) -> dict[str, Any]:
        screenshots, screenshot_failed = self.cleanup_files(
            self.settings.screenshot_dir, self.settings.screenshot_retention_days * 86400
        )
        temporary, temporary_failed = self.cleanup_files(
            self.settings.temp_dir, self.settings.temp_retention_hours * 3600
        )
        self.last_result = {
            "screenshots_removed": screenshots,
            "temporary_removed": temporary,
            "failed": screenshot_failed + temporary_failed,
            "ran_at": time.time(),
        }
        if screenshots or temporary or screenshot_failed or temporary_failed:
            logger.info("Maintenance completed: %s", self.last_result)
        return self.last_result

    async def start(self) -> None:
        self.state = "running"
        await asyncio.to_thread(self.run_once)
        self._task = asyncio.create_task(self._run(), name="maintenance")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.maintenance_seconds)
            except asyncio.TimeoutError:
                await asyncio.to_thread(self.run_once)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
        self.state = "stopped"

