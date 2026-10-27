from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from app.platforms.providers.instagram import InstagramOfficialPublisher
from app.domain.jobs import JobStatus, validate_transition
from app.services.instagram_accounts import INSTAGRAM_SCOPES
from app.services.instagram_media_delivery import InstagramMediaUrl
from app.services.publishers import PublishContext, PublishOutcome


TARGET_ID = "17841400000000000"
MEDIA_ID = "17900000000000001"
CONTAINER_ID = "17900000000000002"


class Connections:
    def __init__(self, scopes=INSTAGRAM_SCOPES) -> None:
        self.connection = {
            "id": "connection-1", "account_id": "account-1", "provider": "instagram",
            "status": "connected", "external_account_id": TARGET_ID, "scopes": list(scopes),
        }

    def get(self, connection_id):
        return self.connection if connection_id == self.connection["id"] else None


class InstagramAPI:
    def __init__(self, *, fail_publish: bool = False) -> None:
        self.calls: list[tuple[str, str, dict, dict]] = []
        self.fail_publish = fail_publish
        self.access_token_calls = 0

    async def access_token(self, _connection_id, _account_id):
        self.access_token_calls += 1
        return "token"

    async def graph_request(self, _connection_id, method, path, *, params=None, data=None):
        self.calls.append((method, path, params or {}, data or {}))
        if path.endswith("/media") and method == "POST":
            return {"id": CONTAINER_ID}
        if path == CONTAINER_ID and method == "GET":
            return {"id": CONTAINER_ID, "status_code": "FINISHED", "status": "Finished"}
        if path.endswith("/media_publish") and method == "POST":
            if self.fail_publish:
                raise RuntimeError("simulated timeout after sending publish")
            return {"id": MEDIA_ID}
        if path == MEDIA_ID and method == "GET":
            return {"id": MEDIA_ID, "media_type": "IMAGE", "permalink": "https://www.instagram.com/p/abc123/"}
        raise AssertionError(f"Unexpected Instagram API request: {method} {path}")


class Media:
    def __init__(self, path: Path) -> None:
        self.path = path

    def resolve_existing(self, _relative_path):
        return self.path


class Delivery:
    def __init__(self, *, configured: bool = True) -> None:
        self.configured = configured
        self.created: list[dict] = []
        self.deleted: list[str] = []

    async def create_url(self, path, **kwargs):
        self.created.append({"path": path, **kwargs})
        return InstagramMediaUrl(
            url="https://tinix-test.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.r2.cloudflarestorage.com/photo?sig=test",
            object_key="tinix-instagram-tmp/release-1/photo.jpg", expires_in=3600,
        )

    async def delete(self, key):
        self.deleted.append(key)


class InstagramOfficialPublisherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.image = Path(self.temp.name) / "photo.jpg"
        Image.new("RGB", (40, 30), color="teal").save(self.image, "JPEG")
        self.digest = hashlib.sha256(self.image.read_bytes()).hexdigest()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _context(self, *, dry_run: bool, transitions: list, requests: list, marker: str = "") -> PublishContext:
        current_status = JobStatus.CHECKING_LOGIN

        async def transition(*args):
            nonlocal current_status
            next_status = validate_transition(current_status, args[0])[1]
            current_status = next_status
            transitions.append(args)

        async def record(*args):
            requests.append(args)

        return PublishContext(
            job={"id": "job-1", "publication_release_id": "release-1", "dry_run": int(dry_run),
                 "provider_request_id": marker},
            account={"id": "account-1", "platform": "instagram"},
            payload={
                "content_format": "image", "caption": "A Tinix photo",
                "target_external_id": TARGET_ID, "publication_release_id": "release-1",
                "media": [{"type": "image", "relative_path": "photo.jpg", "mime_type": "image/jpeg",
                           "size_bytes": self.image.stat().st_size, "sha256": self.digest}],
            },
            is_cancelled=lambda: asyncio.sleep(0, result=False),
            transition=transition, record_provider_request=record, connection_id="connection-1",
        )

    def _publisher(self, api, delivery=None, scopes=INSTAGRAM_SCOPES):
        return InstagramOfficialPublisher(
            Connections(scopes), api, Media(self.image), delivery or Delivery(), poll_interval_seconds=0,
        )

    async def test_dry_run_checks_local_inputs_without_cloud_or_graph_writes(self) -> None:
        api, delivery = InstagramAPI(), Delivery(configured=False)
        publisher = self._publisher(api, delivery)
        transitions, requests = [], []
        result = await publisher.publish(self._context(dry_run=True, transitions=transitions, requests=requests))
        self.assertEqual(result.outcome, PublishOutcome.DRY_RUN_READY)
        self.assertFalse(result.metadata["media_delivery_configured"])
        self.assertEqual(api.calls, [])
        self.assertEqual(delivery.created, [])
        self.assertEqual(transitions, [])
        self.assertEqual(requests, [])

    async def test_real_publish_persists_commit_point_and_verifies_permalink(self) -> None:
        api, delivery = InstagramAPI(), Delivery()
        publisher = self._publisher(api, delivery)
        transitions, requests = [], []
        result = await publisher.publish(self._context(dry_run=False, transitions=transitions, requests=requests))
        self.assertEqual(result.outcome, PublishOutcome.PUBLISHED)
        self.assertEqual(result.post_url, "https://www.instagram.com/p/abc123/")
        self.assertEqual([call[1] for call in api.calls], [
            f"{TARGET_ID}/media", CONTAINER_ID, f"{TARGET_ID}/media_publish", MEDIA_ID,
        ])
        self.assertTrue(requests[-1][1])
        self.assertEqual(
            transitions[-2:],
            [("publishing", "instagram_media_publish_started", True),
             ("verifying", "instagram_media_publish_confirmed", True)],
        )
        self.assertEqual(delivery.deleted, ["tinix-instagram-tmp/release-1/photo.jpg"])

    async def test_resume_from_container_checkpoint_does_not_create_a_second_container(self) -> None:
        api, delivery = InstagramAPI(), Delivery()
        state = {"v": 1, "release": "release-1", "sha": self.digest,
                 "container": CONTAINER_ID, "stage": "container_ready",
                 "key": "tinix-instagram-tmp/release-1/photo.jpg"}
        marker = InstagramOfficialPublisher.MARKER_PREFIX + json.dumps(state)
        result = await self._publisher(api, delivery).publish(
            self._context(dry_run=False, transitions=[], requests=[], marker=marker),
        )
        self.assertEqual(result.outcome, PublishOutcome.PUBLISHED)
        self.assertEqual(delivery.created, [])
        self.assertEqual(api.calls[0][1], CONTAINER_ID)

    async def test_unknown_publish_response_is_not_retried_automatically(self) -> None:
        api = InstagramAPI(fail_publish=True)
        result = await self._publisher(api).publish(
            self._context(dry_run=False, transitions=[], requests=[]),
        )
        self.assertEqual(result.outcome, PublishOutcome.UNKNOWN_RESULT)
        self.assertEqual(sum(call[1] == f"{TARGET_ID}/media" for call in api.calls), 1)
        self.assertFalse(any(call[1] == MEDIA_ID for call in api.calls))

    async def test_wrong_profile_and_missing_publish_scope_fail_before_external_calls(self) -> None:
        api = InstagramAPI()
        wrong_target = self._context(dry_run=True, transitions=[], requests=[])
        wrong_target.payload["target_external_id"] = "17841400000000009"
        result = await self._publisher(api).publish(wrong_target)
        self.assertEqual(result.outcome, PublishOutcome.UNSUPPORTED)
        missing_scope = await self._publisher(api, scopes=("instagram_business_basic",)).publish(
            self._context(dry_run=True, transitions=[], requests=[]),
        )
        self.assertEqual(missing_scope.outcome, PublishOutcome.LOGIN_REQUIRED)
        self.assertEqual(api.calls, [])

    def test_validation_rejects_media_over_8_mb_before_r2_upload(self) -> None:
        payload = {
            "content_format": "image", "caption": "Caption",
            "media": [{"type": "image", "relative_path": "photo.jpg", "mime_type": "image/jpeg",
                       "size_bytes": 8_000_001, "sha256": self.digest}],
        }
        errors = InstagramOfficialPublisher.validate(payload, {})
        self.assertTrue(any("8 MB" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
