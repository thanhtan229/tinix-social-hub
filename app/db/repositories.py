from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db.database import Database, row_to_dict, utc_now
from app.domain.jobs import ACCOUNT_BUSY_STATUSES, TERMINAL_STATUSES, JobStatus, validate_transition


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class AccountRepository:
    def __init__(self, database: Database) -> None:
        self.db = database

    def create(self, name: str, platform: str) -> dict[str, Any]:
        account_id = str(uuid.uuid4())
        profile_id = str(uuid.uuid4())
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT INTO accounts(id,name,platform,profile_key,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (account_id, name.strip(), platform.strip().lower(), account_id, now, now),
                )
                connection.execute(
                    "INSERT INTO chrome_profiles(id,account_id,profile_key,created_at,updated_at) VALUES(?,?,?,?,?)",
                    (profile_id, account_id, account_id, now, now),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get(account_id)

    def get(self, account_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            return row_to_dict(connection.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())

    def list(self, include_disabled: bool = True) -> list[dict[str, Any]]:
        query = "SELECT * FROM accounts" + ("" if include_disabled else " WHERE enabled=1") + " ORDER BY created_at DESC"
        with self.db.connection() as connection:
            return [row_to_dict(row) for row in connection.execute(query)]

    def update(self, account_id: str, name: str, platform: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE accounts SET name=?,platform=?,updated_at=? WHERE id=?",
                (name.strip(), platform.strip().lower(), utc_now(), account_id),
            )
        return self.get(account_id)

    def set_enabled(self, account_id: str, enabled: bool, reason: str | None = None) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE accounts SET enabled=?,disabled_reason=?,updated_at=? WHERE id=?",
                (int(enabled), None if enabled else reason, utc_now(), account_id),
            )
        return self.get(account_id)

    def update_login_status(self, account_id: str, status: str) -> None:
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE accounts SET login_status=?,last_login_check_at=?,updated_at=? WHERE id=?",
                (status, now, now, account_id),
            )

    def delete_if_safe(self, account_id: str) -> bool:
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                dependent = connection.execute("SELECT COUNT(*) FROM jobs WHERE account_id=?", (account_id,)).fetchone()[0]
                targets = connection.execute("SELECT COUNT(*) FROM publishing_targets WHERE account_id=?", (account_id,)).fetchone()[0]
                if dependent or targets:
                    connection.execute("ROLLBACK")
                    return False
                cursor = connection.execute("DELETE FROM accounts WHERE id=?", (account_id,))
                connection.execute("COMMIT")
                return cursor.rowcount > 0
            except Exception:
                connection.execute("ROLLBACK")
                raise


class JobRepository:
    def __init__(self, database: Database, retry_base_seconds: int = 30, retry_cap_seconds: int = 1800) -> None:
        self.db = database
        self.retry_base_seconds = retry_base_seconds
        self.retry_cap_seconds = retry_cap_seconds

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        job_id: str,
        from_status: str | None,
        to_status: str,
        event_type: str,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        connection.execute(
            "INSERT INTO publish_job_events(job_id,from_status,to_status,event_type,message,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)",
            (job_id, from_status, to_status, event_type, message, _json(metadata or {}), utc_now()),
        )

    def create(
        self,
        kind: str,
        payload: dict[str, Any],
        account_id: str | None,
        scheduled_at: str | None,
        *,
        dry_run: bool = True,
        content_id: str | None = None,
        target_id: str | None = None,
        approval_id: str | None = None,
        idempotency_key: str | None = None,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        job_id, now = str(uuid.uuid4()), utc_now()
        status = JobStatus.SCHEDULED if scheduled_at and scheduled_at > now else JobStatus.QUEUED
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT INTO jobs(id,account_id,kind,status,payload_json,content_id,target_id,approval_id,scheduled_at,created_at,updated_at,dry_run,idempotency_key,max_attempts,correlation_id) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        job_id, account_id, kind, status.value, _json(payload), content_id, target_id,
                        approval_id, scheduled_at, now, now, int(dry_run), idempotency_key,
                        max(1, min(max_attempts, 10)), str(uuid.uuid4()),
                    ),
                )
                self._event(connection, job_id, None, status.value, "created")
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            return row_to_dict(connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def list(self, limit: int = 100, offset: int = 0, status: str | None = None) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            if status:
                rows = connection.execute(
                    "SELECT * FROM jobs WHERE status=? ORDER BY created_at DESC LIMIT ? OFFSET ?", (status, limit, offset)
                )
            else:
                rows = connection.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))
            return [row_to_dict(row) for row in rows]

    def events(self, job_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM publish_job_events WHERE job_id=? ORDER BY id", (job_id,))]

    def transition(
        self,
        job_id: str,
        target: str | JobStatus,
        *,
        event_type: str = "transition",
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        failure_code: str | None = None,
        next_attempt_at: str | None = None,
        commit_reached: bool = False,
    ) -> dict[str, Any]:
        target_status = JobStatus(target)
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                if not row:
                    raise KeyError(job_id)
                _, validated_target = validate_transition(row["status"], target_status)
                finished_at = now if validated_target in TERMINAL_STATUSES else None
                connection.execute(
                    "UPDATE jobs SET status=?,updated_at=?,finished_at=?,result_json=COALESCE(?,result_json),error=?,failure_code=?,next_attempt_at=?,"
                    "commit_reached_at=CASE WHEN ? THEN COALESCE(commit_reached_at,?) ELSE commit_reached_at END WHERE id=?",
                    (
                        validated_target.value, now, finished_at, _json(result) if result is not None else None,
                        error[:2000] if error else None, failure_code, next_attempt_at,
                        int(commit_reached), now, job_id,
                    ),
                )
                if validated_target in TERMINAL_STATUSES | {
                    JobStatus.TEMPORARY_FAILURE, JobStatus.LOGIN_REQUIRED,
                    JobStatus.CHECKPOINT, JobStatus.UNKNOWN_RESULT,
                }:
                    connection.execute(
                        "UPDATE publish_attempts SET finished_at=?,outcome=?,failure_code=?,error_message=?,result_json=? "
                        "WHERE id=(SELECT id FROM publish_attempts WHERE job_id=? AND finished_at IS NULL ORDER BY attempt_number DESC LIMIT 1)",
                        (
                            now, validated_target.value, failure_code,
                            error[:2000] if error else None,
                            _json(result) if result is not None else None, job_id,
                        ),
                    )
                self._event(connection, job_id, row["status"], validated_target.value, event_type, message, metadata)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get(job_id)

    def release_due(self) -> int:
        now = utc_now()
        released = 0
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    "SELECT id,status FROM jobs WHERE (status='scheduled' AND scheduled_at<=?) "
                    "OR (status='temporary_failure' AND next_attempt_at<=?) ORDER BY created_at",
                    (now, now),
                ).fetchall()
                for row in rows:
                    connection.execute("UPDATE jobs SET status='queued',updated_at=?,next_attempt_at=NULL WHERE id=?", (now, row["id"]))
                    self._event(connection, row["id"], row["status"], "queued", "due_released")
                    released += 1
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return released

    def recover_interrupted(self) -> int:
        recoverable = {"opening_browser", "checking_login", "uploading"}
        uncertain = {"publishing", "verifying"}
        recovered = 0
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    "SELECT id,kind,status FROM jobs WHERE status IN ('opening_browser','checking_login','uploading','publishing','verifying')"
                ).fetchall()
                now = utc_now()
                for row in rows:
                    target = "queued" if row["status"] in recoverable or row["kind"] != "publish" else "unknown_result"
                    message = "Khôi phục sau khi ứng dụng dừng" if target == "queued" else "Kết quả chưa xác định sau khi ứng dụng dừng"
                    connection.execute(
                        "UPDATE jobs SET status=?,updated_at=?,started_at=NULL,locked_at=NULL,lease_expires_at=NULL,error=? WHERE id=?",
                        (target, now, message, row["id"]),
                    )
                    self._event(connection, row["id"], row["status"], target, "restart_recovery", message)
                    recovered += 1
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return recovered

    def claim_next(self) -> dict[str, Any] | None:
        now = utc_now()
        busy = tuple(status.value for status in ACCOUNT_BUSY_STATUSES)
        placeholders = ",".join("?" for _ in busy)
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    f"SELECT j.* FROM jobs j LEFT JOIN accounts a ON a.id=j.account_id "
                    f"WHERE j.status='queued' AND j.cancel_requested=0 AND (j.next_attempt_at IS NULL OR j.next_attempt_at<=?) "
                    f"AND (j.account_id IS NULL OR a.enabled=1) "
                    f"AND (j.account_id IS NULL OR NOT EXISTS (SELECT 1 FROM jobs active WHERE active.account_id=j.account_id AND active.status IN ({placeholders}))) "
                    f"ORDER BY j.priority,j.created_at LIMIT 1",
                    (now, *busy),
                ).fetchone()
                if row is None:
                    connection.execute("COMMIT")
                    return None
                target = JobStatus.OPENING_BROWSER if row["kind"] == "publish" else JobStatus.PUBLISHING
                connection.execute(
                    "UPDATE jobs SET status=?,attempts=attempts+1,started_at=?,updated_at=?,locked_at=?,error=NULL,failure_code=NULL WHERE id=? AND status='queued'",
                    (target.value, now, now, now, row["id"]),
                )
                attempt_number = row["attempts"] + 1
                connection.execute(
                    "INSERT INTO publish_attempts(id,job_id,attempt_number,started_at) VALUES(?,?,?,?)",
                    (str(uuid.uuid4()), row["id"], attempt_number, now),
                )
                self._event(connection, row["id"], "queued", target.value, "claimed", metadata={"attempt": attempt_number})
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get(row["id"])

    def complete(self, job_id: str, result: dict[str, Any]) -> None:
        job = self.get(job_id)
        if not job:
            raise KeyError(job_id)
        if job["status"] == JobStatus.PUBLISHING.value:
            self.transition(job_id, JobStatus.SUCCEEDED, event_type="completed", result=result)
        elif job["status"] in {JobStatus.VERIFYING.value, JobStatus.UNKNOWN_RESULT.value}:
            self.transition(job_id, JobStatus.SUCCEEDED, event_type="verified", result=result)
        else:
            validate_transition(job["status"], JobStatus.SUCCEEDED)

    def dry_run_ready(self, job_id: str, result: dict[str, Any]) -> None:
        self.transition(job_id, JobStatus.DRY_RUN_READY, event_type="dry_run_ready", result=result)

    def fail(self, job_id: str, error: str, failure_code: str = "unexpected") -> None:
        job = self.get(job_id)
        if not job or JobStatus(job["status"]) in TERMINAL_STATUSES:
            return
        attempts = int(job["attempts"])
        if attempts < int(job["max_attempts"]) and job["status"] not in {
            JobStatus.LOGIN_REQUIRED.value, JobStatus.CHECKPOINT.value, JobStatus.UNKNOWN_RESULT.value,
        }:
            delay = min(self.retry_cap_seconds, self.retry_base_seconds * (2 ** max(0, attempts - 1)))
            due = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            self.transition(
                job_id, JobStatus.TEMPORARY_FAILURE, event_type="temporary_failure",
                error=error, failure_code=failure_code, next_attempt_at=due, metadata={"retry_in_seconds": delay},
            )
        else:
            self.transition(
                job_id, JobStatus.PERMANENT_FAILURE, event_type="permanent_failure",
                error=error, failure_code=failure_code,
            )

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or JobStatus(job["status"]) in TERMINAL_STATUSES:
            return False
        with self.db.connection() as connection:
            connection.execute("UPDATE jobs SET cancel_requested=1,updated_at=? WHERE id=?", (utc_now(), job_id))
        if job["commit_reached_at"] or job["status"] == JobStatus.VERIFYING.value:
            self.transition(job_id, JobStatus.UNKNOWN_RESULT, event_type="cancel_after_commit", message="Hủy sau commit point; cần xác minh thủ công")
        else:
            self.transition(job_id, JobStatus.CANCELLED, event_type="cancelled")
        return True

    def is_cancel_requested(self, job_id: str) -> bool:
        with self.db.connection() as connection:
            row = connection.execute("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
            return bool(row and row[0])

    def mark_cancelled(self, job_id: str) -> None:
        job = self.get(job_id)
        if not job or JobStatus(job["status"]) in TERMINAL_STATUSES | {JobStatus.UNKNOWN_RESULT}:
            return
        self.cancel(job_id)
