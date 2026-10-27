from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx

from app.db.database import Database
from app.db.integration_repositories import PlatformAppRepository
from app.db.provider_repositories import OAuthStateRepository, ProviderConnectionRepository
from app.db.repositories import AccountRepository, TargetRepository
from app.services.instagram_accounts import INSTAGRAM_SCOPES, InstagramAccountService


class FakeProtector:
    def protect_oauth(self, value: str) -> str:
        return "protected:" + value[::-1]

    def unprotect_oauth(self, value: str) -> str:
        return value.removeprefix("protected:")[::-1]

    def protect_secret(self, value: str) -> str:
        return "protected:" + value[::-1]

    def unprotect_secret(self, value: str) -> str:
        return value.removeprefix("protected:")[::-1]


class InstagramHTTP:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, dict]] = []
        self.username = "tinix.studio"
        self.user_id = "17841400000000000"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, *, data=None, **_kwargs):
        self.calls.append(("POST", url, data or {}, {}))
        return httpx.Response(200, json={
            "access_token": "instagram-short-token",
            "permissions": list(INSTAGRAM_SCOPES),
        }, request=httpx.Request("POST", url))

    async def get(self, url, *, params=None, headers=None, **_kwargs):
        self.calls.append(("GET", url, params or {}, headers or {}))
        if url.endswith("/access_token"):
            body = {"access_token": "instagram-long-token", "expires_in": 5_184_000}
        elif url.endswith("/refresh_access_token"):
            body = {"access_token": "instagram-refreshed-token", "expires_in": 5_184_000}
        elif url.endswith("/v26.0/me"):
            body = {"user_id": self.user_id, "username": self.username}
        else:
            body = {"error": {"message": "unexpected path"}}
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))


class InstagramLoginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.database = Database(root / "data" / "tinix.db", root / "backups")
        self.database.initialize()
        protector = FakeProtector()
        self.accounts = AccountRepository(self.database)
        self.account = self.accounts.create("Tinix Instagram", "instagram")
        self.facebook_account = self.accounts.create("Tinix Facebook", "facebook")
        self.connections = ProviderConnectionRepository(self.database, protector)
        self.targets = TargetRepository(self.database)
        self.oauth_states = OAuthStateRepository(self.database, protector)
        self.platform_apps = PlatformAppRepository(self.database, protector)
        self.app = self.platform_apps.create(
            provider="instagram", name="Tinix Instagram", client_id="ig-client-id",
            client_secret="ig-client-secret", redirect_uri="http://127.0.0.1:8765/api/oauth/instagram/callback",
            api_version="v26.0",
        )
        self.http = InstagramHTTP()
        self.service = InstagramAccountService(
            SimpleNamespace(provider_timeout_seconds=5), self.accounts, self.targets, self.connections,
            self.oauth_states, self.platform_apps, None,
            client_factory=lambda **_kwargs: self.http,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _new_state(self) -> str:
        return self.oauth_states.create(
            self.account["id"], "instagram", redirect_uri=self.app["redirect_uri"],
            platform_app_id=self.app["id"],
        )

    def test_authorize_uses_independent_instagram_scopes_and_bound_state(self) -> None:
        result = self.service.authorize_url(self.account["id"], self.app["id"])
        parsed = urlparse(result["authorization_url"])
        query = parse_qs(parsed.query)
        self.assertEqual((parsed.scheme, parsed.hostname, parsed.path), ("https", "www.instagram.com", "/oauth/authorize"))
        self.assertEqual(set(query["scope"][0].split(",")), set(INSTAGRAM_SCOPES))
        pending = self.oauth_states.consume(query["state"][0], "instagram")
        self.assertEqual(pending["account_id"], self.account["id"])
        self.assertEqual(pending["platform_app_id"], self.app["id"])
        self.assertEqual(query["scope"], [",".join(INSTAGRAM_SCOPES)])
        self.assertNotIn("pages_show_list", query["scope"][0])

    def test_authorize_rejects_non_instagram_account_and_invalid_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "account Instagram"):
            self.service.authorize_url(self.facebook_account["id"], self.app["id"])
        self.platform_apps.update(self.app["id"], api_version="v260")
        with self.assertRaisesRegex(RuntimeError, "dạng vNN.0"):
            self.service.authorize_url(self.account["id"], self.app["id"])

    async def test_callback_saves_verified_identity_and_encrypted_long_lived_token(self) -> None:
        result = await self.service.oauth_callback("authorization-code", self._new_state())
        self.assertEqual(result["provider"], "instagram")
        self.assertEqual(result["external_account_id"], self.http.user_id)
        self.assertEqual(result["target"]["external_id"], self.http.user_id)
        self.assertEqual(result["target"]["target_type"], "profile")
        self.assertEqual(result["refresh_metadata"]["username"], self.http.username)
        self.assertEqual(set(result["scopes"]), set(INSTAGRAM_SCOPES))
        self.assertNotIn("access_token", result)
        self.assertEqual(self.connections.secrets(result["id"])["access_token"], "instagram-long-token")
        self.assertEqual(self.http.calls[0][0:2], ("POST", "https://api.instagram.com/oauth/access_token"))
        self.assertEqual(self.http.calls[1][2]["grant_type"], "ig_exchange_token")
        self.assertEqual(self.http.calls[2][3]["Authorization"], "Bearer instagram-long-token")

    async def test_callback_returns_the_matching_target_when_account_has_multiple_profiles(self) -> None:
        self.targets.sync(self.account["id"], "instagram", [{
            "external_id": "17841400000000001", "target_type": "profile",
            "name": "@another.profile", "url": "https://www.instagram.com/another.profile/",
        }])
        result = await self.service.oauth_callback("authorization-code", self._new_state())
        self.assertEqual(result["target"]["external_id"], self.http.user_id)

    async def test_callback_refuses_reconnect_to_a_different_instagram_id(self) -> None:
        original = self.connections.upsert(
            account_id=self.account["id"], provider="instagram", external_account_id="17841400000000000",
            access_token="prior-token", platform_app_id=self.app["id"],
            refresh_metadata={"username": "old.name", "credential_revision": 1},
        )
        self.http.user_id = "17841409999999999"
        with self.assertRaisesRegex(ValueError, "ID đã đổi"):
            await self.service.oauth_callback("authorization-code", self._new_state())
        current = self.connections.get(original["id"])
        self.assertEqual(current["external_account_id"], "17841400000000000")
        self.assertEqual(self.connections.secrets(original["id"])["access_token"], "prior-token")

    async def test_refresh_is_account_scoped_and_updates_identity_and_revision(self) -> None:
        expiry = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        connection = self.connections.upsert(
            account_id=self.account["id"], provider="instagram", external_account_id=self.http.user_id,
            access_token="instagram-old-token", expires_at=expiry,
            refresh_metadata={"username": "old.name", "credential_revision": 2},
            platform_app_id=self.app["id"],
        )
        with self.assertRaisesRegex(RuntimeError, "cần kết nối lại"):
            await self.service.refresh_connection(connection["id"], self.facebook_account["id"])
        updated = await self.service.refresh_connection(connection["id"], self.account["id"])
        self.assertEqual(updated["refresh_metadata"]["username"], self.http.username)
        self.assertEqual(updated["refresh_metadata"]["credential_revision"], 3)
        self.assertEqual(self.connections.secrets(connection["id"])["access_token"], "instagram-refreshed-token")

    async def test_refresh_refuses_identity_change_without_replacing_token(self) -> None:
        connection = self.connections.upsert(
            account_id=self.account["id"], provider="instagram", external_account_id=self.http.user_id,
            access_token="instagram-old-token",
            expires_at=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            refresh_metadata={"username": self.http.username}, platform_app_id=self.app["id"],
        )
        self.http.user_id = "17841409999999999"
        with self.assertRaisesRegex(ValueError, "identity đổi"):
            await self.service.refresh_connection(connection["id"], self.account["id"])
        self.assertEqual(self.connections.secrets(connection["id"])["access_token"], "instagram-old-token")
