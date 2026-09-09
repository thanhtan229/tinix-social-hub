from __future__ import annotations

import json
import uuid
from typing import Any

from app.db.database import Database, row_to_dict, utc_now


class ContentInUseError(ValueError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str | None, default: Any) -> Any:
    return json.loads(value) if value else default


class BrandProfileRepository:
    FIELDS = (
        "name", "description", "products_services", "target_audience", "tone", "pronouns",
        "website", "contact_info", "hashtag_rules",
    )

    def __init__(self, database: Database) -> None:
        self.db = database

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        profile_id, now = str(uuid.uuid4()), utc_now()
        with self.db.connection() as connection:
            connection.execute(
                "INSERT INTO brand_profiles(id,name,description,products_services,target_audience,tone,pronouns,preferred_keywords_json,forbidden_keywords_json,sample_ctas_json,website,contact_info,hashtag_rules,good_examples_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    profile_id, data["name"].strip(), data.get("description"), data.get("products_services"),
                    data.get("target_audience"), data.get("tone"), data.get("pronouns"),
                    _json(data.get("preferred_keywords", [])), _json(data.get("forbidden_keywords", [])),
                    _json(data.get("sample_ctas", [])), data.get("website"), data.get("contact_info"),
                    data.get("hashtag_rules"), _json(data.get("good_examples", [])), now, now,
                ),
            )
        return self.get(profile_id)

    def get(self, profile_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM brand_profiles WHERE id=?", (profile_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        for field in ("preferred_keywords", "forbidden_keywords", "sample_ctas", "good_examples"):
            result[field] = _loads(result.pop(f"{field}_json"), [])
        return result

    def list(self) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            ids = [row[0] for row in connection.execute("SELECT id FROM brand_profiles ORDER BY name")]
        return [self.get(profile_id) for profile_id in ids]

    def update(self, profile_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        if not self.get(profile_id):
            return None
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE brand_profiles SET name=?,description=?,products_services=?,target_audience=?,tone=?,pronouns=?,preferred_keywords_json=?,forbidden_keywords_json=?,sample_ctas_json=?,website=?,contact_info=?,hashtag_rules=?,good_examples_json=?,updated_at=? WHERE id=?",
                (
                    data["name"].strip(), data.get("description"), data.get("products_services"),
                    data.get("target_audience"), data.get("tone"), data.get("pronouns"),
                    _json(data.get("preferred_keywords", [])), _json(data.get("forbidden_keywords", [])),
                    _json(data.get("sample_ctas", [])), data.get("website"), data.get("contact_info"),
                    data.get("hashtag_rules"), _json(data.get("good_examples", [])), utc_now(), profile_id,
                ),
            )
        return self.get(profile_id)

    def delete(self, profile_id: str) -> bool:
        with self.db.connection() as connection:
            cursor = connection.execute("DELETE FROM brand_profiles WHERE id=?", (profile_id,))
            return cursor.rowcount > 0



class ContentRepository:
    def __init__(self, database: Database) -> None:
        self.db = database

    @staticmethod
    def _content_from_row(row: Any) -> dict[str, Any]:
        result = dict(row)
        result["hashtags"] = _loads(result.pop("hashtags_json"), [])
        return result

    def _enrich_content_items(self, connection: Any, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not items:
            return items
        cids = [item["id"] for item in items]
        placeholders = ",".join("?" * len(cids))

        media_rows = connection.execute(
            f"SELECT * FROM content_media WHERE content_id IN ({placeholders}) ORDER BY sort_order, created_at",
            cids,
        ).fetchall()
        media_by_cid: dict[str, list[dict[str, Any]]] = {cid: [] for cid in cids}
        for m in media_rows:
            media_by_cid[m["content_id"]].append(dict(m))

        variant_rows = connection.execute(
            f"SELECT * FROM platform_content_variants WHERE content_id IN ({placeholders}) ORDER BY platform",
            cids,
        ).fetchall()
        variants_by_cid: dict[str, dict[str, Any]] = {cid: {} for cid in cids}
        for v in variant_rows:
            v_dict = dict(v)
            v_dict["hashtags"] = _loads(v_dict.pop("hashtags_json"), [])
            variants_by_cid[v["content_id"]][v_dict["platform"]] = v_dict

        release_rows = connection.execute(
            f"""
            SELECT r.id, r.content_id, r.platform, r.status, r.scheduled_at, r.published_at,
                   r.external_url, r.target_id, t.name as target_name, j.error, j.failure_code
            FROM publication_releases r
            LEFT JOIN publishing_targets t ON t.id = r.target_id
            LEFT JOIN jobs j ON j.id = r.job_id
            WHERE r.content_id IN ({placeholders})
            ORDER BY COALESCE(r.scheduled_at, r.created_at) DESC
            """,
            cids,
        ).fetchall()
        releases_by_cid: dict[str, list[dict[str, Any]]] = {cid: [] for cid in cids}
        for r in release_rows:
            releases_by_cid[r["content_id"]].append(dict(r))

        for item in items:
            cid = item["id"]
            item["media"] = media_by_cid.get(cid, [])
            item["platform_variants"] = variants_by_cid.get(cid, {})
            releases = releases_by_cid.get(cid, [])
            item["releases"] = releases

            platforms = set(item["platform_variants"].keys())
            for r in releases:
                if r.get("platform"):
                    platforms.add(r["platform"])
            item["platforms"] = sorted(list(platforms))

            # Determine publishing status
            succeeded_rels = [r for r in releases if r["status"] == "succeeded"]
            scheduled_rels = [r for r in releases if r["status"] in ("scheduled", "queued")]
            running_rels = [r for r in releases if r["status"] in ("running", "opening_browser", "uploading", "publishing", "verifying")]
            failed_rels = [r for r in releases if r["status"] in ("permanent_failure", "failed")]

            if succeeded_rels:
                item["publishing_status"] = "published"
            elif running_rels:
                item["publishing_status"] = "publishing"
            elif scheduled_rels:
                item["publishing_status"] = "scheduled"
            elif failed_rels:
                item["publishing_status"] = "failed"
            else:
                item["publishing_status"] = "draft"

            item["external_url"] = None
            item["external_urls"] = []
            for r in succeeded_rels:
                if r.get("external_url"):
                    if not item["external_url"]:
                        item["external_url"] = r["external_url"]
                    item["external_urls"].append({
                        "platform": r["platform"],
                        "url": r["external_url"],
                        "target_name": r.get("target_name"),
                        "published_at": r.get("published_at"),
                    })

            if scheduled_rels:
                dates = [r["scheduled_at"] for r in scheduled_rels if r.get("scheduled_at")]
                item["scheduled_at"] = min(dates) if dates else None
            else:
                item["scheduled_at"] = None

            if succeeded_rels:
                dates = [r["published_at"] for r in succeeded_rels if r.get("published_at")]
                item["published_at"] = max(dates) if dates else None
            else:
                item["published_at"] = None

            item["last_error"] = failed_rels[0].get("error") if failed_rels else None

        return items

    def get(self, content_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone()
            if not row:
                return None
            result = self._content_from_row(row)
            enriched = self._enrich_content_items(connection, [result])
            item = enriched[0]
            approval = connection.execute(
                "SELECT * FROM content_approvals WHERE content_id=? ORDER BY requested_at DESC LIMIT 1", (content_id,)
            ).fetchone()
            item["latest_approval"] = dict(approval) if approval else None
            return item

    def list(
        self,
        limit: int = 100,
        offset: int = 0,
        search: str | None = None,
        status: str | None = None,
        platform: str | None = None,
        post_status: str | None = None,
        media_type: str | None = None,
        sort_by: str | None = "newest",
    ) -> list[dict[str, Any]]:
        clauses, params = [], []
        if search:
            clauses.append("(title LIKE ? OR caption LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        if status:
            clauses.append("approval_status=?")
            params.append(status)
        if platform:
            clauses.append(
                "(id IN (SELECT content_id FROM platform_content_variants WHERE platform = ?) "
                "OR id IN (SELECT content_id FROM publication_releases WHERE platform = ?))"
            )
            params.extend([platform.lower(), platform.lower()])
        if media_type:
            if media_type == "image":
                clauses.append("id IN (SELECT content_id FROM content_media WHERE media_type = 'image')")
            elif media_type == "video":
                clauses.append("id IN (SELECT content_id FROM content_media WHERE media_type = 'video')")
            elif media_type in ("text", "none"):
                clauses.append("id NOT IN (SELECT content_id FROM content_media)")
        if post_status:
            if post_status == "published":
                clauses.append("id IN (SELECT content_id FROM publication_releases WHERE status = 'succeeded')")
            elif post_status == "scheduled":
                clauses.append(
                    "id IN (SELECT content_id FROM publication_releases WHERE status IN ('scheduled', 'queued')) "
                    "AND id NOT IN (SELECT content_id FROM publication_releases WHERE status = 'succeeded')"
                )
            elif post_status == "failed":
                clauses.append(
                    "id IN (SELECT content_id FROM publication_releases WHERE status IN ('permanent_failure', 'failed')) "
                    "AND id NOT IN (SELECT content_id FROM publication_releases WHERE status = 'succeeded')"
                )
            elif post_status == "draft":
                clauses.append(
                    "id NOT IN (SELECT content_id FROM publication_releases WHERE status IN ('succeeded', 'scheduled', 'queued', 'running', 'publishing'))"
                )

        order_clause = "ORDER BY updated_at DESC"
        if sort_by == "oldest":
            order_clause = "ORDER BY created_at ASC"
        elif sort_by == "title":
            order_clause = "ORDER BY title ASC"
        elif sort_by == "scheduled":
            order_clause = "ORDER BY (SELECT MIN(scheduled_at) FROM publication_releases WHERE publication_releases.content_id = content_items.id) DESC"

        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.extend([limit, offset])
        with self.db.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM content_items{where} {order_clause} LIMIT ? OFFSET ?", params
            ).fetchall()
            items = [self._content_from_row(row) for row in rows]
            return self._enrich_content_items(connection, items)

    @staticmethod
    def _snapshot(connection: Any, content_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone()
        content = dict(row)
        content["hashtags"] = _loads(content.pop("hashtags_json"), [])
        variants = []
        for raw in connection.execute("SELECT * FROM platform_content_variants WHERE content_id=?", (content_id,)):
            item = dict(raw)
            item["hashtags"] = _loads(item.pop("hashtags_json"), [])
            variants.append(item)
        return {"content": content, "variants": variants}

    @staticmethod
    def _insert_revision(connection: Any, content_id: str, number: int, source: str, note: str | None = None) -> str:
        revision_id = str(uuid.uuid4())
        snapshot = ContentRepository._snapshot(connection, content_id)
        connection.execute(
            "INSERT INTO content_revisions(id,content_id,revision_number,snapshot_json,source,note,created_at) VALUES(?,?,?,?,?,?,?)",
            (revision_id, content_id, number, _json(snapshot), source, note, utc_now()),
        )
        return revision_id

    @staticmethod
    def _upsert_variants(connection: Any, content_id: str, variants: dict[str, dict[str, Any]]) -> None:
        now = utc_now()
        for platform, value in variants.items():
            existing = connection.execute(
                "SELECT id FROM platform_content_variants WHERE content_id=? AND platform=?", (content_id, platform)
            ).fetchone()
            fields = (
                value.get("caption", ""), _json(value.get("hashtags", [])), value.get("cta"),
                value.get("title"), value.get("pinned_comment"), value.get("video_hook"), value.get("video_script"),
            )
            if existing:
                connection.execute(
                    "UPDATE platform_content_variants SET caption=?,hashtags_json=?,cta=?,title=?,pinned_comment=?,video_hook=?,video_script=?,updated_at=? WHERE id=?",
                    (*fields, now, existing["id"]),
                )
            else:
                connection.execute(
                    "INSERT INTO platform_content_variants(id,content_id,platform,caption,hashtags_json,cta,title,pinned_comment,video_hook,video_script,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), content_id, platform, *fields, now, now),
                )

    def create(self, data: dict[str, Any], source: str = "user") -> dict[str, Any]:
        content_id, now = str(uuid.uuid4()), utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT INTO content_items(id,brand_profile_id,brief_id,title,topic,summary,caption,hashtags_json,cta,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        content_id, data.get("brand_profile_id"), data.get("brief_id"), data["title"].strip(),
                        data.get("topic"), data.get("summary"), data.get("caption", ""),
                        _json(data.get("hashtags", [])), data.get("cta"), now, now,
                    ),
                )
                self._upsert_variants(connection, content_id, data.get("platform_variants", {}))
                self._insert_revision(connection, content_id, 1, source, "Initial revision")
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get(content_id)

    def update(self, content_id: str, data: dict[str, Any], source: str = "user") -> dict[str, Any] | None:
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                current = connection.execute("SELECT current_revision FROM content_items WHERE id=?", (content_id,)).fetchone()
                if not current:
                    connection.execute("ROLLBACK")
                    return None
                revision = current["current_revision"] + 1
                connection.execute(
                    "UPDATE content_items SET brand_profile_id=?,title=?,topic=?,summary=?,caption=?,hashtags_json=?,cta=?,approval_status='draft',current_revision=?,updated_at=? WHERE id=?",
                    (
                        data.get("brand_profile_id"), data["title"].strip(), data.get("topic"), data.get("summary"),
                        data.get("caption", ""), _json(data.get("hashtags", [])), data.get("cta"), revision, utc_now(), content_id,
                    ),
                )
                self._upsert_variants(connection, content_id, data.get("platform_variants", {}))
                self._insert_revision(connection, content_id, revision, source)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get(content_id)

    def duplicate(self, content_id: str) -> dict[str, Any] | None:
        content = self.get(content_id)
        if not content:
            return None
        content_copy = dict(content)
        content_copy["title"] = f"{content['title']} (bản sao)"
        content_copy["platform_variants"] = {
            platform: variant for platform, variant in content.get("platform_variants", {}).items()
        }
        duplicate = self.create(content_copy, source="duplicate")
        if duplicate and content.get("media"):
            with self.db.connection() as connection:
                for item in content["media"]:
                    media_id = str(uuid.uuid4())
                    connection.execute(
                        "INSERT INTO content_media(id,content_id,media_type,relative_path,thumbnail_relative_path,original_name,mime_type,size_bytes,sha256,sort_order,asset_id,alt_text,thumbnail_timestamp,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            media_id, duplicate["id"], item["media_type"], item["relative_path"],
                            item.get("thumbnail_relative_path"), item["original_name"], item["mime_type"],
                            item["size_bytes"], item["sha256"], item.get("sort_order", 0),
                            item.get("asset_id"), item.get("alt_text"), item.get("thumbnail_timestamp"),
                            utc_now(),
                        ),
                    )
            return self.get(duplicate["id"])
        return duplicate

    def revisions(self, content_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT id,content_id,revision_number,source,note,created_at FROM content_revisions WHERE content_id=? ORDER BY revision_number DESC",
                (content_id,),
            )]

    def restore_revision(self, content_id: str, revision_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            row = connection.execute(
                "SELECT snapshot_json FROM content_revisions WHERE id=? AND content_id=?", (revision_id, content_id)
            ).fetchone()
        if not row:
            return None
        snapshot = _loads(row[0], {})
        content = snapshot["content"]
        content["platform_variants"] = {item["platform"]: item for item in snapshot.get("variants", [])}
        return self.update(content_id, content, source="restore")

    def request_approval(self, content_id: str) -> dict[str, Any] | None:
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                revision = connection.execute(
                    "SELECT id FROM content_revisions WHERE content_id=? ORDER BY revision_number DESC LIMIT 1", (content_id,)
                ).fetchone()
                if not revision:
                    connection.execute("ROLLBACK")
                    return None
                approval_id = str(uuid.uuid4())
                connection.execute(
                    "INSERT INTO content_approvals(id,content_id,revision_id,status,requested_at) VALUES(?,?,?,?,?)",
                    (approval_id, content_id, revision["id"], "pending", now),
                )
                connection.execute("UPDATE content_items SET approval_status='pending_approval',updated_at=? WHERE id=?", (now, content_id))
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get_approval(approval_id)

    def decide_approval(self, approval_id: str, approved: bool, note: str | None = None) -> dict[str, Any] | None:
        status, content_status, now = ("approved", "approved", utc_now()) if approved else ("rejected", "draft", utc_now())
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute("SELECT content_id,status FROM content_approvals WHERE id=?", (approval_id,)).fetchone()
                if not row or row["status"] != "pending":
                    connection.execute("ROLLBACK")
                    return None
                connection.execute(
                    "UPDATE content_approvals SET status=?,note=?,decided_at=? WHERE id=?", (status, note, now, approval_id)
                )
                connection.execute(
                    "UPDATE content_items SET approval_status=?,updated_at=? WHERE id=?", (content_status, now, row["content_id"])
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get_approval(approval_id)

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            return row_to_dict(connection.execute("SELECT * FROM content_approvals WHERE id=?", (approval_id,)).fetchone())

    def current_approval(self, content_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            return row_to_dict(connection.execute(
                "SELECT a.* FROM content_approvals a JOIN content_revisions r ON r.id=a.revision_id "
                "JOIN content_items c ON c.id=a.content_id "
                "WHERE a.content_id=? AND a.status='approved' AND r.revision_number=c.current_revision "
                "ORDER BY a.decided_at DESC LIMIT 1",
                (content_id,),
            ).fetchone())

    def add_media(self, content_id: str, media: dict[str, Any]) -> dict[str, Any]:
        media_id = str(uuid.uuid4())
        with self.db.connection() as connection:
            connection.execute(
                "INSERT INTO content_media(id,content_id,media_type,relative_path,thumbnail_relative_path,original_name,mime_type,size_bytes,sha256,sort_order,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    media_id, content_id, media["media_type"], media["relative_path"], media.get("thumbnail_relative_path"),
                    media["original_name"], media["mime_type"], media["size_bytes"], media["sha256"], media.get("sort_order", 0), utc_now(),
                ),
            )
        return self.get(content_id)

    def delete(self, content_id: str, force: bool = False) -> list[str] | None:
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                exists = connection.execute("SELECT 1 FROM content_items WHERE id=?", (content_id,)).fetchone()
                if not exists:
                    connection.execute("ROLLBACK")
                    return None
                jobs = connection.execute("SELECT COUNT(*) FROM jobs WHERE content_id=?", (content_id,)).fetchone()[0]
                if jobs:
                    if not force:
                        raise ContentInUseError("Content đang có lịch sử hoặc lịch đăng; không thể xóa record.")
                    connection.execute("UPDATE jobs SET content_id=NULL WHERE content_id=?", (content_id,))
                    connection.execute("UPDATE publication_plans SET content_id=NULL WHERE content_id=?", (content_id,))
                    connection.execute("UPDATE publication_releases SET content_id=NULL WHERE content_id=?", (content_id,))
                paths = []
                for row in connection.execute(
                    "SELECT relative_path,thumbnail_relative_path FROM content_media WHERE content_id=? AND asset_id IS NULL", (content_id,)
                ):
                    paths.extend(path for path in row if path)
                connection.execute("DELETE FROM content_items WHERE id=?", (content_id,))
                connection.execute("COMMIT")
                return paths
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def bulk_delete(self, content_ids: list[str], force: bool = True) -> dict[str, Any]:
        deleted_count = 0
        failed_count = 0
        deleted_ids = []
        all_paths = []
        for cid in content_ids:
            try:
                paths = self.delete(cid, force=force)
                if paths is not None:
                    deleted_count += 1
                    deleted_ids.append(cid)
                    all_paths.extend(paths)
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1
        return {
            "deleted_count": deleted_count,
            "failed_count": failed_count,
            "deleted_ids": deleted_ids,
            "retained_paths": all_paths,
        }


class AIGenerationRepository:
    def __init__(self, database: Database) -> None:
        self.db = database

    def create_brief(self, title: str, text: str, platforms: list[str], brand_id: str | None) -> str:
        brief_id, now = str(uuid.uuid4()), utc_now()
        with self.db.connection() as connection:
            connection.execute(
                "INSERT INTO content_briefs(id,brand_profile_id,title,brief_text,platforms_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (brief_id, brand_id, title[:200], text, _json(platforms), now, now),
            )
        return brief_id

    def start(self, provider: str, model: str, operation: str, request: dict[str, Any], brief_id: str | None, brand_id: str | None) -> str:
        generation_id = str(uuid.uuid4())
        with self.db.connection() as connection:
            connection.execute(
                "INSERT INTO ai_generations(id,brief_id,brand_profile_id,provider,model,operation,request_json,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (generation_id, brief_id, brand_id, provider, model, operation, _json(request), "running", utc_now()),
            )
        return generation_id

    def finish(self, generation_id: str, response: dict[str, Any], usage: dict[str, int | None], latency_ms: int) -> None:
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "UPDATE ai_generations SET response_json=?,status='succeeded',latency_ms=?,finished_at=? WHERE id=?",
                    (_json(response), latency_ms, now, generation_id),
                )
                connection.execute(
                    "INSERT INTO ai_usage(id,generation_id,prompt_tokens,completion_tokens,total_tokens,created_at) VALUES(?,?,?,?,?,?)",
                    (
                        str(uuid.uuid4()), generation_id, usage.get("prompt_tokens"), usage.get("completion_tokens"),
                        usage.get("total_tokens"), now,
                    ),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def fail(self, generation_id: str, code: str, message: str, latency_ms: int) -> None:
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE ai_generations SET status='failed',error_code=?,error_message=?,latency_ms=?,finished_at=? WHERE id=?",
                (code, message[:1000], latency_ms, utc_now(), generation_id),
            )

    def get(self, generation_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM ai_generations WHERE id=?", (generation_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["request"] = _loads(item.pop("request_json"), {})
        item["response"] = _loads(item.pop("response_json"), {})
        return item

    def update_image_job(
        self, generation_id: str, *, status: str, response: dict[str, Any] | None = None,
        error_code: str | None = None, error_message: str | None = None, finished: bool = False,
    ) -> None:
        fields = ["status=?"]
        values: list[Any] = [status]
        if response is not None:
            fields.append("response_json=?")
            values.append(_json(response))
        if error_code is not None:
            fields.append("error_code=?")
            values.append(error_code)
        if error_message is not None:
            fields.append("error_message=?")
            values.append(error_message[:1000])
        if finished:
            fields.append("finished_at=?")
            values.append(utc_now())
        values.append(generation_id)
        with self.db.connection() as connection:
            connection.execute(f"UPDATE ai_generations SET {','.join(fields)} WHERE id=?", values)
