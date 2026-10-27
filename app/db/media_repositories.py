from __future__ import annotations

import uuid
from typing import Any

from app.db.database import Database, row_to_dict, utc_now


class MediaAssetInUseError(ValueError):
    pass


class MediaAssetRepository:
    def __init__(self, database: Database) -> None:
        self.db = database

    def get(self, asset_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM media_assets WHERE id=?", (asset_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["tags"] = [item[0] for item in connection.execute(
                "SELECT tag FROM media_asset_tags WHERE asset_id=? ORDER BY tag", (asset_id,)
            )]
            result["reference_count"] = connection.execute(
                "SELECT (SELECT COUNT(*) FROM content_media WHERE asset_id=?) + "
                "(SELECT COUNT(*) FROM content_media_targets WHERE asset_id=?)", (asset_id, asset_id)
            ).fetchone()[0]
            return result

    def get_by_sha256(self, sha256: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            row = connection.execute("SELECT id FROM media_assets WHERE sha256=?", (sha256,)).fetchone()
        return self.get(row[0]) if row else None

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_by_sha256(data["sha256"])
        if existing:
            return existing
        asset_id, now = str(uuid.uuid4()), utc_now()
        with self.db.connection() as connection:
            connection.execute(
                "INSERT INTO media_assets(id,media_type,relative_path,thumbnail_relative_path,original_name,mime_type,size_bytes,sha256,width,height,duration_seconds,alt_text,thumbnail_timestamp,source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (asset_id, data["media_type"], data["relative_path"], data.get("thumbnail_relative_path"),
                 data["original_name"], data["mime_type"], data["size_bytes"], data["sha256"],
                 data.get("width"), data.get("height"), data.get("duration_seconds"), data.get("alt_text"),
                 data.get("thumbnail_timestamp"), data.get("source", "upload"), now, now),
            )
        return self.get(asset_id)

    def list(
        self, search: str | None = None, media_type: str | None = None, tag: str | None = None,
        orphan_only: bool = False, limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses, params = [], []
        if search:
            clauses.append("(a.original_name LIKE ? OR a.alt_text LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        if media_type:
            clauses.append("a.media_type=?"); params.append(media_type)
        if tag:
            clauses.append("EXISTS(SELECT 1 FROM media_asset_tags t WHERE t.asset_id=a.id AND t.tag=?)"); params.append(tag.lower())
        if orphan_only:
            clauses.append("NOT EXISTS(SELECT 1 FROM content_media cm WHERE cm.asset_id=a.id) "
                           "AND NOT EXISTS(SELECT 1 FROM content_media_targets cm WHERE cm.asset_id=a.id)")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(limit, 500)))
        with self.db.connection() as connection:
            ids = [row[0] for row in connection.execute(
                f"SELECT a.id FROM media_assets a{where} ORDER BY a.created_at DESC LIMIT ?", params
            )]
        return [self.get(asset_id) for asset_id in ids]

    def update(self, asset_id: str, alt_text: str | None, tags: list[str], thumbnail_timestamp: float | None) -> dict[str, Any] | None:
        normalized = sorted({tag.strip().lower() for tag in tags if tag.strip()})
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    "UPDATE media_assets SET alt_text=?,thumbnail_timestamp=?,updated_at=? WHERE id=?",
                    (alt_text, thumbnail_timestamp, now, asset_id),
                )
                if not cursor.rowcount:
                    connection.execute("ROLLBACK"); return None
                connection.execute("DELETE FROM media_asset_tags WHERE asset_id=?", (asset_id,))
                connection.executemany(
                    "INSERT INTO media_asset_tags(asset_id,tag,created_at) VALUES(?,?,?)",
                    [(asset_id, tag[:80], now) for tag in normalized],
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK"); raise
        return self.get(asset_id)

    def attach(self, asset_id: str, content_id: str, sort_order: int = 0, alt_text: str | None = None) -> dict[str, Any]:
        from app.db.content_repositories import ContentRepository

        asset = self.get(asset_id)
        if not asset:
            raise KeyError(asset_id)
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if not connection.execute("SELECT 1 FROM content_items WHERE id=?", (content_id,)).fetchone():
                    raise KeyError(content_id)
                existing_types = {row[0] for row in connection.execute(
                    "SELECT media_type FROM content_media WHERE content_id=?", (content_id,)
                )}
                if (asset["media_type"] == "video" and existing_types) or (asset["media_type"] == "image" and "video" in existing_types):
                    raise ValueError("Không thể trộn video với media khác trong cùng content.")
                existing = connection.execute(
                    "SELECT id FROM content_media WHERE content_id=? AND asset_id=?", (content_id, asset_id)
                ).fetchone()
                if not existing:
                    connection.execute(
                        "INSERT INTO content_media(id,content_id,media_type,relative_path,thumbnail_relative_path,original_name,mime_type,size_bytes,sha256,sort_order,created_at,asset_id,alt_text,thumbnail_timestamp) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (str(uuid.uuid4()), content_id, asset["media_type"], asset["relative_path"],
                         asset["thumbnail_relative_path"], asset["original_name"], asset["mime_type"],
                         asset["size_bytes"], asset["sha256"], sort_order, utc_now(), asset_id,
                         alt_text or asset["alt_text"], asset["thumbnail_timestamp"]),
                    )
                    ContentRepository._record_media_revision(connection, content_id)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get(asset_id)

    def detach(self, asset_id: str, content_id: str) -> bool:
        from app.db.content_repositories import ContentRepository

        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute("DELETE FROM content_media WHERE content_id=? AND asset_id=?", (content_id, asset_id))
                if cursor.rowcount:
                    ContentRepository._record_media_revision(connection, content_id)
                connection.execute("COMMIT")
                return cursor.rowcount > 0
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def set_target_override(
        self, content_id: str, target_id: str, asset_ids: list[str], *,
        alt_texts: dict[str, str] | None = None, inherit: bool = False,
    ) -> dict[str, Any]:
        from app.db.content_repositories import ContentRepository

        unique_ids = list(dict.fromkeys(asset_ids))
        if len(unique_ids) != len(asset_ids) or len(unique_ids) > 10:
            raise ValueError("Media Page phải là asset hợp lệ, không trùng và tối đa 10 tệp.")
        alt_texts = alt_texts or {}
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if not connection.execute("SELECT 1 FROM content_items WHERE id=?", (content_id,)).fetchone():
                    raise KeyError(content_id)
                if not connection.execute("SELECT 1 FROM publishing_targets WHERE id=?", (target_id,)).fetchone():
                    raise KeyError(target_id)
                existing = connection.execute(
                    "SELECT 1 FROM content_target_media_overrides WHERE content_id=? AND target_id=?",
                    (content_id, target_id),
                ).fetchone()
                changed = False
                if inherit:
                    if existing:
                        connection.execute(
                            "DELETE FROM content_target_media_overrides WHERE content_id=? AND target_id=?",
                            (content_id, target_id),
                        )
                        changed = True
                else:
                    current_media = connection.execute(
                        "SELECT asset_id,sort_order,alt_text FROM content_media_targets WHERE content_id=? AND target_id=? ORDER BY sort_order,created_at",
                        (content_id, target_id),
                    ).fetchall() if existing else []
                    desired_media = [(asset_id, index, alt_texts.get(asset_id)) for index, asset_id in enumerate(unique_ids)]
                    unchanged = existing and [tuple(row) for row in current_media] == desired_media
                    if not unchanged:
                        if existing:
                            connection.execute(
                                "DELETE FROM content_target_media_overrides WHERE content_id=? AND target_id=?",
                                (content_id, target_id),
                            )
                        connection.execute(
                            "INSERT INTO content_target_media_overrides(content_id,target_id,created_at) VALUES(?,?,?)",
                            (content_id, target_id, now),
                        )
                        for sort_order, asset_id in enumerate(unique_ids):
                            asset = connection.execute("SELECT id FROM media_assets WHERE id=?", (asset_id,)).fetchone()
                            if not asset:
                                raise KeyError(asset_id)
                            connection.execute(
                                "INSERT INTO content_media_targets(content_id,target_id,asset_id,sort_order,alt_text,created_at) VALUES(?,?,?,?,?,?)",
                                (content_id, target_id, asset_id, sort_order, alt_texts.get(asset_id), now),
                            )
                        changed = True
                if changed:
                    ContentRepository._record_media_revision(connection, content_id)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        content = ContentRepository(self.db).get(content_id)
        return content

    def delete(self, asset_id: str) -> list[str]:
        asset = self.get(asset_id)
        if not asset:
            raise KeyError(asset_id)
        with self.db.connection() as connection:
            references = connection.execute(
                "SELECT (SELECT COUNT(*) FROM content_media WHERE asset_id=?) + "
                "(SELECT COUNT(*) FROM content_media_targets WHERE asset_id=?)", (asset_id, asset_id)
            ).fetchone()[0]
            history = connection.execute(
                "SELECT COUNT(*) FROM publication_releases WHERE media_snapshot_json LIKE ?", (f'%"sha256":"{asset["sha256"]}"%',)
            ).fetchone()[0]
            revisions = connection.execute(
                "SELECT COUNT(*) FROM content_revisions WHERE snapshot_json LIKE ?", (f'%"asset_id":"{asset_id}"%',)
            ).fetchone()[0]
            if references or history or revisions:
                raise MediaAssetInUseError(f"Asset đang có {references} content reference, {history} release snapshot và {revisions} revision snapshot.")
            connection.execute("DELETE FROM media_assets WHERE id=?", (asset_id,))
        return [path for path in (asset["relative_path"], asset["thumbnail_relative_path"]) if path]
