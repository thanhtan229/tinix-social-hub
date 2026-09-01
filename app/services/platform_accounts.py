from __future__ import annotations

import asyncio
from typing import Any

from app.automation.browser_session import BrowserSession
from app.db.repositories import AccountRepository, TargetRepository
from app.services.chrome import ChromeManager
from app.services.web_platform_publisher import ChromeWebPublisher


class PlatformAccountService:
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
            page=await session.page();await page.goto(publisher.spec.home_url,wait_until="domcontentloaded",timeout=30_000)
            status=await publisher.detect_login(page)
        await asyncio.to_thread(self.accounts.update_login_status,account_id,status)
        return {"account_id":account_id,"login_status":status}

    async def sync_targets(self, account_id: str) -> list[dict[str, Any]]:
        account=await asyncio.to_thread(self.accounts.get,account_id)
        if not account:raise KeyError(account_id)
        publisher=self.publishers.get(account["platform"],dry_run=True)
        session=await self._session(account)
        try:
            async with session:
                page=await session.page();await page.goto(publisher.spec.home_url,wait_until="domcontentloaded",timeout=30_000)
                status=await publisher.detect_login(page)
                await asyncio.to_thread(self.accounts.update_login_status,account_id,status)
                if status!="logged_in":raise RuntimeError("Account chưa đăng nhập hoặc đang có checkpoint.")
                discovered=await publisher.discover_targets(page)
            if not discovered:raise RuntimeError("Không tìm thấy profile/channel từ UI; hãy mở Chrome tới trang kênh rồi thử lại.")
            return await asyncio.to_thread(self.targets.sync,account_id,account["platform"],discovered)
        except Exception as exc:
            await asyncio.to_thread(self.targets.set_sync_error,account_id,str(exc));raise
