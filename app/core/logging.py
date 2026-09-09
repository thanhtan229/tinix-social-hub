from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler

from app.core.config import Settings


class SecretRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._secrets: set[str] = set()

    def add(self, *values: str) -> None:
        with self._lock:
            self._secrets.update(value for value in values if value)

    def discard(self, *values: str) -> None:
        with self._lock:
            for value in values:
                self._secrets.discard(value)

    def values(self) -> list[str]:
        with self._lock:
            return list(self._secrets)


secret_registry = SecretRegistry()


class SecretRedactionFilter(logging.Filter):
    def __init__(self, secrets: list[str] | None = None, registry: SecretRegistry | None = None) -> None:
        super().__init__()
        self.secrets = [secret for secret in (secrets or []) if secret]
        self.registry = registry

    def filter(self, record: logging.LogRecord) -> bool:
        values = [*self.secrets, *(self.registry.values() if self.registry else [])]
        if not values:
            return True
        message = record.getMessage()
        for secret in values:
            message = message.replace(secret, "[REDACTED]")
        record.msg, record.args = message, ()
        return True


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    file_handler = RotatingFileHandler(
        settings.log_dir / "tinix.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    secret_registry.add(settings.ai_api_key, settings.youtube_client_secret)
    redaction = SecretRedactionFilter(registry=secret_registry)
    file_handler.addFilter(redaction)
    root.handlers.clear()
    root.addHandler(file_handler)
    if sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        stream.addFilter(redaction)
        root.addHandler(stream)
