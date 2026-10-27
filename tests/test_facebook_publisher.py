from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.automation.facebook.login_detector import LoginStatus
from app.services.facebook_publisher import FacebookPublisher
from app.services.publishers import PublishContext, PublishOutcome


class FakePage:
    url = "https://www.facebook.com/"

    async def goto(self, url, **kwargs):
        self.url = url


class FakeSession:
    def __init__(self, port):
        self.fake_page = FakePage()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def page(self):
        return self.fake_page


class FakeComposer:
    submitted = False
    verify_result = (True, "https://www.facebook.com/page/posts/123")

    def __init__(self, page):
        pass

    async def open(self):
        pass

    async def fill_caption(self, caption):
        self.caption = caption

    async def upload_media(self, paths):
        pass

    async def wait_until_ready(self):
        return object()

    async def submit(self, button):
        type(self).submitted = True

    async def verify_published(self):
        return type(self).verify_result


class FacebookPublisherTests(unittest.TestCase):
    @patch("app.services.facebook_publisher.BrowserSession", FakeSession)
    @patch("app.services.facebook_publisher.FacebookComposerPage", FakeComposer)
    def test_changed_media_never_reaches_submit(self):
        import hashlib
        from app.services.media import MediaValidationError
        path = Path(self.temp.name) / "photo.jpg"
        path.write_bytes(b"changed")
        self.media.resolve_existing = lambda _: path
        transitions = []
        context = self.context(False, transitions)
        context.payload["media"] = [{"relative_path": "photo.jpg", "size_bytes": 7, "sha256": hashlib.sha256(b"approve").hexdigest()}]
        with self.assertRaises(MediaValidationError):
            asyncio.run(self.publisher.publish(context))
        self.assertFalse(FakeComposer.submitted)
        self.assertFalse(any(item[2] for item in transitions))

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.settings = SimpleNamespace(
            screenshot_dir=Path(self.temp.name) / "screenshots",
            close_chrome_after_job=False,
        )
        self.chrome = SimpleNamespace(
            status=lambda account_id: {"state": "ready", "port": 12345},
            open=lambda account: {"state": "ready", "port": 12345},
            close=lambda account_id: True,
        )
        self.accounts = SimpleNamespace(update_login_status=lambda account_id, status: None)
        self.artifacts = SimpleNamespace(record=lambda *args, **kwargs: None)
        self.media = SimpleNamespace(resolve_existing=lambda path: Path(path))
        self.publisher = FacebookPublisher(self.settings, self.chrome, self.accounts, self.artifacts, self.media)
        self.publisher.detector = SimpleNamespace(detect=self._logged_in)
        FakeComposer.submitted = False
        FakeComposer.verify_result = (True, "https://www.facebook.com/page/posts/123")

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    async def _logged_in(page):
        return LoginStatus.LOGGED_IN

    def context(self, dry_run: bool, transitions: list[tuple[str, str, bool]]) -> PublishContext:
        async def is_cancelled():
            return False

        async def transition(target, event, commit=False):
            transitions.append((target, event, commit))

        return PublishContext(
            job={"id": "job-1", "dry_run": int(dry_run)},
            account={"id": "account-1", "platform": "facebook"},
            payload={
                "target_url": "https://www.facebook.com/page",
                "caption": "Hello", "hashtags": ["#test"], "media": [],
            },
            is_cancelled=is_cancelled,
            transition=transition,
        )

    @patch("app.services.facebook_publisher.BrowserSession", FakeSession)
    @patch("app.services.facebook_publisher.FacebookComposerPage", FakeComposer)
    def test_dry_run_never_clicks_post(self) -> None:
        transitions = []
        result = asyncio.run(self.publisher.publish(self.context(True, transitions)))
        self.assertEqual(result.outcome, PublishOutcome.DRY_RUN_READY)
        self.assertFalse(FakeComposer.submitted)
        self.assertIn(("publishing", "composer_ready", False), transitions)

    @patch("app.services.facebook_publisher.BrowserSession", FakeSession)
    @patch("app.services.facebook_publisher.FacebookComposerPage", FakeComposer)
    def test_real_publish_marks_commit_before_click_and_requires_verification(self) -> None:
        transitions = []
        result = asyncio.run(self.publisher.publish(self.context(False, transitions)))
        self.assertEqual(result.outcome, PublishOutcome.PUBLISHED)
        self.assertTrue(FakeComposer.submitted)
        self.assertEqual(transitions[-1], ("verifying", "commit_point_reached", True))
        self.assertIn("/posts/123", result.post_url)

    @patch("app.services.facebook_publisher.BrowserSession", FakeSession)
    @patch("app.services.facebook_publisher.FacebookComposerPage", FakeComposer)
    def test_unverified_post_is_unknown_result(self) -> None:
        FakeComposer.verify_result = (False, None)
        result = asyncio.run(self.publisher.publish(self.context(False, [])))
        self.assertEqual(result.outcome, PublishOutcome.UNKNOWN_RESULT)

    def test_non_facebook_target_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.publisher._validate_target("https://example.com/page")


if __name__ == "__main__":
    unittest.main()

