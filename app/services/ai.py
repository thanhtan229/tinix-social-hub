from __future__ import annotations

import asyncio
import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings


class AIError(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class AIConfigurationError(AIError):
    def __init__(self, message: str = "Chưa cấu hình TINIX_AI_API_KEY trong file .env.") -> None:
        super().__init__("not_configured", message, False)


class PlatformVariant(BaseModel):
    title: str | None = None
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list, max_length=50)
    cta: str = ""
    pinned_comment: str | None = None
    video_hook: str | None = None
    video_script: str | None = None


class StructuredContent(BaseModel):
    topic: str = ""
    summary: str = ""
    platform_variants: dict[str, PlatformVariant] = Field(default_factory=dict)
    media_suggestions: list[str] = Field(default_factory=list, max_length=30)
    warnings: list[str] = Field(default_factory=list, max_length=30)


@dataclass(slots=True)
class AIResult:
    content: StructuredContent
    usage: dict[str, int | None]
    latency_ms: int
    raw_model: str


class AIProvider(ABC):
    name = "abstract"

    @property
    @abstractmethod
    def configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def generate_structured(self, prompt: str, system: str) -> AIResult:
        raise NotImplementedError

    async def close(self) -> None:
        pass


class OpenAICompatibleProvider(AIProvider):
    name = "openai-compatible"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: httpx.AsyncClient | None = None

    @property
    def configured(self) -> bool:
        return bool(self.settings.ai_api_key and self.settings.ai_base_url and self.settings.ai_model)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.ai_base_url,
                headers={"Authorization": f"Bearer {self.settings.ai_api_key}"},
                timeout=self.settings.ai_timeout_seconds,
            )
        return self._client

    @staticmethod
    def _classify_status(status: int) -> AIError:
        if status in {401, 403}:
            return AIError("authentication", "API key không hợp lệ hoặc không có quyền.")
        if status == 429:
            return AIError("rate_limit", "AI đang giới hạn tần suất; hãy thử lại sau.", True)
        if status in {402, 409}:
            return AIError("quota", "Tài khoản AI không còn quota hoặc credit.")
        if status == 404:
            return AIError("model_not_found", "Không tìm thấy model hoặc endpoint AI.")
        if status >= 500:
            return AIError("provider_unavailable", "Dịch vụ AI tạm thời không khả dụng.", True)
        return AIError("provider_error", f"AI trả HTTP {status}.")

    @staticmethod
    def _parse_json(content: str) -> StructuredContent:
        cleaned = content.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return StructuredContent.model_validate(json.loads(cleaned))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise AIError("invalid_output", "AI trả dữ liệu không đúng structured output.") from exc

    async def generate_structured(self, prompt: str, system: str) -> AIResult:
        if not self.configured:
            raise AIConfigurationError()
        started = time.perf_counter()
        body = {
            "model": self.settings.ai_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        last_error: AIError | None = None
        for attempt in range(self.settings.ai_max_retries + 1):
            try:
                response = await self._get_client().post("/chat/completions", json=body)
                if response.status_code >= 400:
                    raise self._classify_status(response.status_code)
                data: dict[str, Any] = response.json()
                structured = self._parse_json(data["choices"][0]["message"]["content"])
                usage = data.get("usage") or {}
                return AIResult(
                    content=structured,
                    usage={
                        "prompt_tokens": usage.get("prompt_tokens"),
                        "completion_tokens": usage.get("completion_tokens"),
                        "total_tokens": usage.get("total_tokens"),
                    },
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    raw_model=data.get("model", self.settings.ai_model),
                )
            except asyncio.CancelledError:
                raise
            except httpx.TimeoutException as exc:
                last_error = AIError("timeout", "AI request quá thời gian chờ.", True)
                last_error.__cause__ = exc
            except httpx.NetworkError as exc:
                last_error = AIError("network", "Không thể kết nối dịch vụ AI.", True)
                last_error.__cause__ = exc
            except AIError as exc:
                last_error = exc
            except (KeyError, TypeError, ValueError) as exc:
                raise AIError("invalid_response", "AI trả response không hợp lệ.") from exc
            if not last_error.retryable or attempt >= self.settings.ai_max_retries:
                raise last_error
            await asyncio.sleep(min(2 ** attempt, 5))
        raise last_error or AIError("unknown", "AI request thất bại.")

    async def generate(self, prompt: str, system: str = "Bạn là trợ lý nội dung mạng xã hội.") -> str:
        result = await self.generate_structured(prompt, system)
        return result.content.model_dump_json()

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


class MockAIProvider(AIProvider):
    name = "mock"

    def __init__(self, result: StructuredContent | None = None) -> None:
        self.result = result or StructuredContent(
            topic="Mock topic",
            summary="Mock summary",
            platform_variants={"facebook": PlatformVariant(caption="Mock caption", hashtags=["#mock"])},
        )

    @property
    def configured(self) -> bool:
        return True

    async def generate_structured(self, prompt: str, system: str) -> AIResult:
        await asyncio.sleep(0)
        return AIResult(self.result, {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, 1, "mock")

