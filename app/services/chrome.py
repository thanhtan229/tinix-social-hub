from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from app.core.config import Settings


@dataclass(slots=True)
class ManagedChrome:
    account_id: str
    pid: int
    port: int
    profile: str
    started_at: str
    started_monotonic: float = 0.0


class ChromeManager:
    """Owns only Chrome processes launched with a Tinix-specific profile path."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sessions_file = settings.data_dir / "chrome_sessions.json"
        self._sessions: dict[str, ManagedChrome] = {}
        self._lock = threading.RLock()
        self._load_sessions()

    def detect_executable(self) -> Path | None:
        candidates: list[Path] = []
        if self.settings.chrome_path:
            candidates.append(Path(self.settings.chrome_path))
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.getenv(variable)
            if base:
                candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
        found = shutil.which("chrome") or shutil.which("chrome.exe")
        if found:
            candidates.append(Path(found))
        return next((path.resolve() for path in candidates if path.is_file()), None)

    def _port_for(self, profile_key: str) -> int:
        base = 12000 + int(hashlib.sha256(profile_key.encode()).hexdigest()[:6], 16) % 20000
        used = {session.port for session in self._sessions.values()}
        for port in range(base, min(base + 200, 65535)):
            if port in used:
                continue
            with socket.socket() as sock:
                sock.settimeout(0.1)
                if sock.connect_ex(("127.0.0.1", port)) != 0:
                    return port
        raise RuntimeError("Không tìm được cổng điều khiển Chrome trống.")

    @staticmethod
    def _path_equal(left: str, right: str) -> bool:
        try:
            return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))
        except OSError:
            return False

    def _owns(self, session: ManagedChrome) -> bool:
        """PID reuse cannot trick Tinix into terminating an unrelated process."""
        try:
            process = psutil.Process(session.pid)
            if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
                return False
            for argument in process.cmdline():
                if argument.lower().startswith("--user-data-dir="):
                    return self._path_equal(argument.split("=", 1)[1].strip('"'), session.profile)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return False
        return False

    @staticmethod
    def _devtools_ready(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return True
        except OSError:
            return False

    def _state(self, session: ManagedChrome) -> str:
        if not self._owns(session):
            return "stopped"
        if self._devtools_ready(session.port):
            return "ready"
        if session.started_monotonic and time.monotonic() - session.started_monotonic < 12:
            return "starting"
        return "unresponsive"

    def _details(self, session: ManagedChrome) -> dict[str, Any]:
        state = self._state(session)
        return {
            "account_id": session.account_id,
            "pid": session.pid,
            "port": session.port,
            "profile": session.profile,
            "started_at": session.started_at,
            "state": state,
            "running": state != "stopped",
            "hung": state == "unresponsive",
        }

    def _persist(self) -> None:
        payload = [{key: value for key, value in asdict(session).items() if key != "started_monotonic"} for session in self._sessions.values()]
        temporary = self._sessions_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self._sessions_file)

    def _load_sessions(self) -> None:
        if not self._sessions_file.exists():
            return
        try:
            payload = json.loads(self._sessions_file.read_text(encoding="utf-8"))
            for item in payload:
                session = ManagedChrome(**item)
                if self._owns(session):
                    self._sessions[session.account_id] = session
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self._sessions = {}
        self._persist()

    def _prune(self) -> None:
        removed = [account_id for account_id, session in self._sessions.items() if not self._owns(session)]
        for account_id in removed:
            self._sessions.pop(account_id, None)
        if removed:
            self._persist()

    def open(self, account: dict[str, Any]) -> dict[str, Any]:
        executable = self.detect_executable()
        if not executable:
            raise FileNotFoundError("Không tìm thấy Google Chrome. Hãy cài Chrome hoặc cấu hình TINIX_CHROME_PATH.")
        account_id = account["id"]
        with self._lock:
            self._prune()
            current = self._sessions.get(account_id)
            if current:
                return self._details(current)
            if len(self._sessions) >= self.settings.max_chrome:
                raise RuntimeError(f"Đã đạt giới hạn {self.settings.max_chrome} Chrome đang chạy.")
            profile = (self.settings.chrome_profile_dir / account["profile_key"]).resolve()
            profile.mkdir(parents=True, exist_ok=True)
            port = self._port_for(account["profile_key"])
            process = subprocess.Popen(
                [str(executable), f"--user-data-dir={profile}", f"--remote-debugging-port={port}", "--no-first-run", "about:blank"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            session = ManagedChrome(
                account_id=account_id,
                pid=process.pid,
                port=port,
                profile=str(profile),
                started_at=datetime.now(timezone.utc).isoformat(),
                started_monotonic=time.monotonic(),
            )
            self._sessions[account_id] = session
            self._persist()
            return self._details(session)

    def status(self, account_id: str | None = None) -> dict[str, Any] | list[dict[str, Any]] | None:
        with self._lock:
            self._prune()
            if account_id:
                session = self._sessions.get(account_id)
                return self._details(session) if session else None
            return [self._details(session) for session in self._sessions.values()]

    def close(self, account_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(account_id)
            if not session:
                return False
            if not self._owns(session):
                self._sessions.pop(account_id, None)
                self._persist()
                return False
            process = psutil.Process(session.pid)
            targets = process.children(recursive=True) + [process]
            for target in reversed(targets):
                try:
                    target.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            _, alive = psutil.wait_procs(targets, timeout=8)
            for target in alive:
                try:
                    target.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            self._sessions.pop(account_id, None)
            self._persist()
            return True

    def close_all(self) -> int:
        with self._lock:
            account_ids = list(self._sessions)
        return sum(1 for account_id in account_ids if self.close(account_id))

