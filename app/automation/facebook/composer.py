from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import Locator, Page

from app.automation.facebook import selectors


class FacebookComposerError(RuntimeError):
    pass


class FacebookComposerPage:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.dialog: Locator | None = None
        self.before_post_links: set[str] = set()

    async def open(self) -> None:
        trigger = self.page.get_by_role("button", name=selectors.CREATE_POST_NAME).first
        if not await trigger.count():
            trigger = self.page.get_by_text(selectors.CREATE_POST_NAME).first
        if not await trigger.count():
            raise FacebookComposerError("Không tìm thấy nút Tạo bài viết trên Page.")
        await trigger.click(timeout=15_000)
        self.dialog = self.page.locator(selectors.COMPOSER_DIALOG).last
        await self.dialog.wait_for(state="visible", timeout=15_000)
        self.before_post_links = await self._post_links()

    async def fill_caption(self, caption: str) -> None:
        if not self.dialog:
            raise FacebookComposerError("Composer chưa được mở.")
        textbox = self.dialog.locator(selectors.COMPOSER_TEXTBOX).first
        await textbox.wait_for(state="visible", timeout=15_000)
        await textbox.fill(caption)

    async def upload_media(self, paths: list[Path]) -> None:
        if not paths:
            return
        if not self.dialog:
            raise FacebookComposerError("Composer chưa được mở.")
        file_input = self.dialog.locator(selectors.FILE_INPUT).first
        if not await file_input.count():
            file_input = self.page.locator(selectors.FILE_INPUT).last
        await file_input.set_input_files([str(path) for path in paths], timeout=20_000)

    async def wait_until_ready(self, timeout_ms: int = 180_000) -> Locator:
        if not self.dialog:
            raise FacebookComposerError("Composer chưa được mở.")
        post_button = self.dialog.get_by_role("button", name=selectors.POST_BUTTON_NAME).last
        await post_button.wait_for(state="visible", timeout=timeout_ms)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_ms / 1000
        while loop.time() < deadline:
            busy = await self.dialog.locator(selectors.UPLOAD_BUSY).count()
            if not busy and await post_button.is_enabled():
                return post_button
            await self.page.wait_for_timeout(500)
        raise FacebookComposerError("Media chưa xử lý xong hoặc nút Đăng chưa sẵn sàng.")

    async def submit(self, button: Locator) -> None:
        await button.click(timeout=15_000)

    async def verify_published(self, timeout_ms: int = 45_000) -> tuple[bool, str | None]:
        if self.dialog:
            try:
                await self.dialog.wait_for(state="hidden", timeout=timeout_ms)
            except Exception:
                return False, None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + min(20, timeout_ms / 1000)
        while loop.time() < deadline:
            success = self.page.get_by_text(selectors.SUCCESS_TEXT).first
            if await success.count() and await success.is_visible():
                return True, None
            after = await self._post_links()
            new_links = after - self.before_post_links
            if new_links:
                return True, sorted(new_links)[0]
            await self.page.wait_for_timeout(500)
        return False, None

    async def _post_links(self) -> set[str]:
        hrefs = await self.page.locator("a[href]").evaluate_all("els => els.map(a => a.href || '')")
        return {href for href in hrefs if any(part in href for part in selectors.POST_URL_PARTS)}
