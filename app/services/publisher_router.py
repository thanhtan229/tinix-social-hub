from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
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
    connection_scopes_hash: str | None = None
    provider_target_binding_id: str | None = None
    provider_target_external_id: str | None = None


class PublisherRouter:
    """Select a publisher before execution and keep fallback decisions explicit."""

    def __init__(self, registry: PublisherRegistry, connections: Any | None = None, target_connections: Any | None = None) -> None:
        self.registry = registry
        self.connections = connections
        self.target_connections = target_connections

    def _official_connection(
        self, account_id: str, provider: str, target_external_id: str | None = None,
    ) -> dict[str, Any] | None:
        if self.connections is None:
            return None
        items = self.connections.list(account_id=account_id, transport="official_api")
        return next((item for item in items
                     if item.get("status") == "connected" and item.get("provider") == provider
                     and (not target_external_id or item.get("external_account_id") == target_external_id)), None)

    @staticmethod
    def _scopes_hash(connection: dict[str, Any] | None) -> str | None:
        if not connection:
            return None
        scopes = sorted(set(connection.get("scopes") or []))
        metadata = connection.get("refresh_metadata") or {}
        if connection.get("provider") == "meta" and (
            metadata.get("auth_method") or metadata.get("credential_revision")
        ):
            try:
                credential_revision = int(metadata.get("credential_revision") or 0)
            except (TypeError, ValueError):
                credential_revision = 0
            frozen_identity = {
                "scopes": scopes,
                "auth_method": metadata.get("auth_method") or "legacy",
                "credential_revision": credential_revision,
            }
            value = json.dumps(frozen_identity, separators=(",", ":"), sort_keys=True)
        else:
            # Preserve hashes for existing releases and non-Meta providers.
            value = json.dumps(scopes, separators=(",", ":"))
        return hashlib.sha256(value.encode()).hexdigest()

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
        frozen_connection_id: str | None = None,
        frozen_connection_scopes_hash: str | None = None,
        target_external_id: str | None = None,
        target_id: str | None = None,
        frozen_provider_target_binding_id: str | None = None,
        frozen_provider_target_external_id: str | None = None,
    ) -> ResolvedPublisher:
        platform = str(account["platform"]).strip().lower()
        selected_preference = RoutingPreference(preference or account.get("routing_preference") or RoutingPreference.CHROME_PREFERRED)

        if frozen_transport:
            publisher = self.registry.get(platform, dry_run=dry_run, transport=frozen_transport)
            if frozen_transport == "official_api":
                connection = None
                if self.connections is not None and frozen_connection_id:
                    getter = getattr(self.connections, "get", None)
                    if getter:
                        connection = getter(frozen_connection_id)
                    else:
                        connection = next(
                            (item for item in self.connections.list(account_id=str(account["id"]), transport="official_api")
                             if item.get("id") == frozen_connection_id),
                            None,
                        )
                connection_valid = bool(
                    connection
                    and connection.get("account_id") == str(account["id"])
                    and connection.get("provider") == str(getattr(publisher, "provider_id", platform))
                    and connection.get("status") == "connected"
                    and (str(getattr(publisher, "provider_id", platform)) == "meta"
                         or not target_external_id or connection.get("external_account_id") == target_external_id)
                    and (not frozen_connection_scopes_hash or self._scopes_hash(connection) == frozen_connection_scopes_hash)
                )
                binding = None
                if str(getattr(publisher, "provider_id", platform)) == "meta":
                    binding = self.target_connections.get(frozen_provider_target_binding_id) if self.target_connections and frozen_provider_target_binding_id else None
                    connection_valid = bool(connection_valid and binding
                        and binding.get("connection_id") == frozen_connection_id
                        and binding.get("target_id") == target_id
                        and binding.get("external_target_id") == frozen_provider_target_external_id
                        and binding.get("status") == "connected")
                return ResolvedPublisher(
                    publisher, frozen_transport,
                    "transport_frozen_on_release" if connection_valid else "frozen_connection_unavailable",
                    connection_id=frozen_connection_id,
                    provider=str(getattr(publisher, "provider_id", platform)),
                    connection_scopes_hash=self._scopes_hash(connection),
                    provider_target_binding_id=binding.get("id") if binding else None,
                    provider_target_external_id=binding.get("external_target_id") if binding else None,
                )
            return ResolvedPublisher(publisher, frozen_transport, "transport_frozen_on_release")

        api_publisher = self.registry.get(platform, dry_run=dry_run, transport="official_api")
        api_provider = str(getattr(api_publisher, "provider_id", platform))
        binding = None
        if api_provider == "meta" and self.target_connections and target_id:
            binding = self.target_connections.for_target(target_id)
        connection = None
        if binding and self.connections:
            connection = self.connections.get(binding["connection_id"])
            if connection and (connection.get("account_id") != str(account["id"]) or connection.get("provider") != api_provider or connection.get("status") != "connected"):
                connection = None
        elif api_provider != "meta":
            connection = self._official_connection(str(account["id"]), api_provider, target_external_id)
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
                    connection_scopes_hash=self._scopes_hash(connection),
                    provider_target_binding_id=binding.get("id") if binding else None,
                    provider_target_external_id=binding.get("external_target_id") if binding else None,
                )
            if transport == "chrome" and chrome_ready:
                chrome_publisher = self.registry.get(platform, dry_run=dry_run, transport=transport)
                if self._supports(chrome_publisher, content_format):
                    return ResolvedPublisher(
                        chrome_publisher,
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
            connection_scopes_hash=self._scopes_hash(connection),
            provider_target_binding_id=binding.get("id") if binding else None,
            provider_target_external_id=binding.get("external_target_id") if binding else None,
        )

    @staticmethod
    def can_fallback(*, error_kind: ProviderErrorKind, commit_possible: bool) -> bool:
        if commit_possible:
            return False
        return error_kind in {ProviderErrorKind.VALIDATION, ProviderErrorKind.PERMANENT}
