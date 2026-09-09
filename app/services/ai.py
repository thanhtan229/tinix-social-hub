from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.core.config import Settings

logger = logging.getLogger(__name__)


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
    image_prompt: str = ""
    media_suggestions: list[str] = Field(default_factory=list, max_length=30)
    warnings: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # 1. Alias lookup for image_prompt
            if not data.get("image_prompt"):
                for key in ("imagePrompt", "image_description", "prompt_tao_anh", "prompt", "image", "image_idea"):
                    val = data.get(key)
                    if isinstance(val, str) and val.strip():
                        data["image_prompt"] = val.strip()
                        break
            # 2. If still empty, synthesize a descriptive prompt from caption or topic
            if not data.get("image_prompt"):
                topic = data.get("topic") or data.get("summary") or ""
                variants = data.get("platform_variants") or {}
                caption = ""
                if isinstance(variants, dict):
                    for v in variants.values():
                        if isinstance(v, dict) and v.get("caption"):
                            caption = v["caption"][:160]
                            break
                base = caption or topic or "social media promotional content"
                data["image_prompt"] = f"A professional, vibrant commercial photograph representing: {base}. Cinematic lighting, highly detailed, realistic."
        return data


@dataclass(slots=True)
class AIResult:
    content: StructuredContent
    usage: dict[str, int | None]
    latency_ms: int
    raw_model: str


@dataclass(slots=True)
class AIImageResult:
    image_bytes: bytes
    mime_type: str
    source_model: str
    fallback_used: bool = False


class AIProvider(ABC):
    name = "abstract"

    @property
    @abstractmethod
    def configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def generate_structured(self, prompt: str, system: str) -> AIResult:
        raise NotImplementedError

    @abstractmethod
    async def generate_image(self, prompt: str) -> AIImageResult:
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

    async def _fallback_pollinations(self, prompt: str) -> AIImageResult:
        encoded = urllib.parse.quote(prompt.strip()[:400], safe="")
        headers = {
            "User-Agent": "TinixSocialHub/1.0 (Desktop Automation Studio)",
            "Accept": "image/jpeg,image/png,image/*,*/*",
        }
        seed = int(time.time() * 1000) % 1_000_000

        models_to_try = [
            ("flux", "FLUX (Pollinations AI)"),
            ("turbo", "Turbo (Pollinations AI)"),
        ]

        last_error: Exception | None = None
        for model_name, display_name in models_to_try:
            url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&seed={seed}&model={model_name}"
            try:
                async with httpx.AsyncClient(timeout=25.0, headers=headers, follow_redirects=True) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200 and len(resp.content) > 500:
                        content_type = resp.headers.get("content-type", "image/jpeg")
                        if "image" not in content_type:
                            content_type = "image/jpeg"
                        return AIImageResult(
                            image_bytes=resp.content,
                            mime_type=content_type,
                            source_model=display_name,
                            fallback_used=True,
                        )
                    logger.warning("Pollinations model %s returned HTTP %s (len: %d)", model_name, resp.status_code, len(resp.content))
            except Exception as exc:
                last_error = exc
                logger.warning("Pollinations model %s request failed: %s", model_name, exc)

        raise AIError(
            "image_fallback_failed",
            f"Dịch vụ tạo ảnh miễn phí FLUX tạm thời không phản hồi ({last_error or 'HTTP error'}). Vui lòng thử lại sau giây lát.",
            retryable=True,
        )

    async def generate_image(self, prompt: str) -> AIImageResult:
        model = getattr(self.settings, "ai_image_model", "") or ""
        if not model:
            if "generativelanguage.googleapis.com" in self.settings.ai_base_url:
                model = "gemini-2.5-flash-image"
            elif "openai.com" in self.settings.ai_base_url:
                model = "dall-e-3"
            else:
                model = "gemini-2.5-flash-image"

        if self.configured:
            body = {
                "model": model,
                "prompt": prompt,
                "n": 1,
                "response_format": "b64_json",
            }
            try:
                primary_timeout = min(float(self.settings.ai_timeout_seconds), 15.0)
                client = self._get_client()
                response = await client.post("/images/generations", json=body, timeout=primary_timeout)
                if response.status_code == 200:
                    data = response.json()
                    items = data.get("data") or []
                    if items:
                        first = items[0]
                        if "b64_json" in first:
                            img_bytes = base64.b64decode(first["b64_json"])
                            return AIImageResult(
                                image_bytes=img_bytes,
                                mime_type="image/png",
                                source_model=model,
                                fallback_used=False,
                            )
                        if "url" in first:
                            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as dl_client:
                                img_resp = await dl_client.get(first["url"])
                                if img_resp.status_code == 200:
                                    return AIImageResult(
                                        image_bytes=img_resp.content,
                                        mime_type=img_resp.headers.get("content-type", "image/png"),
                                        source_model=model,
                                        fallback_used=False,
                                    )
                else:
                    err_snippet = response.text[:200]
                    if response.status_code == 429 and "limit: 0" in err_snippet:
                        logger.info("Gemini image free-tier quota is 0 (billing required). Switching to FLUX.")
                    else:
                        logger.info("Primary image model (%s) returned HTTP %s: %s. Switching to FLUX.", model, response.status_code, err_snippet)
            except Exception as exc:
                logger.info("Primary image model (%s) failed: %s. Switching to FLUX.", model, exc)

        try:
            return await self._fallback_pollinations(prompt)
        except Exception as exc:
            if isinstance(exc, AIError):
                raise
            raise AIError("image_generation_failed", f"Không thể tạo ảnh từ prompt: {exc}") from exc

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
            image_prompt="A modern digital marketing illustration with vibrant gradients",
        )

    @property
    def configured(self) -> bool:
        return True

    async def generate_structured(self, prompt: str, system: str) -> AIResult:
        await asyncio.sleep(0)
        return AIResult(self.result, {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, 1, "mock")

    async def generate_image(self, prompt: str) -> AIImageResult:
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (200, 200), color=(50, 150, 200)).save(buf, "PNG")
        return AIImageResult(image_bytes=buf.getvalue(), mime_type="image/png", source_model="mock", fallback_used=False)

