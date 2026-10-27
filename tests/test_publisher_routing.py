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

    def get(self, connection_id):
        return next((item for item in self.items if item.get("id") == connection_id), None)


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

    def test_format_specific_api_is_selected_when_chrome_cannot_publish_format(self) -> None:
        self.chrome.supported_formats = frozenset({"post"})
        api = StubPublisher()
        api.provider_id = "youtube"
        api.publication_transport = "official_api"
        api.supported_formats = frozenset({"reel"})
        self.registry.register("youtube", api, transport="official_api")
        connection = {"id": "c1", "account_id": "a1", "provider": "youtube", "status": "connected"}
        route = PublisherRouter(self.registry, StubConnections([connection])).resolve(
            self.account, content_format="reel", preference="chrome_preferred",
        )
        self.assertEqual((route.transport, route.publisher, route.connection_id), ("official_api", api, "c1"))

    def test_format_with_no_supporting_transport_is_not_routed_to_chrome(self) -> None:
        self.chrome.supported_formats = frozenset({"post"})
        route = PublisherRouter(self.registry, StubConnections([])).resolve(
            self.account, content_format="reel", preference="chrome_preferred",
        )
        self.assertEqual(route.reason, "no_eligible_transport")
        self.assertEqual(route.transport, "chrome")

    def test_official_route_is_bound_to_target_and_frozen_scopes(self) -> None:
        api = StubPublisher()
        api.publication_transport = "official_api"
        api.provider_id = "youtube"
        api.supported_formats = frozenset({"video"})
        self.registry.register("youtube", api, transport="official_api")
        connection = {
            "id": "c1", "account_id": "a1", "provider": "youtube", "status": "connected",
            "external_account_id": "UC_target", "scopes": ["youtube.upload", "youtube.readonly"],
        }
        router = PublisherRouter(self.registry, StubConnections([connection]))
        initial = router.resolve(
            self.account, content_format="video", preference="official_api_preferred",
            target_external_id="UC_target",
        )
        self.assertEqual(initial.reason, "selected_by_official_api_preferred")
        frozen = router.resolve(
            self.account, content_format="video", frozen_transport="official_api",
            frozen_connection_id="c1", frozen_connection_scopes_hash=initial.connection_scopes_hash,
            target_external_id="UC_target",
        )
        self.assertEqual(frozen.reason, "transport_frozen_on_release")

        connection["scopes"] = ["youtube.upload"]
        changed_scope = router.resolve(
            self.account, content_format="video", frozen_transport="official_api",
            frozen_connection_id="c1", frozen_connection_scopes_hash=initial.connection_scopes_hash,
            target_external_id="UC_target",
        )
        changed_target = router.resolve(
            self.account, content_format="video", frozen_transport="official_api",
            frozen_connection_id="c1", frozen_connection_scopes_hash=router._scopes_hash(connection),
            target_external_id="UC_other",
        )
        self.assertEqual(changed_scope.reason, "frozen_connection_unavailable")
        self.assertEqual(changed_target.reason, "frozen_connection_unavailable")

    def test_api_preferred_connection_must_match_target(self) -> None:
        api = StubPublisher()
        api.publication_transport = "official_api"
        api.provider_id = "youtube"
        api.supported_formats = frozenset({"video"})
        self.registry.register("youtube", api, transport="official_api")
        connections = StubConnections([{
            "id": "c1", "account_id": "a1", "provider": "youtube", "status": "connected",
            "external_account_id": "UC_other",
        }])
        route = PublisherRouter(self.registry, connections).resolve(
            self.account, content_format="video", preference="official_api_only",
            target_external_id="UC_target",
        )
        self.assertEqual(route.reason, "no_eligible_transport")
        self.assertEqual(route.transport, "official_api")

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
