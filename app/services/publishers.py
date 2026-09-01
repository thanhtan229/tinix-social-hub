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


class Publisher(ABC):
    @abstractmethod
    async def publish(self, context: PublishContext) -> PublishResult:
        raise NotImplementedError


class PreviewPublisher(Publisher):
    """Dry-run-only adapter. It can never report a real publish success."""

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
    def __init__(self, platform: str) -> None:
        self.platform = platform

    async def publish(self, context: PublishContext) -> PublishResult:
        return PublishResult(
            PublishOutcome.UNSUPPORTED,
            f"Nền tảng {self.platform} chưa có publisher đăng thật.",
        )


class PublisherRegistry:
    def __init__(self) -> None:
        self._publishers: dict[str, Publisher] = {}
        self._preview = PreviewPublisher()

    def register(self, platform: str, publisher: Publisher) -> None:
        self._publishers[platform.lower()] = publisher

    def get(self, platform: str, *, dry_run: bool) -> Publisher:
        registered = self._publishers.get(platform.lower())
        if registered:
            return registered
        return self._preview if dry_run else UnsupportedPublisher(platform)
