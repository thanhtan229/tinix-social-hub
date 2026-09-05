from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import Settings
from app.db.provider_repositories import OAuthStateRepository, ProviderConnectionRepository
from app.db.repositories import AccountRepository, TargetRepository


YOUTUBE_SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
)


class ProviderAccountService:
    def __init__(
        self, settings: Settings, accounts: AccountRepository,
        connections: ProviderConnectionRepository, oauth_states: OAuthStateRepository,
        targets: TargetRepository | None = None,
    ) -> None:
        self.settings = settings
        self.accounts = accounts
        self.connections = connections
        self.oauth_states = oauth_states
        self.targets = targets
        self._refresh_locks: dict[str, asyncio.Lock] = {}

    @property
    def youtube_configured(self) -> bool:
        return bool(self.settings.youtube_client_id and self.settings.youtube_client_secret)

    def authorize_url(self, account_id: str, provider: str) -> dict[str, Any]:
        account = self.accounts.get(account_id)
        if not account:
            raise KeyError(account_id)
        if provider != "youtube" or account["platform"] != "youtube":
            raise ValueError("Provider không khớp với nền tảng của account.")
        if not self.youtube_configured:
            raise RuntimeError("Chưa cấu hình YouTube OAuth client.")
        state = self.oauth_states.create(
            account_id, provider, redirect_uri=self.settings.youtube_redirect_uri,
        )
        query = urlencode({
            "client_id": self.settings.youtube_client_id,
            "redirect_uri": self.settings.youtube_redirect_uri,
            "response_type": "code",
            "scope": " ".join(YOUTUBE_SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        })
        return {"provider": provider, "authorization_url": f"https://accounts.google.com/o/oauth2/v2/auth?{query}"}

    async def youtube_callback(self, code: str, state: str) -> dict[str, Any]:
        pending = await asyncio.to_thread(self.oauth_states.consume, state, "youtube")
        async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
            response = await client.post("https://oauth2.googleapis.com/token", data={
                "code": code,
                "client_id": self.settings.youtube_client_id,
                "client_secret": self.settings.youtube_client_secret,
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
        connection = await asyncio.to_thread(
            self.connections.upsert,
            account_id=pending["account_id"], provider="youtube", external_account_id=channel["id"],
            status="connected", scopes=str(token.get("scope") or "").split(), access_token=access_token,
            refresh_token=token.get("refresh_token"), expires_at=expires_at,
            refresh_metadata={"token_type": token.get("token_type", "Bearer")},
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
            async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
                response = await client.post("https://oauth2.googleapis.com/token", data={
                    "client_id": self.settings.youtube_client_id,
                    "client_secret": self.settings.youtube_client_secret,
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
                refresh_metadata={"token_type": token.get("token_type", "Bearer")},
            )
            if not updated:
                raise RuntimeError("Không thể cập nhật kết nối YouTube.")
            return str(token["access_token"])
