from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.secrets import SecretProtector
from app.db.database import Database, row_to_dict, utc_now


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class ProviderConnectionRepository:
    """Stores public connection state separately from explicitly accessed secrets."""

    SECRET_FIELDS = {"access_token_protected", "refresh_token_protected"}

    def __init__(self, database: Database, protector: SecretProtector) -> None:
        self.db = database
        self.protector = protector

    @classmethod
    def _public(cls, row: Any) -> dict[str, Any] | None:
        item = row_to_dict(row)
        if not item:
            return None
        for key in cls.SECRET_FIELDS:
            item.pop(key, None)
        item["scopes"] = json.loads(item.pop("scopes_json") or "[]")
        item["refresh_metadata"] = json.loads(item.pop("refresh_metadata_json") or "{}")
        return item

    def list(
        self, *, account_id: str | None = None, transport: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if account_id:
            clauses.append("account_id=?")
            parameters.append(account_id)
        if transport:
            clauses.append("transport=?")
            parameters.append(transport)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.db.connection() as connection:
            return [self._public(row) for row in connection.execute(
                f"SELECT account_connections.*,platform_apps.name AS platform_app_name FROM account_connections LEFT JOIN platform_apps ON platform_apps.id=account_connections.platform_app_id{where} ORDER BY account_connections.created_at", parameters
            )]

    def get(self, connection_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            return self._public(connection.execute(
                "SELECT account_connections.*,platform_apps.name AS platform_app_name FROM account_connections LEFT JOIN platform_apps ON platform_apps.id=account_connections.platform_app_id WHERE account_connections.id=?", (connection_id,)
            ).fetchone())

    def upsert(
        self, *, account_id: str, provider: str, transport: str = "official_api",
        external_account_id: str | None = None, status: str = "connected",
        scopes: list[str] | tuple[str, ...] = (), access_token: str | None = None,
        refresh_token: str | None = None, expires_at: str | None = None,
        refresh_metadata: dict[str, Any] | None = None, platform_app_id: str | None = None,
    ) -> dict[str, Any]:
        if transport not in {"official_api", "chrome"}:
            raise ValueError("Transport kết nối không hợp lệ.")
        if status not in {"connected", "disconnected", "expiring", "reauth_required", "scope_missing", "revoked"}:
            raise ValueError("Trạng thái kết nối không hợp lệ.")
        now = utc_now()
        with self.db.connection() as connection:
            existing = connection.execute(
                "SELECT * FROM account_connections WHERE account_id=? AND transport=? AND provider=?",
                (account_id, transport, provider),
            ).fetchone()
            connection_id = existing["id"] if existing else str(uuid.uuid4())
            protected_access = (
                self.protector.protect_oauth(access_token) if access_token is not None
                else (existing["access_token_protected"] if existing else None)
            )
            protected_refresh = (
                self.protector.protect_oauth(refresh_token) if refresh_token is not None
                else (existing["refresh_token_protected"] if existing else None)
            )
            connection.execute(
                "INSERT INTO account_connections(id,account_id,transport,provider,external_account_id,status,scopes_json,access_token_protected,refresh_token_protected,expires_at,refresh_metadata_json,platform_app_id,granted_at,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(account_id,transport,provider) DO UPDATE SET "
                "external_account_id=excluded.external_account_id,status=excluded.status,scopes_json=excluded.scopes_json,"
                "access_token_protected=excluded.access_token_protected,refresh_token_protected=excluded.refresh_token_protected,"
                "expires_at=excluded.expires_at,refresh_metadata_json=excluded.refresh_metadata_json,platform_app_id=COALESCE(excluded.platform_app_id,account_connections.platform_app_id),granted_at=COALESCE(account_connections.granted_at,excluded.granted_at),updated_at=excluded.updated_at",
                (connection_id, account_id, transport, provider, external_account_id, status, _json(sorted(set(scopes))),
                 protected_access, protected_refresh, expires_at, _json(refresh_metadata or {}), platform_app_id, now, now, now),
            )
        return self.get(connection_id)

    def secrets(self, connection_id: str) -> dict[str, str | None]:
        with self.db.connection() as connection:
            row = connection.execute(
                "SELECT access_token_protected,refresh_token_protected FROM account_connections WHERE id=?",
                (connection_id,),
            ).fetchone()
        if not row:
            raise KeyError(connection_id)
        return {
            "access_token": self.protector.unprotect_oauth(row[0]) if row[0] else None,
            "refresh_token": self.protector.unprotect_oauth(row[1]) if row[1] else None,
        }

    def set_status(self, connection_id: str, status: str, *, error_code: str | None = None, error_message: str | None = None) -> dict[str, Any]:
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE account_connections SET status=?,last_error_code=?,last_error_message=?,last_validated_at=?,updated_at=? WHERE id=?",
                (status, error_code, error_message[:1000] if error_message else None, utc_now(), utc_now(), connection_id),
            )
        result = self.get(connection_id)
        if not result:
            raise KeyError(connection_id)
        return result

    def set_refresh_metadata(self, connection_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE account_connections SET refresh_metadata_json=?,updated_at=? WHERE id=?",
                (_json(metadata), utc_now(), connection_id),
            )
        result = self.get(connection_id)
        if not result:
            raise KeyError(connection_id)
        return result

    def bump_credential_revision(self, connection_id: str) -> dict[str, Any]:
        with self.db.connection() as connection:
            row = connection.execute(
                "SELECT refresh_metadata_json FROM account_connections WHERE id=?", (connection_id,),
            ).fetchone()
            if not row:
                raise KeyError(connection_id)
            metadata = json.loads(row["refresh_metadata_json"] or "{}")
            try:
                revision = int(metadata.get("credential_revision") or 0)
            except (TypeError, ValueError):
                revision = 0
            metadata["credential_revision"] = revision + 1
            connection.execute(
                "UPDATE account_connections SET refresh_metadata_json=?,updated_at=? WHERE id=?",
                (_json(metadata), utc_now(), connection_id),
            )
        return self.get(connection_id)  # type: ignore[return-value]

    def refresh_meta_connected_page_count(self, connection_id: str) -> dict[str, Any]:
        """Refresh Meta Page count without overwriting concurrent credential metadata."""
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT refresh_metadata_json FROM account_connections "
                    "WHERE id=? AND provider='meta' AND transport='official_api'",
                    (connection_id,),
                ).fetchone()
                if not row:
                    raise KeyError(connection_id)
                metadata = json.loads(row["refresh_metadata_json"] or "{}")
                count = connection.execute(
                    "SELECT COUNT(*) FROM provider_target_connections "
                    "WHERE connection_id=? AND provider='meta' AND status='connected'",
                    (connection_id,),
                ).fetchone()[0]
                metadata["connected_page_count"] = int(count)
                connection.execute(
                    "UPDATE account_connections SET refresh_metadata_json=?,updated_at=? WHERE id=?",
                    (_json(metadata), utc_now(), connection_id),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        result = self.get(connection_id)
        if not result:
            raise KeyError(connection_id)
        return result

    def delete(self, connection_id: str, *, account_id: str | None = None) -> bool:
        with self.db.connection() as connection:
            if account_id:
                cursor = connection.execute(
                    "DELETE FROM account_connections WHERE id=? AND account_id=?", (connection_id, account_id),
                )
            else:
                cursor = connection.execute("DELETE FROM account_connections WHERE id=?", (connection_id,))
        return cursor.rowcount > 0

    def health_counts(self) -> dict[str, int]:
        with self.db.connection() as connection:
            rows = connection.execute("SELECT status,COUNT(*) count FROM account_connections GROUP BY status").fetchall()
        return {row["status"]: row["count"] for row in rows}


class OAuthStateRepository:
    def __init__(self, database: Database, protector: SecretProtector) -> None:
        self.db = database
        self.protector = protector

    def create(self, account_id: str, provider: str, *, pkce_verifier: str | None = None, redirect_uri: str | None = None, platform_app_id: str | None = None, ttl_seconds: int = 600) -> str:
        state = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        with self.db.connection() as connection:
            connection.execute(
                "INSERT INTO oauth_states(id,state_hash,account_id,provider,pkce_verifier_protected,redirect_uri,platform_app_id,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), hashlib.sha256(state.encode()).hexdigest(), account_id, provider,
                 self.protector.protect_oauth(pkce_verifier) if pkce_verifier else None, redirect_uri,
                 platform_app_id, (now + timedelta(seconds=ttl_seconds)).isoformat(), now.isoformat()),
            )
        return state

    def consume(self, state: str, provider: str) -> dict[str, Any]:
        digest = hashlib.sha256(state.encode()).hexdigest()
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM oauth_states WHERE state_hash=? AND provider=? AND consumed_at IS NULL AND expires_at>?",
                    (digest, provider, now),
                ).fetchone()
                if not row:
                    raise ValueError("OAuth state không hợp lệ, đã dùng hoặc hết hạn.")
                connection.execute("UPDATE oauth_states SET consumed_at=? WHERE id=?", (now, row["id"]))
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return {
            "account_id": row["account_id"], "provider": row["provider"],
            "redirect_uri": row["redirect_uri"], "platform_app_id": row["platform_app_id"],
            "pkce_verifier": self.protector.unprotect_oauth(row["pkce_verifier_protected"]) if row["pkce_verifier_protected"] else None,
        }


class ProviderTargetConnectionRepository:
    """Stores provider tokens and permissions that are specific to an external target."""

    def __init__(self, database: Database, protector: SecretProtector) -> None:
        self.db = database
        self.protector = protector

    @staticmethod
    def _public(row: Any) -> dict[str, Any] | None:
        item = row_to_dict(row)
        if not item:
            return None
        item.pop("access_token_protected", None)
        item["tasks"] = json.loads(item.pop("tasks_json") or "[]")
        return item

    @staticmethod
    def _validate_meta_page_target(connection: Any, connection_id: str, target_id: str,
                                   external_target_id: str) -> None:
        owner = connection.execute(
            "SELECT c.account_id,t.account_id AS target_account_id,t.platform "
            "FROM account_connections c JOIN publishing_targets t ON t.id=? "
            "WHERE c.id=? AND c.provider='meta'",
            (target_id, connection_id),
        ).fetchone()
        if not owner or owner["account_id"] != owner["target_account_id"] or owner["platform"] != "facebook":
            raise ValueError("Meta Page binding phải trỏ tới target Facebook thuộc đúng account.")
        prior_target = connection.execute(
            "SELECT external_target_id FROM provider_target_connections "
            "WHERE provider='meta' AND target_id=? AND external_target_id<>? LIMIT 1",
            (target_id, external_target_id),
        ).fetchone()
        if prior_target:
            raise ValueError(
                f"Tinix target {target_id} đã được liên kết với Meta Page "
                f"{prior_target['external_target_id']}; không thể chuyển target sang Page {external_target_id}."
            )
        prior_page = connection.execute(
            "SELECT target_id FROM provider_target_connections "
            "WHERE provider='meta' AND external_target_id=? AND target_id<>? LIMIT 1",
            (external_target_id, target_id),
        ).fetchone()
        if prior_page:
            raise ValueError(
                f"Meta Page {external_target_id} đã được liên kết với Tinix target "
                f"{prior_page['target_id']}; không thể tạo liên kết trùng."
            )

    def upsert(
        self, *, connection_id: str, target_id: str, provider: str,
        external_target_id: str, access_token: str, tasks: list[str],
    ) -> dict[str, Any]:
        now = utc_now()
        protected = self.protector.protect_oauth(access_token)
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if provider == "meta":
                    self._validate_meta_page_target(connection, connection_id, target_id, str(external_target_id))
                connection.execute(
                    "INSERT INTO provider_target_connections(id,connection_id,target_id,provider,external_target_id,access_token_protected,tasks_json,status,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(connection_id,target_id) DO UPDATE SET "
                    "provider=excluded.provider,external_target_id=excluded.external_target_id,access_token_protected=excluded.access_token_protected,"
                    "tasks_json=excluded.tasks_json,status='connected',updated_at=excluded.updated_at",
                    (str(uuid.uuid4()), connection_id, target_id, provider, external_target_id,
                     protected, json.dumps(sorted(set(tasks))), "connected", now, now),
                )
                row = connection.execute(
                    "SELECT * FROM provider_target_connections WHERE connection_id=? AND target_id=?",
                    (connection_id, target_id),
                ).fetchone()
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self._public(row)  # type: ignore[return-value]

    def sync_meta_oauth_bindings(
        self, *, connection_id: str | None, bindings: list[dict[str, Any]], credential_changed: bool,
        oauth_connection: dict[str, Any] | None = None,
        expected_credential_revision: int | None = None,
    ) -> list[dict[str, Any]]:
        """Atomically save an OAuth connection (when supplied), targets, and Page bindings."""
        now = utc_now()
        protected_user_token = (
            self.protector.protect_oauth(str(oauth_connection["access_token"]))
            if oauth_connection and oauth_connection.get("access_token") else None
        )
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if oauth_connection:
                    account_id = str(oauth_connection["account_id"])
                    existing_connection = connection.execute(
                        "SELECT id,refresh_metadata_json FROM account_connections "
                        "WHERE account_id=? AND provider='meta' AND transport='official_api'",
                        (account_id,),
                    ).fetchone()
                    actual_connection_id = existing_connection["id"] if existing_connection else None
                    if actual_connection_id != connection_id:
                        raise RuntimeError("Meta connection đã thay đổi trong lúc OAuth; hãy kết nối lại để thử lại.")
                    old_metadata = json.loads(existing_connection["refresh_metadata_json"] or "{}") if existing_connection else {}
                    try:
                        old_revision = int(old_metadata.get("credential_revision") or 0)
                    except (TypeError, ValueError):
                        old_revision = 0
                    if expected_credential_revision is not None and old_revision != expected_credential_revision:
                        raise RuntimeError("Meta token đã thay đổi trong lúc OAuth; hãy kết nối lại để thử lại.")
                    granted_page_ids = {str(item["external_target_id"]) for item in bindings}
                    connected_page_ids = {
                        str(row["external_target_id"])
                        for row in connection.execute(
                            "SELECT external_target_id FROM provider_target_connections "
                            "WHERE connection_id=? AND provider='meta' AND status='connected'",
                            (connection_id,),
                        ).fetchall()
                    }
                    missing_page_ids = connected_page_ids - granted_page_ids
                    if missing_page_ids:
                        raise RuntimeError(
                            "OAuth không còn quyền với các Page đang kết nối: "
                            + ", ".join(sorted(missing_page_ids))
                            + ". Kết nối hiện tại được giữ nguyên; hãy ngắt rõ Page bị thiếu rồi thử lại."
                        )
                    try:
                        revision = int(old_metadata.get("credential_revision") or 0) + 1
                    except (TypeError, ValueError):
                        revision = 1
                    metadata = {**(oauth_connection.get("refresh_metadata") or {}), "credential_revision": revision}
                    connection_id = existing_connection["id"] if existing_connection else str(uuid.uuid4())
                    connection.execute(
                        "INSERT INTO account_connections(id,account_id,transport,provider,external_account_id,status,scopes_json,"
                        "access_token_protected,refresh_token_protected,expires_at,refresh_metadata_json,platform_app_id,granted_at,created_at,updated_at) "
                        "VALUES(?,?,'official_api','meta',?,'connected',?,?,NULL,?,?,?,?,?,?) "
                        "ON CONFLICT(account_id,transport,provider) DO UPDATE SET "
                        "external_account_id=excluded.external_account_id,status='connected',scopes_json=excluded.scopes_json,"
                        "access_token_protected=excluded.access_token_protected,refresh_token_protected=NULL,"
                        "expires_at=excluded.expires_at,refresh_metadata_json=excluded.refresh_metadata_json,"
                        "platform_app_id=excluded.platform_app_id,updated_at=excluded.updated_at",
                        (connection_id, account_id, oauth_connection.get("external_account_id"),
                         _json(sorted(set(oauth_connection.get("scopes") or []))), protected_user_token,
                         oauth_connection.get("expires_at"), _json(metadata), oauth_connection["platform_app_id"],
                         now, now, now),
                    )
                owner = connection.execute(
                    "SELECT account_id,refresh_metadata_json FROM account_connections "
                    "WHERE id=? AND provider='meta' AND transport='official_api'",
                    (connection_id,),
                ).fetchone()
                if not owner:
                    raise KeyError(connection_id)
                if not oauth_connection and expected_credential_revision is not None:
                    current_metadata = json.loads(owner["refresh_metadata_json"] or "{}")
                    try:
                        current_revision = int(current_metadata.get("credential_revision") or 0)
                    except (TypeError, ValueError):
                        current_revision = 0
                    if current_revision != expected_credential_revision:
                        raise RuntimeError("Meta token đã thay đổi trong lúc đồng bộ; hãy đồng bộ lại.")
                account_id = owner["account_id"]
                resolved: list[tuple[dict[str, Any], str]] = []
                for item in bindings:
                    external_id = str(item["external_target_id"])
                    target_id = item.get("target_id")
                    target_data = item.get("target") or {}
                    if not target_id:
                        duplicate = connection.execute(
                            "SELECT account_id FROM publishing_targets WHERE platform='facebook' AND external_id=? LIMIT 1",
                            (external_id,),
                        ).fetchone()
                        if duplicate and duplicate["account_id"] != account_id:
                            raise ValueError(f"Page {external_id} đã thuộc một account Facebook Tinix khác.")
                        existing_target = connection.execute(
                            "SELECT id FROM publishing_targets WHERE account_id=? AND platform='facebook' AND external_id=?",
                            (account_id, external_id),
                        ).fetchone()
                        if existing_target:
                            target_id = existing_target["id"]
                        else:
                            target_id = str(uuid.uuid4())
                            connection.execute(
                                "INSERT INTO publishing_targets(id,account_id,platform,target_type,external_id,name,url,enabled,access_status,can_publish,last_synced_at,last_error,created_at,updated_at) "
                                "VALUES(?,?,'facebook','page',?,?,?,1,'accessible',NULL,?,NULL,?,?)",
                                (target_id, account_id, external_id,
                                 str(target_data.get("name") or external_id), target_data.get("url"), now, now, now),
                            )
                    else:
                        connection.execute(
                            "UPDATE publishing_targets SET name=COALESCE(?,name),url=COALESCE(?,url),"
                            "access_status='accessible',last_synced_at=?,last_error=NULL,updated_at=? "
                            "WHERE id=? AND account_id=? AND platform='facebook'",
                            (target_data.get("name"), target_data.get("url"), now, now, target_id, account_id),
                        )
                    self._validate_meta_page_target(connection, connection_id, str(target_id), external_id)
                    resolved.append((item, str(target_id)))

                for item, target_id in resolved:
                    connection.execute(
                        "INSERT INTO provider_target_connections(id,connection_id,target_id,provider,external_target_id,access_token_protected,tasks_json,status,created_at,updated_at) "
                        "VALUES(?,?,?,'meta',?,?,?,'connected',?,?) ON CONFLICT(connection_id,target_id) DO UPDATE SET "
                        "external_target_id=excluded.external_target_id,access_token_protected=excluded.access_token_protected,"
                        "tasks_json=excluded.tasks_json,status='connected',updated_at=excluded.updated_at",
                        (str(uuid.uuid4()), connection_id, target_id, str(item["external_target_id"]),
                         self.protector.protect_oauth(str(item["access_token"])),
                         _json(sorted(set(item.get("tasks") or []))), now, now),
                    )

                # OAuth callback already advances the revision while writing the
                # new connection above. Ordinary Page syncs advance it here.
                if credential_changed and not oauth_connection:
                    metadata = json.loads(owner["refresh_metadata_json"] or "{}")
                    try:
                        revision = int(metadata.get("credential_revision") or 0)
                    except (TypeError, ValueError):
                        revision = 0
                    metadata["credential_revision"] = revision + 1
                    connection.execute(
                        "UPDATE account_connections SET refresh_metadata_json=?,updated_at=? WHERE id=?",
                        (_json(metadata), now, connection_id),
                    )
                rows = connection.execute(
                    "SELECT * FROM provider_target_connections WHERE connection_id=? AND provider='meta' AND status='connected' ORDER BY target_id",
                    (connection_id,),
                ).fetchall()
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return [self._public(row) for row in rows]  # type: ignore[misc]

    def upsert_system_user_bindings(
        self, *, account_id: str, platform_app_id: str, external_account_id: str,
        scopes: list[str], access_token: str | None, credential_changed: bool,
        bindings: list[dict[str, Any]], disconnect_page_ids: list[str],
        refresh_metadata: dict[str, Any], expected_credential_revision: int | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Atomically update a Meta token and the explicitly selected Page bindings."""
        now = utc_now()
        protected_user = self.protector.protect_oauth(access_token) if access_token is not None else None
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT id,refresh_metadata_json FROM account_connections "
                    "WHERE account_id=? AND transport='official_api' AND provider='meta'",
                    (account_id,),
                ).fetchone()
                previous_metadata = json.loads(existing["refresh_metadata_json"] or "{}") if existing else {}
                try:
                    revision = int(previous_metadata.get("credential_revision") or 0)
                except (TypeError, ValueError):
                    revision = 0
                if expected_credential_revision is not None and revision != expected_credential_revision:
                    raise RuntimeError("Meta token đã thay đổi trong lúc đồng bộ; hãy đồng bộ lại.")
                if credential_changed and existing:
                    selected_page_ids = {str(item["external_target_id"]) for item in bindings}
                    explicitly_disconnected = {str(page_id) for page_id in disconnect_page_ids}
                    connected_page_ids = {
                        str(row["external_target_id"])
                        for row in connection.execute(
                            "SELECT external_target_id FROM provider_target_connections "
                            "WHERE connection_id=? AND provider='meta' AND status='connected'",
                            (existing["id"],),
                        ).fetchall()
                    }
                    omitted_page_ids = connected_page_ids - selected_page_ids - explicitly_disconnected
                    if omitted_page_ids:
                        raise ValueError(
                            "Xác nhận rõ các Page sẽ ngắt khi đổi token: "
                            + ", ".join(sorted(omitted_page_ids)) + "."
                        )
                if credential_changed or not revision:
                    revision += 1
                metadata = {**refresh_metadata, "credential_revision": revision}
                connection_id = existing["id"] if existing else str(uuid.uuid4())
                connection.execute(
                    "INSERT INTO account_connections(id,account_id,transport,provider,external_account_id,status,scopes_json,access_token_protected,refresh_token_protected,expires_at,refresh_metadata_json,platform_app_id,granted_at,created_at,updated_at) "
                    "VALUES(?,?,'official_api','meta',?,'connected',?,?,NULL,NULL,?,?,?, ?,?) "
                    "ON CONFLICT(account_id,transport,provider) DO UPDATE SET "
                    "external_account_id=excluded.external_account_id,status='connected',scopes_json=excluded.scopes_json,"
                    "access_token_protected=COALESCE(excluded.access_token_protected,account_connections.access_token_protected),"
                    "refresh_token_protected=NULL,expires_at=NULL,refresh_metadata_json=excluded.refresh_metadata_json,"
                    "platform_app_id=excluded.platform_app_id,updated_at=excluded.updated_at",
                    (connection_id, account_id, external_account_id, _json(sorted(set(scopes))),
                     protected_user, _json(metadata), platform_app_id, now, now, now),
                )
                for item in bindings:
                    target_id = item.get("target_id")
                    target_data = item.get("target") or {}
                    if not target_id:
                        target_data = dict(target_data)
                        target_id = str(uuid.uuid4())
                        target_account_id = str(target_data.get("account_id") or account_id)
                        target_platform = str(target_data.get("platform") or "facebook")
                        external_id = str(target_data.get("external_id") or item["external_target_id"])
                        duplicate = connection.execute(
                            "SELECT account_id FROM publishing_targets WHERE platform=? AND external_id=? LIMIT 1",
                            (target_platform, external_id),
                        ).fetchone()
                        if duplicate and duplicate["account_id"] != target_account_id:
                            raise ValueError(f"Page {external_id} đã thuộc một account Tinix khác.")
                        existing_target = connection.execute(
                            "SELECT id FROM publishing_targets WHERE account_id=? AND platform=? AND external_id=?",
                            (target_account_id, target_platform, external_id),
                        ).fetchone()
                        if existing_target:
                            target_id = existing_target["id"]
                        else:
                            connection.execute(
                                "INSERT INTO publishing_targets(id,account_id,platform,target_type,external_id,name,url,enabled,access_status,can_publish,last_synced_at,last_error,created_at,updated_at) "
                                "VALUES(?,?,?,?,?,?,?,1,'accessible',NULL,?,NULL,?,?)",
                                (target_id, target_account_id, target_platform,
                                 str(target_data.get("target_type") or "page"), external_id,
                                 str(target_data.get("name") or external_id), target_data.get("url"),
                                 now, now, now),
                            )
                    elif target_data:
                        connection.execute(
                            "UPDATE publishing_targets SET name=COALESCE(?,name),url=COALESCE(?,url),"
                            "access_status='accessible',last_synced_at=?,last_error=NULL,updated_at=? "
                            "WHERE id=? AND account_id=? AND platform='facebook'",
                            (target_data.get("name"), target_data.get("url"), now, now, target_id, account_id),
                        )
                        if not connection.execute(
                            "SELECT 1 FROM publishing_targets WHERE id=? AND account_id=? AND platform='facebook'",
                            (target_id, account_id),
                        ).fetchone():
                            raise ValueError("Meta binding phải trỏ tới target Facebook thuộc đúng account.")
                    protected_page = self.protector.protect_oauth(str(item["access_token"]))
                    external_target_id = str(item["external_target_id"])
                    self._validate_meta_page_target(connection, connection_id, str(target_id), external_target_id)
                    binding_id = str(uuid.uuid4())
                    connection.execute(
                        "INSERT INTO provider_target_connections(id,connection_id,target_id,provider,external_target_id,access_token_protected,tasks_json,status,created_at,updated_at) "
                        "VALUES(?,?,?,'meta',?,?,?,'connected',?,?) ON CONFLICT(connection_id,target_id) DO UPDATE SET "
                        "provider='meta',external_target_id=excluded.external_target_id,"
                        "access_token_protected=excluded.access_token_protected,tasks_json=excluded.tasks_json,"
                        "status='connected',updated_at=excluded.updated_at",
                        (binding_id, connection_id, target_id, external_target_id,
                         protected_page, _json(sorted(set(item.get("tasks") or []))), now, now),
                    )
                for page_id in sorted(set(disconnect_page_ids)):
                    connection.execute(
                        "UPDATE provider_target_connections SET status='disconnected',updated_at=? "
                        "WHERE connection_id=? AND provider='meta' AND external_target_id=?",
                        (now, connection_id, page_id),
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        with self.db.connection() as connection:
            connection_row = connection.execute(
                "SELECT account_connections.*,platform_apps.name AS platform_app_name "
                "FROM account_connections LEFT JOIN platform_apps ON platform_apps.id=account_connections.platform_app_id "
                "WHERE account_connections.id=?", (connection_id,),
            ).fetchone()
            binding_rows = connection.execute(
                "SELECT * FROM provider_target_connections WHERE connection_id=? AND status='connected' ORDER BY target_id",
                (connection_id,),
            ).fetchall()
        return (
            ProviderConnectionRepository._public(connection_row),  # type: ignore[arg-type,return-value]
            [self._public(row) for row in binding_rows],  # type: ignore[list-item]
        )

    def disconnect_and_bump_revision(self, binding_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT connection_id FROM provider_target_connections WHERE id=? AND provider='meta'",
                    (binding_id,),
                ).fetchone()
                if not row:
                    connection.execute("ROLLBACK")
                    return None
                now = utc_now()
                connection.execute(
                    "UPDATE provider_target_connections SET status='disconnected',updated_at=? WHERE id=?",
                    (now, binding_id),
                )
                parent = connection.execute(
                    "SELECT refresh_metadata_json FROM account_connections WHERE id=? AND provider='meta'",
                    (row["connection_id"],),
                ).fetchone()
                if parent:
                    metadata = json.loads(parent["refresh_metadata_json"] or "{}")
                    try:
                        revision = int(metadata.get("credential_revision") or 0)
                    except (TypeError, ValueError):
                        revision = 0
                    metadata["credential_revision"] = revision + 1
                    connection.execute(
                        "UPDATE account_connections SET refresh_metadata_json=?,updated_at=? WHERE id=?",
                        (_json(metadata), now, row["connection_id"]),
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get(binding_id)

    def get(self, binding_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            return self._public(connection.execute(
                "SELECT * FROM provider_target_connections WHERE id=?", (binding_id,),
            ).fetchone())

    def for_target(self, target_id: str, connection_id: str | None = None) -> dict[str, Any] | None:
        clauses = ["target_id=?", "status='connected'"]
        values: list[Any] = [target_id]
        if connection_id:
            clauses.append("connection_id=?")
            values.append(connection_id)
        with self.db.connection() as connection:
            return self._public(connection.execute(
                "SELECT * FROM provider_target_connections WHERE " + " AND ".join(clauses) + " ORDER BY updated_at DESC LIMIT 1",
                values,
            ).fetchone())

    def list(self, connection_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            rows = connection.execute(
                "SELECT b.*,t.name AS target_name,t.url AS target_url FROM provider_target_connections b "
                "JOIN publishing_targets t ON t.id=b.target_id WHERE b.connection_id=? ORDER BY t.name",
                (connection_id,),
            ).fetchall()
        return [self._public(row) for row in rows]  # type: ignore[misc]

    def token(self, binding_id: str) -> str:
        with self.db.connection() as connection:
            row = connection.execute(
                "SELECT access_token_protected FROM provider_target_connections WHERE id=? AND status='connected'",
                (binding_id,),
            ).fetchone()
        if not row:
            raise KeyError(binding_id)
        return self.protector.unprotect_oauth(row[0])
