from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from app.core.config import Settings


logger = logging.getLogger(__name__)


class MaintenanceService:
    PROFILE_CLEANUP_SETTING = "profile_auto_cleanup"
    DEFAULT_PROFILE_THRESHOLD_GB = 5
    DISK_FLOOR_GB = 10
    GIB = 1024 ** 3

    def __init__(
        self, settings: Settings, profile_transfer: Any | None = None,
        app_settings: Any | None = None, notifications: Any | None = None,
    ) -> None:
        self.settings = settings
        self.profile_transfer = profile_transfer
        self.app_settings = app_settings
        self.notifications = notifications
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.state = "stopped"
        self.last_result: dict[str, Any] | None = None

    def profile_cleanup_settings(self) -> dict[str, Any]:
        stored = self.app_settings.get(self.PROFILE_CLEANUP_SETTING, {}) if self.app_settings else {}
        if not isinstance(stored, dict):
            stored = {}
        enabled = bool(stored.get("enabled", True))
        try:
            threshold_gb = float(stored.get("threshold_gb", self.DEFAULT_PROFILE_THRESHOLD_GB))
        except (TypeError, ValueError):
            threshold_gb = self.DEFAULT_PROFILE_THRESHOLD_GB
        threshold_gb = max(0.5, min(100.0, threshold_gb))
        return {
            "enabled": enabled,
            "threshold_gb": threshold_gb,
            "disk_floor_gb": self.DISK_FLOOR_GB,
            "check_interval_seconds": self.settings.maintenance_seconds,
        }

    def update_profile_cleanup_settings(self, enabled: bool, threshold_gb: float) -> dict[str, Any]:
        threshold_gb = max(0.5, min(100.0, float(threshold_gb)))
        value = {"enabled": bool(enabled), "threshold_gb": threshold_gb}
        if self.app_settings:
            self.app_settings.set(self.PROFILE_CLEANUP_SETTING, value)
        return self.profile_cleanup_settings()

    def _notify(self, title: str, message: str, severity: str) -> None:
        if not self.notifications:
            return
        self.notifications.create(
            "profile_auto_cleanup", title, message, severity=severity,
            dedupe_key="profile-auto-cleanup",
        )

    def auto_cleanup_profiles(self) -> dict[str, Any]:
        policy = self.profile_cleanup_settings()
        result: dict[str, Any] = {
            "status": "disabled" if not policy["enabled"] else "not_needed",
            "trigger": None,
            "threshold_bytes": int(policy["threshold_gb"] * self.GIB),
            "disk_floor_bytes": int(policy["disk_floor_gb"] * self.GIB),
        }
        if not policy["enabled"] or not self.profile_transfer:
            if not self.profile_transfer:
                result["status"] = "unavailable"
            return result

        preview = self.profile_transfer.profile_cleanup_preview()
        disk = shutil.disk_usage(self.settings.chrome_profile_dir)
        result.update({
            "profiles_scanned": preview["profiles_scanned"],
            "bytes_removable": preview["bytes_removable"],
            "disk_free_bytes": disk.free,
            "chrome_running": preview["chrome_running"],
        })
        threshold_reached = preview["bytes_removable"] >= result["threshold_bytes"]
        disk_low = disk.free < result["disk_floor_bytes"]
        if not threshold_reached and not disk_low:
            return result
        result["trigger"] = "disk_low" if disk_low else "size_threshold"
        if preview["bytes_removable"] <= 0:
            result["status"] = "nothing_to_clean"
            return result
        if preview["chrome_running"]:
            result["status"] = "deferred_chrome_running"
            self._notify(
                "Đang chờ dọn Chrome profile",
                f"Có thể giải phóng {preview['bytes_removable'] / self.GIB:.1f} GB nhưng Chrome đang mở. App sẽ thử lại sau.",
                "warning",
            )
            return result

        cleaned = self.profile_transfer.cleanup_profiles()
        result.update(cleaned)
        result["status"] = "cleaned"
        self._notify(
            "Đã tự động dọn Chrome profile",
            f"Đã giải phóng {cleaned['bytes_freed'] / self.GIB:.1f} GB từ {cleaned['profiles_cleaned']} profile.",
            "info",
        )
        return result

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
        try:
            profile_cleanup = self.auto_cleanup_profiles()
        except Exception as exc:
            logger.exception("Automatic profile cleanup check failed")
            profile_cleanup = {"status": "error", "error": str(exc)}
        self.last_result = {
            "screenshots_removed": screenshots,
            "temporary_removed": temporary,
            "failed": screenshot_failed + temporary_failed,
            "profile_cleanup": profile_cleanup,
            "ran_at": time.time(),
        }
        if (
            screenshots or temporary or screenshot_failed or temporary_failed
            or profile_cleanup.get("status") not in {"disabled", "not_needed", "unavailable"}
        ):
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
