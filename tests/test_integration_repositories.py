from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.secrets import SecretProtector
from app.db.database import Database
from app.db.integration_repositories import AIProviderConfigRepository, PlatformAppRepository
from app.db.repositories import AppSettingsRepository
from app.services.integrations import IntegrationService, ManagedAIProvider


@unittest.skipUnless(__import__("os").name == "nt", "Credential storage requires Windows DPAPI")
class IntegrationRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.database = Database(root / "data" / "tinix_social.db", root / "backups")
        self.database.initialize()
        protector = SecretProtector()
        self.ai = AIProviderConfigRepository(self.database, protector)
        self.apps = PlatformAppRepository(self.database, protector)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_ai_public_row_masks_and_retains_secret(self) -> None:
        created = self.ai.create(provider="openai", name="Personal", api_key="super-secret-a1b2")
        self.assertTrue(created["has_api_key"])
        self.assertEqual(created["key_hint"], "••••a1b2")
        self.assertNotIn("api_key_protected", created)
        self.assertNotIn("super-secret-a1b2", str(created))
        self.assertEqual(self.ai.secret(created["id"]), "super-secret-a1b2")
        updated = self.ai.update(created["id"], text_model="gpt-4o-mini")
        self.assertEqual(self.ai.secret(created["id"]), "super-secret-a1b2")
        self.assertEqual(updated["text_model"], "gpt-4o-mini")

    def test_openai_compatible_requires_and_stores_custom_base_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "Base URL"):
            self.ai.create(provider="openai-compatible", name="Local", api_key="local-key")
        created = self.ai.create(
            provider="openai-compatible", name="Local", api_key="local-key",
            base_url="http://127.0.0.1:1234/v1/", text_model="local-model",
        )
        self.assertEqual(created["base_url"], "http://127.0.0.1:1234/v1")

    def test_platform_app_prevents_delete_while_connected(self) -> None:
        app = self.apps.create(
            provider="google_youtube", name="Local", client_id="client", client_secret="secret-9z",
            redirect_uri="http://127.0.0.1:8765/api/oauth/youtube/callback",
        )
        self.assertTrue(app["has_client_secret"])
        self.assertNotIn("secret-9z", str(app))
        self.assertEqual(self.apps.secret(app["id"]), "secret-9z")

    def test_database_ai_config_is_resolved_without_env_restart(self) -> None:
        config = self.ai.create(provider="deepseek", name="Team", api_key="database-key-1122", text_model="deepseek-chat")
        service = IntegrationService(
            SimpleNamespace(ai_api_key="", ai_base_url="", ai_model="", ai_image_model="", ai_timeout_seconds=5, ai_max_retries=0),
            self.ai, self.apps, AppSettingsRepository(self.database),
        )
        self.assertTrue(ManagedAIProvider(service).configured)
        self.assertEqual(service.resolve_ai().config_id, config["id"])
        service.set_defaults(config["id"], None)
        self.assertEqual(service.ai_list()["defaults"]["text_config_id"], config["id"])
        with self.assertRaises(ValueError):
            service.update_ai(config["id"], enabled=False)

    def test_ai_list_includes_cached_model_display_names(self) -> None:
        config = self.ai.create(
            provider="gemini", name="Gemini", api_key="gemini-key-1122",
            text_model="gemini-2.5-flash", image_model="gemini-3.1-flash-lite-image",
        )
        self.ai.replace_models(config["id"], [
            {"model_id": "gemini-2.5-flash", "display_name": "Gemini 2.5 Flash", "capabilities": ["text"]},
            {"model_id": "gemini-3.1-flash-lite-image", "display_name": "Nano Banana 2 Lite", "capabilities": ["text", "image"]},
        ])
        service = IntegrationService(
            SimpleNamespace(ai_api_key="", ai_base_url="", ai_model="", ai_image_model="", ai_timeout_seconds=5, ai_max_retries=0),
            self.ai, self.apps, AppSettingsRepository(self.database),
        )
        item = service.ai_list()["configs"][0]
        self.assertEqual(item["text_model_display_name"], "Gemini 2.5 Flash")
        self.assertEqual(item["image_model_display_name"], "Nano Banana 2 Lite")

    def test_gemini_discovery_uses_native_paginated_models_endpoint(self) -> None:
        settings = SimpleNamespace(
            ai_api_key="legacy-gemini-key", ai_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            ai_model="gemini-fast", ai_image_model="", ai_timeout_seconds=5, ai_max_retries=0,
        )
        service = IntegrationService(
            settings,
            self.ai, self.apps, AppSettingsRepository(self.database),
        )
        requests: list[dict[str, str]] = []

        class Response:
            status_code = 200

            def __init__(self, body):
                self.body = body

            def json(self):
                return self.body

        class Client:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            async def get(self, path, params):
                requests.append(params)
                if params.get("pageToken"):
                    return Response({"models": [{"name": "models/gemini-image", "supportedGenerationMethods": ["generateContent"]}]})
                return Response({"models": [
                    {"name": "models/gemini-fast", "displayName": "Gemini Fast", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/embedding-only", "supportedGenerationMethods": ["embedContent"]},
                ], "nextPageToken": "next"})

        with patch("app.services.integrations.httpx.AsyncClient", Client):
            models = asyncio.run(service.discover_models("gemini", "gemini-key"))

        self.assertEqual([item["model_id"] for item in models], ["gemini-fast", "embedding-only", "gemini-image"])
        self.assertFalse(models[1]["metadata"]["supports_generate_content"])
        self.assertEqual(requests, [{"key": "gemini-key", "pageSize": "1000"}, {"key": "gemini-key", "pageSize": "1000", "pageToken": "next"}])

        requests.clear()
        with patch("app.services.integrations.httpx.AsyncClient", Client):
            legacy_models = asyncio.run(service.discover_legacy_models())
        self.assertEqual(len(legacy_models), 3)
        self.assertEqual(requests[0]["key"], "legacy-gemini-key")
        state = service.ai_list()
        self.assertEqual(state["legacy"]["provider"], "gemini")
        self.assertNotIn("legacy-gemini-key", str(state))


if __name__ == "__main__":
    unittest.main()
