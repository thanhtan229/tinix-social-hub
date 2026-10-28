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


class ReelAPI(InstagramAPI):
    """Fake Graph API for Reels: the container reports IN_PROGRESS twice before FINISHED."""

    REEL_CONTAINER_ID = "17900000000000030"
    REEL_MEDIA_ID = "17900000000000031"

    def __init__(self) -> None:
        super().__init__()
        self.polls = 0

    async def graph_request(self, _connection_id, method, path, *, params=None, data=None):
        data = data or {}
        self.calls.append((method, path, params or {}, data))
        if path == f"{TARGET_ID}/media" and method == "POST":
            return {"id": self.REEL_CONTAINER_ID}
        if path == self.REEL_CONTAINER_ID and method == "GET":
            self.polls += 1
            status = "IN_PROGRESS" if self.polls <= 2 else "FINISHED"
            return {"id": path, "status_code": status, "status": status.title()}
        if path.endswith("/media_publish") and method == "POST":
            return {"id": self.REEL_MEDIA_ID}
        if path == self.REEL_MEDIA_ID and method == "GET":
            return {"id": path, "media_type": "VIDEO", "permalink": "https://www.instagram.com/reel/rl123/"}
        raise AssertionError(f"Unexpected Instagram API request: {method} {path}")


class Media:
    def __init__(self, path: Path, by_name: dict[str, Path] | None = None) -> None:
        self.path = path
        self.by_name = by_name or {}

    def resolve_existing(self, relative_path):
        return self.by_name.get(relative_path, self.path)


class CarouselAPI(InstagramAPI):
    """Fake Graph API for carousel: children get unique ids, parent CAROUSEL container, CAROUSEL_ALBUM media."""

    CHILD_IDS = ("17900000000000011", "17900000000000012", "17900000000000013")
    CAROUSEL_ID = "17900000000000020"
    CAROUSEL_MEDIA_ID = "17900000000000021"

    def __init__(self, *, fail_publish: bool = False) -> None:
        super().__init__(fail_publish=fail_publish)
        self.child_index = 0

    async def graph_request(self, _connection_id, method, path, *, params=None, data=None):
        data = data or {}
        self.calls.append((method, path, params or {}, data))
        if path == f"{TARGET_ID}/media" and method == "POST":
            if data.get("is_carousel_item") == "true":
                child = self.CHILD_IDS[self.child_index]
                self.child_index += 1
                return {"id": child}
            return {"id": self.CAROUSEL_ID}
        if method == "GET" and (path in self.CHILD_IDS or path == self.CAROUSEL_ID):
            return {"id": path, "status_code": "FINISHED", "status": "Finished"}
        if path.endswith("/media_publish") and method == "POST":
            if self.fail_publish:
                raise RuntimeError("simulated timeout after sending publish")
            return {"id": self.CAROUSEL_MEDIA_ID}
        if path == self.CAROUSEL_MEDIA_ID and method == "GET":
            return {"id": path, "media_type": "CAROUSEL_ALBUM", "permalink": "https://www.instagram.com/p/car123/"}
        raise AssertionError(f"Unexpected Instagram API request: {method} {path}")


class Delivery:
    def __init__(self, *, configured: bool = True) -> None:
        self.configured = configured
        self.created: list[dict] = []
        self.deleted: list[str] = []

    async def create_url(self, path, **kwargs):
        self.created.append({"path": path, **kwargs})
        return InstagramMediaUrl(
            url="https://tinix-test.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.r2.cloudflarestorage.com/photo?sig=test",
            object_key=f"tinix-instagram-tmp/release-1/{Path(path).name}", expires_in=3600,
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

    def _carousel_setup(self):
        second = Path(self.temp.name) / "photo2.jpg"
        Image.new("RGB", (50, 40), color="orange").save(second, "JPEG")
        third = Path(self.temp.name) / "photo3.jpg"
        Image.new("RGB", (60, 50), color="purple").save(third, "JPEG")
        paths = {"photo.jpg": self.image, "photo2.jpg": second, "photo3.jpg": third}
        media = [
            {"type": "image", "relative_path": name, "mime_type": "image/jpeg",
             "size_bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for name, path in paths.items()
        ]
        return paths, media

    def _carousel_context(self, media, *, dry_run: bool, transitions: list, requests: list, marker: str = "") -> PublishContext:
        context = self._context(dry_run=dry_run, transitions=transitions, requests=requests, marker=marker)
        context.payload["content_format"] = "carousel"
        context.payload["media"] = media[: len(media)]
        return context

    def _carousel_publisher(self, api, paths, delivery=None):
        return InstagramOfficialPublisher(
            Connections(), api, Media(self.image, paths), delivery or Delivery(), poll_interval_seconds=0,
        )

    async def test_carousel_dry_run_checks_every_item_without_cloud_or_graph_writes(self) -> None:
        paths, media = self._carousel_setup()
        api, delivery = CarouselAPI(), Delivery(configured=False)
        result = await self._carousel_publisher(api, paths, delivery).publish(
            self._carousel_context(media, dry_run=True, transitions=[], requests=[]),
        )
        self.assertEqual(result.outcome, PublishOutcome.DRY_RUN_READY)
        self.assertEqual(result.metadata["media_count"], 3)
        self.assertEqual(api.calls, [])
        self.assertEqual(delivery.created, [])

    async def test_carousel_publish_creates_children_then_parent_then_verifies_album(self) -> None:
        paths, media = self._carousel_setup()
        api, delivery = CarouselAPI(), Delivery()
        transitions, requests = [], []
        result = await self._carousel_publisher(api, paths, delivery).publish(
            self._carousel_context(media, dry_run=False, transitions=transitions, requests=requests),
        )
        self.assertEqual(result.outcome, PublishOutcome.PUBLISHED)
        self.assertEqual(result.post_url, "https://www.instagram.com/p/car123/")
        creates = [call[3] for call in api.calls if call[0] == "POST" and call[1] == f"{TARGET_ID}/media"]
        self.assertEqual(len(creates), 4)
        self.assertEqual([c.get("is_carousel_item") for c in creates[:3]], ["true", "true", "true"])
        self.assertEqual(creates[3]["media_type"], "CAROUSEL")
        self.assertEqual(creates[3]["children"], ",".join(CarouselAPI.CHILD_IDS))
        publish_calls = [call for call in api.calls if call[1].endswith("/media_publish")]
        self.assertEqual(len(publish_calls), 1)
        self.assertEqual(publish_calls[0][3], {"creation_id": CarouselAPI.CAROUSEL_ID})
        self.assertTrue(requests[-1][1])
        self.assertEqual(sorted(delivery.deleted), sorted([
            "tinix-instagram-tmp/release-1/photo.jpg",
            "tinix-instagram-tmp/release-1/photo2.jpg",
            "tinix-instagram-tmp/release-1/photo3.jpg",
        ]))

    async def test_carousel_resume_creates_only_missing_children_and_no_second_parent(self) -> None:
        paths, media = self._carousel_setup()
        api, delivery = CarouselAPI(), Delivery()
        state = {"v": 2, "release": "release-1", "sha": hashlib.sha256(
            "".join(item["sha256"] for item in media).encode()).hexdigest(),
            "children": [CarouselAPI.CHILD_IDS[0]], "container": "", "stage": "children"}
        marker = InstagramOfficialPublisher.MARKER_PREFIX + json.dumps(state)
        result = await self._carousel_publisher(api, paths, delivery).publish(
            self._carousel_context(media, dry_run=False, transitions=[], requests=[], marker=marker),
        )
        self.assertEqual(result.outcome, PublishOutcome.PUBLISHED)
        child_creates = [call for call in api.calls if call[1] == f"{TARGET_ID}/media" and call[3].get("is_carousel_item")]
        self.assertEqual(len(child_creates), 2)
        self.assertEqual(len(delivery.created), 2)
        parent_creates = [call for call in api.calls if call[1] == f"{TARGET_ID}/media" and call[3].get("media_type") == "CAROUSEL"]
        self.assertEqual(len(parent_creates), 1)

    async def test_carousel_unknown_publish_response_is_not_retried(self) -> None:
        paths, media = self._carousel_setup()
        api = CarouselAPI(fail_publish=True)
        result = await self._carousel_publisher(api, paths).publish(
            self._carousel_context(media, dry_run=False, transitions=[], requests=[]),
        )
        self.assertEqual(result.outcome, PublishOutcome.UNKNOWN_RESULT)
        self.assertEqual(sum(call[1].endswith("/media_publish") for call in api.calls), 1)

    def test_carousel_validation_requires_two_to_ten_jpeg_items(self) -> None:
        _, media = self._carousel_setup()
        one = {"content_format": "carousel", "caption": "c", "media": media[:1]}
        self.assertTrue(any("từ 2 đến 10" in e for e in InstagramOfficialPublisher.validate(one, {})))
        eleven = {"content_format": "carousel", "caption": "c", "media": media * 4}
        self.assertTrue(any("từ 2 đến 10" in e for e in InstagramOfficialPublisher.validate(eleven, {})))
        two = {"content_format": "carousel", "caption": "c", "media": media[:2]}
        self.assertEqual(InstagramOfficialPublisher.validate(two, {}), [])

    def _reel_setup(self):
        video = Path(self.temp.name) / "clip.mp4"
        video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048)
        digest = hashlib.sha256(video.read_bytes()).hexdigest()
        media = [{"type": "video", "relative_path": "clip.mp4", "mime_type": "video/mp4",
                  "size_bytes": video.stat().st_size, "sha256": digest}]
        return video, media

    def _reel_context(self, media, *, dry_run: bool, transitions: list, requests: list, marker: str = "") -> PublishContext:
        context = self._context(dry_run=dry_run, transitions=transitions, requests=requests, marker=marker)
        context.payload["content_format"] = "reel"
        context.payload["media"] = media
        return context

    async def test_reel_publish_uses_reels_container_waits_for_processing_and_verifies_video(self) -> None:
        video, media = self._reel_setup()
        api = ReelAPI()
        delivery = Delivery()
        publisher = InstagramOfficialPublisher(
            Connections(), api, Media(self.image, {"clip.mp4": video}), delivery, poll_interval_seconds=0,
        )
        transitions, requests = [], []
        result = await publisher.publish(self._reel_context(media, dry_run=False, transitions=transitions, requests=requests))
        self.assertEqual(result.outcome, PublishOutcome.PUBLISHED)
        self.assertEqual(result.post_url, "https://www.instagram.com/reel/rl123/")
        create = [call for call in api.calls if call[0] == "POST" and call[1] == f"{TARGET_ID}/media"][0]
        self.assertEqual(create[3]["media_type"], "REELS")
        self.assertTrue(create[3]["video_url"].startswith("https://"))
        self.assertEqual(api.polls, 3)
        self.assertEqual(delivery.deleted, ["tinix-instagram-tmp/release-1/clip.mp4"])
        self.assertEqual(delivery.created[0]["mime_type"], "video/mp4")

    async def test_reel_dry_run_validates_without_cloud_or_graph_calls(self) -> None:
        video, media = self._reel_setup()
        api, delivery = ReelAPI(), Delivery()
        publisher = InstagramOfficialPublisher(
            Connections(), api, Media(self.image, {"clip.mp4": video}), delivery, poll_interval_seconds=0,
        )
        result = await publisher.publish(self._reel_context(media, dry_run=True, transitions=[], requests=[]))
        self.assertEqual(result.outcome, PublishOutcome.DRY_RUN_READY)
        self.assertEqual(api.calls, [])
        self.assertEqual(delivery.created, [])

    def test_reel_validation_requires_one_mp4_within_limit(self) -> None:
        _, media = self._reel_setup()
        ok = {"content_format": "reel", "caption": "c", "media": media}
        self.assertEqual(InstagramOfficialPublisher.validate(ok, {}), [])
        as_photo = {"content_format": "reel", "caption": "c", "media": [{
            "type": "image", "relative_path": "photo.jpg", "mime_type": "image/jpeg",
            "size_bytes": 10, "sha256": self.digest}]}
        self.assertTrue(InstagramOfficialPublisher.validate(as_photo, {}))
        too_big = {"content_format": "reel", "caption": "c", "media": [{**media[0], "size_bytes": 100_000_001}]}
        self.assertTrue(any("100 MB" in e for e in InstagramOfficialPublisher.validate(too_big, {})))
        two = {"content_format": "reel", "caption": "c", "media": media * 2}
        self.assertTrue(InstagramOfficialPublisher.validate(two, {}))

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
