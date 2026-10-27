from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from app.automation.browser_session import BrowserSession
from app.db.analytics_repositories import AnalyticsRepository
from app.db.publication_repositories import PublicationRepository
from app.db.repositories import AccountRepository
from app.services.publishers import PublisherRegistry
from app.services.web_platform_publisher import ChromeWebPublisher


METRIC_SELECTORS: dict[str, dict[str, str]] = {
    "facebook": {
        "likes": '[aria-label*="reaction" i],[aria-label*="like" i]',
        "comments": '[aria-label*="comment" i]', "shares": '[aria-label*="share" i]',
    },
    "instagram": {
        "likes": 'section span:has-text("likes"),section span:has-text("lượt thích")',
        "comments": 'ul li[role="menuitem"]',
    },
    "tiktok": {
        "likes": '[data-e2e="like-count"]', "comments": '[data-e2e="comment-count"]',
        "shares": '[data-e2e="share-count"]', "views": '[data-e2e="video-views"]',
    },
    "youtube": {
        "views": '#info span:first-child,yt-formatted-string#view-count',
        "likes": '#segmented-like-button button[aria-label],#like-button button[aria-label]',
        "comments": '#count .count-text,#comments-header #count',
    },
    "x": {
        "likes": '[data-testid="like"] span,[data-testid="unlike"] span',
        "comments": '[data-testid="reply"] span',
        "shares": '[data-testid="retweet"] span,[data-testid="unretweet"] span',
        "views": 'a[href$="/analytics"] span',
    },
}


class AnalyticsCollectionError(RuntimeError):
    pass


def parse_visible_number(value: str) -> float | None:
    normalized=value.strip().lower().replace("\u00a0", " ")
    match=re.search(r"(\d+(?:[.,]\d+)?)\s*([kmb]|nghìn|triệu|tỷ)?",normalized)
    if not match:return None
    raw=match.group(1)
    suffix=match.group(2) or ""
    if suffix:
        number=float(raw.replace(",","."));multiplier={"k":1e3,"nghìn":1e3,"m":1e6,"triệu":1e6,"b":1e9,"tỷ":1e9}[suffix]
        return number*multiplier
    number_match=re.search(r"\d[\d.,]*", normalized)
    if not number_match:return None
    raw=number_match.group(0)
    if "." in raw and "," in raw:
        decimal_separator="." if raw.rfind(".") > raw.rfind(",") else ","
        thousands_separator="," if decimal_separator=="." else "."
        return float(raw.replace(thousands_separator, "").replace(decimal_separator, "."))
    separator="." if "." in raw else "," if "," in raw else ""
    if separator and raw.count(separator)==1:
        left,right=raw.split(separator)
        if len(right)==3 and left:
            return float(left+right)
        return float(f"{left}.{right}")
    return float(raw.replace(".","").replace(",",""))


class UIAnalyticsCollector:
    def __init__(
        self, accounts: AccountRepository, publications: PublicationRepository,
        analytics: AnalyticsRepository, publishers: PublisherRegistry,
    ) -> None:
        self.accounts,self.publications,self.analytics,self.publishers=accounts,publications,analytics,publishers

    @staticmethod
    def _validate_url(platform: str, url: str) -> None:
        hosts={
            "facebook": ("facebook.com",), "instagram": ("instagram.com",),
            "tiktok": ("tiktok.com",), "youtube": ("youtube.com", "youtu.be"),
            "x": ("x.com", "twitter.com"),
        }
        parsed=urlparse(url)
        hostname=(parsed.hostname or "").lower()
        if parsed.scheme!="https" or not any(hostname==host or hostname.endswith(f".{host}") for host in hosts[platform]):
            raise AnalyticsCollectionError("URL bài đăng không thuộc đúng nền tảng.")

    async def collect(self, release_id: str) -> dict[str, Any]:
        release=await asyncio.to_thread(self.publications.get_release,release_id)
        if not release:raise KeyError(release_id)
        if not release.get("external_url"):
            return {"status":"unsupported","message":"Release chưa có URL; hãy dùng manual connect.","metrics":[]}
        self._validate_url(release["platform"],release["external_url"])
        account=await asyncio.to_thread(self.accounts.get,release["account_id"])
        if not account:raise AnalyticsCollectionError("Account không còn tồn tại.")
        publisher=self.publishers.get(release["platform"],dry_run=True)
        source=f"ui_chrome:{getattr(publisher,'selector_version','unknown')}"
        run_id=await asyncio.to_thread(self.analytics.start_run,release_id,source)
        try:
            if isinstance(publisher,ChromeWebPublisher):
                chrome=await publisher.chrome_ready(account)
            else:
                chrome=await publisher._chrome_ready(account)
            async with BrowserSession(chrome["port"]) as session:
                page=await session.page();await page.goto(release["external_url"],wait_until="domcontentloaded",timeout=30_000)
                if isinstance(publisher,ChromeWebPublisher):
                    login=await publisher.detect_login(page)
                    if login!="logged_in":raise AnalyticsCollectionError("Phiên Chrome cần đăng nhập/checkpoint.")
                values={}
                for key,selector in METRIC_SELECTORS.get(release["platform"],{}).items():
                    locator=page.locator(selector).first
                    if not await locator.count():continue
                    text=" ".join(filter(None,[await locator.text_content(),await locator.get_attribute("aria-label")]))
                    parsed=parse_visible_number(text)
                    if parsed is not None:values[key]=parsed
            if not values:
                await asyncio.to_thread(self.analytics.finish_run,run_id,"unsupported",0,"UI hiện không hiển thị metric được hỗ trợ.")
                return {"status":"unsupported","message":"UI hiện không hiển thị metric được hỗ trợ.","metrics":[]}
            zone=ZoneInfo(release.get("timezone") or "Asia/Bangkok")
            metric_date=datetime.now(timezone.utc).astimezone(zone).date().isoformat()
            metrics=await asyncio.to_thread(
                self.analytics.upsert,release_id,values,metric_date=metric_date,
                timezone_name=zone.key,source=source,
            )
            await asyncio.to_thread(self.analytics.finish_run,run_id,"succeeded",len(values))
            return {"status":"succeeded","metrics":metrics,"source":source}
        except Exception as exc:
            await asyncio.to_thread(self.analytics.finish_run,run_id,"failed",0,str(exc))
            raise
