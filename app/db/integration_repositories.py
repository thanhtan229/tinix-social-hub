from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.parse import urlparse

from app.core.secrets import SecretProtector
from app.db.database import Database, row_to_dict, utc_now
from app.integrations.catalog import ai_provider, platform_app


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _hint(value: str) -> str:
    return f"••••{value[-4:]}" if value else ""


class AIProviderConfigRepository:
    SECRET_FIELDS = {"api_key_protected"}

    def __init__(self, database: Database, protector: SecretProtector) -> None:
        self.db = database
        self.protector = protector

    @classmethod
    def _public(cls, row: Any) -> dict[str, Any] | None:
        item = row_to_dict(row)
        if not item:
            return None
        for field in cls.SECRET_FIELDS:
            item.pop(field, None)
        item["has_api_key"] = bool(item.get("key_hint", ""))
        return item

    def list(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM ai_provider_configs"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY provider,name"
        with self.db.connection() as connection:
            return [self._public(row) for row in connection.execute(sql)]

    def get(self, config_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            return self._public(connection.execute("SELECT * FROM ai_provider_configs WHERE id=?", (config_id,)).fetchone())

    @staticmethod
    def _base_url(definition: dict[str, Any], base_url: str | None) -> str:
        if not definition.get("requires_base_url"):
            return definition["base_url"]
        value = (base_url or "").strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Base URL của OpenAI-compatible phải là URL http/https tuyệt đối.")
        return value

    def create(self, *, provider: str, name: str, api_key: str, base_url: str | None = None, text_model: str = "", image_model: str = "", enabled: bool = True) -> dict[str, Any]:
        definition = ai_provider(provider)
        clean_key = api_key.strip()
        if not clean_key:
            raise ValueError("API key không được để trống.")
        config_id, now = str(uuid.uuid4()), utc_now()
        with self.db.connection() as connection:
            connection.execute(
                "INSERT INTO ai_provider_configs(id,provider,name,base_url,api_key_protected,key_hint,text_model,image_model,enabled,last_test_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'untested',?,?)",
                (config_id, provider, name.strip(), self._base_url(definition, base_url), self.protector.protect_secret(clean_key), _hint(clean_key), text_model.strip() or definition["recommended_text_model"], image_model.strip(), int(enabled), now, now),
            )
        return self.get(config_id)  # type: ignore[return-value]

    def update(self, config_id: str, *, name: str | None = None, api_key: str | None = None, base_url: str | None = None, text_model: str | None = None, image_model: str | None = None, enabled: bool | None = None) -> dict[str, Any]:
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM ai_provider_configs WHERE id=?", (config_id,)).fetchone()
            if not row:
                raise KeyError(config_id)
            fields: list[str] = ["updated_at=?"]
            values: list[Any] = [utc_now()]
            if name is not None:
                fields.append("name=?"); values.append(name.strip())
            if api_key is not None:
                clean_key = api_key.strip()
                if not clean_key:
                    raise ValueError("API key mới không được để trống.")
                fields.extend(["api_key_protected=?", "key_hint=?", "last_test_status='untested'", "last_test_at=NULL", "last_error_code=NULL", "last_error_message=NULL"])
                values.extend([self.protector.protect_secret(clean_key), _hint(clean_key)])
            if base_url is not None:
                fields.append("base_url=?")
                values.append(self._base_url(ai_provider(row["provider"]), base_url))
            if text_model is not None:
                fields.append("text_model=?"); values.append(text_model.strip())
            if image_model is not None:
                fields.append("image_model=?"); values.append(image_model.strip())
            if enabled is not None:
                fields.append("enabled=?"); values.append(int(enabled))
            values.append(config_id)
            connection.execute(f"UPDATE ai_provider_configs SET {','.join(fields)} WHERE id=?", values)
        return self.get(config_id)  # type: ignore[return-value]

    def delete(self, config_id: str) -> bool:
        with self.db.connection() as connection:
            return connection.execute("DELETE FROM ai_provider_configs WHERE id=?", (config_id,)).rowcount > 0

    def secret(self, config_id: str) -> str:
        with self.db.connection() as connection:
            row = connection.execute("SELECT api_key_protected FROM ai_provider_configs WHERE id=?", (config_id,)).fetchone()
        if not row:
            raise KeyError(config_id)
        return self.protector.unprotect_secret(row[0])

    def replace_models(self, config_id: str, models: list[dict[str, Any]]) -> None:
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("DELETE FROM ai_provider_models WHERE config_id=?", (config_id,))
                connection.executemany(
                    "INSERT INTO ai_provider_models(config_id,model_id,display_name,capabilities_json,raw_metadata_json,fetched_at) VALUES(?,?,?,?,?,?)",
                    [(config_id, item["model_id"], item.get("display_name") or item["model_id"], _json(item.get("capabilities", ["text"])), _json(item.get("metadata") or {}), now) for item in models[:500]],
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def models(self, config_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            if not connection.execute("SELECT 1 FROM ai_provider_configs WHERE id=?", (config_id,)).fetchone():
                raise KeyError(config_id)
            rows = connection.execute("SELECT * FROM ai_provider_models WHERE config_id=? ORDER BY model_id", (config_id,)).fetchall()
        return [{**row_to_dict(row), "capabilities": json.loads(row["capabilities_json"]), "metadata": json.loads(row["raw_metadata_json"])} for row in rows]

    def model_display_name(self, config_id: str, model_id: str) -> str:
        with self.db.connection() as connection:
            row = connection.execute(
                "SELECT display_name FROM ai_provider_models WHERE config_id=? AND model_id=?",
                (config_id, model_id),
            ).fetchone()
        return str(row[0]) if row and row[0] else model_id

    def mark_test(self, config_id: str, *, status: str, error_code: str | None = None, error_message: str | None = None) -> None:
        with self.db.connection() as connection:
            connection.execute("UPDATE ai_provider_configs SET last_test_status=?,last_test_at=?,last_error_code=?,last_error_message=?,updated_at=? WHERE id=?", (status, utc_now(), error_code, (error_message or "")[:500] or None, utc_now(), config_id))


class PlatformAppRepository:
    SECRET_FIELDS = {"client_secret_protected"}

    def __init__(self, database: Database, protector: SecretProtector) -> None:
        self.db = database
        self.protector = protector

    @classmethod
    def _public(cls, row: Any) -> dict[str, Any] | None:
        item = row_to_dict(row)
        if not item:
            return None
        for field in cls.SECRET_FIELDS:
            item.pop(field, None)
        item["has_client_secret"] = bool(item.get("secret_hint", ""))
        item["scopes"] = json.loads(item.pop("scopes_json") or "[]")
        return item

    def list(self, *, provider: str | None = None, enabled_only: bool = False) -> list[dict[str, Any]]:
        clauses, values = [], []
        if provider:
            clauses.append("provider=?"); values.append(provider)
        if enabled_only:
            clauses.append("enabled=1")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.db.connection() as connection:
            return [self._public(row) for row in connection.execute(f"SELECT * FROM platform_apps{where} ORDER BY provider,name", values)]

    def get(self, app_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            return self._public(connection.execute("SELECT * FROM platform_apps WHERE id=?", (app_id,)).fetchone())

    def create(self, *, provider: str, name: str, client_id: str, client_secret: str, redirect_uri: str, api_version: str = "", scopes: list[str] | None = None, enabled: bool = True) -> dict[str, Any]:
        definition = platform_app(provider)
        if not client_id.strip() or not client_secret.strip():
            raise ValueError("Client/App ID và Client Secret không được để trống.")
        app_id, now = str(uuid.uuid4()), utc_now()
        with self.db.connection() as connection:
            connection.execute(
                "INSERT INTO platform_apps(id,provider,name,client_id,client_secret_protected,secret_hint,redirect_uri,api_version,scopes_json,enabled,last_test_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,'untested',?,?)",
                (app_id, provider, name.strip(), client_id.strip(), self.protector.protect_secret(client_secret.strip()), _hint(client_secret.strip()), redirect_uri.strip(), api_version.strip(), _json(scopes if scopes is not None else definition["scopes"]), int(enabled), now, now),
            )
        return self.get(app_id)  # type: ignore[return-value]

    def update(self, app_id: str, *, name: str | None = None, client_id: str | None = None, client_secret: str | None = None, redirect_uri: str | None = None, api_version: str | None = None, scopes: list[str] | None = None, enabled: bool | None = None) -> dict[str, Any]:
        with self.db.connection() as connection:
            if not connection.execute("SELECT id FROM platform_apps WHERE id=?", (app_id,)).fetchone():
                raise KeyError(app_id)
            fields, values = ["updated_at=?"], [utc_now()]
            for field, value in (("name", name), ("client_id", client_id), ("redirect_uri", redirect_uri), ("api_version", api_version)):
                if value is not None:
                    fields.append(f"{field}=?"); values.append(value.strip())
            if client_secret is not None:
                clean_secret = client_secret.strip()
                if not clean_secret:
                    raise ValueError("Client Secret mới không được để trống.")
                fields.extend(["client_secret_protected=?", "secret_hint=?", "last_test_status='untested'", "last_test_at=NULL", "last_error_code=NULL", "last_error_message=NULL"])
                values.extend([self.protector.protect_secret(clean_secret), _hint(clean_secret)])
            if scopes is not None:
                fields.append("scopes_json=?"); values.append(_json(scopes))
            if enabled is not None:
                fields.append("enabled=?"); values.append(int(enabled))
            values.append(app_id)
            connection.execute(f"UPDATE platform_apps SET {','.join(fields)} WHERE id=?", values)
        return self.get(app_id)  # type: ignore[return-value]

    def secret(self, app_id: str) -> str:
        with self.db.connection() as connection:
            row = connection.execute("SELECT client_secret_protected FROM platform_apps WHERE id=?", (app_id,)).fetchone()
        if not row:
            raise KeyError(app_id)
        return self.protector.unprotect_secret(row[0])

    def delete(self, app_id: str) -> bool:
        with self.db.connection() as connection:
            refs = connection.execute("SELECT COUNT(*) FROM account_connections WHERE platform_app_id=?", (app_id,)).fetchone()[0]
            if refs:
                raise ValueError("Platform App đang được account connection sử dụng; hãy ngắt kết nối hoặc đổi app trước.")
            return connection.execute("DELETE FROM platform_apps WHERE id=?", (app_id,)).rowcount > 0

    def mark_test(self, app_id: str, *, status: str, error_code: str | None = None, error_message: str | None = None) -> None:
        with self.db.connection() as connection:
            connection.execute("UPDATE platform_apps SET last_test_status=?,last_test_at=?,last_error_code=?,last_error_message=?,updated_at=? WHERE id=?", (status, utc_now(), error_code, (error_message or "")[:500] or None, utc_now(), app_id))
