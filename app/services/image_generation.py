from __future__ import annotations

import asyncio
import io
import time
from typing import Any

from app.db.content_repositories import AIGenerationRepository
from app.services.ai import AIError, OpenAICompatibleProvider
from app.services.integrations import IntegrationService
from app.services.media import MediaService
from app.services.media_creator import MediaCreatorClient


class ImageGenerationService:
    """Coordinates local Direct API and Tinix Media Creator image jobs."""

    def __init__(
        self, integrations: IntegrationService, generations: AIGenerationRepository,
        media: MediaService, media_creator: MediaCreatorClient, timeout_seconds: int,
    ) -> None:
        self.integrations = integrations
        self.generations = generations
        self.media = media
        self.media_creator = media_creator
        self.timeout_seconds = timeout_seconds
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._external_runs: dict[str, str] = {}

    async def options(self) -> dict[str, Any]:
        ai_state = await asyncio.to_thread(self.integrations.ai_list)
        direct = [
            {
                "config_id": item["id"], "provider": item["provider"], "name": item["name"],
                "model": item.get("image_model") or "", "aspect_ratios": ["auto", "1:1", "4:3", "3:4", "16:9", "9:16"],
                "counts": [1, 2, 4], "qualities": ["auto", "low", "medium", "high"],
            }
            for item in ai_state["configs"] if item.get("enabled") and item.get("image_model")
        ]
        legacy = ai_state.get("legacy") or {}
        if ai_state.get("legacy_configured") and legacy.get("image_model"):
            direct.append({
                "config_id": "__default__", "provider": legacy.get("provider", "legacy"), "name": "Cấu hình .env legacy",
                "model": legacy["image_model"], "aspect_ratios": ["auto", "1:1", "4:3", "3:4", "16:9", "9:16"],
                "counts": [1, 2, 4], "qualities": ["auto", "low", "medium", "high"],
            })
        try:
            providers = await self.media_creator.providers()
            media_creator = {
                "available": True,
                "providers": [
                    {
                        "id": item.get("id"), "label": item.get("label") or item.get("id"),
                        "capabilities": item.get("capabilities") or {},
                    }
                    for item in providers if "image" in (item.get("capabilities") or {}).get("outputTypes", [])
                ],
            }
        except AIError as exc:
            media_creator = {"available": False, "message": str(exc), "providers": []}
        return {"direct_api": direct, "defaults": ai_state.get("defaults") or {}, "media_creator": media_creator}

    async def create_job(self, request: dict[str, Any]) -> dict[str, Any]:
        engine = str(request.get("engine") or "direct_api")
        if engine not in {"direct_api", "media_creator"}:
            raise AIError("invalid_image_engine", "Engine tạo ảnh không hợp lệ.")
        prompt = str(request.get("prompt") or "").strip()
        if not prompt:
            raise AIError("invalid_prompt", "Prompt tạo ảnh không được để trống.")

        if engine == "direct_api":
            config_id = str(request.get("config_id") or "")
            resolved = self.integrations.resolve_specific(config_id, "image") if config_id else self.integrations.resolve_ai("image")
            provider, model = resolved.provider, resolved.settings.ai_model
        else:
            provider = str(request.get("provider") or "").strip()
            if not provider:
                raise AIError("invalid_media_creator_provider", "Hãy chọn provider của Tinix Media Creator.")
            model = provider

        generation_id = await asyncio.to_thread(
            self.generations.start, provider, model, "image", request, None, None,
        )
        await asyncio.to_thread(self.generations.update_image_job, generation_id, status="queued")
        task = asyncio.create_task(self._run(generation_id, {**request, "engine": engine}))
        self._tasks[generation_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(generation_id, None))
        return {"job_id": generation_id, "status": "queued", "engine": engine, "provider": provider, "model": model}

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        item = await asyncio.to_thread(self.generations.get, job_id)
        if not item or item.get("operation") != "image":
            return None
        response = item.get("response") or {}
        return {
            "job_id": item["id"], "status": item["status"], "engine": item["request"].get("engine", "direct_api"),
            "provider": item["provider"], "model": item["model"], "prompt": item["request"].get("prompt", ""),
            "message": response.get("message") or item.get("error_message") or "",
            "progress": response.get("progress", 0 if item["status"] in {"queued", "running"} else 100),
            "images": response.get("images") or [], "attached_content_id": response.get("attached_content_id"),
            "fallback_used": bool(response.get("fallback_used")), "external_run_id": response.get("external_run_id"),
        }

    async def cancel(self, job_id: str) -> bool:
        item = await self.get_job(job_id)
        if not item or item["status"] in {"completed", "partial", "failed", "cancelled"}:
            return False
        external_run_id = self._external_runs.get(job_id) or item.get("external_run_id")
        if external_run_id:
            await self.media_creator.abort_run(external_run_id)
        task = self._tasks.get(job_id)
        if task:
            task.cancel()
        await asyncio.to_thread(
            self.generations.update_image_job, job_id, status="cancelled",
            response={"message": "Đã hủy tác vụ tạo ảnh.", "progress": 0, "external_run_id": external_run_id}, finished=True,
        )
        return True

    async def close(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def _run(self, job_id: str, request: dict[str, Any]) -> None:
        started = time.perf_counter()
        try:
            await asyncio.to_thread(self.generations.update_image_job, job_id, status="running", response={"message": "Đang tạo ảnh…", "progress": 10})
            if request["engine"] == "media_creator":
                payload = await self._run_media_creator(job_id, request)
            else:
                payload = await self._run_direct(request)
            await asyncio.to_thread(self.generations.update_image_job, job_id, status="completed", response=payload, finished=True)
        except asyncio.CancelledError:
            raise
        except AIError as exc:
            await asyncio.to_thread(
                self.generations.update_image_job, job_id, status="failed",
                response={"message": str(exc), "progress": 100}, error_code=exc.code, error_message=str(exc), finished=True,
            )
        except Exception as exc:
            await asyncio.to_thread(
                self.generations.update_image_job, job_id, status="failed",
                response={"message": "Tạo ảnh thất bại.", "progress": 100}, error_code="image_generation_failed", error_message=str(exc), finished=True,
            )
        finally:
            _ = started

    async def _run_direct(self, request: dict[str, Any]) -> dict[str, Any]:
        config_id = str(request.get("config_id") or "")
        resolved = self.integrations.resolve_specific(config_id, "image") if config_id else self.integrations.resolve_ai("image")
        provider = OpenAICompatibleProvider(resolved.settings)
        try:
            results = await provider.generate_images(
                request["prompt"], count=int(request.get("count") or 1),
                aspect_ratio=str(request.get("aspect_ratio") or "auto"), quality=str(request.get("quality") or "auto"),
                allow_fallback=request.get("fallback_policy") == "pollinations",
            )
        finally:
            await provider.close()
        imported = await self._import_results(results, request)
        return {
            "message": f"Đã tạo {len(imported)} ảnh bằng {resolved.settings.ai_model}.", "progress": 100,
            "images": imported, "attached_content_id": request.get("content_id") if imported and request.get("content_id") else None,
            "fallback_used": any(result.fallback_used for result in results),
        }

    async def _run_media_creator(self, job_id: str, request: dict[str, Any]) -> dict[str, Any]:
        run_id = await self.media_creator.create_run(
            run_id=job_id, provider=str(request["provider"]), prompt=request["prompt"],
            aspect_ratio=str(request.get("aspect_ratio") or "auto"), count=int(request.get("count") or 1),
        )
        self._external_runs[job_id] = run_id
        await asyncio.to_thread(self.generations.update_image_job, job_id, status="running", response={"message": "Tinix Media Creator đang tạo ảnh…", "progress": 20, "external_run_id": run_id})
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            status = await self.media_creator.run_status(run_id)
            if status.get("terminal"):
                if status.get("status") in {"failed", "cancelled", "needs_review"}:
                    raise AIError("media_creator_generation_failed", status.get("message") or "Tinix Media Creator không tạo được ảnh.")
                images = await self._import_media_creator_results(status.get("results") or [], request)
                if not images:
                    raise AIError("media_creator_empty_result", "Tinix Media Creator đã hoàn tất nhưng chưa có ảnh kết quả.")
                return {
                    "message": f"Đã nhận {len(images)} ảnh từ Tinix Media Creator.", "progress": 100,
                    "images": images, "attached_content_id": request.get("content_id") if request.get("content_id") else None,
                    "external_run_id": run_id,
                }
            await asyncio.to_thread(self.generations.update_image_job, job_id, status="running", response={
                "message": status.get("message") or "Tinix Media Creator đang xử lý…", "progress": 55, "external_run_id": run_id,
            })
            await asyncio.sleep(2)
        raise AIError("media_creator_timeout", "Tinix Media Creator quá thời gian chờ.", True)

    async def _import_results(self, results: list[Any], request: dict[str, Any]) -> list[dict[str, Any]]:
        imported: list[dict[str, Any]] = []
        for index, result in enumerate(results, start=1):
            ext = ".jpg" if "jpeg" in result.mime_type.lower() else ".png"
            asset = await asyncio.to_thread(
                self.media.upload_asset, io.BytesIO(result.image_bytes), f"ai_gen_{int(time.time())}_{index}{ext}",
                result.mime_type, alt_text=request["prompt"][:200], source="ai_studio",
            )
            if request.get("content_id"):
                await asyncio.to_thread(self.media.attach_asset, request["content_id"], asset["id"], index - 1)
            imported.append({"url": f"/api/media/{asset['relative_path']}", "asset": asset, "source_model": result.source_model})
        return imported

    async def _import_media_creator_results(self, results: list[dict[str, Any]], request: dict[str, Any]) -> list[dict[str, Any]]:
        imported: list[dict[str, Any]] = []
        for index, result in enumerate(results, start=1):
            if result.get("kind") != "image" or not result.get("mediaUrl"):
                continue
            image_bytes, mime_type = await self.media_creator.download(str(result["mediaUrl"]))
            ext = ".jpg" if "jpeg" in mime_type.lower() else ".png"
            name = str(result.get("name") or f"media_creator_{index}{ext}")
            asset = await asyncio.to_thread(
                self.media.upload_asset, io.BytesIO(image_bytes), name, mime_type,
                alt_text=request["prompt"][:200], source="tinix_media_creator",
            )
            if request.get("content_id"):
                await asyncio.to_thread(self.media.attach_asset, request["content_id"], asset["id"], index - 1)
            imported.append({"url": f"/api/media/{asset['relative_path']}", "asset": asset, "source_model": result.get("provider") or "Tinix Media Creator"})
        return imported
