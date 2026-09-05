from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.platforms.providers.youtube import YouTubeOfficialPublisher
from app.services.publishers import PublishContext, PublishOutcome


class Connections:
    def __init__(self) -> None:
        self.status_updates = []

    def list(self, **_kwargs):
        return [{"id": "connection-1", "provider": "youtube", "status": "connected"}]

    def set_status(self, *args, **kwargs):
        self.status_updates.append((args, kwargs))


class ProviderAccounts:
    async def access_token(self, _connection_id):
        return "access-token"


class Media:
    def __init__(self, path: Path) -> None:
        self.path = path

    def resolve_existing(self, _relative_path):
        return self.path


class FakeYouTubeClient:
    def __init__(self) -> None:
        self.put_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, **_kwargs):
        return httpx.Response(
            200,
            headers={
                "Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=req-1",
                "X-GUploader-UploadID": "req-1",
            },
            request=httpx.Request("POST", url),
        )

    async def put(self, url, **_kwargs):
        self.put_calls += 1
        return httpx.Response(201, json={"id": "video-1"}, request=httpx.Request("PUT", url))

    async def get(self, url, **_kwargs):
        return httpx.Response(200, json={"items": [{"id": "video-1"}]}, request=httpx.Request("GET", url))


class YouTubeOfficialPublisherTests(unittest.IsolatedAsyncioTestCase):
    def _context(self, *, dry_run: bool, transitions: list, requests: list) -> PublishContext:
        async def transition(*args):
            transitions.append(args)

        async def record(*args):
            requests.append(args)

        return PublishContext(
            job={"id": "job-1", "dry_run": int(dry_run)},
            account={"id": "account-1", "platform": "youtube"},
            payload={
                "content_format": "video", "title": "Tinix demo", "caption": "Demo",
                "media": [{"type": "video", "relative_path": "demo.mp4"}],
                "platform_settings": {"privacy": "private"},
            },
            is_cancelled=lambda: asyncio.sleep(0, result=False),
            transition=transition,
            record_provider_request=record,
        )

    async def test_dry_run_does_not_create_upload_session(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            video = Path(root) / "demo.mp4"
            video.write_bytes(b"video")
            publisher = YouTubeOfficialPublisher(
                SimpleNamespace(provider_timeout_seconds=30), Connections(), ProviderAccounts(), Media(video),
            )
            transitions, requests = [], []
            with patch("app.platforms.providers.youtube.httpx.AsyncClient") as client:
                result = await publisher.publish(self._context(dry_run=True, transitions=transitions, requests=requests))
            self.assertEqual(result.outcome, PublishOutcome.DRY_RUN_READY)
            client.assert_not_called()
            self.assertEqual(requests, [])
            self.assertFalse(any(item[2] for item in transitions))

    async def test_real_upload_marks_commit_and_verifies_video(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            video = Path(root) / "demo.mp4"
            video.write_bytes(b"video")
            publisher = YouTubeOfficialPublisher(
                SimpleNamespace(provider_timeout_seconds=30), Connections(), ProviderAccounts(), Media(video),
            )
            transitions, requests = [], []
            client = FakeYouTubeClient()
            with patch("app.platforms.providers.youtube.httpx.AsyncClient", return_value=client):
                result = await publisher.publish(self._context(dry_run=False, transitions=transitions, requests=requests))
            self.assertEqual(result.outcome, PublishOutcome.PUBLISHED)
            self.assertEqual(result.post_url, "https://www.youtube.com/watch?v=video-1")
            self.assertEqual(client.put_calls, 1)
            self.assertIn(("verifying", "youtube_upload_started", True), transitions)
            self.assertEqual(requests[-1], ("req-1", True))

    def test_rejects_provider_redirect_to_another_host(self) -> None:
        with self.assertRaises(RuntimeError):
            YouTubeOfficialPublisher._safe_upload_url("https://example.com/upload")


if __name__ == "__main__":
    unittest.main()
