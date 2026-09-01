from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.db.database import Database, row_to_dict, utc_now


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class PublicationRepository:
    """Durable planning records separated from executable jobs."""

    def __init__(self, database: Database) -> None:
        self.db = database

    def create_plan(
        self,
        *,
        content_id: str,
        content_revision_id: str,
        approval_id: str | None,
        dry_run: bool,
        scheduled_at: str | None,
        missed_policy: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        existing = self.get_plan_by_idempotency(idempotency_key)
        if existing:
            return existing
        plan_id, now = str(uuid.uuid4()), utc_now()
        status = "scheduled" if scheduled_at and scheduled_at > now else "queued"
        try:
            with self.db.connection() as connection:
                connection.execute(
                    "INSERT INTO publication_plans(id,content_id,content_revision_id,approval_id,status,dry_run,scheduled_at,missed_policy,idempotency_key,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        plan_id, content_id, content_revision_id, approval_id, status, int(dry_run),
                        scheduled_at, missed_policy, idempotency_key, now, now,
                    ),
                )
        except sqlite3.IntegrityError:
            existing = self.get_plan_by_idempotency(idempotency_key)
            if existing:
                return existing
            raise
        return self.get_plan(plan_id)

    def create_release(
        self,
        *,
        plan_id: str,
        content_id: str,
        content_revision_id: str,
        account_id: str,
        target_id: str,
        platform: str,
        content_format: str,
        scheduled_at: str | None,
        settings: dict[str, Any],
        payload_snapshot: dict[str, Any],
        media_snapshot: list[dict[str, Any]],
        selector_version: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        existing = self.get_release_by_idempotency(idempotency_key)
        if existing:
            return existing
        release_id, now = str(uuid.uuid4()), utc_now()
        status = "scheduled" if scheduled_at and scheduled_at > now else "queued"
        try:
            with self.db.connection() as connection:
                connection.execute(
                    "INSERT INTO publication_releases(id,plan_id,content_id,content_revision_id,account_id,target_id,platform,content_format,status,scheduled_at,settings_json,payload_snapshot_json,media_snapshot_json,selector_version,idempotency_key,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        release_id, plan_id, content_id, content_revision_id, account_id, target_id,
                        platform, content_format, status, scheduled_at, _json(settings),
                        _json(payload_snapshot), _json(media_snapshot), selector_version,
                        idempotency_key, now, now,
                    ),
                )
        except sqlite3.IntegrityError:
            existing = self.get_release_by_idempotency(idempotency_key)
            if existing:
                return existing
            raise
        return self.get_release(release_id)

    def attach_job(self, release_id: str, job_id: str) -> dict[str, Any]:
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "UPDATE publication_releases SET job_id=?,updated_at=? WHERE id=? AND (job_id IS NULL OR job_id=?)",
                    (job_id, utc_now(), release_id, job_id),
                )
                connection.execute(
                    "UPDATE jobs SET publication_release_id=?,updated_at=? WHERE id=?",
                    (release_id, utc_now(), job_id),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get_release(release_id)

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            plan = row_to_dict(connection.execute("SELECT * FROM publication_plans WHERE id=?", (plan_id,)).fetchone())
            if not plan:
                return None
            plan["releases"] = [
                row_to_dict(row) for row in connection.execute(
                    "SELECT * FROM publication_releases WHERE plan_id=? ORDER BY scheduled_at,created_at", (plan_id,)
                )
            ]
            return plan

    def get_plan_by_idempotency(self, key: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            row = connection.execute("SELECT id FROM publication_plans WHERE idempotency_key=?", (key,)).fetchone()
        return self.get_plan(row[0]) if row else None

    def get_release(self, release_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            return row_to_dict(connection.execute("SELECT * FROM publication_releases WHERE id=?", (release_id,)).fetchone())

    def get_release_by_idempotency(self, key: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            return row_to_dict(connection.execute(
                "SELECT * FROM publication_releases WHERE idempotency_key=?", (key,)
            ).fetchone())

    def list_plans(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            ids = [row[0] for row in connection.execute(
                "SELECT id FROM publication_plans ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
            )]
        return [self.get_plan(plan_id) for plan_id in ids]

    def list_releases(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        platform: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        clauses, params = [], []
        if start:
            clauses.append("COALESCE(scheduled_at,created_at)>=?")
            params.append(start)
        if end:
            clauses.append("COALESCE(scheduled_at,created_at)<=?")
            params.append(end)
        if platform:
            clauses.append("platform=?")
            params.append(platform.lower())
        if status:
            clauses.append("status=?")
            params.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(limit, 1000)))
        with self.db.connection() as connection:
            return [row_to_dict(row) for row in connection.execute(
                f"SELECT * FROM publication_releases{where} ORDER BY COALESCE(scheduled_at,created_at),created_at LIMIT ?",
                params,
            )]

    def sync_from_job(self, job: dict[str, Any]) -> None:
        release_id = job.get("publication_release_id")
        if not release_id:
            return
        result = job.get("result") or {}
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE publication_releases SET status=?,external_url=COALESCE(?,external_url),published_at=CASE WHEN ?='succeeded' THEN COALESCE(published_at,?) ELSE published_at END,updated_at=? WHERE id=?",
                (job["status"], result.get("post_url"), job["status"], job.get("finished_at"), utc_now(), release_id),
            )
