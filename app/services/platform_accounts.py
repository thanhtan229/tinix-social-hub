from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlparse

from app.automation.browser_session import BrowserSession
from app.db.repositories import AccountRepository, TargetRepository
from app.services.chrome import ChromeManager
from app.services.web_platform_publisher import ChromeWebPublisher


class PlatformAccountService:
    INVALID_TARGET_IDS = {
        "facebook": frozenset({"url:latest", "url:ad_center"}),
    }
    TARGET_HOSTS = {
        "facebook": ("facebook.com",),
        "instagram": ("instagram.com",),
        "tiktok": ("tiktok.com",),
        "youtube": ("youtube.com", "youtu.be"),
        "x": ("x.com", "twitter.com"),
    }

    def __init__(self, accounts: AccountRepository, targets: TargetRepository, chrome: ChromeManager, publishers: Any) -> None:
        self.accounts, self.targets, self.chrome, self.publishers = accounts, targets, chrome, publishers

    async def _session(self, account: dict[str, Any]) -> BrowserSession:
        publisher = self.publishers.get(account["platform"], dry_run=True)
        if not isinstance(publisher, ChromeWebPublisher):
            raise ValueError("Nền tảng này dùng account service chuyên biệt.")
        chrome = await publisher.chrome_ready(account)
        return BrowserSession(chrome["port"])

    async def check_login(self, account_id: str) -> dict[str, Any]:
        account=await asyncio.to_thread(self.accounts.get,account_id)
        if not account:raise KeyError(account_id)
        publisher=self.publishers.get(account["platform"],dry_run=True)
        session=await self._session(account)
        async with session:
            page=await session.page()
            current_host=urlparse(page.url).netloc.lower()
            if not any(current_host.endswith(host) for host in publisher.spec.allowed_hosts):
                await page.goto(publisher.spec.home_url,wait_until="domcontentloaded",timeout=30_000)
            status=await publisher.detect_login(page)
        await asyncio.to_thread(self.accounts.update_login_status,account_id,status)
        return {"account_id":account_id,"login_status":status}

    async def sync_targets(self, account_id: str) -> list[dict[str, Any]]:
        account=await asyncio.to_thread(self.accounts.get,account_id)
        if not account:raise KeyError(account_id)
        publisher=self.publishers.get(account["platform"],dry_run=True)
        try:
            session=await self._session(account)
            async with session:
                page=await session.page();await page.goto(publisher.spec.home_url,wait_until="domcontentloaded",timeout=30_000)
                status=await publisher.detect_login(page)
                await asyncio.to_thread(self.accounts.update_login_status,account_id,status)
                if status!="logged_in":raise RuntimeError("Account chưa đăng nhập hoặc đang có checkpoint.")
                discovered=await publisher.discover_targets(page)
            if not discovered:raise RuntimeError("Không tìm thấy profile/channel từ UI; hãy mở Chrome tới trang kênh rồi thử lại.")
            existing = await asyncio.to_thread(self.targets.list, account_id)
            synced = await asyncio.to_thread(self.targets.sync,account_id,account["platform"],discovered)
            invalid_ids = self.INVALID_TARGET_IDS.get(account["platform"], frozenset())
            if invalid_ids:
                await asyncio.to_thread(
                    self.targets.remove_invalid_discovery_targets,
                    account_id, account["platform"], invalid_ids,
                )
                synced = await asyncio.to_thread(self.targets.list, account_id)
            if account["platform"] == "youtube":
                stale_ids = self._stale_youtube_external_ids(existing, discovered)
                if stale_ids:
                    await asyncio.to_thread(
                        self.targets.remove_invalid_discovery_targets,
                        account_id,
                        "youtube",
                        stale_ids,
                        "Liên kết menu YouTube Studio, không phải kênh",
                    )
                    synced = await asyncio.to_thread(self.targets.list, account_id)
            return synced
        except Exception as exc:
            await asyncio.to_thread(self.targets.set_sync_error,account_id,str(exc));raise
        finally:
            await asyncio.to_thread(self.chrome.close,account_id)

    @staticmethod
    def _youtube_channel_id(target: dict[str, Any]) -> str | None:
        external_id = str(target.get("external_id") or "")
        if external_id.startswith("UC") and len(external_id) == 24:
            return external_id
        parsed = urlparse(str(target.get("url") or ""))
        parts = parsed.path.strip("/").split("/")
        return parts[1] if len(parts) >= 2 and parts[0] == "channel" else None

    @classmethod
    def _stale_youtube_external_ids(
        cls, existing: list[dict[str, Any]], discovered: list[dict[str, Any]],
    ) -> set[str]:
        discovered_ids = {str(item["external_id"]) for item in discovered}
        return {
            str(item["external_id"])
            for item in existing
            if cls._youtube_channel_id(item) in discovered_ids
            and str(item.get("external_id") or "") not in discovered_ids
        }

    @classmethod
    def _target_url(cls, platform: str, value: str | None) -> str:
        parsed = urlparse(str(value or "").strip())
        host = (parsed.hostname or "").lower()
        allowed = cls.TARGET_HOSTS.get(platform, ())
        if parsed.scheme != "https" or not any(host == item or host.endswith(f".{item}") for item in allowed):
            raise ValueError("URL Page/Kênh không hợp lệ hoặc không khớp nền tảng.")
        return parsed.geturl()

    async def open_target(self, target_id: str) -> dict[str, Any]:
        target = await asyncio.to_thread(self.targets.get, target_id)
        if not target:
            raise KeyError(target_id)
        if target.get("external_id") in self.INVALID_TARGET_IDS.get(target["platform"], frozenset()):
            raise ValueError("Đây là liên kết điều hướng hệ thống, không phải Page/Kênh hợp lệ.")
        account = await asyncio.to_thread(self.accounts.get, target["account_id"])
        if not account or account["platform"] != target["platform"]:
            raise ValueError("Page/Kênh không thuộc account hợp lệ.")
        target_url = self._target_url(target["platform"], target.get("url"))
        chrome = await asyncio.to_thread(self.chrome.open, account)
        for _attempt in range(24):
            current = await asyncio.to_thread(self.chrome.status, account["id"])
            if current and current.get("state") == "ready":
                chrome = current
                break
            if current and current.get("state") in {"stopped", "unresponsive"}:
                raise RuntimeError("Chrome của account không sẵn sàng.")
            await asyncio.sleep(.25)
        else:
            raise RuntimeError("Chrome khởi động quá thời gian chờ.")
        try:
            async with BrowserSession(chrome["port"]) as session:
                page = await session.page()
                await page.goto(target_url, wait_until="domcontentloaded", timeout=30_000)
                await page.bring_to_front()
        except Exception as exc:
            raise RuntimeError("Đã mở Chrome nhưng không thể điều hướng tới Page/Kênh.") from exc
        return {
            "opened": True, "account_id": account["id"], "target_id": target_id,
            "target_url": target_url, "chrome_state": chrome.get("state"),
        }
