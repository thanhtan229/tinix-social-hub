from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.db.automation_repositories import APITokenRepository, WebhookRepository
from app.db.database import Database
from app.db.repositories import AccountRepository, JobRepository


class AutomationSurfaceTests(unittest.TestCase):
    def setUp(self)->None:
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.database=Database(self.root/"data"/"tinix_social.db",self.root/"backups");self.database.initialize()

    def tearDown(self)->None:self.temp.cleanup()

    def test_default_token_is_protected_and_scope_checked(self)->None:
        repository=APITokenRepository(self.database,self.root/"data")
        token=repository.ensure_default()
        protected=(self.root/"data"/"secrets"/"local_api_token.protected").read_text(encoding="utf-8")
        self.assertNotIn(token,protected)
        self.assertIsNotNone(repository.verify(token,"publish"))
        self.assertIsNone(repository.verify("wrong","read"))

    def test_webhook_event_uses_durable_outbox_without_exposing_secret(self)->None:
        hooks=WebhookRepository(self.database)
        created=hooks.create("n8n","http://127.0.0.1:5678/webhook/tinix","a"*32,["job.status_changed"])
        self.assertNotIn("secret",created)
        account=AccountRepository(self.database).create("Main","facebook")
        jobs=JobRepository(self.database);job=jobs.create("publish",{},account["id"],None,max_attempts=1)
        jobs.claim_next();jobs.fail(job["id"],"fixture failure")
        outbox=hooks.outbox()
        self.assertEqual(outbox[0]["event_type"],"job.status_changed")
        claimed=hooks.claim();self.assertEqual(claimed["subscription"]["secret"],"a"*32)
        hooks.finish(claimed["id"])
        self.assertEqual(hooks.outbox()[0]["status"],"sent")


if __name__=="__main__":unittest.main()
