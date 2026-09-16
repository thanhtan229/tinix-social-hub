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
from app.platforms.validation import PlatformValidationError, validate_publication
from app.services.publisher_router import PublisherRouter, RoutingPreference


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
        publisher_router: PublisherRouter | None = None,
    ) -> None:
        self.jobs = jobs
        self.accounts = accounts
        self.targets = targets
        self.contents = contents
        self.rng = rng or random.SystemRandom()
        self.publications = publications or PublicationRepository(jobs.db)
        self.publisher_router = publisher_router

    @staticmethod
    def _idempotency(
        content: dict[str, Any], target_id: str, scheduled_at: str | None, dry_run: bool,
        content_format: str, platform_settings: dict[str, Any],
        routing_preference: str = "chrome_preferred",
    ) -> str:
        raw = json.dumps(
            [
                content["id"], content["current_revision"], target_id, scheduled_at or "now",
                dry_run, content_format, platform_settings, routing_preference,
            ],
            sort_keys=True,
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
        content_format: str = "post",
        platform_settings: dict[str, Any] | None = None,
        routing_preference: str | None = None,
    ) -> list[dict[str, Any]]:
        content = self.contents.get(content_id)
        account = self.accounts.get(account_id)
        if not content:
            raise SchedulingError("Không tìm thấy content.")
        if not account or not account["enabled"]:
            raise SchedulingError("Account không tồn tại hoặc đang bị tắt.")
        if account.get("profile_operation_locked"):
            raise SchedulingError("Profile của account đang được bảo trì; hãy thử lại sau.")
        definition = get_platform(account["platform"])
        if not definition or not definition.operational:
            raise SchedulingError("Nền tảng chưa được bật cho Chrome publishing.")
        try:
            requested_routing = RoutingPreference(
                routing_preference or account.get("routing_preference") or RoutingPreference.CHROME_PREFERRED
            ).value
        except ValueError as exc:
            raise SchedulingError("Routing preference không hợp lệ.") from exc
        route_transport = "chrome"
        route_provider: str | None = None
        route_provider_version: str | None = None
        route_selector_version = definition.selector_version
        route_reason = "selected_by_catalog_default"
        route_connection_id: str | None = None
        if self.publisher_router:
            route = self.publisher_router.resolve(
                account, content_format=content_format, dry_run=dry_run, preference=requested_routing,
            )
            if route.reason == "no_eligible_transport":
                raise SchedulingError("Không có transport phù hợp cho account và định dạng đã chọn.")
            transport = definition.transport(route.transport)
            if not transport or content_format not in transport.content_formats:
                raise SchedulingError("Định dạng đã chọn chưa được hỗ trợ bởi phương thức đăng hiện tại.")
            route_transport = route.transport
            route_provider = route.provider
            route_provider_version = getattr(route.publisher, "provider_version", None)
            route_selector_version = getattr(route.publisher, "selector_version", definition.selector_version)
            route_reason = route.reason
            route_connection_id = route.connection_id
        approval = self.contents.current_approval(content_id)
        if not dry_run and not approval:
            raise SchedulingError("Bản revision hiện tại chưa được duyệt.")
        if not target_ids:
            raise SchedulingError("Cần chọn ít nhất một Page/profile/channel.")
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
            if self.targets.is_system_navigation_target(target):
                raise SchedulingError("Đích đã chọn là liên kết điều hướng hệ thống, không phải Page/Kênh có thể đăng.")
            if target["access_status"] not in {"accessible", "unknown"}:
                raise SchedulingError(f"Page {target['name']} hiện không thể truy cập.")
            targets.append(target)

        if not dry_run:
            missing_evidence = [
                target["name"] for target in targets
                if not self.publications.dry_run_evidence(
                    account_id=account_id,
                    target_id=target["id"],
                    content_format=content_format,
                    transport=route_transport,
                    selector_version=route_selector_version,
                    provider_version=route_provider_version,
                )
            ]
            if missing_evidence:
                labels = ", ".join(missing_evidence[:3])
                suffix = "…" if len(missing_evidence) > 3 else ""
                raise SchedulingError(
                    "Đăng thật yêu cầu dry-run thành công với route hiện tại "
                    f"(account, Page/Kênh, định dạng và phiên bản publisher). Chưa có bằng chứng: {labels}{suffix}."
                )

        created: list[dict[str, Any]] = []
        offset = 0
        variant = content["platform_variants"].get(account["platform"]) or {}
        caption = variant.get("caption") or content["caption"]
        hashtags = variant.get("hashtags") or content["hashtags"]
        platform_settings = dict(platform_settings or {})
        platform_settings.setdefault("cta", variant.get("cta") or content.get("cta"))
        validation_media = [
            {"type": media["media_type"], "size_bytes": media["size_bytes"]}
            for media in content["media"]
        ]
        validation_caption = "\n\n".join(
            part for part in (caption, " ".join(hashtags or [])) if part
        ).strip()
        try:
            validate_publication(
                account["platform"], content_format, validation_caption,
                validation_media, platform_settings,
            )
        except PlatformValidationError as exc:
            raise SchedulingError(str(exc)) from exc
        plan_raw = json.dumps(
            [
                content_id, revision_id, account_id, sorted(target["id"] for target in targets),
                base.isoformat() if base else "now", dry_run, delay_seconds,
                random_delay_seconds, missed_policy,
                content_format, platform_settings, requested_routing,
            ],
            sort_keys=True,
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
        for index, target in enumerate(targets):
            if index:
                offset += max(0, delay_seconds)
                if random_delay_seconds > 0:
                    offset += self.rng.randint(0, random_delay_seconds)
            due = (base + timedelta(seconds=offset)).isoformat() if base else None
            key = self._idempotency(
                content, target["id"], due, dry_run, content_format, platform_settings, requested_routing,
            )
            existing = self.jobs.get_by_idempotency(key)
            if existing:
                created.append(existing)
                continue
            payload = {
                "content_id": content_id,
                "content_revision_id": revision_id,
                "publication_plan_id": plan["id"],
                "content_format": content_format,
                "platform_settings": platform_settings,
                "title": variant.get("title") or content["title"],
                "target_id": target["id"],
                "target_external_id": target["external_id"],
                "target_name": target["name"],
                "target_url": target["url"],
                "caption": caption,
                "hashtags": hashtags,
                "cta": variant.get("cta") or content.get("cta"),
                "media": [
                    {"type": media["media_type"], "relative_path": media["relative_path"]}
                    for media in content["media"]
                ],
                "routing_preference": requested_routing,
            }
            release_key = hashlib.sha256(f"release:{plan_key}:{target['id']}:{due or 'now'}".encode()).hexdigest()
            release = self.publications.create_release(
                plan_id=plan["id"], content_id=content_id, content_revision_id=revision_id,
                account_id=account_id, target_id=target["id"], platform=account["platform"],
                content_format=content_format,
                scheduled_at=due,
                settings=platform_settings,
                payload_snapshot=payload, media_snapshot=media_snapshot,
                selector_version=route_selector_version,
                idempotency_key=release_key,
                requested_routing_policy=requested_routing,
                publication_transport=route_transport,
                provider=route_provider,
                provider_version=route_provider_version,
                routing_reason=route_reason,
                connection_id=route_connection_id,
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
