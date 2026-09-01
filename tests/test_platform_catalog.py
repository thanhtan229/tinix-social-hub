from __future__ import annotations

import unittest

from app.platforms import PLATFORM_CATALOG, capability_summary, get_platform


class PlatformCatalogTests(unittest.TestCase):
    def test_ids_are_unique_and_lookup_is_normalized(self) -> None:
        ids = [platform.id for platform in PLATFORM_CATALOG]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(get_platform(" Instagram ").id, "instagram")
        self.assertIsNone(get_platform("threads"))

    def test_only_facebook_is_operational_during_architecture_review(self) -> None:
        operational = [platform.id for platform in PLATFORM_CATALOG if platform.operational]
        self.assertEqual(operational, ["facebook"])
        for platform in PLATFORM_CATALOG:
            self.assertEqual(platform.publication_transport, "chrome")
            if platform.id != "facebook":
                self.assertEqual(platform.capabilities.publishing, "not_started")
                self.assertEqual(platform.capabilities.result_verification, "not_started")

    def test_capability_summary_accounts_for_every_boundary(self) -> None:
        for platform in PLATFORM_CATALOG:
            self.assertEqual(sum(capability_summary(platform).values()), 6)


if __name__ == "__main__":
    unittest.main()
