from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import BinaryIO


class WorkerLock:
    """Kernel-owned lock, outside the data tree replaced by recovery bundles."""

    def __init__(self, database_path: Path) -> None:
        path = database_path.resolve()
        key = hashlib.sha256(os.path.normcase(str(path)).encode()).hexdigest()[:24]
        self.path = path.parent.parent / f".tinix-worker-{key}.lock"
        self._handle: BinaryIO | None = None

    def acquire(self) -> None:
        if self._handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise RuntimeError("Một worker khác đang sở hữu database này; không khởi động worker thứ hai.") from exc
        self._handle = handle

    @property
    def held(self) -> bool:
        return self._handle is not None

    def release(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
