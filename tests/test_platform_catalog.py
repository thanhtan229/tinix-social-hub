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
        self.assertEqual(operational, ["facebook", "instagram", "tiktok", "youtube"])
        for platform in PLATFORM_CATALOG:
            self.assertEqual(platform.publication_transport, "chrome")
            if platform.id != "facebook":
                self.assertEqual(platform.capabilities.publishing, "review_required")
                self.assertEqual(platform.capabilities.result_verification, "review_required")

    def test_capability_summary_accounts_for_every_boundary(self) -> None:
        for platform in PLATFORM_CATALOG:
            self.assertEqual(sum(capability_summary(platform).values()), 6)

    def test_runtime_registry_rejects_non_chrome_publishers(self) -> None:
        class ApiPublisher(Publisher):
            publication_transport = "api"

            async def publish(self, context):
                raise AssertionError("must not run")

        with self.assertRaises(ValueError):
            PublisherRegistry().register("instagram", ApiPublisher())


if __name__ == "__main__":
    unittest.main()
