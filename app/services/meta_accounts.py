from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

from app.automation.browser_session import BrowserSession
from app.core.config import Settings
from app.db.provider_repositories import OAuthStateRepository, ProviderConnectionRepository, ProviderTargetConnectionRepository
from app.db.repositories import AccountRepository, TargetRepository


class MetaGraphAPIError(RuntimeError):
    def __init__(self, status_code: int, code: str | None, message: str) -> None:
        self.status_code = status_code
        self.graph_code = code
        super().__init__(message)


class MetaAccountService:
    provider = "meta"
    graph_root = "https://graph.facebook.com"
    scopes_default = ("pages_show_list", "pages_manage_posts", "pages_read_engagement", "read_insights")

    def __init__(
        self, settings: Settings, accounts: AccountRepository, targets: TargetRepository,
        connections: ProviderConnectionRepository, oauth_states: OAuthStateRepository,
        target_connections: ProviderTargetConnectionRepository, platform_apps: Any, chrome: Any,
        client_factory: Any = httpx.AsyncClient,
    ) -> None:
        self.settings = settings
        self.accounts = accounts
        self.targets = targets
        self.connections = connections
        self.oauth_states = oauth_states
        self.target_connections = target_connections
        self.platform_apps = platform_apps
        self.chrome = chrome
        self.client_factory = client_factory

    def _app(self, app_id: str | None = None) -> dict[str, Any]:
        if app_id:
            app = self.platform_apps.get(app_id)
            if not app or app.get("provider") != "meta" or not app.get("enabled"):
                raise ValueError("Meta Platform App không tồn tại hoặc đang tắt.")
            candidates = [app]
        else:
            candidates = self.platform_apps.list(provider="meta", enabled_only=True)
        app = next((item for item in candidates if item), None)
        if not app:
            raise RuntimeError("Hãy thêm và bật Meta Developer App trong Cài đặt → Tích hợp.")
        version = str(app.get("api_version") or "").strip()
        if not version.startswith("v") or not version[1:].replace(".", "").isdigit():
            raise RuntimeError("Hãy đặt Graph API version (ví dụ vXX.0) trong cấu hình Meta App trước khi kết nối.")
        return {**app, "api_version": version.rstrip("/")}

    def system_user_access_token(self, account_id: str) -> str:
        """Return the saved System User token for one connected Facebook account."""
        account = self.accounts.get(account_id)
        if not account:
            raise KeyError(account_id)
        if account.get("platform") != "facebook":
            raise ValueError("Meta Page API cần account Facebook trong Tinix.")
        connection = next((item for item in self.connections.list(
            account_id=account_id, transport="official_api",
        ) if item.get("provider") == self.provider), None)
        metadata = (connection or {}).get("refresh_metadata") or {}
        if (not connection or connection.get("status") != "connected"
                or metadata.get("auth_method") != "system_user"):
            raise RuntimeError("Account chưa có System User access token đã lưu.")
        token = self.connections.secrets(connection["id"]).get("access_token")
        if not token:
            raise RuntimeError("Meta connection không còn System User token đã lưu.")
        return str(token)

    def _graph_url(self, app: dict[str, Any], path: str) -> str:
        return f"{self.graph_root}/{app['api_version']}/{path.lstrip('/')}"

    @staticmethod
    def _video_graph_url(app: dict[str, Any], path: str) -> str:
        return f"https://graph-video.facebook.com/{app['api_version']}/{path.lstrip('/')}"

    def authorize_url(self, account_id: str, platform_app_id: str | None = None) -> dict[str, Any]:
        account = self.accounts.get(account_id)
        if not account:
            raise KeyError(account_id)
        if account.get("platform") != "facebook":
            raise ValueError("Meta Page API cần account Facebook trong Tinix.")
        app = self._app(platform_app_id)
        if not app.get("has_client_secret"):
            raise RuntimeError("Meta App chưa có App Secret. Chỉ cần App Secret nếu dùng OAuth.")
        redirect = str(app["redirect_uri"])
        parsed = urlparse(redirect)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Redirect URI Meta phải là URL http/https tuyệt đối.")
        scopes = sorted(set(app.get("scopes") or self.scopes_default))
        state = self.oauth_states.create(
            account_id, self.provider, redirect_uri=redirect,
            platform_app_id=app["id"],
        )
        query = urlencode({
            "client_id": app["client_id"], "redirect_uri": redirect,
            "response_type": "code", "state": state, "scope": ",".join(scopes),
        })
        return {"provider": self.provider, "authorization_url": f"https://www.facebook.com/{app['api_version']}/dialog/oauth?{query}"}

    async def open_authorization(self, account_id: str, platform_app_id: str | None = None) -> dict[str, Any]:
        if not self.chrome:
            raise RuntimeError("Chrome profile của account chưa được cấu hình.")
        account = await asyncio.to_thread(self.accounts.get, account_id)
        if not account:
            raise KeyError(account_id)
        authorization = await asyncio.to_thread(self.authorize_url, account_id, platform_app_id)
        parsed = urlparse(authorization["authorization_url"])
        if parsed.scheme != "https" or parsed.hostname != "www.facebook.com" or not parsed.path.endswith("/dialog/oauth"):
            raise ValueError("Địa chỉ OAuth Meta không hợp lệ.")
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

    async def _request(self, app: dict[str, Any], method: str, path: str, token: str, *, params: dict[str, Any] | None = None, data: dict[str, Any] | None = None) -> dict[str, Any]:
        request_params = dict(params or {})
        request_data = dict(data or {})
        # Tokens are sent in Authorization headers and are never written to query strings or logs.
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with self.client_factory(timeout=self.settings.provider_timeout_seconds) as client:
                response = await client.request(method, self._graph_url(app, path), params=request_params, data=request_data, headers=headers)
        except httpx.HTTPError as exc:
            raise RuntimeError("Không kết nối được Meta Graph API.") from exc
        return self._parse_graph_response(response)

    @staticmethod
    def _parse_graph_response(response: Any) -> dict[str, Any]:
        if response.status_code in {401, 403}:
            raise MetaGraphAPIError(response.status_code, None, "Meta từ chối quyền. Hãy kiểm tra lại scope, Page task và trạng thái App.")
        if response.status_code == 429:
            raise MetaGraphAPIError(response.status_code, "rate_limited", "Meta đang giới hạn tần suất; hãy chờ rồi thử lại.")
        if response.status_code >= 500:
            raise MetaGraphAPIError(response.status_code, None, "Meta Graph API tạm thời không khả dụng.")
        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError("Meta trả về phản hồi không hợp lệ.") from exc
        if response.status_code >= 400 or (isinstance(body, dict) and body.get("error")):
            error = body.get("error") if isinstance(body, dict) else {}
            message = str((error or {}).get("message") or "Meta từ chối yêu cầu.")[:400]
            code = str((error or {}).get("code") or "") or None
            raise MetaGraphAPIError(response.status_code, code, f"Meta Graph API: {message}")
        if not isinstance(body, dict):
            raise RuntimeError("Meta trả về dữ liệu không hợp lệ.")
        return body

    async def oauth_callback(self, code: str, state: str) -> dict[str, Any]:
        pending = await asyncio.to_thread(self.oauth_states.consume, state, self.provider)
        existing = next((item for item in await asyncio.to_thread(
            self.connections.list, account_id=pending["account_id"], transport="official_api",
        ) if item.get("provider") == self.provider), None)
        expected_credential_revision = self._credential_revision((existing or {}).get("refresh_metadata") or {})
        app = await asyncio.to_thread(self._app, pending.get("platform_app_id"))
        try:
            async with self.client_factory(timeout=self.settings.provider_timeout_seconds) as client:
                exchanged_code = await client.get(self._graph_url(app, "oauth/access_token"), params={
                    "client_id": app["client_id"], "client_secret": self.platform_apps.secret(app["id"]),
                    "redirect_uri": pending["redirect_uri"], "code": code,
                })
        except httpx.HTTPError as exc:
            raise RuntimeError("Không kết nối được Meta để đổi OAuth code.") from exc
        try:
            token_body = exchanged_code.json()
        except ValueError as exc:
            raise RuntimeError("Meta trả về phản hồi OAuth không hợp lệ.") from exc
        if exchanged_code.status_code >= 400 or not isinstance(token_body, dict):
            raise RuntimeError("Meta từ chối đổi OAuth code; hãy kiểm tra App ID, redirect URI và cấu hình app.")
        user_token = str(token_body.get("access_token") or "")
        if not user_token:
            raise RuntimeError("Meta không trả access token.")
        # Exchange short-lived user token where supported; a failed exchange keeps the valid token gated by its expiry.
        async with self.client_factory(timeout=self.settings.provider_timeout_seconds) as client:
            try:
                exchanged = await client.get(self._graph_url(app, "oauth/access_token"), params={
                    "grant_type": "fb_exchange_token", "client_id": app["client_id"],
                    "client_secret": self.platform_apps.secret(app["id"]), "fb_exchange_token": user_token,
                })
                if exchanged.status_code < 400 and isinstance(exchanged.json(), dict):
                    user_token = str(exchanged.json().get("access_token") or user_token)
                    token_body = exchanged.json()
            except (httpx.HTTPError, ValueError):
                pass
        identity = await self._request(app, "GET", "me", user_token, params={"fields": "id,name"})
        permissions = await self._request(app, "GET", "me/permissions", user_token)
        granted = [str(item["permission"]) for item in permissions.get("data", [])
                   if isinstance(item, dict) and item.get("status") == "granted" and item.get("permission")]
        pages = await self._discover_oauth_pages(app, user_token)
        if existing:
            await self._ensure_oauth_page_set_is_compatible(existing["id"], pages)
        binding_inputs = await self._oauth_binding_inputs(pending["account_id"], pages)
        expires_at = None
        if token_body.get("expires_in"):
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(token_body["expires_in"]))).isoformat()
        await asyncio.to_thread(
            self.target_connections.sync_meta_oauth_bindings,
            connection_id=existing["id"] if existing else None,
            bindings=binding_inputs,
            credential_changed=True,
            expected_credential_revision=expected_credential_revision,
            oauth_connection={
                "account_id": pending["account_id"],
                "external_account_id": str(identity.get("id") or ""),
                "scopes": granted,
                "access_token": user_token,
                "expires_at": expires_at,
                "refresh_metadata": {"token_type": "Bearer", "token_refresh_supported": False,
                                     "auth_method": "oauth_user"},
                "platform_app_id": app["id"],
            },
        )
        connection = next((item for item in await asyncio.to_thread(
            self.connections.list, account_id=pending["account_id"], transport="official_api",
        ) if item.get("provider") == self.provider), None)
        if not connection:
            raise RuntimeError("Không thể lưu Meta connection sau khi đồng bộ Page.")
        await self._refresh_page_count(connection["id"])
        return {**connection, "display_name": identity.get("name"), "reconnected": bool(existing)}

    async def _discover_oauth_pages(self, app: dict[str, Any], user_token: str) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        after: str | None = None
        for page_number in range(20):
            params: dict[str, Any] = {"fields": "id,name,access_token,tasks,link", "limit": 100}
            if after:
                params["after"] = after
            body = await self._request(app, "GET", "me/accounts", user_token, params=params)
            pages.extend(item for item in body.get("data", [])
                          if isinstance(item, dict) and item.get("id") and item.get("access_token"))
            paging = body.get("paging") or {}
            after = ((paging.get("cursors") or {}).get("after"))
            if not paging.get("next"):
                break
            if not after:
                raise RuntimeError("Meta báo còn Page nhưng thiếu cursor phân trang; Tinix không lưu kết nối chưa xác minh đủ.")
            if page_number == 19:
                raise RuntimeError("Meta trả quá 2.000 Page; Tinix chưa thể xác minh hết quyền nên không lưu kết nối.")
        if not pages:
            raise RuntimeError("Meta không trả Page nào có Page access token cho account này.")
        return pages

    async def _ensure_oauth_page_set_is_compatible(
        self, connection_id: str, pages: list[dict[str, Any]],
    ) -> None:
        granted_page_ids = {str(page["id"]) for page in pages}
        current = await asyncio.to_thread(self.target_connections.list, connection_id)
        missing = [item for item in current
                   if item.get("provider") == self.provider and item.get("status") == "connected"
                   and str(item.get("external_target_id") or "") not in granted_page_ids]
        if missing:
            page_names = ", ".join(
                f"{item.get('target_name') or item.get('external_target_id')} ({item.get('external_target_id')})"
                for item in missing
            )
            raise RuntimeError(
                "Quyền Meta mới không còn bao gồm các Page đang kết nối: " + page_names
                + ". Kết nối cũ được giữ nguyên. Hãy ngắt rõ từng Page này trong Tài khoản & Page rồi kết nối lại."
            )

    async def _oauth_binding_inputs(
        self, account_id: str, pages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        existing = await asyncio.to_thread(self.targets.list, account_id)
        all_targets = await asyncio.to_thread(self.targets.list)
        page_targets: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        selected_target_pages: dict[str, str] = {}
        for page in pages:
            page_id = str(page["id"])
            page_slug = self._page_slug(str(page.get("link") or ""))
            cross_account = next((item for item in all_targets if item.get("platform") == "facebook"
                                  and str(item.get("external_id") or "") == page_id
                                  and item.get("account_id") != account_id), None)
            if cross_account:
                raise RuntimeError(f"Page {page_id} đã thuộc một account Facebook Tinix khác; không tự tạo liên kết trùng.")
            exact = next((item for item in existing if item.get("platform") == "facebook"
                          and str(item.get("external_id") or "") == page_id), None)
            slug_matches = [item for item in existing if item.get("platform") == "facebook" and page_slug and page_slug in {
                self._page_slug(str(item.get("url") or "")), self._page_slug(str(item.get("external_id") or "")),
            }]
            if not exact and len(slug_matches) > 1:
                raise RuntimeError(f"Page {page_id} khớp nhiều target Tinix; cần xử lý target trùng trước khi đồng bộ.")
            target = exact or (slug_matches[0] if len(slug_matches) == 1 else None)
            if target:
                prior_page_id = selected_target_pages.get(target["id"])
                if prior_page_id and prior_page_id != page_id:
                    raise RuntimeError(
                        f"Nhiều Meta Page cùng khớp Tinix target {target['id']}; cần xử lý target trùng trước khi đồng bộ."
                    )
                selected_target_pages[target["id"]] = page_id
            page_targets.append((page, target))

        result = []
        for page, target in page_targets:
            tasks = [str(task) for task in page.get("tasks", [])]
            result.append({
                "target_id": target["id"] if target else None,
                "target": {"name": str(page.get("name") or page["id"]), "url": page.get("link")},
                "external_target_id": str(page["id"]), "access_token": str(page["access_token"]),
                "tasks": tasks,
            })
        return result

    async def _system_user_page(
        self, app: dict[str, Any], page_id: str, token: str,
    ) -> dict[str, Any]:
        """Resolve one explicitly selected Page without requiring a browser redirect."""
        try:
            page = None
            after: str | None = None
            for _ in range(20):
                params: dict[str, Any] = {"fields": "id,name,access_token,tasks,link", "limit": 100}
                if after:
                    params["after"] = after
                body = await self._request(app, "GET", "me/accounts", token, params=params)
                page = next((item for item in body.get("data", [])
                             if isinstance(item, dict) and str(item.get("id") or "") == page_id), None)
                if page:
                    break
                paging = body.get("paging") or {}
                after = str(((paging.get("cursors") or {}).get("after")) or "") or None
                if not after or not paging.get("next"):
                    break
            if page:
                if not page.get("access_token"):
                    page = {**page, "access_token": token}
                return page
        except RuntimeError:
            # System User tokens may be scoped directly to an assigned Page and
            # may not expose the user-oriented /me/accounts discovery edge.
            pass

        page = await self._request(
            app, "GET", page_id, token, params={"fields": "id,name,link"},
        )
        if str(page.get("id") or "") != page_id:
            raise RuntimeError("Meta xác thực token nhưng Page ID trả về không khớp với Page đã chọn.")
        page_token = token
        try:
            token_body = await self._request(app, "GET", page_id, token, params={"fields": "access_token"})
            if token_body.get("access_token"):
                page_token = str(token_body["access_token"])
        except RuntimeError:
            pass
        return {
            **page,
            "access_token": page_token,
            # OAuth scopes do not prove that this specific Page grants a task.
            "tasks": [],
        }

    async def discover_system_user_pages(
        self, platform_app_id: str, access_token: str,
    ) -> dict[str, Any]:
        clean_token = str(access_token or "").strip()
        if len(clean_token) < 20 or len(clean_token) > 10000:
            raise ValueError("System User token có định dạng hoặc độ dài không hợp lệ.")
        app = await asyncio.to_thread(self._app, platform_app_id)
        pages: list[dict[str, Any]] = []
        after: str | None = None
        try:
            for _ in range(20):
                params: dict[str, Any] = {
                    "fields": "id,name,link,tasks", "limit": 100,
                }
                if after:
                    params["after"] = after
                body = await self._request(app, "GET", "me/accounts", clean_token, params=params)
                pages.extend(item for item in body.get("data", [])
                             if isinstance(item, dict) and str(item.get("id") or "").isdigit())
                paging = body.get("paging") or {}
                cursors = paging.get("cursors") or {}
                after = str(cursors.get("after") or "") or None
                if not after or not paging.get("next"):
                    break
        except RuntimeError as exc:
            message = str(exc).lower()
            if "từ chối quyền" in message or "invalid token" in message or "access token" in message:
                status = "permission_denied"
                hint = "Meta từ chối token hoặc quyền liệt kê Page. Kiểm tra token/quyền; bạn vẫn có thể thử nhập Page ID để xác minh trực tiếp."
            elif "unsupported" in message or "not supported" in message:
                status = "unsupported"
                hint = "Loại token này không hỗ trợ liệt kê Page. Nhập Page ID dạng số để xác minh từng Page."
            else:
                status = "unavailable"
                hint = "Hiện không lấy được danh sách Page từ Meta. Có thể nhập Page ID dạng số để xác minh riêng."
            return {
                "status": status, "pages": [], "message": hint,
            }

        unique: dict[str, dict[str, Any]] = {}
        for page in pages:
            page_id = str(page["id"])
            unique[page_id] = {
                "id": page_id, "name": str(page.get("name") or page_id),
                "link": page.get("link"),
                "tasks": [str(task) for task in page.get("tasks", []) if task],
                "permissions_verified": bool(page.get("tasks")),
            }
        return {
            "status": "available" if unique else "empty",
            "pages": list(unique.values()),
            "message": "Chọn Page cần kết nối." if unique else "Meta trả danh sách rỗng; bạn vẫn có thể nhập Page ID để kiểm tra riêng.",
        }

    async def connect_system_user(
        self, account_id: str, platform_app_id: str, access_token: str,
        page_ids: list[str], disconnect_page_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        account = await asyncio.to_thread(self.accounts.get, account_id)
        if not account:
            raise KeyError(account_id)
        if account.get("platform") != "facebook":
            raise ValueError("Meta Page API cần account Facebook trong Tinix.")
        clean_token = str(access_token or "").strip()
        selected_page_ids = list(dict.fromkeys(str(value).strip() for value in page_ids if str(value).strip()))
        removed_page_ids = list(dict.fromkeys(str(value).strip() for value in (disconnect_page_ids or []) if str(value).strip()))
        if not selected_page_ids or len(selected_page_ids) > 100:
            raise ValueError("Chọn ít nhất một Page và tối đa 100 Page mỗi lần.")
        if any(not value.isdigit() or len(value) > 30 for value in [*selected_page_ids, *removed_page_ids]):
            raise ValueError("Page ID phải là dãy số lấy từ Meta Graph API.")
        if set(selected_page_ids) & set(removed_page_ids):
            raise ValueError("Một Page không thể vừa giữ kết nối vừa ngắt kết nối.")
        app = await asyncio.to_thread(self._app, platform_app_id)

        existing_connection = next((item for item in await asyncio.to_thread(
            self.connections.list, account_id=account_id, transport="official_api",
        ) if item.get("provider") == self.provider), None)
        old_metadata = (existing_connection or {}).get("refresh_metadata") or {}
        old_bindings = await asyncio.to_thread(
            self.target_connections.list, existing_connection["id"],
        ) if existing_connection else []
        connected_bindings = [item for item in old_bindings if item.get("status") == "connected"]
        connected_page_ids = {str(item.get("external_target_id") or "") for item in connected_bindings}
        expected_credential_revision = self._credential_revision(old_metadata)

        if clean_token:
            if len(clean_token) < 20 or len(clean_token) > 10000:
                raise ValueError("System User token có định dạng hoặc độ dài không hợp lệ.")
            old_token = None
            if existing_connection:
                old_token = (await asyncio.to_thread(
                    self.connections.secrets, existing_connection["id"],
                )).get("access_token")
            credential_changed = bool(
                clean_token != old_token
                or old_metadata.get("auth_method") != "system_user"
                or existing_connection.get("platform_app_id") != app["id"]
            ) if existing_connection else True
        else:
            if (not existing_connection or existing_connection.get("status") != "connected"
                    or old_metadata.get("auth_method") != "system_user"):
                raise ValueError("Nhập token System User để kết nối lần đầu hoặc đổi token.")
            if existing_connection.get("platform_app_id") != app["id"]:
                raise ValueError("Đổi Meta App cần nhập lại token để xác minh.")
            clean_token = str((await asyncio.to_thread(
                self.connections.secrets, existing_connection["id"],
            )).get("access_token") or "")
            if not clean_token:
                raise RuntimeError("Meta connection không còn System User token đã lưu.")
            credential_changed = False

        unknown_removals = set(removed_page_ids) - connected_page_ids
        if unknown_removals:
            raise ValueError("Chỉ có thể ngắt Page đang được kết nối trong account này.")

        previous_scopes = list(existing_connection.get("scopes") or []) if existing_connection else []
        try:
            permission_body = await self._request(app, "GET", "me/permissions", clean_token)
            granted = [str(item["permission"]) for item in permission_body.get("data", [])
                       if isinstance(item, dict) and item.get("status") == "granted" and item.get("permission")]
        except RuntimeError:
            granted = previous_scopes if not credential_changed else []
        if existing_connection and set(granted) != set(existing_connection.get("scopes") or []):
            credential_changed = True
        omitted_existing = connected_page_ids - set(selected_page_ids)
        if credential_changed and omitted_existing - set(removed_page_ids):
            omitted = ", ".join(sorted(omitted_existing - set(removed_page_ids)))
            raise ValueError(f"Xác nhận rõ các Page sẽ ngắt khi đổi token: {omitted}.")
        try:
            identity = await self._request(app, "GET", "me", clean_token, params={"fields": "id,name"})
        except RuntimeError:
            identity = {}

        validated_pages: list[dict[str, Any]] = []
        for selected_id in selected_page_ids:
            page = await self._system_user_page(app, selected_id, clean_token)
            tasks = [str(task) for task in page.get("tasks", []) if task]
            page_id = str(page["id"])
            all_targets = await asyncio.to_thread(self.targets.list)
            cross_account = next((item for item in all_targets
                                  if item.get("platform") == "facebook"
                                  and item.get("external_id") == page_id
                                  and item.get("account_id") != account_id), None)
            if cross_account:
                raise RuntimeError(f"Page {page_id} đã thuộc một account Facebook Tinix khác; không tự tạo liên kết trùng.")
            existing_targets = [item for item in all_targets if item.get("account_id") == account_id]
            exact = next((item for item in existing_targets if item.get("platform") == "facebook"
                          and str(item.get("external_id") or "") == page_id), None)
            page_slug = self._page_slug(str(page.get("link") or ""))
            slug_matches = [item for item in existing_targets if item.get("platform") == "facebook"
                            and page_slug and page_slug in {
                                self._page_slug(str(item.get("url") or "")),
                                self._page_slug(str(item.get("external_id") or "")),
                            }]
            target = exact or (slug_matches[0] if len(slug_matches) == 1 else None)
            if not exact and len(slug_matches) > 1:
                raise RuntimeError(f"Page {page_id} khớp nhiều target Tinix; cần xử lý target trùng trước khi kết nối.")
            validated_pages.append({
                "page": page, "page_id": page_id, "tasks": tasks,
                "target": target,
            })

        credential_changed = credential_changed or bool(removed_page_ids)
        if existing_connection:
            previous_by_target = {item.get("target_id"): item for item in old_bindings}
            for item in validated_pages:
                if not item["target"]:
                    continue
                target_id = item["target"]["id"]
                previous = previous_by_target.get(target_id)
                if not previous:
                    continue
                if previous.get("status") != "connected":
                    credential_changed = True
                    continue
                old_page_token = await asyncio.to_thread(
                    self.target_connections.token, previous["id"],
                )
                new_page_token = str(item["page"].get("access_token") or clean_token)
                if (old_page_token != new_page_token
                        or sorted(previous.get("tasks") or []) != sorted(item["tasks"])):
                    credential_changed = True

        binding_inputs = [{
            "target_id": item["target"]["id"] if item["target"] else None,
            "target": {
                "account_id": account_id, "platform": "facebook", "target_type": "page",
                "external_id": item["page_id"],
                "name": str(item["page"].get("name") or item["page_id"]),
                "url": item["page"].get("link"),
            } if not item["target"] else None,
            "external_target_id": item["page_id"],
            "access_token": str(item["page"].get("access_token") or clean_token),
            "tasks": item["tasks"],
        } for item in validated_pages]
        connection, bindings = await asyncio.to_thread(
            self.target_connections.upsert_system_user_bindings,
            account_id=account_id, platform_app_id=app["id"],
            external_account_id=str(identity.get("id") or f"system-user:{account_id}"),
            scopes=granted, access_token=clean_token if access_token.strip() else None,
            credential_changed=credential_changed, bindings=binding_inputs,
            disconnect_page_ids=removed_page_ids,
            expected_credential_revision=expected_credential_revision,
            refresh_metadata={"token_type": "Bearer", "token_refresh_supported": False,
                              "auth_method": "system_user"},
        )
        connection = await self._refresh_page_count(connection["id"])
        target_by_id = {item["id"]: item for item in await asyncio.to_thread(self.targets.list, account_id)}
        selected_by_external = {item["page_id"]: item for item in validated_pages}
        selected = [{
            "id": item["external_target_id"],
            "name": target_by_id.get(item["target_id"], {}).get("name") or item["external_target_id"],
            "target_id": item["target_id"], "binding_id": item["id"],
            "tasks": item.get("tasks") or [],
            "permissions_verified": bool(item.get("tasks")),
            "can_publish": self.can_publish(item.get("tasks") or []),
        } for item in bindings if item.get("external_target_id") in selected_by_external]
        return {
            "connected": True, "provider": self.provider, "account_id": account_id,
            "connection_id": connection["id"], "auth_method": "system_user",
            "pages": selected,
            "disconnected_page_ids": removed_page_ids,
            "connected_page_count": len(bindings),
            "scopes": granted, "credential_revision": connection["refresh_metadata"].get("credential_revision"),
        }

    async def _user_token(self, connection_id: str) -> str:
        connection = await asyncio.to_thread(self.connections.get, connection_id)
        if not connection or connection.get("provider") != self.provider or connection.get("status") != "connected":
            raise RuntimeError("Meta connection cần kết nối lại.")
        expiry = datetime.fromisoformat(connection["expires_at"]) if connection.get("expires_at") else None
        secrets = await asyncio.to_thread(self.connections.secrets, connection_id)
        if expiry and expiry <= datetime.now(timezone.utc) + timedelta(seconds=60):
            await asyncio.to_thread(self.connections.set_status, connection_id, "reauth_required", error_code="token_expired")
            raise RuntimeError("Meta user token đã hết hạn; hãy kết nối lại.")
        if not secrets.get("access_token"):
            raise RuntimeError("Meta connection không còn access token.")
        return str(secrets["access_token"])

    @staticmethod
    def _page_slug(value: str | None) -> str:
        if not value:
            return ""
        parsed = urlparse(value if "://" in value else f"https://www.facebook.com/{value.removeprefix('url:')}")
        return parsed.path.strip("/").split("/")[-1].lower()

    async def sync_targets(self, connection_id: str) -> list[dict[str, Any]]:
        connection = await asyncio.to_thread(self.connections.get, connection_id)
        if not connection or connection.get("provider") != self.provider:
            raise KeyError(connection_id)
        app = await asyncio.to_thread(self._app, connection.get("platform_app_id"))
        user_token = await self._user_token(connection_id)
        pages: list[dict[str, Any]] = []
        metadata = connection.get("refresh_metadata") or {}
        if metadata.get("auth_method") == "system_user":
            bound_pages = [item for item in await asyncio.to_thread(
                self.target_connections.list, connection_id,
            ) if item.get("provider") == self.provider and item.get("status") == "connected"]
            if not bound_pages:
                raise RuntimeError("Meta System User chưa có Page đang kết nối.")
            for binding in bound_pages:
                page = await self._system_user_page(
                    app, str(binding.get("external_target_id") or ""), user_token,
                )
                if str(page.get("id") or "") != str(binding.get("external_target_id") or ""):
                    raise RuntimeError("Meta Page ID trả về không khớp với binding đang đồng bộ.")
                pages.append((binding, page))
            targets_by_id = {item["id"]: item for item in await asyncio.to_thread(
                self.targets.list, connection["account_id"],
            )}
            bindings_to_save: list[dict[str, Any]] = []
            result: list[dict[str, Any]] = []
            credential_changed = False
            for binding, page in pages:
                target = targets_by_id.get(binding.get("target_id"))
                if not target or target.get("platform") != "facebook" or target.get("account_id") != connection["account_id"]:
                    raise RuntimeError("Page binding không còn trỏ tới target Facebook thuộc đúng account.")
                tasks = [str(task) for task in page.get("tasks", []) if task]
                page_token = str(page.get("access_token") or user_token)
                if (sorted(binding.get("tasks") or []) != sorted(tasks)
                        or await asyncio.to_thread(self.target_connections.token, binding["id"]) != page_token):
                    credential_changed = True
                bindings_to_save.append({
                    "target_id": target["id"], "external_target_id": str(page["id"]),
                    "access_token": page_token, "tasks": tasks,
                    "target": {"name": str(page.get("name") or target["name"]),
                               "url": page.get("link") or target.get("url")},
                })
            await asyncio.to_thread(
                self.target_connections.upsert_system_user_bindings,
                account_id=connection["account_id"], platform_app_id=connection["platform_app_id"],
                external_account_id=connection.get("external_account_id") or f"system-user:{connection['account_id']}",
                scopes=connection.get("scopes") or [], access_token=None,
                credential_changed=credential_changed, bindings=bindings_to_save,
                disconnect_page_ids=[], refresh_metadata=metadata,
                expected_credential_revision=self._credential_revision(metadata),
            )
            await self._refresh_page_count(connection_id)
            refreshed_targets = {item["id"]: item for item in await asyncio.to_thread(
                self.targets.list, connection["account_id"],
            )}
            for binding, page in pages:
                target = refreshed_targets[binding["target_id"]]
                result.append({**target, "binding_id": binding["id"], "page_tasks": page.get("tasks") or [],
                               "can_publish": self.can_publish(page.get("tasks") or [])})
            return result
        else:
            pages = await self._discover_oauth_pages(app, user_token)
            await self._ensure_oauth_page_set_is_compatible(connection_id, pages)
        if not pages:
            raise RuntimeError("Meta không trả Page nào có Page access token cho account này.")
        account_id = connection["account_id"]
        binding_inputs = await self._oauth_binding_inputs(account_id, pages)
        existing_bindings = await asyncio.to_thread(self.target_connections.list, connection_id)
        binding_credentials_changed = False
        for item in binding_inputs:
            existing_binding = next((binding for binding in existing_bindings
                                     if item.get("target_id") and binding.get("target_id") == item["target_id"]), None)
            if existing_binding:
                if existing_binding.get("status") != "connected":
                    binding_credentials_changed = True
                elif (sorted(existing_binding.get("tasks") or []) != sorted(item["tasks"])
                      or await asyncio.to_thread(self.target_connections.token, existing_binding["id"]) != item["access_token"]):
                    binding_credentials_changed = True
        bindings = await asyncio.to_thread(
            self.target_connections.sync_meta_oauth_bindings,
            connection_id=connection_id, bindings=binding_inputs,
            credential_changed=binding_credentials_changed,
            expected_credential_revision=self._credential_revision(metadata),
        )
        refreshed_targets = {item["id"]: item for item in await asyncio.to_thread(
            self.targets.list, account_id,
        )}
        binding_by_page = {item["external_target_id"]: item for item in bindings}
        result = []
        for page in pages:
            binding = binding_by_page.get(str(page["id"]))
            target = refreshed_targets.get(binding["target_id"]) if binding else None
            if not binding or not target:
                continue
            tasks = [str(task) for task in page.get("tasks", [])]
            result.append({**target, "binding_id": binding["id"], "page_tasks": tasks,
                           "can_publish": self.can_publish(tasks)})
        if not result:
            raise RuntimeError("Không ánh xạ được Page trả về từ Meta vào account Tinix đã chọn.")
        await self._refresh_page_count(connection_id)
        return result

    @staticmethod
    def can_publish(tasks: list[str]) -> bool:
        return bool(set(tasks) & {"CREATE_CONTENT", "PROFILE_PLUS_CREATE_CONTENT", "FULL_CONTROL", "PROFILE_PLUS_FULL_CONTROL"})

    @staticmethod
    def _credential_revision(metadata: dict[str, Any]) -> int:
        try:
            return int(metadata.get("credential_revision") or 0)
        except (TypeError, ValueError):
            return 0

    def list_bindings(self, account_id: str) -> list[dict[str, Any]]:
        connection = next((item for item in self.connections.list(account_id=account_id, transport="official_api")
                           if item.get("provider") == self.provider), None)
        if not connection:
            return []
        return [{**item, "permissions_verified": bool(item.get("tasks")),
                 "can_publish": self.can_publish(item.get("tasks") or [])}
                for item in self.target_connections.list(connection["id"])]

    def connected_page_count(self, connection_id: str) -> int:
        return sum(1 for item in self.target_connections.list(connection_id)
                   if item.get("provider") == self.provider and item.get("status") == "connected")

    async def _refresh_page_count(self, connection_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.connections.refresh_meta_connected_page_count, connection_id)

    async def disconnect_binding(self, account_id: str, binding_id: str) -> dict[str, Any]:
        binding = await asyncio.to_thread(self.target_connections.get, binding_id)
        if not binding or binding.get("provider") != self.provider:
            raise KeyError(binding_id)
        connection = await asyncio.to_thread(self.connections.get, binding["connection_id"])
        if not connection or connection.get("account_id") != account_id:
            raise KeyError(binding_id)
        updated = await asyncio.to_thread(self.target_connections.disconnect_and_bump_revision, binding_id)
        if not updated:
            raise KeyError(binding_id)
        await self._refresh_page_count(connection["id"])
        return {"disconnected": True, "page_id": updated["external_target_id"],
                "binding_id": binding_id}

    async def graph_request(self, connection_id: str, binding_id: str, method: str, path: str, *, params: dict[str, Any] | None = None, data: dict[str, Any] | None = None) -> dict[str, Any]:
        connection = await asyncio.to_thread(self.connections.get, connection_id)
        binding = await asyncio.to_thread(self.target_connections.get, binding_id)
        if not connection or not binding or binding.get("connection_id") != connection_id or binding.get("provider") != self.provider:
            raise RuntimeError("Meta Page binding không khớp với connection đã đóng băng.")
        app = await asyncio.to_thread(self._app, connection.get("platform_app_id"))
        token = await asyncio.to_thread(self.target_connections.token, binding_id)
        return await self._request(app, method, path, token, params=params, data=data)

    async def publish_local_photo(
        self, connection_id: str, binding_id: str, page_id: str, filename: str,
        mime_type: str, file_bytes: bytes, caption: str, *, published: bool = True,
    ) -> dict[str, Any]:
        """Upload one local Page photo, optionally as unpublished album media."""
        connection = await asyncio.to_thread(self.connections.get, connection_id)
        binding = await asyncio.to_thread(self.target_connections.get, binding_id)
        if (not connection or not binding or binding.get("connection_id") != connection_id
                or binding.get("provider") != self.provider or binding.get("status") != "connected"
                or binding.get("external_target_id") != page_id):
            raise RuntimeError("Meta Page binding không khớp với connection hoặc Page đã đóng băng.")
        if not re.fullmatch(r"\d+", str(page_id)):
            raise ValueError("Meta Page ID không hợp lệ.")
        allowed_mimes = {"image/jpeg", "image/png", "image/bmp", "image/x-ms-bmp", "image/gif", "image/tiff"}
        if mime_type not in allowed_mimes or not file_bytes or len(file_bytes) > 10 * 1024 * 1024:
            raise ValueError("Ảnh Facebook API cần JPEG, PNG, BMP, GIF hoặc TIFF và không vượt 10 MB.")
        app = await asyncio.to_thread(self._app, connection.get("platform_app_id"))
        token = await asyncio.to_thread(self.target_connections.token, binding_id)
        safe_filename = Path(filename).name
        if not safe_filename or any(char in safe_filename for char in "\r\n\0"):
            raise ValueError("Tên file ảnh không hợp lệ.")
        try:
            async with self.client_factory(timeout=self.settings.provider_timeout_seconds) as client:
                response = await client.post(
                    self._graph_url(app, f"{page_id}/photos"),
                    data={"published": str(bool(published)).lower(),
                          **({"caption": caption} if published else {})},
                    files={"source": (safe_filename, file_bytes, mime_type)},
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.HTTPError as exc:
            raise RuntimeError("Không xác định được kết quả tải/đăng ảnh lên Meta.") from exc
        return self._parse_graph_response(response)

    async def publish_page_photo_album(
        self, connection_id: str, binding_id: str, page_id: str,
        caption: str, photo_ids: list[str],
    ) -> dict[str, Any]:
        """Create one Page feed post from previously uploaded, unpublished photos."""
        connection = await asyncio.to_thread(self.connections.get, connection_id)
        binding = await asyncio.to_thread(self.target_connections.get, binding_id)
        if (not connection or not binding or binding.get("connection_id") != connection_id
                or binding.get("provider") != self.provider or binding.get("status") != "connected"
                or binding.get("external_target_id") != page_id):
            raise RuntimeError("Meta Page binding không khớp với connection hoặc Page đã đóng băng.")
        if not re.fullmatch(r"\d+", str(page_id)):
            raise ValueError("Meta Page ID không hợp lệ.")
        if not 2 <= len(photo_ids) <= 10 or any(not re.fullmatch(r"\d+", str(item)) for item in photo_ids):
            raise ValueError("Bài nhiều ảnh cần từ 2 đến 10 ID ảnh Meta hợp lệ.")
        if len(set(photo_ids)) != len(photo_ids):
            raise ValueError("Bài nhiều ảnh không được gắn ID ảnh trùng lặp.")
        data = {"message": caption} if caption else {}
        data.update({
            f"attached_media[{index}]": json.dumps({"media_fbid": photo_id}, separators=(",", ":"))
            for index, photo_id in enumerate(photo_ids)
        })
        return await self.graph_request(connection_id, binding_id, "POST", f"{page_id}/feed", data=data)

    async def page_video_request(
        self, connection_id: str, binding_id: str, page_id: str,
        data: dict[str, Any], *, file_chunk: tuple[str, bytes] | None = None,
    ) -> dict[str, Any]:
        """Call the Page Videos chunk-upload edge with the frozen Page token."""
        connection = await asyncio.to_thread(self.connections.get, connection_id)
        binding = await asyncio.to_thread(self.target_connections.get, binding_id)
        if (not connection or not binding or binding.get("connection_id") != connection_id
                or binding.get("provider") != self.provider or binding.get("status") != "connected"
                or binding.get("external_target_id") != page_id):
            raise RuntimeError("Meta Page binding không khớp với connection hoặc Page đã đóng băng.")
        if not re.fullmatch(r"\d+", str(page_id)):
            raise ValueError("Meta Page ID không hợp lệ.")
        upload_phase = str(data.get("upload_phase") or "")
        if upload_phase not in {"start", "transfer", "finish", "cancel"}:
            raise ValueError("Phase upload video Page không hợp lệ.")
        if (upload_phase == "transfer") != (file_chunk is not None):
            raise ValueError("Chunk file chỉ được gửi trong phase transfer.")
        if upload_phase == "start":
            file_size = str(data.get("file_size") or "")
            if not file_size.isdigit() or int(file_size) <= 0:
                raise ValueError("Kích thước file video Page không hợp lệ.")
        else:
            session_id = str(data.get("upload_session_id") or "")
            if not session_id.isdigit():
                raise ValueError("Upload session video Page không hợp lệ.")
        if upload_phase == "transfer" and not str(data.get("start_offset") or "").isdigit():
            raise ValueError("Offset chunk video Page không hợp lệ.")
        if file_chunk is not None:
            filename, chunk = file_chunk
            if (not filename or any(char in filename for char in "\\/\r\n\0")
                    or not chunk or len(chunk) > 64 * 1024 * 1024):
                raise ValueError("Chunk video Page hoặc tên file không hợp lệ.")
        app = await asyncio.to_thread(self._app, connection.get("platform_app_id"))
        token = await asyncio.to_thread(self.target_connections.token, binding_id)
        files = ({"video_file_chunk": (file_chunk[0], file_chunk[1], "video/mp4")}
                 if file_chunk else None)
        try:
            async with self.client_factory(timeout=self.settings.provider_timeout_seconds) as client:
                response = await client.request(
                    "POST", self._video_graph_url(app, f"{page_id}/videos"),
                    data=data, files=files,
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.HTTPError as exc:
            raise RuntimeError("Không xác định được kết quả upload video Page lên Meta.") from exc
        return self._parse_graph_response(response)

    async def upload_local_reel(
        self, connection_id: str, binding_id: str, upload_url: str,
        file_path: Path, file_size: int,
    ) -> dict[str, Any]:
        """Stream a local Reel file to Meta's fixed RUpload endpoint without exposing the Page token."""
        connection = await asyncio.to_thread(self.connections.get, connection_id)
        binding = await asyncio.to_thread(self.target_connections.get, binding_id)
        if (not connection or not binding or binding.get("connection_id") != connection_id
                or binding.get("provider") != self.provider or binding.get("status") != "connected"):
            raise RuntimeError("Meta Page binding không khớp với connection đã đóng băng.")
        app = await asyncio.to_thread(self._app, connection.get("platform_app_id"))
        parsed = urlparse(upload_url)
        match = re.fullmatch(r"/video-upload/v\d+\.\d+/(\d+)", parsed.path)
        if (parsed.scheme != "https" or parsed.hostname != "rupload.facebook.com"
                or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment
                or not match):
            raise ValueError("Meta trả URL upload Reel không hợp lệ.")
        token = await asyncio.to_thread(self.target_connections.token, binding_id)
        if not file_path.is_file() or file_path.stat().st_size != file_size or file_size <= 0:
            raise RuntimeError("File Reel đã thay đổi hoặc không còn tồn tại.")

        async def body():
            with file_path.open("rb") as source:
                while chunk := await asyncio.to_thread(source.read, 1024 * 1024):
                    yield chunk

        headers = {
            "Authorization": f"OAuth {token}", "offset": "0",
            "file_size": str(file_size), "Content-Length": str(file_size),
            "Content-Type": "application/octet-stream",
        }
        try:
            async with self.client_factory(timeout=self.settings.provider_timeout_seconds) as client:
                response = await client.post(upload_url, headers=headers, content=body())
        except httpx.HTTPError as exc:
            raise RuntimeError("Không xác định được kết quả tải Reel lên Meta.") from exc
        if response.status_code >= 400:
            try:
                error = (response.json() or {}).get("error") or {}
            except (ValueError, AttributeError):
                error = {}
            code = str(error.get("code") or "") if isinstance(error, dict) else ""
            subcode = str(error.get("error_subcode") or "") if isinstance(error, dict) else ""
            diagnostic = f" (HTTP {response.status_code}, code {code or '-'}, subcode {subcode or '-'})"
            raise RuntimeError("Meta từ chối tải file Reel lên" + diagnostic + ".")
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError("Meta trả phản hồi upload Reel không hợp lệ.") from exc
        if not isinstance(result, dict) or result.get("success") is not True:
            raise RuntimeError("Meta chưa xác nhận đã tải Reel lên.")
        return result
