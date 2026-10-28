from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone

from app.services.instagram_accounts import InstagramAccountService


def _iso(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


class _Connections:
    def __init__(self, items: list[dict]) -> None:
        self.items = items
        self.transports: list[str | None] = []

    def list(self, *, account_id=None, transport=None):
        self.transports.append(transport)
        return list(self.items)


class InstagramTokenRefreshTests(unittest.TestCase):
    def _service(self, items: list[dict], failing: set[str] | None = None):
        service = InstagramAccountService.__new__(InstagramAccountService)
        service.connections = _Connections(items)
        service.refreshed: list[str] = []
        failing = failing or set()

        async def refresh_connection(connection_id, account_id=None):
            if connection_id in failing:
                raise RuntimeError("Instagram token đã hết hạn hoặc thiếu hạn dùng; hãy kết nối lại.")
            service.refreshed.append(connection_id)
            return {}

        service.refresh_connection = refresh_connection
        return service

    def test_refreshes_only_connections_expiring_within_seven_days(self) -> None:
        items = [
            {"id": "soon", "provider": "instagram", "status": "connected", "account_id": "a", "expires_at": _iso(3)},
            {"id": "later", "provider": "instagram", "status": "connected", "account_id": "a", "expires_at": _iso(40)},
            {"id": "other", "provider": "meta", "status": "connected", "account_id": "a", "expires_at": _iso(1)},
            {"id": "off", "provider": "instagram", "status": "disconnected", "account_id": "a", "expires_at": _iso(1)},
        ]
        service = self._service(items)
        summary = asyncio.run(service.refresh_due_connections())
        self.assertEqual(service.refreshed, ["soon"])
        self.assertEqual(summary, {"checked": 2, "refreshed": 1, "failed": 0})
        self.assertEqual(service.connections.transports, ["official_api"])

    def test_one_failing_connection_does_not_stop_the_others(self) -> None:
        items = [
            {"id": "bad", "provider": "instagram", "status": "connected", "account_id": "a", "expires_at": _iso(1)},
            {"id": "good", "provider": "instagram", "status": "connected", "account_id": "b", "expires_at": _iso(2)},
        ]
        service = self._service(items, failing={"bad"})
        summary = asyncio.run(service.refresh_due_connections())
        self.assertEqual(service.refreshed, ["good"])
        self.assertEqual(summary, {"checked": 2, "refreshed": 1, "failed": 1})

    def test_connection_without_expiry_is_skipped(self) -> None:
        items = [{"id": "none", "provider": "instagram", "status": "connected", "account_id": "a", "expires_at": None}]
        service = self._service(items)
        summary = asyncio.run(service.refresh_due_connections())
        self.assertEqual(service.refreshed, [])
        self.assertEqual(summary["refreshed"], 0)


if __name__ == "__main__":
    unittest.main()
