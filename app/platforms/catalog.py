from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


CapabilityState = Literal["ready", "review_required", "scaffold", "not_started", "deferred"]


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
    operational: bool = False

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
        next_milestone="Kiểm thử dry-run và đăng thật có giám sát trên Page thực tế.", operational=True,
    ),
    PlatformDefinition(
        id="instagram", name="Instagram", phase="Architecture scaffold",
        account_label="Instagram account", target_label="Profile", target_types=("profile",),
        content_formats=("image", "carousel", "reel", "story"),
        capabilities=PlatformCapabilities("ready", "scaffold", "scaffold", "scaffold", "not_started", "not_started"),
        next_milestone="Chốt login/session, profile discovery và composer contract.",
    ),
    PlatformDefinition(
        id="tiktok", name="TikTok", phase="Architecture scaffold",
        account_label="TikTok account", target_label="Channel", target_types=("channel",),
        content_formats=("short_video", "photo_post"),
        capabilities=PlatformCapabilities("ready", "scaffold", "scaffold", "scaffold", "not_started", "not_started"),
        next_milestone="Chốt upload contract, metadata video và checkpoint handling.",
    ),
    PlatformDefinition(
        id="youtube", name="YouTube", phase="Architecture scaffold",
        account_label="Google account", target_label="Channel", target_types=("channel",),
        content_formats=("video", "short", "community_post"),
        capabilities=PlatformCapabilities("ready", "scaffold", "scaffold", "scaffold", "not_started", "not_started"),
        next_milestone="Chọn YouTube Studio automation hay API chính thức trước khi triển khai.",
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
