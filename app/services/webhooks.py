from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging

import httpx

from app.db.automation_repositories import WebhookRepository


logger=logging.getLogger(__name__)


class WebhookDispatcher:
    def __init__(self,repository:WebhookRepository,poll_seconds:float=2)->None:
        self.repository=repository;self.poll_seconds=poll_seconds;self._stop=asyncio.Event();self._task=None;self.state="stopped"

    async def start(self)->None:self.state="running";self._task=asyncio.create_task(self._run(),name="webhook-dispatcher")
    async def stop(self)->None:
        self._stop.set()
        if self._task:await self._task
        self.state="stopped"

    async def _run(self)->None:
        async with httpx.AsyncClient(timeout=15,follow_redirects=False) as client:
            while not self._stop.is_set():
                item=await asyncio.to_thread(self.repository.claim)
                if item:
                    body=json.dumps(item["payload"],ensure_ascii=False,separators=(",",":")).encode()
                    signature=hmac.new(item["subscription"]["secret"].encode(),body,hashlib.sha256).hexdigest()
                    try:
                        response=await client.post(item["subscription"]["url"],content=body,headers={"Content-Type":"application/json","X-Tinix-Event":item["event_type"],"X-Tinix-Signature":"sha256="+signature,"X-Tinix-Delivery":item["id"]})
                        response.raise_for_status();await asyncio.to_thread(self.repository.finish,item["id"])
                    except Exception as exc:
                        logger.warning("Webhook %s delivery failed: %s",item["id"],exc);await asyncio.to_thread(self.repository.finish,item["id"],str(exc))
                    continue
                try:await asyncio.wait_for(self._stop.wait(),timeout=self.poll_seconds)
                except asyncio.TimeoutError:pass
