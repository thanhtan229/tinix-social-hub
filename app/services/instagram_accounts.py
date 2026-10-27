from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

from app.automation.browser_session import BrowserSession
from app.core.config import Settings
from app.core.logging import secret_registry
from app.db.provider_repositories import OAuthStateRepository, ProviderConnectionRepository
from app.db.repositories import AccountRepository


INSTAGRAM_SCOPES = ("instagram_business_basic", "instagram_business_content_publish")
INSTAGRAM_USERNAME = re.compile(r"[A-Za-z0-9._]{1,30}\Z")


class InstagramGraphAPIError(RuntimeError):
    def __init__(self, status_code: int, graph_code: str = "") -> None:
        self.status_code = int(status_code)
        self.graph_code = str(graph_code)
        super().__init__("Instagram Graph API từ chối yêu cầu.")


class InstagramAccountService:
    """Independent Instagram Login connection; separate from Facebook Page OAuth/tokens."""

    provider = "instagram"
    authorize_endpoint = "https://www.instagram.com/oauth/authorize"
    token_endpoint = "https://api.instagram.com/oauth/access_token"
    graph_root = "https://graph.instagram.com"

    def __init__(
        self, settings: Settings, accounts: AccountRepository,
        targets: Any, connections: ProviderConnectionRepository, oauth_states: OAuthStateRepository,
        platform_apps: Any, chrome: Any, client_factory: Any = httpx.AsyncClient,
    ) -> None:
        self.settings = settings
        self.accounts = accounts
        self.targets = targets
        self.connections = connections
        self.oauth_states = oauth_states
        self.platform_apps = platform_apps
        self.chrome = chrome
        self.client_factory = client_factory
        self._refresh_locks: dict[str, asyncio.Lock] = {}

    def _app(self, app_id: str | None = None) -> dict[str, Any]:
        if app_id:
            app = self.platform_apps.get(app_id)
            if not app or app.get("provider") != self.provider or not app.get("enabled"):
                raise ValueError("Instagram App không tồn tại, đang tắt hoặc không dùng Instagram Login độc lập.")
            candidates = [app]
        else:
            candidates = self.platform_apps.list(provider=self.provider, enabled_only=True)
        app = next((item for item in candidates if item), None)
        if not app:
            raise RuntimeError("Hãy thêm và bật Instagram App Login trong Cài đặt → Tích hợp.")
        version = str(app.get("api_version") or "").strip()
        if not re.fullmatch(r"v\d+\.\d+", version):
            raise RuntimeError("Hãy đặt Graph API version theo dạng vNN.0 trong cấu hình Instagram App.")
        redirect = str(app.get("redirect_uri") or "").strip()
        parsed = urlparse(redirect)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.path != "/api/oauth/instagram/callback"
                or parsed.query or parsed.fragment):
            raise ValueError("Redirect URI Instagram phải trỏ chính xác tới /api/oauth/instagram/callback.")
        return {**app, "api_version": version.rstrip("/"), "redirect_uri": redirect}

    def authorize_url(self, account_id: str, platform_app_id: str | None = None) -> dict[str, Any]:
        account = self.accounts.get(account_id)
        if not account:
            raise KeyError(account_id)
        if account.get("platform") != self.provider:
            raise ValueError("Instagram Login chỉ kết nối với account Instagram trong Tinix.")
        app = self._app(platform_app_id)
        if not app.get("has_client_secret"):
            raise RuntimeError("Instagram App chưa có App Secret.")
        configured_scopes = set(app.get("scopes") or INSTAGRAM_SCOPES)
        if not set(INSTAGRAM_SCOPES).issubset(configured_scopes):
            raise RuntimeError("Instagram App cần scope instagram_business_basic và instagram_business_content_publish.")
        scopes = list(INSTAGRAM_SCOPES)
        state = self.oauth_states.create(
            account_id, self.provider, redirect_uri=app["redirect_uri"], platform_app_id=app["id"],
        )
        query = urlencode({
            "client_id": app["client_id"], "redirect_uri": app["redirect_uri"],
            "response_type": "code", "scope": ",".join(scopes), "state": state,
        })
        return {"provider": self.provider, "authorization_url": f"{self.authorize_endpoint}?{query}"}

    async def open_authorization(self, account_id: str, platform_app_id: str | None = None) -> dict[str, Any]:
        if not self.chrome:
            raise RuntimeError("Chrome profile của account chưa được cấu hình.")
        account = await asyncio.to_thread(self.accounts.get, account_id)
        if not account:
            raise KeyError(account_id)
        authorization = await asyncio.to_thread(self.authorize_url, account_id, platform_app_id)
        parsed = urlparse(authorization["authorization_url"])
        if parsed.scheme != "https" or parsed.hostname != "www.instagram.com" or parsed.path != "/oauth/authorize":
            raise ValueError("Địa chỉ OAuth Instagram không hợp lệ.")
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
            await page.goto(authorization["authorization_url"], wait_until="domcontentloaded", timeout=30_000)
            await page.bring_to_front()
        return {"opened": True, "account_id": account_id, "provider": self.provider}

    async def _graph_get(self, path: str, *, params: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with self.client_factory(timeout=self.settings.provider_timeout_seconds) as client:
                response = await client.get(f"{self.graph_root}/{path.lstrip('/')}", params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise RuntimeError("Không kết nối được Instagram Graph API.") from exc
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError("Instagram trả phản hồi không hợp lệ.") from exc
        if response.status_code >= 400 or not isinstance(result, dict) or result.get("error"):
            raise RuntimeError("Instagram từ chối yêu cầu OAuth hoặc Graph API.")
        return result

    async def graph_request(
        self, connection_id: str, method: str, path: str, *,
        params: dict[str, Any] | None = None, data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        connection = await asyncio.to_thread(self.connections.get, connection_id)
        if (not connection or connection.get("provider") != self.provider
                or connection.get("status") != "connected"):
            raise RuntimeError("Instagram connection cần kết nối lại.")
        app = await asyncio.to_thread(self._app, connection.get("platform_app_id"))
        await self.refresh_connection(connection_id, connection.get("account_id"))
        secrets = await asyncio.to_thread(self.connections.secrets, connection_id)
        token = str(secrets.get("access_token") or "")
        if not token:
            raise RuntimeError("Instagram connection không còn access token.")
        secret_registry.add(token)
        clean_method = method.upper()
        if clean_method not in {"GET", "POST"}:
            raise ValueError("Instagram Graph API chỉ cho phép GET hoặc POST trong publisher.")
        url = f"{self.graph_root}/{app['api_version']}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with self.client_factory(timeout=self.settings.provider_timeout_seconds) as client:
                response = await client.request(
                    clean_method, url, params=params, data=data if clean_method == "POST" else None,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise RuntimeError("Không kết nối được Instagram Graph API.") from exc
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError("Instagram trả phản hồi Graph API không hợp lệ.") from exc
        error = result.get("error") if isinstance(result, dict) else None
        if response.status_code >= 400 or not isinstance(result, dict) or error:
            code = error.get("code", "") if isinstance(error, dict) else ""
            raise InstagramGraphAPIError(response.status_code, str(code))
        return result

    async def access_token(self, connection_id: str, account_id: str | None = None) -> str:
        await self.refresh_connection(connection_id, account_id)
        secrets = await asyncio.to_thread(self.connections.secrets, connection_id)
        token = str(secrets.get("access_token") or "")
        if not token:
            raise RuntimeError("Instagram connection không còn access token.")
        secret_registry.add(token)
        return token

    async def oauth_callback(self, code: str, state: str) -> dict[str, Any]:
        pending = await asyncio.to_thread(self.oauth_states.consume, state, self.provider)
        account = await asyncio.to_thread(self.accounts.get, pending["account_id"])
        if not account or account.get("platform") != self.provider:
            raise ValueError("Instagram OAuth state không còn gắn với account Instagram.")
        app = await asyncio.to_thread(self._app, pending.get("platform_app_id"))
        app_secret = await asyncio.to_thread(self.platform_apps.secret, app["id"])
        secret_registry.add(app_secret)
        try:
            async with self.client_factory(timeout=self.settings.provider_timeout_seconds) as client:
                response = await client.post(self.token_endpoint, data={
                    "client_id": app["client_id"], "client_secret": app_secret,
                    "grant_type": "authorization_code", "redirect_uri": pending["redirect_uri"],
                    "code": code,
                })
        except httpx.HTTPError as exc:
            raise RuntimeError("Không kết nối được Instagram để đổi OAuth code.") from exc
        try:
            token_body = response.json()
        except ValueError as exc:
            raise RuntimeError("Instagram trả phản hồi OAuth không hợp lệ.") from exc
        if response.status_code >= 400 or not isinstance(token_body, dict) or token_body.get("error"):
            raise RuntimeError("Instagram từ chối OAuth code; kiểm tra App ID, redirect URI và chế độ App.")
        access_token = str(token_body.get("access_token") or "")
        if not access_token:
            raise RuntimeError("Instagram không trả access token.")
        secret_registry.add(access_token)
        try:
            long_token = await self._graph_get("access_token", params={
                "grant_type": "ig_exchange_token", "client_secret": app_secret,
                "access_token": access_token,
            })
            access_token = str(long_token.get("access_token") or "")
            expires_in = int(long_token.get("expires_in") or 0)
            if not access_token or expires_in <= 0:
                raise RuntimeError("Instagram không cấp long-lived access token; hãy kết nối lại.")
            identity = await self._graph_get(
                f"{app['api_version']}/me", params={"fields": "user_id,username"}, token=access_token,
            )
        except (ValueError, TypeError) as exc:
            raise RuntimeError("Instagram trả thông tin token hoặc identity không hợp lệ.") from exc
        external_id = str(identity.get("user_id") or identity.get("id") or token_body.get("user_id") or "")
        username = str(identity.get("username") or "").strip().lstrip("@")
        if not external_id.isdigit() or not INSTAGRAM_USERNAME.fullmatch(username):
            raise RuntimeError("Không xác minh được Instagram Professional account từ token vừa cấp.")
        existing = next((item for item in await asyncio.to_thread(
            self.connections.list, account_id=pending["account_id"], transport="official_api",
        ) if item.get("provider") == self.provider), None)
        if existing and existing.get("external_account_id") != external_id:
            raise ValueError("Instagram account ID đã đổi. Ngắt kết nối hiện tại trước khi ghép một profile khác.")
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat() if expires_in > 0 else None
        granted_scopes = token_body.get("permissions") or []
        if isinstance(granted_scopes, str):
            granted_scopes = [item.strip() for item in granted_scopes.replace(" ", ",").split(",") if item.strip()]
        elif isinstance(granted_scopes, list):
            granted_scopes = [
                str(item.get("permission") or item.get("scope") or "").strip()
                for item in granted_scopes
                if isinstance(item, dict)
                and str(item.get("status") or "granted").lower() in {"granted", "approved"}
                and (item.get("permission") or item.get("scope"))
            ] + [item.strip() for item in granted_scopes if isinstance(item, str) and item.strip()]
        else:
            granted_scopes = []
        connection = await asyncio.to_thread(
            self.connections.upsert,
            account_id=pending["account_id"], provider=self.provider,
            external_account_id=external_id, status="connected", scopes=list(granted_scopes),
            access_token=access_token, expires_at=expires_at,
            refresh_metadata={"auth_method": "instagram_login", "token_type": "bearer",
                             "username": username, "credential_revision":
                             int((existing or {}).get("refresh_metadata", {}).get("credential_revision") or 0) + 1},
            platform_app_id=app["id"],
        )
        synced_targets = await asyncio.to_thread(self.targets.sync, pending["account_id"], self.provider, [{
            "external_id": external_id, "target_type": "profile", "name": f"@{username}",
            "url": f"https://www.instagram.com/{username}/",
        }])
        target = next((item for item in synced_targets if item.get("external_id") == external_id), None)
        return {**connection, "username": username, "target": target,
                "reconnected": bool(existing)}

    async def refresh_connection(self, connection_id: str, account_id: str | None = None) -> dict[str, Any]:
        lock = self._refresh_locks.setdefault(connection_id, asyncio.Lock())
        async with lock:
            return await self._refresh_connection(connection_id, account_id)

    async def _refresh_connection(self, connection_id: str, account_id: str | None) -> dict[str, Any]:
        connection = await asyncio.to_thread(self.connections.get, connection_id)
        if (not connection or connection.get("provider") != self.provider
                or connection.get("status") != "connected"
                or account_id and connection.get("account_id") != account_id):
            raise RuntimeError("Instagram connection cần kết nối lại.")
        expiry = datetime.fromisoformat(connection["expires_at"]) if connection.get("expires_at") else None
        if expiry and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if not expiry or expiry <= datetime.now(timezone.utc):
            raise RuntimeError("Instagram token đã hết hạn hoặc thiếu hạn dùng; hãy kết nối lại.")
        if expiry > datetime.now(timezone.utc) + timedelta(days=7):
            return connection
        secrets = await asyncio.to_thread(self.connections.secrets, connection_id)
        token = str(secrets.get("access_token") or "")
        if not token:
            raise RuntimeError("Instagram connection không còn access token.")
        secret_registry.add(token)
        refreshed = await self._graph_get("refresh_access_token", params={
            "grant_type": "ig_refresh_token", "access_token": token,
        })
        new_token = str(refreshed.get("access_token") or "")
        try:
            expires_in = int(refreshed.get("expires_in") or 0)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Instagram trả thời hạn token gia hạn không hợp lệ.") from exc
        if not new_token or expires_in <= 0:
            raise RuntimeError("Instagram không trả access token mới.")
        secret_registry.add(new_token)
        app = await asyncio.to_thread(self._app, connection.get("platform_app_id"))
        identity = await self._graph_get(
            f"{app['api_version']}/me", params={"fields": "user_id,username"}, token=new_token,
        )
        external_id = str(identity.get("user_id") or identity.get("id") or "")
        username = str(identity.get("username") or "").strip().lstrip("@")
        if (external_id != str(connection.get("external_account_id") or "")
                or not INSTAGRAM_USERNAME.fullmatch(username)):
            raise ValueError("Instagram identity đổi sau khi gia hạn; kết nối lại đúng profile trong Tinix.")
        metadata = dict(connection.get("refresh_metadata") or {})
        updated = await asyncio.to_thread(
            self.connections.upsert,
            account_id=connection["account_id"], provider=self.provider,
            external_account_id=connection["external_account_id"], status="connected",
            scopes=connection.get("scopes") or (), access_token=new_token,
            expires_at=(datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat() if expires_in else None,
            refresh_metadata={**metadata, "username": username,
                              "credential_revision": int(metadata.get("credential_revision") or 0) + 1},
            platform_app_id=connection.get("platform_app_id"),
        )
        return updated
