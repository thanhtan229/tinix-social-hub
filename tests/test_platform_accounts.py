from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.platform_accounts import PlatformAccountService


class Accounts:
    def get(self, account_id):
        return {"id": account_id, "platform": "facebook", "profile_key": "profile-1"}


class Targets:
    def __init__(self, url="https://www.facebook.com/tinix", external_id="url:tinix") -> None:
        self.url = url
        self.external_id = external_id

    def get(self, target_id):
        return {
            "id": target_id, "account_id": "account-1", "platform": "facebook",
            "url": self.url, "external_id": self.external_id,
        }


class Chrome:
    def open(self, _account):
        return {"port": 12345, "state": "starting"}

    def status(self, _account_id):
        return {"port": 12345, "state": "ready"}


class Page:
    def __init__(self) -> None:
        self.visited = None
        self.brought_to_front = False

    async def goto(self, url, **_kwargs):
        self.visited = url

    async def bring_to_front(self):
        self.brought_to_front = True


class Session:
    page_instance = Page()

    def __init__(self, port):
        self.port = port

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def page(self):
        return self.page_instance


class PlatformAccountNavigationTests(unittest.IsolatedAsyncioTestCase):
    def test_youtube_menu_targets_for_discovered_channel_are_stale(self) -> None:
        channel_id = "UCXdYgfzFMIvyE-tgjosC6MQ"
        existing = [
            {"external_id": f"channel/{channel_id}/analytics", "url": f"https://studio.youtube.com/channel/{channel_id}/analytics"},
            {"external_id": f"channel/{channel_id}/content", "url": f"https://studio.youtube.com/channel/{channel_id}/content"},
            {"external_id": "another-channel", "url": "https://www.youtube.com/channel/UCaaaaaaaaaaaaaaaaaaaaaa"},
        ]
        discovered = [{"external_id": channel_id}]
        self.assertEqual(
            PlatformAccountService._stale_youtube_external_ids(existing, discovered),
            {f"channel/{channel_id}/analytics", f"channel/{channel_id}/content"},
        )

    async def test_open_target_uses_owning_account_and_saved_url(self) -> None:
        service = PlatformAccountService(Accounts(), Targets(), Chrome(), object())
        with patch("app.services.platform_accounts.BrowserSession", Session):
            result = await service.open_target("target-1")
        self.assertTrue(result["opened"])
        self.assertEqual(result["account_id"], "account-1")
        self.assertEqual(Session.page_instance.visited, "https://www.facebook.com/tinix")
        self.assertTrue(Session.page_instance.brought_to_front)

    async def test_open_target_rejects_url_outside_platform(self) -> None:
        service = PlatformAccountService(
            Accounts(), Targets("https://example.com/not-a-facebook-page"), Chrome(), object(),
        )
        with self.assertRaises(ValueError):
            await service.open_target("target-1")

    async def test_open_target_rejects_hidden_navigation_item(self) -> None:
        service = PlatformAccountService(
            Accounts(), Targets("https://www.facebook.com/latest", "url:latest"), Chrome(), object(),
        )
        with self.assertRaises(ValueError):
            await service.open_target("target-1")


if __name__ == "__main__":
    unittest.main()
