from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.automation.facebook.composer import FacebookComposerPage


class FacebookComposerVerificationTests(unittest.TestCase):
    def test_normalizes_modern_facebook_permalink(self) -> None:
        url = FacebookComposerPage._normalize_post_url(
            "https://www.facebook.com/permalink.php?story_fbid=123&id=456&__cft__[0]=tracking#fragment"
        )
        self.assertEqual(
            url,
            "https://www.facebook.com/permalink.php?story_fbid=123&id=456",
        )

    def test_rejects_non_facebook_and_non_post_links(self) -> None:
        self.assertIsNone(FacebookComposerPage._normalize_post_url("https://example.com/posts/123"))
        self.assertIsNone(FacebookComposerPage._normalize_post_url("https://www.facebook.com/tinicantho"))

    def test_builds_permalink_from_page_boost_link(self) -> None:
        url = FacebookComposerPage._post_url_from_boost_href(
            "https://www.facebook.com/ad_center/create/boostpost/?page_id=106946975052940&target_id=1090686046690449&tracking=value"
        )
        self.assertEqual(
            url,
            "https://www.facebook.com/106946975052940/posts/1090686046690449",
        )

    def test_rejects_boost_link_without_post_identity(self) -> None:
        self.assertIsNone(
            FacebookComposerPage._post_url_from_boost_href(
                "https://www.facebook.com/ad_center/create/boostpost/?page_id=106946975052940"
            )
        )

    def test_verification_returns_new_permalink_before_caption_fallback(self) -> None:
        page = MagicMock()
        page.get_by_text.return_value.first.count = AsyncMock(return_value=1)
        page.get_by_text.return_value.first.is_visible = AsyncMock(return_value=True)
        composer = FacebookComposerPage(page)
        composer.before_post_links = {"https://www.facebook.com/page/posts/old"}
        composer._published_post_url = AsyncMock(
            return_value="https://www.facebook.com/page/posts/new"
        )

        verified, post_url = asyncio.run(composer.verify_published())

        self.assertTrue(verified)
        self.assertEqual(post_url, "https://www.facebook.com/page/posts/new")


if __name__ == "__main__":
    unittest.main()
