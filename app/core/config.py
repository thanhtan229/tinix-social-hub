from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _path(name: str, default: str) -> Path:
    value = os.getenv(name, default).strip()
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path
    host: str
    port: int
    open_browser: bool
    embedded_worker: bool
    max_concurrent_jobs: int
    max_chrome: int
    job_poll_seconds: int
    scheduler_seconds: int
    close_chrome_after_job: bool
    screenshot_retention_days: int
    temp_retention_hours: int
    maintenance_seconds: int
    data_dir: Path
    media_dir: Path
    export_dir: Path
    backup_dir: Path
    log_dir: Path
    screenshot_dir: Path
    chrome_profile_dir: Path
    chrome_path: str
    ai_base_url: str
    ai_model: str
    ai_api_key: str
    ai_timeout_seconds: int
    ai_max_retries: int

    @property
    def database_path(self) -> Path:
        return self.data_dir / "tinix_social.db"

    @property
    def temp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def web_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir, self.media_dir, self.export_dir, self.backup_dir,
            self.log_dir, self.screenshot_dir, self.chrome_profile_dir, self.temp_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_dotenv(PROJECT_ROOT / ".env")
    host = os.getenv("TINIX_HOST", "127.0.0.1").strip()
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Bản PC chỉ được bind WebUI vào 127.0.0.1 hoặc localhost.")
    settings = Settings(
        project_root=PROJECT_ROOT,
        host=host,
        port=_int("TINIX_PORT", 8765, 1024, 65535),
        open_browser=_bool("TINIX_OPEN_BROWSER", True),
        embedded_worker=_bool("TINIX_EMBEDDED_WORKER", True),
        max_concurrent_jobs=_int("TINIX_MAX_CONCURRENT_JOBS", 2, 1, 8),
        max_chrome=_int("TINIX_MAX_CHROME", 2, 1, 8),
        job_poll_seconds=_int("TINIX_JOB_POLL_SECONDS", 2, 1, 30),
        scheduler_seconds=_int("TINIX_SCHEDULER_SECONDS", 15, 5, 300),
        close_chrome_after_job=_bool("TINIX_CLOSE_CHROME_AFTER_JOB", False),
        screenshot_retention_days=_int("TINIX_SCREENSHOT_RETENTION_DAYS", 14, 1, 365),
        temp_retention_hours=_int("TINIX_TEMP_RETENTION_HOURS", 48, 1, 720),
        maintenance_seconds=_int("TINIX_MAINTENANCE_SECONDS", 21600, 300, 86400),
        data_dir=_path("TINIX_DATA_DIR", "data"),
        media_dir=_path("TINIX_MEDIA_DIR", "media"),
        export_dir=_path("TINIX_EXPORT_DIR", "exports"),
        backup_dir=_path("TINIX_BACKUP_DIR", "data/backups"),
        log_dir=_path("TINIX_LOG_DIR", "logs"),
        screenshot_dir=_path("TINIX_SCREENSHOT_DIR", "screenshots"),
        chrome_profile_dir=_path("TINIX_CHROME_PROFILE_DIR", "chrome_profiles"),
        chrome_path=os.getenv("TINIX_CHROME_PATH", "").strip(),
        ai_base_url=os.getenv("TINIX_AI_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        ai_model=os.getenv("TINIX_AI_MODEL", "deepseek-chat").strip(),
        ai_api_key=os.getenv("TINIX_AI_API_KEY", "").strip(),
        ai_timeout_seconds=_int("TINIX_AI_TIMEOUT_SECONDS", 60, 5, 600),
        ai_max_retries=_int("TINIX_AI_MAX_RETRIES", 2, 0, 5),
    )
    settings.ensure_directories()
    return settings
