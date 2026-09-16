from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.db.analytics_repositories import AnalyticsRepository
from app.db.content_repositories import ContentRepository
from app.db.database import Database
from app.db.publication_repositories import PublicationRepository
from app.db.repositories import AccountRepository, JobRepository, TargetRepository
from app.services.scheduling import SchedulingService
from app.services.ui_analytics import AnalyticsCollectionError, UIAnalyticsCollector, parse_visible_number


class AnalyticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.database=Database(root/"data"/"tinix_social.db",root/"backups");self.database.initialize()
        accounts=AccountRepository(self.database);targets=TargetRepository(self.database);contents=ContentRepository(self.database)
        self.jobs=JobRepository(self.database)
        self.publications=PublicationRepository(self.database);self.analytics=AnalyticsRepository(self.database)
        account=accounts.create("Main","facebook")
        target=targets.sync(account["id"],"facebook",[{"external_id":"p","name":"Page","url":"https://facebook.com/p"}])[0]
        content=contents.create({"title":"Post","caption":"Hello","hashtags":[],"platform_variants":{"facebook":{"caption":"Hello"}}})
        job=SchedulingService(self.jobs,accounts,targets,contents,publications=self.publications).schedule(content["id"],account["id"],[target["id"]],None,True,0,0,"confirm")[0]
        self.release_id=job["publication_release_id"]
        self.account_id=account["id"]

    def tearDown(self) -> None:self.temp.cleanup()

    def test_metric_upsert_is_idempotent_and_keeps_provenance(self) -> None:
        today=datetime.now(timezone.utc).date().isoformat();source="ui_chrome:fixture-v1"
        self.analytics.upsert(self.release_id,{"likes":10,"views":100},metric_date=today,timezone_name="Asia/Bangkok",source=source)
        rows=self.analytics.upsert(self.release_id,{"likes":12,"views":120},metric_date=today,timezone_name="Asia/Bangkok",source=source)
        self.assertEqual(len(rows),2)
        self.assertEqual({row["metric_key"]:row["value"] for row in rows},{"likes":12.0,"views":120.0})
        self.assertTrue(all(row["timezone"]=="Asia/Bangkok" and row["source"]==source for row in rows))
        summary=self.analytics.summary(30)
        self.assertTrue(summary["supported"]);self.assertEqual(summary["metrics"]["likes"]["current"],12)

    def test_manual_connect_records_release_event(self) -> None:
        release=self.analytics.connect_release(self.release_id,"https://facebook.com/p/posts/1","Checked in UI")
        self.assertEqual(release["verification_status"],"verified")
        self.assertEqual(release["verification_method"],"manual_connect")
        self.assertEqual(self.publications.release_events(self.release_id)[0]["event_type"],"manual_connect")

    def test_visible_number_parser_supports_compact_locales(self) -> None:
        self.assertEqual(parse_visible_number("1.2K likes"),1200)
        self.assertEqual(parse_visible_number("2,5 triệu lượt xem"),2_500_000)
        self.assertEqual(parse_visible_number("1.234 lượt thích"),1234)
        self.assertEqual(parse_visible_number("1,234,567 views"),1_234_567)
        self.assertEqual(parse_visible_number("1.234.567 lượt xem"),1_234_567)
        self.assertIsNone(parse_visible_number("Không hiển thị"))

    def test_platform_url_validation_rejects_lookalike_hostnames(self) -> None:
        UIAnalyticsCollector._validate_url("facebook", "https://www.facebook.com/page/posts/1")
        with self.assertRaises(AnalyticsCollectionError):
            UIAnalyticsCollector._validate_url("facebook", "https://notfacebook.com/page/posts/1")

    def test_readiness_uses_release_evidence_and_invalidates_old_selectors(self) -> None:
        job=self.jobs.claim_next()
        self.jobs.transition(job["id"], "checking_login")
        self.jobs.transition(job["id"], "publishing")
        self.jobs.dry_run_ready(job["id"], {"post_url": None})
        readiness=self.publications.account_readiness(
            self.account_id, platform="facebook", selector_version="facebook-web-v1",
        )
        self.assertEqual(readiness[0]["state"], "dry_run_ready")
        stale=self.publications.account_readiness(
            self.account_id, platform="facebook", selector_version="facebook-web-v2",
        )
        self.assertEqual(stale[0]["state"], "review_required")

    def test_readiness_keeps_last_success_when_a_newer_attempt_fails(self) -> None:
        job=self.jobs.claim_next()
        self.jobs.transition(job["id"], "checking_login")
        self.jobs.transition(job["id"], "publishing")
        self.jobs.dry_run_ready(job["id"], {"post_url": None})
        newer = SchedulingService(self.jobs, AccountRepository(self.database), TargetRepository(self.database), ContentRepository(self.database), publications=self.publications).schedule(
            self.jobs.get(job["id"])["content_id"], self.account_id,
            [self.publications.get_release(self.release_id)["target_id"]],
            datetime(2030, 1, 1, tzinfo=timezone.utc), True, 0, 0, "confirm",
        )[0]
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE publication_releases SET status='permanent_failure',updated_at='2999-01-01T00:00:00+00:00' WHERE id=?",
                (newer["publication_release_id"],),
            )
        readiness=self.publications.account_readiness(
            self.account_id, platform="facebook", selector_version="facebook-web-v1",
        )
        self.assertEqual(readiness[0]["state"], "attention_required")
        self.assertEqual(readiness[0]["latest_status"], "permanent_failure")
        self.assertEqual(readiness[0]["last_success_status"], "dry_run_ready")

    def test_readiness_compares_current_selector_with_last_success_after_cancelled_attempt(self) -> None:
        job=self.jobs.claim_next()
        self.jobs.transition(job["id"], "checking_login")
        self.jobs.transition(job["id"], "publishing")
        self.jobs.dry_run_ready(job["id"], {"post_url": None})
        newer = SchedulingService(self.jobs, AccountRepository(self.database), TargetRepository(self.database), ContentRepository(self.database), publications=self.publications).schedule(
            self.jobs.get(job["id"])["content_id"], self.account_id,
            [self.publications.get_release(self.release_id)["target_id"]],
            datetime(2030, 1, 1, tzinfo=timezone.utc), True, 0, 0, "confirm",
        )[0]
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE publication_releases SET selector_version='facebook-web-v2',status='cancelled',updated_at='2999-01-01T00:00:00+00:00' WHERE id=?",
                (newer["publication_release_id"],),
            )

        readiness=self.publications.account_readiness(
            self.account_id, platform="facebook", selector_version="facebook-web-v2",
        )

        self.assertEqual(readiness[0]["state"], "review_required")
        self.assertEqual(readiness[0]["last_success_status"], "dry_run_ready")


if __name__=="__main__":unittest.main()
