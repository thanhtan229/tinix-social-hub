from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db.database import Database, utc_now


class AnalyticsRepository:
    def __init__(self, database: Database) -> None:
        self.db = database

    def start_run(self, release_id: str, source: str) -> str:
        run_id = str(uuid.uuid4())
        with self.db.connection() as connection:
            if not connection.execute("SELECT 1 FROM publication_releases WHERE id=?", (release_id,)).fetchone():
                raise KeyError(release_id)
            connection.execute(
                "INSERT INTO analytics_fetch_runs(id,release_id,status,source,started_at) VALUES(?,?,?,?,?)",
                (run_id, release_id, "running", source, utc_now()),
            )
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
    ) -> list[dict[str, Any]]:
        now = fetched_at or utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if not connection.execute("SELECT 1 FROM publication_releases WHERE id=?", (release_id,)).fetchone():
                    raise KeyError(release_id)
                for key, value in values.items():
                    connection.execute(
                        "INSERT INTO release_metrics(id,release_id,metric_key,metric_date,timezone,value,source,fetched_at,created_at) VALUES(?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(release_id,metric_key,metric_date,source) DO UPDATE SET value=excluded.value,timezone=excluded.timezone,fetched_at=excluded.fetched_at",
                        (str(uuid.uuid4()), release_id, key, metric_date, timezone_name, float(value), source, now, now),
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

    def summary(self, days: int = 30, platform: str | None = None) -> dict[str, Any]:
        end = datetime.now(timezone.utc).date() + timedelta(days=1)
        start = end - timedelta(days=days)
        previous = start - timedelta(days=days)
        platform_clause = " AND r.platform=?" if platform else ""
        params: list[Any] = [previous.isoformat(), end.isoformat()]
        if platform: params.append(platform)
        with self.db.connection() as connection:
            rows = [dict(row) for row in connection.execute(
                "SELECT m.metric_key,m.metric_date,m.value,m.source,r.platform FROM release_metrics m "
                "JOIN publication_releases r ON r.id=m.release_id WHERE m.metric_date>=? AND m.metric_date<?" + platform_clause,
                params,
            )]
        current, prior = {}, {}
        for row in rows:
            bucket = current if row["metric_date"] >= start.isoformat() else prior
            bucket[row["metric_key"]] = bucket.get(row["metric_key"], 0) + row["value"]
        keys = sorted(set(current) | set(prior))
        comparison = {key: {"current": current.get(key, 0), "previous": prior.get(key, 0)} for key in keys}
        return {
            "supported": bool(rows), "days": days, "platform": platform,
            "range": {"start": start.isoformat(), "end": end.isoformat()},
            "metrics": comparison, "sources": sorted({row["source"] for row in rows}),
        }

    def connect_release(self, release_id: str, external_url: str, note: str) -> dict[str, Any]:
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute("SELECT * FROM publication_releases WHERE id=?", (release_id,)).fetchone()
                if not row: raise KeyError(release_id)
                connection.execute(
                    "UPDATE publication_releases SET external_url=?,verification_status='verified',verified_at=?,verification_note=?,updated_at=? WHERE id=?",
                    (external_url, now, note[:2000], now, release_id),
                )
                connection.execute(
                    "INSERT INTO publication_release_events(release_id,event_type,from_status,to_status,message,metadata_json,created_at) VALUES(?,?,?,?,?,'{}',?)",
                    (release_id, "manual_connect", row["status"], row["status"], note[:2000], now),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK"); raise
        with self.db.connection() as connection:
            return dict(connection.execute("SELECT * FROM publication_releases WHERE id=?", (release_id,)).fetchone())
