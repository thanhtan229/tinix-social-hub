from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
import psutil

from app import __version__


router = APIRouter(prefix="/api")


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    platform: str = Field(min_length=1, max_length=40)


class AccountUpdate(AccountCreate):
    pass


class EnabledUpdate(BaseModel):
    enabled: bool
    reason: str | None = Field(default=None, max_length=500)


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


def services(request: Request) -> Any:
    return request.app.state.services


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    svc = services(request)
    integrity = await asyncio.to_thread(svc.database.ping)
    usage = shutil.disk_usage(svc.settings.data_dir)
    chrome = await asyncio.to_thread(svc.chrome.status)
    memory = psutil.virtual_memory()
    process_memory = psutil.Process().memory_info().rss
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
        "maintenance": {
            "state": getattr(maintenance, "state", "unavailable"),
            "last_result": getattr(maintenance, "last_result", None),
        },
    }


@router.get("/accounts")
async def list_accounts(request: Request) -> list[dict[str, Any]]:
    return await asyncio.to_thread(services(request).accounts.list)


@router.post("/accounts", status_code=201)
async def create_account(body: AccountCreate, request: Request) -> dict[str, Any]:
    if body.platform.lower() not in {"facebook", "instagram", "tiktok", "youtube"}:
        raise HTTPException(422, "Nền tảng không được hỗ trợ.")
    return await asyncio.to_thread(services(request).accounts.create, body.name, body.platform)


@router.put("/accounts/{account_id}")
async def update_account(account_id: str, body: AccountUpdate, request: Request) -> dict[str, Any]:
    account = await asyncio.to_thread(services(request).accounts.update, account_id, body.name, body.platform)
    if not account:
        raise HTTPException(404, "Không tìm thấy account.")
    return account


@router.patch("/accounts/{account_id}/enabled")
async def enable_account(account_id: str, body: EnabledUpdate, request: Request) -> dict[str, Any]:
    account = await asyncio.to_thread(
        services(request).accounts.set_enabled, account_id, body.enabled, body.reason
    )
    if not account:
        raise HTTPException(404, "Không tìm thấy account.")
    return account


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: str, request: Request) -> dict[str, bool]:
    svc = services(request)
    if not await asyncio.to_thread(svc.accounts.get, account_id):
        raise HTTPException(404, "Không tìm thấy account.")
    await asyncio.to_thread(svc.chrome.close, account_id)
    deleted = await asyncio.to_thread(svc.accounts.delete_if_safe, account_id)
    if not deleted:
        raise HTTPException(409, "Account đang có Page hoặc lịch sử job; hãy tắt account thay vì xóa.")
    return {"deleted": True}


@router.post("/accounts/{account_id}/check-login")
async def check_account_login(account_id: str, request: Request) -> dict[str, Any]:
    try:
        return await services(request).facebook_accounts.check_login(account_id)
    except KeyError as exc:
        raise HTTPException(404, "Không tìm thấy account.") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/accounts/{account_id}/sync-pages")
async def sync_facebook_pages(account_id: str, request: Request) -> list[dict[str, Any]]:
    try:
        return await services(request).facebook_accounts.sync_pages(account_id)
    except KeyError as exc:
        raise HTTPException(404, "Không tìm thấy account.") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


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


@router.post("/jobs", status_code=201)
async def create_job(body: JobCreate, request: Request) -> dict[str, Any]:
    svc = services(request)
    if body.kind == "publish" and not body.account_id:
        raise HTTPException(422, "Job publish cần account_id.")
    if body.account_id and not await asyncio.to_thread(svc.accounts.get, body.account_id):
        raise HTTPException(404, "Không tìm thấy account.")
    scheduled_at = body.scheduled_at.astimezone(timezone.utc).isoformat() if body.scheduled_at else None
    job = await asyncio.to_thread(
        svc.jobs.create, body.kind, body.payload, body.account_id, scheduled_at, dry_run=body.dry_run
    )
    svc.worker.notify()
    return job


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
