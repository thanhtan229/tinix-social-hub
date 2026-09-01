from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from playwright.async_api import Page

from app.automation.facebook import selectors


@dataclass(frozen=True, slots=True)
class FacebookTarget:
    external_id: str
    name: str
    url: str


class FacebookPagesPage:
    MANAGED_PAGES_URL = "https://www.facebook.com/pages/?category=your_pages"
    RESERVED_PATHS = {
        "", "pages", "groups", "events", "friends", "marketplace", "watch", "gaming",
        "settings", "help", "privacy", "login", "checkpoint", "notifications", "messages",
    }
    FORBIDDEN_NAMES = {
        "thông tin liên hệ", "chi tiết", "giới thiệu", "contact info", "details", "about",
        "xem thêm", "see more", "trang", "pages",
    }

    def __init__(self, page: Page) -> None:
        self.page = page

    @classmethod
    def parse_links(cls, links: list[dict[str, str]]) -> list[FacebookTarget]:
        targets: dict[str, FacebookTarget] = {}
        for link in links:
            name = " ".join((link.get("text") or "").split()).strip()
            href = (link.get("href") or "").strip()
            if not name or name.casefold() in cls.FORBIDDEN_NAMES:
                continue
            parsed = urlparse(href)
            if not parsed.netloc.lower().endswith("facebook.com"):
                continue
            query_id = parse_qs(parsed.query).get("id", [None])[0]
            segments = [segment for segment in parsed.path.split("/") if segment]
            first = segments[0].lower() if segments else ""
            if not query_id and first in cls.RESERVED_PATHS:
                continue
            if query_id and query_id.isdigit():
                external_id = query_id
                canonical = f"https://www.facebook.com/profile.php?id={query_id}"
            else:
                slug = re.sub(r"[^a-zA-Z0-9._-]", "", segments[0]) if segments else ""
                if not slug:
                    continue
                external_id = f"url:{slug.casefold()}"
                canonical = f"https://www.facebook.com/{slug}"
            existing = targets.get(external_id)
            if existing is None or len(name) > len(existing.name):
                targets[external_id] = FacebookTarget(external_id, name[:200], canonical)
        return sorted(targets.values(), key=lambda target: target.name.casefold())

    async def discover(self) -> list[FacebookTarget]:
        await self.page.goto(self.MANAGED_PAGES_URL, wait_until="domcontentloaded", timeout=30_000)
        await self.page.wait_for_timeout(1500)
        links = await self.page.locator(selectors.PAGE_LINKS).evaluate_all(
            "els => els.map(a => ({href: a.href || '', text: (a.innerText || a.textContent || '').trim()}))"
        )
        return self.parse_links(links)

