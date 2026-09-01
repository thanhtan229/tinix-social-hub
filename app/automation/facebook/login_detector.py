from __future__ import annotations

from enum import StrEnum

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

    @classmethod
    def detect_from_html(cls, url: str, html: str) -> LoginStatus:
        lowered_url = url.lower()
        lowered = html.lower()
        if any(part in lowered_url for part in cls.CHECKPOINT_URL_PARTS):
            return LoginStatus.CHECKPOINT
        if "approvals_code" in lowered or "checkpoint" in lowered and "form" in lowered:
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
        if await page.locator(selectors.CHECKPOINT_MARKERS).count():
            return LoginStatus.CHECKPOINT
        if await page.locator(selectors.LOGIN_EMAIL).count() and await page.locator(selectors.LOGIN_PASSWORD).count():
            return LoginStatus.LOGGED_OUT if "/login" in url.lower() else LoginStatus.SESSION_LOST
        if await page.locator(selectors.ACCOUNT_MENU).count():
            return LoginStatus.LOGGED_IN
        return self.detect_from_html(url, await page.content())

