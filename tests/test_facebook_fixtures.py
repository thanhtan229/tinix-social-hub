from __future__ import annotations

import unittest

from app.automation.facebook.login_detector import FacebookLoginDetector, LoginStatus
from app.automation.facebook.page_objects import FacebookPagesPage


class EmptyLocator:
    async def count(self) -> int:
        return 0

    def nth(self, _index: int) -> "EmptyLocator":
        return self

    async def is_visible(self) -> bool:
        return False


class LoggedInContext:
    async def cookies(self, _url: str) -> list[dict[str, str]]:
        return [{"name": "c_user", "value": "test-user"}]


class CookieAuthenticatedPage:
    url = "https://www.facebook.com/"
    context = LoggedInContext()

    def locator(self, _selector: str) -> EmptyLocator:
        return EmptyLocator()

    async def content(self) -> str:
        return "<html></html>"


class LoginDetectorFixtureTests(unittest.TestCase):
    def test_checkpoint_url_wins(self) -> None:
        self.assertEqual(
            FacebookLoginDetector.detect_from_html("https://www.facebook.com/checkpoint/", "<html></html>"),
            LoginStatus.CHECKPOINT,
        )

    def test_unrelated_checkpoint_text_does_not_override_logged_in_signal(self) -> None:
        html = '<form id="composer"></form><script>const route = "checkpoint";</script><div aria-label="Tài khoản"></div>'
        self.assertEqual(
            FacebookLoginDetector.detect_from_html("https://www.facebook.com/", html),
            LoginStatus.LOGGED_IN,
        )
    def test_checkpoint_form_is_detected(self) -> None:
        html = '<form method="post" action="/checkpoint/verify/"><input name="approvals_code"></form>'
        self.assertEqual(
            FacebookLoginDetector.detect_from_html("https://www.facebook.com/", html),
            LoginStatus.CHECKPOINT,
        )

    def test_login_form_is_logged_out(self) -> None:
        html = '<form><input name="email"><input name="pass" type="password"></form>'
        self.assertEqual(
            FacebookLoginDetector.detect_from_html("https://www.facebook.com/login/", html),
            LoginStatus.LOGGED_OUT,
        )

    def test_account_menu_is_logged_in(self) -> None:
        html = '<div aria-label="Tài khoản"></div>'
        self.assertEqual(
            FacebookLoginDetector.detect_from_html("https://www.facebook.com/", html),
            LoginStatus.LOGGED_IN,
        )


class AsyncLoginDetectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_c_user_cookie_is_authenticated_without_account_menu(self) -> None:
        self.assertEqual(
            await FacebookLoginDetector().detect(CookieAuthenticatedPage()),
            LoginStatus.LOGGED_IN,
        )


class FacebookPageLinkFixtureTests(unittest.TestCase):
    def test_page_parser_filters_generic_labels_and_reserved_links(self) -> None:
        links = [
            {"href": "https://www.facebook.com/tinix.studio", "text": "Tinix Studio"},
            {"href": "https://www.facebook.com/tinix.studio/about", "text": "Thông tin liên hệ"},
            {"href": "https://www.facebook.com/pages/", "text": "Pages"},
            {"href": "https://example.com/not-facebook", "text": "Wrong"},
        ]
        result = FacebookPagesPage.parse_links(links)
        self.assertEqual([(item.external_id, item.name) for item in result], [("url:tinix.studio", "Tinix Studio")])

    def test_numeric_profile_id_is_stable(self) -> None:
        result = FacebookPagesPage.parse_links(
            [{"href": "https://www.facebook.com/profile.php?id=123456&ref=pages", "text": "Page Number"}]
        )
        self.assertEqual(result[0].external_id, "123456")
        self.assertEqual(result[0].url, "https://www.facebook.com/profile.php?id=123456")
