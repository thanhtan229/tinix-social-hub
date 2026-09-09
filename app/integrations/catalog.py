from __future__ import annotations

from typing import Any


AI_PROVIDERS: dict[str, dict[str, Any]] = {
    "gemini": {
        "id": "gemini", "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model_list_path": "/models", "model_list_base_url": "https://generativelanguage.googleapis.com/v1beta", "auth": "bearer",
        "recommended_text_model": "gemini-2.5-flash",
        "recommended_image_model": "gemini-2.5-flash-image",
        "text_models": ["gemini-2.5-flash", "gemini-2.5-pro"],
        "image_models": ["gemini-2.5-flash-image"],
        "capabilities": ["text", "image"],
    },
    "deepseek": {
        "id": "deepseek", "name": "DeepSeek",
        "base_url": "https://api.deepseek.com", "model_list_path": "/models", "auth": "bearer",
        "recommended_text_model": "deepseek-chat", "recommended_image_model": "",
        "text_models": ["deepseek-chat", "deepseek-reasoner"],
        "image_models": [],
        "capabilities": ["text"],
    },
    "openai": {
        "id": "openai", "name": "OpenAI",
        "base_url": "https://api.openai.com/v1", "model_list_path": "/models", "auth": "bearer",
        "recommended_text_model": "gpt-4o-mini", "recommended_image_model": "gpt-image-1",
        "text_models": ["gpt-4o-mini", "gpt-4o"],
        "image_models": ["gpt-image-1", "dall-e-3"],
        "capabilities": ["text", "image"],
    },
    "openai-compatible": {
        "id": "openai-compatible", "name": "OpenAI-compatible",
        "base_url": "", "model_list_path": "/models", "auth": "bearer",
        "recommended_text_model": "", "recommended_image_model": "",
        "text_models": [], "image_models": [],
        "capabilities": ["text", "image"], "requires_base_url": True,
    },
}

PLATFORM_APPS: dict[str, dict[str, Any]] = {
    "meta": {
        "id": "meta", "name": "Meta (Facebook & Instagram)", "client_label": "App ID",
        "secret_label": "App Secret", "default_redirect_path": "/api/oauth/meta/callback",
        "scopes": ["pages_show_list", "pages_manage_posts", "instagram_basic"],
        "official_publisher": "planned",
    },
    "tiktok": {
        "id": "tiktok", "name": "TikTok", "client_label": "Client Key",
        "secret_label": "Client Secret", "default_redirect_path": "/api/oauth/tiktok/callback",
        "scopes": ["user.info.basic", "video.publish"], "official_publisher": "planned",
    },
    "google_youtube": {
        "id": "google_youtube", "name": "Google / YouTube", "client_label": "Client ID",
        "secret_label": "Client Secret", "default_redirect_path": "/api/oauth/youtube/callback",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"],
        "official_publisher": "available",
    },
    "x": {
        "id": "x", "name": "X", "client_label": "Client ID",
        "secret_label": "Client Secret", "default_redirect_path": "/api/oauth/x/callback",
        "scopes": ["tweet.read", "tweet.write", "users.read", "offline.access"],
        "official_publisher": "planned",
    },
}


def ai_provider(provider: str) -> dict[str, Any]:
    item = AI_PROVIDERS.get(provider)
    if not item:
        raise ValueError("AI provider không được hỗ trợ.")
    return item


def platform_app(provider: str) -> dict[str, Any]:
    item = PLATFORM_APPS.get(provider)
    if not item:
        raise ValueError("Platform Developer App không được hỗ trợ.")
    return item


def integration_catalog() -> dict[str, list[dict[str, Any]]]:
    return {"ai_providers": list(AI_PROVIDERS.values()), "platform_apps": list(PLATFORM_APPS.values())}
