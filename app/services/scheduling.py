from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db.content_repositories import ContentRepository
from app.db.publication_repositories import PublicationRepository
from app.db.repositories import AccountRepository, JobRepository, TargetRepository
from app.platforms import get_platform


class SchedulingError(ValueError):
    pass


class SchedulingService:
    def __init__(
        self,
        jobs: JobRepository,
        accounts: AccountRepository,
        targets: TargetRepository,
        contents: ContentRepository,
        rng: random.Random | None = None,
        publications: PublicationRepository | None = None,
    ) -> None:
        self.jobs = jobs
        self.accounts = accounts
        self.targets = targets
        self.contents = contents
        self.rng = rng or random.SystemRandom()
        self.publications = publications or PublicationRepository(jobs.db)

    @staticmethod
    def _idempotency(content: dict[str, Any], target_id: str, scheduled_at: str | None, dry_run: bool) -> str:
        raw = json.dumps(
            [content["id"], content["current_revision"], target_id, scheduled_at or "now", dry_run],
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    def schedule(
        self,
        content_id: str,
        account_id: str,
        target_ids: list[str],
        scheduled_at: datetime | None,
        dry_run: bool,
        delay_seconds: int,
        random_delay_seconds: int,
        missed_policy: str,
    ) -> list[dict[str, Any]]:
        content = self.contents.get(content_id)
        account = self.accounts.get(account_id)
        if not content:
            raise SchedulingError("Không tìm thấy content.")
        if not account or not account["enabled"]:
            raise SchedulingError("Account không tồn tại hoặc đang bị tắt.")
        if account["platform"] != "facebook":
            raise SchedulingError("Facebook MVP chỉ lập lịch cho account Facebook.")
        approval = self.contents.current_approval(content_id)
        if not dry_run and not approval:
            raise SchedulingError("Bản revision hiện tại chưa được duyệt.")
        if not target_ids:
            raise SchedulingError("Cần chọn ít nhất một Facebook Page.")
        if missed_policy not in {"publish", "skip", "confirm"}:
            raise SchedulingError("Chính sách job bị lỡ không hợp lệ.")
        base = scheduled_at.astimezone(timezone.utc) if scheduled_at else None
        revisions = self.contents.revisions(content_id)
        if not revisions:
            raise SchedulingError("Content chưa có revision để đóng băng khi lập lịch.")
        revision_id = revisions[0]["id"]
        targets = []
        for target_id in dict.fromkeys(target_ids):
            target = self.targets.get(target_id)
            if not target or target["account_id"] != account_id or not target["enabled"]:
                raise SchedulingError("Page không hợp lệ, bị tắt hoặc không thuộc account đã chọn.")
            if target["access_status"] not in {"accessible", "unknown"}:
                raise SchedulingError(f"Page {target['name']} hiện không thể truy cập.")
            targets.append(target)

        created: list[dict[str, Any]] = []
        offset = 0
        facebook = content["platform_variants"].get("facebook") or {}
        caption = facebook.get("caption") or content["caption"]
        hashtags = facebook.get("hashtags") or content["hashtags"]
        plan_raw = json.dumps(
            [
                content_id, revision_id, account_id, sorted(target["id"] for target in targets),
                base.isoformat() if base else "now", dry_run, delay_seconds,
                random_delay_seconds, missed_policy,
            ],
            separators=(",", ":"),
        )
        plan_key = hashlib.sha256(plan_raw.encode()).hexdigest()
        plan = self.publications.create_plan(
            content_id=content_id,
            content_revision_id=revision_id,
            approval_id=approval["id"] if approval else None,
            dry_run=dry_run,
            scheduled_at=base.isoformat() if base else None,
            missed_policy=missed_policy,
            idempotency_key=plan_key,
        )
        media_snapshot = [
            {
                "id": media["id"], "type": media["media_type"],
                "relative_path": media["relative_path"],
                "thumbnail_relative_path": media.get("thumbnail_relative_path"),
                "mime_type": media["mime_type"], "size_bytes": media["size_bytes"],
                "sha256": media["sha256"], "sort_order": media["sort_order"],
            }
            for media in content["media"]
        ]
        definition = get_platform(account["platform"])
        for index, target in enumerate(targets):
            if index:
                offset += max(0, delay_seconds)
                if random_delay_seconds > 0:
                    offset += self.rng.randint(0, random_delay_seconds)
            due = (base + timedelta(seconds=offset)).isoformat() if base else None
            key = self._idempotency(content, target["id"], due, dry_run)
            existing = self.jobs.get_by_idempotency(key)
            if existing:
                created.append(existing)
                continue
            payload = {
                "content_id": content_id,
                "content_revision_id": revision_id,
                "publication_plan_id": plan["id"],
                "target_id": target["id"],
                "target_external_id": target["external_id"],
                "target_name": target["name"],
                "target_url": target["url"],
                "caption": caption,
                "hashtags": hashtags,
                "cta": facebook.get("cta") or content.get("cta"),
                "media": [
                    {"type": media["media_type"], "relative_path": media["relative_path"]}
                    for media in content["media"]
                ],
            }
            release_key = hashlib.sha256(f"release:{plan_key}:{target['id']}:{due or 'now'}".encode()).hexdigest()
            release = self.publications.create_release(
                plan_id=plan["id"], content_id=content_id, content_revision_id=revision_id,
                account_id=account_id, target_id=target["id"], platform=account["platform"],
                content_format="video" if any(item["type"] == "video" for item in media_snapshot) else "post",
                scheduled_at=due,
                settings={"cta": facebook.get("cta") or content.get("cta")},
                payload_snapshot=payload, media_snapshot=media_snapshot,
                selector_version=getattr(definition, "selector_version", None),
                idempotency_key=release_key,
            )
            payload["publication_release_id"] = release["id"]
            job = self.jobs.create(
                "publish", payload, account_id, due, dry_run=dry_run, content_id=content_id,
                target_id=target["id"], approval_id=approval["id"] if approval else None,
                idempotency_key=key, missed_policy=missed_policy,
                publication_release_id=release["id"],
            )
            self.publications.attach_job(release["id"], job["id"])
            created.append(job)
        return created
