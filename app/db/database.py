from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


MIGRATIONS: list[tuple[int, str]] = [
    (1, """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        platform TEXT NOT NULL,
        profile_key TEXT NOT NULL UNIQUE,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        account_id TEXT,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        scheduled_at TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        error TEXT,
        result_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        cancel_requested INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE RESTRICT
    );
    CREATE INDEX IF NOT EXISTS idx_jobs_status_schedule ON jobs(status, scheduled_at, created_at);
    CREATE INDEX IF NOT EXISTS idx_jobs_account_status ON jobs(account_id, status);
    """),
]


class Database:
    def __init__(self, path: Path, backup_dir: Path) -> None:
        self.path = path
        self.backup_dir = backup_dir

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        schema_changed = False
        with self.connection() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            current = connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
            for version, sql in MIGRATIONS:
                if version <= current:
                    continue
                connection.execute("BEGIN IMMEDIATE")
                try:
                    for statement in sql.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                    connection.execute("INSERT INTO schema_version(version, applied_at) VALUES (?, ?)", (version, utc_now()))
                    connection.execute("COMMIT")
                    schema_changed = True
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        if schema_changed:
            self.create_backup(reason="migration")
        return schema_changed

    def integrity_check(self) -> dict[str, Any]:
        with self.connection() as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        return {"ok": result == "ok", "result": result}

    def create_backup(self, reason: str = "manual", keep: int = 7) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        destination = self.backup_dir / f"tinix-{reason}-{stamp}.db"
        with self.connection() as source, closing(sqlite3.connect(destination)) as target:
            source.backup(target)
        backups = sorted(self.backup_dir.glob("tinix-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[keep:]:
            old.unlink(missing_ok=True)
        return destination

    def list_backups(self) -> list[dict[str, Any]]:
        return [
            {"name": p.name, "size": p.stat().st_size, "modified_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat()}
            for p in sorted(self.backup_dir.glob("tinix-*.db"), key=lambda item: item.stat().st_mtime, reverse=True)
        ]

    def restore_backup(self, name: str) -> None:
        source = (self.backup_dir / Path(name).name).resolve()
        if source.parent != self.backup_dir.resolve() or not source.is_file():
            raise FileNotFoundError("Không tìm thấy bản backup hợp lệ.")
        with closing(sqlite3.connect(source)) as check:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup bị lỗi integrity check.")
        safety = self.create_backup(reason="before-restore", keep=1000)
        try:
            with closing(sqlite3.connect(source)) as backup, closing(sqlite3.connect(self.path)) as target:
                backup.backup(target)
        except Exception:
            with closing(sqlite3.connect(safety)) as backup, closing(sqlite3.connect(self.path)) as target:
                backup.backup(target)
            raise


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for key in ("payload_json", "result_json"):
        if key in result:
            value = result.pop(key)
            result[key.removesuffix("_json")] = json.loads(value) if value else None
    return result
