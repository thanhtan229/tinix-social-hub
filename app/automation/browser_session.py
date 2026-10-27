from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright


class BrowserConnectionError(RuntimeError):
    pass


@dataclass(slots=True)
class BrowserSession:
    port: int
    playwright: Playwright | None = None
    browser: Browser | None = None
    context: BrowserContext | None = None

    async def connect(self) -> "BrowserSession":
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{self.port}", timeout=15_000
            )
            self.context = self.browser.contexts[0] if self.browser.contexts else await self.browser.new_context()
            return self
        except Exception as exc:
            await self.disconnect()
            raise BrowserConnectionError(f"Không thể kết nối Chrome qua CDP port {self.port}.") from exc

    async def page(self) -> Page:
        if not self.context:
            raise BrowserConnectionError("BrowserSession chưa kết nối.")
        return self.context.pages[0] if self.context.pages else await self.context.new_page()

    async def new_page(self) -> Page:
        if not self.context:
            raise BrowserConnectionError("BrowserSession chưa kết nối.")
        return await self.context.new_page()

    async def disconnect(self) -> None:
        # Do not call browser.close(): Chrome lifecycle belongs to ChromeManager.
        if self.playwright:
            await self.playwright.stop()
        self.playwright = None
        self.browser = None
        self.context = None

    async def __aenter__(self) -> "BrowserSession":
        return await self.connect()

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()
