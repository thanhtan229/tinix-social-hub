from __future__ import annotations

import time
from typing import Any

from app.db.content_repositories import AIGenerationRepository, BrandProfileRepository, ContentRepository
from app.services.ai import AIError, AIProvider


SYSTEM_PROMPT = """Bạn là AI Content Studio. Chỉ trả về JSON hợp lệ theo schema:
{
  "topic":"", "summary":"", "platform_variants": {
    "facebook":{"caption":"","hashtags":[],"cta":"","pinned_comment":""},
    "instagram":{"caption":"","hashtags":[],"cta":""},
    "tiktok":{"caption":"","hashtags":[],"video_hook":"","video_script":""},
    "youtube":{"title":"","caption":"","hashtags":[],"video_hook":"","video_script":""}
  }, "media_suggestions":[], "warnings":[]
}
Không tự lập lịch hoặc đăng. Tuân thủ brand profile và cảnh báo nếu brief xung đột từ khóa cấm."""


class AIContentStudioService:
    def __init__(
        self,
        provider: AIProvider,
        generations: AIGenerationRepository,
        brands: BrandProfileRepository,
        contents: ContentRepository,
    ) -> None:
        self.provider = provider
        self.generations = generations
        self.brands = brands
        self.contents = contents

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
        generation_id = self.generations.start(
            self.provider.name, getattr(getattr(self.provider, "settings", None), "ai_model", "mock"),
            operation, request, brief_id, brand_profile_id,
        )
        started = time.perf_counter()
        prompt = f"Thao tác: {operation}\nNền tảng: {', '.join(platforms)}\nBrief: {brief}\n{self._brand_context(brand)}"
        try:
            result = await self.provider.generate_structured(prompt, SYSTEM_PROMPT)
            payload = result.content.model_dump()
            self.generations.finish(generation_id, payload, result.usage, result.latency_ms)
        except AIError as exc:
            self.generations.fail(generation_id, exc.code, str(exc), int((time.perf_counter() - started) * 1000))
            raise
        content = None
        if save_draft:
            facebook = result.content.platform_variants.get("facebook")
            content = self.contents.create(
                {
                    "brand_profile_id": brand_profile_id,
                    "brief_id": brief_id,
                    "title": result.content.topic or "AI draft",
                    "topic": result.content.topic,
                    "summary": result.content.summary,
                    "caption": facebook.caption if facebook else "",
                    "hashtags": facebook.hashtags if facebook else [],
                    "cta": facebook.cta if facebook else None,
                    "platform_variants": {
                        platform: variant.model_dump() for platform, variant in result.content.platform_variants.items()
                    },
                },
                source="ai",
            )
        return {"generation_id": generation_id, "structured_content": payload, "content": content}
