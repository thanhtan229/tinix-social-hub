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
            self.assertEqual(sum(capability_summary(platform).values()), 6)

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


if __name__ == "__main__":
    unittest.main()
