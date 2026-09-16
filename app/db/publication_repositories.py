from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
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
        requested_routing_policy: str = "chrome_preferred",
        publication_transport: str | None = None,
        provider: str | None = None,
        provider_version: str | None = None,
        routing_reason: str | None = None,
        connection_id: str | None = None,
    ) -> dict[str, Any]:
        existing = self.get_release_by_idempotency(idempotency_key)
        if existing:
            return existing
        release_id, now = str(uuid.uuid4()), utc_now()
        status = "scheduled" if scheduled_at and scheduled_at > now else "queued"
        try:
            with self.db.connection() as connection:
                connection.execute(
                    "INSERT INTO publication_releases(id,plan_id,content_id,content_revision_id,account_id,target_id,platform,content_format,status,scheduled_at,settings_json,payload_snapshot_json,media_snapshot_json,selector_version,requested_routing_policy,publication_transport,provider,provider_version,routing_reason,connection_id,idempotency_key,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        release_id, plan_id, content_id, content_revision_id, account_id, target_id,
                        platform, content_format, status, scheduled_at, _json(settings),
                        _json(payload_snapshot), _json(media_snapshot), selector_version, requested_routing_policy,
                        publication_transport, provider, provider_version, routing_reason, connection_id,
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

    def dry_run_evidence(
        self,
        *,
        account_id: str,
        target_id: str,
        content_format: str,
        transport: str,
        selector_version: str | None,
        provider_version: str | None,
    ) -> dict[str, Any] | None:
        """Return the newest route-matched dry-run evidence, if it is still current."""
        clauses = [
            "account_id=?", "target_id=?", "content_format=?", "status='dry_run_ready'",
            "COALESCE(publication_transport, 'chrome')=?",
        ]
        params: list[Any] = [account_id, target_id, content_format, transport]
        if selector_version:
            clauses.append("selector_version=?")
            params.append(selector_version)
        if provider_version:
            clauses.append("provider_version=?")
            params.append(provider_version)
        where = " AND ".join(clauses)
        with self.db.connection() as connection:
            row = connection.execute(
                f"SELECT * FROM publication_releases WHERE {where} ORDER BY updated_at DESC LIMIT 1",
                params,
            ).fetchone()
        return row_to_dict(row)

    def account_readiness(
        self, account_id: str, *, platform: str, selector_version: str | None,
    ) -> list[dict[str, Any]]:
        """Show the current attempt and the last success for each publish route."""
        with self.db.connection() as connection:
            rows = [dict(row) for row in connection.execute(
                """SELECT target_id,content_format,publication_transport,provider,provider_version,
                          selector_version,status,verification_status,updated_at,
                          COALESCE(verified_at,published_at,updated_at) AS completed_at
                   FROM publication_releases
                   WHERE account_id=? AND platform=?
                   ORDER BY updated_at DESC""",
                (account_id, platform),
            )]
        latest: dict[tuple[str, str, str], dict[str, Any]] = {}
        last_success: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in rows:
            transport = str(row.get("publication_transport") or "chrome")
            key = (str(row["target_id"]), str(row["content_format"]), transport)
            latest.setdefault(key, row)
            if row["status"] in {"dry_run_ready", "succeeded"}:
                last_success.setdefault(key, row)
        result: list[dict[str, Any]] = []
        failures = {"temporary_failure", "permanent_failure", "login_required", "checkpoint", "unknown_result"}
        pending = {"scheduled", "queued", "pending_approval", "approved", "opening_browser", "checking_login", "uploading", "publishing", "verifying"}
        for key, row in latest.items():
            transport = key[2]
            successful = last_success.get(key)
            if row["status"] in failures:
                state = "attention_required"
            elif row["status"] in pending:
                state = "latest_attempt_pending"
            elif transport == "chrome" and selector_version and successful and successful.get("selector_version") != selector_version:
                state = "review_required"
            elif successful and successful.get("verification_status") == "verified":
                state = "real_publish_verified"
            elif successful and successful.get("status") == "succeeded":
                state = "published_unverified"
            elif successful:
                state = "dry_run_ready"
            else:
                state = "no_successful_evidence"
            result.append({
                "target_id": key[0], "content_format": key[1], "transport": transport,
                "provider": row.get("provider"), "provider_version": row.get("provider_version"),
                "selector_version": row.get("selector_version"), "state": state,
                "latest_status": row["status"], "latest_at": row.get("updated_at"),
                "last_success_status": successful.get("status") if successful else None,
                "last_success_at": successful.get("completed_at") if successful else None,
                "completed_at": successful.get("completed_at") if successful else None,
            })
        return sorted(result, key=lambda item: (item["target_id"], item["content_format"], item["transport"]))

    def release_detail(self, release_id: str) -> dict[str, Any] | None:
        release = self.get_release(release_id)
        if not release:
            return None
        release["events"] = self.release_events(release_id)
        with self.db.connection() as connection:
            release["job"] = row_to_dict(connection.execute(
                "SELECT * FROM jobs WHERE id=?", (release.get("job_id"),)
            ).fetchone()) if release.get("job_id") else None
            release["attempts"] = [dict(row) for row in connection.execute(
                "SELECT * FROM publish_attempts WHERE job_id=? ORDER BY attempt_number", (release.get("job_id"),)
            )] if release.get("job_id") else []
            release["artifacts"] = [dict(row) for row in connection.execute(
                "SELECT * FROM browser_error_artifacts WHERE job_id=? ORDER BY created_at DESC", (release.get("job_id"),)
            )] if release.get("job_id") else []
        return release

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

    def release_events(self, release_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM publication_release_events WHERE release_id=? ORDER BY id", (release_id,)
            )]

    def reschedule_release(self, release_id: str, scheduled_at: str, timezone_name: str) -> dict[str, Any]:
        due = datetime.fromisoformat(scheduled_at)
        if due.tzinfo is None:
            raise ValueError("Thời gian reschedule cần timezone.")
        due_utc = due.astimezone(timezone.utc).isoformat()
        now = utc_now()
        target_status = "scheduled" if due_utc > now else "queued"
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                release = connection.execute("SELECT * FROM publication_releases WHERE id=?", (release_id,)).fetchone()
                if not release:
                    raise KeyError(release_id)
                job = connection.execute("SELECT * FROM jobs WHERE id=?", (release["job_id"],)).fetchone()
                allowed = {"scheduled", "queued", "pending_approval", "approved", "draft"}
                if not job or job["status"] not in allowed or job["commit_reached_at"]:
                    raise ValueError("Release đã chạy hoặc không còn an toàn để đổi lịch.")
                connection.execute(
                    "UPDATE publication_releases SET scheduled_at=?,timezone=?,status=?,rescheduled_at=?,updated_at=? WHERE id=?",
                    (due_utc, timezone_name, target_status, now, now, release_id),
                )
                connection.execute(
                    "UPDATE jobs SET scheduled_at=?,status=?,next_attempt_at=NULL,updated_at=? WHERE id=?",
                    (due_utc, target_status, now, job["id"]),
                )
                connection.execute(
                    "INSERT INTO publication_release_events(release_id,event_type,from_status,to_status,metadata_json,created_at) VALUES(?,?,?,?,?,?)",
                    (
                        release_id, "rescheduled", release["status"], target_status,
                        _json({"from": release["scheduled_at"], "to": due_utc, "timezone": timezone_name}), now,
                    ),
                )
                connection.execute(
                    "INSERT INTO publish_job_events(job_id,from_status,to_status,event_type,metadata_json,created_at) VALUES(?,?,?,?,?,?)",
                    (
                        job["id"], job["status"], target_status, "rescheduled",
                        _json({"scheduled_at": due_utc, "timezone": timezone_name}), now,
                    ),
                )
                plan_id = release["plan_id"]
                plan_due = connection.execute(
                    "SELECT MIN(scheduled_at) FROM publication_releases WHERE plan_id=?", (plan_id,)
                ).fetchone()[0]
                statuses = [row[0] for row in connection.execute(
                    "SELECT status FROM publication_releases WHERE plan_id=?", (plan_id,)
                )]
                if all(status == "scheduled" for status in statuses):
                    plan_status = "scheduled"
                elif any(status in {"opening_browser", "checking_login", "uploading", "publishing", "verifying"} for status in statuses):
                    plan_status = "active"
                else:
                    plan_status = "queued"
                connection.execute(
                    "UPDATE publication_plans SET scheduled_at=?,timezone=?,status=?,updated_at=? WHERE id=?",
                    (plan_due, timezone_name, plan_status, now, plan_id),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get_release(release_id)

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
