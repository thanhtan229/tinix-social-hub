from __future__ import annotations

import unittest

from app.automation.facebook.login_detector import FacebookLoginDetector, LoginStatus
from app.automation.facebook.page_objects import FacebookPagesPage


class LoginDetectorFixtureTests(unittest.TestCase):
    def test_checkpoint_url_wins(self) -> None:
        self.assertEqual(
            FacebookLoginDetector.detect_from_html("https://www.facebook.com/checkpoint/", "<html></html>"),
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

