from __future__ import annotations

import unittest

from app.platforms.contracts import ProviderErrorKind
from app.services.publisher_router import PublisherRouter
from app.services.publishers import Publisher, PublisherRegistry


class StubPublisher(Publisher):
    async def publish(self, context):
        raise AssertionError("not executed")


class StubConnections:
    def __init__(self, items):
        self.items = items

    def list(self, **filters):
        return self.items


class PublisherRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.account = {"id": "a1", "platform": "youtube", "routing_preference": "chrome_preferred"}
        self.registry = PublisherRegistry()
        self.chrome = StubPublisher()
        self.registry.register("youtube", self.chrome)

    def test_chrome_remains_default_without_official_connection(self) -> None:
        route = PublisherRouter(self.registry, StubConnections([])).resolve(self.account, content_format="video")
        self.assertEqual(route.transport, "chrome")
        self.assertIs(route.publisher, self.chrome)

    def test_api_preferred_requires_registered_adapter_and_connection(self) -> None:
        api = StubPublisher()
        api.publication_transport = "official_api"
        api.supported_formats = frozenset({"video"})
        self.registry.register("youtube", api)
        connections = StubConnections([{"id": "c1", "provider": "youtube", "status": "connected"}])
        route = PublisherRouter(self.registry, connections).resolve(
            self.account, content_format="video", preference="official_api_preferred",
        )
        self.assertEqual((route.transport, route.connection_id), ("official_api", "c1"))

    def test_api_only_never_silently_uses_chrome(self) -> None:
        route = PublisherRouter(self.registry, StubConnections([])).resolve(
            self.account, content_format="video", preference="official_api_only",
        )
        self.assertEqual(route.transport, "official_api")
        self.assertEqual(route.reason, "no_eligible_transport")

    def test_frozen_transport_wins_over_changed_preference(self) -> None:
        route = PublisherRouter(self.registry, StubConnections([])).resolve(
            self.account, preference="official_api_only", frozen_transport="chrome",
        )
        self.assertEqual((route.transport, route.reason), ("chrome", "transport_frozen_on_release"))

    def test_fallback_is_forbidden_after_possible_commit(self) -> None:
        self.assertFalse(PublisherRouter.can_fallback(error_kind=ProviderErrorKind.TRANSIENT, commit_possible=False))
        self.assertFalse(PublisherRouter.can_fallback(error_kind=ProviderErrorKind.VALIDATION, commit_possible=True))
        self.assertTrue(PublisherRouter.can_fallback(error_kind=ProviderErrorKind.VALIDATION, commit_possible=False))


if __name__ == "__main__":
    unittest.main()
