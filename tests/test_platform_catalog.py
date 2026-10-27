from __future__ import annotations

import unittest

from app.platforms import PLATFORM_CATALOG, capability_summary, get_platform
from app.services.publishers import Publisher, PublisherRegistry


class PlatformCatalogTests(unittest.TestCase):
    def test_ids_are_unique_and_lookup_is_normalized(self) -> None:
        ids = [platform.id for platform in PLATFORM_CATALOG]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(get_platform(" Instagram ").id, "instagram")
        self.assertIsNone(get_platform("threads"))

    def test_every_provider_is_chrome_operational_with_review_gate(self) -> None:
        operational = [platform.id for platform in PLATFORM_CATALOG if platform.operational]
        self.assertEqual(operational, ["facebook", "instagram", "tiktok", "youtube", "x"])
        for platform in PLATFORM_CATALOG:
            self.assertEqual(platform.publication_transport, "chrome")
            if platform.id != "facebook":
                self.assertEqual(platform.capabilities.publishing, "review_required")
                self.assertEqual(platform.capabilities.result_verification, "review_required")

    def test_capability_summary_accounts_for_every_boundary(self) -> None:
        for platform in PLATFORM_CATALOG:
            summary = capability_summary(platform)
            self.assertEqual(set(summary), {"ready", "review_required", "scaffold", "not_started", "deferred"})
            self.assertEqual(sum(summary.values()), 7)

    def test_x_post_schema_supports_text_and_media(self) -> None:
        platform = get_platform("x")
        self.assertIsNotNone(platform)
        schema = platform.format_schemas[0]
        self.assertEqual((schema.id, schema.max_caption_length), ("post", 280))
        self.assertEqual((schema.min_media, schema.max_media), (0, 4))

    def test_runtime_registry_keys_publishers_by_transport(self) -> None:
        class ApiPublisher(Publisher):
            publication_transport = "official_api"

            async def publish(self, context):
                raise AssertionError("must not run")

        registry = PublisherRegistry()
        publisher = ApiPublisher()
        registry.register("instagram", publisher)
        self.assertIs(registry.get("instagram", dry_run=False, transport="official_api"), publisher)
        self.assertEqual(registry.transports("instagram"), ("official_api",))

    def test_youtube_official_api_is_ready_only_for_video_formats(self) -> None:
        transport = get_platform("youtube").transport("official_api")
        self.assertEqual(transport.readiness, "ready")
        self.assertEqual(transport.content_formats, ("video", "short"))
        self.assertNotIn("community_post", transport.content_formats)

    def test_catalog_only_exposes_formats_implemented_by_the_active_transport(self) -> None:
        self.assertEqual(get_platform("instagram").content_formats, ("image", "carousel"))
        self.assertEqual(get_platform("tiktok").content_formats, ("short_video",))
        self.assertEqual(get_platform("youtube").content_formats, ("video", "short"))

    def test_instagram_official_photo_publisher_is_review_gated_until_live_acceptance(self) -> None:
        transport = get_platform("instagram").transport("official_api")
        self.assertEqual(transport.content_formats, ("image",))
        self.assertEqual(transport.authentication, "review_required")
        self.assertEqual(transport.publishing, "review_required")
        self.assertEqual(transport.readiness, "review_required")
        self.assertIn("instagram_business_content_publish", transport.required_scopes)

    def test_facebook_catalog_exposes_separate_api_media_formats(self) -> None:
        facebook = get_platform("facebook")
        self.assertEqual(facebook.phase, "Page API text/photo album/video + Reel")
        self.assertEqual(facebook.content_formats, ("post", "photo", "multi_photo", "video", "reel"))
        self.assertEqual(facebook.transport("chrome").content_formats, ("post",))
        self.assertEqual(facebook.transport("official_api").content_formats,
                         ("post", "photo", "multi_photo", "video", "reel"))
        photo = next(item for item in facebook.format_schemas if item.id == "photo")
        self.assertEqual((photo.min_media, photo.max_media, photo.allowed_media_types), (1, 1, ("image",)))
        album = next(item for item in facebook.format_schemas if item.id == "multi_photo")
        self.assertEqual((album.min_media, album.max_media, album.allowed_media_types),
                         (2, 10, ("image",)))
        video = next(item for item in facebook.format_schemas if item.id == "video")
        self.assertEqual((video.min_media, video.max_media, video.allowed_media_types), (1, 1, ("video",)))


if __name__ == "__main__":
    unittest.main()
