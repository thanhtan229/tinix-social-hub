from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import webbrowser
from typing import Any
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routes import router
from app.api.content import router as content_router
from app.api.v1 import router as v1_router
from app.api.local_boundary import install_local_boundary
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.database import Database
from app.db.calendar_repositories import PostingSlotRepository
from app.db.content_repositories import AIGenerationRepository, BrandProfileRepository, ContentRepository
from app.db.prompt_repositories import PromptTemplateRepository
from app.db.publication_repositories import PublicationRepository
from app.db.provider_repositories import OAuthStateRepository, ProviderConnectionRepository, ProviderTargetConnectionRepository
from app.db.integration_repositories import AIProviderConfigRepository, PlatformAppRepository
from app.db.notification_repositories import NotificationRepository
from app.db.media_repositories import MediaAssetRepository
from app.db.analytics_repositories import AnalyticsRepository
from app.db.automation_repositories import APITokenRepository, WebhookRepository
from app.db.repositories import AppSettingsRepository, AccountRepository, ArtifactRepository, ChromeProfileRepository, JobRepository, TargetRepository
from app.services.ai import AIProvider
from app.services.integrations import IntegrationService, ManagedAIProvider
from app.services.ai_studio import AIContentStudioService
from app.services.chrome import ChromeManager
from app.services.maintenance import MaintenanceService
from app.services.media import MediaService
from app.services.media_creator import MediaCreatorClient
from app.services.image_generation import ImageGenerationService
from app.services.scheduling import SchedulingService
from app.services.facebook_accounts import FacebookAccountService
from app.services.facebook_publisher import FacebookPublisher
from app.services.publishers import PublisherRegistry
from app.services.publisher_router import PublisherRouter
from app.services.provider_accounts import ProviderAccountService
from app.platforms.providers import YouTubeOfficialPublisher
from app.platforms.providers.meta import MetaPagePublisher
from app.services.meta_accounts import MetaAccountService
from app.services.instagram_accounts import InstagramAccountService
from app.services.web_platform_publisher import (
    InstagramChromePublisher,
    TikTokChromePublisher,
    XChromePublisher,
    YouTubeChromePublisher,
)
from app.services.platform_accounts import PlatformAccountService
from app.services.profile_transfer import ChromeProfileTransferService
from app.services.recovery_bundle import RecoveryBundleService
from app.services.ui_analytics import UIAnalyticsCollector
from app.services.api_analytics import MetaAPIAnalyticsCollector, YouTubeAPIAnalyticsCollector
from app.services.analytics_scheduler import AnalyticsRefreshScheduler
from app.services.webhooks import WebhookDispatcher
from app.services.instagram_media_delivery import InstagramMediaDelivery
from app.platforms.providers.instagram import InstagramOfficialPublisher
from app.core.secrets import SecretProtector
from app.runtime import BrowserRuntime, DurableQueue, LocalPathStorage, ManagedStorage, SecretStore, StateDatabase
from app.services.worker import LocalWorker, Scheduler


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Services:
    settings: Settings
    database: StateDatabase
    accounts: AccountRepository
    jobs: DurableQueue
    targets: TargetRepository
    contents: ContentRepository
    brands: BrandProfileRepository
    prompts: PromptTemplateRepository
    ai_generations: AIGenerationRepository
    publications: PublicationRepository
    posting_slots: PostingSlotRepository
    notifications: NotificationRepository
    media_assets: MediaAssetRepository
    analytics: AnalyticsRepository
    app_settings: AppSettingsRepository
    api_tokens: APITokenRepository
    webhooks: WebhookRepository
    chrome: ChromeManager
    ai: AIProvider
    integrations: IntegrationService
    ai_provider_configs: AIProviderConfigRepository
    platform_apps: PlatformAppRepository
    publishers: PublisherRegistry
    publisher_router: PublisherRouter
    provider_connections: ProviderConnectionRepository
    oauth_states: OAuthStateRepository
    provider_accounts: ProviderAccountService
    meta_accounts: MetaAccountService
    instagram_accounts: InstagramAccountService
    instagram_media_delivery: InstagramMediaDelivery
    provider_target_connections: ProviderTargetConnectionRepository
    worker: LocalWorker
    scheduler: Scheduler
    maintenance: MaintenanceService
    facebook_accounts: FacebookAccountService
    platform_accounts: PlatformAccountService
    analytics_collector: UIAnalyticsCollector
    api_analytics_collector: YouTubeAPIAnalyticsCollector
    meta_analytics_collector: MetaAPIAnalyticsCollector
    analytics_scheduler: AnalyticsRefreshScheduler
    webhook_dispatcher: WebhookDispatcher
    storage: ManagedStorage
    secrets: SecretStore
    media: MediaService
    ai_studio: AIContentStudioService
    image_generation: ImageGenerationService
    scheduling: SchedulingService
    profile_transfer: ChromeProfileTransferService
    recovery: RecoveryBundleService
    application_lock: asyncio.Lock


def build_services(settings: Settings) -> Services:
    database = Database(settings.database_path, settings.backup_dir)
    secret_store = SecretProtector()
    accounts = AccountRepository(database, secret_store)
    jobs = JobRepository(database)
    targets = TargetRepository(database)
    contents = ContentRepository(database)
    brands = BrandProfileRepository(database)
    prompts = PromptTemplateRepository(database)
    ai_generations = AIGenerationRepository(database)
    publications = PublicationRepository(database)
    posting_slots = PostingSlotRepository(database)
    notifications = NotificationRepository(database)
    media_assets = MediaAssetRepository(database)
    analytics = AnalyticsRepository(database)
    app_settings = AppSettingsRepository(database)
    ai_provider_configs = AIProviderConfigRepository(database, secret_store)
    platform_apps = PlatformAppRepository(database, secret_store)
    integrations = IntegrationService(settings, ai_provider_configs, platform_apps, app_settings)
    storage = LocalPathStorage(settings.media_dir)
    api_tokens = APITokenRepository(database, settings.data_dir, secret_store)
    webhooks = WebhookRepository(database, secret_store)
    chrome_profiles = ChromeProfileRepository(database)
    artifacts = ArtifactRepository(database)
    chrome = ChromeManager(settings, chrome_profiles)
    ai = ManagedAIProvider(integrations)
    publishers = PublisherRegistry()
    provider_connections = ProviderConnectionRepository(database, secret_store)
    oauth_states = OAuthStateRepository(database, secret_store)
    provider_target_connections = ProviderTargetConnectionRepository(database, secret_store)
    provider_accounts = ProviderAccountService(settings, accounts, provider_connections, oauth_states, targets, platform_apps, chrome)
    meta_accounts = MetaAccountService(settings, accounts, targets, provider_connections, oauth_states, provider_target_connections, platform_apps, chrome)
    instagram_accounts = InstagramAccountService(settings, accounts, targets, provider_connections, oauth_states, platform_apps, chrome)
    publisher_router = PublisherRouter(publishers, provider_connections, provider_target_connections)
    worker = LocalWorker(settings, jobs, accounts, ai, publishers, publisher_router)
    scheduler = Scheduler(settings, jobs, worker)
    facebook_accounts = FacebookAccountService(accounts, targets, chrome)
    media = MediaService(settings, contents, media_assets, storage)
    instagram_media_delivery = InstagramMediaDelivery(settings)
    media_creator = MediaCreatorClient(settings.media_creator_url, settings.media_creator_timeout_seconds)
    image_generation = ImageGenerationService(
        ai_generations, media, media_creator, settings.media_creator_timeout_seconds,
    )
    publishers.register("facebook", FacebookPublisher(settings, chrome, accounts, artifacts, media))
    publishers.register("instagram", InstagramChromePublisher(settings, chrome, accounts, artifacts, media))
    publishers.register(
        "instagram",
        InstagramOfficialPublisher(provider_connections, instagram_accounts, media, instagram_media_delivery),
        transport="official_api",
    )
    publishers.register("tiktok", TikTokChromePublisher(settings, chrome, accounts, artifacts, media))
    publishers.register("youtube", YouTubeChromePublisher(settings, chrome, accounts, artifacts, media))
    publishers.register("x", XChromePublisher(settings, chrome, accounts, artifacts, media))
    publishers.register(
        "youtube",
        YouTubeOfficialPublisher(settings, provider_connections, provider_accounts, media),
        transport="official_api",
    )
    publishers.register("facebook", MetaPagePublisher(meta_accounts, provider_target_connections, media), transport="official_api")
    platform_accounts = PlatformAccountService(accounts, targets, chrome, publishers)
    analytics_collector = UIAnalyticsCollector(accounts, publications, analytics, publishers)
    api_analytics_collector = YouTubeAPIAnalyticsCollector(
        accounts, targets, publications, analytics, provider_connections, provider_accounts,
    )
    meta_analytics_collector = MetaAPIAnalyticsCollector(
        targets, publications, analytics, meta_accounts, provider_target_connections,
    )
    analytics_scheduler = AnalyticsRefreshScheduler(
        app_settings, analytics, api_analytics_collector, meta_analytics_collector,
    )
    webhook_dispatcher = WebhookDispatcher(webhooks)
    ai_studio = AIContentStudioService(ai, ai_generations, brands, contents, prompts, media)
    scheduling = SchedulingService(
        jobs, accounts, targets, contents, publications=publications, publisher_router=publisher_router,
    )
    profile_transfer = ChromeProfileTransferService(settings, database, accounts, secret_store)
    recovery = RecoveryBundleService(settings, database, profile_transfer)
    maintenance = MaintenanceService(settings, profile_transfer, app_settings, notifications)
    return Services(
        settings=settings, database=database, accounts=accounts, jobs=jobs, targets=targets,
        contents=contents, brands=brands, prompts=prompts, ai_generations=ai_generations, publications=publications,
        posting_slots=posting_slots, notifications=notifications, media_assets=media_assets, analytics=analytics,
        app_settings=app_settings,
        api_tokens=api_tokens, webhooks=webhooks,
        chrome=chrome, ai=ai, integrations=integrations, ai_provider_configs=ai_provider_configs, platform_apps=platform_apps, publishers=publishers, publisher_router=publisher_router,
        provider_connections=provider_connections, oauth_states=oauth_states,
        provider_accounts=provider_accounts,
        meta_accounts=meta_accounts, instagram_accounts=instagram_accounts,
        instagram_media_delivery=instagram_media_delivery,
        provider_target_connections=provider_target_connections,
        worker=worker, scheduler=scheduler,
        maintenance=maintenance, facebook_accounts=facebook_accounts, platform_accounts=platform_accounts,
        analytics_collector=analytics_collector, webhook_dispatcher=webhook_dispatcher,
        api_analytics_collector=api_analytics_collector,
        meta_analytics_collector=meta_analytics_collector,
        analytics_scheduler=analytics_scheduler,
        storage=storage, secrets=secret_store, media=media,
        ai_studio=ai_studio, image_generation=image_generation, scheduling=scheduling, profile_transfer=profile_transfer, recovery=recovery,
        application_lock=asyncio.Lock(),
    )


async def _instagram_token_refresh_loop(services: Any, interval_seconds: int = 24 * 3600) -> None:
    """Check Instagram tokens once at startup and then daily; refresh only those close to expiry."""
    while True:
        try:
            summary = await services.instagram_accounts.refresh_due_connections()
            logger.info("Instagram token refresh check: %s", summary)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Instagram token refresh check failed")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()
    configure_logging(settings)
    services = build_services(settings)
    application.state.services = services
    changed = await asyncio.to_thread(services.database.initialize)
    migrated_credentials = await asyncio.to_thread(services.accounts.migrate_legacy_credentials)
    recovered_profile_locks = await asyncio.to_thread(services.accounts.recover_profile_operations)
    await asyncio.to_thread(services.api_tokens.ensure_default)
    logger.info("Database ready%s", " after migration" if changed else "")
    if migrated_credentials:
        logger.info("Protected credentials for %s legacy account(s)", migrated_credentials)
    if recovered_profile_locks:
        logger.warning("Recovered %s interrupted Chrome profile operation lock(s)", recovered_profile_locks)
    if settings.embedded_worker:
        await services.worker.start()
        await services.scheduler.start()
    await services.image_generation.start()
    await services.analytics_scheduler.start()
    instagram_refresh_task = asyncio.create_task(_instagram_token_refresh_loop(services))
    await services.maintenance.start()
    await services.webhook_dispatcher.start()
    if settings.open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(settings.web_url)).start()
    logger.info("Tinix Social Hub %s is ready at %s", __version__, settings.web_url)
    try:
        yield
    finally:
        logger.info("Graceful shutdown started")
        instagram_refresh_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await instagram_refresh_task
        await services.webhook_dispatcher.stop()
        await services.maintenance.stop()
        await services.image_generation.close()
        if settings.embedded_worker:
            await services.scheduler.stop()
            await services.worker.stop()
        await services.analytics_scheduler.stop()
        await services.ai.close()
        closed = await asyncio.to_thread(services.chrome.close_all)
        logger.info("Shutdown complete; closed %s managed Chrome processes", closed)


app = FastAPI(title="Tinix Social Hub", version=__version__, lifespan=lifespan)
install_local_boundary(app, get_settings().host)
app.include_router(router)
app.include_router(content_router)
app.include_router(v1_router)
static_dir = get_settings().project_root / "app" / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.middleware("http")
async def serialize_mutating_requests(request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and hasattr(request.app.state, "services"):
        async with request.app.state.services.application_lock:
            return await call_next(request)
    return await call_next(request)


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(
        static_dir / "index.html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
