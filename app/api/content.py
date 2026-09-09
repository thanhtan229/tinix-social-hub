from __future__ import annotations

import asyncio
import csv
import io
from datetime import datetime
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.services.ai import AIError, PlatformVariant
from app.db.content_repositories import ContentInUseError
from app.db.media_repositories import MediaAssetInUseError
from app.platforms import PLATFORM_CATALOG
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


class BulkDeleteBody(BaseModel):
    content_ids: list[str] = Field(min_length=1, max_length=500)
    force: bool = True
    delete_files: bool = False


class ApprovalDecision(BaseModel):
    approved: bool
    note: str | None = Field(default=None, max_length=1000)


class AIGenerateBody(BaseModel):
    operation: str = Field(default="write", pattern="^(write|rewrite|shorten|expand|hook|cta|hashtags|variants|cross_platform|video_script|connection_test)$")
    brief: str = Field(min_length=1, max_length=12000)
    brand_profile_id: str | None = None
    platforms: list[str] = Field(default_factory=lambda: ["facebook"], min_length=1, max_length=5)
    save_draft: bool = True


class AIGenerateImageBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    content_id: str | None = None


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
    routing_preference: str | None = Field(
        default=None,
        pattern="^(official_api_preferred|chrome_preferred|official_api_only|chrome_only)$",
    )


class MediaAssetUpdate(BaseModel):
    alt_text: str | None = Field(default=None, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    thumbnail_timestamp: float | None = Field(default=None, ge=0)


class MediaAttachBody(BaseModel):
    content_id: str
    sort_order: int = Field(default=0, ge=0, le=1000)
    alt_text: str | None = Field(default=None, max_length=2000)


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


@router.delete("/brand-profiles/{profile_id}")
async def delete_brand(profile_id: str, request: Request) -> dict[str, Any]:
    deleted = await asyncio.to_thread(services(request).brands.delete, profile_id)
    if not deleted:
        raise HTTPException(404, "Không tìm thấy Brand Profile.")
    return {"deleted": True, "profile_id": profile_id}


@router.get("/contents")
async def list_contents(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, max_length=100),
    status: str | None = None,
    platform: str | None = None,
    post_status: str | None = None,
    media_type: str | None = None,
    sort_by: str | None = "newest",
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(
        services(request).contents.list,
        limit, offset, search, status, platform, post_status, media_type, sort_by,
    )


@router.get("/contents/export")
async def export_contents(
    request: Request,
    search: str | None = Query(None, max_length=100),
    status: str | None = None,
    platform: str | None = None,
    post_status: str | None = None,
    media_type: str | None = None,
) -> Response:
    contents = await asyncio.to_thread(
        services(request).contents.list,
        limit=5000, offset=0, search=search, status=status, platform=platform,
        post_status=post_status, media_type=media_type, sort_by="newest",
    )
    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM for Microsoft Excel compatibility
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Tiêu đề", "Nội dung (Caption)", "Hashtags", "CTA",
        "Nền tảng", "Tình trạng", "Lịch đăng", "Ngày đăng", "Link bài viết", "Số media"
    ])
    for item in contents:
        writer.writerow([
            item.get("id", ""),
            item.get("title", ""),
            item.get("caption", ""),
            " ".join(item.get("hashtags", [])),
            item.get("cta", "") or "",
            ", ".join(item.get("platforms", [])),
            item.get("publishing_status", "draft"),
            item.get("scheduled_at", "") or "",
            item.get("published_at", "") or "",
            item.get("external_url", "") or "",
            len(item.get("media", [])),
        ])
    content_bytes = output.getvalue().encode("utf-8")
    return Response(
        content=content_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=tinix-posts-export.csv"},
    )


@router.post("/contents/bulk-delete")
async def bulk_delete_contents(body: BulkDeleteBody, request: Request) -> dict[str, Any]:
    svc = services(request)
    result = await asyncio.to_thread(svc.contents.bulk_delete, body.content_ids, body.force)
    if body.delete_files and result.get("retained_paths"):
        await asyncio.to_thread(svc.media.delete_managed, result["retained_paths"])
    return result


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
async def delete_content(content_id: str, request: Request, delete_files: bool = False, force: bool = False) -> dict[str, Any]:
    svc = services(request)
    try:
        paths = await asyncio.to_thread(svc.contents.delete, content_id, force)
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


@router.get("/media-assets")
async def list_media_assets(
    request: Request, search: str | None = Query(default=None, max_length=100),
    media_type: str | None = Query(default=None, pattern="^(image|video)$"),
    tag: str | None = Query(default=None, max_length=80), orphan_only: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(
        services(request).media_assets.list, search, media_type, tag, orphan_only, limit
    )


@router.post("/media-assets", status_code=201)
async def upload_media_asset(
    request: Request, file: UploadFile = File(...), alt_text: str | None = Form(default=None),
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            services(request).media.upload_asset, file.file, file.filename or "upload", file.content_type,
            alt_text=alt_text,
        )
    except MediaValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.patch("/media-assets/{asset_id}")
async def update_media_asset(asset_id: str, body: MediaAssetUpdate, request: Request) -> dict[str, Any]:
    asset = await asyncio.to_thread(
        services(request).media_assets.update, asset_id, body.alt_text, body.tags, body.thumbnail_timestamp
    )
    if not asset:
        raise HTTPException(404, "Không tìm thấy media asset.")
    return asset


@router.post("/media-assets/{asset_id}/attach")
async def attach_media_asset(asset_id: str, body: MediaAttachBody, request: Request) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            services(request).media.attach_asset, body.content_id, asset_id, body.sort_order, body.alt_text
        )
    except MediaValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/media-assets/{asset_id}/attach/{content_id}")
async def detach_media_asset(asset_id: str, content_id: str, request: Request) -> dict[str, bool]:
    detached = await asyncio.to_thread(services(request).media_assets.detach, asset_id, content_id)
    if not detached:
        raise HTTPException(404, "Không tìm thấy reference.")
    return {"detached": True}


@router.get("/media-assets/{asset_id}/compatibility")
async def media_asset_compatibility(asset_id: str, request: Request) -> dict[str, Any]:
    asset = await asyncio.to_thread(services(request).media_assets.get, asset_id)
    if not asset:
        raise HTTPException(404, "Không tìm thấy media asset.")
    platforms = {}
    for platform in PLATFORM_CATALOG:
        platforms[platform.id] = [
            schema.id for schema in platform.format_schemas
            if asset["media_type"] in schema.allowed_media_types and schema.min_media <= 1 <= schema.max_media
        ]
    return {"asset_id": asset_id, "platforms": platforms}


@router.delete("/media-assets/{asset_id}")
async def delete_media_asset(asset_id: str, request: Request, delete_files: bool = True) -> dict[str, Any]:
    try:
        paths = await asyncio.to_thread(services(request).media_assets.delete, asset_id)
    except KeyError as exc:
        raise HTTPException(404, "Không tìm thấy media asset.") from exc
    except MediaAssetInUseError as exc:
        raise HTTPException(409, str(exc)) from exc
    deleted = await asyncio.to_thread(services(request).media.delete_managed, paths) if delete_files else 0
    return {"deleted": True, "files_deleted": deleted}


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


@router.post("/ai/generate-image")
async def generate_ai_image(body: AIGenerateImageBody, request: Request) -> dict[str, Any]:
    try:
        return await services(request).ai_studio.generate_image(body.prompt, body.content_id)
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
            body.routing_preference,
        )
        services(request).worker.notify()
        return jobs
    except SchedulingError as exc:
        raise HTTPException(422, str(exc)) from exc
