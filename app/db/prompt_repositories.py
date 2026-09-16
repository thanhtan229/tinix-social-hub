from __future__ import annotations

import uuid
from typing import Any

from app.db.database import Database, utc_now


class PromptTemplateRepository:
    """Persistent, user-editable AI Studio system prompts."""

    def __init__(self, database: Database) -> None:
        self.db = database

    @staticmethod
    def _public(row: Any) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        return item

    @staticmethod
    def _clean_name(value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Tên System Prompt không được để trống.")
        return cleaned

    @staticmethod
    def _clean_prompt(value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Nội dung System Prompt không được để trống.")
        return cleaned

    def get(self, template_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM prompt_templates WHERE id=?", (template_id,)).fetchone()
        return self._public(row)

    def get_by_operation(self, operation: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            row = connection.execute(
                "SELECT * FROM prompt_templates WHERE operation=? AND enabled=1 ORDER BY created_at LIMIT 1",
                (operation,),
            ).fetchone()
        return self._public(row)

    def list(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM prompt_templates"
        if enabled_only:
            query += " WHERE enabled=1"
        query += " ORDER BY name COLLATE NOCASE"
        with self.db.connection() as connection:
            rows = connection.execute(query).fetchall()
        return [self._public(row) for row in rows]

    def _name_used(self, name: str, excluding_id: str | None = None) -> bool:
        query = "SELECT 1 FROM prompt_templates WHERE name=?"
        values: list[str] = [name]
        if excluding_id:
            query += " AND id<>?"
            values.append(excluding_id)
        with self.db.connection() as connection:
            return connection.execute(query, values).fetchone() is not None

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        name = self._clean_name(str(data.get("name") or ""))
        system_prompt = self._clean_prompt(str(data.get("system_prompt") or ""))
        if self._name_used(name):
            raise ValueError("Tên System Prompt đã tồn tại.")
        template_id, now = str(uuid.uuid4()), utc_now()
        with self.db.connection() as connection:
            connection.execute(
                "INSERT INTO prompt_templates(id,name,operation,system_prompt,user_template,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    template_id, name, "custom", system_prompt, "ai-studio-context-v1",
                    int(bool(data.get("enabled", True))), now, now,
                ),
            )
        return self.get(template_id)  # type: ignore[return-value]

    def update(self, template_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get(template_id)
        if not current:
            return None
        name = self._clean_name(str(data.get("name") or ""))
        system_prompt = self._clean_prompt(str(data.get("system_prompt") or ""))
        if self._name_used(name, excluding_id=template_id):
            raise ValueError("Tên System Prompt đã tồn tại.")
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE prompt_templates SET name=?,system_prompt=?,enabled=?,updated_at=? WHERE id=?",
                (name, system_prompt, int(bool(data.get("enabled", True))), utc_now(), template_id),
            )
        return self.get(template_id)

    def delete(self, template_id: str) -> bool:
        with self.db.connection() as connection:
            return connection.execute("DELETE FROM prompt_templates WHERE id=?", (template_id,)).rowcount > 0
