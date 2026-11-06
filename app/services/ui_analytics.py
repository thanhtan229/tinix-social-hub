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
        "likes": '[aria-label*="reaction" i],[aria-label*="Like:" i],[aria-label*="Thích:" i]',
        "comments": '[aria-label*="comment" i]', "shares": '[aria-label*="share" i],[aria-label*="chia sẻ" i]',
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


FACEBOOK_METRIC_SCOPE_INDEX_SCRIPT = """caption => {
    const elements = [...document.querySelectorAll('div')];
    const matches = elements
        .filter(element => (element.innerText || '').includes(caption))
        .sort((left, right) => left.innerText.length - right.innerText.length);
    const hasPostAction = element => [...element.querySelectorAll('[aria-label]')].some(node =>
        /bày tỏ cảm xúc.*bài viết|react to (?:this|the) post|like (?:this|the) post/i.test(
            node.getAttribute('aria-label') || ''
        )
    );
    for (const match of matches) {
        let parent = match;
        while (parent && parent !== document.body) {
            if (hasPostAction(parent))
                return elements.indexOf(parent);
            parent = parent.parentElement;
        }
    }
    return -1;
}"""

class AnalyticsCollectionError(RuntimeError):
    pass


def parse_visible_number(value: str) -> float | None:
    normalized = value.strip().lower().replace("\u00a0", " ")
    suffixes = r"k|m|b|ngh\u00ecn|tri\u1ec7u|t\u1ef7"
    tokens = list(re.finditer(rf"\d+(?:[.,]\d+)*(?:\s*(?:{suffixes}))?", normalized))
    if not tokens:
        return None

    metric_context = re.compile(
        r"\b(?:likes?|reactions?|comments?|shares?|views?|subscribers?)\b|th\u00edch|"
        r"l\u01b0\u1ee3t\s+(?:th\u00edch|xem)|chia\s+s\u1ebb"
    )
    candidates = []
    for token in tokens:
        raw_token = token.group(0).strip()
        suffix_match = re.search(rf"\s*({suffixes})$", raw_token)
        suffix = suffix_match.group(1) if suffix_match else ""
        raw = raw_token[:suffix_match.start()].strip() if suffix_match else raw_token
        number = _parse_localized_number(raw)
        if number is None:
            continue
        context_start = max(0, token.start() - 48)
        context_end = min(len(normalized), token.end() + 48)
        context = normalized[context_start:context_end]
        contextual = bool(suffix or metric_context.search(context))
        exact_value = normalized.strip() == raw_token
        if contextual or exact_value:
            multipliers = {
                "k": 1e3, "ngh\u00ecn": 1e3,
                "m": 1e6, "tri\u1ec7u": 1e6,
                "b": 1e9, "t\u1ef7": 1e9,
            }
            token_start = token.start() - context_start
            token_end = token.end() - context_start
            label_before_count = bool(re.search(
                metric_context.pattern + r"\s*[:：]\s*$", normalized[:token.start()],
            ))
            distance = 0 if suffix else min(
                (
                    max(match.start() - token_end, token_start - match.end(), 0)
                    for match in metric_context.finditer(context)
                ),
                default=10_000,
            )
            candidates.append((0 if label_before_count else 1, distance, token.start(), number * multipliers.get(suffix, 1)))

    if not candidates:
        return None
    return min(candidates)[3]


def _parse_localized_number(raw: str) -> float | None:
    if not re.fullmatch(r"\d+(?:[.,]\d+)*", raw):
        return None
    if "." in raw and "," in raw:
        decimal_separator = "." if raw.rfind(".") > raw.rfind(",") else ","
        thousands_separator = "," if decimal_separator == "." else "."
        integer, decimal = raw.rsplit(decimal_separator, 1)
        grouping = rf"\d{{1,3}}(?:{re.escape(thousands_separator)}\d{{3}})+"
        if not re.fullmatch(grouping, integer):
            return None
        return float(integer.replace(thousands_separator, "") + "." + decimal)

    separator = "." if "." in raw else "," if "," in raw else ""
    if not separator:
        return float(raw)
    parts = raw.split(separator)
    if len(parts) > 2:
        if not (1 <= len(parts[0]) <= 3 and all(len(part) == 3 for part in parts[1:])):
            return None
        return float("".join(parts))
    left, right = parts
    if len(right) == 3:
        return float(left + right)
    return float(f"{left}.{right}")

def parse_metric_value(text_content: str | None, aria_label: str | None = None) -> float | None:
    """Parse a metric element, ignoring labels that contain no visible count."""
    value = " ".join(filter(None, (text_content, aria_label)))
    return parse_visible_number(value)


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
                metric_scope=None if release["platform"]=="facebook" else page
                if release["platform"]=="facebook":
                    caption=str((release.get("payload_snapshot") or {}).get("caption") or "").strip()
                    if caption:
                        scope_index=-1
                        for attempt in range(20):
                            scope_index=await page.evaluate(FACEBOOK_METRIC_SCOPE_INDEX_SCRIPT,caption)
                            if scope_index>=0:break
                            if attempt<19:await page.wait_for_timeout(500)
                        if scope_index>=0:
                            metric_scope=page.locator("div").nth(scope_index)
                values={}
                for key,selector in METRIC_SELECTORS.get(release["platform"],{}).items():
                    if metric_scope is None:continue
                    locator=metric_scope.locator(selector).first
                    if not await locator.count():continue
                    parsed=parse_metric_value(await locator.text_content(),await locator.get_attribute("aria-label"))
                    if parsed is not None:values[key]=parsed
                # Diagnostic only, read while the page is still open: labels with digits, to tune selectors.
                observed=[] if values else await page.evaluate("""() => [...document.querySelectorAll('[aria-label]')]
                    .map(e => e.getAttribute('aria-label')).filter(t => /\\d/.test(t)).slice(0, 15)""")
            if not values:
                await asyncio.to_thread(self.analytics.finish_run,run_id,"unsupported",0,"UI hiện không hiển thị metric được hỗ trợ.")
                return {"status":"unsupported","message":"UI hiện không hiển thị metric được hỗ trợ.","metrics":[],
                        "observed_labels":[str(label)[:120] for label in observed]}
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

    async def collect_tracked_post(self, post_id: str) -> dict[str, Any]:
        tracked = await asyncio.to_thread(self.analytics.get_tracked_post, post_id)
        if not tracked:
            raise KeyError(post_id)
        if tracked["platform"] != "facebook":
            raise AnalyticsCollectionError("Thu thập Chrome cho bài có sẵn hiện chỉ hỗ trợ Facebook.")
        self._validate_url("facebook", tracked["external_url"])
        account = await asyncio.to_thread(self.accounts.get, tracked["account_id"])
        if not account:
            raise AnalyticsCollectionError("Account của Page không còn tồn tại.")
        publisher = self.publishers.get("facebook", dry_run=True)
        source = f"ui_chrome:{getattr(publisher, 'selector_version', 'unknown')}"
        run_id = await asyncio.to_thread(self.analytics.start_tracked_post_run, post_id, source)
        try:
            chrome = await publisher.chrome_ready(account) if isinstance(publisher, ChromeWebPublisher) else await publisher._chrome_ready(account)
            async with BrowserSession(chrome["port"]) as session:
                page = await session.page()
                await page.goto(tracked["external_url"], wait_until="domcontentloaded", timeout=30_000)
                if isinstance(publisher, ChromeWebPublisher) and await publisher.detect_login(page) != "logged_in":
                    raise AnalyticsCollectionError("Phiên Chrome cần đăng nhập/checkpoint.")
                await page.wait_for_timeout(1_000)
                title = str(tracked.get("title") or "").strip()
                scope_index = -1
                if title:
                    for attempt in range(20):
                        scope_index = await page.evaluate(FACEBOOK_METRIC_SCOPE_INDEX_SCRIPT, title)
                        if scope_index >= 0:
                            break
                        if attempt < 19:
                            await page.wait_for_timeout(500)
                scope = page.locator("div").nth(scope_index) if scope_index >= 0 else None
                values: dict[str, float] = {}
                if scope is not None:
                    for key, selector in METRIC_SELECTORS["facebook"].items():
                        locator = scope.locator(selector)
                        for index in range(await locator.count()):
                            candidate = locator.nth(index)
                            parsed = parse_metric_value(
                                await candidate.text_content(), await candidate.get_attribute("aria-label"),
                            )
                            if parsed is not None:
                                values[key] = parsed
                                break
                observed = [] if values or scope is None else await scope.evaluate("""root => [...root.querySelectorAll('[aria-label]')]
                    .map(e => e.getAttribute('aria-label')).filter(t => /\\d/.test(t)).slice(0, 15)""")
            if not values:
                message = "Facebook không hiển thị metric hỗ trợ cho bài này trong phiên Chrome."
                await asyncio.to_thread(self.analytics.finish_tracked_post_run, run_id, "unsupported", 0, message)
                return {"status": "unsupported", "message": message, "metrics": [],
                        "observed_labels": [str(label)[:120] for label in observed]}
            zone = ZoneInfo("Asia/Bangkok")
            metric_date = datetime.now(timezone.utc).astimezone(zone).date().isoformat()
            metrics = await asyncio.to_thread(
                self.analytics.upsert_tracked_post, post_id, values, metric_date=metric_date,
                timezone_name=zone.key, source=source,
            )
            await asyncio.to_thread(self.analytics.finish_tracked_post_run, run_id, "succeeded", len(values))
            return {"status": "succeeded", "metrics": metrics, "source": source}
        except Exception as exc:
            await asyncio.to_thread(self.analytics.finish_tracked_post_run, run_id, "failed", 0, str(exc))
            raise
