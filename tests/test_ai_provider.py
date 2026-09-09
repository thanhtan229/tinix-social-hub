from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace

import httpx

from app.services.ai import AIError, OpenAICompatibleProvider


def settings():
    return SimpleNamespace(
        ai_api_key="test-only-key",
        ai_base_url="https://ai.example",
        ai_model="test-model",
        ai_timeout_seconds=5,
        ai_max_retries=0,
    )


class AIProviderTests(unittest.TestCase):
    def provider_with(self, handler) -> OpenAICompatibleProvider:
        provider = OpenAICompatibleProvider(settings())
        provider._client = httpx.AsyncClient(
            base_url="https://ai.example",
            transport=httpx.MockTransport(handler),
            headers={"Authorization": "Bearer test-only-key"},
        )
        return provider

    def test_structured_output_and_usage(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "model": "test-model",
                "choices": [{"message": {"content": json.dumps({
                    "topic": "Topic", "summary": "Summary",
                    "platform_variants": {"facebook": {"caption": "Hello", "hashtags": ["#test"]}},
                    "media_suggestions": [], "warnings": [],
                })}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            })

        provider = self.provider_with(handler)

        async def run():
            result = await provider.generate_structured("brief", "system")
            await provider.close()
            return result

        result = asyncio.run(run())
        self.assertEqual(result.content.platform_variants["facebook"].caption, "Hello")
        self.assertEqual(result.usage["total_tokens"], 30)

    def test_authentication_error_is_classified_and_not_retried(self) -> None:
        provider = self.provider_with(lambda request: httpx.Response(401, json={"error": "invalid"}))

        async def run():
            try:
                await provider.generate_structured("brief", "system")
            finally:
                await provider.close()

        with self.assertRaises(AIError) as caught:
            asyncio.run(run())
        self.assertEqual(caught.exception.code, "authentication")
        self.assertFalse(caught.exception.retryable)

    def test_invalid_json_is_rejected(self) -> None:
        provider = self.provider_with(lambda request: httpx.Response(200, json={
            "choices": [{"message": {"content": "not-json"}}]
        }))

        async def run():
            try:
                await provider.generate_structured("brief", "system")
            finally:
                await provider.close()

        with self.assertRaises(AIError) as caught:
            asyncio.run(run())
        self.assertEqual(caught.exception.code, "invalid_output")

    def test_generate_image_primary_b64(self) -> None:
        import base64
        fake_png = b"\x89PNG\r\n\x1a\nfake-image-bytes"
        b64_str = base64.b64encode(fake_png).decode("ascii")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/images/generations":
                return httpx.Response(200, json={
                    "data": [{"b64_json": b64_str}]
                })
            return httpx.Response(404)

        provider = self.provider_with(handler)

        async def run():
            res = await provider.generate_image("test prompt")
            await provider.close()
            return res

        result = asyncio.run(run())
        self.assertEqual(result.image_bytes, fake_png)
        self.assertFalse(result.fallback_used)

    def test_generate_image_fallback_when_primary_fails(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            # Simulate 429 Quota Exceeded on primary API
            return httpx.Response(429, json={"error": "quota exceeded"})

        provider = self.provider_with(handler)

        # Mock _fallback_pollinations
        from app.services.ai import AIImageResult
        async def mock_fallback(prompt: str):
            return AIImageResult(
                image_bytes=b"mock-fallback-bytes",
                mime_type="image/jpeg",
                source_model="FLUX (Pollinations AI)",
                fallback_used=True,
            )
        provider._fallback_pollinations = mock_fallback

        async def run():
            res = await provider.generate_image("test prompt")
            await provider.close()
            return res

        result = asyncio.run(run())
        self.assertEqual(result.image_bytes, b"mock-fallback-bytes")
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.source_model, "FLUX (Pollinations AI)")


if __name__ == "__main__":
    unittest.main()

