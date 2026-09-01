from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Page

from app.automation.browser_session import BrowserSession
from app.automation.facebook.composer import FacebookComposerPage
from app.automation.facebook.login_detector import FacebookLoginDetector, LoginStatus
from app.core.config import Settings
from app.db.repositories import AccountRepository, ArtifactRepository
from app.services.chrome import ChromeManager
from app.services.media import MediaService
from app.services.publishers import PublishContext, PublishOutcome, Publisher, PublishResult


logger = logging.getLogger(__name__)


class FacebookPublisher(Publisher):
    selector_version = "facebook-web-v1"
    def __init__(
        self,
        settings: Settings,
        chrome: ChromeManager,
        accounts: AccountRepository,
        artifacts: ArtifactRepository,
        media: MediaService,
    ) -> None:
        self.settings = settings
        self.chrome = chrome
        self.accounts = accounts
        self.artifacts = artifacts
        self.media = media
        self.detector = FacebookLoginDetector()

    @staticmethod
    def _validate_target(url: str | None) -> str:
        if not url:
            raise ValueError("Job chưa có URL Facebook Page đích.")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc.lower().endswith("facebook.com"):
            raise ValueError("URL Page đích không thuộc facebook.com.")
        return url

    async def _chrome_ready(self, account: dict) -> dict:
        status = await asyncio.to_thread(self.chrome.status, account["id"])
        if not status:
            status = await asyncio.to_thread(self.chrome.open, account)
        for _ in range(30):
            status = await asyncio.to_thread(self.chrome.status, account["id"])
            if status and status["state"] == "ready":
                return status
            if status and status["state"] == "unresponsive":
                raise RuntimeError("Chrome bị treo hoặc cổng CDP không phản hồi.")
            await asyncio.sleep(0.5)
        raise RuntimeError("Chrome khởi động quá thời gian chờ.")

    async def _capture_error(self, page: Page | None, job_id: str, step: str) -> None:
        if not page:
            return
        try:
            directory = (self.settings.screenshot_dir / job_id).resolve()
            root = self.settings.screenshot_dir.resolve()
            if root not in directory.parents:
                return
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            path = directory / f"{step}-{stamp}.png"
            await page.screenshot(path=str(path), full_page=False)
            await asyncio.to_thread(
                self.artifacts.record, job_id, "screenshot", path.relative_to(root).as_posix(), {"step": step}
            )
        except Exception:
            logger.warning("Could not capture Facebook error screenshot for job %s", job_id)

    @staticmethod
    async def _check_cancel(context: PublishContext) -> None:
        if await context.is_cancelled():
            raise asyncio.CancelledError

    async def publish(self, context: PublishContext) -> PublishResult:
        page: Page | None = None
        submitted = False
        keep_chrome = False
        target_url = self._validate_target(context.payload.get("target_url"))
        await self._check_cancel(context)
        chrome = await self._chrome_ready(context.account)
        try:
            async with BrowserSession(chrome["port"]) as session:
                page = await session.page()
                await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30_000)
                login = await self.detector.detect(page)
                await asyncio.to_thread(self.accounts.update_login_status, context.account["id"], login.value)
                if login == LoginStatus.CHECKPOINT:
                    keep_chrome = True
                    return PublishResult(PublishOutcome.CHECKPOINT, "Facebook đang yêu cầu checkpoint.")
                if login != LoginStatus.LOGGED_IN:
                    keep_chrome = True
                    return PublishResult(PublishOutcome.LOGIN_REQUIRED, "Account Facebook chưa đăng nhập hoặc đã mất phiên.")

                await self._check_cancel(context)
                await page.goto(target_url, wait_until="domcontentloaded", timeout=30_000)
                composer = FacebookComposerPage(page)
                await composer.open()
                caption = context.payload.get("caption", "")
                hashtags = " ".join(context.payload.get("hashtags") or [])
                cta = context.payload.get("cta") or ""
                full_caption = "\n\n".join(part for part in (caption, cta, hashtags) if part).strip()
                await composer.fill_caption(full_caption)

                media_records = context.payload.get("media") or []
                media_paths: list[Path] = []
                if media_records:
                    await context.transition("uploading", "upload_started", False)
                    for item in media_records:
                        media_paths.append(await asyncio.to_thread(self.media.resolve_existing, item["relative_path"]))
                    await self._check_cancel(context)
                    await composer.upload_media(media_paths)
                await context.transition("publishing", "composer_ready", False)
                post_button = await composer.wait_until_ready()
                await self._check_cancel(context)
                if context.job.get("dry_run"):
                    keep_chrome = True
                    return PublishResult(
                        PublishOutcome.DRY_RUN_READY,
                        "Dry-run đã tới bước cuối; nút Đăng sẵn sàng nhưng chưa được bấm.",
                        metadata={"target_url": target_url, "media_count": len(media_paths)},
                    )

                await context.transition("verifying", "commit_point_reached", True)
                submitted = True
                await composer.submit(post_button)
                published, post_url = await composer.verify_published()
                if not published:
                    await self._capture_error(page, context.job["id"], "verify")
                    return PublishResult(PublishOutcome.UNKNOWN_RESULT, "Đã bấm Đăng nhưng chưa xác minh được kết quả.")
                return PublishResult(
                    PublishOutcome.PUBLISHED,
                    "Facebook đã đóng composer sau khi đăng.",
                    post_url=post_url,
                    metadata={"target_url": target_url, "media_count": len(media_paths)},
                )
        except asyncio.CancelledError:
            if submitted:
                await self._capture_error(page, context.job["id"], "cancel-after-commit")
            raise
        except Exception:
            await self._capture_error(page, context.job["id"], "publisher-error")
            if submitted:
                return PublishResult(PublishOutcome.UNKNOWN_RESULT, "Lỗi sau khi bấm Đăng; cần xác minh thủ công.")
            raise
        finally:
            if self.settings.close_chrome_after_job and not keep_chrome:
                await asyncio.to_thread(self.chrome.close, context.account["id"])
