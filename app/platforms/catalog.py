from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


CapabilityState = Literal["ready", "review_required", "scaffold", "not_started", "deferred"]


@dataclass(frozen=True, slots=True)
class SettingSchema:
    key: str
    label: str
    field_type: str = "text"
    required: bool = False
    default: object = None
    options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FormatSchema:
    id: str
    label: str
    max_caption_length: int
    min_media: int
    max_media: int
    allowed_media_types: tuple[str, ...]
    settings: tuple[SettingSchema, ...] = ()


@dataclass(frozen=True, slots=True)
class PlatformCapabilities:
    content_variants: CapabilityState
    account_session: CapabilityState
    target_discovery: CapabilityState
    dry_run: CapabilityState
    publishing: CapabilityState
    result_verification: CapabilityState


@dataclass(frozen=True, slots=True)
class PlatformDefinition:
    id: str
    name: str
    phase: str
    account_label: str
    target_label: str
    target_types: tuple[str, ...]
    content_formats: tuple[str, ...]
    capabilities: PlatformCapabilities
    next_milestone: str
    publication_transport: str = "chrome"
    selector_version: str = "scaffold"
    operational: bool = False
    format_schemas: tuple[FormatSchema, ...] = ()

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["readiness"] = capability_summary(self)
        return result


PLATFORM_CATALOG: tuple[PlatformDefinition, ...] = (
    PlatformDefinition(
        id="facebook", name="Facebook", phase="MVP release candidate",
        account_label="Facebook account", target_label="Page", target_types=("page",),
        content_formats=("text", "multi_image", "video"),
        capabilities=PlatformCapabilities("ready", "ready", "ready", "review_required", "review_required", "review_required"),
        next_milestone="Kiểm thử dry-run và đăng thật có giám sát trên Page thực tế.",
        selector_version="facebook-web-v1", operational=True,
        format_schemas=(
            FormatSchema("post", "Bài viết", 63206, 0, 10, ("image", "video"), (
                SettingSchema("first_comment", "Bình luận đầu tiên", "textarea"),
            )),
            FormatSchema("video", "Video", 63206, 1, 1, ("video",)),
        ),
    ),
    PlatformDefinition(
        id="instagram", name="Instagram", phase="Architecture scaffold",
        account_label="Instagram account", target_label="Profile", target_types=("profile",),
        content_formats=("image", "carousel", "reel", "story"),
        capabilities=PlatformCapabilities("ready", "scaffold", "scaffold", "scaffold", "not_started", "not_started"),
        next_milestone="Chốt login/session, profile discovery và composer contract.",
        format_schemas=(
            FormatSchema("image", "Ảnh", 2200, 1, 1, ("image",)),
            FormatSchema("carousel", "Carousel", 2200, 2, 10, ("image",)),
            FormatSchema("reel", "Reel", 2200, 1, 1, ("video",)),
            FormatSchema("story", "Story", 2200, 1, 1, ("image", "video")),
        ),
    ),
    PlatformDefinition(
        id="tiktok", name="TikTok", phase="Architecture scaffold",
        account_label="TikTok account", target_label="Channel", target_types=("channel",),
        content_formats=("short_video", "photo_post"),
        capabilities=PlatformCapabilities("ready", "scaffold", "scaffold", "scaffold", "not_started", "not_started"),
        next_milestone="Chốt upload contract, metadata video và checkpoint handling.",
        format_schemas=(
            FormatSchema("short_video", "Video ngắn", 2200, 1, 1, ("video",), (
                SettingSchema("privacy", "Quyền riêng tư", "select", True, "public", ("public", "friends", "private")),
                SettingSchema("allow_comments", "Cho phép bình luận", "checkbox", False, True),
            )),
            FormatSchema("photo_post", "Bài ảnh", 2200, 1, 35, ("image",)),
        ),
    ),
    PlatformDefinition(
        id="youtube", name="YouTube", phase="Architecture scaffold",
        account_label="Google account", target_label="Channel", target_types=("channel",),
        content_formats=("video", "short", "community_post"),
        capabilities=PlatformCapabilities("ready", "scaffold", "scaffold", "scaffold", "not_started", "not_started"),
        next_milestone="Chốt luồng YouTube Studio cho video/Short và cơ chế xác minh trên UI.",
        format_schemas=(
            FormatSchema("video", "Video", 5000, 1, 1, ("video",), (
                SettingSchema("title", "Tiêu đề", "text", True),
                SettingSchema("privacy", "Quyền riêng tư", "select", True, "private", ("private", "unlisted", "public")),
                SettingSchema("playlist", "Danh sách phát"),
            )),
            FormatSchema("short", "Short", 5000, 1, 1, ("video",), (
                SettingSchema("title", "Tiêu đề", "text", True),
                SettingSchema("privacy", "Quyền riêng tư", "select", True, "private", ("private", "unlisted", "public")),
            )),
            FormatSchema("community_post", "Community post", 1500, 0, 5, ("image",)),
        ),
    ),
)


def get_platform(platform_id: str) -> PlatformDefinition | None:
    normalized = platform_id.strip().lower()
    return next((item for item in PLATFORM_CATALOG if item.id == normalized), None)


def capability_summary(platform: PlatformDefinition) -> dict[str, int]:
    values = asdict(platform.capabilities).values()
    counts = {state: 0 for state in ("ready", "review_required", "scaffold", "not_started", "deferred")}
    for state in values:
        counts[state] += 1
    return counts
