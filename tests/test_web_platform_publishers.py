from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.publishers import PublishContext, PublishOutcome
from app.services.web_platform_publisher import (
    ChromeWebPublisher,
    SPECS,
    InstagramChromePublisher,
    TikTokChromePublisher,
    VerificationBaseline,
    XChromePublisher,
)


class FakeButton:
    def __init__(self) -> None: self.clicks = 0
    async def click(self, **kwargs) -> None: self.clicks += 1


class FakePage:
    url = "https://www.instagram.com/"
    async def goto(self, *args, **kwargs) -> None: pass


class VerificationElement:
    def __init__(self, visible: bool) -> None:
        self.visible = visible

    async def is_visible(self) -> bool:
        return self.visible


class VerificationLocator:
    def __init__(self, page, kind: str) -> None:
        self.page = page
        self.kind = kind

    async def count(self) -> int:
        if self.kind == "links":
            return len(self.page.links)
        return int(self.page.success_present)

    def nth(self, _index: int):
        return VerificationElement(self.page.success_visible)

    async def evaluate_all(self, _script: str):
        return list(self.page.links)


class VerificationPage:
    def __init__(self, links=(), *, success_present: bool = False, success_visible: bool = False) -> None:
        self.links = list(links)
        self.success_present = success_present
        self.success_visible = success_visible

    def locator(self, selector: str):
        return VerificationLocator(self, "links" if selector == "a[href]" else "success")


class FakeSession:
    def __init__(self, port: int) -> None: self.fake_page = FakePage()
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def page(self): return self.fake_page


class Accounts:
    def update_login_status(self, account_id, status): pass


class EmptyLocator:
    async def count(self): return 0
    def nth(self, _index): return self
    async def is_visible(self): return False


class TikTokContext:
    def __init__(self, cookies): self._cookies = cookies
    async def cookies(self, _url): return self._cookies


class TikTokPage:
    def __init__(self, url="https://www.tiktok.com/", cookies=()):
        self.url = url
        self.context = TikTokContext(cookies)
    def locator(self, _selector): return EmptyLocator()


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
    async def capture_verification_baseline(self, page): return VerificationBaseline(frozenset(), 0)
    async def verify(self, page, baseline): return True, "https://www.instagram.com/p/test/"


class WebPlatformPublisherTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def verifier(root: Path, platform: str) -> ChromeWebPublisher:
        return ChromeWebPublisher(
            SPECS[platform],
            SimpleNamespace(screenshot_dir=root, close_chrome_after_job=False),
            SimpleNamespace(), Accounts(), SimpleNamespace(), SimpleNamespace(),
        )

    def test_specs_are_versioned_and_never_reference_platform_api(self) -> None:
        self.assertEqual(set(SPECS), {"instagram", "tiktok", "youtube", "x"})
        for platform, spec in SPECS.items():
            self.assertIn("web", spec.version)
            self.assertNotIn("api.", spec.compose_url)
            self.assertTrue(spec.formats)

    async def test_tiktok_session_cookie_is_detected_before_spa_dom_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            settings = SimpleNamespace(screenshot_dir=Path(root), close_chrome_after_job=False)
            publisher = TikTokChromePublisher(
                settings, SimpleNamespace(), Accounts(), SimpleNamespace(), SimpleNamespace()
            )
            page = TikTokPage(cookies=[{"name": "sessionid", "value": "active-session"}])
            self.assertEqual(await publisher.detect_login(page), "logged_in")

    async def test_tiktok_login_url_is_logged_out_not_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            settings = SimpleNamespace(screenshot_dir=Path(root), close_chrome_after_job=False)
            publisher = TikTokChromePublisher(
                settings, SimpleNamespace(), Accounts(), SimpleNamespace(), SimpleNamespace()
            )
            self.assertEqual(
                await publisher.detect_login(TikTokPage(url="https://www.tiktok.com/login")),
                "logged_out",
            )

    async def test_x_auth_cookie_and_target_url_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            settings = SimpleNamespace(screenshot_dir=Path(root), close_chrome_after_job=False)
            publisher = XChromePublisher(
                settings, SimpleNamespace(), Accounts(), SimpleNamespace(), SimpleNamespace()
            )
            page = TikTokPage(
                url="https://x.com/home",
                cookies=[{"name": "auth_token", "value": "active-session"}],
            )
            self.assertEqual(await publisher.detect_login(page), "logged_in")
            self.assertEqual(publisher.validate_target("https://x.com/tinix"), "https://x.com/tinix")
            with self.assertRaises(ValueError):
                publisher.validate_target("https://example.com/tinix")
            with self.assertRaises(ValueError):
                publisher.validate_target("https://notx.com/tinix")

    async def test_youtube_discovery_collapses_studio_menu_links_to_one_channel(self) -> None:
        channel_id = "UCXdYgfzFMIvyE-tgjosC6MQ"
        with tempfile.TemporaryDirectory() as root:
            publisher = self.verifier(Path(root), "youtube")
            page = VerificationPage([
                {"url": f"https://studio.youtube.com/channel/{channel_id}/analytics", "name": "Analytics"},
                {"url": f"https://studio.youtube.com/channel/{channel_id}/content", "name": "Content"},
                {"url": f"https://www.youtube.com/channel/{channel_id}", "name": "Tan Nguyen"},
                {"url": f"https://studio.youtube.com/channel/{channel_id}/posts", "name": "Community"},
            ])
            self.assertEqual(await publisher.discover_targets(page), [{
                "external_id": channel_id,
                "name": "Tan Nguyen",
                "url": f"https://www.youtube.com/channel/{channel_id}",
                "target_type": "channel",
            }])

    async def test_verifier_rejects_existing_post_link_and_hidden_success_signal(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            old_urls = {
                "instagram": "https://www.instagram.com/p/old-post/",
                "tiktok": "https://www.tiktok.com/@tinix/video/old-post",
                "youtube": "https://www.youtube.com/watch?v=old-post",
                "x": "https://x.com/tinix/status/old-post",
            }
            for platform, old_url in old_urls.items():
                publisher = self.verifier(Path(root), platform)
                page = VerificationPage([old_url])
                baseline = await publisher.capture_verification_baseline(page)
                page.success_present = True
                page.success_visible = False
                self.assertEqual(await publisher.verify(page, baseline, timeout_seconds=0), (False, None))

    async def test_verifier_accepts_new_visible_evidence_only(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            evidence = {
                "instagram": ("https://www.instagram.com/p/old-post/", "https://www.instagram.com/p/new-post/"),
                "tiktok": ("https://www.tiktok.com/@tinix/video/old-post", "https://www.tiktok.com/@tinix/video/new-post"),
                "youtube": ("https://www.youtube.com/watch?v=old-post", "https://www.youtube.com/watch?v=new-post"),
                "x": ("https://x.com/tinix/status/old-post", "https://x.com/tinix/status/new-post"),
            }
            for platform, (old_url, new_url) in evidence.items():
                publisher = self.verifier(Path(root), platform)
                page = VerificationPage([old_url])
                baseline = await publisher.capture_verification_baseline(page)
                page.links.append(new_url)
                self.assertEqual(await publisher.verify(page, baseline, timeout_seconds=0), (True, new_url.rstrip("/")))
            publisher = self.verifier(Path(root), "instagram")
            page = VerificationPage()
            baseline = await publisher.capture_verification_baseline(page)
            page.success_present = True
            page.success_visible = True
            self.assertEqual(await publisher.verify(page, baseline, timeout_seconds=0), (True, None))

    async def test_verifier_rejects_lookalike_hostname(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            publisher = self.verifier(Path(root), "instagram")
            page = VerificationPage(["https://notinstagram.com/p/not-ours/"])
            baseline = await publisher.capture_verification_baseline(page)
            self.assertEqual(await publisher.verify(page, baseline, timeout_seconds=0), (False, None))

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

    async def test_unverified_real_publish_is_unknown_result(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            publisher = PublisherUnderTest(Path(root))

            async def unverified(_page, _baseline):
                return False, None

            publisher.verify = unverified
            context = PublishContext(
                job={"id": "job-3", "dry_run": 0}, account={"id": "a", "platform": "instagram"},
                payload={"content_format": "image", "target_url": "https://www.instagram.com/example/"},
                is_cancelled=lambda: asyncio.sleep(0, result=False), transition=lambda *_args: asyncio.sleep(0),
            )
            with patch("app.services.web_platform_publisher.BrowserSession", FakeSession):
                result = await publisher.publish(context)
            self.assertEqual(result.outcome, PublishOutcome.UNKNOWN_RESULT)
            self.assertEqual(publisher.button.clicks, 1)


if __name__ == "__main__": unittest.main()
