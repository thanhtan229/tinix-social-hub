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
    (2, """
    ALTER TABLE accounts ADD COLUMN login_status TEXT NOT NULL DEFAULT 'unknown';
    ALTER TABLE accounts ADD COLUMN last_login_check_at TEXT;
    ALTER TABLE accounts ADD COLUMN disabled_reason TEXT;
    CREATE TABLE chrome_profiles (
        id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL UNIQUE,
        profile_key TEXT NOT NULL UNIQUE,
        remote_port INTEGER,
        last_pid INTEGER,
        last_started_at TEXT,
        last_seen_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
    );
    INSERT INTO chrome_profiles(id,account_id,profile_key,created_at,updated_at)
        SELECT 'profile-' || id,id,profile_key,created_at,updated_at FROM accounts;
    CREATE TABLE publishing_targets (
        id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        target_type TEXT NOT NULL,
        external_id TEXT NOT NULL,
        name TEXT NOT NULL,
        url TEXT,
        enabled INTEGER NOT NULL DEFAULT 1,
        access_status TEXT NOT NULL DEFAULT 'unknown',
        can_publish INTEGER,
        last_synced_at TEXT,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE,
        UNIQUE(account_id,platform,external_id)
    );
    CREATE INDEX idx_targets_account_enabled ON publishing_targets(account_id,enabled,name);
    CREATE TABLE target_groups (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE target_group_members (
        group_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY(group_id,target_id),
        FOREIGN KEY(group_id) REFERENCES target_groups(id) ON DELETE CASCADE,
        FOREIGN KEY(target_id) REFERENCES publishing_targets(id) ON DELETE CASCADE
    );
    CREATE TABLE app_settings (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """),
    (3, """
    CREATE TABLE brand_profiles (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        products_services TEXT,
        target_audience TEXT,
        tone TEXT,
        pronouns TEXT,
        preferred_keywords_json TEXT NOT NULL DEFAULT '[]',
        forbidden_keywords_json TEXT NOT NULL DEFAULT '[]',
        sample_ctas_json TEXT NOT NULL DEFAULT '[]',
        website TEXT,
        contact_info TEXT,
        hashtag_rules TEXT,
        good_examples_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE prompt_templates (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        operation TEXT NOT NULL,
        system_prompt TEXT NOT NULL,
        user_template TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE content_briefs (
        id TEXT PRIMARY KEY,
        brand_profile_id TEXT,
        title TEXT NOT NULL,
        brief_text TEXT NOT NULL,
        platforms_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(brand_profile_id) REFERENCES brand_profiles(id) ON DELETE SET NULL
    );
    CREATE TABLE content_items (
        id TEXT PRIMARY KEY,
        brand_profile_id TEXT,
        brief_id TEXT,
        title TEXT NOT NULL,
        topic TEXT,
        summary TEXT,
        caption TEXT NOT NULL DEFAULT '',
        hashtags_json TEXT NOT NULL DEFAULT '[]',
        cta TEXT,
        approval_status TEXT NOT NULL DEFAULT 'draft',
        current_revision INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(brand_profile_id) REFERENCES brand_profiles(id) ON DELETE SET NULL,
        FOREIGN KEY(brief_id) REFERENCES content_briefs(id) ON DELETE SET NULL
    );
    CREATE INDEX idx_content_status_updated ON content_items(approval_status,updated_at DESC);
    CREATE TABLE content_media (
        id TEXT PRIMARY KEY,
        content_id TEXT NOT NULL,
        media_type TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        thumbnail_relative_path TEXT,
        original_name TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        sha256 TEXT NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY(content_id) REFERENCES content_items(id) ON DELETE CASCADE,
        UNIQUE(content_id,relative_path)
    );
    CREATE INDEX idx_content_media_order ON content_media(content_id,sort_order);
    CREATE TABLE platform_content_variants (
        id TEXT PRIMARY KEY,
        content_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        caption TEXT NOT NULL DEFAULT '',
        hashtags_json TEXT NOT NULL DEFAULT '[]',
        cta TEXT,
        title TEXT,
        pinned_comment TEXT,
        video_hook TEXT,
        video_script TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(content_id) REFERENCES content_items(id) ON DELETE CASCADE,
        UNIQUE(content_id,platform)
    );
    CREATE TABLE content_revisions (
        id TEXT PRIMARY KEY,
        content_id TEXT NOT NULL,
        revision_number INTEGER NOT NULL,
        snapshot_json TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'user',
        note TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(content_id) REFERENCES content_items(id) ON DELETE CASCADE,
        UNIQUE(content_id,revision_number)
    );
    CREATE TABLE content_approvals (
        id TEXT PRIMARY KEY,
        content_id TEXT NOT NULL,
        revision_id TEXT NOT NULL,
        status TEXT NOT NULL,
        note TEXT,
        requested_at TEXT NOT NULL,
        decided_at TEXT,
        FOREIGN KEY(content_id) REFERENCES content_items(id) ON DELETE CASCADE,
        FOREIGN KEY(revision_id) REFERENCES content_revisions(id) ON DELETE CASCADE
    );
    CREATE INDEX idx_approvals_content_status ON content_approvals(content_id,status,requested_at DESC);
    CREATE TABLE ai_generations (
        id TEXT PRIMARY KEY,
        brief_id TEXT,
        brand_profile_id TEXT,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        operation TEXT NOT NULL,
        request_json TEXT NOT NULL,
        response_json TEXT,
        status TEXT NOT NULL,
        error_code TEXT,
        error_message TEXT,
        latency_ms INTEGER,
        created_at TEXT NOT NULL,
        finished_at TEXT,
        FOREIGN KEY(brief_id) REFERENCES content_briefs(id) ON DELETE SET NULL,
        FOREIGN KEY(brand_profile_id) REFERENCES brand_profiles(id) ON DELETE SET NULL
    );
    CREATE TABLE ai_usage (
        id TEXT PRIMARY KEY,
        generation_id TEXT NOT NULL UNIQUE,
        prompt_tokens INTEGER,
        completion_tokens INTEGER,
        total_tokens INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY(generation_id) REFERENCES ai_generations(id) ON DELETE CASCADE
    );
    """),
    (4, """
    CREATE TABLE jobs_v4 (
        id TEXT PRIMARY KEY,
        account_id TEXT,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        content_id TEXT,
        target_id TEXT,
        approval_id TEXT,
        scheduled_at TEXT,
        next_attempt_at TEXT,
        priority INTEGER NOT NULL DEFAULT 100,
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        idempotency_key TEXT,
        dry_run INTEGER NOT NULL DEFAULT 1,
        missed_policy TEXT NOT NULL DEFAULT 'confirm',
        error TEXT,
        failure_code TEXT,
        result_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        cancel_requested INTEGER NOT NULL DEFAULT 0,
        commit_reached_at TEXT,
        locked_at TEXT,
        lease_expires_at TEXT,
        correlation_id TEXT,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE RESTRICT,
        FOREIGN KEY(content_id) REFERENCES content_items(id) ON DELETE RESTRICT,
        FOREIGN KEY(target_id) REFERENCES publishing_targets(id) ON DELETE RESTRICT,
        FOREIGN KEY(approval_id) REFERENCES content_approvals(id) ON DELETE RESTRICT
    );
    INSERT INTO jobs_v4(
        id,account_id,kind,status,payload_json,scheduled_at,attempts,max_attempts,error,
        result_json,created_at,updated_at,started_at,finished_at,cancel_requested,dry_run
    ) SELECT
        id,account_id,kind,
        CASE status WHEN 'failed' THEN 'permanent_failure' WHEN 'running' THEN 'queued' WHEN 'waiting_user' THEN 'checkpoint' ELSE status END,
        payload_json,scheduled_at,attempts,max_attempts,error,result_json,created_at,updated_at,
        CASE WHEN status='running' THEN NULL ELSE started_at END,finished_at,cancel_requested,
        CASE WHEN kind='publish' THEN 1 ELSE 0 END
    FROM jobs;
    DROP TABLE jobs;
    ALTER TABLE jobs_v4 RENAME TO jobs;
    CREATE INDEX idx_jobs_status_due ON jobs(status,next_attempt_at,scheduled_at,priority,created_at);
    CREATE INDEX idx_jobs_account_status ON jobs(account_id,status);
    CREATE INDEX idx_jobs_target_schedule ON jobs(target_id,scheduled_at);
    CREATE UNIQUE INDEX idx_jobs_idempotency ON jobs(idempotency_key) WHERE idempotency_key IS NOT NULL;
    CREATE UNIQUE INDEX idx_jobs_no_duplicate_active_publish
        ON jobs(content_id,target_id,scheduled_at)
        WHERE kind='publish' AND dry_run=0 AND status NOT IN ('succeeded','permanent_failure','cancelled');
    CREATE TABLE publish_job_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        from_status TEXT,
        to_status TEXT NOT NULL,
        event_type TEXT NOT NULL,
        message TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );
    CREATE INDEX idx_job_events_job_created ON publish_job_events(job_id,created_at);
    CREATE TABLE publish_attempts (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        attempt_number INTEGER NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        outcome TEXT,
        failure_code TEXT,
        error_message TEXT,
        result_json TEXT,
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
        UNIQUE(job_id,attempt_number)
    );
    CREATE TABLE browser_error_artifacts (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        attempt_id TEXT,
        artifact_type TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
        FOREIGN KEY(attempt_id) REFERENCES publish_attempts(id) ON DELETE SET NULL
    );
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
        database_existed = self.path.exists() and self.path.stat().st_size > 0
        with self.connection() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            current = connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
        pending = [(version, sql) for version, sql in MIGRATIONS if version > current]
        if not pending:
            return False
        if database_existed and current > 0:
            self.create_backup(reason=f"pre-migration-v{pending[0][0]}")
        with self.connection() as connection:
            for version, sql in pending:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    for statement in sql.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                    connection.execute("INSERT INTO schema_version(version, applied_at) VALUES (?, ?)", (version, utc_now()))
                    connection.execute("COMMIT")
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        integrity = self.integrity_check()
        if not integrity["ok"]:
            raise RuntimeError(f"Database không đạt integrity check sau migration: {integrity['result']}")
        return True

    def ping(self) -> dict[str, Any]:
        try:
            with self.connection() as connection:
                connection.execute("SELECT 1").fetchone()
            return {"ok": True, "result": "ok"}
        except sqlite3.Error as exc:
            return {"ok": False, "result": type(exc).__name__}

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
