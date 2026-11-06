from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db.database import Database, utc_now


class AnalyticsFetchInProgress(ValueError):
    """A recent fetch for this identity and source already owns the refresh slot."""


class AnalyticsRepository:
    def __init__(self, database: Database) -> None:
        self.db = database

    def start_run(self, release_id: str, source: str) -> str:
        run_id = str(uuid.uuid4())
        stale_before = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute("SELECT 1 FROM publication_releases WHERE id=?", (release_id,)).fetchone():
                connection.execute("ROLLBACK")
                raise KeyError(release_id)
            try:
                active = connection.execute(
                    "SELECT 1 FROM analytics_fetch_runs WHERE release_id=? AND source=? AND status='running' AND started_at>=? LIMIT 1",
                    (release_id, source, stale_before),
                ).fetchone()
                if active:
                    raise AnalyticsFetchInProgress("Đang có lượt cập nhật metrics cho release này; hãy chờ lượt đó hoàn tất.")
                connection.execute(
                    "INSERT INTO analytics_fetch_runs(id,release_id,status,source,started_at) VALUES(?,?,?,?,?)",
                    (run_id, release_id, "running", source, utc_now()),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return run_id

    def finish_run(self, run_id: str, status: str, count: int, message: str | None = None) -> None:
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE analytics_fetch_runs SET status=?,metrics_count=?,message=?,finished_at=? WHERE id=?",
                (status, count, message, utc_now(), run_id),
            )

    def upsert(
        self, release_id: str, values: dict[str, float], *, metric_date: str,
        timezone_name: str, source: str, fetched_at: str | None = None,
        metric_kind: str = "snapshot", unit: str = "count",
        period_start: str | None = None, period_end: str | None = None,
        provider_metric_names: dict[str, str] | None = None,
        provider_metric_units: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        now = fetched_at or utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if not connection.execute("SELECT 1 FROM publication_releases WHERE id=?", (release_id,)).fetchone():
                    raise KeyError(release_id)
                for key, value in values.items():
                    connection.execute(
                        "INSERT INTO release_metrics(id,release_id,metric_key,metric_date,timezone,value,source,fetched_at,created_at,metric_kind,unit,period_start,period_end,provider_metric_name) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(release_id,metric_key,metric_date,source) DO UPDATE SET "
                        "timezone=excluded.timezone,value=excluded.value,fetched_at=excluded.fetched_at,"
                        "metric_kind=excluded.metric_kind,unit=excluded.unit,period_start=excluded.period_start,period_end=excluded.period_end,"
                        "provider_metric_name=COALESCE(excluded.provider_metric_name,release_metrics.provider_metric_name)",
                        (str(uuid.uuid4()), release_id, key, metric_date, timezone_name, float(value), source, now, now,
                         metric_kind, (provider_metric_units or {}).get(key, unit), period_start, period_end,
                         (provider_metric_names or {}).get(key)),
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK"); raise
        return self.for_release(release_id)

    def for_release(self, release_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM release_metrics WHERE release_id=? ORDER BY metric_date DESC,metric_key", (release_id,)
            )]

    def runs(self, release_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM analytics_fetch_runs WHERE release_id=? ORDER BY started_at DESC LIMIT ?", (release_id, limit)
            )]

    def summary(
        self, days: int = 30, platform: str | None = None,
        account_id: str | None = None, target_id: str | None = None,
    ) -> dict[str, Any]:
        end = datetime.now(timezone.utc).date() + timedelta(days=1)
        start = end - timedelta(days=days)
        previous = start - timedelta(days=days)
        filter_clause = ""
        params: list[Any] = [previous.isoformat(), end.isoformat()]
        filters = []
        for column, value in (("r.platform", platform), ("r.account_id", account_id), ("r.target_id", target_id)):
            if value:
                filters.append(f" AND {column}=?")
                params.append(value)
        filter_clause = "".join(filters)
        with self.db.connection() as connection:
            rows = [dict(row) for row in connection.execute(
                "SELECT m.release_id,m.metric_key,m.metric_date,m.value,m.source,m.metric_kind,m.unit,m.period_start,m.period_end,m.fetched_at,r.platform FROM release_metrics m "
                "JOIN publication_releases r ON r.id=m.release_id WHERE m.metric_date>=? AND m.metric_date<?" + filter_clause,
                params,
            )]
        current, prior = {}, {}
        bucket_rows: dict[str, list[dict[str, Any]]] = {"current": [], "previous": []}
        for row in rows:
            bucket_name = "current" if row["metric_date"] >= start.isoformat() else "previous"
            bucket_rows[bucket_name].append(row)
        for bucket_name, bucket in (("current", current), ("previous", prior)):
            grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for row in bucket_rows[bucket_name]:
                grouped.setdefault((row["release_id"], row["metric_key"]), []).append(row)
            for (_release_id, metric_key), samples in grouped.items():
                interval_samples = [item for item in samples if item["metric_kind"] == "interval"]
                if interval_samples:
                    by_period: dict[tuple[str, str], list[dict[str, Any]]] = {}
                    for item in interval_samples:
                        period = (item.get("period_start") or item["metric_date"],
                                  item.get("period_end") or item["metric_date"])
                        by_period.setdefault(period, []).append(item)
                    chosen = [max(period, key=lambda item: (
                        int(str(item["source"]).startswith("api_")), item["source"], item["fetched_at"],
                    )) for period in by_period.values()]
                else:
                    chosen = [max(
                        samples,
                        key=lambda item: (
                            item["metric_date"],
                            int(str(item["source"]).startswith("api_")),
                            item["source"],
                        ),
                    )]
                bucket[metric_key] = bucket.get(metric_key, 0) + sum(item["value"] for item in chosen)
        keys = sorted(set(current) | set(prior))
        comparison = {key: {"current": current.get(key, 0), "previous": prior.get(key, 0)} for key in keys}
        return {
            "supported": bool(rows), "days": days, "platform": platform,
            "account_id": account_id, "target_id": target_id,
            "range": {"start": start.isoformat(), "end": end.isoformat()},
            "metrics": comparison, "sources": sorted({row["source"] for row in rows}),
        }

    def start_channel_run(self, target_id: str, source: str) -> str:
        run_id = str(uuid.uuid4())
        stale_before = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute("SELECT 1 FROM publishing_targets WHERE id=?", (target_id,)).fetchone():
                connection.execute("ROLLBACK")
                raise KeyError(target_id)
            try:
                active = connection.execute(
                    "SELECT 1 FROM channel_analytics_fetch_runs WHERE target_id=? AND source=? AND status='running' AND started_at>=? LIMIT 1",
                    (target_id, source, stale_before),
                ).fetchone()
                if active:
                    raise AnalyticsFetchInProgress("Đang có lượt cập nhật metrics cho target này; hãy chờ lượt đó hoàn tất.")
                connection.execute(
                    "INSERT INTO channel_analytics_fetch_runs(id,target_id,status,source,started_at) VALUES(?,?,?,?,?)",
                    (run_id, target_id, "running", source, utc_now()),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return run_id

    def finish_channel_run(self, run_id: str, status: str, count: int, message: str | None = None) -> None:
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE channel_analytics_fetch_runs SET status=?,metrics_count=?,message=?,finished_at=? WHERE id=?",
                (status, count, message, utc_now(), run_id),
            )

    def upsert_channel(
        self, target_id: str, values: dict[str, float], *, metric_date: str,
        timezone_name: str, source: str, fetched_at: str | None = None,
        metric_kind: str = "snapshot", unit: str = "count",
        period_start: str | None = None, period_end: str | None = None,
        provider_metric_names: dict[str, str] | None = None,
        provider_metric_units: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        now = fetched_at or utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if not connection.execute("SELECT 1 FROM publishing_targets WHERE id=?", (target_id,)).fetchone():
                    raise KeyError(target_id)
                for key, value in values.items():
                    connection.execute(
                        "INSERT INTO channel_metrics(id,target_id,metric_key,metric_date,timezone,value,source,metric_kind,unit,period_start,period_end,fetched_at,created_at,provider_metric_name) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(target_id,metric_key,metric_date,source) DO UPDATE SET "
                        "timezone=excluded.timezone,value=excluded.value,metric_kind=excluded.metric_kind,unit=excluded.unit,"
                        "period_start=excluded.period_start,period_end=excluded.period_end,fetched_at=excluded.fetched_at,"
                        "provider_metric_name=COALESCE(excluded.provider_metric_name,channel_metrics.provider_metric_name)",
                        (str(uuid.uuid4()), target_id, key, metric_date, timezone_name, float(value), source,
                         metric_kind, (provider_metric_units or {}).get(key, unit), period_start, period_end,
                         now, now, (provider_metric_names or {}).get(key)),
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.channel_metrics(target_id)

    def channel_metrics(
        self, target_id: str | None = None, platform: str | None = None,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if target_id:
            clauses.append("m.target_id=?")
            params.append(target_id)
        if platform:
            clauses.append("t.platform=?")
            params.append(platform)
        if account_id:
            clauses.append("t.account_id=?")
            params.append(account_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.db.connection() as connection:
            rows = [dict(row) for row in connection.execute(
                "SELECT m.*,t.account_id,t.platform,t.name AS target_name FROM channel_metrics m "
                "JOIN publishing_targets t ON t.id=m.target_id" + where +
                " ORDER BY m.metric_date DESC,m.fetched_at DESC,m.metric_key",
                params,
            )]
        latest: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for row in rows:
            key = (row["target_id"], row["metric_key"])
            previous = latest.get(key)
            rank = (row["metric_date"], int(str(row["source"]).startswith("api_")), row["fetched_at"])
            if previous is None or rank > (
                previous["metric_date"], int(str(previous["source"]).startswith("api_")), previous["fetched_at"],
            ):
                latest[key] = row
        return sorted(latest.values(), key=lambda item: (item["target_name"].casefold(), item["metric_key"]))

    def channel_metric_history(
        self, target_id: str | None = None, days: int = 90, source: str | None = None,
        platform: str | None = None, account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        start = (datetime.now(timezone.utc).date() - timedelta(days=max(1, min(days, 365)))).isoformat()
        clauses, params = ["m.metric_date>=?"], [start]
        for column, value in (("m.target_id", target_id), ("m.source", source),
                              ("t.platform", platform), ("t.account_id", account_id)):
            if value:
                clauses.append(f"{column}=?")
                params.append(value)
        with self.db.connection() as connection:
            rows = [dict(row) for row in connection.execute(
                "SELECT m.*,t.account_id,t.platform,t.name AS target_name FROM channel_metrics m "
                "JOIN publishing_targets t ON t.id=m.target_id WHERE " + " AND ".join(clauses) +
                " ORDER BY m.metric_date,m.metric_key,m.fetched_at",
                params,
            )]
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (row["target_id"], row["metric_date"], row["metric_key"], row["metric_kind"])
            old = latest.get(key)
            rank = (int(str(row["source"]).startswith("api_")), row["fetched_at"])
            if old is None or rank > (int(str(old["source"]).startswith("api_")), old["fetched_at"]):
                latest[key] = row
        return sorted(latest.values(), key=lambda item: (item["metric_date"], item["metric_key"]))

    def channel_summary(
        self, days: int = 30, platform: str | None = None,
        target_id: str | None = None, account_id: str | None = None,
    ) -> dict[str, Any]:
        end = datetime.now(timezone.utc).date() + timedelta(days=1)
        start = end - timedelta(days=days)
        previous = start - timedelta(days=days)
        clauses = ["m.metric_date>=?", "m.metric_date<?"]
        params: list[Any] = [previous.isoformat(), end.isoformat()]
        for column, value in (("t.platform", platform), ("t.id", target_id), ("t.account_id", account_id)):
            if value:
                clauses.append(f"{column}=?")
                params.append(value)
        with self.db.connection() as connection:
            rows = [dict(row) for row in connection.execute(
                "SELECT m.target_id,m.metric_key,m.metric_date,m.value,m.source,m.metric_kind,m.unit,t.platform "
                "FROM channel_metrics m JOIN publishing_targets t ON t.id=m.target_id WHERE " + " AND ".join(clauses),
                params,
            )]
        sums: dict[str, dict[str, float]] = {"current": {}, "previous": {}}
        buckets: dict[str, list[dict[str, Any]]] = {"current": [], "previous": []}
        for row in rows:
            buckets["current" if row["metric_date"] >= start.isoformat() else "previous"].append(row)
        for bucket_name, bucket_rows in buckets.items():
            grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for row in bucket_rows:
                grouped.setdefault((row["target_id"], row["metric_key"]), []).append(row)
            for (_target, metric_key), samples in grouped.items():
                interval = [row for row in samples if row["metric_kind"] == "interval"]
                if interval:
                    by_day: dict[str, list[dict[str, Any]]] = {}
                    for row in interval:
                        by_day.setdefault(row["metric_date"], []).append(row)
                    chosen = [max(day, key=lambda row: (int(str(row["source"]).startswith("api_")), row["source"]))
                              for day in by_day.values()]
                else:
                    chosen = [max(samples, key=lambda row: (
                        row["metric_date"], int(str(row["source"]).startswith("api_")), row["source"],
                    ))]
                sums[bucket_name][metric_key] = sums[bucket_name].get(metric_key, 0) + sum(row["value"] for row in chosen)
        metrics = {
            key: {"current": sums["current"].get(key, 0), "previous": sums["previous"].get(key, 0)}
            for key in sorted(set(sums["current"]) | set(sums["previous"]))
        }
        return {
            "supported": bool(rows), "days": days, "platform": platform,
            "target_id": target_id, "account_id": account_id,
            "range": {"start": start.isoformat(), "end": end.isoformat()}, "metrics": metrics,
            "sources": sorted({row["source"] for row in rows}),
        }

    def channel_runs(self, target_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM channel_analytics_fetch_runs WHERE target_id=? ORDER BY started_at DESC LIMIT ?",
                (target_id, limit),
            )]

    def latest_channel_runs(
        self, target_id: str | None = None, platform: str | None = None,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        for column, value in (("f.target_id", target_id), ("t.platform", platform), ("t.account_id", account_id)):
            if value:
                clauses.append(f"{column}=?")
                parameters.append(value)
        query = (
            "SELECT f.id,f.target_id,f.status,f.source,f.started_at,f.finished_at,"
            "f.metrics_count,f.message FROM channel_analytics_fetch_runs f "
            "JOIN publishing_targets t ON t.id=f.target_id "
        )
        query += f"WHERE {' AND '.join(clauses)} AND " if clauses else "WHERE "
        query += (
            "f.id=(SELECT latest.id FROM channel_analytics_fetch_runs latest "
            "WHERE latest.target_id=f.target_id ORDER BY latest.started_at DESC LIMIT 1) "
            "ORDER BY f.started_at DESC"
        )
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(query, parameters)]

    def connected_meta_target_ids(
        self, target_id: str | None = None, account_id: str | None = None,
    ) -> list[str]:
        clauses = ["b.provider='meta'", "b.status='connected'", "t.platform='facebook'"]
        parameters: list[Any] = []
        if target_id:
            clauses.append("t.id=?")
            parameters.append(target_id)
        if account_id:
            clauses.append("t.account_id=?")
            parameters.append(account_id)
        with self.db.connection() as connection:
            return [row[0] for row in connection.execute(
                "SELECT DISTINCT t.id FROM provider_target_connections b "
                "JOIN publishing_targets t ON t.id=b.target_id "
                "JOIN account_connections c ON c.id=b.connection_id "
                "AND c.provider='meta' AND c.transport='official_api' AND c.status='connected' WHERE "
                + " AND ".join(clauses) + " ORDER BY t.id",
                parameters,
            )]

    def meta_target_connection_statuses(
        self, target_id: str | None = None, account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["b.provider='meta'", "t.platform='facebook'"]
        parameters: list[Any] = []
        if target_id:
            clauses.append("t.id=?")
            parameters.append(target_id)
        if account_id:
            clauses.append("t.account_id=?")
            parameters.append(account_id)
        with self.db.connection() as connection:
            rows = connection.execute(
                "SELECT t.id AS target_id,b.status AS binding_status,c.status AS connection_status "
                "FROM provider_target_connections b JOIN publishing_targets t ON t.id=b.target_id "
                "JOIN account_connections c ON c.id=b.connection_id "
                "WHERE c.provider='meta' AND c.transport='official_api' AND "
                + " AND ".join(clauses)
                + " ORDER BY CASE WHEN c.status='connected' AND b.status='connected' THEN 0 ELSE 1 END,"
                "b.updated_at DESC",
                parameters,
            ).fetchall()
        by_target: dict[str, dict[str, Any]] = {}
        for row in rows:
            by_target.setdefault(row["target_id"], dict(row))
        return list(by_target.values())

    def due_release_ids(
        self, cooldown_hours: int = 24, limit: int = 10,
        platform: str = "youtube", source: str = "api_youtube_data_v3",
    ) -> list[str]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, cooldown_hours))).isoformat()
        with self.db.connection() as connection:
            return [row[0] for row in connection.execute(
                """SELECT r.id FROM publication_releases r
                   JOIN publishing_targets t ON t.id=r.target_id
                   WHERE r.platform=?
                     AND r.status IN ('succeeded','unknown_result')
                     AND r.verification_status='verified'
                     AND (r.external_release_id IS NOT NULL OR r.external_url IS NOT NULL)
                     AND (? != 'api_meta_graph' OR EXISTS (
                         SELECT 1 FROM provider_target_connections b
                         JOIN account_connections c ON c.id=b.connection_id
                         WHERE b.target_id=t.id AND b.provider='meta' AND b.status='connected'
                           AND b.external_target_id=t.external_id
                           AND c.provider='meta' AND c.transport='official_api' AND c.status='connected'
                     ))
                     AND NOT EXISTS (
                         SELECT 1 FROM analytics_fetch_runs f
                         WHERE f.release_id=r.id AND f.source=? AND f.started_at>=?
                     )
                     AND NOT EXISTS (
                         SELECT 1 FROM analytics_fetch_runs f
                         WHERE f.release_id=r.id AND f.source=? AND f.status='unavailable'
                     )
                   ORDER BY COALESCE((SELECT MAX(f.started_at) FROM analytics_fetch_runs f WHERE f.release_id=r.id AND f.source=?),''),
                            COALESCE(r.published_at,r.updated_at) DESC
                   LIMIT ?""",
                (platform, source, source, cutoff, source, source, max(1, min(limit, 50))),
            )]

    def due_channel_target_ids(
        self, cooldown_hours: int = 24, limit: int = 10,
        platform: str = "youtube", source: str = "api_youtube_data_v3",
    ) -> list[str]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, cooldown_hours))).isoformat()
        with self.db.connection() as connection:
            return [row[0] for row in connection.execute(
                """SELECT t.id FROM publishing_targets t
                   WHERE t.platform=? AND t.enabled=1 AND t.access_status IN ('accessible','unknown')
                     AND (? != 'api_meta_graph' OR EXISTS (
                         SELECT 1 FROM provider_target_connections b
                         JOIN account_connections c ON c.id=b.connection_id
                         WHERE b.target_id=t.id AND b.provider='meta' AND b.status='connected'
                           AND b.external_target_id=t.external_id
                           AND c.provider='meta' AND c.transport='official_api' AND c.status='connected'
                     ))
                     AND NOT EXISTS (
                         SELECT 1 FROM channel_analytics_fetch_runs f
                         WHERE f.target_id=t.id AND f.source=? AND f.started_at>=?
                     )
                   ORDER BY COALESCE((SELECT MAX(f.started_at) FROM channel_analytics_fetch_runs f WHERE f.target_id=t.id AND f.source=?),''),t.name
                   LIMIT ?""",
                (platform, source, source, cutoff, source, max(1, min(limit, 50))),
            )]

    def connect_release(
        self, release_id: str, external_url: str, note: str,
        external_release_id: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute("SELECT * FROM publication_releases WHERE id=?", (release_id,)).fetchone()
                if not row: raise KeyError(release_id)
                if row["status"] not in {"succeeded", "unknown_result"}:
                    raise ValueError("Chỉ có thể đối soát bài đã đăng hoặc đang có kết quả chưa xác định.")
                if row["external_url"] and row["external_url"] != external_url:
                    raise ValueError("Release đã gắn với một URL khác; không thể đổi identity vì có thể làm sai liên kết analytics.")
                connection.execute(
                    "UPDATE publication_releases SET external_url=?,external_release_id=COALESCE(?,external_release_id),"
                    "verification_status='verified',verification_method='manual_connect',verified_at=?,verification_note=?,updated_at=? WHERE id=?",
                    (external_url, external_release_id, now, note[:2000], now, release_id),
                )
                connection.execute(
                    "INSERT INTO publication_release_events(release_id,event_type,from_status,to_status,message,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)",
                    (release_id, "manual_connect", row["status"], row["status"], note[:2000], json.dumps({
                        "method": "manual_confirmation",
                        "target_id": row["target_id"], "account_id": row["account_id"],
                        "external_url": external_url, "external_release_id": external_release_id,
                    }), now),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK"); raise
        with self.db.connection() as connection:
            return dict(connection.execute("SELECT * FROM publication_releases WHERE id=?", (release_id,)).fetchone())

    def add_tracked_post(self, target_id: str, platform: str, external_url: str, title: str = "") -> dict[str, Any]:
        post_id, now = str(uuid.uuid4()), utc_now()
        with self.db.connection() as connection:
            try:
                connection.execute(
                    "INSERT INTO tracked_posts(id,target_id,platform,external_url,title,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                    (post_id, target_id, platform, external_url, title.strip()[:240], now, now),
                )
            except sqlite3.IntegrityError as exc:
                if "UNIQUE constraint failed" in str(exc):
                    raise ValueError("Bài viết này đã có trong danh sách theo dõi của Page.") from exc
                raise
        return self.get_tracked_post(post_id)

    def get_tracked_post(self, post_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            row = connection.execute(
                "SELECT p.*,t.name AS target_name,t.account_id FROM tracked_posts p "
                "JOIN publishing_targets t ON t.id=p.target_id WHERE p.id=?", (post_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_tracked_posts(self, target_id: str | None = None) -> list[dict[str, Any]]:
        clauses, parameters = [], []
        if target_id:
            clauses.append("p.target_id=?")
            parameters.append(target_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.db.connection() as connection:
            rows = connection.execute(
                "SELECT p.*,t.name AS target_name,t.account_id FROM tracked_posts p "
                "JOIN publishing_targets t ON t.id=p.target_id" + where + " ORDER BY p.created_at DESC", parameters,
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["metrics"] = [dict(metric) for metric in connection.execute(
                    "SELECT * FROM tracked_post_metrics WHERE tracked_post_id=? ORDER BY metric_date DESC,metric_key",
                    (item["id"],),
                )]
                run = connection.execute(
                    "SELECT * FROM tracked_post_fetch_runs WHERE tracked_post_id=? ORDER BY started_at DESC LIMIT 1",
                    (item["id"],),
                ).fetchone()
                item["latest_run"] = dict(run) if run else None
                result.append(item)
        return result

    def remove_tracked_post(self, post_id: str) -> bool:
        with self.db.connection() as connection:
            cursor = connection.execute("DELETE FROM tracked_posts WHERE id=?", (post_id,))
            return cursor.rowcount > 0

    def due_tracked_post_ids(self, cooldown_hours: int, limit: int) -> list[str]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)).isoformat()
        bounded_limit = max(1, min(int(limit), 50))
        with self.db.connection() as connection:
            rows = connection.execute(
                "SELECT p.id, MAX(r.started_at) AS last_run FROM tracked_posts p "
                "LEFT JOIN tracked_post_fetch_runs r ON r.tracked_post_id=p.id "
                "GROUP BY p.id HAVING last_run IS NULL OR last_run < ? "
                "ORDER BY last_run IS NOT NULL, last_run, p.created_at LIMIT ?",
                (cutoff, bounded_limit),
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def start_tracked_post_run(self, post_id: str, source: str) -> str:
        run_id = str(uuid.uuid4())
        stale_before = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute("SELECT 1 FROM tracked_posts WHERE id=?", (post_id,)).fetchone():
                connection.execute("ROLLBACK")
                raise KeyError(post_id)
            try:
                active = connection.execute(
                    "SELECT 1 FROM tracked_post_fetch_runs WHERE tracked_post_id=? AND source=? AND status='running' AND started_at>=? LIMIT 1",
                    (post_id, source, stale_before),
                ).fetchone()
                if active:
                    raise AnalyticsFetchInProgress("Đang cập nhật metrics cho bài này; hãy đợi lượt đó hoàn tất.")
                connection.execute(
                    "INSERT INTO tracked_post_fetch_runs(id,tracked_post_id,status,source,started_at) VALUES(?,?,?,?,?)",
                    (run_id, post_id, "running", source, utc_now()),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return run_id

    def finish_tracked_post_run(self, run_id: str, status: str, count: int, message: str | None = None) -> None:
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE tracked_post_fetch_runs SET status=?,metrics_count=?,message=?,finished_at=? WHERE id=?",
                (status, count, message, utc_now(), run_id),
            )

    def upsert_tracked_post(self, post_id: str, values: dict[str, float], *, metric_date: str,
                            timezone_name: str, source: str) -> list[dict[str, Any]]:
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute("SELECT 1 FROM tracked_posts WHERE id=?", (post_id,)).fetchone():
                connection.execute("ROLLBACK")
                raise KeyError(post_id)
            try:
                for key, value in values.items():
                    connection.execute(
                        "INSERT INTO tracked_post_metrics(id,tracked_post_id,metric_key,metric_date,timezone,value,source,fetched_at,created_at) VALUES(?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(tracked_post_id,metric_key,metric_date,source) DO UPDATE SET timezone=excluded.timezone,value=excluded.value,fetched_at=excluded.fetched_at",
                        (str(uuid.uuid4()), post_id, key, metric_date, timezone_name, float(value), source, now, now),
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM tracked_post_metrics WHERE tracked_post_id=? ORDER BY metric_date DESC,metric_key", (post_id,),
            )]

    def tracked_post_runs(self, post_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM tracked_post_fetch_runs WHERE tracked_post_id=? ORDER BY started_at DESC LIMIT 20", (post_id,),
            )]

    def tracked_post_metrics(self, post_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM tracked_post_metrics WHERE tracked_post_id=? ORDER BY metric_date DESC,metric_key", (post_id,),
            )]
