from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any


class Publisher(ABC):
    @abstractmethod
    async def publish(self, account: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class PreviewPublisher(Publisher):
    """Safe MVP adapter: validates a job without posting to an external platform."""

    async def publish(self, account: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0.2)
        return {
            "mode": "preview",
            "platform": account["platform"],
            "message": "Publisher adapter đã nhận job. Chưa gửi ra mạng xã hội trong bản khung MVP.",
            "payload": payload,
        }


class PublisherRegistry:
    def __init__(self) -> None:
        self._publishers: dict[str, Publisher] = {}
        self._fallback = PreviewPublisher()

    def register(self, platform: str, publisher: Publisher) -> None:
        self._publishers[platform.lower()] = publisher

    def get(self, platform: str) -> Publisher:
        return self._publishers.get(platform.lower(), self._fallback)

