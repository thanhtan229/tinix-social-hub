from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from app.services.instagram_media_delivery import InstagramMediaDelivery, InstagramMediaDeliveryError


ACCOUNT_ID = "a" * 32


class FakeR2Client:
    def __init__(self) -> None:
        self.put_calls: list[dict] = []
        self.sign_calls: list[dict] = []
        self.delete_calls: list[dict] = []

    def put_object(self, **kwargs) -> None:
        kwargs["body_bytes"] = kwargs.pop("Body").read()
        self.put_calls.append(kwargs)

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        self.sign_calls.append({"operation": operation, "params": Params, "expires": ExpiresIn})
        return f"https://tinix-test.{ACCOUNT_ID}.r2.cloudflarestorage.com/{Params['Key']}?signature=fake"

    def delete_object(self, **kwargs) -> None:
        self.delete_calls.append(kwargs)


class InstagramMediaDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "photo.jpg"
        Image.new("RGB", (32, 24), color="navy").save(self.path, "JPEG")
        self.digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.client = FakeR2Client()
        self.factory_calls = []

        def factory(*args, **kwargs):
            self.factory_calls.append((args, kwargs))
            return self.client

        self.settings = SimpleNamespace(
            instagram_r2_account_id=ACCOUNT_ID,
            instagram_r2_bucket="tinix-test",
            instagram_r2_access_key_id="test-access-id",
            instagram_r2_secret_access_key="test-secret-key",
            instagram_r2_url_ttl_seconds=3600,
        )
        self.delivery = InstagramMediaDelivery(self.settings, client_factory=factory)

    def tearDown(self) -> None:
        self.temp.cleanup()

    async def test_uploads_private_jpeg_and_signs_short_lived_get_url(self) -> None:
        result = await self.delivery.create_url(
            self.path, release_id="release-1", sha256=self.digest, mime_type="image/jpeg",
        )
        self.assertEqual(result.object_key, f"tinix-instagram-tmp/release-1/{self.digest}.jpg")
        self.assertEqual(result.expires_in, 3600)
        self.assertEqual(self.client.put_calls[0]["body_bytes"], self.path.read_bytes())
        self.assertEqual(self.client.put_calls[0]["ContentType"], "image/jpeg")
        self.assertEqual(self.client.put_calls[0]["CacheControl"], "private, no-store")
        self.assertEqual(self.client.sign_calls[0]["operation"], "get_object")
        self.assertEqual(self.client.sign_calls[0]["expires"], 3600)
        self.assertEqual(self.factory_calls[0][1]["endpoint_url"],
                         f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com")

    async def test_refuses_changed_or_non_jpeg_media_before_cloud_access(self) -> None:
        with self.assertRaisesRegex(InstagramMediaDeliveryError, "đã thay đổi"):
            await self.delivery.create_url(
                self.path, release_id="release-1", sha256="0" * 64, mime_type="image/jpeg",
            )
        with self.assertRaisesRegex(InstagramMediaDeliveryError, "JPEG"):
            await self.delivery.create_url(
                self.path, release_id="release-1", sha256=self.digest, mime_type="image/png",
            )
        self.assertEqual(self.factory_calls, [])

    async def test_rejects_images_over_the_provider_decimal_8_mb_limit(self) -> None:
        oversized = Path(self.temp.name) / "large.jpg"
        with oversized.open("wb") as image:
            image.truncate(8_000_001)
        with self.assertRaisesRegex(InstagramMediaDeliveryError, "8 MB"):
            await self.delivery.create_url(
                oversized, release_id="release-1", sha256="0" * 64, mime_type="image/jpeg",
            )
        self.assertEqual(self.factory_calls, [])

    async def test_uploads_private_mp4_for_reels_with_video_content_type(self) -> None:
        video = Path(self.temp.name) / "clip.mp4"
        video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4096)
        digest = hashlib.sha256(video.read_bytes()).hexdigest()
        result = await self.delivery.create_url(video, release_id="release-1", sha256=digest, mime_type="video/mp4")
        self.assertEqual(result.object_key, f"tinix-instagram-tmp/release-1/{digest}.mp4")
        self.assertEqual(self.client.put_calls[0]["ContentType"], "video/mp4")
        self.assertEqual(self.client.put_calls[0]["CacheControl"], "private, no-store")

    async def test_refuses_mp4_over_the_reel_byte_ceiling_before_cloud_access(self) -> None:
        video = Path(self.temp.name) / "big.mp4"
        video.write_bytes(b"\x00" * 16)
        with patch.dict(InstagramMediaDelivery.ALLOWED_TYPES, {"video/mp4": (frozenset({".mp4"}), 8, "mp4")}):
            with self.assertRaisesRegex(InstagramMediaDeliveryError, "100 MB"):
                await self.delivery.create_url(
                    video, release_id="release-1", sha256=hashlib.sha256(video.read_bytes()).hexdigest(),
                    mime_type="video/mp4",
                )
        self.assertEqual(self.client.put_calls, [])

    async def test_unconfigured_delivery_fails_closed(self) -> None:
        settings = SimpleNamespace(**{**vars(self.settings), "instagram_r2_secret_access_key": ""})
        delivery = InstagramMediaDelivery(settings, client_factory=lambda *_args, **_kwargs: self.client)
        with self.assertRaisesRegex(InstagramMediaDeliveryError, "cấu hình Cloudflare R2"):
            await delivery.create_url(
                self.path, release_id="release-1", sha256=self.digest, mime_type="image/jpeg",
            )
        self.assertEqual(self.client.put_calls, [])


if __name__ == "__main__":
    unittest.main()
