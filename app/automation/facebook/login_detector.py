from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from playwright.async_api import Page

from app.automation.facebook import selectors


class LoginStatus(StrEnum):
    LOGGED_IN = "logged_in"
    LOGGED_OUT = "logged_out"
    SESSION_LOST = "session_lost"
    CHECKPOINT = "checkpoint"
    UNKNOWN = "unknown"


class FacebookLoginDetector:
    CHECKPOINT_URL_PARTS = ("/checkpoint", "/challenge", "/two_step_verification", "/recover")
    CHECKPOINT_FORM = re.compile(
        r"<form\b[^>]*\baction\s*=\s*['\"][^'\"]*(?:checkpoint|challenge|two_step_verification|recover)[^'\"]*['\"]",
        re.IGNORECASE,
    )
    CHECKPOINT_INPUT = re.compile(r"<input\b[^>]*\bname\s*=\s*['\"]approvals_code['\"]", re.IGNORECASE)
    CHECKPOINT_PAGELET = re.compile(r"\bdata-pagelet\s*=\s*['\"][^'\"]*checkpoint[^'\"]*['\"]", re.IGNORECASE)

    @staticmethod
    async def _any_visible(locator: Any, limit: int = 10) -> bool:
        for index in range(min(await locator.count(), limit)):
            if await locator.nth(index).is_visible():
                return True
        return False

    @classmethod
    def detect_from_html(cls, url: str, html: str) -> LoginStatus:
        lowered_url = url.lower()
        lowered = html.lower()
        if any(part in lowered_url for part in cls.CHECKPOINT_URL_PARTS):
            return LoginStatus.CHECKPOINT
        if cls.CHECKPOINT_FORM.search(html) or cls.CHECKPOINT_INPUT.search(html) or cls.CHECKPOINT_PAGELET.search(html):
            return LoginStatus.CHECKPOINT
        has_email = "name=\"email\"" in lowered or "name='email'" in lowered or "id=\"email\"" in lowered
        has_password = "name=\"pass\"" in lowered or "name='pass'" in lowered or "id=\"pass\"" in lowered
        if has_email and has_password:
            return LoginStatus.SESSION_LOST if "facebook.com" in lowered_url and "/login" not in lowered_url else LoginStatus.LOGGED_OUT
        account_signals = ("aria-label=\"account\"", "aria-label=\"tài khoản\"", "data-pagelet=\"bluebar\"")
        if any(signal in lowered for signal in account_signals):
            return LoginStatus.LOGGED_IN
        return LoginStatus.UNKNOWN

    async def detect(self, page: Page) -> LoginStatus:
        url = page.url
        if any(part in url.lower() for part in self.CHECKPOINT_URL_PARTS):
            return LoginStatus.CHECKPOINT
        checkpoint_markers = page.locator(selectors.CHECKPOINT_MARKERS)
        if await self._any_visible(checkpoint_markers):
            return LoginStatus.CHECKPOINT
        email_fields = page.locator(selectors.LOGIN_EMAIL)
        password_fields = page.locator(selectors.LOGIN_PASSWORD)
        email_visible = await self._any_visible(email_fields)
        password_visible = await self._any_visible(password_fields)
        if email_visible and password_visible:
            return LoginStatus.LOGGED_OUT if "/login" in url.lower() else LoginStatus.SESSION_LOST
        cookies = await page.context.cookies("https://www.facebook.com/")
        if any(cookie.get("name") == "c_user" and cookie.get("value") for cookie in cookies):
            return LoginStatus.LOGGED_IN
        if await page.locator(selectors.ACCOUNT_MENU).count():
            return LoginStatus.LOGGED_IN
        return self.detect_from_html(url, await page.content())
