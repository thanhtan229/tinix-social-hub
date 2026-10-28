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
    analytics: CapabilityState = "scaffold"


@dataclass(frozen=True, slots=True)
class TransportDefinition:
    id: str
    readiness: CapabilityState
    content_formats: tuple[str, ...]
    authentication: CapabilityState
    target_discovery: CapabilityState
    publishing: CapabilityState
    result_verification: CapabilityState
    required_scopes: tuple[str, ...] = ()


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
    transports: tuple[TransportDefinition, ...] = ()

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["readiness"] = capability_summary(self)
        if not self.transports:
            result["transports"] = [asdict(default_chrome_transport(self))]
        return result

    def transport(self, transport_id: str) -> TransportDefinition | None:
        candidates = self.transports or (default_chrome_transport(self),)
        return next((item for item in candidates if item.id == transport_id), None)


def default_chrome_transport(platform: PlatformDefinition) -> TransportDefinition:
    return TransportDefinition(
        id="chrome",
        readiness="ready" if platform.operational else "scaffold",
        content_formats=platform.content_formats,
        authentication=platform.capabilities.account_session,
        target_discovery=platform.capabilities.target_discovery,
        publishing=platform.capabilities.publishing,
        result_verification=platform.capabilities.result_verification,
    )


def foundation_transports(content_formats: tuple[str, ...]) -> tuple[TransportDefinition, ...]:
    return (
        TransportDefinition(
            id="chrome", readiness="ready", content_formats=content_formats,
            authentication="ready", target_discovery="review_required",
            publishing="review_required", result_verification="review_required",
        ),
        TransportDefinition(
            id="official_api", readiness="scaffold", content_formats=(),
            authentication="scaffold", target_discovery="scaffold",
            publishing="scaffold", result_verification="scaffold",
        ),
    )


def youtube_transports() -> tuple[TransportDefinition, ...]:
    chrome, _scaffold = foundation_transports(("video", "short"))
    return (
        chrome,
        TransportDefinition(
            id="official_api", readiness="ready", content_formats=("video", "short"),
            authentication="ready", target_discovery="ready",
            publishing="ready", result_verification="ready",
            required_scopes=(
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube.readonly",
            ),
        ),
    )


PLATFORM_CATALOG: tuple[PlatformDefinition, ...] = (
    PlatformDefinition(
        id="facebook", name="Facebook", phase="Page API text/photo album/video + Reel",
        account_label="Facebook account", target_label="Page", target_types=("page",),
        content_formats=("post", "photo", "multi_photo", "video", "reel"),
        capabilities=PlatformCapabilities("ready", "ready", "ready", "review_required", "review_required", "review_required"),
        next_milestone="Official API hỗ trợ bài chữ, một ảnh, album ảnh, video Page MP4 và Reel; media cần Page/app có quyền phù hợp.",
        selector_version="facebook-web-v1", operational=True,
        transports=(
            foundation_transports(("post",))[0],
            TransportDefinition(
                id="official_api", readiness="review_required",
                content_formats=("post", "photo", "multi_photo", "video", "reel"),
                authentication="review_required", target_discovery="review_required",
                publishing="review_required", result_verification="review_required",
                required_scopes=("pages_show_list", "pages_manage_posts", "pages_read_engagement", "read_insights"),
            ),
        ),
        format_schemas=(
            FormatSchema("post", "Bài viết", 63206, 0, 10, ("image", "video"), (
                SettingSchema("first_comment", "Bình luận đầu tiên", "textarea"),
            )),
            FormatSchema("photo", "Ảnh Facebook", 63206, 1, 1, ("image",)),
            FormatSchema("multi_photo", "Nhiều ảnh Facebook", 63206, 2, 10, ("image",)),
            FormatSchema("video", "Video Page thường", 63206, 1, 1, ("video",)),
            FormatSchema("reel", "Facebook Reel", 63_000, 1, 1, ("video",)),
        ),
    ),
    PlatformDefinition(
        id="instagram", name="Instagram", phase="Chrome image/carousel · Instagram Login API photo publisher implemented; R2 and live acceptance required",
        account_label="Instagram account", target_label="Profile", target_types=("profile",),
        content_formats=("image", "carousel"),
        capabilities=PlatformCapabilities("ready", "review_required", "review_required", "review_required", "review_required", "review_required"),
        next_milestone="Instagram Login độc lập; publisher ảnh chờ cấu hình private R2 và nghiệm thu OAuth/live.",
        selector_version="instagram-web-v1", operational=True,
        transports=(
            foundation_transports(("image", "carousel"))[0],
            TransportDefinition(
                id="official_api", readiness="review_required", content_formats=("image", "carousel"),
                authentication="review_required", target_discovery="api",
                publishing="review_required", result_verification="review_required",
                required_scopes=("instagram_business_basic", "instagram_business_content_publish"),
            ),
        ),
        format_schemas=(
            FormatSchema("image", "Ảnh", 2200, 1, 1, ("image",)),
            FormatSchema("carousel", "Carousel", 2200, 2, 10, ("image",)),
        ),
    ),
    PlatformDefinition(
        id="tiktok", name="TikTok", phase="Chrome adapter · short video",
        account_label="TikTok account", target_label="Channel", target_types=("channel",),
        content_formats=("short_video",),
        capabilities=PlatformCapabilities("ready", "review_required", "review_required", "review_required", "review_required", "review_required"),
        next_milestone="Dry-run TikTok Studio và xác nhận privacy/comment trên UI thật.",
        selector_version="tiktok-studio-web-v1", operational=True,
        transports=foundation_transports(("short_video",)),
        format_schemas=(
            FormatSchema("short_video", "Video ngắn", 2200, 1, 1, ("video",), (
                SettingSchema("privacy", "Quyền riêng tư", "select", True, "public", ("public", "friends", "private")),
                SettingSchema("allow_comments", "Cho phép bình luận", "checkbox", False, True),
            )),
        ),
    ),
    PlatformDefinition(
        id="youtube", name="YouTube", phase="Chrome adapter · video/Short",
        account_label="Google account", target_label="Channel", target_types=("channel",),
        content_formats=("video", "short"),
        capabilities=PlatformCapabilities(
            "ready", "review_required", "review_required", "review_required", "review_required", "review_required",
            analytics="review_required",
        ),
        next_milestone="OAuth API hỗ trợ đăng video/Short, snapshot và báo cáo theo ngày; cần acceptance trên channel thật.",
        selector_version="youtube-studio-web-v1", operational=True,
        transports=youtube_transports(),
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
        ),
    ),
    PlatformDefinition(
        id="x", name="X", phase="Chrome adapter · post",
        account_label="X account", target_label="Profile", target_types=("profile",),
        content_formats=("post",),
        capabilities=PlatformCapabilities(
            "ready", "review_required", "review_required", "review_required",
            "review_required", "review_required",
        ),
        next_milestone="Dry-run X composer trên profile thật và xác nhận selector sau mỗi thay đổi UI.",
        selector_version="x-web-v1", operational=True,
        transports=foundation_transports(("post",)),
        format_schemas=(
            FormatSchema("post", "Bài post", 280, 0, 4, ("image", "video")),
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
