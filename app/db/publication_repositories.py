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

    def create_batch(
        self, *, content_id: str, revision_id: str, approval_id: str | None,
        dry_run: bool, missed_policy: str, request_key: str, request_hash: str,
        plan_key: str, entries: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Atomically create one plan, all its releases and their executable jobs."""
        if not entries:
            raise ValueError("Cần chọn ít nhất một Page/Kênh đích.")
        now = utc_now()
        plan_id = str(uuid.uuid4())
        plan_due = min((item["scheduled_at"] for item in entries if item.get("scheduled_at")), default=None)
        plan_status = "scheduled" if plan_due and plan_due > now else "queued"
        job_ids: list[str] = []
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                prior = connection.execute(
                    "SELECT id,request_hash FROM publication_plans WHERE request_key=?", (request_key,),
                ).fetchone()
                if prior:
                    if prior["request_hash"] != request_hash:
                        raise ValueError("Mã yêu cầu này đã được dùng cho lựa chọn khác. Hãy tạo yêu cầu mới.")
                    plan_id = prior["id"]
                    job_ids = [row[0] for row in connection.execute(
                        "SELECT job_id FROM publication_releases WHERE plan_id=? AND job_id IS NOT NULL ORDER BY created_at",
                        (plan_id,),
                    )]
                    connection.execute("COMMIT")
                    return self.get_plan(plan_id), [self._job(job_id) for job_id in job_ids]

                content = connection.execute(
                    "SELECT current_revision FROM content_items WHERE id=?", (content_id,),
                ).fetchone()
                revision = connection.execute(
                    "SELECT id,revision_number FROM content_revisions WHERE id=? AND content_id=?",
                    (revision_id, content_id),
                ).fetchone()
                if not content or not revision or revision["revision_number"] != content["current_revision"]:
                    raise ValueError("Nội dung đã thay đổi sau khi kiểm tra. Hãy kiểm tra lại trước khi lên lịch.")
                if not dry_run:
                    current_approval = connection.execute(
                        "SELECT id FROM content_approvals WHERE id=? AND content_id=? AND revision_id=? AND status='approved'",
                        (approval_id, content_id, revision_id),
                    ).fetchone()
                    if not current_approval:
                        raise ValueError("Bản nội dung hiện tại chưa được duyệt.")

                connection.execute(
                    "INSERT INTO publication_plans(id,content_id,content_revision_id,approval_id,status,dry_run,scheduled_at,missed_policy,idempotency_key,request_key,request_hash,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (plan_id, content_id, revision_id, approval_id, plan_status, int(dry_run), plan_due,
                     missed_policy, plan_key, request_key, request_hash, now, now),
                )

                for item in entries:
                    account = connection.execute(
                        "SELECT enabled,profile_operation_locked FROM accounts WHERE id=?", (item["account_id"],),
                    ).fetchone()
                    target = connection.execute(
                        "SELECT account_id,platform,enabled,access_status FROM publishing_targets WHERE id=?",
                        (item["target_id"],),
                    ).fetchone()
                    if (not account or not account["enabled"] or account["profile_operation_locked"]
                            or not target or target["account_id"] != item["account_id"]
                            or target["platform"] != item["platform"] or not target["enabled"]
                            or target["access_status"] not in {"accessible", "unknown"}):
                        raise ValueError(f"Page {item['target_name']} vừa đổi trạng thái. Hãy kiểm tra lại.")
                    if item.get("provider") == "meta":
                        binding = connection.execute(
                            "SELECT b.status,c.status AS connection_status FROM provider_target_connections b "
                            "JOIN account_connections c ON c.id=b.connection_id "
                            "WHERE b.id=? AND b.target_id=? AND b.connection_id=?",
                            (item.get("provider_target_binding_id"), item["target_id"], item.get("connection_id")),
                        ).fetchone()
                        if not binding or binding["status"] != "connected" or binding["connection_status"] != "connected":
                            raise ValueError(f"Kết nối API của Page {item['target_name']} vừa thay đổi. Hãy kiểm tra lại.")

                    due = item.get("scheduled_at")
                    status = "scheduled" if due and due > now else "queued"
                    release_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
                    payload = dict(item["payload"])
                    payload.update({
                        "publication_plan_id": plan_id,
                        "publication_release_id": release_id,
                        "content_revision_id": revision_id,
                    })
                    connection.execute(
                        "INSERT INTO publication_releases(id,plan_id,content_id,content_revision_id,account_id,target_id,platform,content_format,status,scheduled_at,settings_json,payload_snapshot_json,media_snapshot_json,selector_version,requested_routing_policy,publication_transport,provider,provider_version,routing_reason,connection_id,connection_scopes_hash,idempotency_key,job_id,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (release_id, plan_id, content_id, revision_id, item["account_id"], item["target_id"],
                         item["platform"], item["content_format"], status, due, _json(item["settings"]),
                         _json(payload), _json(item["media_snapshot"]), item["selector_version"],
                         item["routing_preference"], item["publication_transport"], item.get("provider"),
                         item.get("provider_version"), item["routing_reason"], item.get("connection_id"),
                         item.get("connection_scopes_hash"), item["release_key"], None, now, now),
                    )
                    connection.execute(
                        "INSERT INTO jobs(id,account_id,kind,status,payload_json,content_id,target_id,approval_id,scheduled_at,created_at,updated_at,dry_run,idempotency_key,max_attempts,correlation_id,missed_policy,publication_release_id) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (job_id, item["account_id"], "publish", status, _json(payload), content_id,
                         item["target_id"], approval_id, due, now, now, int(dry_run), item["job_key"],
                         3, str(uuid.uuid4()), missed_policy, release_id),
                    )
                    connection.execute(
                        "INSERT INTO publish_job_events(job_id,from_status,to_status,event_type,message,metadata_json,created_at) "
                        "VALUES(?,NULL,?,'created',NULL,'{}',?)", (job_id, status, now),
                    )
                    connection.execute(
                        "UPDATE publication_releases SET job_id=?,updated_at=? WHERE id=?",
                        (job_id, now, release_id),
                    )
                    job_ids.append(job_id)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get_plan(plan_id), [self._job(job_id) for job_id in job_ids]

    def _job(self, job_id: str) -> dict[str, Any]:
        with self.db.connection() as connection:
            return row_to_dict(connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

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
        connection_scopes_hash: str | None = None,
    ) -> dict[str, Any]:
        existing = self.get_release_by_idempotency(idempotency_key)
        if existing:
            return existing
        release_id, now = str(uuid.uuid4()), utc_now()
        status = "scheduled" if scheduled_at and scheduled_at > now else "queued"
        try:
            with self.db.connection() as connection:
                connection.execute(
                    "INSERT INTO publication_releases(id,plan_id,content_id,content_revision_id,account_id,target_id,platform,content_format,status,scheduled_at,settings_json,payload_snapshot_json,media_snapshot_json,selector_version,requested_routing_policy,publication_transport,provider,provider_version,routing_reason,connection_id,connection_scopes_hash,idempotency_key,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        release_id, plan_id, content_id, content_revision_id, account_id, target_id,
                        platform, content_format, status, scheduled_at, _json(settings),
                        _json(payload_snapshot), _json(media_snapshot), selector_version, requested_routing_policy,
                        publication_transport, provider, provider_version, routing_reason, connection_id,
                        connection_scopes_hash,
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
        connection_id: str | None = None,
        connection_scopes_hash: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the newest route-matched dry-run evidence, if it is still current."""
        clauses = [
            "account_id=?", "target_id=?", "content_format=?", "status='dry_run_ready'",
            "COALESCE(publication_transport, 'chrome')=?",
        ]
        params: list[Any] = [account_id, target_id, content_format, transport]
        clauses.append("connection_id IS ?")
        params.append(connection_id)
        clauses.append("connection_scopes_hash IS ?")
        params.append(connection_scopes_hash)
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
        release["payload_snapshot"] = release.get("payload_snapshot") or {}
        release["media_snapshot"] = release.get("media_snapshot") or []
        release["settings_snapshot"] = release.get("settings") or {}
        release["events"] = self.release_events(release_id)
        with self.db.connection() as connection:
            release["target"] = row_to_dict(connection.execute(
                "SELECT id,name,platform,target_type,external_id,url FROM publishing_targets WHERE id=?",
                (release["target_id"],),
            ).fetchone())
            release["account"] = row_to_dict(connection.execute(
                "SELECT id,name,platform FROM accounts WHERE id=?", (release["account_id"],)
            ).fetchone())
            job = row_to_dict(connection.execute(
                "SELECT id,status,commit_reached_at,finished_at,dry_run,error,failure_code,result_json FROM jobs WHERE id=?",
                (release.get("job_id"),),
            ).fetchone()) if release.get("job_id") else None
            if job:
                result = job.pop("result", {}) or {}
                job["result"] = {key: result[key] for key in ("post_url", "external_post_id") if result.get(key)}
            release["job"] = job
            release["attempts"] = [dict(row) for row in connection.execute(
                "SELECT * FROM publish_attempts WHERE job_id=? ORDER BY attempt_number", (release.get("job_id"),)
            )] if release.get("job_id") else []
            release["artifacts"] = [{
                key: row[key] for key in ("id", "artifact_type", "relative_path", "created_at")
            } for row in connection.execute(
                "SELECT * FROM browser_error_artifacts WHERE job_id=? ORDER BY created_at DESC", (release.get("job_id"),)
            )] if release.get("job_id") else []
        release["attempts"] = [{
            key: attempt.get(key) for key in (
                "attempt_number", "started_at", "finished_at", "outcome", "transport", "provider",
                "failure_code", "error_message",
            )
        } for attempt in release["attempts"]]
        release["events"] = [{
            key: event.get(key) for key in ("event_type", "from_status", "to_status", "message", "created_at")
        } for event in release["events"]]
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
        offset: int = 0,
        order: str = "asc",
        account_id: str | None = None,
        target_id: str | None = None,
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
        if account_id:
            clauses.append("account_id=?")
            params.append(account_id)
        if target_id:
            clauses.append("target_id=?")
            params.append(target_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(limit, 1000)))
        params.append(max(0, offset))
        direction = "DESC" if str(order).lower() == "desc" else "ASC"
        with self.db.connection() as connection:
            return [row_to_dict(row) for row in connection.execute(
                f"SELECT * FROM publication_releases{where} ORDER BY COALESCE(scheduled_at,created_at) {direction},created_at {direction} LIMIT ? OFFSET ?",
                params,
            )]

    def release_events(self, release_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM publication_release_events WHERE release_id=? ORDER BY id", (release_id,)
            )]

    def reschedule_release(self, release_id: str, scheduled_at: str, timezone_name: str) -> dict[str, Any]:
        return self.reschedule_releases([release_id], scheduled_at, timezone_name)[0]

    def reschedule_releases(
        self, release_ids: list[str], scheduled_at: str, timezone_name: str
    ) -> list[dict[str, Any]]:
        if not release_ids or len(release_ids) > 100 or len(set(release_ids)) != len(release_ids):
            raise ValueError("Danh sách release đổi lịch không hợp lệ.")
        due = datetime.fromisoformat(scheduled_at)
        if due.tzinfo is None:
            raise ValueError("Thời gian reschedule cần timezone.")
        due_utc = due.astimezone(timezone.utc).isoformat()
        now = utc_now()
        target_status = "scheduled" if due_utc > now else "queued"
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                placeholders = ",".join("?" for _ in release_ids)
                releases = connection.execute(
                    f"SELECT * FROM publication_releases WHERE id IN ({placeholders})", release_ids
                ).fetchall()
                if len(releases) != len(release_ids):
                    found = {release["id"] for release in releases}
                    raise KeyError(next(value for value in release_ids if value not in found))
                allowed = {"scheduled", "queued", "pending_approval", "approved", "draft"}
                jobs = {
                    row["id"]: row for row in connection.execute(
                        f"SELECT * FROM jobs WHERE id IN ({','.join('?' for _ in releases)})",
                        [release["job_id"] for release in releases],
                    ).fetchall()
                } if releases else {}
                for release in releases:
                    job = jobs.get(release["job_id"])
                    if not job or job["status"] not in allowed or job["commit_reached_at"]:
                        raise ValueError("Một release đã chạy hoặc không còn an toàn; không release nào được đổi lịch.")
                plan_ids = {release["plan_id"] for release in releases}
                for release in releases:
                    job = jobs[release["job_id"]]
                    connection.execute(
                        "UPDATE publication_releases SET scheduled_at=?,timezone=?,status=?,rescheduled_at=?,updated_at=? WHERE id=?",
                        (due_utc, timezone_name, target_status, now, now, release["id"]),
                    )
                    connection.execute(
                        "UPDATE jobs SET scheduled_at=?,status=?,next_attempt_at=NULL,updated_at=? WHERE id=?",
                        (due_utc, target_status, now, job["id"]),
                    )
                    connection.execute(
                        "INSERT INTO publication_release_events(release_id,event_type,from_status,to_status,metadata_json,created_at) VALUES(?,?,?,?,?,?)",
                        (release["id"], "rescheduled", release["status"], target_status,
                         _json({"from": release["scheduled_at"], "to": due_utc, "timezone": timezone_name}), now),
                    )
                    connection.execute(
                        "INSERT INTO publish_job_events(job_id,from_status,to_status,event_type,metadata_json,created_at) VALUES(?,?,?,?,?,?)",
                        (job["id"], job["status"], target_status, "rescheduled",
                         _json({"scheduled_at": due_utc, "timezone": timezone_name}), now),
                    )
                for plan_id in plan_ids:
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
        return [self.get_release(release_id) for release_id in release_ids]

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
