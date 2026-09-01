from __future__ import annotations

import asyncio
import logging
import threading
import webbrowser
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routes import router
from app.api.content import router as content_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.database import Database
from app.db.calendar_repositories import PostingSlotRepository
from app.db.content_repositories import AIGenerationRepository, BrandProfileRepository, ContentRepository
from app.db.publication_repositories import PublicationRepository
from app.db.notification_repositories import NotificationRepository
from app.db.repositories import AccountRepository, ArtifactRepository, ChromeProfileRepository, JobRepository, TargetRepository
from app.services.ai import OpenAICompatibleProvider
from app.services.ai_studio import AIContentStudioService
from app.services.chrome import ChromeManager
from app.services.maintenance import MaintenanceService
from app.services.media import MediaService
from app.services.scheduling import SchedulingService
from app.services.facebook_accounts import FacebookAccountService
from app.services.facebook_publisher import FacebookPublisher
from app.services.publishers import InstagramPublisherStub, PublisherRegistry, TikTokPublisherStub, YouTubePublisherStub
from app.services.worker import LocalWorker, Scheduler


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Services:
    settings: Settings
    database: Database
    accounts: AccountRepository
    jobs: JobRepository
    targets: TargetRepository
    contents: ContentRepository
    brands: BrandProfileRepository
    ai_generations: AIGenerationRepository
    publications: PublicationRepository
    posting_slots: PostingSlotRepository
    notifications: NotificationRepository
    chrome: ChromeManager
    ai: OpenAICompatibleProvider
    publishers: PublisherRegistry
    worker: LocalWorker
    scheduler: Scheduler
    maintenance: MaintenanceService
    facebook_accounts: FacebookAccountService
    media: MediaService
    ai_studio: AIContentStudioService
    scheduling: SchedulingService
    application_lock: asyncio.Lock


def build_services(settings: Settings) -> Services:
    database = Database(settings.database_path, settings.backup_dir)
    accounts = AccountRepository(database)
    jobs = JobRepository(database)
    targets = TargetRepository(database)
    contents = ContentRepository(database)
    brands = BrandProfileRepository(database)
    ai_generations = AIGenerationRepository(database)
    publications = PublicationRepository(database)
    posting_slots = PostingSlotRepository(database)
    notifications = NotificationRepository(database)
    chrome_profiles = ChromeProfileRepository(database)
    artifacts = ArtifactRepository(database)
    chrome = ChromeManager(settings, chrome_profiles)
    ai = OpenAICompatibleProvider(settings)
    publishers = PublisherRegistry()
    publishers.register("instagram", InstagramPublisherStub())
    publishers.register("tiktok", TikTokPublisherStub())
    publishers.register("youtube", YouTubePublisherStub())
    worker = LocalWorker(settings, jobs, accounts, ai, publishers)
    scheduler = Scheduler(settings, jobs, worker)
    maintenance = MaintenanceService(settings)
    facebook_accounts = FacebookAccountService(accounts, targets, chrome)
    media = MediaService(settings, contents)
    publishers.register("facebook", FacebookPublisher(settings, chrome, accounts, artifacts, media))
    ai_studio = AIContentStudioService(ai, ai_generations, brands, contents)
    scheduling = SchedulingService(jobs, accounts, targets, contents, publications=publications)
    return Services(
        settings=settings, database=database, accounts=accounts, jobs=jobs, targets=targets,
        contents=contents, brands=brands, ai_generations=ai_generations, publications=publications,
        posting_slots=posting_slots, notifications=notifications,
        chrome=chrome, ai=ai, publishers=publishers, worker=worker, scheduler=scheduler,
        maintenance=maintenance, facebook_accounts=facebook_accounts, media=media,
        ai_studio=ai_studio, scheduling=scheduling, application_lock=asyncio.Lock(),
    )


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()
    configure_logging(settings)
    services = build_services(settings)
    application.state.services = services
    changed = await asyncio.to_thread(services.database.initialize)
    logger.info("Database ready%s", " after migration" if changed else "")
    await services.worker.start()
    await services.scheduler.start()
    await services.maintenance.start()
    if settings.open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(settings.web_url)).start()
    logger.info("Tinix Social Studio %s is ready at %s", __version__, settings.web_url)
    try:
        yield
    finally:
        logger.info("Graceful shutdown started")
        await services.maintenance.stop()
        await services.scheduler.stop()
        await services.worker.stop()
        await services.ai.close()
        closed = await asyncio.to_thread(services.chrome.close_all)
        logger.info("Shutdown complete; closed %s managed Chrome processes", closed)


app = FastAPI(title="Tinix Social Studio", version=__version__, lifespan=lifespan)
app.include_router(router)
app.include_router(content_router)
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
    return FileResponse(static_dir / "index.html")
