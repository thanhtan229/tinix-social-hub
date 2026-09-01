from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.db.database import Database, row_to_dict, utc_now


class AccountRepository:
    def __init__(self, database: Database) -> None:
        self.db = database

    def create(self, name: str, platform: str) -> dict[str, Any]:
        account_id = str(uuid.uuid4())
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute(
                "INSERT INTO accounts(id,name,platform,profile_key,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (account_id, name.strip(), platform.strip().lower(), account_id, now, now),
            )
        return self.get(account_id)

    def get(self, account_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            return row_to_dict(connection.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())

    def list(self) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return [row_to_dict(row) for row in connection.execute("SELECT * FROM accounts ORDER BY created_at DESC")]


class JobRepository:
    ACTIVE = ("running", "waiting_user")

    def __init__(self, database: Database) -> None:
        self.db = database

    def create(self, kind: str, payload: dict[str, Any], account_id: str | None, scheduled_at: str | None) -> dict[str, Any]:
        job_id, now = str(uuid.uuid4()), utc_now()
        status = "scheduled" if scheduled_at and scheduled_at > now else "queued"
        with self.db.connection() as connection:
            connection.execute(
                "INSERT INTO jobs(id,account_id,kind,status,payload_json,scheduled_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (job_id, account_id, kind, status, json.dumps(payload, ensure_ascii=False), scheduled_at, now, now),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            return row_to_dict(connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def list(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            rows = connection.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))
            return [row_to_dict(row) for row in rows]

    def release_due(self) -> int:
        now = utc_now()
        with self.db.connection() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET status='queued',updated_at=? WHERE status='scheduled' AND scheduled_at<=?",
                (now, now),
            )
            return cursor.rowcount

    def recover_interrupted(self) -> int:
        now = utc_now()
        with self.db.connection() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET status='queued',error='Ứng dụng đã dừng khi job đang chạy; job được đưa lại vào hàng đợi.',updated_at=?,started_at=NULL "
                "WHERE status='running'",
                (now,),
            )
            return cursor.rowcount

    def claim_next(self) -> dict[str, Any] | None:
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT j.* FROM jobs j WHERE j.status='queued' AND j.cancel_requested=0 "
                    "AND (j.account_id IS NULL OR NOT EXISTS (SELECT 1 FROM jobs active WHERE active.account_id=j.account_id AND active.status IN ('running','waiting_user'))) "
                    "ORDER BY j.created_at LIMIT 1"
                ).fetchone()
                if row is None:
                    connection.execute("COMMIT")
                    return None
                connection.execute(
                    "UPDATE jobs SET status='running',attempts=attempts+1,started_at=?,updated_at=?,error=NULL WHERE id=? AND status='queued'",
                    (now, now, row["id"]),
                )
                connection.execute("COMMIT")
                return self.get(row["id"])
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def complete(self, job_id: str, result: dict[str, Any]) -> None:
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE jobs SET status='succeeded',result_json=?,finished_at=?,updated_at=? WHERE id=?",
                (json.dumps(result, ensure_ascii=False), now, now, job_id),
            )

    def fail(self, job_id: str, error: str) -> None:
        now = utc_now()
        with self.db.connection() as connection:
            row = connection.execute("SELECT attempts,max_attempts FROM jobs WHERE id=?", (job_id,)).fetchone()
            status = "queued" if row and row["attempts"] < row["max_attempts"] else "failed"
            connection.execute(
                "UPDATE jobs SET status=?,error=?,finished_at=?,updated_at=? WHERE id=?",
                (status, error[:2000], now if status == "failed" else None, now, job_id),
            )

    def cancel(self, job_id: str) -> bool:
        now = utc_now()
        with self.db.connection() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET cancel_requested=1,status=CASE WHEN status IN ('queued','scheduled') THEN 'cancelled' ELSE status END,updated_at=? "
                "WHERE id=? AND status NOT IN ('succeeded','failed','cancelled')",
                (now, job_id),
            )
            return cursor.rowcount > 0

    def is_cancel_requested(self, job_id: str) -> bool:
        with self.db.connection() as connection:
            row = connection.execute("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
            return bool(row and row[0])

    def mark_cancelled(self, job_id: str) -> None:
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute("UPDATE jobs SET status='cancelled',finished_at=?,updated_at=? WHERE id=?", (now, now, job_id))

