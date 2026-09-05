from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Locator, Page

from app.automation.browser_session import BrowserSession
from app.core.config import Settings
from app.db.repositories import AccountRepository, ArtifactRepository
from app.services.chrome import ChromeManager
from app.services.media import MediaService
from app.services.publishers import (
    PublishContext,
    Publisher,
    PublishOutcome,
    PublishResult,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WebSelectorSpec:
    platform: str
    version: str
    home_url: str
    compose_url: str
    allowed_hosts: tuple[str, ...]
    login_selector: str
    logged_in_selector: str
    checkpoint_fragments: tuple[str, ...]
    create_selector: str | None
    file_input: str
    caption_selector: str
    title_selector: str | None
    submit_selector: str
    processing_selector: str
    success_selector: str
    target_link_selector: str
    post_url_fragments: tuple[str, ...]
    formats: tuple[str, ...]
    authenticated_cookie_names: tuple[str, ...] = ()


SPECS: dict[str, WebSelectorSpec] = {
    "instagram": WebSelectorSpec(
        "instagram", "instagram-web-v1", "https://www.instagram.com/", "https://www.instagram.com/",
        ("instagram.com",), 'input[name="username"],form[action*="login"]',
        'a[href^="/direct/inbox"],a[href*="accounts/edit"],svg[aria-label="Home"]',
        ("challenge", "checkpoint", "accounts/login"),
        'svg[aria-label="New post"],a[href="#"] svg[aria-label="New post"]', 'input[type="file"]',
        'div[contenteditable="true"][role="textbox"],textarea[aria-label*="caption" i]', None,
        'div[role="dialog"] button:has-text("Share"),div[role="dialog"] button:has-text("Chia sẻ")',
        'div[role="progressbar"]', 'text=/Your (post|reel) has been shared|Đã chia sẻ/i',
        'a[href^="/"]:not([href*="/explore"]):not([href*="/direct"])', ("/p/", "/reel/"),
        ("image", "carousel"),
    ),
    "tiktok": WebSelectorSpec(
        "tiktok", "tiktok-studio-web-v1", "https://www.tiktok.com/", "https://www.tiktok.com/tiktokstudio/upload",
        ("tiktok.com",), 'a[href*="/login"],button[data-e2e*="login"]',
        '[data-e2e="profile-icon"],a[href*="tiktokstudio"],a[href^="/@"]',
        ("captcha", "verify", "checkpoint"), None, 'input[type="file"]',
        '[contenteditable="true"][data-e2e*="caption"],div[contenteditable="true"]', None,
        'button[data-e2e*="post"],button:has-text("Post")', '[class*="progress" i],[data-e2e*="uploading"]',
        'text=/uploaded|posted|đã đăng/i', 'a[href^="/@"]', ("/video/",), ("short_video",),
        authenticated_cookie_names=("sessionid", "sessionid_ss", "sid_tt"),
    ),
    "youtube": WebSelectorSpec(
        "youtube", "youtube-studio-web-v1", "https://studio.youtube.com/", "https://studio.youtube.com/",
        ("youtube.com", "studio.youtube.com"), 'input[type="email"],a[href*="accounts.google.com"]',
        'ytcp-button#create-icon,ytcp-entity-page,ytcp-app-header',
        ("accounts.google.com", "challenge", "signin"),
        'ytcp-button#create-icon,tp-yt-paper-item[test-id="upload-beta"]', 'input[type="file"]',
        '#description-textarea #textbox,[aria-label*="description" i][contenteditable="true"]',
        '#title-textarea #textbox,[aria-label*="title" i][contenteditable="true"]',
        '#done-button,#save-button', 'ytcp-video-upload-progress,[class*="progress" i]',
        'text=/Checks complete|Upload complete|Đã tải lên/i', 'a[href*="/channel/"]',
        ("youtu.be/", "youtube.com/watch", "youtube.com/shorts"), ("video", "short"),
    ),
    "x": WebSelectorSpec(
        "x", "x-web-v1", "https://x.com/home", "https://x.com/compose/post",
        ("x.com", "twitter.com"),
        'input[autocomplete="username"],input[name="text"],input[autocomplete="current-password"]',
        'a[data-testid="AppTabBar_Profile_Link"],button[data-testid="SideNav_AccountSwitcher_Button"]',
        ("account/access", "account/locked", "account/suspended"), None,
        'input[data-testid="fileInput"],input[type="file"][accept*="image"]',
        'div[data-testid="tweetTextarea_0"][contenteditable="true"]', None,
        'button[data-testid="tweetButtonInline"],button[data-testid="tweetButton"]',
        'div[role="progressbar"]',
        'text=/Your post was sent|Bài đăng của bạn đã được gửi/i',
        'a[data-testid="AppTabBar_Profile_Link"],a[href*="/status/"]',
        ("/status/",), ("post",), authenticated_cookie_names=("auth_token",),
    ),
}


class ChromeWebPublisher(Publisher):
    max_concurrent_jobs = 1

    def __init__(
        self, spec: WebSelectorSpec, settings: Settings, chrome: ChromeManager,
        accounts: AccountRepository, artifacts: ArtifactRepository, media: MediaService,
    ) -> None:
        self.spec = spec
        self.platform_id = spec.platform
        self.selector_version = spec.version
        self.settings = settings
        self.chrome = chrome
        self.accounts = accounts
        self.artifacts = artifacts
        self.media = media

    def validate_target(self, url: str | None) -> str:
        if not url:
            return self.spec.home_url
        parsed = urlparse(url)
        if parsed.scheme != "https" or not any(parsed.netloc.lower().endswith(host) for host in self.spec.allowed_hosts):
            raise ValueError(f"URL đích không thuộc {self.spec.platform}.")
        return url

    async def chrome_ready(self, account: dict) -> dict:
        status = await asyncio.to_thread(self.chrome.status, account["id"])
        if not status:
            await asyncio.to_thread(self.chrome.open, account)
        for _ in range(30):
            status = await asyncio.to_thread(self.chrome.status, account["id"])
            if status and status["state"] == "ready": return status
            if status and status["state"] == "unresponsive": raise RuntimeError("Chrome không phản hồi qua CDP.")
            await asyncio.sleep(.5)
        raise RuntimeError("Chrome khởi động quá thời gian chờ.")

    @staticmethod
    async def _any_visible(locator: Locator, limit: int = 10) -> bool:
        for index in range(min(await locator.count(), limit)):
            if await locator.nth(index).is_visible():
                return True
        return False

    async def detect_login(self, page: Page) -> str:
        url = page.url.lower()
        if any(fragment in url for fragment in self.spec.checkpoint_fragments): return "checkpoint"
        if await self._any_visible(page.locator(self.spec.logged_in_selector)): return "logged_in"
        if await self._any_visible(page.locator(self.spec.login_selector)): return "logged_out"
        if self.spec.authenticated_cookie_names:
            cookies = await page.context.cookies(self.spec.home_url)
            if any(
                cookie.get("name") in self.spec.authenticated_cookie_names and cookie.get("value")
                for cookie in cookies
            ):
                return "logged_in"
        if "/login" in url or "/signin" in url: return "logged_out"
        return "unknown"

    async def discover_targets(self, page: Page) -> list[dict[str, str]]:
        anchors = page.locator(self.spec.target_link_selector)
        values = await anchors.evaluate_all("els => els.map(a => ({url:a.href||'',name:(a.textContent||a.getAttribute('aria-label')||'').trim()}))")
        result, seen = [], set()
        for item in values:
            url = item.get("url", "")
            if not url or url in seen or not any(urlparse(url).netloc.lower().endswith(host) for host in self.spec.allowed_hosts): continue
            seen.add(url)
            external = urlparse(url).path.strip("/") or self.spec.platform
            target_type = "profile" if self.spec.platform in {"instagram", "x"} else "channel"
            result.append({"external_id": external[:255], "name": (item.get("name") or external)[:255], "url": url, "target_type": target_type})
        return result[:20]

    async def _visible(self, page: Page, selector: str) -> Locator:
        locator = page.locator(selector).last
        await locator.wait_for(state="visible", timeout=30_000)
        return locator

    async def apply_platform_settings(self, page: Page, settings: dict) -> None:
        """Apply only controls that can be positively identified; never guess-click publish."""
        if self.spec.platform == "tiktok":
            privacy = settings.get("privacy")
            control = page.locator('select[data-e2e*="privacy"],select[name*="privacy" i]').first
            if privacy and await control.count():
                await control.select_option(value=str(privacy))
            comments = page.locator('input[type="checkbox"][name*="comment" i]').first
            if "allow_comments" in settings and await comments.count():
                checked = await comments.is_checked()
                if checked != bool(settings["allow_comments"]): await comments.click()
        if self.spec.platform == "youtube":
            audience = page.locator('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]').first
            if await audience.count(): await audience.click()
            for _ in range(3):
                next_button = page.locator('#next-button:not([disabled])').first
                if not await next_button.count(): break
                await next_button.click(); await page.wait_for_timeout(500)
            privacy = str(settings.get("privacy") or "private").upper()
            option = page.locator(f'tp-yt-paper-radio-button[name="{privacy}"]').first
            if await option.count(): await option.click()

    async def prepare_composer(self, page: Page, context: PublishContext) -> tuple[Locator, list[Path]]:
        await page.goto(self.spec.compose_url, wait_until="domcontentloaded", timeout=30_000)
        if self.spec.create_selector:
            create = page.locator(self.spec.create_selector).first
            if await create.count(): await create.click(timeout=15_000)
        paths = [await asyncio.to_thread(self.media.resolve_existing, item["relative_path"]) for item in context.payload.get("media", [])]
        if paths:
            await context.transition("uploading", "upload_started", False)
            await page.locator(self.spec.file_input).last.set_input_files([str(path) for path in paths], timeout=30_000)
        if self.spec.title_selector:
            title = str((context.payload.get("platform_settings") or {}).get("title") or context.payload.get("title") or "")
            field = await self._visible(page, self.spec.title_selector)
            await field.fill(title[:100])
        caption = context.payload.get("caption", "")
        hashtags = " ".join(context.payload.get("hashtags") or [])
        full_caption = "\n\n".join(part for part in (caption, hashtags) if part).strip()
        if self.spec.caption_selector:
            field = await self._visible(page, self.spec.caption_selector)
            await field.fill(full_caption)
        await self.apply_platform_settings(page, context.payload.get("platform_settings") or {})
        await context.transition("publishing", "composer_ready", False)
        submit = await self._visible(page, self.spec.submit_selector)
        loop, deadline = asyncio.get_running_loop(), asyncio.get_running_loop().time()+180
        while loop.time()<deadline:
            busy = await page.locator(self.spec.processing_selector).count()
            if not busy and await submit.is_enabled(): return submit, paths
            await page.wait_for_timeout(500)
        raise RuntimeError("Upload chưa xử lý xong hoặc nút phát hành chưa sẵn sàng.")

    async def verify(self, page: Page) -> tuple[bool, str | None]:
        deadline=asyncio.get_running_loop().time()+60
        while asyncio.get_running_loop().time()<deadline:
            if await page.locator(self.spec.success_selector).count(): return True, None
            hrefs=await page.locator("a[href]").evaluate_all("els => els.map(a=>a.href||'')")
            match=next((url for url in hrefs if any(fragment in url for fragment in self.spec.post_url_fragments)),None)
            if match:return True,match
            await page.wait_for_timeout(750)
        return False,None

    async def capture(self, page: Page | None, job_id: str, step: str) -> None:
        if not page:return
        try:
            root=self.settings.screenshot_dir.resolve();directory=(root/job_id).resolve()
            if root not in directory.parents:return
            directory.mkdir(parents=True,exist_ok=True)
            path=directory/f"{self.spec.platform}-{step}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S-%f}.png"
            await page.screenshot(path=str(path),full_page=False)
            await asyncio.to_thread(self.artifacts.record,job_id,"screenshot",path.relative_to(root).as_posix(),{"step":step,"selector_version":self.selector_version})
        except Exception:logger.warning("Could not capture %s screenshot for %s",self.spec.platform,job_id)

    async def publish(self, context: PublishContext) -> PublishResult:
        content_format=context.payload.get("content_format") or ""
        if content_format not in self.spec.formats:
            return PublishResult(PublishOutcome.UNSUPPORTED,f"{self.spec.platform} chưa hỗ trợ Chrome format {content_format}.")
        page=None;submitted=False;keep=False
        self.validate_target(context.payload.get("target_url"))
        if await context.is_cancelled():raise asyncio.CancelledError
        chrome=await self.chrome_ready(context.account)
        try:
            async with BrowserSession(chrome["port"]) as session:
                page=await session.page();await page.goto(self.spec.home_url,wait_until="domcontentloaded",timeout=30_000)
                login=await self.detect_login(page);await asyncio.to_thread(self.accounts.update_login_status,context.account["id"],login)
                if login=="checkpoint":keep=True;return PublishResult(PublishOutcome.CHECKPOINT,"Nền tảng yêu cầu checkpoint/captcha.")
                if login!="logged_in":keep=True;return PublishResult(PublishOutcome.LOGIN_REQUIRED,"Account chưa đăng nhập hoặc trạng thái phiên chưa xác định.")
                submit,paths=await self.prepare_composer(page,context)
                if await context.is_cancelled():raise asyncio.CancelledError
                if context.job.get("dry_run"):
                    keep=True;return PublishResult(PublishOutcome.DRY_RUN_READY,"Dry-run đã tới nút phát hành và chưa click.",metadata={"media_count":len(paths),"selector_version":self.selector_version})
                await context.transition("verifying","commit_point_reached",True);submitted=True
                await submit.click(timeout=15_000)
                ok,url=await self.verify(page)
                if not ok:
                    await self.capture(page,context.job["id"],"verify")
                    return PublishResult(PublishOutcome.UNKNOWN_RESULT,"Đã click phát hành nhưng chưa xác minh được kết quả.")
                return PublishResult(PublishOutcome.PUBLISHED,"Đã xác minh phát hành trên UI.",post_url=url,metadata={"selector_version":self.selector_version})
        except asyncio.CancelledError:raise
        except Exception:
            await self.capture(page,context.job["id"],"publisher-error")
            if submitted:return PublishResult(PublishOutcome.UNKNOWN_RESULT,"Lỗi sau commit point; cần xác minh thủ công.")
            raise
        finally:
            if self.settings.close_chrome_after_job and not keep:await asyncio.to_thread(self.chrome.close,context.account["id"])


class InstagramChromePublisher(ChromeWebPublisher):
    def __init__(self,*args,**kwargs):super().__init__(SPECS["instagram"],*args,**kwargs)


class TikTokChromePublisher(ChromeWebPublisher):
    def __init__(self,*args,**kwargs):super().__init__(SPECS["tiktok"],*args,**kwargs)


class YouTubeChromePublisher(ChromeWebPublisher):
    def __init__(self,*args,**kwargs):super().__init__(SPECS["youtube"],*args,**kwargs)


class XChromePublisher(ChromeWebPublisher):
    def __init__(self,*args,**kwargs):super().__init__(SPECS["x"],*args,**kwargs)
