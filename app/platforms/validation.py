from __future__ import annotations

from typing import Any

from app.platforms.catalog import FormatSchema, get_platform


class PlatformValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def get_format_schema(platform: str, content_format: str) -> FormatSchema:
    definition = get_platform(platform)
    if not definition:
        raise PlatformValidationError([f"Nền tảng không tồn tại: {platform}"])
    if content_format not in definition.content_formats:
        raise PlatformValidationError([f"Định dạng {content_format} chưa được hỗ trợ cho {definition.name}."])
    schema = next((item for item in definition.format_schemas if item.id == content_format), None)
    if not schema:
        raise PlatformValidationError([f"Định dạng {content_format} không hợp lệ cho {definition.name}."])
    return schema


def validate_publication(
    platform: str,
    content_format: str,
    caption: str,
    media: list[dict[str, Any]],
    settings: dict[str, Any],
) -> FormatSchema:
    schema = get_format_schema(platform, content_format)
    errors: list[str] = []
    if len(caption) > schema.max_caption_length:
        errors.append(f"Caption vượt giới hạn {schema.max_caption_length} ký tự.")
    count = len(media)
    if count < schema.min_media or count > schema.max_media:
        errors.append(f"Định dạng {schema.label} cần {schema.min_media}-{schema.max_media} media.")
    media_types = [item.get("type") or item.get("media_type") for item in media]
    invalid = sorted({kind for kind in media_types if kind not in schema.allowed_media_types})
    if invalid:
        errors.append(f"Media không hỗ trợ: {', '.join(invalid)}.")
    if "video" in media_types and len(media_types) > 1:
        errors.append("Một release không được trộn video với media khác.")
    for field in schema.settings:
        value = settings.get(field.key, field.default)
        if field.required and (value is None or value == ""):
            errors.append(f"Thiếu trường bắt buộc: {field.label}.")
        if field.options and value not in field.options:
            errors.append(f"Giá trị {field.label} không hợp lệ.")
    if errors:
        raise PlatformValidationError(errors)
    return schema
