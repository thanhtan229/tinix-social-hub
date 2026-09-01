from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    file_handler = RotatingFileHandler(
        settings.log_dir / "tinix.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream)

