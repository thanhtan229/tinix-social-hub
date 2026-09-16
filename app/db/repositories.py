from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.secrets import SecretProtector
from app.db.database import Database, row_to_dict, utc_now
from app.domain.jobs import ACCOUNT_BUSY_STATUSES, TERMINAL_STATUSES, JobStatus, validate_transition


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class AppSettingsRepository:
    def __init__(self, database: Database) -> None:
        self.db = database

    def get(self, key: str, default: Any = None) -> Any:
        with self.db.connection() as connection:
            row = connection.execute(
                "SELECT value_json FROM app_settings WHERE key=?", (key,)
            ).fetchone()
        return json.loads(row["value_json"]) if row else default

    def set(self, key: str, value: Any) -> Any:
        with self.db.connection() as connection:
            connection.execute(
                "INSERT INTO app_settings(key,value_json,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
                (key, _json(value), utc_now()),
            )
        return value


class AccountRepository:
    CREDENTIAL_FIELDS = ("password", "secret_2fa", "email_pass", "cookie", "recovery_codes")

    def __init__(self, database: Database, secrets: SecretProtector | None = None) -> None:
        self.db = database
        self.secrets = secrets or SecretProtector()

    def _protected_credentials(self, metadata: dict[str, Any]) -> dict[str, str]:
        return {
            field: self.secrets.protect_secret(str(metadata.get(field) or ""))
            if metadata.get(field) else ""
            for field in self.CREDENTIAL_FIELDS
        }

    def _hydrate_credentials(self, account: dict[str, Any] | None) -> dict[str, Any] | None:
        if account is None:
            return None
        legacy = {field: str(account.get(field) or "") for field in self.CREDENTIAL_FIELDS}
        protected = {
            field: str(account.pop(f"{field}_protected", "") or "")
            for field in self.CREDENTIAL_FIELDS
        }
        if any(legacy.values()):
            protected = {
                field: self.secrets.protect_secret(legacy[field]) if legacy[field] else protected[field]
                for field in self.CREDENTIAL_FIELDS
            }
            with self.db.connection() as connection:
                connection.execute(
                    """UPDATE accounts SET
                        password='',secret_2fa='',email_pass='',cookie='',recovery_codes='',
                        password_protected=?,secret_2fa_protected=?,email_pass_protected=?,
                        cookie_protected=?,recovery_codes_protected=?,updated_at=? WHERE id=?""",
                    (
                        protected["password"], protected["secret_2fa"], protected["email_pass"],
                        protected["cookie"], protected["recovery_codes"], utc_now(), account["id"],
                    ),
                )
        for field in self.CREDENTIAL_FIELDS:
            account[field] = legacy[field] or (
                self.secrets.unprotect_secret(protected[field]) if protected[field] else ""
            )
        return account

    def migrate_legacy_credentials(self) -> int:
        with self.db.connection() as connection:
            rows = [row_to_dict(row) for row in connection.execute("SELECT * FROM accounts")]
        return sum(1 for account in rows if any((account or {}).get(field) for field in self.CREDENTIAL_FIELDS)
                   and self._hydrate_credentials(account))

    def create(self, name: str, platform: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        account_id = str(uuid.uuid4())
        profile_id = str(uuid.uuid4())
        now = utc_now()
        metadata = metadata or {}
        protected = self._protected_credentials(metadata)
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """INSERT INTO accounts(
                        id,name,platform,profile_key,username,email,password,secret_2fa,email_pass,cookie,
                        recovery_email,recovery_codes,notes,starred,password_protected,secret_2fa_protected,
                        email_pass_protected,cookie_protected,recovery_codes_protected,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        account_id, name.strip(), platform.strip().lower(), account_id,
                        str(metadata.get("username") or ""), str(metadata.get("email") or ""),
                        "", "", "", "",
                        str(metadata.get("recovery_email") or "").strip(),
                        "",
                        str(metadata.get("notes") or ""),
                        1 if metadata.get("starred") else 0,
                        protected["password"], protected["secret_2fa"], protected["email_pass"],
                        protected["cookie"], protected["recovery_codes"],
                        now, now,
                    ),
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
            account = row_to_dict(connection.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())
        return self._hydrate_credentials(account)

    def list(self, include_disabled: bool = True) -> list[dict[str, Any]]:
        query = "SELECT * FROM accounts" + ("" if include_disabled else " WHERE enabled=1") + " ORDER BY created_at DESC"
        with self.db.connection() as connection:
            accounts = [row_to_dict(row) for row in connection.execute(query)]
        return [account for row in accounts if (account := self._hydrate_credentials(row)) is not None]

    def update(
        self, account_id: str, name: str, platform: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        metadata = metadata or {}
        fields = ["name=?", "platform=?"]
        values: list[Any] = [name.strip(), platform.strip().lower()]
        for field in ("username", "email", "recovery_email", "notes"):
            if field in metadata:
                fields.append(f"{field}=?")
                values.append(str(metadata.get(field) or "").strip())
        for field in self.CREDENTIAL_FIELDS:
            if field in metadata:
                protected = self.secrets.protect_secret(str(metadata[field])) if metadata[field] else ""
                fields.extend((f"{field}=?", f"{field}_protected=?"))
                values.extend(("", protected))
        if "starred" in metadata:
            fields.append("starred=?")
            values.append(1 if metadata["starred"] else 0)
        fields.append("updated_at=?")
        values.extend([utc_now(), account_id])
        with self.db.connection() as connection:
            connection.execute(
                f"UPDATE accounts SET {','.join(fields)} WHERE id=?",
                values,
            )
        return self.get(account_id)

    def set_starred(self, account_id: str, starred: bool) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE accounts SET starred=?,updated_at=? WHERE id=?",
                (1 if starred else 0, utc_now(), account_id),
            )
        return self.get(account_id)

    def toggle_starred(self, account_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE accounts SET starred=(1 - COALESCE(starred, 0)),updated_at=? WHERE id=?",
                (utc_now(), account_id),
            )
        return self.get(account_id)

    def clear_credentials(self, account_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            connection.execute(
                """UPDATE accounts SET
                    password='',secret_2fa='',recovery_codes='',email_pass='',cookie='',
                    password_protected='',secret_2fa_protected='',recovery_codes_protected='',
                    email_pass_protected='',cookie_protected='',updated_at=?
                WHERE id=?""",
                (utc_now(), account_id),
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

    def set_routing_preference(self, account_id: str, preference: str) -> dict[str, Any] | None:
        allowed = {"official_api_preferred", "chrome_preferred", "official_api_only", "chrome_only"}
        if preference not in allowed:
            raise ValueError("Routing preference không hợp lệ.")
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE accounts SET routing_preference=?,updated_at=? WHERE id=?",
                (preference, utc_now(), account_id),
            )
        return self.get(account_id)

    def begin_profile_operation(self, account_id: str) -> dict[str, Any]:
        """Lock an account only when no unfinished job can start using its profile."""
        terminal = tuple(status.value for status in TERMINAL_STATUSES)
        placeholders = ",".join("?" for _ in terminal)
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                account = connection.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
                if not account:
                    raise KeyError(account_id)
                if account["profile_operation_locked"]:
                    raise RuntimeError("Profile đang được Import, Export, Backup hoặc Restore.")
                unfinished = connection.execute(
                    f"SELECT COUNT(*) FROM jobs WHERE account_id=? AND status NOT IN ({placeholders})",
                    (account_id, *terminal),
                ).fetchone()[0]
                if unfinished:
                    raise RuntimeError("Account còn job chưa kết thúc; hãy hoàn tất hoặc hủy job trước.")
                connection.execute(
                    "UPDATE accounts SET profile_operation_locked=1,updated_at=? WHERE id=?",
                    (utc_now(), account_id),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get(account_id)

    def end_profile_operation(self, account_id: str) -> None:
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE accounts SET profile_operation_locked=0,updated_at=? WHERE id=?",
                (utc_now(), account_id),
            )

    def recover_profile_operations(self) -> int:
        """Release maintenance locks left behind by an interrupted app process."""
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                count = connection.execute(
                    "SELECT COUNT(*) FROM accounts WHERE profile_operation_locked=1"
                ).fetchone()[0]
                connection.execute(
                    "UPDATE accounts SET profile_operation_locked=0,updated_at=? WHERE profile_operation_locked=1",
                    (now,),
                )
                connection.execute(
                    "UPDATE chrome_profile_operations SET status='failed',error='Ứng dụng dừng khi thao tác đang chạy',finished_at=? WHERE status='running'",
                    (now,),
                )
                connection.execute("COMMIT")
                return count
            except Exception:
                connection.execute("ROLLBACK")
                raise

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


class ChromeProfileRepository:
    def __init__(self, database: Database) -> None:
        self.db = database

    def get_for_account(self, account_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            return row_to_dict(connection.execute("SELECT * FROM chrome_profiles WHERE account_id=?", (account_id,)).fetchone())

    def record_started(self, account_id: str, port: int, pid: int, started_at: str) -> None:
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE chrome_profiles SET remote_port=?,last_pid=?,last_started_at=?,last_seen_at=?,updated_at=? WHERE account_id=?",
                (port, pid, started_at, now, now, account_id),
            )

    def record_stopped(self, account_id: str) -> None:
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE chrome_profiles SET remote_port=NULL,last_pid=NULL,last_seen_at=?,updated_at=? WHERE account_id=?",
                (now, now, account_id),
            )


class ArtifactRepository:
    def __init__(self, database: Database) -> None:
        self.db = database

    def record(
        self,
        job_id: str,
        artifact_type: str,
        relative_path: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        artifact_id = str(uuid.uuid4())
        with self.db.connection() as connection:
            attempt = connection.execute(
                "SELECT id FROM publish_attempts WHERE job_id=? ORDER BY attempt_number DESC LIMIT 1", (job_id,)
            ).fetchone()
            connection.execute(
                "INSERT INTO browser_error_artifacts(id,job_id,attempt_id,artifact_type,relative_path,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (artifact_id, job_id, attempt["id"] if attempt else None, artifact_type, relative_path, _json(metadata or {}), utc_now()),
            )
            return dict(connection.execute("SELECT * FROM browser_error_artifacts WHERE id=?", (artifact_id,)).fetchone())


class JobRepository:
    ACTIVE_HISTORY_STATUSES = {
        "scheduled", "queued", "opening_browser", "checking_login", "uploading",
        "publishing", "verifying", "running", "retry_wait",
    }
    FAILED_HISTORY_STATUSES = {
        "temporary_failure", "permanent_failure", "login_required", "checkpoint",
        "unknown_result",
    }

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

    @staticmethod
    def _sync_plan_status(connection: sqlite3.Connection, release_id: str | None) -> None:
        if not release_id:
            return
        row = connection.execute("SELECT plan_id FROM publication_releases WHERE id=?", (release_id,)).fetchone()
        if not row:
            return
        plan_id = row["plan_id"]
        statuses = [item[0] for item in connection.execute(
            "SELECT status FROM publication_releases WHERE plan_id=?", (plan_id,)
        )]
        terminal = {"succeeded", "dry_run_ready", "permanent_failure", "cancelled"}
        successful = {"succeeded", "dry_run_ready"}
        if statuses and all(status in successful for status in statuses):
            aggregate = "completed"
        elif statuses and all(status == "cancelled" for status in statuses):
            aggregate = "cancelled"
        elif statuses and all(status in terminal for status in statuses):
            aggregate = "partially_failed"
        elif any(status in {"opening_browser", "checking_login", "uploading", "publishing", "verifying"} for status in statuses):
            aggregate = "active"
        elif statuses and all(status == "scheduled" for status in statuses):
            aggregate = "scheduled"
        else:
            aggregate = "queued"
        connection.execute(
            "UPDATE publication_plans SET status=?,updated_at=? WHERE id=?",
            (aggregate, utc_now(), plan_id),
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
        missed_policy: str = "confirm",
        publication_release_id: str | None = None,
    ) -> dict[str, Any]:
        job_id, now = str(uuid.uuid4()), utc_now()
        status = JobStatus.SCHEDULED if scheduled_at and scheduled_at > now else JobStatus.QUEUED
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if account_id:
                    account = connection.execute(
                        "SELECT profile_operation_locked FROM accounts WHERE id=?", (account_id,)
                    ).fetchone()
                    if account and account["profile_operation_locked"]:
                        raise RuntimeError("Profile của account đang được bảo trì; chưa thể tạo job.")
                connection.execute(
                    "INSERT INTO jobs(id,account_id,kind,status,payload_json,content_id,target_id,approval_id,scheduled_at,created_at,updated_at,dry_run,idempotency_key,max_attempts,correlation_id,missed_policy,publication_release_id) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        job_id, account_id, kind, status.value, _json(payload), content_id, target_id,
                        approval_id, scheduled_at, now, now, int(dry_run), idempotency_key,
                        max(1, min(max_attempts, 10)), str(uuid.uuid4()), missed_policy,
                        publication_release_id,
                    ),
                )
                self._event(connection, job_id, None, status.value, "created")
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get(job_id)

    def get_by_idempotency(self, key: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            return row_to_dict(connection.execute("SELECT * FROM jobs WHERE idempotency_key=?", (key,)).fetchone())

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

    def history_candidates(
        self,
        *,
        before: str | None = None,
        after: str | None = None,
        status_filter: str = "all",
        job_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        parameters: list[Any] = []
        active = sorted(self.ACTIVE_HISTORY_STATUSES)
        clauses.append(f"status NOT IN ({','.join('?' for _ in active)})")
        parameters.extend(active)
        if before:
            clauses.append("created_at < ?")
            parameters.append(before)
        if after:
            clauses.append("created_at >= ?")
            parameters.append(after)
        if job_ids is not None:
            unique_ids = list(dict.fromkeys(job_ids))
            if not unique_ids:
                return {"jobs": [], "artifacts": [], "blocked_active": 0}
            clauses.append(f"id IN ({','.join('?' for _ in unique_ids)})")
            parameters.extend(unique_ids)
        if status_filter == "succeeded":
            clauses.append("status='succeeded'")
        elif status_filter == "dry_run":
            clauses.append("dry_run=1")
        elif status_filter == "failed":
            failed = sorted(self.FAILED_HISTORY_STATUSES)
            clauses.append(f"status IN ({','.join('?' for _ in failed)})")
            parameters.extend(failed)
        elif status_filter != "all":
            raise ValueError("Bộ lọc trạng thái lịch sử không hợp lệ.")

        where = " AND ".join(clauses)
        with self.db.connection() as connection:
            jobs = [dict(row) for row in connection.execute(
                f"SELECT id,status,dry_run,created_at FROM jobs WHERE {where} ORDER BY created_at DESC",
                parameters,
            )]
            ids = [job["id"] for job in jobs]
            artifacts: list[dict[str, Any]] = []
            if ids:
                placeholders = ",".join("?" for _ in ids)
                artifacts = [dict(row) for row in connection.execute(
                    f"SELECT id,job_id,relative_path FROM browser_error_artifacts WHERE job_id IN ({placeholders})",
                    ids,
                )]
            blocked_active = 0
            if job_ids:
                unique_ids = list(dict.fromkeys(job_ids))
                placeholders = ",".join("?" for _ in unique_ids)
                blocked_active = connection.execute(
                    f"SELECT COUNT(*) FROM jobs WHERE id IN ({placeholders}) AND status IN ({','.join('?' for _ in active)})",
                    [*unique_ids, *active],
                ).fetchone()[0]
        return {"jobs": jobs, "artifacts": artifacts, "blocked_active": blocked_active}

    def delete_history(self, job_ids: list[str]) -> dict[str, Any]:
        unique_ids = list(dict.fromkeys(job_ids))
        if not unique_ids:
            return {"deleted": 0, "job_ids": [], "artifacts": [], "blocked_active": 0}
        placeholders = ",".join("?" for _ in unique_ids)
        active = sorted(self.ACTIVE_HISTORY_STATUSES)
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = [dict(row) for row in connection.execute(
                    f"SELECT id,status FROM jobs WHERE id IN ({placeholders})", unique_ids
                )]
                eligible = [row["id"] for row in rows if row["status"] not in self.ACTIVE_HISTORY_STATUSES]
                blocked_active = sum(row["status"] in self.ACTIVE_HISTORY_STATUSES for row in rows)
                artifacts: list[dict[str, Any]] = []
                if eligible:
                    eligible_placeholders = ",".join("?" for _ in eligible)
                    artifacts = [dict(row) for row in connection.execute(
                        f"SELECT id,job_id,relative_path FROM browser_error_artifacts WHERE job_id IN ({eligible_placeholders})",
                        eligible,
                    )]
                    connection.execute(
                        f"DELETE FROM notifications WHERE entity_type='job' AND entity_id IN ({eligible_placeholders})",
                        eligible,
                    )
                    connection.execute(
                        f"DELETE FROM jobs WHERE id IN ({eligible_placeholders}) AND status NOT IN ({','.join('?' for _ in active)})",
                        [*eligible, *active],
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return {
            "deleted": len(eligible), "job_ids": eligible, "artifacts": artifacts,
            "blocked_active": blocked_active,
        }

    def events(self, job_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM publish_job_events WHERE job_id=? ORDER BY id", (job_id,))]

    def artifacts(self, job_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM browser_error_artifacts WHERE job_id=? ORDER BY created_at DESC", (job_id,)
            )]

    def detail(self, job_id: str) -> dict[str, Any] | None:
        job = self.get(job_id)
        if not job:
            return None
        with self.db.connection() as connection:
            job["attempt_history"] = [dict(row) for row in connection.execute(
                "SELECT * FROM publish_attempts WHERE job_id=? ORDER BY attempt_number", (job_id,)
            )]
            job["release"] = row_to_dict(connection.execute(
                "SELECT * FROM publication_releases WHERE id=?", (job.get("publication_release_id"),)
            ).fetchone()) if job.get("publication_release_id") else None
        job["events"] = self.events(job_id)
        job["artifacts"] = self.artifacts(job_id)
        return job

    def record_route(
        self, job_id: str, *, transport: str, reason: str,
        provider: str | None = None, provider_version: str | None = None,
        connection_id: str | None = None,
    ) -> dict[str, Any]:
        """Freeze the selected transport before a commit-capable publisher runs."""
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                job = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                if not job:
                    raise KeyError(job_id)
                release = None
                if job["publication_release_id"]:
                    release = connection.execute(
                        "SELECT publication_transport FROM publication_releases WHERE id=?",
                        (job["publication_release_id"],),
                    ).fetchone()
                    if release and release["publication_transport"] and release["publication_transport"] != transport:
                        raise ValueError("Transport đã được đóng băng cho release; không được chuyển route khi retry.")
                    connection.execute(
                        "UPDATE publication_releases SET publication_transport=COALESCE(publication_transport,?),"
                        "provider=COALESCE(provider,?),provider_version=COALESCE(provider_version,?),"
                        "routing_reason=COALESCE(routing_reason,?),connection_id=COALESCE(connection_id,?),updated_at=? WHERE id=?",
                        (transport, provider, provider_version, reason, connection_id, now, job["publication_release_id"]),
                    )
                connection.execute(
                    "UPDATE publish_attempts SET transport=?,provider=? WHERE id=(SELECT id FROM publish_attempts WHERE job_id=? ORDER BY attempt_number DESC LIMIT 1)",
                    (transport, provider, job_id),
                )
                self._event(
                    connection, job_id, job["status"], job["status"], "route_selected",
                    metadata={"transport": transport, "provider": provider, "reason": reason, "connection_id": connection_id},
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get(job_id)

    def record_provider_request(
        self, job_id: str, provider_request_id: str, *, commit_possible: bool = False,
    ) -> None:
        """Attach the provider correlation id to the active attempt for support and recovery."""
        with self.db.connection() as connection:
            cursor = connection.execute(
                "UPDATE publish_attempts SET provider_request_id=?,commit_possible=MAX(commit_possible,?) "
                "WHERE id=(SELECT id FROM publish_attempts WHERE job_id=? ORDER BY attempt_number DESC LIMIT 1)",
                (provider_request_id[:500], int(commit_possible), job_id),
            )
            if not cursor.rowcount:
                raise KeyError(job_id)

    def health_counts(self, stuck_minutes: int = 15) -> dict[str, int]:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stuck_minutes)).isoformat()
        with self.db.connection() as connection:
            stuck = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('opening_browser','checking_login','uploading','publishing','verifying') AND updated_at<?",
                (cutoff,),
            ).fetchone()[0]
            attention = connection.execute(
                """SELECT COUNT(*)
                   FROM jobs AS job
                   LEFT JOIN publication_releases AS failed_release
                     ON failed_release.id=job.publication_release_id
                   WHERE job.status IN ('login_required','checkpoint','unknown_result')
                      OR (
                          job.status='permanent_failure'
                          AND (
                              failed_release.id IS NULL
                              OR NOT EXISTS (
                                  SELECT 1
                                  FROM publication_releases AS later_release
                                  WHERE later_release.account_id=failed_release.account_id
                                    AND later_release.target_id=failed_release.target_id
                                    AND later_release.content_format=failed_release.content_format
                                    AND COALESCE(later_release.publication_transport, 'chrome')
                                        =COALESCE(failed_release.publication_transport, 'chrome')
                                    AND COALESCE(later_release.selector_version, '')
                                        =COALESCE(failed_release.selector_version, '')
                                    AND COALESCE(later_release.provider_version, '')
                                        =COALESCE(failed_release.provider_version, '')
                                    AND later_release.status IN ('dry_run_ready','succeeded')
                                    AND later_release.updated_at>failed_release.updated_at
                              )
                          )
                      )""",
            ).fetchone()[0]
        return {"stuck": stuck, "needs_attention": attention}

    def retry(self, job_id: str) -> dict[str, Any]:
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                if not row:
                    raise KeyError(job_id)
                if row["account_id"]:
                    account = connection.execute(
                        "SELECT profile_operation_locked FROM accounts WHERE id=?", (row["account_id"],)
                    ).fetchone()
                    if account and account["profile_operation_locked"]:
                        raise ValueError("Profile của account đang được bảo trì; chưa thể retry job.")
                safe = {"temporary_failure", "permanent_failure", "login_required", "checkpoint"}
                if row["status"] not in safe or row["commit_reached_at"]:
                    raise ValueError("Job không ở trạng thái retry an toàn hoặc đã qua commit point.")
                connection.execute(
                    "UPDATE jobs SET status='queued',cancel_requested=0,next_attempt_at=NULL,finished_at=NULL,error=NULL,failure_code=NULL,updated_at=? WHERE id=?",
                    (now, job_id),
                )
                if row["publication_release_id"]:
                    connection.execute(
                        "UPDATE publication_releases SET status='queued',verification_status='pending',updated_at=? WHERE id=?",
                        (now, row["publication_release_id"]),
                    )
                    self._sync_plan_status(connection, row["publication_release_id"])
                self._event(connection, job_id, row["status"], "queued", "manual_retry")
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get(job_id)

    def finalize_unknown(self, job_id: str, succeeded: bool, note: str, post_url: str | None = None) -> dict[str, Any]:
        target = "succeeded" if succeeded else "permanent_failure"
        now = utc_now()
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            if row["status"] not in {"unknown_result", "verifying"}:
                raise ValueError("Chỉ finalize job đang chờ xác minh.")
        result = {"post_url": post_url, "manual_verification": True, "note": note}
        job = self.transition(
            job_id, target, event_type="manual_finalize", message=note,
            result=result if succeeded else None, error=None if succeeded else note,
            failure_code=None if succeeded else "manual_unconfirmed",
        )
        if job.get("publication_release_id"):
            with self.db.connection() as connection:
                connection.execute(
                    "UPDATE publication_releases SET verification_status=?,verification_method='manual',verified_at=?,verification_note=?,external_url=COALESCE(?,external_url),updated_at=? WHERE id=?",
                    ("verified" if succeeded else "rejected", now, note[:2000], post_url, now, job["publication_release_id"]),
                )
        return self.get(job_id)

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
        verification_status: str | None = None,
        verification_method: str | None = None,
        verification_note: str | None = None,
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
                if commit_reached:
                    connection.execute(
                        "UPDATE publish_attempts SET commit_possible=1 WHERE id=(SELECT id FROM publish_attempts WHERE job_id=? ORDER BY attempt_number DESC LIMIT 1)",
                        (job_id,),
                    )
                if row["publication_release_id"]:
                    post_url = result.get("post_url") if result else None
                    connection.execute(
                        "UPDATE publication_releases SET status=?,external_url=COALESCE(?,external_url),"
                        "published_at=CASE WHEN ?='succeeded' THEN COALESCE(published_at,?) ELSE published_at END,"
                        "verification_status=COALESCE(?,verification_status),"
                        "verification_method=COALESCE(?,verification_method),"
                        "verified_at=CASE WHEN ?='verified' THEN COALESCE(verified_at,?) ELSE verified_at END,"
                        "verification_note=COALESCE(?,verification_note),updated_at=? WHERE id=?",
                        (
                            validated_target.value, post_url, validated_target.value,
                            finished_at, verification_status, verification_method,
                            verification_status, now, verification_note[:2000] if verification_note else None,
                            now, row["publication_release_id"],
                        ),
                    )
                    self._sync_plan_status(connection, row["publication_release_id"])
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
                notices = {
                    "succeeded": ("completed", "info", "Phát hành hoàn tất"),
                    "dry_run_ready": ("completed", "info", "Dry-run sẵn sàng"),
                    "login_required": ("reconnect", "warning", "Cần đăng nhập lại"),
                    "checkpoint": ("checkpoint", "warning", "Cần xử lý checkpoint"),
                    "unknown_result": ("unconfirmed", "warning", "Kết quả chưa xác định"),
                    "permanent_failure": ("failed", "error", "Phát hành thất bại"),
                }
                if validated_target.value in notices:
                    notice_type, severity, title = notices[validated_target.value]
                    connection.execute(
                        "INSERT OR IGNORE INTO notifications(id,notification_type,severity,title,message,entity_type,entity_id,dedupe_key,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (str(uuid.uuid4()), notice_type, severity, title, message or error or f"Job {job_id}",
                         "job", job_id, f"job:{job_id}:{validated_target.value}:{row['attempts']}", _json(metadata or {}), now),
                    )
                webhook_payload = _json({
                    "event": "job.status_changed", "job_id": job_id,
                    "from_status": row["status"], "to_status": validated_target.value,
                    "release_id": row["publication_release_id"], "occurred_at": now,
                })
                for subscription in connection.execute(
                    "SELECT id,events_json FROM webhook_subscriptions WHERE enabled=1"
                ).fetchall():
                    subscribed = json.loads(subscription["events_json"])
                    if "*" in subscribed or "job.status_changed" in subscribed:
                        connection.execute(
                            "INSERT INTO webhook_outbox(id,subscription_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",
                            (str(uuid.uuid4()), subscription["id"], "job.status_changed", webhook_payload, now),
                        )
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
                    "SELECT id,status,missed_policy,scheduled_at FROM jobs WHERE (status='scheduled' AND scheduled_at<=?) "
                    "OR (status='temporary_failure' AND next_attempt_at<=?) ORDER BY created_at",
                    (now, now),
                ).fetchall()
                missed_cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
                for row in rows:
                    target, event = "queued", "due_released"
                    is_missed = bool(
                        row["status"] == "scheduled" and row["scheduled_at"]
                        and datetime.fromisoformat(row["scheduled_at"]) < missed_cutoff
                    )
                    if is_missed and row["missed_policy"] == "skip":
                        target, event = "cancelled", "missed_skipped"
                    elif is_missed and row["missed_policy"] == "confirm":
                        target, event = "pending_approval", "missed_waiting_confirmation"
                    connection.execute(
                        "UPDATE jobs SET status=?,updated_at=?,next_attempt_at=NULL,finished_at=CASE WHEN ?='cancelled' THEN ? ELSE finished_at END WHERE id=?",
                        (target, now, target, now, row["id"]),
                    )
                    connection.execute(
                        "UPDATE publication_releases SET status=?,updated_at=? WHERE id=(SELECT publication_release_id FROM jobs WHERE id=?)",
                        (target, now, row["id"]),
                    )
                    release = connection.execute("SELECT publication_release_id FROM jobs WHERE id=?", (row["id"],)).fetchone()
                    self._sync_plan_status(connection, release[0] if release else None)
                    self._event(connection, row["id"], row["status"], target, event)
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
                    "SELECT id,kind,status,publication_release_id FROM jobs WHERE status IN ('opening_browser','checking_login','uploading','publishing','verifying')"
                ).fetchall()
                now = utc_now()
                for row in rows:
                    target = "queued" if row["status"] in recoverable or row["kind"] != "publish" else "unknown_result"
                    message = "Khôi phục sau khi ứng dụng dừng" if target == "queued" else "Kết quả chưa xác định sau khi ứng dụng dừng"
                    connection.execute(
                        "UPDATE jobs SET status=?,updated_at=?,started_at=NULL,locked_at=NULL,lease_expires_at=NULL,error=? WHERE id=?",
                        (target, now, message, row["id"]),
                    )
                    connection.execute(
                        "UPDATE publication_releases SET status=?,updated_at=? WHERE id=(SELECT publication_release_id FROM jobs WHERE id=?)",
                        (target, now, row["id"]),
                    )
                    self._sync_plan_status(connection, row["publication_release_id"])
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
                    f"AND (j.account_id IS NULL OR (a.enabled=1 AND a.profile_operation_locked=0)) "
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
                if row["publication_release_id"]:
                    connection.execute(
                        "UPDATE publication_releases SET status=?,updated_at=? WHERE id=?",
                        (target.value, now, row["publication_release_id"]),
                    )
                    self._sync_plan_status(connection, row["publication_release_id"])
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
        publisher_verified = result.get("outcome") == "published"
        verification = {
            "verification_status": "verified" if publisher_verified else None,
            "verification_method": "publisher" if publisher_verified else None,
            "verification_note": "Publisher đã xác minh kết quả trước khi đánh dấu thành công." if publisher_verified else None,
        }
        if job["status"] == JobStatus.PUBLISHING.value:
            self.transition(job_id, JobStatus.SUCCEEDED, event_type="completed", result=result, **verification)
        elif job["status"] in {JobStatus.VERIFYING.value, JobStatus.UNKNOWN_RESULT.value}:
            self.transition(job_id, JobStatus.SUCCEEDED, event_type="verified", result=result, **verification)
        else:
            validate_transition(job["status"], JobStatus.SUCCEEDED)

    def dry_run_ready(self, job_id: str, result: dict[str, Any]) -> None:
        self.transition(job_id, JobStatus.DRY_RUN_READY, event_type="dry_run_ready", result=result)

    def fail(self, job_id: str, error: str, failure_code: str = "unexpected") -> None:
        job = self.get(job_id)
        if not job or JobStatus(job["status"]) in TERMINAL_STATUSES:
            return
        if job.get("commit_reached_at") or job["status"] == JobStatus.VERIFYING.value:
            self.transition(
                job_id, JobStatus.UNKNOWN_RESULT, event_type="failure_after_commit",
                error=error, failure_code=failure_code,
                message="Lỗi xảy ra sau commit point; cần xác minh thủ công trước khi tiếp tục.",
            )
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


class TargetRepository:
    # These URLs are navigation surfaces returned by Facebook's page menu, not
    # publishable Pages. Keep this policy at the repository boundary so every
    # caller (UI, API and scheduler) gets the same safety rule.
    SYSTEM_NAVIGATION_EXTERNAL_IDS: dict[str, frozenset[str]] = {
        "facebook": frozenset({"url:latest", "url:ad_center"}),
    }

    def __init__(self, database: Database) -> None:
        self.db = database

    @classmethod
    def is_system_navigation_target(cls, target: dict[str, Any]) -> bool:
        platform = str(target.get("platform") or "").strip().lower()
        external_id = str(target.get("external_id") or "")
        return external_id in cls.SYSTEM_NAVIGATION_EXTERNAL_IDS.get(platform, frozenset())

    def sync(self, account_id: str, platform: str, targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized_platform = platform.strip().lower()
        targets = [
            target for target in targets
            if not self.is_system_navigation_target({**target, "platform": normalized_platform})
        ]
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for target in targets:
                    existing = connection.execute(
                        "SELECT id FROM publishing_targets WHERE account_id=? AND platform=? AND external_id=?",
                        (account_id, normalized_platform, target["external_id"]),
                    ).fetchone()
                    if existing:
                        connection.execute(
                            "UPDATE publishing_targets SET name=?,url=?,access_status='accessible',last_synced_at=?,last_error=NULL,updated_at=? WHERE id=?",
                            (target["name"], target.get("url"), now, now, existing["id"]),
                        )
                    else:
                        connection.execute(
                            "INSERT INTO publishing_targets(id,account_id,platform,target_type,external_id,name,url,access_status,last_synced_at,created_at,updated_at) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                str(uuid.uuid4()), account_id, normalized_platform, target.get("target_type", "page"),
                                target["external_id"], target["name"], target.get("url"), "accessible", now, now, now,
                            ),
                        )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.list(account_id=account_id)

    def remove_invalid_discovery_targets(
        self, account_id: str, platform: str, external_ids: set[str] | frozenset[str],
        reason: str = "Liên kết điều hướng Facebook, không phải Page",
    ) -> dict[str, int]:
        """Remove false discovery results without breaking publication history."""
        if not external_ids:
            return {"removed": 0, "preserved": 0}
        placeholders = ",".join("?" for _ in external_ids)
        parameters = [account_id, platform, *sorted(external_ids)]
        removed = preserved = 0
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    f"SELECT id FROM publishing_targets WHERE account_id=? AND platform=? "
                    f"AND external_id IN ({placeholders})",
                    parameters,
                ).fetchall()
                for row in rows:
                    target_id = row["id"]
                    referenced = connection.execute(
                        "SELECT EXISTS(SELECT 1 FROM jobs WHERE target_id=?) OR "
                        "EXISTS(SELECT 1 FROM publication_releases WHERE target_id=?)",
                        (target_id, target_id),
                    ).fetchone()[0]
                    if referenced:
                        connection.execute(
                            "UPDATE publishing_targets SET enabled=0,access_status='invalid_discovery',"
                            "last_error=?,updated_at=? WHERE id=?",
                            (reason[:1000], utc_now(), target_id),
                        )
                        preserved += 1
                    else:
                        connection.execute("DELETE FROM publishing_targets WHERE id=?", (target_id,))
                        removed += 1
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return {"removed": removed, "preserved": preserved}

    def list(self, account_id: str | None = None, search: str | None = None, enabled: bool | None = None) -> list[dict[str, Any]]:
        clauses, parameters = ["access_status!='invalid_discovery'"], []
        if account_id:
            clauses.append("account_id=?")
            parameters.append(account_id)
        if search:
            clauses.append("name LIKE ? ESCAPE '\\'")
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            parameters.append(f"%{escaped}%")
        if enabled is not None:
            clauses.append("enabled=?")
            parameters.append(int(enabled))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.db.connection() as connection:
            return [
                row_to_dict(row)
                for row in connection.execute(f"SELECT * FROM publishing_targets{where} ORDER BY name", parameters)
            ]

    def get(self, target_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            return row_to_dict(connection.execute("SELECT * FROM publishing_targets WHERE id=?", (target_id,)).fetchone())

    def set_enabled(self, target_id: str, enabled: bool) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE publishing_targets SET enabled=?,updated_at=? WHERE id=?", (int(enabled), utc_now(), target_id)
            )
        return self.get(target_id)

    def set_sync_error(self, account_id: str, message: str) -> None:
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE publishing_targets SET access_status='sync_error',last_error=?,updated_at=? WHERE account_id=?",
                (message[:1000], utc_now(), account_id),
            )

    def create_group(self, name: str, description: str | None = None) -> dict[str, Any]:
        group_id, now = str(uuid.uuid4()), utc_now()
        with self.db.connection() as connection:
            connection.execute(
                "INSERT INTO target_groups(id,name,description,created_at,updated_at) VALUES(?,?,?,?,?)",
                (group_id, name.strip(), description, now, now),
            )
        return self.get_group(group_id)

    def get_group(self, group_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM target_groups WHERE id=?", (group_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["target_ids"] = [
                item[0] for item in connection.execute("SELECT target_id FROM target_group_members WHERE group_id=?", (group_id,))
            ]
            return result

    def list_groups(self) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            ids = [row[0] for row in connection.execute("SELECT id FROM target_groups ORDER BY name")]
        return [self.get_group(group_id) for group_id in ids]

    def set_group_members(self, group_id: str, target_ids: list[str]) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("DELETE FROM target_group_members WHERE group_id=?", (group_id,))
                for target_id in dict.fromkeys(target_ids):
                    connection.execute(
                        "INSERT INTO target_group_members(group_id,target_id,created_at) VALUES(?,?,?)",
                        (group_id, target_id, utc_now()),
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get_group(group_id)
