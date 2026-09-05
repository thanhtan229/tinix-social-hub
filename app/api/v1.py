from __future__ import annotations

import asyncio
import secrets
from datetime import timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.content import ContentBody, ScheduleBody
from app.platforms import PLATFORM_CATALOG
from app.services.scheduling import SchedulingError


router=APIRouter(prefix="/api/v1",tags=["local-automation-v1"])


def svc(request:Request)->Any:return request.app.state.services


def public_account(account:dict[str,Any])->dict[str,Any]:
    hidden={"password","secret_2fa","email_pass","cookie"}
    result={key:value for key,value in account.items() if key not in hidden}
    result.update({
        "has_password":bool(account.get("password")),"has_2fa":bool(account.get("secret_2fa")),
        "has_email_password":bool(account.get("email_pass")),"has_cookie":bool(account.get("cookie")),
    })
    return result


async def authorize(request:Request,scope:str)->dict[str,Any]:
    authorization=request.headers.get("authorization","")
    if not authorization.startswith("Bearer "):
        raise HTTPException(401,"Thiếu Bearer token.",headers={"WWW-Authenticate":"Bearer"})
    token=authorization[7:].strip()
    if not token:raise HTTPException(401,"Bearer token trống.")
    identity=await asyncio.to_thread(svc(request).api_tokens.verify,token,scope)
    if not identity:raise HTTPException(403,f"Token không hợp lệ hoặc thiếu scope {scope}.")
    return identity


class WebhookCreate(BaseModel):
    name:str=Field(min_length=1,max_length=120)
    url:str=Field(min_length=10,max_length=2000)
    events:list[str]=Field(default_factory=lambda:["job.status_changed"],min_length=1,max_length=30)
    secret:str|None=Field(default=None,min_length=16,max_length=500)


@router.get("/health")
async def health(request:Request)->dict[str,Any]:
    await authorize(request,"read")
    return {
        "status":"ok", "api_version":"v1", "transport":"local-http",
        "publication_transport":"chrome",
        "publication_transports":["chrome","official_api"],
    }


@router.get("/platforms")
async def platforms(request:Request)->list[dict[str,object]]:
    await authorize(request,"read");return [item.to_dict() for item in PLATFORM_CATALOG]


@router.get("/accounts")
async def accounts(request:Request)->list[dict[str,Any]]:
    await authorize(request,"read");items=await asyncio.to_thread(svc(request).accounts.list);return [public_account(item) for item in items]


@router.get("/targets")
async def targets(request:Request,account_id:str|None=None)->list[dict[str,Any]]:
    await authorize(request,"read");return await asyncio.to_thread(svc(request).targets.list,account_id)


@router.get("/targets/{target_id}/slots")
async def slots(target_id:str,request:Request)->list[dict[str,Any]]:
    await authorize(request,"read");return await asyncio.to_thread(svc(request).posting_slots.list,target_id)


@router.get("/media")
async def media(request:Request,limit:int=Query(200,ge=1,le=500))->list[dict[str,Any]]:
    await authorize(request,"read");return await asyncio.to_thread(svc(request).media_assets.list,None,None,None,False,limit)


@router.get("/content")
async def content(request:Request,limit:int=Query(100,ge=1,le=200))->list[dict[str,Any]]:
    await authorize(request,"read");return await asyncio.to_thread(svc(request).contents.list,limit)


@router.post("/content",status_code=201)
async def create_content(body:ContentBody,request:Request)->dict[str,Any]:
    await authorize(request,"write");return await asyncio.to_thread(svc(request).contents.create,body.model_dump(mode="json"),"api_v1")


@router.get("/plans")
async def plans(request:Request,limit:int=Query(100,ge=1,le=500))->list[dict[str,Any]]:
    await authorize(request,"read");return await asyncio.to_thread(svc(request).publications.list_plans,limit,0)


@router.post("/plans",status_code=201)
async def create_plan(body:ScheduleBody,request:Request)->list[dict[str,Any]]:
    await authorize(request,"publish" if not body.dry_run else "write")
    try:
        jobs=await asyncio.to_thread(
            svc(request).scheduling.schedule,body.content_id,body.account_id,body.target_ids,
            body.scheduled_at.astimezone(timezone.utc) if body.scheduled_at else None,body.dry_run,
            body.delay_seconds,body.random_delay_seconds,body.missed_policy,body.content_format,body.platform_settings,
            body.routing_preference,
        );svc(request).worker.notify();return jobs
    except SchedulingError as exc:raise HTTPException(409,str(exc)) from exc


@router.get("/releases")
async def releases(request:Request,limit:int=Query(200,ge=1,le=1000))->list[dict[str,Any]]:
    await authorize(request,"read");return await asyncio.to_thread(svc(request).publications.list_releases,limit=limit)


@router.get("/jobs")
async def jobs(request:Request,limit:int=Query(100,ge=1,le=200))->list[dict[str,Any]]:
    await authorize(request,"read");return await asyncio.to_thread(svc(request).jobs.list,limit,0)


@router.post("/jobs/{job_id}/retry")
async def retry(job_id:str,request:Request)->dict[str,Any]:
    await authorize(request,"write")
    try:result=await asyncio.to_thread(svc(request).jobs.retry,job_id);svc(request).worker.notify();return result
    except KeyError as exc:raise HTTPException(404,"Không tìm thấy job.") from exc
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc


@router.post("/jobs/{job_id}/cancel")
async def cancel(job_id:str,request:Request)->dict[str,bool]:
    await authorize(request,"write");cancelled=await asyncio.to_thread(svc(request).jobs.cancel,job_id)
    if not cancelled:raise HTTPException(409,"Job không tồn tại hoặc đã kết thúc.")
    svc(request).worker.cancel(job_id);return {"cancelled":True}


@router.get("/webhooks")
async def webhooks(request:Request)->list[dict[str,Any]]:
    await authorize(request,"read");return await asyncio.to_thread(svc(request).webhooks.list)


@router.post("/webhooks",status_code=201)
async def create_webhook(body:WebhookCreate,request:Request)->dict[str,Any]:
    await authorize(request,"write");parsed=urlparse(body.url)
    if parsed.scheme not in {"http","https"} or not parsed.netloc:raise HTTPException(422,"Webhook URL phải là HTTP(S).")
    allowed={"job.status_changed","*"}
    if not set(body.events)<=allowed:raise HTTPException(422,"Webhook event không được hỗ trợ.")
    return await asyncio.to_thread(svc(request).webhooks.create,body.name,body.url,body.secret or secrets.token_urlsafe(32),body.events)


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(webhook_id:str,request:Request)->dict[str,bool]:
    await authorize(request,"write");deleted=await asyncio.to_thread(svc(request).webhooks.delete,webhook_id)
    if not deleted:raise HTTPException(404,"Không tìm thấy webhook.")
    return {"deleted":True}


@router.get("/webhook-outbox")
async def webhook_outbox(request:Request,limit:int=Query(100,ge=1,le=500))->list[dict[str,Any]]:
    await authorize(request,"read");return await asyncio.to_thread(svc(request).webhooks.outbox,limit)
