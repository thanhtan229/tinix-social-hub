"""Platform manifests and extension boundaries."""

from app.platforms.catalog import PLATFORM_CATALOG, PlatformDefinition, capability_summary, get_platform

__all__ = ["PLATFORM_CATALOG", "PlatformDefinition", "capability_summary", "get_platform"]
