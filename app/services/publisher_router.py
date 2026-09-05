from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.platforms.contracts import ProviderErrorKind
from app.services.publishers import Publisher, PublisherRegistry


class RoutingPreference(StrEnum):
    OFFICIAL_API_PREFERRED = "official_api_preferred"
    CHROME_PREFERRED = "chrome_preferred"
    OFFICIAL_API_ONLY = "official_api_only"
    CHROME_ONLY = "chrome_only"


@dataclass(frozen=True, slots=True)
class ResolvedPublisher:
    publisher: Publisher
    transport: str
    reason: str
    connection_id: str | None = None
    provider: str | None = None


class PublisherRouter:
    """Select a publisher before execution and keep fallback decisions explicit."""

    def __init__(self, registry: PublisherRegistry, connections: Any | None = None) -> None:
        self.registry = registry
        self.connections = connections

    def _official_connection(self, account_id: str, provider: str) -> dict[str, Any] | None:
        if self.connections is None:
            return None
        items = self.connections.list(account_id=account_id, transport="official_api")
        return next((item for item in items
                     if item.get("status") == "connected" and item.get("provider") == provider), None)

    @staticmethod
    def _supports(publisher: Publisher, content_format: str) -> bool:
        formats = getattr(publisher, "supported_formats", None)
        return formats is None or content_format in formats

    def resolve(
        self,
        account: dict[str, Any],
        *,
        content_format: str = "post",
        dry_run: bool = False,
        preference: str | RoutingPreference | None = None,
        frozen_transport: str | None = None,
    ) -> ResolvedPublisher:
        platform = str(account["platform"]).strip().lower()
        selected_preference = RoutingPreference(preference or account.get("routing_preference") or RoutingPreference.CHROME_PREFERRED)

        if frozen_transport:
            publisher = self.registry.get(platform, dry_run=dry_run, transport=frozen_transport)
            return ResolvedPublisher(publisher, frozen_transport, "transport_frozen_on_release")

        api_publisher = self.registry.get(platform, dry_run=dry_run, transport="official_api")
        api_provider = str(getattr(api_publisher, "provider_id", platform))
        connection = self._official_connection(str(account["id"]), api_provider)
        api_ready = bool(
            connection
            and self.registry.has(platform, "official_api")
            and self._supports(api_publisher, content_format)
        )
        chrome_ready = self.registry.has(platform, "chrome")

        order = {
            RoutingPreference.OFFICIAL_API_PREFERRED: ("official_api", "chrome"),
            RoutingPreference.CHROME_PREFERRED: ("chrome", "official_api"),
            RoutingPreference.OFFICIAL_API_ONLY: ("official_api",),
            RoutingPreference.CHROME_ONLY: ("chrome",),
        }[selected_preference]
        for transport in order:
            if transport == "official_api" and api_ready:
                return ResolvedPublisher(
                    api_publisher,
                    transport,
                    f"selected_by_{selected_preference.value}",
                    connection_id=connection.get("id"),
                    provider=connection.get("provider"),
                )
            if transport == "chrome" and chrome_ready:
                return ResolvedPublisher(
                    self.registry.get(platform, dry_run=dry_run, transport=transport),
                    transport,
                    f"selected_by_{selected_preference.value}",
                )

        unavailable = order[0]
        return ResolvedPublisher(
            self.registry.get(platform, dry_run=dry_run, transport=unavailable),
            unavailable,
            "no_eligible_transport",
            connection_id=connection.get("id") if connection else None,
            provider=connection.get("provider") if connection else None,
        )

    @staticmethod
    def can_fallback(*, error_kind: ProviderErrorKind, commit_possible: bool) -> bool:
        if commit_possible:
            return False
        return error_kind in {ProviderErrorKind.VALIDATION, ProviderErrorKind.PERMANENT}
