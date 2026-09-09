from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.core.logging import secret_registry
from app.db.integration_repositories import AIProviderConfigRepository, PlatformAppRepository
from app.db.database import utc_now
from app.db.repositories import AppSettingsRepository
from app.integrations.catalog import ai_provider, integration_catalog, platform_app
from app.services.ai import AIConfigurationError, AIError, AIImageResult, AIProvider, AIResult, OpenAICompatibleProvider


@dataclass(frozen=True, slots=True)
class ResolvedAIConfig:
    config_id: str
    provider: str
    settings: Any


class IntegrationService:
    def __init__(self, settings: Settings, ai_configs: AIProviderConfigRepository, platform_apps: PlatformAppRepository, app_settings: AppSettingsRepository) -> None:
        self.settings = settings
        self.ai_configs = ai_configs
        self.platform_apps = platform_apps
        self.app_settings = app_settings

    def catalog(self) -> dict[str, list[dict[str, Any]]]:
        return integration_catalog()

    def _legacy(self) -> ResolvedAIConfig | None:
        if not (self.settings.ai_api_key and self.settings.ai_base_url and self.settings.ai_model):
            return None
        base_url = self.settings.ai_base_url
        provider = "gemini" if "generativelanguage.googleapis.com" in base_url else "openai" if "openai.com" in base_url else "deepseek" if "deepseek.com" in base_url else "legacy"
        return ResolvedAIConfig("legacy-env", provider, SimpleNamespace(
            ai_api_key=self.settings.ai_api_key, ai_base_url=base_url, ai_model=self.settings.ai_model,
            ai_image_model=self.settings.ai_image_model, ai_timeout_seconds=self.settings.ai_timeout_seconds,
            ai_max_retries=self.settings.ai_max_retries,
        ))

    def resolve_ai(self, capability: str = "text") -> ResolvedAIConfig:
        setting_key = "ai.default_image_config_id" if capability == "image" else "ai.default_text_config_id"
        config_id = self.app_settings.get(setting_key)
        selected = self.ai_configs.get(str(config_id)) if config_id else None
        if not selected or not selected.get("enabled"):
            items = self.ai_configs.list(enabled_only=True)
            selected = next((item for item in items if item.get("image_model" if capability == "image" else "text_model")), None)
        if selected:
            secret = self.ai_configs.secret(selected["id"])
            secret_registry.add(secret)
            return ResolvedAIConfig(selected["id"], selected["provider"], SimpleNamespace(
                ai_api_key=secret, ai_base_url=selected["base_url"],
                ai_model=selected["image_model"] if capability == "image" and selected.get("image_model") else selected["text_model"],
                ai_image_model=selected.get("image_model") or "", ai_timeout_seconds=self.settings.ai_timeout_seconds,
                ai_max_retries=self.settings.ai_max_retries,
            ))
        legacy = self._legacy()
        if legacy:
            return legacy
        raise AIConfigurationError("Chưa cấu hình AI Provider. Hãy thêm API key trong Cài đặt > Tích hợp & API.")

    def set_defaults(self, text_config_id: str | None, image_config_id: str | None) -> dict[str, Any]:
        for config_id, capability in ((text_config_id, "text_model"), (image_config_id, "image_model")):
            if config_id:
                item = self.ai_configs.get(config_id)
                if not item or not item.get("enabled") or not item.get(capability):
                    raise ValueError("Cấu hình mặc định không hợp lệ hoặc đang tắt.")
        now = utc_now()
        with self.app_settings.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.executemany(
                    "INSERT INTO app_settings(key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
                    [
                        ("ai.default_text_config_id", json.dumps(text_config_id), now),
                        ("ai.default_image_config_id", json.dumps(image_config_id), now),
                    ],
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return {"text_config_id": text_config_id, "image_config_id": image_config_id}

    def ai_list(self) -> dict[str, Any]:
        defaults = {"text_config_id": self.app_settings.get("ai.default_text_config_id"), "image_config_id": self.app_settings.get("ai.default_image_config_id")}
        return {"configs": self.ai_configs.list(), "defaults": defaults, "legacy_configured": bool(self._legacy())}

    def create_ai(self, **payload: Any) -> dict[str, Any]:
        return self.ai_configs.create(**payload)

    def update_ai(self, config_id: str, **payload: Any) -> dict[str, Any]:
        if payload.get("enabled") is False and config_id in {
            self.app_settings.get("ai.default_text_config_id"), self.app_settings.get("ai.default_image_config_id"),
        }:
            raise ValueError("Không thể tắt cấu hình đang là mặc định; hãy chọn cấu hình mặc định khác trước.")
        return self.ai_configs.update(config_id, **payload)

    def delete_ai(self, config_id: str) -> bool:
        if config_id in {self.app_settings.get("ai.default_text_config_id"), self.app_settings.get("ai.default_image_config_id")}:
            raise ValueError("Không thể xóa cấu hình đang là mặc định.")
        return self.ai_configs.delete(config_id)

    @staticmethod
    def _capabilities(model_id: str) -> list[str]:
        lowered = model_id.lower()
        if any(token in lowered for token in ("embedding", "audio", "realtime", "tts", "transcribe", "moderation")):
            return []
        return ["image"] if "image" in lowered or "dall-e" in lowered else ["text"]

    @staticmethod
    def _discovery_base_url(provider: str, base_url: str | None = None) -> str:
        definition = ai_provider(provider)
        if not definition.get("requires_base_url"):
            return definition["base_url"]
        value = (base_url or "").strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Base URL của OpenAI-compatible phải là URL http/https tuyệt đối.")
        return value

    async def _fetch_models(self, provider: str, base_url: str, api_key: str) -> list[dict[str, Any]]:
        definition = ai_provider(provider)
        raw_items: list[dict[str, Any]] = []
        timeout = min(self.settings.ai_timeout_seconds, 30)
        if provider == "gemini":
            page_token = ""
            async with httpx.AsyncClient(base_url=definition["model_list_base_url"], timeout=timeout) as client:
                for _ in range(20):
                    params = {"key": api_key, "pageSize": "1000"}
                    if page_token:
                        params["pageToken"] = page_token
                    response = await client.get(definition["model_list_path"], params=params)
                    if response.status_code >= 400:
                        raise OpenAICompatibleProvider._classify_status(response.status_code)
                    body = response.json()
                    raw_items.extend(item for item in body.get("models", []) if isinstance(item, dict))
                    page_token = str(body.get("nextPageToken") or "")
                    if not page_token:
                        break
        else:
            async with httpx.AsyncClient(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout) as client:
                response = await client.get(definition["model_list_path"])
            if response.status_code >= 400:
                raise OpenAICompatibleProvider._classify_status(response.status_code)
            body = response.json()
            raw_items = [item for item in (body.get("data") or body.get("models") or []) if isinstance(item, dict)]

        models: list[dict[str, Any]] = []
        for raw in raw_items[:500]:
            model_id = str(raw.get("id") or raw.get("name") or "").removeprefix("models/").strip()
            if not model_id:
                continue
            if provider == "gemini":
                supports_generate_content = "generateContent" in (raw.get("supportedGenerationMethods") or [])
                capabilities = ["text"] if supports_generate_content else []
                if supports_generate_content and "image" in model_id.lower():
                    capabilities.append("image")
                metadata = {
                    "description": raw.get("description", "")[:500],
                    "supports_generate_content": supports_generate_content,
                    "supported_generation_methods": raw.get("supportedGenerationMethods") or [],
                }
            else:
                capabilities = self._capabilities(model_id)
                if not capabilities:
                    continue
                metadata = {"owned_by": raw.get("owned_by"), "description": raw.get("description", "")[:500]}
            models.append({"model_id": model_id, "display_name": raw.get("display_name") or raw.get("displayName") or model_id, "capabilities": capabilities, "metadata": metadata})
        return models

    async def discover_models(self, provider: str, api_key: str, base_url: str | None = None) -> list[dict[str, Any]]:
        key = api_key.strip()
        if not key:
            raise ValueError("API key không được để trống.")
        secret_registry.add(key)
        return await self._fetch_models(provider, self._discovery_base_url(provider, base_url), key)

    async def refresh_models(self, config_id: str) -> list[dict[str, Any]]:
        item = self.ai_configs.get(config_id)
        if not item:
            raise KeyError(config_id)
        key = self.ai_configs.secret(config_id)
        secret_registry.add(key)
        started = time.perf_counter()
        try:
            models = await self._fetch_models(item["provider"], item["base_url"], key)
            self.ai_configs.replace_models(config_id, models)
            self.ai_configs.mark_test(config_id, status="ok")
            return self.ai_configs.models(config_id)
        except (httpx.HTTPError, ValueError, AIError) as exc:
            error = exc if isinstance(exc, AIError) else AIError("network", "Không thể tải danh sách model.")
            self.ai_configs.mark_test(config_id, status="failed", error_code=error.code, error_message=str(error))
            raise error
        finally:
            _ = started

    async def test_ai(self, config_id: str) -> dict[str, Any]:
        resolved = self.resolve_specific(config_id)
        provider = OpenAICompatibleProvider(resolved.settings)
        started = time.perf_counter()
        try:
            result = await provider.generate_structured("Trả JSON hợp lệ: {\"topic\":\"ok\",\"summary\":\"ok\",\"platform_variants\":{},\"image_prompt\":\"\",\"media_suggestions\":[],\"warnings\":[]}", "Bạn chỉ trả JSON hợp lệ.")
            self.ai_configs.mark_test(config_id, status="ok")
            return {"status": "ok", "provider": resolved.provider, "model": result.raw_model, "latency_ms": result.latency_ms, "tested_at": time.time()}
        except AIError as exc:
            self.ai_configs.mark_test(config_id, status="failed", error_code=exc.code, error_message=str(exc))
            raise
        finally:
            await provider.close()
            _ = started

    def resolve_specific(self, config_id: str, capability: str = "text") -> ResolvedAIConfig:
        item = self.ai_configs.get(config_id)
        if not item or not item.get("enabled"):
            raise AIConfigurationError("Không tìm thấy AI Provider đang hoạt động.")
        secret = self.ai_configs.secret(config_id)
        secret_registry.add(secret)
        model = item.get("image_model") if capability == "image" else item.get("text_model")
        if not model:
            raise AIConfigurationError("Provider chưa chọn model cho tác vụ này.")
        return ResolvedAIConfig(config_id, item["provider"], SimpleNamespace(ai_api_key=secret, ai_base_url=item["base_url"], ai_model=model, ai_image_model=item.get("image_model") or "", ai_timeout_seconds=self.settings.ai_timeout_seconds, ai_max_retries=self.settings.ai_max_retries))

    def test_platform_app(self, app_id: str) -> dict[str, Any]:
        item = self.platform_apps.get(app_id)
        if not item:
            raise KeyError(app_id)
        parsed = urlparse(item["redirect_uri"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            self.platform_apps.mark_test(app_id, status="failed", error_code="invalid_redirect_uri", error_message="Redirect URI phải là URL http/https tuyệt đối.")
            raise ValueError("Redirect URI phải là URL http/https tuyệt đối.")
        self.platform_apps.mark_test(app_id, status="oauth_required")
        return {"status": "oauth_required", "provider": item["provider"], "message": "Cấu hình hợp lệ. Hãy kết nối một account để xác nhận OAuth và scope thực tế."}


class ManagedAIProvider(AIProvider):
    name = "managed"

    def __init__(self, integrations: IntegrationService) -> None:
        self.integrations = integrations

    @property
    def configured(self) -> bool:
        try:
            self.integrations.resolve_ai()
            return True
        except AIConfigurationError:
            return False

    def describe(self) -> dict[str, str]:
        try:
            resolved = self.integrations.resolve_ai()
            return {"provider": resolved.provider, "model": resolved.settings.ai_model, "config_id": resolved.config_id}
        except AIConfigurationError:
            return {"provider": self.name, "model": "unconfigured", "config_id": ""}

    async def generate_structured(self, prompt: str, system: str) -> AIResult:
        resolved = self.integrations.resolve_ai("text")
        provider = OpenAICompatibleProvider(resolved.settings)
        try:
            return await provider.generate_structured(prompt, system)
        finally:
            await provider.close()

    async def generate_image(self, prompt: str) -> AIImageResult:
        resolved = self.integrations.resolve_ai("image")
        provider = OpenAICompatibleProvider(resolved.settings)
        try:
            return await provider.generate_image(prompt)
        finally:
            await provider.close()
