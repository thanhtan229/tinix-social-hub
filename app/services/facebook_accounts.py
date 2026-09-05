from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.automation.browser_session import BrowserSession
from app.automation.facebook.login_detector import FacebookLoginDetector, LoginStatus
from app.automation.facebook.page_objects import FacebookPagesPage
from app.db.repositories import AccountRepository, TargetRepository
from app.services.chrome import ChromeManager


logger = logging.getLogger(__name__)


class FacebookAccountService:
    INVALID_DISCOVERY_TARGETS = frozenset({"url:latest", "url:ad_center"})

    def __init__(self, accounts: AccountRepository, targets: TargetRepository, chrome: ChromeManager) -> None:
        self.accounts = accounts
        self.targets = targets
        self.chrome = chrome
        self.detector = FacebookLoginDetector()

    async def _ready_session(self, account: dict[str, Any]) -> BrowserSession:
        chrome = await asyncio.to_thread(self.chrome.status, account["id"])
        if not chrome:
            chrome = await asyncio.to_thread(self.chrome.open, account)
        for _ in range(24):
            chrome = await asyncio.to_thread(self.chrome.status, account["id"])
            if chrome and chrome["state"] == "ready":
                return BrowserSession(chrome["port"])
            if chrome and chrome["state"] == "unresponsive":
                raise RuntimeError("Chrome không phản hồi qua cổng điều khiển.")
            await asyncio.sleep(0.5)
        raise RuntimeError("Chrome khởi động quá thời gian chờ.")

    async def check_login(self, account_id: str) -> dict[str, Any]:
        account = await asyncio.to_thread(self.accounts.get, account_id)
        if not account:
            raise KeyError(account_id)
        if account["platform"] != "facebook":
            raise ValueError("LoginDetector hiện chỉ hỗ trợ Facebook.")
        session = await self._ready_session(account)
        async with session:
            page = await session.page()
            await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30_000)
            status = await self.detector.detect(page)
            checked_url = page.url
        await asyncio.to_thread(self.accounts.update_login_status, account_id, status.value)
        logger.info("Facebook login check: account=%s status=%s url=%s", account_id, status.value, checked_url)
        return {"account_id": account_id, "login_status": status.value}

    async def sync_pages(self, account_id: str) -> list[dict[str, Any]]:
        account = await asyncio.to_thread(self.accounts.get, account_id)
        if not account:
            raise KeyError(account_id)
        try:
            session = await self._ready_session(account)
            async with session:
                page = await session.page()
                await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30_000)
                status = await self.detector.detect(page)
                await asyncio.to_thread(self.accounts.update_login_status, account_id, status.value)
                if status == LoginStatus.CHECKPOINT:
                    raise RuntimeError("Facebook đang yêu cầu checkpoint; hãy xử lý trong Chrome rồi thử lại.")
                if status != LoginStatus.LOGGED_IN:
                    raise RuntimeError("Account Facebook chưa đăng nhập hoặc đã mất phiên.")
                discovered = await FacebookPagesPage(page).discover()
            payload = [
                {"external_id": item.external_id, "name": item.name, "url": item.url, "target_type": "page"}
                for item in discovered
            ]
            existing = await asyncio.to_thread(self.targets.list, account_id)
            false_positive_ids = {
                item["external_id"] for item in existing
                if FacebookPagesPage.is_false_positive(item.get("name") or "", item.get("url") or "")
            }
            await asyncio.to_thread(
                self.targets.remove_invalid_discovery_targets,
                account_id, "facebook", self.INVALID_DISCOVERY_TARGETS | false_positive_ids,
            )
            return await asyncio.to_thread(self.targets.sync, account_id, "facebook", payload)
        except Exception as exc:
            await asyncio.to_thread(self.targets.set_sync_error, account_id, str(exc))
            raise
        finally:
            await asyncio.to_thread(self.chrome.close, account_id)
