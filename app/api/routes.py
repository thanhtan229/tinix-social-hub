from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psutil
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app import __version__
from app.platforms import PLATFORM_CATALOG, get_platform
from app.runtime import runtime_report

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    platform: str = Field(min_length=1, max_length=40)
    username: str = Field(default="", max_length=500)
    email: str = Field(default="", max_length=500)
    password: str = Field(default="", max_length=2_000)
    secret_2fa: str = Field(default="", max_length=500)
    email_pass: str = Field(default="", max_length=2_000)
    cookie: str = Field(default="", max_length=200_000)


class AccountUpdate(AccountCreate):
    pass


class EnabledUpdate(BaseModel):
    enabled: bool
    reason: str | None = Field(default=None, max_length=500)


class RoutingPreferenceUpdate(BaseModel):
    routing_preference: str = Field(
        pattern="^(official_api_preferred|chrome_preferred|official_api_only|chrome_only)$"
    )


class TargetGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class TargetGroupMembers(BaseModel):
    target_ids: list[str] = Field(default_factory=list, max_length=500)


class JobCreate(BaseModel):
    kind: str = Field(pattern="^(publish|ai_content)$")
    account_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    scheduled_at: datetime | None = None
    dry_run: bool = True


class RestoreRequest(BaseModel):
    name: str


class ProfileImportRequest(BaseModel):
    source_path: str = Field(min_length=3, max_length=2000)


class ProfileBundleImportRequest(BaseModel):
    bundle_path: str = Field(min_length=3, max_length=2000)


class ProfileRestoreRequest(BaseModel):
    backup_name: str = Field(min_length=1, max_length=200)


class ProfileAutoCleanupSettings(BaseModel):
    enabled: bool = True
    threshold_gb: float = Field(default=5, ge=0.5, le=100)


class PostingSlotItem(BaseModel):
    weekday: int = Field(ge=0, le=6)
    minute_of_day: int = Field(ge=0, le=1439)


class PostingSlotsUpdate(BaseModel):
    timezone: str = Field(default="Asia/Bangkok", min_length=1, max_length=100)
    slots: list[PostingSlotItem] = Field(default_factory=list, max_length=100)


class ReleaseReschedule(BaseModel):
    scheduled_at: datetime
    timezone: str = Field(default="Asia/Bangkok", min_length=1, max_length=100)


class JobFinalize(BaseModel):
    succeeded: bool
    note: str = Field(min_length=1, max_length=2000)
    post_url: str | None = Field(default=None, max_length=2000)


class BulkRetry(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=200)
    preview: bool = True


class JobHistoryCleanup(BaseModel):
    mode: str = Field(pattern="^(older_than|custom|all|selected)$")
    older_than_days: int | None = Field(default=None, ge=1, le=3650)
    from_date: datetime | None = None
    to_date: datetime | None = None
    status_filter: str = Field(default="all", pattern="^(all|succeeded|dry_run|failed)$")
    job_ids: list[str] = Field(default_factory=list, max_length=5000)
    candidate_ids: list[str] = Field(default_factory=list, max_length=5000)
    delete_artifacts: bool = True
    preview: bool = True
    confirm: bool = False


class ReleaseConnect(BaseModel):
    external_url: str = Field(min_length=10, max_length=2000)
    note: str = Field(default="Kết nối thủ công từ WebUI", min_length=1, max_length=2000)


def services(request: Request) -> Any:
    return request.app.state.services


def public_account(account: dict[str, Any] | None) -> dict[str, Any] | None:
    if account is None:
        return None
    hidden = {"password", "secret_2fa", "email_pass", "cookie"}
    public = {key: value for key, value in account.items() if key not in hidden}
    public.update({
        "has_password": bool(account.get("password")),
        "has_2fa": bool(account.get("secret_2fa")),
        "has_email_password": bool(account.get("email_pass")),
        "has_cookie": bool(account.get("cookie")),
    })
    return public


@router.get("/platforms")
async def list_platforms() -> list[dict[str, object]]:
    """Expose the architecture roadmap without enabling unfinished features."""
    return [platform.to_dict() for platform in PLATFORM_CATALOG]


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    svc = services(request)
    integrity = await asyncio.to_thread(svc.database.ping)
    usage = shutil.disk_usage(svc.settings.data_dir)
    chrome = await asyncio.to_thread(svc.chrome.status)
    memory = psutil.virtual_memory()
    process_memory = psutil.Process().memory_info().rss
    queue_health = await asyncio.to_thread(svc.jobs.health_counts)
    provider_connections = getattr(svc, "provider_connections", None)
    provider_health = await asyncio.to_thread(provider_connections.health_counts) if provider_connections else {}
    warnings = []
    if queue_health["stuck"]:
        warnings.append({"code": "stuck_jobs", "severity": "warning", "count": queue_health["stuck"]})
    if queue_health["needs_attention"]:
        warnings.append({"code": "jobs_need_attention", "severity": "warning", "count": queue_health["needs_attention"]})
    if usage.free < max(2 * 1024**3, int(usage.total * .1)):
        warnings.append({"code": "disk_low", "severity": "error", "free_bytes": usage.free})
    maintenance = getattr(svc, "maintenance", None)
    return {
        "status": "ok" if integrity["ok"] else "degraded",
        "version": __version__,
        "backend": "running",
        "worker": {"state": svc.worker.state, "active_jobs": svc.worker.active_count},
        "scheduler": svc.scheduler.state,
        "database": integrity,
        "chrome": {
            "running": len(chrome), "limit": svc.settings.max_chrome,
            "hung": sum(1 for item in chrome if item.get("hung")),
        },
        "disk": {"free_bytes": usage.free, "total_bytes": usage.total},
        "memory": {"available_bytes": memory.available, "total_bytes": memory.total, "process_bytes": process_memory},
        "ai_configured": svc.ai.configured,
        "queue_health": queue_health,
        "provider_connections": provider_health,
        "warnings": warnings,
        "maintenance": {
            "state": getattr(maintenance, "state", "unavailable"),
            "last_result": getattr(maintenance, "last_result", None),
        },
    }


@router.get("/runtime")
async def runtime_readiness(request: Request) -> dict[str, Any]:
    svc = services(request)
    return runtime_report(
        database=svc.database, queue=svc.jobs, storage=svc.storage,
        secrets=svc.secrets, browser=svc.chrome,
    )


@router.get("/accounts")
async def list_accounts(request: Request) -> list[dict[str, Any]]:
    accounts = await asyncio.to_thread(services(request).accounts.list)
    return [public_account(account) for account in accounts]


@router.get("/accounts/{account_id}/credentials")
async def account_credentials(account_id: str, request: Request, response: Response) -> dict[str, str]:
    account = await asyncio.to_thread(services(request).accounts.get, account_id)
    if not account:
        raise HTTPException(404, "Không tìm thấy account.")
    response.headers["Cache-Control"] = "no-store"
    return {
        "password": str(account.get("password") or ""),
        "secret_2fa": str(account.get("secret_2fa") or ""),
        "email_pass": str(account.get("email_pass") or ""),
        "cookie": str(account.get("cookie") or ""),
    }


@router.post("/accounts", status_code=201)
async def create_account(body: AccountCreate, request: Request) -> dict[str, Any]:
    if not get_platform(body.platform):
        raise HTTPException(422, "Nền tảng không được hỗ trợ.")
    account = await asyncio.to_thread(
        services(request).accounts.create, body.name, body.platform,
        metadata=body.model_dump(exclude={"name", "platform"}),
    )
    return public_account(account)


@router.put("/accounts/{account_id}")
async def update_account(account_id: str, body: AccountUpdate, request: Request) -> dict[str, Any]:
    if not get_platform(body.platform):
        raise HTTPException(422, "Nền tảng không được hỗ trợ.")
    account = await asyncio.to_thread(
        services(request).accounts.update, account_id, body.name, body.platform,
        metadata=body.model_dump(exclude={"name", "platform"}),
    )
    if not account:
        raise HTTPException(404, "Không tìm thấy account.")
    return public_account(account)


@router.patch("/accounts/{account_id}/enabled")
async def enable_account(account_id: str, body: EnabledUpdate, request: Request) -> dict[str, Any]:
    account = await asyncio.to_thread(
        services(request).accounts.set_enabled, account_id, body.enabled, body.reason
    )
    if not account:
        raise HTTPException(404, "Không tìm thấy account.")
    return public_account(account)


@router.patch("/accounts/{account_id}/routing-preference")
async def update_account_routing(
    account_id: str, body: RoutingPreferenceUpdate, request: Request,
) -> dict[str, Any]:
    try:
        account = await asyncio.to_thread(
            services(request).accounts.set_routing_preference, account_id, body.routing_preference,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not account:
        raise HTTPException(404, "Không tìm thấy account.")
    return public_account(account)


@router.get("/accounts/{account_id}/connections")
async def list_account_connections(account_id: str, request: Request) -> list[dict[str, Any]]:
    svc = services(request)
    if not await asyncio.to_thread(svc.accounts.get, account_id):
        raise HTTPException(404, "Không tìm thấy account.")
    return await asyncio.to_thread(svc.provider_connections.list, account_id=account_id)


@router.get("/connections")
async def list_provider_connections(request: Request) -> list[dict[str, Any]]:
    return await asyncio.to_thread(services(request).provider_connections.list)


@router.post("/accounts/{account_id}/connections/{provider}/authorize")
async def authorize_provider_connection(account_id: str, provider: str, request: Request) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(services(request).provider_accounts.authorize_url, account_id, provider)
    except KeyError as exc:
        raise HTTPException(404, "Không tìm thấy account.") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete("/accounts/{account_id}/connections/{connection_id}")
async def delete_provider_connection(account_id: str, connection_id: str, request: Request) -> dict[str, bool]:
    deleted = await asyncio.to_thread(
        services(request).provider_connections.delete, connection_id, account_id=account_id,
    )
    if not deleted:
        raise HTTPException(404, "Không tìm thấy kết nối API.")
    return {"deleted": True}


@router.get("/oauth/youtube/callback")
async def youtube_oauth_callback(code: str, state: str, request: Request) -> dict[str, Any]:
    try:
        connection = await services(request).provider_accounts.youtube_callback(code, state)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.warning("YouTube OAuth callback failed: %s", exc)
        raise HTTPException(409, f"Không thể kết nối YouTube: {exc}") from exc
    return {
        "connected": True,
        "provider": "youtube",
        "account_id": connection["account_id"],
        "channel_title": connection.get("channel_title"),
        "message": "Đã kết nối YouTube API. Bạn có thể đóng tab này và quay lại Tinix Social Hub.",
    }


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: str, request: Request, delete_profile: bool = Query(default=False),
) -> dict[str, Any]:
    svc = services(request)
    account = await asyncio.to_thread(svc.accounts.get, account_id)
    if not account:
        raise HTTPException(404, "Không tìm thấy account.")
    profile_path = (svc.settings.chrome_profile_dir / account["profile_key"]).resolve()
    profile_root = svc.settings.chrome_profile_dir.resolve()
    backup_path = (svc.settings.backup_dir / "chrome_profiles" / account_id).resolve()
    backup_root = (svc.settings.backup_dir / "chrome_profiles").resolve()
    if profile_path.parent != profile_root or backup_path.parent != backup_root:
        raise HTTPException(409, "Đường dẫn profile hoặc backup không hợp lệ.")
    await asyncio.to_thread(svc.chrome.close, account_id)
    deleted = await asyncio.to_thread(svc.accounts.delete_if_safe, account_id)
    if not deleted:
        raise HTTPException(409, "Account đang có Page hoặc lịch sử job; hãy tắt account thay vì xóa.")
    profile_deleted = False
    backup_deleted = False
    cleanup_warning = ""
    if delete_profile:
        try:
            if profile_path.exists():
                await asyncio.to_thread(shutil.rmtree, profile_path)
                profile_deleted = True
            if backup_path.exists():
                await asyncio.to_thread(shutil.rmtree, backup_path)
                backup_deleted = True
        except OSError as exc:
            cleanup_warning = f"Account đã xóa nhưng không thể xóa hết dữ liệu profile: {exc}"
            logger.warning("Account profile cleanup incomplete: account=%s error=%s", account_id, exc)
    return {
        "deleted": True, "profile_deleted": profile_deleted,
        "backup_deleted": backup_deleted, "cleanup_warning": cleanup_warning,
    }


@router.post("/accounts/{account_id}/check-login")
async def check_account_login(account_id: str, request: Request) -> dict[str, Any]:
    try:
        svc = services(request)
        account = await asyncio.to_thread(svc.accounts.get, account_id)
        if not account:
            raise KeyError(account_id)
        handler = svc.facebook_accounts if account["platform"] == "facebook" else svc.platform_accounts
        return await handler.check_login(account_id)
    except KeyError as exc:
        raise HTTPException(404, "Không tìm thấy account.") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/accounts/{account_id}/sync-pages")
async def sync_facebook_pages(account_id: str, request: Request) -> list[dict[str, Any]]:
    try:
        svc = services(request)
        account = await asyncio.to_thread(svc.accounts.get, account_id)
        if not account:
            raise KeyError(account_id)
        if account["platform"] == "facebook":
            return await svc.facebook_accounts.sync_pages(account_id)
        return await svc.platform_accounts.sync_targets(account_id)
    except KeyError as exc:
        raise HTTPException(404, "Không tìm thấy account.") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/accounts/{account_id}/sync-targets")
async def sync_platform_targets(account_id: str, request: Request) -> list[dict[str, Any]]:
    return await sync_facebook_pages(account_id, request)


async def _profile_operation(request: Request, account_id: str, method: str, *args: Any) -> dict[str, Any]:
    from app.services.profile_transfer import ProfileTransferError
    svc = services(request)
    try:
        # Mutating requests are already serialized by ``serialize_mutating_requests``
        # in app.main. Acquiring the same non-reentrant asyncio.Lock here deadlocks.
        logger.info("Profile operation started: %s account=%s", method, account_id)
        result = await asyncio.to_thread(getattr(svc.profile_transfer, method), account_id, *args)
        logger.info("Profile operation completed: %s account=%s", method, account_id)
        return result
    except KeyError as exc:
        raise HTTPException(404, "Không tìm thấy account.") from exc
    except (ProfileTransferError, RuntimeError, ValueError, OSError) as exc:
        logger.warning("Profile operation failed: %s account=%s error=%s", method, account_id, exc)
        raise HTTPException(409, str(exc)) from exc


@router.get("/accounts/{account_id}/profile/backups")
async def list_profile_backups(account_id: str, request: Request) -> list[dict[str, Any]]:
    try:
        return await asyncio.to_thread(services(request).profile_transfer.list_backups, account_id)
    except KeyError as exc:
        raise HTTPException(404, "Không tìm thấy account.") from exc


@router.get("/accounts/{account_id}/profile/history")
async def profile_operation_history(account_id: str, request: Request) -> list[dict[str, Any]]:
    try:
        return await asyncio.to_thread(services(request).profile_transfer.history, account_id)
    except KeyError as exc:
        raise HTTPException(404, "Không tìm thấy account.") from exc


@router.post("/accounts/{account_id}/profile/import")
async def import_profile(account_id: str, body: ProfileImportRequest, request: Request) -> dict[str, Any]:
    return await _profile_operation(request, account_id, "import_profile", body.source_path)


@router.post("/profiles/import")
async def import_profile_bundle(body: ProfileBundleImportRequest, request: Request) -> dict[str, Any]:
    from app.services.profile_transfer import ProfileTransferError
    svc = services(request)
    try:
        logger.info("Profile bundle import started: %s", body.bundle_path)
        result = await asyncio.to_thread(svc.profile_transfer.import_all_profiles, body.bundle_path)
        if "accounts" in result:
            result["accounts"] = [public_account(account) for account in result["accounts"]]
        logger.info("Profile bundle import completed: accounts=%s", result.get("accounts_imported", 0))
        return result
    except (ProfileTransferError, RuntimeError, ValueError, OSError) as exc:
        logger.warning("Profile bundle import failed: %s error=%s", body.bundle_path, exc)
        raise HTTPException(409, str(exc)) from exc


@router.post("/profiles/export")
async def export_all_profiles(request: Request) -> dict[str, Any]:
    from app.services.profile_transfer import ProfileTransferError
    svc = services(request)
    try:
        logger.info("Profile bundle export started")
        result = await asyncio.to_thread(svc.profile_transfer.export_all_profiles)
        logger.info("Profile bundle export completed: accounts=%s", result.get("accounts_exported", 0))
        return result
    except (ProfileTransferError, RuntimeError, ValueError, OSError) as exc:
        logger.warning("Profile bundle export failed: %s", exc)
        raise HTTPException(409, str(exc)) from exc


@router.get("/profiles/cleanup-preview")
async def preview_profile_cleanup(request: Request) -> dict[str, Any]:
    from app.services.profile_transfer import ProfileTransferError
    try:
        return await asyncio.to_thread(services(request).profile_transfer.profile_cleanup_preview)
    except (ProfileTransferError, RuntimeError, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/profiles/cleanup")
async def cleanup_profiles(request: Request) -> dict[str, Any]:
    from app.services.profile_transfer import ProfileTransferError
    svc = services(request)
    try:
        logger.info("Profile cleanup started")
        result = await asyncio.to_thread(svc.profile_transfer.cleanup_profiles)
        logger.info(
            "Profile cleanup completed: profiles=%s bytes=%s",
            result.get("profiles_cleaned", 0),
            result.get("bytes_freed", 0),
        )
        return result
    except (ProfileTransferError, RuntimeError, ValueError, OSError) as exc:
        logger.warning("Profile cleanup failed: %s", exc)
        raise HTTPException(409, str(exc)) from exc


@router.post("/accounts/{account_id}/profile/export")
async def export_profile(account_id: str, request: Request) -> dict[str, Any]:
    return await _profile_operation(request, account_id, "export_profile")


@router.post("/accounts/{account_id}/profile/backup")
async def backup_profile(account_id: str, request: Request) -> dict[str, Any]:
    return await _profile_operation(request, account_id, "backup_profile")


@router.post("/accounts/{account_id}/profile/restore")
async def restore_profile(account_id: str, body: ProfileRestoreRequest, request: Request) -> dict[str, Any]:
    return await _profile_operation(request, account_id, "restore_profile", body.backup_name)


@router.get("/targets")
async def list_targets(
    request: Request,
    account_id: str | None = None,
    search: str | None = Query(default=None, max_length=100),
    enabled: bool | None = None,
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(services(request).targets.list, account_id, search, enabled)


@router.patch("/targets/{target_id}/enabled")
async def enable_target(target_id: str, body: EnabledUpdate, request: Request) -> dict[str, Any]:
    target = await asyncio.to_thread(services(request).targets.set_enabled, target_id, body.enabled)
    if not target:
        raise HTTPException(404, "Không tìm thấy Page.")
    return target


@router.post("/targets/{target_id}/chrome/open")
async def open_target_in_chrome(target_id: str, request: Request) -> dict[str, Any]:
    try:
        return await services(request).platform_accounts.open_target(target_id)
    except KeyError as exc:
        raise HTTPException(404, "Không tìm thấy Page/Kênh.") from exc
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/targets/{target_id}/posting-slots")
async def list_posting_slots(target_id: str, request: Request) -> list[dict[str, Any]]:
    if not await asyncio.to_thread(services(request).targets.get, target_id):
        raise HTTPException(404, "Không tìm thấy kênh.")
    return await asyncio.to_thread(services(request).posting_slots.list, target_id)


@router.put("/targets/{target_id}/posting-slots")
async def replace_posting_slots(
    target_id: str, body: PostingSlotsUpdate, request: Request
) -> list[dict[str, Any]]:
    try:
        return await asyncio.to_thread(
            services(request).posting_slots.replace,
            target_id, body.timezone, [item.model_dump() for item in body.slots],
        )
    except KeyError as exc:
        raise HTTPException(404, "Không tìm thấy kênh.") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/targets/{target_id}/next-slot")
async def next_posting_slot(
    target_id: str, request: Request, after: datetime | None = None
) -> dict[str, str]:
    try:
        result = await asyncio.to_thread(services(request).posting_slots.find_next, target_id, after)
        return {"scheduled_at": result.isoformat()}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/target-groups")
async def list_target_groups(request: Request) -> list[dict[str, Any]]:
    return await asyncio.to_thread(services(request).targets.list_groups)


@router.post("/target-groups", status_code=201)
async def create_target_group(body: TargetGroupCreate, request: Request) -> dict[str, Any]:
    return await asyncio.to_thread(services(request).targets.create_group, body.name, body.description)


@router.put("/target-groups/{group_id}/members")
async def set_target_group_members(group_id: str, body: TargetGroupMembers, request: Request) -> dict[str, Any]:
    group = await asyncio.to_thread(services(request).targets.set_group_members, group_id, body.target_ids)
    if not group:
        raise HTTPException(404, "Không tìm thấy nhóm Page.")
    return group


@router.get("/jobs")
async def list_jobs(request: Request, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> list[dict[str, Any]]:
    return await asyncio.to_thread(services(request).jobs.list, limit, offset)


@router.get("/publication-plans")
async def list_publication_plans(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(services(request).publications.list_plans, limit, offset)


@router.get("/publication-plans/{plan_id}")
async def get_publication_plan(plan_id: str, request: Request) -> dict[str, Any]:
    plan = await asyncio.to_thread(services(request).publications.get_plan, plan_id)
    if not plan:
        raise HTTPException(404, "Không tìm thấy publication plan.")
    return plan


@router.get("/publication-releases")
async def list_publication_releases(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    platform: str | None = None,
    status: str | None = None,
    limit: int = Query(500, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(
        services(request).publications.list_releases,
        start=start, end=end, platform=platform, status=status, limit=limit,
    )


@router.patch("/publication-releases/{release_id}/schedule")
async def reschedule_publication_release(
    release_id: str, body: ReleaseReschedule, request: Request
) -> dict[str, Any]:
    try:
        services(request).posting_slots.validate_timezone(body.timezone)
        return await asyncio.to_thread(
            services(request).publications.reschedule_release,
            release_id, body.scheduled_at.isoformat(), body.timezone,
        )
    except KeyError as exc:
        raise HTTPException(404, "Không tìm thấy release.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/publication-releases/{release_id}/events")
async def publication_release_events(release_id: str, request: Request) -> list[dict[str, Any]]:
    if not await asyncio.to_thread(services(request).publications.get_release, release_id):
        raise HTTPException(404, "Không tìm thấy release.")
    return await asyncio.to_thread(services(request).publications.release_events, release_id)


@router.get("/publication-releases/{release_id}")
async def publication_release_detail(release_id: str, request: Request) -> dict[str, Any]:
    release = await asyncio.to_thread(services(request).publications.release_detail, release_id)
    if not release:
        raise HTTPException(404, "Không tìm thấy release.")
    return release


@router.patch("/publication-releases/{release_id}/connect")
async def connect_publication_release(
    release_id: str, body: ReleaseConnect, request: Request
) -> dict[str, Any]:
    release = await asyncio.to_thread(services(request).publications.get_release, release_id)
    if not release:
        raise HTTPException(404, "Không tìm thấy release.")
    from app.services.ui_analytics import AnalyticsCollectionError
    try:
        services(request).analytics_collector._validate_url(release["platform"], body.external_url)
        return await asyncio.to_thread(
            services(request).analytics.connect_release, release_id, body.external_url, body.note
        )
    except AnalyticsCollectionError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/publication-releases/{release_id}/collect-metrics")
async def collect_release_metrics(release_id: str, request: Request) -> dict[str, Any]:
    from app.services.ui_analytics import AnalyticsCollectionError
    try:
        return await services(request).analytics_collector.collect(release_id)
    except KeyError as exc:
        raise HTTPException(404, "Không tìm thấy release.") from exc
    except AnalyticsCollectionError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/publication-releases/{release_id}/metrics")
async def release_metrics(release_id: str, request: Request) -> dict[str, Any]:
    if not await asyncio.to_thread(services(request).publications.get_release, release_id):
        raise HTTPException(404, "Không tìm thấy release.")
    metrics, runs = await asyncio.gather(
        asyncio.to_thread(services(request).analytics.for_release, release_id),
        asyncio.to_thread(services(request).analytics.runs, release_id),
    )
    return {"metrics": metrics, "fetch_runs": runs}


@router.get("/analytics/summary")
async def analytics_summary(
    request: Request, days: int = Query(30, ge=7, le=90), platform: str | None = None
) -> dict[str, Any]:
    return await asyncio.to_thread(services(request).analytics.summary, days, platform)


@router.post("/jobs", status_code=201)
async def create_job(body: JobCreate, request: Request) -> dict[str, Any]:
    svc = services(request)
    if body.kind == "publish" and not body.account_id:
        raise HTTPException(422, "Job publish cần account_id.")
    if body.account_id and not await asyncio.to_thread(svc.accounts.get, body.account_id):
        raise HTTPException(404, "Không tìm thấy account.")
    scheduled_at = body.scheduled_at.astimezone(timezone.utc).isoformat() if body.scheduled_at else None
    try:
        job = await asyncio.to_thread(
            svc.jobs.create, body.kind, body.payload, body.account_id, scheduled_at, dry_run=body.dry_run
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    svc.worker.notify()
    return job


@router.get("/jobs/{job_id}")
async def job_detail(job_id: str, request: Request) -> dict[str, Any]:
    job = await asyncio.to_thread(services(request).jobs.detail, job_id)
    if not job:
        raise HTTPException(404, "Không tìm thấy job.")
    return job


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, request: Request) -> dict[str, Any]:
    try:
        job = await asyncio.to_thread(services(request).jobs.retry, job_id)
        services(request).worker.notify()
        return job
    except KeyError as exc:
        raise HTTPException(404, "Không tìm thấy job.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/jobs/{job_id}/finalize")
async def finalize_job(job_id: str, body: JobFinalize, request: Request) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            services(request).jobs.finalize_unknown, job_id, body.succeeded, body.note, body.post_url
        )
    except KeyError as exc:
        raise HTTPException(404, "Không tìm thấy job.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/jobs/retry-bulk")
async def retry_jobs_bulk(body: BulkRetry, request: Request) -> dict[str, Any]:
    jobs = [await asyncio.to_thread(services(request).jobs.get, item) for item in dict.fromkeys(body.job_ids)]
    eligible = [item["id"] for item in jobs if item and item["status"] in {"temporary_failure", "permanent_failure", "login_required", "checkpoint"} and not item["commit_reached_at"]]
    blocked = [item for item in body.job_ids if item not in eligible]
    if not body.preview:
        for job_id in eligible:
            await asyncio.to_thread(services(request).jobs.retry, job_id)
        services(request).worker.notify()
    return {"preview": body.preview, "eligible": eligible, "blocked": blocked, "count": len(eligible)}


def _artifact_file_stats(settings: Any, artifacts: list[dict[str, Any]]) -> tuple[int, list[Path]]:
    root = settings.screenshot_dir.resolve()
    total = 0
    files: list[Path] = []
    for artifact in artifacts:
        candidate = (root / artifact["relative_path"]).resolve()
        if root not in candidate.parents or candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            total += candidate.stat().st_size
            files.append(candidate)
        except OSError:
            continue
    return total, files


@router.post("/jobs/history/cleanup")
async def cleanup_job_history(body: JobHistoryCleanup, request: Request) -> dict[str, Any]:
    svc = services(request)
    before: str | None = None
    after: str | None = None
    selected_ids: list[str] | None = None
    if body.mode == "older_than":
        if body.older_than_days is None:
            raise HTTPException(422, "Hãy chọn số ngày cần giữ lại.")
        before = (datetime.now(timezone.utc) - timedelta(days=body.older_than_days)).isoformat()
    elif body.mode == "custom":
        if body.from_date is None or body.to_date is None:
            raise HTTPException(422, "Hãy chọn đầy đủ ngày bắt đầu và kết thúc.")
        start = body.from_date.astimezone(timezone.utc)
        end = body.to_date.astimezone(timezone.utc)
        if start > end:
            raise HTTPException(422, "Ngày bắt đầu phải trước ngày kết thúc.")
        after, before = start.isoformat(), end.isoformat()
    elif body.mode == "selected":
        if not body.job_ids:
            raise HTTPException(422, "Hãy chọn ít nhất một tác vụ trong bảng.")
        selected_ids = body.job_ids

    try:
        candidates = await asyncio.to_thread(
            svc.jobs.history_candidates,
            before=before,
            after=after,
            status_filter=body.status_filter,
            job_ids=selected_ids,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    candidate_ids = [job["id"] for job in candidates["jobs"]]
    artifact_bytes, _ = await asyncio.to_thread(
        _artifact_file_stats, svc.settings, candidates["artifacts"]
    )
    if body.preview:
        return {
            "preview": True,
            "count": len(candidate_ids),
            "candidate_ids": candidate_ids,
            "artifact_count": len(candidates["artifacts"]),
            "artifact_bytes": artifact_bytes,
            "blocked_active": candidates["blocked_active"],
        }
    if not body.confirm:
        raise HTTPException(409, "Cần xác nhận lần cuối trước khi xóa lịch sử.")
    expected = list(dict.fromkeys(body.candidate_ids))
    if not expected:
        raise HTTPException(409, "Hãy xem trước phạm vi trước khi xóa.")
    # Delete only the immutable preview set, while rechecking active statuses.
    current = set(candidate_ids)
    approved_ids = [job_id for job_id in expected if job_id in current]
    deleted = await asyncio.to_thread(svc.jobs.delete_history, approved_ids)
    removed_files = 0
    removed_bytes = 0
    if body.delete_artifacts:
        _, files = await asyncio.to_thread(_artifact_file_stats, svc.settings, deleted["artifacts"])
        for path in files:
            try:
                size = path.stat().st_size
                path.unlink()
                removed_files += 1
                removed_bytes += size
                try:
                    path.parent.rmdir()
                except OSError:
                    pass
            except OSError:
                logger.warning("Không thể xóa artifact lịch sử %s", path)
    return {
        "preview": False,
        "deleted": deleted["deleted"],
        "removed_artifacts": removed_files,
        "removed_bytes": removed_bytes,
        "blocked_active": max(deleted["blocked_active"], candidates["blocked_active"]),
        "skipped_changed": len(expected) - len(approved_ids),
    }


@router.get("/notifications")
async def list_notifications(
    request: Request, unread_only: bool = False, limit: int = Query(100, ge=1, le=500)
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(services(request).notifications.list, unread_only, limit)


@router.post("/notifications/{notification_id}/read")
async def read_notification(notification_id: str, request: Request) -> dict[str, bool]:
    marked = await asyncio.to_thread(services(request).notifications.mark_read, notification_id)
    if not marked:
        raise HTTPException(404, "Không tìm thấy thông báo.")
    return {"read": True}


@router.post("/notifications/read-all")
async def read_all_notifications(request: Request) -> dict[str, int]:
    return {"read": await asyncio.to_thread(services(request).notifications.mark_all_read)}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request) -> dict[str, bool]:
    cancelled = await asyncio.to_thread(services(request).jobs.cancel, job_id)
    if not cancelled:
        raise HTTPException(409, "Job không tồn tại hoặc đã kết thúc.")
    services(request).worker.cancel(job_id)
    return {"cancelled": True}


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request) -> list[dict[str, Any]]:
    if not await asyncio.to_thread(services(request).jobs.get, job_id):
        raise HTTPException(404, "Không tìm thấy job.")
    return await asyncio.to_thread(services(request).jobs.events, job_id)


@router.get("/jobs/{job_id}/artifacts")
async def job_artifacts(job_id: str, request: Request) -> list[dict[str, Any]]:
    if not await asyncio.to_thread(services(request).jobs.get, job_id):
        raise HTTPException(404, "Không tìm thấy job.")
    return await asyncio.to_thread(services(request).jobs.artifacts, job_id)


@router.get("/chrome")
async def chrome_status(request: Request) -> Any:
    return await asyncio.to_thread(services(request).chrome.status)


@router.post("/accounts/{account_id}/chrome/open")
async def open_chrome(account_id: str, request: Request) -> dict[str, Any]:
    svc = services(request)
    account = await asyncio.to_thread(svc.accounts.get, account_id)
    if not account:
        raise HTTPException(404, "Không tìm thấy account.")
    try:
        return await asyncio.to_thread(svc.chrome.open, account)
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/accounts/{account_id}/chrome/close")
async def close_chrome(account_id: str, request: Request) -> dict[str, bool]:
    return {"closed": await asyncio.to_thread(services(request).chrome.close, account_id)}


@router.post("/chrome/close-all")
async def close_all_chrome(request: Request) -> dict[str, int]:
    return {"closed": await asyncio.to_thread(services(request).chrome.close_all)}


@router.get("/database/integrity")
async def database_integrity(request: Request) -> dict[str, Any]:
    return await asyncio.to_thread(services(request).database.integrity_check)


@router.get("/database/backups")
async def list_backups(request: Request) -> list[dict[str, Any]]:
    return await asyncio.to_thread(services(request).database.list_backups)


@router.post("/database/backups")
async def create_backup(request: Request) -> dict[str, str]:
    path = await asyncio.to_thread(services(request).database.create_backup)
    return {"name": path.name}


@router.post("/database/restore")
async def restore_backup(body: RestoreRequest, request: Request) -> dict[str, bool]:
    svc = services(request)
    async with svc.scheduler.maintenance_lock:
        try:
            await svc.worker.pause()
            await asyncio.to_thread(svc.database.restore_backup, body.name)
        except TimeoutError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            svc.worker.resume()
    return {"restored": True}


@router.post("/maintenance/run")
async def run_maintenance(request: Request) -> dict[str, Any]:
    maintenance = getattr(services(request), "maintenance", None)
    if not maintenance:
        raise HTTPException(503, "Maintenance service không khả dụng.")
    return await asyncio.to_thread(maintenance.run_once)


@router.get("/settings/profile-cleanup")
async def get_profile_cleanup_settings(request: Request) -> dict[str, Any]:
    maintenance = getattr(services(request), "maintenance", None)
    if not maintenance:
        raise HTTPException(503, "Maintenance service không khả dụng.")
    return await asyncio.to_thread(maintenance.profile_cleanup_settings)


@router.put("/settings/profile-cleanup")
async def update_profile_cleanup_settings(
    body: ProfileAutoCleanupSettings, request: Request,
) -> dict[str, Any]:
    maintenance = getattr(services(request), "maintenance", None)
    if not maintenance:
        raise HTTPException(503, "Maintenance service không khả dụng.")
    return await asyncio.to_thread(
        maintenance.update_profile_cleanup_settings, body.enabled, body.threshold_gb
    )
