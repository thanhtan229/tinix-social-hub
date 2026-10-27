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
    def resolve_content(content: dict[str, Any], platform: str, target_id: str) -> dict[str, Any]:
        """Resolve the persisted composition while retaining legacy variant semantics."""
        composition = content.get("composition") or {}
        if composition.get("version") != 1:
            variant = content.get("platform_variants", {}).get(platform) or {}
            return {
                "title": variant.get("title") or content["title"],
                "caption": variant.get("caption") or content["caption"],
                "hashtags": variant.get("hashtags") or content["hashtags"],
                "cta": variant.get("cta") or content.get("cta"),
                "pinned_comment": variant.get("pinned_comment"),
                "video_hook": variant.get("video_hook"),
                "video_script": variant.get("video_script"),
            }

        resolved = dict(composition.get("global_content") or {})
        platform_override = composition.get("platform_overrides", {}).get(platform)
        target_override = composition.get("target_overrides", {}).get(target_id)
        for override in (platform_override, target_override):
            if override is not None:
                resolved.update(override)
        legacy_variant = content.get("platform_variants", {}).get(platform) or {}
        return {
            "title": resolved.get("title") or legacy_variant.get("title") or content["title"],
            "caption": resolved.get("caption", content["caption"]),
            "hashtags": resolved.get("hashtags", content["hashtags"]),
            "cta": resolved.get("cta", content.get("cta")),
            "pinned_comment": resolved.get("pinned_comment", legacy_variant.get("pinned_comment")),
            "video_hook": resolved.get("video_hook", legacy_variant.get("video_hook")),
            "video_script": resolved.get("video_script", legacy_variant.get("video_script")),
        }

    def schedule_batch(
        self, *, content_id: str, target_ids: list[str], scheduled_at: datetime,
        dry_run: bool, missed_policy: str, content_format: str,
        platform_settings: dict[str, Any], request_key: str = "",
        routing_preference: str | None = None, target_scheduled_at: dict[str, datetime] | None = None,
        target_content_formats: dict[str, str] | None = None,
        target_platform_settings: dict[str, dict[str, Any]] | None = None,
        delay_seconds: int = 0, random_delay_seconds: int = 0,
        preflight_only: bool = False,
    ) -> Any:
        unique_target_ids = list(dict.fromkeys(target_ids))
        if not unique_target_ids or len(unique_target_ids) != len(target_ids):
            raise SchedulingError("Cần chọn Page hợp lệ và không chọn trùng.")
        if len(unique_target_ids) > 100:
            raise SchedulingError("Mỗi lần có thể chọn tối đa 100 Page.")
        target_scheduled_at = target_scheduled_at or {}
        target_content_formats = target_content_formats or {}
        target_platform_settings = target_platform_settings or {}
        if set(target_scheduled_at) - set(unique_target_ids):
            raise SchedulingError("Có giờ đăng riêng cho Page không nằm trong danh sách đã chọn.")
        if set(target_content_formats) - set(unique_target_ids) or set(target_platform_settings) - set(unique_target_ids):
            raise SchedulingError("Có cấu hình xuất bản cho đích không nằm trong danh sách đã chọn.")
        if any(value.tzinfo is None for value in target_scheduled_at.values()):
            raise SchedulingError("Ngày giờ riêng của từng Page cần timezone rõ ràng.")
        if not preflight_only and (not request_key or len(request_key) > 160):
            raise SchedulingError("Mã yêu cầu lên lịch không hợp lệ.")
        if scheduled_at.tzinfo is None:
            raise SchedulingError("Ngày giờ lên lịch cần timezone rõ ràng.")
        if missed_policy not in {"publish", "skip", "confirm"}:
            raise SchedulingError("Chính sách job bị lỡ không hợp lệ.")

        content = self.contents.get(content_id)
        if not content:
            raise SchedulingError("Không tìm thấy content.")
        revisions = self.contents.revisions(content_id)
        if not revisions:
            raise SchedulingError("Content chưa có revision để đóng băng khi lập lịch.")
        revision_id = revisions[0]["id"]
        approval = self.contents.current_approval(content_id)
        if not dry_run and not approval:
            raise SchedulingError("Bản revision hiện tại chưa được duyệt.")

        targets: list[tuple[dict[str, Any], dict[str, Any], str, dict[str, Any], str]] = []
        target_results: list[dict[str, Any]] = []
        target_errors: list[str] = []
        for target_id in unique_target_ids:
            target = self.targets.get(target_id)
            account = self.accounts.get(target["account_id"]) if target else None
            if not target or not account or not account.get("enabled") or account.get("profile_operation_locked"):
                message = "Page không tồn tại, account đang tắt hoặc đang bảo trì."
                target_errors.append(message)
                target_results.append({"target_id": target_id, "name": target.get("name") if target else target_id, "status": "error", "error": message})
                continue
            if not target.get("enabled") or target.get("access_status") not in {"accessible", "unknown"}:
                message = f"Page {target['name']} hiện không thể truy cập."
                target_errors.append(message)
                target_results.append({"target_id": target_id, "name": target["name"], "status": "error", "error": message})
                continue
            if self.targets.is_system_navigation_target(target):
                message = "Đích này là liên kết điều hướng, không phải Page có thể đăng."
                target_errors.append(message)
                target_results.append({"target_id": target_id, "name": target["name"], "status": "error", "error": message})
                continue
            definition = get_platform(account["platform"])
            if not definition or not definition.operational or target["platform"] != account["platform"]:
                message = f"Nền tảng của Page {target['name']} chưa được bật."
                target_errors.append(message)
                target_results.append({"target_id": target_id, "name": target["name"], "status": "error", "error": message})
                continue
            resolved_format = target_content_formats.get(target_id, content_format)
            if resolved_format not in definition.content_formats:
                message = f"Định dạng {resolved_format} chưa được hỗ trợ cho {definition.name}."
                target_errors.append(message)
                target_results.append({"target_id": target_id, "name": target["name"], "status": "error", "error": message})
                continue
            try:
                preference = RoutingPreference(
                    routing_preference or account.get("routing_preference") or RoutingPreference.CHROME_PREFERRED
                ).value
            except ValueError as exc:
                message = "Routing preference không hợp lệ."
                target_errors.append(message)
                target_results.append({"target_id": target_id, "name": target["name"], "status": "error", "error": message})
                continue
            variant = self.resolve_content(content, account["platform"], target_id)
            targets.append((target, account, preference, variant, resolved_format))

        entries: list[dict[str, Any]] = []
        cumulative_delay = 0
        for index, (target, account, preference, variant, target_format) in enumerate(targets):
            source_media = content.get("target_media_overrides", {}).get(target["id"], content["media"])
            media_snapshot = [
                {"id": media.get("asset_id") or media.get("id"), "type": media["media_type"],
                 "relative_path": media["relative_path"], "original_name": media["original_name"],
                 "thumbnail_relative_path": media.get("thumbnail_relative_path"), "mime_type": media["mime_type"],
                 "size_bytes": media["size_bytes"], "sha256": media["sha256"],
                 "sort_order": media.get("sort_order", 0)}
                for media in source_media
            ]
            validation_media = [{"type": item["type"], "size_bytes": item["size_bytes"],
                                 "relative_path": item["relative_path"], "mime_type": item["mime_type"],
                                 "sha256": item["sha256"]}
                                for item in media_snapshot]
            try:
                if self.publisher_router:
                    route = self.publisher_router.resolve(
                        account, content_format=target_format, dry_run=dry_run, preference=preference,
                        target_external_id=target["external_id"], target_id=target["id"],
                    )
                    if route.reason == "no_eligible_transport":
                        raise SchedulingError("Không có phương thức đăng phù hợp.")
                    transport = get_platform(account["platform"]).transport(route.transport)
                    if not transport or target_format not in transport.content_formats:
                        raise SchedulingError("Định dạng chưa được hỗ trợ với phương thức đăng này.")
                else:
                    route = type("Route", (), {
                        "reason": "selected_by_catalog_default", "transport": "chrome", "provider": None,
                        "publisher": None, "connection_id": None, "connection_scopes_hash": None,
                        "provider_target_binding_id": None, "provider_target_external_id": None,
                    })()
                publisher = route.publisher
                route_version = getattr(publisher, "provider_version", None)
                selector_for_format = getattr(publisher, "selector_version_for", None)
                selector_version = (selector_for_format(target_format) if selector_for_format else
                                    getattr(publisher, "selector_version", get_platform(account["platform"]).selector_version))
                route_data = {
                    "transport": route.transport, "provider": route.provider, "provider_version": route_version,
                    "selector_version": selector_version, "reason": route.reason,
                    "connection_id": route.connection_id, "connection_scopes_hash": route.connection_scopes_hash,
                    "provider_target_binding_id": route.provider_target_binding_id,
                    "provider_target_external_id": route.provider_target_external_id,
                }
                route_raw = json.dumps(route_data, sort_keys=True, separators=(",", ":"))
                route_fingerprint = hashlib.sha256(route_raw.encode()).hexdigest()
                caption = "\n\n".join(part for part in (variant["caption"], " ".join(variant["hashtags"] or [])) if part).strip()
                settings = dict(platform_settings)
                settings.setdefault("cta", variant["cta"])
                settings.update(target_platform_settings.get(target["id"], {}))
                validate_publication(account["platform"], target_format, caption, validation_media, settings)
                if route.transport == "official_api" and route.provider == "meta":
                    errors = publisher.validate({"caption": caption, "media": validation_media,
                                                 "content_format": target_format}, settings)
                    if errors:
                        raise SchedulingError(" ".join(errors))
                if not dry_run and not self.publications.dry_run_evidence(
                    account_id=account["id"], target_id=target["id"], content_format=target_format,
                    transport=route.transport, selector_version=selector_version, provider_version=route_version,
                    connection_id=route.connection_id, connection_scopes_hash=route.connection_scopes_hash,
                ):
                    raise SchedulingError("Cần dry-run thành công với phương thức đăng hiện tại.")
            except PlatformValidationError as exc:
                target_errors.append(f"{target['name']}: {exc}")
                target_results.append({"target_id": target["id"], "name": target["name"], "status": "error", "error": str(exc)})
                continue
            except SchedulingError as exc:
                target_errors.append(f"{target['name']}: {exc}")
                target_results.append({"target_id": target["id"], "name": target["name"], "status": "error", "error": str(exc)})
                continue

            if index:
                jitter_seed = int(hashlib.sha256(f"{request_key}:{target['id']}".encode()).hexdigest()[:8], 16)
                cumulative_delay += max(0, delay_seconds)
                if random_delay_seconds > 0:
                    cumulative_delay += jitter_seed % (random_delay_seconds + 1)
            target_due = target_scheduled_at.get(target["id"], scheduled_at)
            if target_due.tzinfo is None:
                message = "Ngày giờ đăng riêng của Page cần timezone rõ ràng."
                target_errors.append(f"{target['name']}: {message}")
                target_results.append({"target_id": target["id"], "name": target["name"], "status": "error", "error": message})
                continue
            if target["id"] not in target_scheduled_at and index:
                target_due = target_due + timedelta(seconds=cumulative_delay)
            due = target_due.astimezone(timezone.utc).isoformat()
            payload = {
                "content_id": content_id, "content_format": target_format, "platform_settings": settings,
                "title": variant["title"], "target_id": target["id"], "target_external_id": target["external_id"],
                "target_name": target["name"], "target_url": target["url"], "caption": variant["caption"],
                "hashtags": variant["hashtags"], "cta": variant["cta"],
                "media": [{"type": item["type"], "relative_path": item["relative_path"],
                           "mime_type": item["mime_type"], "size_bytes": item["size_bytes"],
                           "sha256": item["sha256"]} for item in media_snapshot],
                "routing_preference": preference,
                "provider_target_binding_id": route.provider_target_binding_id,
                "provider_target_external_id": route.provider_target_external_id,
            }
            entry_hash = json.dumps(
                [target["id"], account["id"], due, target_format, settings, variant, route_fingerprint],
                sort_keys=True, separators=(",", ":"),
            )
            entry_key = hashlib.sha256(f"{request_key}:{target['id']}:{entry_hash}".encode()).hexdigest()
            entries.append({
                "account_id": account["id"], "target_id": target["id"], "target_name": target["name"],
                "platform": account["platform"], "content_format": target_format, "scheduled_at": due,
                "settings": settings, "payload": payload, "media_snapshot": media_snapshot,
                "selector_version": selector_version, "routing_preference": preference,
                "publication_transport": route.transport, "provider": route.provider,
                "provider_version": route_version, "routing_reason": route.reason,
                "connection_id": route.connection_id, "connection_scopes_hash": route.connection_scopes_hash,
                "provider_target_binding_id": route.provider_target_binding_id,
                "route_fingerprint": route_fingerprint, "job_key": entry_key,
                "release_key": hashlib.sha256(f"release:{entry_key}".encode()).hexdigest(),
            })
            target_results.append({
                "target_id": target["id"], "name": target["name"], "account_name": account["name"],
                "status": "ready", "caption": caption, "hashtags": variant["hashtags"],
                "platform": account["platform"], "content_format": target_format,
                "transport": route.transport, "provider": route.provider, "scheduled_at": due,
                "media": [{"name": item["original_name"], "type": item["type"]} for item in media_snapshot],
            })

        if preflight_only:
            return {"ready": not target_errors and len(entries) == len(unique_target_ids), "targets": target_results}
        if target_errors:
            raise SchedulingError("Không thể lên lịch toàn bộ đợt: " + " | ".join(target_errors))

        request_hash_raw = json.dumps(
            {"content_id": content_id, "revision_id": revision_id, "approval_id": approval["id"] if approval else None,
             "dry_run": dry_run, "missed_policy": missed_policy,
             "delay_seconds": delay_seconds, "random_delay_seconds": random_delay_seconds,
             "entries": [{key: item[key] for key in ("account_id", "target_id", "scheduled_at", "content_format",
                                                       "settings", "payload", "route_fingerprint")} for item in entries]},
            sort_keys=True, separators=(",", ":"),
        )
        request_hash = hashlib.sha256(request_hash_raw.encode()).hexdigest()
        plan_key = hashlib.sha256(f"{request_key}:{request_hash}".encode()).hexdigest()
        try:
            _, jobs = self.publications.create_batch(
                content_id=content_id, revision_id=revision_id, approval_id=approval["id"] if approval else None,
                dry_run=dry_run, missed_policy=missed_policy, request_key=request_key,
                request_hash=request_hash, plan_key=plan_key, entries=entries,
            )
            return jobs
        except ValueError as exc:
            raise SchedulingError(str(exc)) from exc

    @staticmethod
    def _idempotency(
        content: dict[str, Any], target_id: str, scheduled_at: str | None, dry_run: bool,
        content_format: str, platform_settings: dict[str, Any],
        routing_preference: str = "chrome_preferred",
        route_fingerprint: str | None = None,
    ) -> str:
        raw = json.dumps(
            [
                content["id"], content["current_revision"], target_id, scheduled_at or "now",
                dry_run, content_format, platform_settings, routing_preference, route_fingerprint,
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

        routes_by_target: dict[str, dict[str, Any]] = {}
        for target in targets:
            publisher = None
            route_transport = "chrome"
            route_provider = None
            route_provider_version = None
            route_selector_version = definition.selector_version
            route_reason = "selected_by_catalog_default"
            route_connection_id = None
            route_connection_scopes_hash = None
            route_target_binding_id = None
            route_target_external_id = None
            if self.publisher_router:
                resolved = self.publisher_router.resolve(
                    account, content_format=content_format, dry_run=dry_run,
                    preference=requested_routing, target_external_id=target["external_id"], target_id=target["id"],
                )
                if resolved.reason == "no_eligible_transport":
                    raise SchedulingError(f"Không có transport phù hợp cho {target['name']} và định dạng đã chọn.")
                transport = definition.transport(resolved.transport)
                if not transport or content_format not in transport.content_formats:
                    raise SchedulingError("Định dạng đã chọn chưa được hỗ trợ bởi phương thức đăng hiện tại.")
                publisher = resolved.publisher
                route_transport = resolved.transport
                route_provider = resolved.provider
                route_provider_version = getattr(resolved.publisher, "provider_version", None)
                selector_for_format = getattr(resolved.publisher, "selector_version_for", None)
                route_selector_version = (selector_for_format(content_format) if selector_for_format else
                                          getattr(resolved.publisher, "selector_version", definition.selector_version))
                route_reason = resolved.reason
                route_connection_id = resolved.connection_id
                route_connection_scopes_hash = resolved.connection_scopes_hash
                route_target_binding_id = resolved.provider_target_binding_id
                route_target_external_id = resolved.provider_target_external_id
            route_data = {
                "publisher": publisher, "transport": route_transport, "provider": route_provider,
                "provider_version": route_provider_version, "selector_version": route_selector_version,
                "reason": route_reason, "connection_id": route_connection_id,
                "connection_scopes_hash": route_connection_scopes_hash,
                "provider_target_binding_id": route_target_binding_id,
                "provider_target_external_id": route_target_external_id,
            }
            fingerprint_raw = json.dumps(
                [route_transport, route_provider, route_provider_version, route_selector_version,
                 route_connection_id, route_connection_scopes_hash, route_target_binding_id, route_target_external_id], separators=(",", ":"),
            )
            route_data["fingerprint"] = hashlib.sha256(fingerprint_raw.encode()).hexdigest()
            routes_by_target[target["id"]] = route_data

        if not dry_run:
            missing_evidence = [
                target["name"] for target in targets
                if not self.publications.dry_run_evidence(
                    account_id=account_id,
                    target_id=target["id"],
                    content_format=content_format,
                    transport=routes_by_target[target["id"]]["transport"],
                    selector_version=routes_by_target[target["id"]]["selector_version"],
                    provider_version=routes_by_target[target["id"]]["provider_version"],
                    connection_id=routes_by_target[target["id"]]["connection_id"],
                    connection_scopes_hash=routes_by_target[target["id"]]["connection_scopes_hash"],
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
        variants_by_target = {
            target["id"]: self.resolve_content(content, account["platform"], target["id"])
            for target in targets
        }
        platform_settings = dict(platform_settings or {})
        validation_media = [
            {"type": media["media_type"], "size_bytes": media["size_bytes"],
             "relative_path": media["relative_path"], "mime_type": media["mime_type"],
             "sha256": media["sha256"]}
            for media in content["media"]
        ]
        try:
            for target in targets:
                variant = variants_by_target[target["id"]]
                validation_caption = "\n\n".join(
                    part for part in (variant["caption"], " ".join(variant["hashtags"] or [])) if part
                ).strip()
                settings_for_target = dict(platform_settings)
                settings_for_target.setdefault("cta", variant["cta"])
                validate_publication(
                    account["platform"], content_format, validation_caption,
                    validation_media, settings_for_target,
                )
                route = routes_by_target[target["id"]]
                if route["transport"] == "official_api" and route["provider"] == "meta":
                    errors = route["publisher"].validate(
                        {"caption": validation_caption, "media": validation_media,
                         "content_format": content_format}, settings_for_target,
                    )
                    if errors:
                        raise SchedulingError(" ".join(errors))
        except PlatformValidationError as exc:
            raise SchedulingError(str(exc)) from exc
        plan_raw = json.dumps(
            [
                content_id, revision_id, account_id, sorted(target["id"] for target in targets),
                base.isoformat() if base else "now", dry_run, delay_seconds,
                random_delay_seconds, missed_policy,
                content_format, platform_settings, requested_routing,
                sorted((target_id, route["fingerprint"]) for target_id, route in routes_by_target.items()),
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
                routes_by_target[target["id"]]["fingerprint"],
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
                "title": variants_by_target[target["id"]]["title"],
                "target_id": target["id"],
                "target_external_id": target["external_id"],
                "target_name": target["name"],
                "target_url": target["url"],
                "caption": variants_by_target[target["id"]]["caption"],
                "hashtags": variants_by_target[target["id"]]["hashtags"],
                "cta": variants_by_target[target["id"]]["cta"],
                "media": [
                    {"type": media["media_type"], "relative_path": media["relative_path"],
                     "mime_type": media["mime_type"], "size_bytes": media["size_bytes"],
                     "sha256": media["sha256"]}
                    for media in content["media"]
                ],
                "routing_preference": requested_routing,
                "provider_target_binding_id": routes_by_target[target["id"]]["provider_target_binding_id"],
                "provider_target_external_id": routes_by_target[target["id"]]["provider_target_external_id"],
            }
            route = routes_by_target[target["id"]]
            release_key = hashlib.sha256(f"release:{plan_key}:{target['id']}:{due or 'now'}".encode()).hexdigest()
            release = self.publications.create_release(
                plan_id=plan["id"], content_id=content_id, content_revision_id=revision_id,
                account_id=account_id, target_id=target["id"], platform=account["platform"],
                content_format=content_format,
                scheduled_at=due,
                settings=platform_settings,
                payload_snapshot=payload, media_snapshot=media_snapshot,
                selector_version=route["selector_version"],
                idempotency_key=release_key,
                requested_routing_policy=requested_routing,
                publication_transport=route["transport"],
                provider=route["provider"],
                provider_version=route["provider_version"],
                routing_reason=route["reason"],
                connection_id=route["connection_id"],
                connection_scopes_hash=route["connection_scopes_hash"],
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
