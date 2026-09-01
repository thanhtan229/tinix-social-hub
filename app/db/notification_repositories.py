from __future__ import annotations

import json
import uuid
from typing import Any

from app.db.database import Database, utc_now


class NotificationRepository:
    def __init__(self, database: Database) -> None:
        self.db = database

    def create(
        self, notification_type: str, title: str, message: str, *, severity: str = "info",
        entity_type: str | None = None, entity_id: str | None = None,
        dedupe_key: str | None = None, metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        notification_id = str(uuid.uuid4())
        with self.db.connection() as connection:
            connection.execute(
                "INSERT INTO notifications(id,notification_type,severity,title,message,entity_type,entity_id,dedupe_key,metadata_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(dedupe_key) DO UPDATE SET title=excluded.title,message=excluded.message,severity=excluded.severity,metadata_json=excluded.metadata_json,read_at=NULL,created_at=excluded.created_at",
                (notification_id, notification_type, severity, title, message, entity_type, entity_id,
                 dedupe_key, json.dumps(metadata or {}, ensure_ascii=False), utc_now()),
            )
            row = connection.execute(
                "SELECT * FROM notifications WHERE id=? OR (dedupe_key IS NOT NULL AND dedupe_key=?) ORDER BY created_at DESC LIMIT 1",
                (notification_id, dedupe_key),
            ).fetchone()
        return dict(row)

    def list(self, unread_only: bool = False, limit: int = 100) -> list[dict[str, Any]]:
        where = " WHERE read_at IS NULL" if unread_only else ""
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(
                f"SELECT * FROM notifications{where} ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 500)),)
            )]

    def mark_read(self, notification_id: str) -> bool:
        with self.db.connection() as connection:
            cursor = connection.execute(
                "UPDATE notifications SET read_at=COALESCE(read_at,?) WHERE id=?", (utc_now(), notification_id)
            )
        return cursor.rowcount > 0

    def mark_all_read(self) -> int:
        with self.db.connection() as connection:
            cursor = connection.execute("UPDATE notifications SET read_at=? WHERE read_at IS NULL", (utc_now(),))
        return cursor.rowcount
