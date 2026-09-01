from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app import __version__


router = APIRouter(prefix="/api")


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    platform: str = Field(min_length=1, max_length=40)


class JobCreate(BaseModel):
    kind: str = Field(pattern="^(publish|ai_content)$")
    account_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    scheduled_at: datetime | None = None


class RestoreRequest(BaseModel):
    name: str


def services(request: Request) -> Any:
    return request.app.state.services


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    svc = services(request)
    integrity = await asyncio.to_thread(svc.database.integrity_check)
    usage = shutil.disk_usage(svc.settings.data_dir)
    chrome = svc.chrome.status()
    return {
        "status": "ok" if integrity["ok"] else "degraded",
        "version": __version__,
        "backend": "running",
        "worker": {"state": svc.worker.state, "active_jobs": svc.worker.active_count},
        "scheduler": svc.scheduler.state,
        "database": integrity,
        "chrome": {"running": len(chrome), "limit": svc.settings.max_chrome},
        "disk": {"free_bytes": usage.free, "total_bytes": usage.total},
        "ai_configured": svc.ai.configured,
    }


@router.get("/accounts")
async def list_accounts(request: Request) -> list[dict[str, Any]]:
    return await asyncio.to_thread(services(request).accounts.list)


@router.post("/accounts", status_code=201)
async def create_account(body: AccountCreate, request: Request) -> dict[str, Any]:
    return await asyncio.to_thread(services(request).accounts.create, body.name, body.platform)


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
    job = await asyncio.to_thread(svc.jobs.create, body.kind, body.payload, body.account_id, scheduled_at)
    svc.worker.notify()
    return job


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request) -> dict[str, bool]:
    cancelled = await asyncio.to_thread(services(request).jobs.cancel, job_id)
    if not cancelled:
        raise HTTPException(409, "Job không tồn tại hoặc đã kết thúc.")
    services(request).worker.cancel(job_id)
    return {"cancelled": True}


@router.get("/chrome")
async def chrome_status(request: Request) -> Any:
    return services(request).chrome.status()


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
