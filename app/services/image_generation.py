from __future__ import annotations

import asyncio
import io
import time
from typing import Any

from app.db.content_repositories import AIGenerationRepository
from app.services.ai import AIError
from app.services.media import MediaService
from app.services.media_creator import MediaCreatorClient


class ImageGenerationService:
    """Coordinates image jobs through the local Tinix Media Creator only."""

    def __init__(
        self, generations: AIGenerationRepository, media: MediaService,
        media_creator: MediaCreatorClient, timeout_seconds: int,
    ) -> None:
        self.generations = generations
        self.media = media
        self.media_creator = media_creator
        self.timeout_seconds = timeout_seconds
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._external_runs: dict[str, str] = {}

    async def start(self) -> None:
        for item in await asyncio.to_thread(self.generations.pending_image_jobs):
            job_id = item["id"]
            if job_id in self._tasks:
                continue
            run_id = (item.get("response") or {}).get("external_run_id")
            if not run_id:
                await asyncio.to_thread(
                    self.generations.update_image_job, job_id, status="failed", finished=True,
                    error_code="image_generation_interrupted",
                    error_message="Tác vụ bị gián đoạn trước khi lưu run ID; kiểm tra Media Creator trước khi thử lại.",
                    response={"message": "Tác vụ bị gián đoạn; chưa tự tạo run mới.", "progress": 100},
                )
                continue
            self._external_runs[job_id] = run_id
            self._schedule(job_id, item["request"], resume_run_id=run_id)

    def _schedule(self, job_id: str, request: dict[str, Any], resume_run_id: str | None = None) -> None:
        task = asyncio.create_task(self._run(job_id, request, resume_run_id), name=f"image-{job_id}")
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))

    async def options(self) -> dict[str, Any]:
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
        return {"media_creator": media_creator}

    async def create_job(self, request: dict[str, Any]) -> dict[str, Any]:
        engine = str(request.get("engine") or "media_creator")
        if engine != "media_creator":
            raise AIError("invalid_image_engine", "Engine tạo ảnh không hợp lệ.")
        prompt = str(request.get("prompt") or "").strip()
        if not prompt:
            raise AIError("invalid_prompt", "Prompt tạo ảnh không được để trống.")

        provider = str(request.get("provider") or "").strip()
        if not provider:
            raise AIError("invalid_media_creator_provider", "Hãy chọn provider của Tinix Media Creator.")
        selected_model = str(request.get("model") or "").strip()
        providers = await self.media_creator.providers()
        provider_info = next((item for item in providers if item.get("id") == provider), None)
        if not provider_info or "image" not in (provider_info.get("capabilities") or {}).get("outputTypes", []):
            raise AIError("invalid_media_creator_provider", "Provider đã chọn không hỗ trợ tạo ảnh.")
        image_models = (provider_info.get("capabilities") or {}).get("imageModels") or []
        model_ids = {
            str(item.get("id") or item.get("model") or item.get("name") or "").strip()
            if isinstance(item, dict) else str(item).strip()
            for item in image_models
        }
        model_ids.discard("")
        if selected_model and selected_model not in model_ids:
            raise AIError("invalid_image_model", "Model đã chọn không thuộc provider ảnh này.")
        model = selected_model or "auto"
        request = {**request, "model": selected_model}

        generation_id = await asyncio.to_thread(
            self.generations.start, provider, model, "image", {**request, "engine": engine}, None, None,
        )
        await asyncio.to_thread(self.generations.update_image_job, generation_id, status="queued")
        self._schedule(generation_id, {**request, "engine": engine})
        return {"job_id": generation_id, "status": "queued", "engine": engine, "provider": provider, "model": model}

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        item = await asyncio.to_thread(self.generations.get, job_id)
        if not item or item.get("operation") != "image":
            return None
        response = item.get("response") or {}
        return {
            "job_id": item["id"], "status": item["status"], "engine": item["request"].get("engine", "media_creator"),
            "provider": item["provider"], "model": item["model"], "prompt": item["request"].get("prompt", ""),
            "message": response.get("message") or item.get("error_message") or "",
            "progress": response.get("progress", 0 if item["status"] in {"queued", "running"} else 100),
            "images": response.get("images") or [], "attached_content_id": response.get("attached_content_id"),
            "external_run_id": response.get("external_run_id"),
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
            await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(
            self.generations.update_image_job, job_id, status="cancelled",
            response={"message": "Đã hủy tác vụ tạo ảnh.", "progress": 0, "external_run_id": external_run_id}, finished=True,
        )
        return True

    async def close(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def _run(self, job_id: str, request: dict[str, Any], resume_run_id: str | None = None) -> None:
        started = time.perf_counter()
        try:
            # Persist the client-assigned ID before dispatch, including an interrupted create request.
            run_id = resume_run_id or job_id
            self._external_runs[job_id] = run_id
            await asyncio.to_thread(self.generations.update_image_job, job_id, status="running", response={
                "message": "Đang tạo ảnh…", "progress": 10, "external_run_id": run_id,
            })
            payload = await self._run_media_creator(job_id, request, resume_run_id)
            await asyncio.to_thread(self.generations.update_image_job, job_id, status="completed", response=payload, finished=True)
        except asyncio.CancelledError:
            raise
        except AIError as exc:
            await asyncio.to_thread(
                self.generations.update_image_job, job_id, status="failed",
                response={"message": str(exc), "progress": 100, "external_run_id": self._external_runs.get(job_id)}, error_code=exc.code, error_message=str(exc), finished=True,
            )
        except Exception as exc:
            await asyncio.to_thread(
                self.generations.update_image_job, job_id, status="failed",
                response={"message": "Tạo ảnh thất bại.", "progress": 100, "external_run_id": self._external_runs.get(job_id)}, error_code="image_generation_failed", error_message=str(exc), finished=True,
            )
        finally:
            _ = started

    async def _run_media_creator(self, job_id: str, request: dict[str, Any], resume_run_id: str | None = None) -> dict[str, Any]:
        run_id = resume_run_id or await self.media_creator.create_run(
            run_id=job_id, provider=str(request["provider"]), prompt=request["prompt"],
            aspect_ratio=str(request.get("aspect_ratio") or "auto"), count=int(request.get("count") or 1),
            model=str(request.get("model") or ""),
        )
        self._external_runs[job_id] = run_id
        await asyncio.to_thread(self.generations.update_image_job, job_id, status="running", response={"message": "Tinix Media Creator đang tạo ảnh…", "progress": 20, "external_run_id": run_id})
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            status = await self.media_creator.run_status(run_id)
            if resume_run_id and status.get("status") == "unknown":
                raise AIError("image_generation_interrupted", "Run đã lưu không còn ở Media Creator; kiểm tra kết quả trước khi thử lại.")
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
