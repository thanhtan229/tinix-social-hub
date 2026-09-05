from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from app.db.database import Database
from app.db.provider_repositories import OAuthStateRepository, ProviderConnectionRepository
from app.db.repositories import AccountRepository
from app.services.provider_accounts import ProviderAccountService


class FakeProtector:
    def protect_oauth(self, value: str) -> str:
        return "protected:" + value[::-1]

    def unprotect_oauth(self, value: str) -> str:
        return value.removeprefix("protected:")[::-1]


class ProviderConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.database = Database(root / "data" / "tinix.db", root / "backups")
        self.database.initialize()
        self.account = AccountRepository(self.database).create("Channel", "youtube")
        self.protector = FakeProtector()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_public_rows_never_expose_token_columns(self) -> None:
        repository = ProviderConnectionRepository(self.database, self.protector)
        item = repository.upsert(
            account_id=self.account["id"], provider="youtube", scopes=["upload"],
            access_token="access-secret", refresh_token="refresh-secret",
        )
        self.assertNotIn("access_token_protected", item)
        self.assertNotIn("refresh_token_protected", item)
        self.assertEqual(repository.secrets(item["id"])["refresh_token"], "refresh-secret")

    def test_oauth_state_is_single_use(self) -> None:
        states = OAuthStateRepository(self.database, self.protector)
        state = states.create(self.account["id"], "youtube", pkce_verifier="verifier")
        consumed = states.consume(state, "youtube")
        self.assertEqual(consumed["pkce_verifier"], "verifier")
        with self.assertRaises(ValueError):
            states.consume(state, "youtube")

    def test_youtube_authorization_uses_offline_access_and_bound_state(self) -> None:
        connections = ProviderConnectionRepository(self.database, self.protector)
        states = OAuthStateRepository(self.database, self.protector)
        service = ProviderAccountService(
            SimpleNamespace(
                youtube_client_id="client-id", youtube_client_secret="client-secret",
                youtube_redirect_uri="http://127.0.0.1:8765/api/oauth/youtube/callback",
            ),
            AccountRepository(self.database), connections, states,
        )
        result = service.authorize_url(self.account["id"], "youtube")
        query = parse_qs(urlparse(result["authorization_url"]).query)
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["prompt"], ["consent"])
        consumed = states.consume(query["state"][0], "youtube")
        self.assertEqual(consumed["account_id"], self.account["id"])


if __name__ == "__main__":
    unittest.main()
