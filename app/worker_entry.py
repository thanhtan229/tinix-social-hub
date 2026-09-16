from __future__ import annotations

import asyncio
import logging
import signal

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.main import build_services


logger=logging.getLogger(__name__)


async def run()->None:
    settings=get_settings();configure_logging(settings);services=build_services(settings)
    await asyncio.to_thread(services.database.initialize)
    await asyncio.to_thread(services.accounts.migrate_legacy_credentials)
    stop=asyncio.Event();loop=asyncio.get_running_loop()
    for name in ("SIGINT","SIGTERM"):
        signum=getattr(signal,name,None)
        if signum:
            try:loop.add_signal_handler(signum,stop.set)
            except NotImplementedError:pass
    await services.worker.start();await services.scheduler.start()
    logger.info("Standalone Tinix worker started against %s",settings.database_path)
    try:await stop.wait()
    finally:
        await services.scheduler.stop();await services.worker.stop();await services.ai.close()
        await asyncio.to_thread(services.chrome.close_all)


if __name__=="__main__":asyncio.run(run())
