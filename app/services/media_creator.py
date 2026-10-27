from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.services.ai import AIError


class MediaCreatorClient:
    """Small, loopback-only client for Tinix Media Creator's public local API."""

    def __init__(self, base_url: str, timeout_seconds: int) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Tinix Media Creator chỉ được phép dùng URL HTTP loopback.")
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout_seconds, connect=3.0)

    def _absolute_url(self, value: str) -> str:
        url = urljoin(f"{self.base_url}/", value)
        parsed, expected = urlparse(url), urlparse(self.base_url)
        if parsed.scheme != expected.scheme or parsed.hostname != expected.hostname or parsed.port != expected.port:
            raise AIError("media_creator_invalid_result", "Media Creator trả về URL kết quả không hợp lệ.")
        return url

    @staticmethod
    def _error(response: httpx.Response) -> AIError:
        try:
            detail = response.json().get("error")
        except (ValueError, AttributeError):
            detail = response.text[:300]
        if response.status_code in {408, 429} or response.status_code >= 500:
            return AIError("media_creator_unavailable", f"Tinix Media Creator tạm thời không phản hồi: {detail or response.status_code}", True)
        return AIError("media_creator_error", f"Tinix Media Creator từ chối yêu cầu: {detail or response.status_code}")

    async def providers(self) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(8.0, connect=3.0)) as client:
                response = await client.get("/api/providers")
        except httpx.HTTPError as exc:
            raise AIError("media_creator_offline", "Tinix Media Creator chưa chạy tại địa chỉ đã cấu hình.", True) from exc
        if response.status_code >= 400:
            raise self._error(response)
        return [item for item in response.json().get("providers", []) if isinstance(item, dict)]

    async def create_run(
        self, *, run_id: str, provider: str, prompt: str, aspect_ratio: str, count: int, model: str = "",
    ) -> str:
        options = {"count": count, "imageCount": count, "aspectRatio": aspect_ratio}
        if model:
            options["model"] = model
        job = {
            "id": run_id,
            "provider": provider,
            "type": "image",
            "operation": "generate",
            "prompt": prompt,
            "originalPrompt": prompt,
            "aspectRatio": aspect_ratio,
            "imageCount": count,
            "options": options,
        }
        body = {"runId": run_id, "provider": provider, "jobs": [job], "async": True, "maxConcurrentProfiles": 1}
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(30.0, connect=3.0)) as client:
                response = await client.post("/api/v1/runs", json=body)
        except httpx.HTTPError as exc:
            raise AIError("media_creator_offline", "Không thể kết nối Tinix Media Creator.", True) from exc
        if response.status_code >= 400:
            raise self._error(response)
        data = response.json()
        return str(data.get("runId") or run_id)

    async def run_status(self, run_id: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(15.0, connect=3.0)) as client:
                response = await client.get(f"/api/v1/runs/{run_id}/status")
                if response.status_code == 404:
                    return {"status": "unknown", "active": False, "terminal": False, "results": []}
                if response.status_code >= 400:
                    raise self._error(response)
                data = response.json()
                if not data.get("results") and data.get("terminal"):
                    fallback = await client.get("/api/results")
                    if fallback.status_code == 200:
                        data["results"] = [item for item in fallback.json().get("results", []) if item.get("runId") == run_id]
                return data
        except AIError:
            raise
        except httpx.HTTPError as exc:
            raise AIError("media_creator_unavailable", "Mất kết nối với Tinix Media Creator.", True) from exc

    async def abort_run(self, run_id: str) -> None:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(15.0, connect=3.0)) as client:
                response = await client.post(f"/api/v1/runs/{run_id}/abort", json={"reason": "cancelled_from_social_hub"})
        except httpx.HTTPError as exc:
            raise AIError("media_creator_unavailable", "Không thể gửi yêu cầu hủy sang Tinix Media Creator.", True) from exc
        if response.status_code >= 400:
            raise self._error(response)

    async def download(self, media_url: str) -> tuple[bytes, str]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                response = await client.get(self._absolute_url(media_url))
        except httpx.HTTPError as exc:
            raise AIError("media_creator_download_failed", "Không thể tải ảnh kết quả từ Tinix Media Creator.", True) from exc
        if response.status_code >= 400:
            raise self._error(response)
        return response.content, response.headers.get("content-type", "image/png")
