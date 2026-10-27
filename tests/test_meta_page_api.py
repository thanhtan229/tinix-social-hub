from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from app.db.database import Database
from app.db.provider_repositories import OAuthStateRepository, ProviderConnectionRepository, ProviderTargetConnectionRepository
from app.db.integration_repositories import PlatformAppRepository
from app.db.repositories import AccountRepository, TargetRepository
from app.platforms.providers.meta import MetaPagePublisher
from app.services.publisher_router import PublisherRouter, RoutingPreference
from app.services.publishers import PublishContext, PublishOutcome, PublisherRegistry
from app.services.api_analytics import MetaAPIAnalyticsCollector
from app.services.meta_accounts import MetaAccountService, MetaGraphAPIError


class _FakeProtector:
    def protect_oauth(self, value: str) -> str:
        return "protected:" + value[::-1]

    def unprotect_oauth(self, value: str) -> str:
        return value.removeprefix("protected:")[::-1]

    def protect_secret(self, value: str) -> str:
        return "protected:" + value[::-1]


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.body = body

    def json(self):
        return self.body


class _FakeOAuthClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, _url, *, params=None):
        if params and params.get("code"):
            return _FakeResponse(200, {"access_token": "new-oauth-user-token-value", "expires_in": 3600})
        return _FakeResponse(400, {"error": {"message": "Long-lived exchange unavailable"}})


class _MetaHTTP:
    def __init__(self):
        self.calls = []
        self.uploads = []
        self.photo_posts = []
        self.feed_posts = []
        self.video_api_calls = []
        self.video_sizes = {}
        self.reel_upload_error = None
        self.reject_token = False
        self.direct_page_only = False
        self.pages = [{
            "id": "123456789", "name": "Tí Nị Studio - Chụp ảnh cho bé và gia đình",
            "link": "https://www.facebook.com/tiniphotos/",
            "access_token": "page-access-token-value-123456",
            "tasks": ["CREATE_CONTENT", "ANALYZE"],
        }]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def request(self, method, url, *, params=None, data=None, headers=None, files=None):
        self.calls.append((method, url, params or {}, headers or {}))
        token = (headers or {}).get("Authorization", "")
        if self.reject_token:
            return _FakeResponse(400, {"error": {"message": "Invalid token"}})
        path = url.rsplit("/v23.0/", 1)[-1]
        if path == "123456789/feed":
            if not token.startswith("Bearer "):
                return _FakeResponse(401, {"error": {"message": "Missing bearer token"}})
            self.feed_posts.append((url, headers or {}, data or {}))
            return _FakeResponse(200, {"id": "123456789_888"})
        if path == "123456789/videos":
            request_data = data or {}
            phase = request_data.get("upload_phase")
            self.video_api_calls.append((url, headers or {}, request_data, files or {}))
            if phase == "start":
                self.video_sizes["7654321"] = int(request_data["file_size"])
                return _FakeResponse(200, {"upload_session_id": "7654321", "start_offset": "0", "end_offset": "5"})
            if phase == "transfer":
                filename, chunk, mime_type = files["video_file_chunk"]
                start = int(request_data["start_offset"])
                next_start = start + len(chunk)
                next_end = min(next_start + 5, self.video_sizes[request_data["upload_session_id"]])
                return _FakeResponse(200, {"start_offset": str(next_start), "end_offset": str(next_end)})
            if phase == "finish":
                return _FakeResponse(200, {"success": True, "video_id": "2468013579"})
            if phase == "cancel":
                return _FakeResponse(200, {"success": True})
        if path == "me":
            body = {"id": "system-user-1", "name": "Tinix Social Hub"}
        elif path == "me/permissions":
            body = {"data": [
                {"permission": "pages_manage_posts", "status": "granted"},
                {"permission": "pages_read_engagement", "status": "granted"},
            ]}
        elif path == "me/accounts":
            if self.direct_page_only:
                return _FakeResponse(400, {"error": {"message": "Unsupported user edge"}})
            body = {"data": self.pages}
        elif path.isdigit() and any(str(page["id"]) == path for page in self.pages):
            page = next(page for page in self.pages if str(page["id"]) == path)
            if (params or {}).get("fields") == "access_token" and self.direct_page_only:
                return _FakeResponse(400, {"error": {"message": "Page token field unavailable"}})
            body = {key: value for key, value in page.items() if key != "access_token"}
            if (params or {}).get("fields") == "access_token":
                body["access_token"] = page["access_token"]
        else:
            body = {"error": {"message": f"Unexpected endpoint {path}"}}
            return _FakeResponse(400, body)
        if not token.startswith("Bearer "):
            return _FakeResponse(401, {"error": {"message": "Missing bearer token"}})
        return _FakeResponse(200, body)

    async def post(self, url, *, headers=None, content=None, data=None, files=None):
        if files:
            self.photo_posts.append((url, headers or {}, data or {}, files))
            return _FakeResponse(200, {"id": "987654321", "post_id": "123456789_777"})
        body = b"".join([chunk async for chunk in content])
        self.uploads.append((url, headers or {}, body))
        if self.reel_upload_error:
            return _FakeResponse(400, {"error": self.reel_upload_error})
        return _FakeResponse(200, {"success": True})


class _MetaPlatformApps:
    app = {
        "id": "meta-app-1", "provider": "meta", "name": "Tinix Meta",
        "client_id": "meta-client-id", "enabled": True, "api_version": "v23.0",
        "has_client_secret": False,
    }

    def get(self, app_id):
        return self.app if app_id == self.app["id"] else None

    def list(self, *, provider=None, enabled_only=False):
        return [self.app]


class MetaSystemUserConnectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.database = Database(root / "data" / "tinix.db", root / "backups")
        self.database.initialize()
        self.accounts = AccountRepository(self.database)
        self.account = self.accounts.create("Tí Nị Studio", "facebook")
        self.targets = TargetRepository(self.database)
        protector = _FakeProtector()
        self.connections = ProviderConnectionRepository(self.database, protector)
        self.target_connections = ProviderTargetConnectionRepository(self.database, protector)
        platform_app = PlatformAppRepository(self.database, protector).create(
            provider="meta", name="Tinix Meta", client_id="meta-client-id",
            client_secret="", redirect_uri="", api_version="v23.0",
        )
        self.platform_apps = _MetaPlatformApps()
        self.platform_apps.app = {**self.platform_apps.app, "id": platform_app["id"]}
        self.http = _MetaHTTP()
        self.service = MetaAccountService(
            SimpleNamespace(provider_timeout_seconds=5), self.accounts, self.targets,
            self.connections, OAuthStateRepository(self.database, protector),
            self.target_connections, self.platform_apps, None,
            client_factory=lambda **_kwargs: self.http,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _prepare_oauth_callback(self):
        self.platform_apps.secret = lambda _app_id: "fake-app-secret"
        self.service.client_factory = lambda **_kwargs: _FakeOAuthClient()

        async def request(_app, _method, path, _token, *, params=None, data=None):
            if path == "me":
                return {"id": "new-oauth-user", "name": "Meta User"}
            if path == "me/permissions":
                return {"data": [{"permission": "pages_show_list", "status": "granted"}]}
            if path == "me/accounts":
                return {"data": self.http.pages}
            raise AssertionError(f"Unexpected Meta endpoint: {path}")

        self.service._request = request
        return self.service.oauth_states.create(
            self.account["id"], "meta", redirect_uri="https://tinix.example/api/oauth/meta/callback",
            platform_app_id=self.platform_apps.app["id"],
        )

    async def test_connects_system_user_to_exact_page_without_returning_token(self):
        result = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456", ["123456789"],
        )
        self.assertTrue(result["connected"])
        self.assertTrue(result["pages"][0]["can_publish"])
        self.assertEqual(result["auth_method"], "system_user")
        self.assertNotIn("access_token", result)
        connection = self.connections.get(result["connection_id"])
        self.assertEqual(connection["refresh_metadata"]["auth_method"], "system_user")
        self.assertEqual(connection["refresh_metadata"]["credential_revision"], 1)
        self.assertEqual(self.connections.secrets(connection["id"])["access_token"], "system-user-token-value-123456")
        binding = self.target_connections.get(result["pages"][0]["binding_id"])
        self.assertEqual(binding["external_target_id"], "123456789")
        self.assertEqual(self.target_connections.token(binding["id"]), "page-access-token-value-123456")

    async def test_reel_upload_streams_binary_with_page_auth_header(self):
        connected = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456", ["123456789"],
        )
        binding_id = connected["pages"][0]["binding_id"]
        video = Path(self.temp.name) / "sample.mp4"
        video.write_bytes(b"local reel bytes")
        upload_url = "https://rupload.facebook.com/video-upload/v23.0/987654321"
        result = await self.service.upload_local_reel(
            connected["connection_id"], binding_id, upload_url, video, video.stat().st_size,
        )
        self.assertEqual(result, {"success": True})
        sent_url, headers, body = self.http.uploads[0]
        self.assertEqual(sent_url, upload_url)
        self.assertEqual(headers["Authorization"], "OAuth page-access-token-value-123456")
        self.assertEqual(headers["offset"], "0")
        self.assertEqual(headers["file_size"], str(len(b"local reel bytes")))
        self.assertEqual(headers["Content-Length"], str(len(b"local reel bytes")))
        self.assertEqual(body, b"local reel bytes")
        self.assertNotIn("system-user-token-value-123456", str(result))

    async def test_reel_upload_rejects_non_meta_upload_host(self):
        connected = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456", ["123456789"],
        )
        binding_id = connected["pages"][0]["binding_id"]
        video = Path(self.temp.name) / "sample.mp4"
        video.write_bytes(b"local reel bytes")
        with self.assertRaisesRegex(ValueError, "URL upload Reel"):
            await self.service.upload_local_reel(
                connected["connection_id"], binding_id,
                "https://example.org/video-upload/v23.0/987654321", video, video.stat().st_size,
            )
        self.assertEqual(self.http.uploads, [])

    async def test_reel_upload_reports_meta_codes_without_echoing_provider_message(self):
        connected = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456", ["123456789"],
        )
        binding_id = connected["pages"][0]["binding_id"]
        video = Path(self.temp.name) / "sample.mp4"
        video.write_bytes(b"local reel bytes")
        self.http.reel_upload_error = {"code": 100, "error_subcode": 42,
                                       "message": "private provider diagnostic"}
        with self.assertRaisesRegex(RuntimeError, "HTTP 400, code 100, subcode 42") as raised:
            await self.service.upload_local_reel(
                connected["connection_id"], binding_id,
                "https://rupload.facebook.com/video-upload/v23.0/987654321",
                video, video.stat().st_size,
            )
        self.assertNotIn("private provider diagnostic", str(raised.exception))

    async def test_photo_upload_uses_multipart_page_photos_endpoint_and_page_token(self):
        connected = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456", ["123456789"],
        )
        binding_id = connected["pages"][0]["binding_id"]
        result = await self.service.publish_local_photo(
            connected["connection_id"], binding_id, "123456789", "portrait.jpg", "image/jpeg",
            b"fixture image", "Ảnh Tinix",
        )
        self.assertEqual(result["id"], "987654321")
        url, headers, data, files = self.http.photo_posts[0]
        self.assertTrue(url.endswith("/v23.0/123456789/photos"))
        self.assertEqual(headers["Authorization"], "Bearer page-access-token-value-123456")
        self.assertEqual(data, {"caption": "Ảnh Tinix", "published": "true"})
        self.assertEqual(files["source"], ("portrait.jpg", b"fixture image", "image/jpeg"))
        self.assertNotIn("system-user-token-value-123456", str(self.http.photo_posts))

    async def test_photo_album_uploads_unpublished_media_then_attaches_in_input_order(self):
        connected = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456", ["123456789"],
        )
        binding_id = connected["pages"][0]["binding_id"]
        uploaded = await self.service.publish_local_photo(
            connected["connection_id"], binding_id, "123456789", "first.jpg", "image/jpeg",
            b"first image", "", published=False,
        )
        self.assertEqual(uploaded["id"], "987654321")
        self.assertEqual(self.http.photo_posts[0][2], {"published": "false"})
        result = await self.service.publish_page_photo_album(
            connected["connection_id"], binding_id, "123456789", "Album caption", ["987654321", "987654322"],
        )
        self.assertEqual(result["id"], "123456789_888")
        url, headers, data = self.http.feed_posts[0]
        self.assertTrue(url.endswith("/v23.0/123456789/feed"))
        self.assertEqual(headers["Authorization"], "Bearer page-access-token-value-123456")
        self.assertEqual(data, {
            "message": "Album caption",
            "attached_media[0]": '{"media_fbid":"987654321"}',
            "attached_media[1]": '{"media_fbid":"987654322"}',
        })

    async def test_photo_album_rejects_invalid_or_duplicate_ids_and_wrong_page_before_feed(self):
        connected = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456", ["123456789"],
        )
        binding_id = connected["pages"][0]["binding_id"]
        for page_id, photo_ids in (
            ("999999999", ["987654321", "987654322"]),
            ("123456789", ["987654321", "bad"]),
            ("123456789", ["987654321", "987654321"]),
        ):
            with self.subTest(page_id=page_id, photo_ids=photo_ids):
                with self.assertRaises((ValueError, RuntimeError)):
                    await self.service.publish_page_photo_album(
                        connected["connection_id"], binding_id, page_id, "caption", photo_ids,
                    )
        self.assertEqual(self.http.feed_posts, [])

    async def test_photo_upload_refuses_a_page_binding_mismatch_before_network(self):
        connected = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456", ["123456789"],
        )
        binding_id = connected["pages"][0]["binding_id"]
        with self.assertRaisesRegex(RuntimeError, "binding"):
            await self.service.publish_local_photo(
                connected["connection_id"], binding_id, "999999999", "portrait.jpg", "image/jpeg",
                b"fixture image", "Ảnh Tinix",
            )
        self.assertEqual(self.http.photo_posts, [])

    async def test_page_video_uses_v26_chunk_contract_and_page_token(self):
        connected = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456", ["123456789"],
        )
        binding_id = connected["pages"][0]["binding_id"]
        video = Path(self.temp.name) / "sample.mp4"
        video_bytes = b"0123456789abcdefg"
        video.write_bytes(video_bytes)
        started = await self.service.page_video_request(
            connected["connection_id"], binding_id, "123456789",
            {"upload_phase": "start", "file_size": str(len(video_bytes))},
        )
        self.assertEqual(started["upload_session_id"], "7654321")
        offset, end = int(started["start_offset"]), int(started["end_offset"])
        while offset < len(video_bytes):
            chunk = video_bytes[offset:end]
            transferred = await self.service.page_video_request(
                connected["connection_id"], binding_id, "123456789",
                {"upload_phase": "transfer", "upload_session_id": "7654321", "start_offset": str(offset)},
                file_chunk=(video.name, chunk),
            )
            offset, end = int(transferred["start_offset"]), int(transferred["end_offset"])
        finished = await self.service.page_video_request(
            connected["connection_id"], binding_id, "123456789",
            {"upload_phase": "finish", "upload_session_id": "7654321", "published": "true"},
        )
        self.assertEqual(finished["video_id"], "2468013579")
        self.assertTrue(all(call[0].startswith("https://graph-video.facebook.com/v23.0/123456789/videos")
                            for call in self.http.video_api_calls))
        self.assertTrue(all(call[1]["Authorization"] == "Bearer page-access-token-value-123456"
                            for call in self.http.video_api_calls))
        transfer = next(call for call in self.http.video_api_calls if call[2].get("upload_phase") == "transfer")
        self.assertEqual(transfer[3]["video_file_chunk"][1], video_bytes[:5])

    async def test_page_video_rejects_binding_mismatch_and_invalid_phase_before_network(self):
        connected = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456", ["123456789"],
        )
        binding_id = connected["pages"][0]["binding_id"]
        with self.assertRaisesRegex(RuntimeError, "binding"):
            await self.service.page_video_request(
                connected["connection_id"], binding_id, "999999999", {"upload_phase": "start"},
            )
        with self.assertRaisesRegex(ValueError, "(?i)phase"):
            await self.service.page_video_request(
                connected["connection_id"], binding_id, "123456789", {"upload_phase": "resume"},
            )
        with self.assertRaisesRegex(ValueError, "session"):
            await self.service.page_video_request(
                connected["connection_id"], binding_id, "123456789",
                {"upload_phase": "finish"},
            )
        self.assertEqual(self.http.video_api_calls, [])

    async def test_discovery_returns_multiple_page_candidates_without_page_tokens(self):
        self.http.pages.append({
            "id": "987654321", "name": "Other Page", "link": "https://facebook.com/otherpage",
            "access_token": "second-page-access-token-123456", "tasks": ["ANALYZE"],
        })
        result = await self.service.discover_system_user_pages(
            self.platform_apps.app["id"], "system-user-token-value-123456",
        )
        self.assertEqual(result["status"], "available")
        self.assertEqual({item["id"] for item in result["pages"]}, {"123456789", "987654321"})
        self.assertNotIn("page-access-token-value-123456", str(result))
        self.assertNotIn("second-page-access-token-123456", str(result))

    async def test_initial_connection_can_atomically_bind_multiple_pages(self):
        self.http.pages.append({
            "id": "987654321", "name": "Other Page", "link": "https://facebook.com/otherpage",
            "access_token": "second-page-access-token-123456", "tasks": ["ANALYZE"],
        })
        result = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456",
            ["123456789", "987654321"],
        )
        self.assertEqual(result["connected_page_count"], 2)
        self.assertEqual({item["id"] for item in result["pages"]}, {"123456789", "987654321"})
        self.assertEqual(len([item for item in self.target_connections.list(result["connection_id"])
                             if item["status"] == "connected"]), 2)

    async def test_failed_replacement_keeps_existing_connection_and_page_token(self):
        first = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456", ["123456789"],
        )
        self.http.reject_token = True
        with self.assertRaisesRegex(RuntimeError, "Meta Graph API"):
            await self.service.connect_system_user(
                self.account["id"], self.platform_apps.app["id"], "replacement-token-value-123456", ["123456789"],
            )
        connection = self.connections.get(first["connection_id"])
        self.assertEqual(self.connections.secrets(connection["id"])["access_token"], "system-user-token-value-123456")
        self.assertEqual(connection["refresh_metadata"]["credential_revision"], 1)

    async def test_successful_token_rotation_advances_credential_revision(self):
        first = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456", ["123456789"],
        )
        old_connection = self.connections.get(first["connection_id"])
        second = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "replacement-token-value-123456", ["123456789"],
        )
        new_connection = self.connections.get(second["connection_id"])
        self.assertEqual(first["connection_id"], second["connection_id"])
        self.assertEqual(new_connection["refresh_metadata"]["credential_revision"], 2)
        self.assertNotEqual(PublisherRouter._scopes_hash(old_connection), PublisherRouter._scopes_hash(new_connection))

    async def test_adding_page_with_saved_token_preserves_other_bindings_and_revision(self):
        first = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456", ["123456789"],
        )
        self.http.pages.append({
            "id": "987654321", "name": "Other Page", "link": "https://facebook.com/otherpage",
            "access_token": "second-page-access-token-123456", "tasks": ["ANALYZE"],
        })
        second = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "", ["987654321"],
        )
        bindings = self.target_connections.list(first["connection_id"])
        self.assertEqual(sum(item["status"] == "connected" for item in bindings), 2)
        self.assertEqual(second["connected_page_count"], 2)
        self.assertEqual(second["credential_revision"], 1)
        self.assertFalse(next(page for page in second["pages"] if page["id"] == "987654321")["can_publish"])

    async def test_token_rotation_requires_explicit_disconnect(self):
        first = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456", ["123456789"],
        )
        self.http.pages.append({
            "id": "987654321", "name": "Other Page", "link": "https://facebook.com/otherpage",
            "access_token": "second-page-access-token-123456", "tasks": ["ANALYZE"],
        })
        await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "", ["987654321"],
        )
        with self.assertRaisesRegex(ValueError, "Xác nhận rõ"):
            await self.service.connect_system_user(
                self.account["id"], self.platform_apps.app["id"], "replacement-token-value-123456", ["123456789"],
            )
        self.assertEqual(self.connections.secrets(first["connection_id"])["access_token"], "system-user-token-value-123456")
        result = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "replacement-token-value-123456",
            ["123456789"], ["987654321"],
        )
        bindings = self.target_connections.list(first["connection_id"])
        self.assertEqual(next(item for item in bindings if item["external_target_id"] == "123456789")["status"], "connected")
        self.assertEqual(next(item for item in bindings if item["external_target_id"] == "987654321")["status"], "disconnected")
        self.assertEqual(result["credential_revision"], 2)

    async def test_changed_page_tasks_advance_revision_even_when_user_token_is_same(self):
        first = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456", ["123456789"],
        )
        self.http.pages[0]["tasks"] = ["ANALYZE"]
        result = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456", ["123456789"],
        )
        self.assertEqual(first["credential_revision"], 1)
        self.assertEqual(result["credential_revision"], 2)

    async def test_page_already_attached_to_other_tinix_account_is_not_duplicated(self):
        other = self.accounts.create("Other Facebook", "facebook")
        self.targets.sync(other["id"], "facebook", [{
            "target_type": "page", "external_id": "123456789", "name": "Other account copy",
        }])
        with self.assertRaisesRegex(RuntimeError, "account Facebook Tinix khác"):
            await self.service.connect_system_user(
                self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456", ["123456789"],
            )
        self.assertEqual(self.connections.list(account_id=self.account["id"]), [])

    async def test_page_slug_ambiguity_is_rejected_before_any_connection_or_target_write(self):
        self.targets.sync(self.account["id"], "facebook", [
            {"target_type": "page", "external_id": "url:tiniphotos", "name": "Old Page A",
             "url": "https://www.facebook.com/tiniphotos"},
            {"target_type": "page", "external_id": "legacy:tiniphotos", "name": "Old Page B",
             "url": "https://www.facebook.com/tiniphotos"},
        ])
        before = self.targets.list(self.account["id"])
        with self.assertRaisesRegex(RuntimeError, "khớp nhiều target"):
            await self.service.connect_system_user(
                self.account["id"], self.platform_apps.app["id"],
                "system-user-token-value-123456", ["123456789"],
            )
        self.assertEqual(self.connections.list(account_id=self.account["id"]), [])
        self.assertEqual(self.targets.list(self.account["id"]), before)

    async def test_page_slug_cannot_rebind_a_target_already_bound_to_another_page(self):
        self.targets.sync(self.account["id"], "facebook", [{
            "target_type": "page", "external_id": "url:tiniphotos", "name": "Tí Nị Studio",
            "url": "https://www.facebook.com/tiniphotos",
        }])
        first = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"],
            "system-user-token-value-123456", ["123456789"],
        )
        self.http.pages.append({
            "id": "987654321", "name": "Renamed Page", "link": "https://facebook.com/tiniphotos",
            "access_token": "second-page-access-token-123456", "tasks": ["CREATE_CONTENT"],
        })
        with self.assertRaisesRegex(ValueError, "đã được liên kết với Meta Page 123456789"):
            await self.service.connect_system_user(
                self.account["id"], self.platform_apps.app["id"], "", ["987654321"], ["123456789"],
            )
        bindings = self.target_connections.list(first["connection_id"])
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0]["external_target_id"], "123456789")

    async def test_oauth_sync_rejects_ambiguous_page_slug_matches(self):
        self.targets.sync(self.account["id"], "facebook", [
            {"target_type": "page", "external_id": "url:tiniphotos", "name": "Old Page A",
             "url": "https://www.facebook.com/tiniphotos"},
            {"target_type": "page", "external_id": "legacy:tiniphotos", "name": "Old Page B",
             "url": "https://www.facebook.com/tiniphotos"},
        ])
        connection = self.connections.upsert(
            account_id=self.account["id"], provider="meta", external_account_id="system-user-1",
            scopes=["pages_show_list"], access_token="system-user-token-value-123456",
            platform_app_id=self.platform_apps.app["id"],
            refresh_metadata={"auth_method": "oauth_user"},
        )
        with self.assertRaisesRegex(RuntimeError, "khớp nhiều target"):
            await self.service.sync_targets(connection["id"])
        self.assertEqual(self.target_connections.list(connection["id"]), [])

    async def test_oauth_sync_cannot_rebind_existing_target_to_another_page(self):
        target = self.targets.sync(self.account["id"], "facebook", [{
            "target_type": "page", "external_id": "url:tiniphotos", "name": "Original Page",
            "url": "https://www.facebook.com/tiniphotos",
        }])[0]
        connection = self.connections.upsert(
            account_id=self.account["id"], provider="meta", external_account_id="oauth-user-1",
            scopes=["pages_show_list"], access_token="oauth-user-token-value-123456",
            platform_app_id=self.platform_apps.app["id"],
            refresh_metadata={"auth_method": "oauth_user"},
        )
        first = await self.service.sync_targets(connection["id"])
        self.assertEqual(first[0]["id"], target["id"])
        self.assertEqual(self.target_connections.list(connection["id"])[0]["external_target_id"], "123456789")
        original_name = self.targets.get(target["id"])["name"]

        self.http.pages[:] = [{
            "id": "987654321", "name": "Different Page", "link": "https://facebook.com/tiniphotos",
            "access_token": "different-page-token-value-123456", "tasks": ["CREATE_CONTENT"],
        }]
        with self.assertRaisesRegex(RuntimeError, r"Tí Nị Studio.+ngắt rõ từng Page"):
            await self.service.sync_targets(connection["id"])
        saved_target = self.targets.get(target["id"])
        saved_binding = self.target_connections.list(connection["id"])[0]
        self.assertEqual(saved_target["name"], original_name)
        self.assertEqual(saved_binding["external_target_id"], "123456789")

    async def test_failed_oauth_reconnect_preserves_existing_connection_and_page_binding(self):
        target = self.targets.sync(self.account["id"], "facebook", [{
            "target_type": "page", "external_id": "url:tiniphotos", "name": "Original Page",
            "url": "https://www.facebook.com/tiniphotos",
        }])[0]
        connection = self.connections.upsert(
            account_id=self.account["id"], provider="meta", external_account_id="old-oauth-user",
            status="connected", scopes=["pages_show_list"], access_token="old-oauth-user-token-value",
            refresh_metadata={"auth_method": "oauth_user", "credential_revision": 7},
            platform_app_id=self.platform_apps.app["id"],
        )
        binding = self.target_connections.upsert(
            connection_id=connection["id"], target_id=target["id"], provider="meta",
            external_target_id="123456789", access_token="old-page-token-value", tasks=["ANALYZE"],
        )
        self.http.pages[:] = [{
            "id": "987654321", "name": "Different Page", "link": "https://facebook.com/tiniphotos",
            "access_token": "different-page-token-value", "tasks": ["CREATE_CONTENT"],
        }]
        state = self._prepare_oauth_callback()
        with self.assertRaisesRegex(RuntimeError, r"Original Page \(123456789\).+ngắt rõ từng Page"):
            await self.service.oauth_callback("authorization-code", state)

        saved_connection = self.connections.get(connection["id"])
        self.assertEqual(saved_connection["status"], "connected")
        self.assertEqual(saved_connection["external_account_id"], "old-oauth-user")
        self.assertEqual(saved_connection["refresh_metadata"]["credential_revision"], 7)
        self.assertEqual(self.connections.secrets(connection["id"])["access_token"], "old-oauth-user-token-value")
        saved_binding = self.target_connections.get(binding["id"])
        self.assertEqual(saved_binding["external_target_id"], "123456789")
        self.assertEqual(self.target_connections.token(binding["id"]), "old-page-token-value")

    async def test_oauth_reconnect_updates_page_binding_and_advances_revision_once(self):
        target = self.targets.sync(self.account["id"], "facebook", [{
            "target_type": "page", "external_id": "url:tiniphotos", "name": "Tí Nị Studio",
            "url": "https://www.facebook.com/tiniphotos",
        }])[0]
        connection = self.connections.upsert(
            account_id=self.account["id"], provider="meta", external_account_id="old-oauth-user",
            status="reauth_required", scopes=["pages_show_list"], access_token="old-oauth-user-token-value",
            refresh_metadata={"auth_method": "oauth_user", "credential_revision": 7},
            platform_app_id=self.platform_apps.app["id"],
        )
        binding = self.target_connections.upsert(
            connection_id=connection["id"], target_id=target["id"], provider="meta",
            external_target_id="123456789", access_token="old-page-token-value", tasks=["ANALYZE"],
        )
        self.http.pages[:] = [{
            "id": "123456789", "name": "Tí Nị Studio",
            "link": "https://www.facebook.com/tiniphotos",
            "access_token": "new-page-token-value", "tasks": ["CREATE_CONTENT", "ANALYZE"],
        }]
        state = self._prepare_oauth_callback()

        result = await self.service.oauth_callback("authorization-code", state)

        self.assertTrue(result["reconnected"])
        self.assertEqual(result["status"], "connected")
        self.assertEqual(result["refresh_metadata"]["credential_revision"], 8)
        self.assertEqual(self.connections.secrets(connection["id"])["access_token"], "new-oauth-user-token-value")
        self.assertEqual(self.target_connections.token(binding["id"]), "new-page-token-value")

    async def test_oauth_reconnect_requires_explicit_disconnect_when_access_to_page_is_lost(self):
        target = self.targets.sync(self.account["id"], "facebook", [{
            "target_type": "page", "external_id": "123456789", "name": "Existing Page",
            "url": "https://www.facebook.com/existingpage",
        }])[0]
        connection = self.connections.upsert(
            account_id=self.account["id"], provider="meta", external_account_id="old-oauth-user",
            status="reauth_required", scopes=["pages_show_list"], access_token="old-oauth-user-token-value",
            refresh_metadata={"auth_method": "oauth_user", "credential_revision": 7},
            platform_app_id=self.platform_apps.app["id"],
        )
        binding = self.target_connections.upsert(
            connection_id=connection["id"], target_id=target["id"], provider="meta",
            external_target_id="123456789", access_token="old-page-token-value", tasks=["ANALYZE"],
        )
        self.http.pages[:] = [{
            "id": "987654321", "name": "Other Page", "link": "https://www.facebook.com/otherpage",
            "access_token": "other-page-token-value", "tasks": ["CREATE_CONTENT"],
        }]
        state = self._prepare_oauth_callback()

        with self.assertRaisesRegex(RuntimeError, r"Existing Page \(123456789\).+ngắt rõ từng Page"):
            await self.service.oauth_callback("authorization-code", state)

        self.assertEqual(self.connections.get(connection["id"])["status"], "reauth_required")
        self.assertEqual(self.connections.secrets(connection["id"])["access_token"], "old-oauth-user-token-value")
        self.assertEqual(self.connections.get(connection["id"])["refresh_metadata"]["credential_revision"], 7)
        self.assertEqual(self.target_connections.get(binding["id"])["status"], "connected")
        self.assertEqual(self.target_connections.token(binding["id"]), "old-page-token-value")

    async def test_oauth_callback_rechecks_connected_pages_inside_transaction(self):
        targets = self.targets.sync(self.account["id"], "facebook", [
            {"target_type": "page", "external_id": "123456789", "name": "Page A"},
            {"target_type": "page", "external_id": "987654321", "name": "Page B"},
        ])
        targets_by_page = {item["external_id"]: item for item in targets}
        connection = self.connections.upsert(
            account_id=self.account["id"], provider="meta", external_account_id="old-oauth-user",
            status="connected", scopes=["pages_show_list"], access_token="old-oauth-user-token-value",
            refresh_metadata={"auth_method": "oauth_user", "credential_revision": 7},
            platform_app_id=self.platform_apps.app["id"],
        )
        page_a = self.target_connections.upsert(
            connection_id=connection["id"], target_id=targets_by_page["123456789"]["id"], provider="meta",
            external_target_id="123456789", access_token="old-page-A-token-value", tasks=["ANALYZE"],
        )
        self.http.pages[:] = [{
            "id": "123456789", "name": "Page A", "access_token": "new-page-A-token-value",
            "tasks": ["ANALYZE"],
        }]
        state = self._prepare_oauth_callback()
        original_check = self.service._ensure_oauth_page_set_is_compatible

        async def add_page_after_precheck(connection_id, pages):
            await original_check(connection_id, pages)
            self.target_connections.upsert(
                connection_id=connection_id, target_id=targets_by_page["987654321"]["id"], provider="meta",
                external_target_id="987654321", access_token="concurrent-page-B-token-value", tasks=["ANALYZE"],
            )

        self.service._ensure_oauth_page_set_is_compatible = add_page_after_precheck
        with self.assertRaisesRegex(RuntimeError, "OAuth không còn quyền"):
            await self.service.oauth_callback("authorization-code", state)

        self.assertEqual(self.connections.secrets(connection["id"])["access_token"], "old-oauth-user-token-value")
        self.assertEqual(self.connections.get(connection["id"])["refresh_metadata"]["credential_revision"], 7)
        self.assertEqual(self.target_connections.token(page_a["id"]), "old-page-A-token-value")
        page_b = next(item for item in self.target_connections.list(connection["id"])
                      if item["external_target_id"] == "987654321")
        self.assertEqual(page_b["status"], "connected")

    async def test_oauth_callback_rejects_credential_revision_changed_during_provider_calls(self):
        target = self.targets.sync(self.account["id"], "facebook", [{
            "target_type": "page", "external_id": "123456789", "name": "Page A",
        }])[0]
        connection = self.connections.upsert(
            account_id=self.account["id"], provider="meta", external_account_id="old-oauth-user",
            status="connected", scopes=["pages_show_list"], access_token="old-oauth-user-token-value",
            refresh_metadata={"auth_method": "oauth_user", "credential_revision": 7},
            platform_app_id=self.platform_apps.app["id"],
        )
        binding = self.target_connections.upsert(
            connection_id=connection["id"], target_id=target["id"], provider="meta",
            external_target_id="123456789", access_token="old-page-token-value", tasks=["ANALYZE"],
        )
        state = self._prepare_oauth_callback()
        original_discover = self.service._discover_oauth_pages

        async def change_revision_during_provider_calls(app, token):
            pages = await original_discover(app, token)
            self.connections.bump_credential_revision(connection["id"])
            return pages

        self.service._discover_oauth_pages = change_revision_during_provider_calls
        with self.assertRaisesRegex(RuntimeError, "Meta token đã thay đổi"):
            await self.service.oauth_callback("authorization-code", state)

        saved_connection = self.connections.get(connection["id"])
        self.assertEqual(saved_connection["refresh_metadata"]["credential_revision"], 8)
        self.assertEqual(self.connections.secrets(connection["id"])["access_token"], "old-oauth-user-token-value")
        self.assertEqual(self.target_connections.token(binding["id"]), "old-page-token-value")

    async def test_system_user_binding_sync_rejects_stale_credential_revision(self):
        connection = self.connections.upsert(
            account_id=self.account["id"], provider="meta", external_account_id="system-user-1",
            status="connected", scopes=["pages_manage_posts"], access_token="old-system-user-token-value",
            refresh_metadata={"auth_method": "system_user", "credential_revision": 5},
            platform_app_id=self.platform_apps.app["id"],
        )
        with self.assertRaisesRegex(RuntimeError, "Meta token đã thay đổi"):
            self.target_connections.upsert_system_user_bindings(
                account_id=self.account["id"], platform_app_id=self.platform_apps.app["id"],
                external_account_id="system-user-1", scopes=["pages_manage_posts"], access_token=None,
                credential_changed=False, bindings=[], disconnect_page_ids=[],
                refresh_metadata={"auth_method": "system_user"}, expected_credential_revision=4,
            )
        self.assertEqual(self.connections.get(connection["id"])["refresh_metadata"]["credential_revision"], 5)
        self.assertEqual(self.connections.secrets(connection["id"])["access_token"], "old-system-user-token-value")

    async def test_oauth_page_sync_rejects_stale_credential_revision(self):
        target = self.targets.sync(self.account["id"], "facebook", [{
            "target_type": "page", "external_id": "123456789", "name": "Page A",
        }])[0]
        connection = self.connections.upsert(
            account_id=self.account["id"], provider="meta", external_account_id="oauth-user-1",
            status="connected", scopes=["pages_show_list"], access_token="old-oauth-user-token-value",
            refresh_metadata={"auth_method": "oauth_user", "credential_revision": 5},
            platform_app_id=self.platform_apps.app["id"],
        )
        binding = self.target_connections.upsert(
            connection_id=connection["id"], target_id=target["id"], provider="meta",
            external_target_id="123456789", access_token="old-page-token-value", tasks=["ANALYZE"],
        )
        with self.assertRaisesRegex(RuntimeError, "Meta token đã thay đổi"):
            self.target_connections.sync_meta_oauth_bindings(
                connection_id=connection["id"], credential_changed=False,
                expected_credential_revision=4,
                bindings=[{
                    "target_id": target["id"], "external_target_id": "123456789",
                    "access_token": "stale-page-token-value", "tasks": ["ANALYZE"],
                }],
            )
        self.assertEqual(self.connections.get(connection["id"])["refresh_metadata"]["credential_revision"], 5)
        self.assertEqual(self.target_connections.token(binding["id"]), "old-page-token-value")

    async def test_page_disconnect_and_credential_revision_change_atomically(self):
        target = self.targets.sync(self.account["id"], "facebook", [{
            "target_type": "page", "external_id": "123456789", "name": "Page A",
        }])[0]
        connection = self.connections.upsert(
            account_id=self.account["id"], provider="meta", external_account_id="system-user-1",
            status="connected", scopes=["pages_manage_posts"], access_token="system-user-token-value",
            refresh_metadata={"auth_method": "system_user", "credential_revision": 5},
            platform_app_id=self.platform_apps.app["id"],
        )
        binding = self.target_connections.upsert(
            connection_id=connection["id"], target_id=target["id"], provider="meta",
            external_target_id="123456789", access_token="page-token-value", tasks=["ANALYZE"],
        )

        disconnected = self.target_connections.disconnect_and_bump_revision(binding["id"])

        self.assertEqual(disconnected["status"], "disconnected")
        self.assertEqual(self.connections.get(connection["id"])["refresh_metadata"]["credential_revision"], 6)

    async def test_refresh_page_count_preserves_current_credential_revision(self):
        target = self.targets.sync(self.account["id"], "facebook", [{
            "target_type": "page", "external_id": "123456789", "name": "Page A",
        }])[0]
        connection = self.connections.upsert(
            account_id=self.account["id"], provider="meta", external_account_id="system-user-1",
            status="connected", scopes=["pages_manage_posts"], access_token="system-user-token-value",
            refresh_metadata={"auth_method": "system_user", "credential_revision": 5, "keep": "metadata"},
            platform_app_id=self.platform_apps.app["id"],
        )
        binding = self.target_connections.upsert(
            connection_id=connection["id"], target_id=target["id"], provider="meta",
            external_target_id="123456789", access_token="page-token-value", tasks=["ANALYZE"],
        )

        refreshed = await self.service._refresh_page_count(connection["id"])
        self.assertEqual(refreshed["refresh_metadata"]["connected_page_count"], 1)
        self.assertEqual(refreshed["refresh_metadata"]["credential_revision"], 5)
        self.assertEqual(refreshed["refresh_metadata"]["keep"], "metadata")

        self.target_connections.disconnect_and_bump_revision(binding["id"])
        refreshed = await self.service._refresh_page_count(connection["id"])
        self.assertEqual(refreshed["refresh_metadata"]["connected_page_count"], 0)
        self.assertEqual(refreshed["refresh_metadata"]["credential_revision"], 6)

    async def test_system_user_token_rotation_rechecks_all_connected_pages_in_transaction(self):
        targets = self.targets.sync(self.account["id"], "facebook", [
            {"target_type": "page", "external_id": "123456789", "name": "Page A"},
            {"target_type": "page", "external_id": "987654321", "name": "Page B"},
        ])
        targets_by_page = {item["external_id"]: item for item in targets}
        connection = self.connections.upsert(
            account_id=self.account["id"], provider="meta", external_account_id="system-user-1",
            status="connected", scopes=["pages_manage_posts"], access_token="old-system-user-token-value",
            refresh_metadata={"auth_method": "system_user", "credential_revision": 5},
            platform_app_id=self.platform_apps.app["id"],
        )
        binding_a = self.target_connections.upsert(
            connection_id=connection["id"], target_id=targets_by_page["123456789"]["id"], provider="meta",
            external_target_id="123456789", access_token="old-page-A-token-value", tasks=["ANALYZE"],
        )
        binding_b = self.target_connections.upsert(
            connection_id=connection["id"], target_id=targets_by_page["987654321"]["id"], provider="meta",
            external_target_id="987654321", access_token="newly-added-page-B-token-value", tasks=["ANALYZE"],
        )

        with self.assertRaisesRegex(ValueError, "Xác nhận rõ các Page sẽ ngắt.*987654321"):
            self.target_connections.upsert_system_user_bindings(
                account_id=self.account["id"], platform_app_id=self.platform_apps.app["id"],
                external_account_id="system-user-1", scopes=["pages_manage_posts"],
                access_token="replacement-system-user-token-value", credential_changed=True,
                bindings=[{
                    "target_id": targets_by_page["123456789"]["id"], "external_target_id": "123456789",
                    "access_token": "replacement-page-A-token-value", "tasks": ["ANALYZE"],
                }], disconnect_page_ids=[], refresh_metadata={"auth_method": "system_user"},
                expected_credential_revision=5,
            )

        self.assertEqual(self.connections.secrets(connection["id"])["access_token"], "old-system-user-token-value")
        self.assertEqual(self.connections.get(connection["id"])["refresh_metadata"]["credential_revision"], 5)
        self.assertEqual(self.target_connections.token(binding_a["id"]), "old-page-A-token-value")
        self.assertEqual(self.target_connections.token(binding_b["id"]), "newly-added-page-B-token-value")
        self.assertEqual(self.target_connections.get(binding_b["id"])["status"], "connected")

    async def test_oauth_page_discovery_rejects_incomplete_pagination(self):
        calls = 0

        async def request(_app, _method, _path, _token, *, params=None, data=None):
            nonlocal calls
            calls += 1
            return {"data": [{
                "id": str(calls), "access_token": f"page-token-{calls}",
            }], "paging": {"next": "https://graph.facebook.com/next"}}

        self.service._request = request
        with self.assertRaisesRegex(RuntimeError, "thiếu cursor phân trang"):
            await self.service._discover_oauth_pages(self.platform_apps.app, "user-token")
        self.assertEqual(calls, 1)

    async def test_target_creation_and_provider_bindings_roll_back_as_one_transaction(self):
        with self.assertRaises(ValueError):
            self.target_connections.upsert_system_user_bindings(
                account_id=self.account["id"], platform_app_id=self.platform_apps.app["id"],
                external_account_id="system-user-1", scopes=["pages_manage_posts"],
                access_token="system-user-token-value-123456", credential_changed=True,
                bindings=[
                    {"target_id": None, "target": {
                        "account_id": self.account["id"], "platform": "facebook",
                        "target_type": "page", "external_id": "777777777",
                        "name": "New target that must roll back", "url": "https://facebook.com/777777777",
                    }, "external_target_id": "777777777", "access_token": "page-token-value-123456",
                     "tasks": ["CREATE_CONTENT"]},
                    {"target_id": "missing-target", "external_target_id": "888888888",
                     "access_token": "page-token-value-123456", "tasks": []},
                ], disconnect_page_ids=[], refresh_metadata={"auth_method": "system_user"},
            )
        self.assertEqual(self.connections.list(account_id=self.account["id"]), [])
        self.assertEqual(self.targets.list(self.account["id"]), [])
        with self.database.connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM provider_target_connections WHERE external_target_id IN ('777777777','888888888')"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    async def test_system_user_can_bind_a_page_when_me_accounts_is_unavailable(self):
        self.http.direct_page_only = True
        result = await self.service.connect_system_user(
            self.account["id"], self.platform_apps.app["id"], "system-user-token-value-123456", ["123456789"],
        )
        self.assertEqual(result["pages"][0]["id"], "123456789")
        self.assertFalse(result["pages"][0]["can_publish"])
        self.assertEqual(
            self.target_connections.token(result["pages"][0]["binding_id"]),
            "system-user-token-value-123456",
        )




class _Bindings:
    def __init__(self) -> None:
        self.binding = {
            "id": "binding-1", "connection_id": "connection-1", "target_id": "target-1",
            "external_target_id": "12345", "status": "connected", "tasks": ["CREATE_CONTENT"],
        }

    def get(self, binding_id: str):
        return self.binding if binding_id == self.binding["id"] else None

    def for_target(self, target_id: str, connection_id: str | None = None):
        if target_id != self.binding["target_id"] or (connection_id and connection_id != self.binding["connection_id"]):
            return None
        return self.binding


class _Connections:
    connection = {
        "id": "connection-1", "account_id": "account-1", "provider": "meta",
        "status": "connected", "scopes": ["pages_manage_posts"],
    }

    def get(self, connection_id: str):
        return self.connection if connection_id == self.connection["id"] else None

    def list(self, *, account_id=None, transport=None):
        return [self.connection] if account_id == self.connection["account_id"] else []


class _LocalMedia:
    def __init__(self, path: Path) -> None:
        self.path = path

    def resolve_existing(self, _relative_path: str) -> Path:
        return self.path


class _LocalMediaSet:
    def __init__(self, paths: dict[str, Path]) -> None:
        self.paths = paths

    def resolve_existing(self, relative_path: str) -> Path:
        return self.paths[relative_path]


class MetaPagePublisherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.bindings = _Bindings()
        self.calls = []
        self.uploads = []
        self.photo_uploads = []
        self.page_video_calls = []
        self.fail_page_video_finish = False
        self.page_video_published = True
        self.page_video_owner_id = "12345"
        self.reel_owner_id = "12345"
        self.temp_dir = tempfile.TemporaryDirectory()
        self.video_path = Path(self.temp_dir.name) / "fixture.mp4"
        self.video_path.write_bytes(b"fixture video data")
        self.video_sha = hashlib.sha256(self.video_path.read_bytes()).hexdigest()
        self.photo_path = Path(self.temp_dir.name) / "fixture.jpg"
        self.photo_path.write_bytes(b"fixture image data")
        self.photo_sha = hashlib.sha256(self.photo_path.read_bytes()).hexdigest()
        self.photo_path2 = Path(self.temp_dir.name) / "fixture-2.png"
        self.photo_path2.write_bytes(b"second fixture image data")
        self.photo_sha2 = hashlib.sha256(self.photo_path2.read_bytes()).hexdigest()
        self.album_uploads = []
        self.album_upload_attempts = []
        self.album_publish_calls = []
        self.album_upload_error_index = None
        self.album_missing_photo_id = False
        self.album_publish_error = False
        self.album_missing_post_id = False
        self.album_post_owner_id = "12345"
        self.album_next_photo_id = 987654320
        self.publisher = MetaPagePublisher(self, self.bindings, _LocalMedia(self.video_path))
        self.publisher._validate_reel_file = lambda _path: None
        self.publisher._validate_page_video_file = lambda _path: None

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def can_publish(tasks: list[str]) -> bool:
        return "CREATE_CONTENT" in tasks

    async def graph_request(self, connection_id, binding_id, method, path, *, params=None, data=None):
        self.calls.append((method, path, params, data))
        if method == "GET" and path == "12345_777":
            return {"id": path, "from": {"id": "12345"},
                    "permalink_url": "https://facebook.com/12345/posts/777"}
        if method == "GET" and path == "12345_888":
            return {"id": path, "from": {"id": self.album_post_owner_id},
                    "permalink_url": "https://facebook.com/12345/posts/888"}
        if method == "GET" and path == "987654321":
            return {"id": path, "from": {"id": "12345"}, "link": "https://facebook.com/photo.php?fbid=987654321"}
        if method == "GET" and path == "2468013579":
            return {"id": path, "from": {"id": self.page_video_owner_id},
                    "permalink_url": "/reel/2468013579/",
                    "status": {"publishing_phase": {
                        "publish_status": "published" if self.page_video_published else "pending",
                    }}}
        if path.endswith("/video_reels") and method == "POST" and data.get("upload_phase") == "start":
            return {"video_id": "1234567", "upload_url": "https://rupload.facebook.com/video-upload/v26.0/1234567"}
        if path.endswith("/video_reels") and method == "POST":
            return {"success": True}
        if method == "GET" and params == {"fields": "id,from,permalink_url,status"}:
            return {"id": "1234567", "from": {"id": self.reel_owner_id},
                    "permalink_url": "/reel/1234567/",
                    "status": {"publishing_phase": {"status": "complete", "publish_status": "published"}}}
        if method == "POST":
            return {"id": "12345_67890"}
        return {"id": "12345_67890", "from": {"id": "12345"}, "permalink_url": "https://facebook.com/12345/posts/67890"}

    async def upload_local_reel(self, connection_id, binding_id, upload_url, file_path, file_size):
        self.uploads.append((connection_id, binding_id, upload_url, file_path, file_size))
        return {"success": True}

    async def publish_local_photo(self, connection_id, binding_id, page_id, filename, mime_type, file_bytes, caption,
                                  *, published=True):
        if published:
            self.photo_uploads.append((connection_id, binding_id, page_id, filename, mime_type, file_bytes, caption))
            return {"id": "987654321", "post_id": "12345_777"}
        self.album_upload_attempts.append(filename)
        index = len(self.album_upload_attempts) - 1
        if index == self.album_upload_error_index:
            raise RuntimeError("simulated photo upload timeout")
        self.album_next_photo_id += 1
        photo_id = str(self.album_next_photo_id)
        self.album_uploads.append((connection_id, binding_id, page_id, filename, mime_type, file_bytes, caption, published))
        return {} if self.album_missing_photo_id else {"id": photo_id}

    async def publish_page_photo_album(self, connection_id, binding_id, page_id, caption, photo_ids):
        self.album_publish_calls.append((connection_id, binding_id, page_id, caption, list(photo_ids)))
        if self.album_publish_error:
            raise RuntimeError("simulated feed publish timeout")
        return {} if self.album_missing_post_id else {"id": "12345_888"}

    async def page_video_request(self, connection_id, binding_id, page_id, data, *, file_chunk=None):
        self.page_video_calls.append((connection_id, binding_id, page_id, dict(data), file_chunk))
        phase = data["upload_phase"]
        if phase == "start":
            return {"video_id": "2468013579", "upload_session_id": "7654321",
                    "start_offset": "0", "end_offset": "5"}
        if phase == "transfer":
            start = int(data["start_offset"])
            next_start = start + len(file_chunk[1])
            size = self.video_path.stat().st_size
            return {"start_offset": str(next_start), "end_offset": str(min(next_start + 5, size))}
        if phase == "finish":
            if self.fail_page_video_finish:
                raise RuntimeError("simulated finish timeout")
            return {"success": True}
        return {"success": True}

    def context(self, dry_run: bool) -> PublishContext:
        return PublishContext(
            job={"id": "job-1", "dry_run": dry_run},
            account={"id": "account-1", "platform": "facebook"},
            payload={"caption": "Tinix test", "content_format": "post", "media": [], "target_id": "target-1",
                     "provider_target_binding_id": "binding-1", "provider_target_external_id": "12345"},
            is_cancelled=lambda: _false(), transition=lambda *_: _noop(),
            record_provider_request=lambda *_args, **_kwargs: _noop(), connection_id="connection-1",
        )

    async def test_dry_run_validates_page_without_sending_graph_request(self) -> None:
        result = await self.publisher.publish(self.context(True))
        self.assertEqual(result.outcome, PublishOutcome.DRY_RUN_READY)
        self.assertEqual(self.calls, [])

    async def test_real_publish_posts_once_then_verifies_page_identity(self) -> None:
        result = await self.publisher.publish(self.context(False))
        self.assertEqual(result.outcome, PublishOutcome.PUBLISHED)
        self.assertEqual([call[0] for call in self.calls], ["POST", "GET"])
        self.assertEqual(result.metadata["page_id"], "12345")

    async def test_rejects_media_during_first_text_only_slice(self) -> None:
        for dry_run in (True, False):
            context = self.context(dry_run)
            context.payload["media"] = [{"type": "image", "path": "local.jpg"}]
            result = await self.publisher.publish(context)
            self.assertEqual(result.outcome, PublishOutcome.UNSUPPORTED)
            self.assertIn("chọn định dạng Ảnh Facebook", result.message)
        self.assertEqual(self.calls, [])

    def reel_context(self, dry_run: bool, *, provider_request_id: str | None = None,
                     provider_request_commit_possible: bool = False) -> PublishContext:
        return PublishContext(
            job={"id": "job-reel-1", "dry_run": dry_run,
                 "provider_request_id": provider_request_id,
                 "provider_request_commit_possible": provider_request_commit_possible},
            account={"id": "account-1", "platform": "facebook"},
            payload={"caption": "Tinix Reel", "content_format": "reel",
                     "media": [{"type": "video", "relative_path": "fixture.mp4",
                                "size_bytes": self.video_path.stat().st_size, "sha256": self.video_sha}],
                     "target_id": "target-1", "provider_target_binding_id": "binding-1",
                     "provider_target_external_id": "12345"},
            is_cancelled=lambda: _false(), transition=lambda *_: _noop(),
            record_provider_request=lambda *_args, **_kwargs: _noop(), connection_id="connection-1",
        )

    def photo_context(self, dry_run: bool, *, provider_request_id: str | None = None,
                      provider_request_commit_possible: bool = False) -> PublishContext:
        return PublishContext(
            job={"id": "job-photo-1", "dry_run": dry_run,
                 "provider_request_id": provider_request_id,
                 "provider_request_commit_possible": provider_request_commit_possible},
            account={"id": "account-1", "platform": "facebook"},
            payload={"caption": "Ảnh Tinix", "content_format": "photo",
                     "media": [{"type": "image", "relative_path": "fixture.jpg", "mime_type": "image/jpeg",
                                "size_bytes": self.photo_path.stat().st_size, "sha256": self.photo_sha}],
                     "target_id": "target-1", "provider_target_binding_id": "binding-1",
                     "provider_target_external_id": "12345"},
            is_cancelled=lambda: _false(), transition=lambda *_: _noop(),
            record_provider_request=lambda *_args, **_kwargs: _noop(), connection_id="connection-1",
        )

    def page_video_context(self, dry_run: bool, *, provider_request_id: str | None = None,
                           provider_request_commit_possible: bool = False) -> PublishContext:
        return PublishContext(
            job={"id": "job-page-video-1", "dry_run": dry_run,
                 "provider_request_id": provider_request_id,
                 "provider_request_commit_possible": provider_request_commit_possible},
            account={"id": "account-1", "platform": "facebook"},
            payload={"caption": "Video Tinix", "content_format": "video",
                     "media": [{"type": "video", "relative_path": "fixture.mp4", "mime_type": "video/mp4",
                                "size_bytes": self.video_path.stat().st_size, "sha256": self.video_sha}],
                     "target_id": "target-1", "provider_target_binding_id": "binding-1",
                     "provider_target_external_id": "12345"},
            is_cancelled=lambda: _false(), transition=lambda *_: _noop(),
            record_provider_request=lambda *_args, **_kwargs: _noop(), connection_id="connection-1",
        )

    def photo_album_context(self, dry_run: bool, *, provider_request_id: str | None = None,
                            provider_request_commit_possible: bool = False) -> PublishContext:
        return PublishContext(
            job={"id": "job-photo-album-1", "dry_run": dry_run,
                 "provider_request_id": provider_request_id,
                 "provider_request_commit_possible": provider_request_commit_possible},
            account={"id": "account-1", "platform": "facebook"},
            payload={"caption": "Album Tinix", "content_format": "multi_photo",
                     "media": [
                         {"type": "image", "relative_path": "fixture.jpg", "mime_type": "image/jpeg",
                          "size_bytes": self.photo_path.stat().st_size, "sha256": self.photo_sha},
                         {"type": "image", "relative_path": "fixture-2.png", "mime_type": "image/png",
                          "size_bytes": self.photo_path2.stat().st_size, "sha256": self.photo_sha2},
                     ],
                     "target_id": "target-1", "provider_target_binding_id": "binding-1",
                     "provider_target_external_id": "12345"},
            is_cancelled=lambda: _false(), transition=lambda *_: _noop(),
            record_provider_request=lambda *_args, **_kwargs: _noop(), connection_id="connection-1",
        )

    async def test_photo_dry_run_checks_local_snapshot_without_provider_calls(self):
        self.publisher.media = _LocalMedia(self.photo_path)
        result = await self.publisher.publish(self.photo_context(True))
        self.assertEqual(result.outcome, PublishOutcome.DRY_RUN_READY)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.photo_uploads, [])

    async def test_photo_publishes_local_image_and_verifies_page_post(self):
        self.publisher.media = _LocalMedia(self.photo_path)
        recorded = []
        context = self.photo_context(False)
        context.record_provider_request = lambda request_id, commit=False: _record(recorded, request_id, commit)
        result = await self.publisher.publish(context)
        self.assertEqual(result.outcome, PublishOutcome.PUBLISHED)
        self.assertEqual(result.metadata["photo_id"], "987654321")
        self.assertEqual(result.metadata["post_id"], "12345_777")
        self.assertEqual(self.photo_uploads[0][2:], (
            "12345", "fixture.jpg", "image/jpeg", b"fixture image data", "Ảnh Tinix",
        ))
        self.assertEqual(self.calls[-1][1], "12345_777")
        self.assertTrue(recorded[-1][1])
        self.assertEqual(json.loads(recorded[-1][0])["photo_id"], "987654321")

    async def test_photo_album_dry_run_checks_every_snapshot_without_uploading(self):
        self.publisher.media = _LocalMediaSet({"fixture.jpg": self.photo_path, "fixture-2.png": self.photo_path2})
        result = await self.publisher.publish(self.photo_album_context(True))
        self.assertEqual(result.outcome, PublishOutcome.DRY_RUN_READY)
        self.assertEqual(result.metadata["content_format"], "multi_photo")
        self.assertEqual(self.album_uploads, [])
        self.assertEqual(self.album_publish_calls, [])
        self.assertEqual(self.calls, [])

    async def test_photo_album_uploads_in_order_then_publishes_and_verifies_one_feed_post(self):
        self.publisher.media = _LocalMediaSet({"fixture.jpg": self.photo_path, "fixture-2.png": self.photo_path2})
        recorded = []
        context = self.photo_album_context(False)
        transitions = []
        current_status = "checking_login"
        async def transition(target, event_type, commit_reached=False):
            nonlocal current_status
            from app.domain.jobs import validate_transition
            validate_transition(current_status, target)
            transitions.append(target)
            current_status = target
        context.transition = transition
        context.record_provider_request = lambda request_id, commit=False: _record(recorded, request_id, commit)
        result = await self.publisher.publish(context)
        self.assertEqual(result.outcome, PublishOutcome.PUBLISHED)
        self.assertEqual(result.post_url, "https://facebook.com/12345/posts/888")
        self.assertEqual(result.metadata["photo_ids"], ["987654321", "987654322"])
        self.assertEqual([item[3] for item in self.album_uploads], ["fixture.jpg", "fixture-2.png"])
        self.assertEqual(self.album_upload_attempts, ["fixture.jpg", "fixture-2.png"])
        self.assertEqual([item[5] for item in self.album_uploads],
                         [b"fixture image data", b"second fixture image data"])
        self.assertTrue(all(item[7] is False for item in self.album_uploads))
        self.assertEqual(transitions, ["uploading", "publishing", "verifying"])
        self.assertEqual(self.album_publish_calls[0][3:],
                         ("Album Tinix", ["987654321", "987654322"]))
        self.assertEqual([call[0] for call in self.calls], ["GET"])
        self.assertTrue(recorded[-1][1])
        self.assertEqual(json.loads(recorded[-1][0])["ph"], "published")

    async def test_photo_album_resumes_after_last_confirmed_upload_without_reuploading_it(self):
        self.publisher.media = _LocalMediaSet({"fixture.jpg": self.photo_path, "fixture-2.png": self.photo_path2})
        context = self.photo_album_context(False)
        media = context.payload["media"]
        snapshot = self.publisher._photo_album_snapshot(media)
        marker = json.dumps({"k": "page_photo_album", "p": "12345", "s": snapshot,
                             "ids": ["987654321"], "n": 1, "u": None, "ph": "uploading", "post": None},
                            separators=(",", ":"), sort_keys=True)
        context.job["provider_request_id"] = marker
        self.album_next_photo_id = 987654321
        result = await self.publisher.publish(context)
        self.assertEqual(result.outcome, PublishOutcome.PUBLISHED)
        self.assertEqual([item[3] for item in self.album_uploads], ["fixture-2.png"])
        self.assertEqual(self.album_upload_attempts, ["fixture-2.png"])
        self.assertEqual(self.album_publish_calls[0][4], ["987654321", "987654322"])

    async def test_photo_album_cancel_after_confirmed_upload_keeps_checkpoint_and_does_not_publish(self):
        self.publisher.media = _LocalMediaSet({"fixture.jpg": self.photo_path, "fixture-2.png": self.photo_path2})
        recorded = []
        context = self.photo_album_context(False)
        context.record_provider_request = lambda request_id, commit=False: _record(recorded, request_id, commit)
        cancellation_checks = iter((False, False, True))
        async def is_cancelled():
            return next(cancellation_checks)
        context.is_cancelled = is_cancelled
        with self.assertRaises(asyncio.CancelledError):
            await self.publisher.publish(context)
        saved = json.loads(recorded[-1][0])
        self.assertEqual((saved["n"], saved["u"], saved["ph"]), (1, None, "uploading"))
        self.assertFalse(recorded[-1][1])
        self.assertEqual(self.album_upload_attempts, ["fixture.jpg"])
        self.assertEqual(self.album_publish_calls, [])

    async def test_photo_album_does_not_repeat_an_uncertain_photo_upload_after_restart(self):
        self.publisher.media = _LocalMediaSet({"fixture.jpg": self.photo_path, "fixture-2.png": self.photo_path2})
        recorded = []
        context = self.photo_album_context(False)
        context.record_provider_request = lambda request_id, commit=False: _record(recorded, request_id, commit)
        self.album_upload_error_index = 1
        first = await self.publisher.publish(context)
        self.assertEqual(first.outcome, PublishOutcome.UNKNOWN_RESULT)
        marker = recorded[-1][0]
        self.assertEqual(json.loads(marker)["u"], 1)
        uploaded_count = len(self.album_uploads)
        retry = self.photo_album_context(False, provider_request_id=marker)
        retried = await self.publisher.publish(retry)
        self.assertEqual(retried.outcome, PublishOutcome.UNKNOWN_RESULT)
        self.assertEqual(len(self.album_uploads), uploaded_count)
        self.assertEqual(self.album_upload_attempts, ["fixture.jpg", "fixture-2.png"])
        self.assertEqual(self.album_publish_calls, [])

    async def test_photo_album_missing_photo_id_stops_before_attaching_and_is_not_retried(self):
        self.publisher.media = _LocalMediaSet({"fixture.jpg": self.photo_path, "fixture-2.png": self.photo_path2})
        recorded = []
        context = self.photo_album_context(False)
        context.record_provider_request = lambda request_id, commit=False: _record(recorded, request_id, commit)
        self.album_missing_photo_id = True
        first = await self.publisher.publish(context)
        self.assertEqual(first.outcome, PublishOutcome.UNKNOWN_RESULT)
        marker = recorded[-1][0]
        self.assertEqual(json.loads(marker)["u"], 0)
        retry = await self.publisher.publish(self.photo_album_context(False, provider_request_id=marker))
        self.assertEqual(retry.outcome, PublishOutcome.UNKNOWN_RESULT)
        self.assertEqual(len(self.album_upload_attempts), 1)
        self.assertEqual(self.album_publish_calls, [])

    async def test_photo_album_commit_timeout_never_reposts_and_published_marker_only_verifies(self):
        self.publisher.media = _LocalMediaSet({"fixture.jpg": self.photo_path, "fixture-2.png": self.photo_path2})
        recorded = []
        context = self.photo_album_context(False)
        context.record_provider_request = lambda request_id, commit=False: _record(recorded, request_id, commit)
        self.album_publish_error = True
        first = await self.publisher.publish(context)
        self.assertEqual(first.outcome, PublishOutcome.UNKNOWN_RESULT)
        marker = recorded[-1][0]
        self.assertTrue(recorded[-1][1])
        self.assertEqual(json.loads(marker)["ph"], "publishing")
        calls_before_retry = len(self.album_publish_calls)
        retry = await self.publisher.publish(self.photo_album_context(
            False, provider_request_id=marker, provider_request_commit_possible=True,
        ))
        self.assertEqual(retry.outcome, PublishOutcome.UNKNOWN_RESULT)
        self.assertEqual(len(self.album_publish_calls), calls_before_retry)

        self.album_publish_error = False
        success_context = self.photo_album_context(False)
        success_context.record_provider_request = lambda request_id, commit=False: _record(recorded, request_id, commit)
        success = await self.publisher.publish(success_context)
        published_marker = recorded[-1][0]
        calls_before_recovery = len(self.album_publish_calls)
        recovered = await self.publisher.publish(self.photo_album_context(
            False, provider_request_id=published_marker, provider_request_commit_possible=True,
        ))
        self.assertEqual(success.outcome, PublishOutcome.PUBLISHED)
        self.assertEqual(recovered.outcome, PublishOutcome.PUBLISHED)
        self.assertEqual(len(self.album_publish_calls), calls_before_recovery)

    async def test_photo_album_missing_post_id_is_unknown_and_never_reposts(self):
        self.publisher.media = _LocalMediaSet({"fixture.jpg": self.photo_path, "fixture-2.png": self.photo_path2})
        recorded = []
        context = self.photo_album_context(False)
        context.record_provider_request = lambda request_id, commit=False: _record(recorded, request_id, commit)
        self.album_missing_post_id = True
        result = await self.publisher.publish(context)
        marker = recorded[-1][0]
        self.assertEqual(result.outcome, PublishOutcome.UNKNOWN_RESULT)
        self.assertTrue(recorded[-1][1])
        self.assertEqual(json.loads(marker)["ph"], "publishing")
        retry = await self.publisher.publish(self.photo_album_context(
            False, provider_request_id=marker, provider_request_commit_possible=True,
        ))
        self.assertEqual(retry.outcome, PublishOutcome.UNKNOWN_RESULT)
        self.assertEqual(len(self.album_publish_calls), 1)

    async def test_photo_album_rejects_wrong_page_verification_without_reposting(self):
        self.publisher.media = _LocalMediaSet({"fixture.jpg": self.photo_path, "fixture-2.png": self.photo_path2})
        self.album_post_owner_id = "another-page"
        result = await self.publisher.publish(self.photo_album_context(False))
        self.assertEqual(result.outcome, PublishOutcome.UNKNOWN_RESULT)
        self.assertEqual(len(self.album_publish_calls), 1)
        self.assertEqual(len(self.album_uploads), 2)

    def test_photo_album_validation_requires_two_through_ten_valid_images(self):
        valid = self.photo_album_context(False).payload
        self.assertEqual(MetaPagePublisher.validate(valid, {}), [])
        for media in (valid["media"][:1], valid["media"] * 6):
            payload = dict(valid, media=media)
            self.assertTrue(MetaPagePublisher.validate(payload, {}))
        bad_mime = dict(valid, media=[dict(valid["media"][0]), dict(valid["media"][1])])
        bad_mime["media"][1]["mime_type"] = "image/jpeg"
        self.assertTrue(MetaPagePublisher.validate(bad_mime, {}))

    async def test_photo_restart_reconciles_saved_id_without_uploading_again(self):
        self.publisher.media = _LocalMedia(self.photo_path)
        marker = json.dumps({"kind": "page_photo", "photo_id": "987654321", "post_id": "12345_777"})
        result = await self.publisher.publish(self.photo_context(
            False, provider_request_id=marker, provider_request_commit_possible=True,
        ))
        self.assertEqual(result.outcome, PublishOutcome.PUBLISHED)
        self.assertEqual(self.photo_uploads, [])
        self.assertEqual(self.calls[0][1], "987654321")

    async def test_page_video_dry_run_checks_snapshot_without_uploading(self):
        result = await self.publisher.publish(self.page_video_context(True))
        self.assertEqual(result.outcome, PublishOutcome.DRY_RUN_READY)
        self.assertEqual(result.metadata["content_format"], "video")
        self.assertEqual(self.page_video_calls, [])

    async def test_page_video_uploads_server_sized_chunks_then_finishes_once(self):
        recorded = []
        context = self.page_video_context(False)
        context.record_provider_request = lambda request_id, commit=False: _record(recorded, request_id, commit)
        result = await self.publisher.publish(context)
        phases = [call[3]["upload_phase"] for call in self.page_video_calls]
        self.assertEqual(result.outcome, PublishOutcome.PUBLISHED)
        self.assertEqual(result.metadata["external_id"], "2468013579")
        self.assertEqual(result.post_url, "https://www.facebook.com/reel/2468013579/")
        self.assertEqual(phases[0], "start")
        self.assertEqual(phases[-1], "finish")
        self.assertTrue(all(phase == "transfer" for phase in phases[1:-1]))
        self.assertEqual([int(call[3]["start_offset"]) for call in self.page_video_calls if call[3]["upload_phase"] == "transfer"],
                         list(range(0, self.video_path.stat().st_size, 5)))
        self.assertTrue(recorded[-3][1])
        self.assertEqual(json.loads(recorded[-3][0])["phase"], "finishing")
        self.assertEqual(json.loads(recorded[-2][0])["phase"], "finish_accepted")
        self.assertEqual(json.loads(recorded[-1][0])["phase"], "complete")
        self.assertEqual(json.loads(recorded[-1][0])["video_id"], "2468013579")

    async def test_page_video_resumes_only_from_last_confirmed_offset(self):
        marker = json.dumps({"kind": "page_video", "page_id": "12345", "size": self.video_path.stat().st_size,
                             "sha256": self.video_sha, "phase": "uploading", "pending": False,
                             "session_id": "7654321", "video_id": "2468013579",
                             "start_offset": 5, "end_offset": 10})
        result = await self.publisher.publish(self.page_video_context(False, provider_request_id=marker))
        self.assertEqual(result.outcome, PublishOutcome.PUBLISHED)
        self.assertNotEqual(self.page_video_calls[0][3]["upload_phase"], "start")
        self.assertEqual(self.page_video_calls[0][3]["start_offset"], "5")

    async def test_page_video_does_not_repeat_an_uncertain_chunk_after_restart(self):
        marker = json.dumps({"kind": "page_video", "page_id": "12345", "size": self.video_path.stat().st_size,
                             "sha256": self.video_sha, "phase": "uploading", "pending": True,
                             "session_id": "7654321", "video_id": "2468013579",
                             "start_offset": 5, "end_offset": 10})
        result = await self.publisher.publish(self.page_video_context(False, provider_request_id=marker))
        self.assertEqual(result.outcome, PublishOutcome.UNKNOWN_RESULT)
        self.assertEqual(self.page_video_calls, [])

    async def test_page_video_recovers_completed_marker_without_meta_call(self):
        marker = json.dumps({"kind": "page_video", "page_id": "12345", "size": self.video_path.stat().st_size,
                             "sha256": self.video_sha, "phase": "complete", "pending": False,
                             "session_id": "7654321", "start_offset": self.video_path.stat().st_size,
                             "end_offset": self.video_path.stat().st_size, "video_id": "2468013579"})
        result = await self.publisher.publish(self.page_video_context(
            False, provider_request_id=marker, provider_request_commit_possible=True,
        ))
        self.assertEqual(result.outcome, PublishOutcome.PUBLISHED)
        self.assertEqual(result.metadata["external_id"], "2468013579")
        self.assertEqual(self.page_video_calls, [])

    async def test_page_video_finish_timeout_is_unknown_and_never_retried(self):
        self.fail_page_video_finish = True
        self.page_video_published = False
        recorded = []
        context = self.page_video_context(False)
        context.record_provider_request = lambda request_id, commit=False: _record(recorded, request_id, commit)
        result = await self.publisher.publish(context)
        self.assertEqual(result.outcome, PublishOutcome.UNKNOWN_RESULT)
        marker = recorded[-1][0]
        self.assertTrue(recorded[-1][1])
        previous_call_count = len(self.page_video_calls)
        with patch("app.platforms.providers.meta.asyncio.sleep", return_value=None):
            retry = await self.publisher.publish(self.page_video_context(
                False, provider_request_id=marker, provider_request_commit_possible=True,
            ))
        self.assertEqual(retry.outcome, PublishOutcome.UNKNOWN_RESULT)
        self.assertEqual(len(self.page_video_calls), previous_call_count)

    async def test_page_video_finish_acceptance_waits_for_publish_and_recovers_without_reposting(self):
        self.page_video_published = False
        recorded = []
        context = self.page_video_context(False)
        context.record_provider_request = lambda request_id, commit=False: _record(recorded, request_id, commit)
        with patch("app.platforms.providers.meta.asyncio.sleep", return_value=None):
            result = await self.publisher.publish(context)
        self.assertEqual(result.outcome, PublishOutcome.UNKNOWN_RESULT)
        marker = recorded[-1][0]
        self.assertEqual(json.loads(marker)["phase"], "finish_accepted")
        previous_call_count = len(self.page_video_calls)
        self.page_video_published = True
        recovered = await self.publisher.publish(self.page_video_context(
            False, provider_request_id=marker, provider_request_commit_possible=True,
        ))
        self.assertEqual(recovered.outcome, PublishOutcome.PUBLISHED)
        self.assertEqual(recovered.post_url, "https://www.facebook.com/reel/2468013579/")
        self.assertEqual(len(self.page_video_calls), previous_call_count)

    async def test_page_video_never_confirms_a_different_page(self):
        self.page_video_owner_id = "other-page"
        with patch("app.platforms.providers.meta.asyncio.sleep", return_value=None):
            result = await self.publisher.publish(self.page_video_context(False))
        self.assertEqual(result.outcome, PublishOutcome.UNKNOWN_RESULT)
        self.assertIsNone(result.post_url)

    async def test_page_video_rejects_changed_file_before_start(self):
        self.video_path.write_bytes(b"different but same-sized")
        result = await self.publisher.publish(self.page_video_context(False))
        self.assertEqual(result.outcome, PublishOutcome.UNSUPPORTED)
        self.assertEqual(self.page_video_calls, [])

    def test_page_video_preflight_needs_ffprobe_and_readable_mp4_metadata(self):
        with patch("app.platforms.providers.meta.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "ffprobe"):
                MetaPagePublisher._validate_page_video_file(self.video_path)
        probe = SimpleNamespace(
            returncode=0,
            stdout='{"streams":[{"width":1280,"height":720}],"format":{"format_name":"mov,mp4,m4a,3gp,3g2,mj2","duration":"12.5"}}',
        )
        with patch("app.platforms.providers.meta.shutil.which", return_value="ffprobe"), \
                patch("app.platforms.providers.meta.subprocess.run", return_value=probe):
            MetaPagePublisher._validate_page_video_file(self.video_path)
        invalid = SimpleNamespace(returncode=0, stdout='{"streams":[],"format":{}}')
        with patch("app.platforms.providers.meta.shutil.which", return_value="ffprobe"), \
                patch("app.platforms.providers.meta.subprocess.run", return_value=invalid):
            with self.assertRaisesRegex(RuntimeError, "không đọc được video MP4"):
                MetaPagePublisher._validate_page_video_file(self.video_path)

    async def test_photo_restart_without_provider_id_never_reposts(self):
        self.publisher.media = _LocalMedia(self.photo_path)
        result = await self.publisher.publish(self.photo_context(
            False, provider_request_id="meta-page-photo:job-photo-1", provider_request_commit_possible=True,
        ))
        self.assertEqual(result.outcome, PublishOutcome.UNKNOWN_RESULT)
        self.assertEqual(self.photo_uploads, [])
        self.assertEqual(self.calls, [])

    async def test_photo_rejects_wrong_mime_oversize_and_multiple_images_before_provider_call(self):
        self.publisher.media = _LocalMedia(self.photo_path)
        context = self.photo_context(False)
        context.payload["media"][0]["mime_type"] = "image/png"
        self.assertEqual((await self.publisher.publish(context)).outcome, PublishOutcome.UNSUPPORTED)
        context = self.photo_context(False)
        context.payload["media"][0]["size_bytes"] = 10 * 1024 * 1024 + 1
        self.assertEqual((await self.publisher.publish(context)).outcome, PublishOutcome.UNSUPPORTED)
        context = self.photo_context(False)
        context.payload["media"].append(dict(context.payload["media"][0]))
        self.assertEqual((await self.publisher.publish(context)).outcome, PublishOutcome.UNSUPPORTED)
        self.assertEqual(self.photo_uploads, [])

    async def test_reel_dry_run_checks_local_snapshot_without_provider_calls(self) -> None:
        result = await self.publisher.publish(self.reel_context(True))
        self.assertEqual(result.outcome, PublishOutcome.DRY_RUN_READY)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.uploads, [])

    async def test_reel_uses_one_local_upload_session_then_verifies_same_video(self) -> None:
        result = await self.publisher.publish(self.reel_context(False))
        self.assertEqual(result.outcome, PublishOutcome.PUBLISHED)
        self.assertEqual(result.post_url, "https://www.facebook.com/reel/1234567/")
        self.assertEqual(result.metadata["external_id"], "1234567")
        self.assertEqual([call[0] for call in self.calls], ["POST", "POST", "GET"])
        self.assertEqual(self.calls[0][3], {"upload_phase": "start"})
        self.assertEqual(self.calls[1][3]["video_state"], "PUBLISHED")
        self.assertEqual(self.uploads[0][2], "https://rupload.facebook.com/video-upload/v26.0/1234567")

    async def test_reel_saves_upload_url_and_commit_marker_for_restart_recovery(self) -> None:
        recorded = []
        context = self.reel_context(False)
        context.record_provider_request = lambda request_id, commit=False: _record(recorded, request_id, commit)
        result = await self.publisher.publish(context)
        self.assertEqual(result.outcome, PublishOutcome.PUBLISHED)
        upload_url = "https://rupload.facebook.com/video-upload/v26.0/1234567"
        self.assertEqual(recorded, [(upload_url, False), (upload_url, True)])

    async def test_reel_recovers_completed_upload_without_creating_or_uploading_session_again(self) -> None:
        upload_url = "https://rupload.facebook.com/video-upload/v26.0/1234567"
        self.graph_request = AsyncMock(side_effect=[
            {"id": "1234567", "status": {"uploading_phase": {"status": "complete"}}},
            {"success": True},
            {"id": "1234567", "from": {"id": "12345"},
             "permalink_url": "/reel/1234567/",
             "status": {"publishing_phase": {"status": "complete", "publish_status": "published"}}},
        ])
        with patch("app.platforms.providers.meta.asyncio.sleep", new=AsyncMock()):
            result = await self.publisher.publish(self.reel_context(False, provider_request_id=upload_url))
        self.assertEqual(result.outcome, PublishOutcome.PUBLISHED)
        self.assertEqual(result.post_url, "https://www.facebook.com/reel/1234567/")
        self.assertEqual([call.args[2] for call in self.graph_request.call_args_list], ["GET", "POST", "GET"])
        self.assertEqual(self.uploads, [])

    async def test_reel_does_not_confirm_a_different_page(self) -> None:
        self.reel_owner_id = "another-page"
        with patch("app.platforms.providers.meta.asyncio.sleep", new=AsyncMock()):
            result = await self.publisher.publish(self.reel_context(False))
        self.assertEqual(result.outcome, PublishOutcome.UNKNOWN_RESULT)
        self.assertEqual(len(self.uploads), 1)
        self.assertEqual(sum(1 for call in self.calls if call[0] == "POST"), 2)

    async def test_reel_recovery_requires_published_status_on_bound_page(self) -> None:
        upload_url = "https://rupload.facebook.com/video-upload/v26.0/1234567"
        self.graph_request = AsyncMock(return_value={
            "id": "1234567", "from": {"id": "another-page"},
            "status": {"publishing_phase": {"status": "complete", "publish_status": "published"}},
        })
        result = await self.publisher.publish(self.reel_context(
            False, provider_request_id=upload_url, provider_request_commit_possible=True,
        ))
        self.assertEqual(result.outcome, PublishOutcome.UNKNOWN_RESULT)
        self.assertEqual(self.graph_request.await_count, 1)
        self.assertEqual(self.uploads, [])

    async def test_reel_restart_with_unfinished_upload_does_not_retry_or_create_second_session(self) -> None:
        upload_url = "https://rupload.facebook.com/video-upload/v26.0/1234567"
        self.graph_request = AsyncMock(return_value={
            "id": "1234567", "status": {"uploading_phase": {"status": "in_progress"}},
        })
        result = await self.publisher.publish(self.reel_context(False, provider_request_id=upload_url))
        self.assertEqual(result.outcome, PublishOutcome.UNKNOWN_RESULT)
        self.assertEqual(self.graph_request.await_count, 1)
        self.assertEqual(self.uploads, [])

    async def test_reel_restart_after_commit_only_reconciles_existing_video(self) -> None:
        upload_url = "https://rupload.facebook.com/video-upload/v26.0/1234567"
        self.graph_request = AsyncMock(return_value={
            "id": "1234567", "status": {"publishing_phase": {"status": "in_progress"}},
        })
        result = await self.publisher.publish(self.reel_context(
            False, provider_request_id=upload_url, provider_request_commit_possible=True,
        ))
        self.assertEqual(result.outcome, PublishOutcome.UNKNOWN_RESULT)
        self.assertEqual(self.graph_request.await_count, 1)
        self.assertEqual(self.uploads, [])

    async def test_reel_rejects_mutated_snapshot_before_creating_provider_session(self) -> None:
        self.video_path.write_bytes(b"changed video")
        result = await self.publisher.publish(self.reel_context(False))
        self.assertEqual(result.outcome, PublishOutcome.UNSUPPORTED)
        self.assertIn("đã đổi", result.message)
        self.assertEqual(self.calls, [])

    def test_reel_preflight_accepts_meta_candidate_spec_and_rejects_wrong_video(self) -> None:
        good = {"streams": [{"width": 1080, "height": 1920, "avg_frame_rate": "30/1"}],
                "format": {"duration": "12.5"}}
        rotated = {"streams": [{"width": 1920, "height": 1080, "avg_frame_rate": "30/1",
                                "side_data_list": [{"rotation": 90}]}],
                   "format": {"duration": "12.5"}}
        bad = {"streams": [{"width": 480, "height": 1000, "avg_frame_rate": "20/1"}],
               "format": {"duration": "120"}}
        with patch("app.platforms.providers.meta.shutil.which", return_value="ffprobe"), \
             patch("app.platforms.providers.meta.subprocess.run",
                   return_value=SimpleNamespace(returncode=0, stdout=json.dumps(good))):
            MetaPagePublisher._validate_reel_file(self.video_path)
        with patch("app.platforms.providers.meta.shutil.which", return_value="ffprobe"), \
             patch("app.platforms.providers.meta.subprocess.run",
                   return_value=SimpleNamespace(returncode=0, stdout=json.dumps(rotated))):
            MetaPagePublisher._validate_reel_file(self.video_path)
        with patch("app.platforms.providers.meta.shutil.which", return_value="ffprobe"), \
             patch("app.platforms.providers.meta.subprocess.run",
                   return_value=SimpleNamespace(returncode=0, stdout=json.dumps(bad))):
            with self.assertRaises(RuntimeError) as raised:
                MetaPagePublisher._validate_reel_file(self.video_path)
        self.assertIn("9:16", str(raised.exception))
        self.assertIn("23 fps", str(raised.exception))
        self.assertIn("4 đến 60", str(raised.exception))

    def test_reel_preflight_fails_clearly_when_ffprobe_is_missing(self) -> None:
        with patch("app.platforms.providers.meta.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "cần ffprobe"):
                MetaPagePublisher._validate_reel_file(self.video_path)

    async def test_reel_unknown_after_finish_never_starts_a_second_session(self) -> None:
        self.graph_request = AsyncMock(side_effect=[
            {"video_id": "1234567", "upload_url": "https://rupload.facebook.com/video-upload/v26.0/1234567"},
            {"success": True}, *[{"id": "1234567", "status": {"publishing_phase": {"status": "in_progress"}}}
                                  for _ in range(8)],
        ])
        with patch("app.platforms.providers.meta.asyncio.sleep", new=AsyncMock()):
            result = await self.publisher.publish(self.reel_context(False))
        self.assertEqual(result.outcome, PublishOutcome.UNKNOWN_RESULT)
        self.assertEqual(sum(1 for call in self.graph_request.call_args_list
                             if call.args[3].endswith("/video_reels") and call.kwargs["data"].get("upload_phase") == "start"), 1)


async def _false() -> bool:
    return False


async def _noop(*_args, **_kwargs) -> None:
    return None


async def _record(records: list[tuple[str, bool]], request_id: str, commit_possible: bool = False) -> None:
    records.append((request_id, commit_possible))


class MetaRoutingTests(unittest.TestCase):
    def test_release_route_freezes_page_binding_and_rejects_changed_binding(self) -> None:
        bindings = _Bindings()
        registry = PublisherRegistry()
        publisher = MetaPagePublisher(_FakeMeta(), bindings)
        registry.register("facebook", publisher, transport="official_api")
        registry.register("facebook", _FakeChromePublisher(), transport="chrome")
        router = PublisherRouter(registry, _Connections(), bindings)
        account = {"id": "account-1", "platform": "facebook"}
        route = router.resolve(account, preference=RoutingPreference.OFFICIAL_API_ONLY,
                               target_id="target-1", target_external_id="url:tiniphotos")
        self.assertEqual(route.transport, "official_api")
        self.assertEqual(route.provider_target_external_id, "12345")
        frozen = router.resolve(account, frozen_transport="official_api", frozen_connection_id="connection-1",
                                frozen_connection_scopes_hash=route.connection_scopes_hash,
                                target_id="target-1", frozen_provider_target_binding_id="binding-1",
                                frozen_provider_target_external_id="12345")
        self.assertEqual(frozen.reason, "transport_frozen_on_release")
        invalid = router.resolve(account, frozen_transport="official_api", frozen_connection_id="connection-1",
                                 frozen_connection_scopes_hash=route.connection_scopes_hash,
                                 target_id="other-target", frozen_provider_target_binding_id="binding-1",
                                 frozen_provider_target_external_id="12345")
        self.assertEqual(invalid.reason, "frozen_connection_unavailable")

    def test_meta_credential_change_invalidates_a_frozen_release_even_with_same_scopes(self) -> None:
        old = {
            "id": "connection-1", "account_id": "account-1", "provider": "meta",
            "status": "connected", "scopes": ["pages_manage_posts"],
            "refresh_metadata": {"auth_method": "system_user", "credential_revision": 1},
        }
        new = {**old, "refresh_metadata": {"auth_method": "system_user", "credential_revision": 2}}
        frozen_hash = PublisherRouter._scopes_hash(old)
        self.assertNotEqual(frozen_hash, PublisherRouter._scopes_hash(new))
        connections = _Connections()
        connections.connection = new
        bindings = _Bindings()
        registry = PublisherRegistry()
        registry.register("facebook", MetaPagePublisher(_FakeMeta(), bindings), transport="official_api")
        route = PublisherRouter(registry, connections, bindings).resolve(
            {"id": "account-1", "platform": "facebook"},
            frozen_transport="official_api", frozen_connection_id="connection-1",
            frozen_connection_scopes_hash=frozen_hash, target_id="target-1",
            frozen_provider_target_binding_id="binding-1",
            frozen_provider_target_external_id="12345",
        )
        self.assertEqual(route.reason, "frozen_connection_unavailable")


class MetaVideoAnalyticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_reel_and_page_video_request_supported_video_fields(self):
        for content_format in ("reel", "video"):
            with self.subTest(content_format=content_format):
                class Publications:
                    @staticmethod
                    def get_release(_release_id):
                        return {"platform": "facebook", "status": "succeeded", "content_format": content_format,
                                "external_release_id": "video-1", "target_id": "target-1",
                                "connection_id": "connection-1"}

                class TargetBindings:
                    @staticmethod
                    def for_target(*_args):
                        return {"id": "binding-1", "connection_id": "connection-1",
                                "external_target_id": "page-1"}

                class Analytics:
                    def __init__(self):
                        self.saved = None
                        self.finished = None

                    @staticmethod
                    def start_run(*_args):
                        return "run-1"

                    def upsert(self, _release_id, values, **kwargs):
                        self.saved = (values, kwargs["provider_metric_names"])
                        return [{"metric_key": key, "value": value} for key, value in values.items()]

                    def finish_run(self, _run_id, status, count, message=None):
                        self.finished = (status, count, message)

                class Meta:
                    @staticmethod
                    async def graph_request(_connection_id, _binding_id, _method, _path, *, params):
                        fields = params["fields"]
                        assert "views" in fields and "shares" not in fields
                        return {"id": "video-1", "from": {"id": "page-1"},
                                "permalink_url": "/reel/video-1/",
                                "likes": {"summary": {"total_count": 0}},
                                "comments": {"summary": {"total_count": 2}}, "views": 3}

                analytics = Analytics()
                collector = MetaAPIAnalyticsCollector(None, Publications(), analytics, Meta(), TargetBindings())
                result = await collector.collect_release("release-1")
                self.assertEqual(result["status"], "succeeded")
                self.assertEqual(result["post_url"], "https://www.facebook.com/reel/video-1/")
                self.assertEqual(analytics.saved[0], {"likes": 0.0, "comments": 2.0, "views": 3.0})
                self.assertEqual(analytics.finished[:2], ("succeeded", 3))


class MetaDeletedPostAnalyticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_post_is_a_recorded_result_and_keeps_old_metrics(self):
        class Publications:
            @staticmethod
            def get_release(_release_id):
                return {"id": "release-1", "platform": "facebook", "status": "succeeded",
                        "external_release_id": "page-id_post-id", "target_id": "target-1",
                        "connection_id": "connection-1"}

        class TargetBindings:
            @staticmethod
            def for_target(*_args):
                return {"id": "binding-1", "connection_id": "connection-1",
                        "external_target_id": "page-id"}

        class Analytics:
            def __init__(self):
                self.finished = None
                self.upsert_calls = 0

            @staticmethod
            def start_run(*_args):
                return "run-1"

            def finish_run(self, _run_id, status, count, message=None):
                self.finished = (status, count, message)

            def upsert(self, *_args, **_kwargs):
                self.upsert_calls += 1
                raise AssertionError("Unavailable posts must not refresh or replace stored metrics")

        class Meta:
            @staticmethod
            async def graph_request(*_args, **_kwargs):
                raise MetaGraphAPIError(400, "100", "Meta Graph API: Object does not exist")

        analytics = Analytics()
        collector = MetaAPIAnalyticsCollector(
            None, Publications(), analytics, Meta(), TargetBindings(),
        )
        result = await collector.collect_release("release-1")
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("đã bị xóa", result["message"])
        self.assertEqual(analytics.finished[0:2], ("unavailable", 0))
        self.assertEqual(analytics.upsert_calls, 0)

    async def test_unrelated_graph_bad_request_is_failed_not_mislabeled_as_deleted_post(self):
        class Publications:
            @staticmethod
            def get_release(_release_id):
                return {"id": "release-1", "platform": "facebook", "status": "succeeded",
                        "external_release_id": "page-id_post-id", "target_id": "target-1",
                        "connection_id": "connection-1"}

        class TargetBindings:
            @staticmethod
            def for_target(*_args):
                return {"id": "binding-1", "connection_id": "connection-1",
                        "external_target_id": "page-id"}

        class Analytics:
            @staticmethod
            def start_run(*_args):
                return "run-1"

            def finish_run(self, _run_id, status, count, message=None):
                self.finished = (status, count, message)

        class Meta:
            @staticmethod
            async def graph_request(*_args, **_kwargs):
                raise MetaGraphAPIError(400, "100", "Meta Graph API: Invalid field selection")

        analytics = Analytics()
        collector = MetaAPIAnalyticsCollector(None, Publications(), analytics, Meta(), TargetBindings())
        result = await collector.collect_release("release-1")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["code"], "meta_provider_error")
        self.assertEqual(analytics.finished[0:2], ("failed", 0))

    async def test_page_permission_error_is_recorded_and_returned_without_server_error(self):
        class Targets:
            @staticmethod
            def get(_target_id):
                return {"id": "target-1", "platform": "facebook"}

        class TargetBindings:
            @staticmethod
            def for_target(_target_id):
                return {"id": "binding-1", "connection_id": "connection-1",
                        "external_target_id": "page-id"}

        class Analytics:
            @staticmethod
            def start_channel_run(*_args):
                return "run-1"

            def finish_channel_run(self, _run_id, status, count, message=None):
                self.finished = (status, count, message)

        class Meta:
            @staticmethod
            async def graph_request(*_args, **_kwargs):
                raise MetaGraphAPIError(400, "200", "Meta Graph API: Permissions error")

        analytics = Analytics()
        collector = MetaAPIAnalyticsCollector(Targets(), None, analytics, Meta(), TargetBindings())
        result = await collector.collect_channel("target-1")
        self.assertEqual(result["status"], "needs_connection")
        self.assertEqual(result["code"], "meta_permission_denied")
        self.assertEqual(analytics.finished[0:2], ("needs_connection", 0))


class _FakeMeta:
    @staticmethod
    def can_publish(_tasks):
        return True


class _FakeChromePublisher:
    platform_id = "facebook"
    publication_transport = "chrome"
    selector_version = "test"


if __name__ == "__main__":
    unittest.main()
