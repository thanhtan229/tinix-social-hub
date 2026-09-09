from __future__ import annotations

import time
from typing import Any

from app.db.content_repositories import AIGenerationRepository, BrandProfileRepository, ContentRepository
from app.services.ai import AIError, AIProvider


SYSTEM_PROMPT = """Bạn là AI Content Studio chuyên nghiệp. Chỉ trả về JSON hợp lệ theo schema:
{
  "topic":"", "summary":"", "platform_variants": {
    "facebook":{"caption":"","hashtags":[],"cta":"","pinned_comment":""},
    "instagram":{"caption":"","hashtags":[],"cta":""},
    "tiktok":{"caption":"","hashtags":[],"video_hook":"","video_script":""},
    "youtube":{"title":"","caption":"","hashtags":[],"video_hook":"","video_script":""},
    "x":{"caption":"","hashtags":[],"cta":""}
  },
  "image_prompt": "Prompt chi tiết mô tả hình ảnh minh họa chất lượng cao bằng tiếng Anh (hoặc tiếng Việt) phù hợp với caption và thông điệp bài viết dành cho AI tạo ảnh (DALL-E, Midjourney, FLUX, Imagen)",
  "media_suggestions":[], "warnings":[]
}
Bắt buộc tạo trường 'image_prompt' chi tiết về bối cảnh, chủ thể, phong cách, ánh sáng bám sát nội dung caption đã tạo.
Không tự lập lịch hoặc đăng. Tuân thủ brand profile và cảnh báo nếu brief xung đột từ khóa cấm."""


class AIContentStudioService:
    def __init__(
        self,
        provider: AIProvider,
        generations: AIGenerationRepository,
        brands: BrandProfileRepository,
        contents: ContentRepository,
        media: Any = None,
    ) -> None:
        self.provider = provider
        self.generations = generations
        self.brands = brands
        self.contents = contents
        self.media = media

    @staticmethod
    def _brand_context(brand: dict[str, Any] | None) -> str:
        if not brand:
            return "Không có Brand Profile."
        allowed = {
            key: value for key, value in brand.items()
            if key not in {"id", "created_at", "updated_at"} and value not in (None, "", [])
        }
        return f"Brand Profile: {allowed}"

    async def generate(
        self,
        operation: str,
        brief: str,
        brand_profile_id: str | None,
        platforms: list[str],
        save_draft: bool,
    ) -> dict[str, Any]:
        brand = self.brands.get(brand_profile_id) if brand_profile_id else None
        request = {"operation": operation, "brief": brief, "platforms": platforms}
        brief_id = self.generations.create_brief(brief.strip().splitlines()[0][:200], brief, platforms, brand_profile_id)
        descriptor = self.provider.describe() if hasattr(self.provider, "describe") else {
            "provider": self.provider.name, "model": getattr(getattr(self.provider, "settings", None), "ai_model", "mock"),
        }
        generation_id = self.generations.start(
            descriptor["provider"], descriptor["model"], operation, request, brief_id, brand_profile_id,
        )
        prompt = (
            f"Thao tác: {operation}\n"
            f"Nền tảng: {', '.join(platforms)}\n"
            f"Brief: {brief}\n"
            f"{self._brand_context(brand)}\n\n"
            "Yêu cầu: Luôn tạo trường 'image_prompt' mô tả chi tiết hình ảnh minh họa cho bài viết."
        )
        started = time.perf_counter()
        try:
            result = await self.provider.generate_structured(prompt, SYSTEM_PROMPT)
            payload = result.content.model_dump()
            self.generations.finish(generation_id, payload, result.usage, result.latency_ms)
        except AIError as exc:
            self.generations.fail(generation_id, exc.code, str(exc), int((time.perf_counter() - started) * 1000))
            raise
        content = None
        if save_draft:
            primary = result.content.platform_variants.get("facebook")
            if not primary:
                primary = next(
                    (result.content.platform_variants.get(platform) for platform in platforms
                     if result.content.platform_variants.get(platform)),
                    None,
                )
            content = self.contents.create(
                {
                    "brand_profile_id": brand_profile_id,
                    "brief_id": brief_id,
                    "title": result.content.topic or "AI draft",
                    "topic": result.content.topic,
                    "summary": result.content.summary,
                    "caption": primary.caption if primary else "",
                    "hashtags": primary.hashtags if primary else [],
                    "cta": primary.cta if primary else None,
                    "platform_variants": {
                        platform: variant.model_dump() for platform, variant in result.content.platform_variants.items()
                    },
                },
                source="ai",
            )
        return {"generation_id": generation_id, "structured_content": payload, "content": content}

    async def generate_image(
        self, prompt: str, content_id: str | None = None
    ) -> dict[str, Any]:
        cleaned_prompt = (prompt or "").strip()
        if not cleaned_prompt:
            raise AIError("invalid_prompt", "Prompt tạo ảnh không được để trống.")

        result = await self.provider.generate_image(cleaned_prompt)
        asset_info = None
        media_url = None

        if self.media:
            import io
            ext = ".jpg" if "jpeg" in result.mime_type.lower() else ".png"
            stream = io.BytesIO(result.image_bytes)
            asset = self.media.upload_asset(
                stream,
                original_name=f"ai_gen_{int(time.time())}{ext}",
                content_type=result.mime_type,
                alt_text=cleaned_prompt[:200],
                source="ai_studio",
            )
            asset_info = asset
            media_url = f"/api/media/{asset['relative_path']}"

            if content_id:
                try:
                    self.media.attach_asset(content_id, asset["id"], sort_order=0)
                except Exception:
                    pass

        import base64
        b64_data = base64.b64encode(result.image_bytes).decode("ascii")
        data_uri = f"data:{result.mime_type};base64,{b64_data}"

        return {
            "prompt": cleaned_prompt,
            "url": media_url or data_uri,
            "data_uri": data_uri,
            "asset": asset_info,
            "source_model": result.source_model,
            "fallback_used": result.fallback_used,
            "attached_content_id": content_id if (self.media and content_id and asset_info) else None,
        }
