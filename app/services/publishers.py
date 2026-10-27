from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Awaitable, Callable


class PublishOutcome(StrEnum):
    PUBLISHED = "published"
    DRY_RUN_READY = "dry_run_ready"
    UNSUPPORTED = "unsupported"
    LOGIN_REQUIRED = "login_required"
    CHECKPOINT = "checkpoint"
    UNKNOWN_RESULT = "unknown_result"


@dataclass(slots=True)
class PublishResult:
    outcome: PublishOutcome
    message: str
    post_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PublishContext:
    job: dict[str, Any]
    account: dict[str, Any]
    payload: dict[str, Any]
    is_cancelled: Callable[[], Awaitable[bool]]
    transition: Callable[[str, str, bool], Awaitable[None]]
    record_provider_request: Callable[[str, bool], Awaitable[None]] | None = None
    connection_id: str | None = None


class Publisher(ABC):
    platform_id = "unknown"
    publication_transport = "chrome"
    selector_version = "unversioned"
    max_concurrent_jobs = 1

    @abstractmethod
    async def publish(self, context: PublishContext) -> PublishResult:
        raise NotImplementedError


class PreviewPublisher(Publisher):
    """Dry-run-only adapter. It can never report a real publish success."""

    publication_transport = "preview"

    async def publish(self, context: PublishContext) -> PublishResult:
        if not context.job.get("dry_run"):
            return PublishResult(PublishOutcome.UNSUPPORTED, "PreviewPublisher chỉ được dùng cho dry-run.")
        if await context.is_cancelled():
            raise asyncio.CancelledError
        await asyncio.sleep(0.05)
        return PublishResult(
            PublishOutcome.DRY_RUN_READY,
            "Dry-run đã kiểm tra payload. Chưa thao tác đăng lên nền tảng.",
            metadata={"platform": context.account["platform"]},
        )


class UnsupportedPublisher(Publisher):
    def __init__(self, platform: str, transport: str = "chrome") -> None:
        self.platform = platform
        self.platform_id = platform
        self.publication_transport = transport
        self.selector_version = "scaffold"

    async def publish(self, context: PublishContext) -> PublishResult:
        return PublishResult(
            PublishOutcome.UNSUPPORTED,
            f"Nền tảng {self.platform} chưa có publisher đăng thật.",
        )


class InstagramPublisherStub(UnsupportedPublisher):
    def __init__(self) -> None:
        super().__init__("instagram")


class TikTokPublisherStub(UnsupportedPublisher):
    def __init__(self) -> None:
        super().__init__("tiktok")


class YouTubePublisherStub(UnsupportedPublisher):
    def __init__(self) -> None:
        super().__init__("youtube")


class PublisherRegistry:
    def __init__(self) -> None:
        self._publishers: dict[tuple[str, str], Publisher] = {}
        self._preview = PreviewPublisher()

    def register(self, platform: str, publisher: Publisher, *, transport: str | None = None) -> None:
        normalized = platform.lower()
        selected_transport = (transport or getattr(publisher, "publication_transport", "chrome")).strip().lower()
        if selected_transport not in {"chrome", "official_api"}:
            raise ValueError(f"Publication transport không hợp lệ: {selected_transport}")
        publisher.platform_id = normalized
        publisher.publication_transport = selected_transport
        self._publishers[(normalized, selected_transport)] = publisher

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "platform": platform,
                "transport": publisher.publication_transport,
                "selector_version": publisher.selector_version,
                "max_concurrent_jobs": publisher.max_concurrent_jobs,
                "implementation": type(publisher).__name__,
            }
            for (platform, _transport), publisher in sorted(self._publishers.items())
        ]

    def has(self, platform: str, transport: str = "chrome") -> bool:
        return (platform.strip().lower(), transport.strip().lower()) in self._publishers

    def transports(self, platform: str) -> tuple[str, ...]:
        normalized = platform.strip().lower()
        return tuple(sorted(transport for item_platform, transport in self._publishers if item_platform == normalized))

    def get(self, platform: str, *, dry_run: bool, transport: str = "chrome") -> Publisher:
        normalized_transport = transport.strip().lower()
        registered = self._publishers.get((platform.lower(), normalized_transport))
        if registered:
            return registered
        if dry_run and normalized_transport == "chrome":
            return self._preview
        return UnsupportedPublisher(platform, normalized_transport)
