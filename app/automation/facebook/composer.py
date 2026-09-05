from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from app.automation.facebook import selectors


class FacebookComposerError(RuntimeError):
    pass


class FacebookComposerPage:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.dialog: Locator | None = None
        self.before_post_links: set[str] = set()
        self.submitted_caption = ""

    async def open(self) -> None:
        for attempt in range(2):
            trigger = await self._find_visible_create_trigger(timeout_ms=15_000)
            if trigger is None:
                switch = await self._visible_page_button(selectors.PAGE_SWITCH_NAME, timeout_ms=10_000)
                if switch is None:
                    raise FacebookComposerError("Không tìm thấy nút Tạo bài viết trên Page.")
                await switch.click(timeout=15_000)
                await self.page.wait_for_timeout(1_500)
                continue
            await trigger.click(timeout=15_000)
            self.dialog = self.page.locator(
                f"{selectors.COMPOSER_DIALOG}:has({selectors.COMPOSER_TEXTBOX})"
            ).last
            try:
                await self.dialog.wait_for(state="visible", timeout=8_000)
            except PlaywrightTimeoutError:
                if attempt == 0:
                    await self.page.wait_for_timeout(1_000)
                    continue
                raise FacebookComposerError("Đã bấm nút tạo bài viết nhưng Facebook không mở hộp soạn.")
            self.before_post_links = await self._post_links()
            return
        raise FacebookComposerError("Không thể mở hộp soạn bài sau khi chuyển sang Page.")

    async def _find_visible_create_trigger(self, timeout_ms: int = 0) -> Locator | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_ms / 1000
        while True:
            trigger: Locator | None = None
            for candidates in (
                self.page.get_by_role("button", name=selectors.CREATE_POST_NAME),
                self.page.get_by_text(selectors.CREATE_POST_NAME),
            ):
                for index in range(await candidates.count()):
                    candidate = candidates.nth(index)
                    if await candidate.is_visible():
                        trigger = candidate
                        break
                if trigger:
                    return trigger
            if loop.time() >= deadline:
                return None
            await self.page.wait_for_timeout(500)

    async def _visible_page_button(self, name: object, timeout_ms: int = 0) -> Locator | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_ms / 1000
        while True:
            buttons = self.page.get_by_role("button", name=name)
            for index in range(await buttons.count()):
                button = buttons.nth(index)
                if await button.is_visible():
                    return button
            if loop.time() >= deadline:
                return None
            await self.page.wait_for_timeout(500)

    async def fill_caption(self, caption: str) -> None:
        if not self.dialog:
            raise FacebookComposerError("Composer chưa được mở.")
        textbox = self.dialog.locator(selectors.COMPOSER_TEXTBOX).first
        await textbox.wait_for(state="visible", timeout=15_000)
        await textbox.fill(caption)
        self.submitted_caption = caption

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
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_ms / 1000
        advanced = False
        while loop.time() < deadline:
            post_button = await self._visible_dialog_button(selectors.POST_BUTTON_NAME)
            busy = await self._has_visible_upload_busy()
            if post_button is not None and not busy and await post_button.is_enabled():
                return post_button
            if not advanced:
                next_button = await self._visible_dialog_button(selectors.NEXT_BUTTON_NAME)
                if next_button is not None and await next_button.is_enabled():
                    await next_button.click(timeout=15_000)
                    advanced = True
            await self.page.wait_for_timeout(500)
        raise FacebookComposerError("Không tìm thấy nút Đăng sẵn sàng trong hộp soạn bài.")

    async def _visible_dialog_button(self, name: object) -> Locator | None:
        dialogs = self.page.locator(selectors.COMPOSER_DIALOG)
        for dialog_index in range(await dialogs.count() - 1, -1, -1):
            dialog = dialogs.nth(dialog_index)
            if not await dialog.is_visible():
                continue
            buttons = dialog.get_by_role("button", name=name)
            for button_index in range(await buttons.count() - 1, -1, -1):
                button = buttons.nth(button_index)
                if await button.is_visible():
                    return button
        return None

    async def _has_visible_upload_busy(self) -> bool:
        if not self.dialog:
            return False
        indicators = self.dialog.locator(selectors.UPLOAD_BUSY)
        for index in range(await indicators.count()):
            if await indicators.nth(index).is_visible():
                return True
        return False

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
        confirmed_at: float | None = None
        while loop.time() < deadline:
            post_url = await self._published_post_url()
            if post_url:
                return True, post_url

            success = self.page.get_by_text(selectors.SUCCESS_TEXT).first
            if await success.count() and await success.is_visible():
                confirmed_at = confirmed_at or loop.time()
            if self.submitted_caption:
                published_caption = self.page.get_by_text(self.submitted_caption, exact=True).last
                if await published_caption.count() and await published_caption.is_visible():
                    confirmed_at = confirmed_at or loop.time()
            # Facebook often renders the post first and attaches its permalink a
            # moment later. Keep polling briefly after visual confirmation.
            if confirmed_at is not None and loop.time() - confirmed_at >= 8:
                return True, None
            await self.page.wait_for_timeout(500)
        return (True, None) if confirmed_at is not None else (False, None)

    async def _published_post_url(self) -> str | None:
        candidates: set[str] = set()
        if self.submitted_caption:
            captions = self.page.get_by_text(self.submitted_caption, exact=True)
            for index in range(await captions.count() - 1, -1, -1):
                caption = captions.nth(index)
                if not await caption.is_visible():
                    continue
                # Scope link discovery to the exact feed item containing the
                # submitted caption. Looking for any ancestor with a boost link
                # can climb into the whole feed and select an older post.
                feed_item = caption.locator("xpath=ancestor::*[@aria-posinset][1]")
                article = caption.locator("xpath=ancestor::*[@role='article'][1]")
                scope = feed_item.first if await feed_item.count() else (
                    article.first if await article.count() else None
                )
                if scope is not None:
                    boost_links = await scope.locator("a[href*='boostpost']").evaluate_all(
                        "els => els.map(a => a.href || '')"
                    )
                    for href in boost_links:
                        if post_url := self._post_url_from_boost_href(href):
                            candidates.add(post_url)
                    candidates.update(await self._post_links(scope))
                break

        # With no caption, a newly added permalink is the only available signal.
        # Captioned posts must never use this page-wide fallback because lazy
        # rendering can make an older post link look newly added.
        if not self.submitted_caption:
            after = await self._post_links()
            candidates.update(after - self.before_post_links)
        return self._preferred_post_url(candidates)

    async def _post_links(self, root: Locator | None = None) -> set[str]:
        link_root = root if root is not None else self.page
        hrefs = await link_root.locator("a[href]").evaluate_all(
            "els => els.map(a => a.href || '')"
        )
        return {
            normalized
            for href in hrefs
            if (normalized := self._normalize_post_url(href)) is not None
        }

    @staticmethod
    def _normalize_post_url(href: str) -> str | None:
        if not href:
            return None
        parsed = urlsplit(href)
        if parsed.netloc.lower() not in {"facebook.com", "www.facebook.com", "m.facebook.com"}:
            return None
        if not any(part in parsed.path.lower() for part in selectors.POST_URL_PARTS):
            return None
        retained_query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key in {"fbid", "story_fbid", "id"}
        ]
        return urlunsplit(("https", "www.facebook.com", parsed.path, urlencode(retained_query), ""))

    @staticmethod
    def _preferred_post_url(candidates: set[str]) -> str | None:
        if not candidates:
            return None
        priority = ("/posts/", "/permalink.php", "/reel/", "/videos/", "/photo/")
        return min(
            candidates,
            key=lambda url: next(
                (index for index, part in enumerate(priority) if part in url.lower()),
                len(priority),
            ),
        )

    @staticmethod
    def _post_url_from_boost_href(href: str) -> str | None:
        """Build a stable post URL from Facebook's Page-management boost link."""
        parsed = urlsplit(href)
        if parsed.netloc.lower() not in {"facebook.com", "www.facebook.com", "m.facebook.com"}:
            return None
        if "boostpost" not in parsed.path.lower():
            return None
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        page_id, target_id = query.get("page_id"), query.get("target_id")
        if not (page_id and target_id and page_id.isdigit() and target_id.isdigit()):
            return None
        return f"https://www.facebook.com/{page_id}/posts/{target_id}"
