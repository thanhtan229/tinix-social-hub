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
