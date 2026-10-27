from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

from app.core.config import Settings
from app.db.provider_repositories import OAuthStateRepository, ProviderConnectionRepository
from app.db.repositories import AccountRepository, TargetRepository
from app.automation.browser_session import BrowserSession


YOUTUBE_SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
)


class ProviderAccountService:
    def __init__(
        self, settings: Settings, accounts: AccountRepository,
        connections: ProviderConnectionRepository, oauth_states: OAuthStateRepository,
        targets: TargetRepository | None = None, platform_apps: Any | None = None,
        chrome: Any | None = None,
    ) -> None:
        self.settings = settings
        self.accounts = accounts
        self.connections = connections
        self.oauth_states = oauth_states
        self.targets = targets
        self.platform_apps = platform_apps
        self.chrome = chrome
        self._refresh_locks: dict[str, asyncio.Lock] = {}

    def _youtube_client(self, platform_app_id: str | None = None) -> dict[str, str | None]:
        if self.platform_apps:
            if platform_app_id:
                explicit = self.platform_apps.get(platform_app_id)
                if not explicit:
                    raise ValueError("Không tìm thấy Platform App YouTube.")
                if explicit.get("provider") != "google_youtube" or not explicit.get("enabled"):
                    raise ValueError("Platform App đã chọn không phải Google/YouTube hoặc đang tắt.")
                candidates = [explicit]
            else:
                candidates = self.platform_apps.list(provider="google_youtube", enabled_only=True)
            app = next((item for item in candidates if item and item.get("enabled")), None)
            if app:
                return {
                    "id": str(app["client_id"]), "secret": self.platform_apps.secret(app["id"]),
                    "redirect_uri": str(app["redirect_uri"]), "platform_app_id": str(app["id"]),
                }
        return {
            "id": self.settings.youtube_client_id, "secret": self.settings.youtube_client_secret,
            "redirect_uri": self.settings.youtube_redirect_uri, "platform_app_id": None,
        }

    @property
    def youtube_configured(self) -> bool:
        client = self._youtube_client()
        return bool(client["id"] and client["secret"])

    def authorize_url(self, account_id: str, provider: str, platform_app_id: str | None = None) -> dict[str, Any]:
        account = self.accounts.get(account_id)
        if not account:
            raise KeyError(account_id)
        if provider != "youtube" or account["platform"] != "youtube":
            raise ValueError("Provider không khớp với nền tảng của account.")
        client = self._youtube_client(platform_app_id)
        if not client["id"] or not client["secret"]:
            raise RuntimeError("Chưa cấu hình YouTube OAuth client.")
        state = self.oauth_states.create(
            account_id, provider, redirect_uri=str(client["redirect_uri"]), platform_app_id=client["platform_app_id"],
        )
        query = urlencode({
            "client_id": client["id"],
            "redirect_uri": client["redirect_uri"],
            "response_type": "code",
            "scope": " ".join(YOUTUBE_SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        })
        return {"provider": provider, "authorization_url": f"https://accounts.google.com/o/oauth2/v2/auth?{query}"}

    async def open_authorization_in_profile(
        self, account_id: str, provider: str, platform_app_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.chrome:
            raise RuntimeError("Chrome profile của Tinix chưa được cấu hình.")
        account = await asyncio.to_thread(self.accounts.get, account_id)
        if not account:
            raise KeyError(account_id)
        authorization = await asyncio.to_thread(self.authorize_url, account_id, provider, platform_app_id)
        url = authorization["authorization_url"]
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "accounts.google.com" or parsed.path != "/o/oauth2/v2/auth":
            raise ValueError("Địa chỉ OAuth YouTube không hợp lệ.")
        await asyncio.to_thread(self.chrome.open, account)
        managed = None
        for _ in range(30):
            managed = await asyncio.to_thread(self.chrome.status, account_id)
            if managed and managed.get("state") == "ready":
                break
            if managed and managed.get("state") == "unresponsive":
                raise RuntimeError("Chrome profile của account không phản hồi qua CDP.")
            await asyncio.sleep(0.5)
        if not managed or managed.get("state") != "ready":
            raise RuntimeError("Chrome profile của account khởi động quá thời gian chờ.")
        async with BrowserSession(managed["port"]) as session:
            page = await session.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await page.bring_to_front()
        return {"opened": True, "account_id": account_id, "provider": provider}

    @staticmethod
    def _assert_same_youtube_channel(expected_channel_id: str | None, actual_channel_id: str) -> None:
        if expected_channel_id and expected_channel_id != actual_channel_id:
            raise ValueError(
                "Google đã cấp quyền cho một YouTube channel khác với channel đang liên kết. "
                "Hãy chọn đúng Google account trong Chrome profile của Tinix rồi thử lại."
            )

    async def youtube_callback(self, code: str, state: str) -> dict[str, Any]:
        pending = await asyncio.to_thread(self.oauth_states.consume, state, "youtube")
        client_config = await asyncio.to_thread(self._youtube_client, pending.get("platform_app_id"))
        if not client_config["id"] or not client_config["secret"]:
            raise RuntimeError("Platform App YouTube đã bị tắt hoặc thiếu secret.")
        async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
            response = await client.post("https://oauth2.googleapis.com/token", data={
                "code": code,
                "client_id": client_config["id"],
                "client_secret": client_config["secret"],
                "redirect_uri": pending["redirect_uri"],
                "grant_type": "authorization_code",
            })
            response.raise_for_status()
            token = response.json()
            access_token = token["access_token"]
            identity = await client.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "id,snippet", "mine": "true"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            identity.raise_for_status()
            items = identity.json().get("items") or []
            if not items:
                raise RuntimeError("Không tìm thấy YouTube channel cho tài khoản đã cấp quyền.")
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(token.get("expires_in", 3600)))).isoformat()
        channel = items[0]
        existing_connections = await asyncio.to_thread(
            self.connections.list, account_id=pending["account_id"], transport="official_api",
        )
        current = next((item for item in existing_connections if item.get("provider") == "youtube"), None)
        self._assert_same_youtube_channel(
            current.get("external_account_id") if current else None, str(channel["id"]),
        )
        connection = await asyncio.to_thread(
            self.connections.upsert,
            account_id=pending["account_id"], provider="youtube", external_account_id=channel["id"],
            status="connected", scopes=str(token.get("scope") or "").split(), access_token=access_token,
            refresh_token=token.get("refresh_token"), expires_at=expires_at,
            refresh_metadata={"token_type": token.get("token_type", "Bearer")}, platform_app_id=pending.get("platform_app_id"),
        )
        if self.targets:
            await asyncio.to_thread(
                self.targets.sync,
                pending["account_id"],
                "youtube",
                [{
                    "target_type": "channel",
                    "external_id": channel["id"],
                    "name": channel.get("snippet", {}).get("title") or channel["id"],
                    "url": f"https://www.youtube.com/channel/{channel['id']}",
                }],
            )
        return {**connection, "channel_title": channel.get("snippet", {}).get("title")}

    async def access_token(self, connection_id: str) -> str:
        lock = self._refresh_locks.setdefault(connection_id, asyncio.Lock())
        async with lock:
            connection = await asyncio.to_thread(self.connections.get, connection_id)
            if not connection:
                raise KeyError(connection_id)
            expiry = datetime.fromisoformat(connection["expires_at"]) if connection.get("expires_at") else None
            secrets = await asyncio.to_thread(self.connections.secrets, connection_id)
            if expiry and expiry > datetime.now(timezone.utc) + timedelta(seconds=60) and secrets["access_token"]:
                return str(secrets["access_token"])
            if not secrets["refresh_token"]:
                await asyncio.to_thread(self.connections.set_status, connection_id, "reauth_required", error_code="missing_refresh_token")
                raise RuntimeError("Kết nối YouTube cần cấp quyền lại.")
            client_config = await asyncio.to_thread(self._youtube_client, connection.get("platform_app_id"))
            if not client_config["id"] or not client_config["secret"]:
                await asyncio.to_thread(self.connections.set_status, connection_id, "reauth_required", error_code="missing_platform_app")
                raise RuntimeError("Platform App YouTube không còn khả dụng.")
            async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
                response = await client.post("https://oauth2.googleapis.com/token", data={
                    "client_id": client_config["id"],
                    "client_secret": client_config["secret"],
                    "refresh_token": secrets["refresh_token"],
                    "grant_type": "refresh_token",
                })
                if response.status_code >= 400:
                    await asyncio.to_thread(
                        self.connections.set_status, connection_id, "reauth_required",
                        error_code="refresh_failed", error_message=response.text,
                    )
                    raise RuntimeError("Không thể làm mới quyền YouTube; cần kết nối lại.")
                token = response.json()
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(token.get("expires_in", 3600)))).isoformat()
            updated = await asyncio.to_thread(
                self.connections.upsert,
                account_id=connection["account_id"], provider="youtube",
                external_account_id=connection.get("external_account_id"), status="connected",
                scopes=connection.get("scopes") or [], access_token=token["access_token"],
                refresh_token=token.get("refresh_token"), expires_at=expires_at,
                refresh_metadata={"token_type": token.get("token_type", "Bearer")}, platform_app_id=connection.get("platform_app_id"),
            )
            if not updated:
                raise RuntimeError("Không thể cập nhật kết nối YouTube.")
            return str(token["access_token"])
