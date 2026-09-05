from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Awaitable, Callable, Protocol


class IdempotencyClass(StrEnum):
    READ_ONLY = "read_only"
    SAFE_RETRY = "safe_retry"
    COMMIT_ONCE = "commit_once"
    VERIFY_ONLY = "verify_only"


class ProviderErrorKind(StrEnum):
    AUTH = "auth"
    CHECKPOINT = "checkpoint"
    VALIDATION = "validation"
    RATE_LIMIT = "rate_limit"
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    UNCONFIRMED = "unconfirmed"


@dataclass(frozen=True, slots=True)
class SettingsField:
    key: str
    label: str
    field_type: str = "text"
    required: bool = False
    default: Any = None
    options: tuple[str, ...] = ()
    visible_when: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FormatConstraints:
    max_caption_length: int | None = None
    min_media: int = 0
    max_media: int = 0
    allowed_media_types: tuple[str, ...] = ()
    max_media_size_bytes: int | None = None
    settings: tuple[SettingsField, ...] = ()


class ChromePlatformAdapter(Protocol):
    """Runtime boundary for a Chrome-only platform integration.

    Implementations own selectors and Page Objects. Generic scheduling code must
    not inspect platform DOM or call a social-network publishing API.
    """

    platform_id: str
    selector_version: str
    max_concurrent_jobs: int

    def constraints(self, content_format: str) -> FormatConstraints: ...

    def validate(self, payload: dict[str, Any], settings: dict[str, Any]) -> list[str]: ...

    async def detect_login(self, page: Any) -> str: ...

    async def discover_targets(self, page: Any) -> list[dict[str, Any]]: ...

    async def publish(
        self,
        context: Any,
        is_cancelled: Callable[[], Awaitable[bool]],
    ) -> Any: ...


class OfficialApiAdapter(Protocol):
    """Transport-neutral boundary for a provider's official publishing API."""

    platform_id: str
    publication_transport: str
    provider_version: str
    max_concurrent_jobs: int
    supported_formats: frozenset[str]

    def validate(self, payload: dict[str, Any], settings: dict[str, Any]) -> list[str]: ...

    async def publish(self, context: Any) -> Any: ...

    async def verify(self, external_id: str, context: Any) -> Any: ...
