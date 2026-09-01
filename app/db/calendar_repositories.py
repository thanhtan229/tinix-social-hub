from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db.database import Database, utc_now


class SlotValidationError(ValueError):
    pass


class PostingSlotRepository:
    def __init__(self, database: Database) -> None:
        self.db = database

    @staticmethod
    def _zone(name: str) -> ZoneInfo:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise SlotValidationError(f"Múi giờ không hợp lệ: {name}") from exc

    def validate_timezone(self, name: str) -> None:
        self._zone(name)

    def replace(self, target_id: str, timezone_name: str, slots: list[dict[str, int]]) -> list[dict[str, Any]]:
        self._zone(timezone_name)
        normalized = sorted({(int(item["weekday"]), int(item["minute_of_day"])) for item in slots})
        if any(day < 0 or day > 6 or minute < 0 or minute > 1439 for day, minute in normalized):
            raise SlotValidationError("Slot cần weekday 0-6 và minute_of_day 0-1439.")
        now = utc_now()
        with self.db.connection() as connection:
            if not connection.execute("SELECT 1 FROM publishing_targets WHERE id=?", (target_id,)).fetchone():
                raise KeyError(target_id)
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("DELETE FROM channel_posting_slots WHERE target_id=?", (target_id,))
                for weekday, minute in normalized:
                    connection.execute(
                        "INSERT INTO channel_posting_slots(id,target_id,weekday,minute_of_day,timezone,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                        (str(uuid.uuid4()), target_id, weekday, minute, timezone_name, now, now),
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.list(target_id)

    def list(self, target_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM channel_posting_slots WHERE target_id=? ORDER BY weekday,minute_of_day", (target_id,)
            )]

    def find_next(self, target_id: str, after: datetime | None = None) -> datetime:
        after_utc = (after or datetime.now(timezone.utc)).astimezone(timezone.utc)
        slots = self.list(target_id)
        if not slots:
            raise SlotValidationError("Kênh chưa có posting slot.")
        zone = self._zone(slots[0]["timezone"])
        with self.db.connection() as connection:
            occupied = {
                datetime.fromisoformat(row[0]).astimezone(timezone.utc)
                for row in connection.execute(
                    "SELECT scheduled_at FROM publication_releases WHERE target_id=? AND scheduled_at IS NOT NULL "
                    "AND status NOT IN ('succeeded','dry_run_ready','permanent_failure','cancelled')",
                    (target_id,),
                )
            }
        local_after = after_utc.astimezone(zone)
        by_weekday: dict[int, list[int]] = {}
        for slot in slots:
            if slot["enabled"]:
                by_weekday.setdefault(slot["weekday"], []).append(slot["minute_of_day"])
        for delta in range(0, 371):
            day = local_after.date() + timedelta(days=delta)
            for minute in by_weekday.get(day.weekday(), []):
                wall = datetime.combine(day, time(minute // 60, minute % 60), tzinfo=zone)
                candidate = wall.astimezone(timezone.utc)
                # A DST spring-forward wall time round-trips to a different local time.
                round_trip = candidate.astimezone(zone)
                if (round_trip.date(), round_trip.hour, round_trip.minute) != (day, wall.hour, wall.minute):
                    continue
                if candidate <= after_utc or candidate in occupied:
                    continue
                return candidate
        raise SlotValidationError("Không tìm thấy posting slot khả dụng trong 370 ngày tới.")
