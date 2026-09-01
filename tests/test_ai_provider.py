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


if __name__ == "__main__":
    unittest.main()

