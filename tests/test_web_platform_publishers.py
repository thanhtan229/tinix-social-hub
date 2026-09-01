from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.publishers import PublishContext, PublishOutcome
from app.services.web_platform_publisher import SPECS, InstagramChromePublisher


class FakeButton:
    def __init__(self) -> None: self.clicks = 0
    async def click(self, **kwargs) -> None: self.clicks += 1


class FakePage:
    url = "https://www.instagram.com/"
    async def goto(self, *args, **kwargs) -> None: pass


class FakeSession:
    def __init__(self, port: int) -> None: self.fake_page = FakePage()
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def page(self): return self.fake_page


class Accounts:
    def update_login_status(self, account_id, status): pass


class PublisherUnderTest(InstagramChromePublisher):
    def __init__(self, root: Path) -> None:
        settings = SimpleNamespace(screenshot_dir=root, close_chrome_after_job=False)
        super().__init__(settings, SimpleNamespace(), Accounts(), SimpleNamespace(), SimpleNamespace())
        self.button = FakeButton()
    async def chrome_ready(self, account): return {"port": 1234}
    async def detect_login(self, page): return "logged_in"
    async def prepare_composer(self, page, context):
        await context.transition("publishing", "composer_ready", False)
        return self.button, []
    async def verify(self, page): return True, "https://www.instagram.com/p/test/"


class WebPlatformPublisherTests(unittest.IsolatedAsyncioTestCase):
    def test_specs_are_versioned_and_never_reference_platform_api(self) -> None:
        self.assertEqual(set(SPECS), {"instagram", "tiktok", "youtube"})
        for platform, spec in SPECS.items():
            self.assertIn("web", spec.version)
            self.assertNotIn("api.", spec.compose_url)
            self.assertTrue(spec.formats)

    async def test_dry_run_reaches_ready_without_clicking_submit(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            publisher = PublisherUnderTest(Path(root))
            transitions = []
            async def transition(*args): transitions.append(args)
            context = PublishContext(
                job={"id":"job-1","dry_run":1}, account={"id":"a","platform":"instagram"},
                payload={"content_format":"image","target_url":"https://www.instagram.com/example/"},
                is_cancelled=lambda: asyncio.sleep(0, result=False), transition=transition,
            )
            with patch("app.services.web_platform_publisher.BrowserSession", FakeSession):
                result = await publisher.publish(context)
            self.assertEqual(result.outcome, PublishOutcome.DRY_RUN_READY)
            self.assertEqual(publisher.button.clicks, 0)
            self.assertFalse(any(item[2] for item in transitions))

    async def test_real_publish_marks_commit_before_single_click(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            publisher = PublisherUnderTest(Path(root)); transitions=[]
            async def transition(*args): transitions.append(args)
            context=PublishContext(
                job={"id":"job-2","dry_run":0},account={"id":"a","platform":"instagram"},
                payload={"content_format":"image","target_url":"https://www.instagram.com/example/"},
                is_cancelled=lambda: asyncio.sleep(0,result=False),transition=transition,
            )
            with patch("app.services.web_platform_publisher.BrowserSession",FakeSession):result=await publisher.publish(context)
            self.assertEqual(result.outcome,PublishOutcome.PUBLISHED)
            self.assertEqual(publisher.button.clicks,1)
            self.assertIn(("verifying","commit_point_reached",True),transitions)


if __name__ == "__main__": unittest.main()
