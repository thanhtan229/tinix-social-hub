from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.services.ai import AIError, PlatformVariant
from app.db.content_repositories import ContentInUseError
from app.services.media import MediaValidationError
from app.services.scheduling import SchedulingError


router = APIRouter(prefix="/api")


def services(request: Request) -> Any:
    return request.app.state.services


class BrandProfileBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    products_services: str | None = None
    target_audience: str | None = None
    tone: str | None = None
    pronouns: str | None = None
    preferred_keywords: list[str] = Field(default_factory=list, max_length=100)
    forbidden_keywords: list[str] = Field(default_factory=list, max_length=100)
    sample_ctas: list[str] = Field(default_factory=list, max_length=50)
    website: str | None = None
    contact_info: str | None = None
    hashtag_rules: str | None = None
    good_examples: list[str] = Field(default_factory=list, max_length=30)


class ContentBody(BaseModel):
    brand_profile_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    topic: str | None = None
    summary: str | None = None
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list, max_length=100)
    cta: str | None = None
    platform_variants: dict[str, PlatformVariant] = Field(default_factory=dict)


class ApprovalDecision(BaseModel):
    approved: bool
    note: str | None = Field(default=None, max_length=1000)


class AIGenerateBody(BaseModel):
    operation: str = Field(default="write", pattern="^(write|rewrite|shorten|expand|hook|cta|hashtags|variants|cross_platform|video_script|connection_test)$")
    brief: str = Field(min_length=1, max_length=12000)
    brand_profile_id: str | None = None
    platforms: list[str] = Field(default_factory=lambda: ["facebook"], min_length=1, max_length=4)
    save_draft: bool = True


class ScheduleBody(BaseModel):
    content_id: str
    account_id: str
    target_ids: list[str] = Field(min_length=1, max_length=100)
    scheduled_at: datetime | None = None
    dry_run: bool = True
    delay_seconds: int = Field(default=0, ge=0, le=86400)
    random_delay_seconds: int = Field(default=0, ge=0, le=3600)
    missed_policy: str = Field(default="confirm", pattern="^(publish|skip|confirm)$")
    content_format: str = Field(default="post", min_length=1, max_length=50)
    platform_settings: dict[str, Any] = Field(default_factory=dict)


@router.get("/brand-profiles")
async def list_brands(request: Request) -> list[dict[str, Any]]:
    return await asyncio.to_thread(services(request).brands.list)


@router.post("/brand-profiles", status_code=201)
async def create_brand(body: BrandProfileBody, request: Request) -> dict[str, Any]:
    return await asyncio.to_thread(services(request).brands.create, body.model_dump())


@router.put("/brand-profiles/{profile_id}")
async def update_brand(profile_id: str, body: BrandProfileBody, request: Request) -> dict[str, Any]:
    profile = await asyncio.to_thread(services(request).brands.update, profile_id, body.model_dump())
    if not profile:
        raise HTTPException(404, "Không tìm thấy Brand Profile.")
    return profile


@router.get("/contents")
async def list_contents(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, max_length=100),
    status: str | None = None,
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(services(request).contents.list, limit, offset, search, status)


@router.get("/contents/{content_id}")
async def get_content(content_id: str, request: Request) -> dict[str, Any]:
    content = await asyncio.to_thread(services(request).contents.get, content_id)
    if not content:
        raise HTTPException(404, "Không tìm thấy content.")
    return content


@router.post("/contents", status_code=201)
async def create_content(body: ContentBody, request: Request) -> dict[str, Any]:
    return await asyncio.to_thread(services(request).contents.create, body.model_dump(mode="json"))


@router.put("/contents/{content_id}")
async def update_content(content_id: str, body: ContentBody, request: Request) -> dict[str, Any]:
    content = await asyncio.to_thread(services(request).contents.update, content_id, body.model_dump(mode="json"))
    if not content:
        raise HTTPException(404, "Không tìm thấy content.")
    return content


@router.post("/contents/{content_id}/duplicate", status_code=201)
async def duplicate_content(content_id: str, request: Request) -> dict[str, Any]:
    content = await asyncio.to_thread(services(request).contents.duplicate, content_id)
    if not content:
        raise HTTPException(404, "Không tìm thấy content.")
    return content


@router.delete("/contents/{content_id}")
async def delete_content(content_id: str, request: Request, delete_files: bool = False) -> dict[str, Any]:
    svc = services(request)
    try:
        paths = await asyncio.to_thread(svc.contents.delete, content_id)
    except ContentInUseError as exc:
        raise HTTPException(409, str(exc)) from exc
    if paths is None:
        raise HTTPException(404, "Không tìm thấy content.")
    deleted_files = await asyncio.to_thread(svc.media.delete_managed, paths) if delete_files else 0
    return {"deleted": True, "files_deleted": deleted_files, "files_retained": 0 if delete_files else len(paths)}


@router.get("/contents/{content_id}/revisions")
async def content_revisions(content_id: str, request: Request) -> list[dict[str, Any]]:
    return await asyncio.to_thread(services(request).contents.revisions, content_id)


@router.post("/contents/{content_id}/revisions/{revision_id}/restore")
async def restore_content_revision(content_id: str, revision_id: str, request: Request) -> dict[str, Any]:
    content = await asyncio.to_thread(services(request).contents.restore_revision, content_id, revision_id)
    if not content:
        raise HTTPException(404, "Không tìm thấy revision.")
    return content


@router.post("/contents/{content_id}/request-approval")
async def request_content_approval(content_id: str, request: Request) -> dict[str, Any]:
    approval = await asyncio.to_thread(services(request).contents.request_approval, content_id)
    if not approval:
        raise HTTPException(404, "Không tìm thấy content.")
    return approval


@router.post("/approvals/{approval_id}/decide")
async def decide_content_approval(approval_id: str, body: ApprovalDecision, request: Request) -> dict[str, Any]:
    approval = await asyncio.to_thread(
        services(request).contents.decide_approval, approval_id, body.approved, body.note
    )
    if not approval:
        raise HTTPException(409, "Approval không tồn tại hoặc đã được quyết định.")
    return approval


@router.post("/contents/{content_id}/media", status_code=201)
async def upload_content_media(
    content_id: str,
    request: Request,
    file: UploadFile = File(...),
    sort_order: int = Form(0),
) -> dict[str, Any]:
    svc = services(request)
    if not await asyncio.to_thread(svc.contents.get, content_id):
        raise HTTPException(404, "Không tìm thấy content.")
    try:
        return await asyncio.to_thread(
            svc.media.save_upload, content_id, file.file, file.filename or "upload", file.content_type, sort_order
        )
    except MediaValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/media/{relative_path:path}", include_in_schema=False)
async def serve_media(relative_path: str, request: Request) -> FileResponse:
    try:
        path = await asyncio.to_thread(services(request).media.resolve_existing, relative_path)
    except (FileNotFoundError, MediaValidationError) as exc:
        raise HTTPException(404, "Không tìm thấy media.") from exc
    return FileResponse(path)


@router.post("/ai/generate")
async def generate_ai_content(body: AIGenerateBody, request: Request) -> dict[str, Any]:
    try:
        return await services(request).ai_studio.generate(
            body.operation, body.brief, body.brand_profile_id, body.platforms, body.save_draft
        )
    except AIError as exc:
        status = 503 if exc.retryable else 422
        raise HTTPException(status, {"code": exc.code, "message": str(exc)}) from exc


@router.post("/schedules", status_code=201)
async def create_schedule(body: ScheduleBody, request: Request) -> list[dict[str, Any]]:
    try:
        jobs = await asyncio.to_thread(
            services(request).scheduling.schedule,
            body.content_id, body.account_id, body.target_ids, body.scheduled_at,
            body.dry_run, body.delay_seconds, body.random_delay_seconds, body.missed_policy,
            body.content_format, body.platform_settings,
        )
        services(request).worker.notify()
        return jobs
    except SchedulingError as exc:
        raise HTTPException(422, str(exc)) from exc
