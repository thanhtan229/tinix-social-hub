from __future__ import annotations

import logging
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.core.logging import SecretRedactionFilter
from app.services.maintenance import MaintenanceService


class MaintenanceTests(unittest.TestCase):
    def test_only_old_files_under_managed_root_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "old.png"
            fresh = root / "fresh.png"
            old.write_bytes(b"old")
            fresh.write_bytes(b"fresh")
            old_time = time.time() - 3600
            os.utime(old, (old_time, old_time))
            removed, failed = MaintenanceService.cleanup_files(root, older_than_seconds=60)
            self.assertEqual((removed, failed), (1, 0))
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())


class LoggingSafetyTests(unittest.TestCase):
    def test_api_key_is_redacted_from_message_and_arguments(self) -> None:
        record = logging.LogRecord("test", logging.ERROR, __file__, 1, "Request failed for %s", ("secret-key",), None)
        filter_ = SecretRedactionFilter(["secret-key"])
        self.assertTrue(filter_.filter(record))
        self.assertNotIn("secret-key", record.getMessage())
        self.assertIn("[REDACTED]", record.getMessage())


if __name__ == "__main__":
    unittest.main()

