from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.config import Settings


class AIConfigurationError(RuntimeError):
    pass


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.ai_api_key and self.settings.ai_base_url and self.settings.ai_model)

    async def generate(self, prompt: str, system: str = "Bạn là trợ lý nội dung mạng xã hội.") -> str:
        if not self.configured:
            raise AIConfigurationError("Chưa cấu hình TINIX_AI_API_KEY trong file .env.")
        headers = {"Authorization": f"Bearer {self.settings.ai_api_key}"}
        body = {
            "model": self.settings.ai_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        last_error: Exception | None = None
        for attempt in range(self.settings.ai_max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.settings.ai_timeout_seconds) as client:
                    response = await client.post(f"{self.settings.ai_base_url}/chat/completions", headers=headers, json=body)
                    response.raise_for_status()
                    data: dict[str, Any] = response.json()
                    return data["choices"][0]["message"]["content"]
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt < self.settings.ai_max_retries:
                    await asyncio.sleep(min(2 ** attempt, 5))
        raise RuntimeError(f"AI request thất bại: {type(last_error).__name__}") from last_error

