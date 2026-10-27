from __future__ import annotations

import tempfile
import unittest
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import json

from app.db.analytics_repositories import AnalyticsFetchInProgress, AnalyticsRepository
from app.db.content_repositories import ContentRepository
from app.db.database import Database
from app.db.publication_repositories import PublicationRepository
from app.db.provider_repositories import ProviderConnectionRepository, ProviderTargetConnectionRepository
from app.db.repositories import AccountRepository, AppSettingsRepository, JobRepository, TargetRepository
from app.services.api_analytics import APIAnalyticsError, YouTubeAPIAnalyticsCollector
from app.services.analytics_scheduler import AnalyticsRefreshScheduler
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

    def test_analytics_refresh_claim_prevents_duplicate_manual_and_scheduled_fetches(self) -> None:
        release_run = self.analytics.start_run(self.release_id, "api_meta_graph")
        with self.assertRaises(AnalyticsFetchInProgress):
            self.analytics.start_run(self.release_id, "api_meta_graph")
        self.analytics.finish_run(release_run, "succeeded", 1)
        target_id = self.publications.get_release(self.release_id)["target_id"]
        channel_run = self.analytics.start_channel_run(target_id, "api_meta_graph")
        with self.assertRaises(AnalyticsFetchInProgress):
            self.analytics.start_channel_run(target_id, "api_meta_graph")
        self.analytics.finish_channel_run(channel_run, "succeeded", 1)

    def test_manual_connect_records_release_event(self) -> None:
        with self.database.connection() as connection:
            connection.execute("UPDATE publication_releases SET status='succeeded' WHERE id=?", (self.release_id,))
        release=self.analytics.connect_release(self.release_id,"https://facebook.com/p/posts/1","Checked in UI")
        self.assertEqual(release["verification_status"],"verified")
        self.assertEqual(release["verification_method"],"manual_connect")
        event=self.publications.release_events(self.release_id)[0]
        self.assertEqual(event["event_type"],"manual_connect")
        self.assertEqual(json.loads(event["metadata_json"])["method"],"manual_confirmation")
        with self.assertRaisesRegex(ValueError,"identity"):
            self.analytics.connect_release(self.release_id,"https://facebook.com/p/posts/2","Different post")

    def test_manual_connect_rejects_dry_run_release(self) -> None:
        with self.assertRaisesRegex(ValueError, "đã đăng"):
            self.analytics.connect_release(self.release_id,"https://facebook.com/p/posts/1","Not published")

    def test_snapshots_use_latest_value_instead_of_adding_daily_counts(self) -> None:
        with self.database.connection() as connection:
            connection.execute("UPDATE publication_releases SET status='succeeded' WHERE id=?", (self.release_id,))
        # Dates are relative to today: summary(30) only covers the last 30 days.
        today = datetime.now(timezone.utc).date()
        self.analytics.upsert(self.release_id,{"views":100},metric_date=(today-timedelta(days=2)).isoformat(),timezone_name="UTC",source="ui_chrome")
        self.analytics.upsert(self.release_id,{"views":150},metric_date=(today-timedelta(days=1)).isoformat(),timezone_name="UTC",source="api_youtube_data_v3")
        summary=self.analytics.summary(30)
        self.assertEqual(summary["metrics"]["views"]["current"],150)

    def test_interval_metrics_sum_days_without_adding_lifetime_snapshots(self) -> None:
        today=datetime.now(timezone.utc).date()
        with self.database.connection() as connection:
            connection.execute("UPDATE publication_releases SET status='succeeded' WHERE id=?", (self.release_id,))
        self.analytics.upsert(self.release_id,{"views":1000},metric_date=(today-timedelta(days=1)).isoformat(),
                              timezone_name="UTC",source="api_youtube_data_v3")
        self.analytics.upsert(self.release_id,{"views":1100},metric_date=today.isoformat(),
                              timezone_name="UTC",source="api_youtube_data_v3")
        for day,value in ((today-timedelta(days=1),8),(today,12)):
            day_text=day.isoformat()
            self.analytics.upsert(self.release_id,{"daily_views":value},metric_date=day_text,
                                  timezone_name="UTC",source="api_youtube_analytics_v2",metric_kind="interval",
                                  period_start=day_text,period_end=day_text)
            self.analytics.upsert(self.release_id,{"daily_views":value+100},metric_date=day_text,
                                  timezone_name="UTC",source="ui_chrome",metric_kind="interval",
                                  period_start=day_text,period_end=day_text)
        summary=self.analytics.summary(30)
        self.assertEqual(summary["metrics"]["views"]["current"],1100)
        self.assertEqual(summary["metrics"]["daily_views"]["current"],20)

    def test_channel_summary_prefers_one_api_value_per_interval_day(self) -> None:
        account=AccountRepository(self.database).create("YouTube","youtube")
        target=TargetRepository(self.database).sync(account["id"],"youtube",[
            {"external_id":"UC_summary1","name":"Summary","url":"https://youtube.com/channel/UC_summary1"},
        ])[0]
        today=datetime.now(timezone.utc).date()
        for delta,value in ((1,10),(0,15)):
            day=(today-timedelta(days=delta)).isoformat()
            self.analytics.upsert_channel(target["id"],{"daily_views":value},metric_date=day,timezone_name="UTC",
                                          source="api_youtube_analytics_v2",metric_kind="interval",
                                          period_start=day,period_end=day)
            self.analytics.upsert_channel(target["id"],{"daily_views":value+100},metric_date=day,timezone_name="UTC",
                                          source="ui_chrome",metric_kind="interval",period_start=day,period_end=day)
        summary=self.analytics.channel_summary(7,target_id=target["id"])
        self.assertEqual(summary["metrics"]["daily_views"]["current"],25)
        history=self.analytics.channel_metric_history(target["id"],7)
        self.assertEqual(len([row for row in history if row["metric_key"]=="daily_views"]),2)

    def test_latest_channel_runs_returns_one_filtered_status_per_target(self) -> None:
        target=TargetRepository(self.database).list(self.account_id)[0]
        older=self.analytics.start_channel_run(target["id"],"api_meta_graph")
        self.analytics.finish_channel_run(older,"unavailable",0,"meta_page_unavailable")
        latest=self.analytics.start_channel_run(target["id"],"api_meta_graph")
        self.analytics.finish_channel_run(latest,"succeeded",2)
        rows=self.analytics.latest_channel_runs(platform="facebook",account_id=self.account_id)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["id"],latest)
        self.assertEqual(rows[0]["status"],"succeeded")
        self.assertEqual(self.analytics.latest_channel_runs()[0]["id"],latest)

    def test_connected_meta_targets_are_listed_before_their_first_fetch(self) -> None:
        class Protector:
            @staticmethod
            def protect_oauth(value): return "protected:" + value
            @staticmethod
            def unprotect_oauth(value): return value.removeprefix("protected:")

        target=TargetRepository(self.database).list(self.account_id)[0]
        connections=ProviderConnectionRepository(self.database,Protector())
        connection=connections.upsert(account_id=self.account_id,provider="meta",access_token="user-token")
        bindings=ProviderTargetConnectionRepository(self.database,Protector())
        bindings.upsert(connection_id=connection["id"],target_id=target["id"],provider="meta",
                        external_target_id="123456789",access_token="page-token",tasks=["ANALYZE"])
        self.assertEqual(self.analytics.connected_meta_target_ids(),[target["id"]])
        self.assertEqual(self.analytics.connected_meta_target_ids(account_id="other-account"),[])
        self.assertEqual(self.analytics.meta_target_connection_statuses(),[{
            "target_id": target["id"], "binding_status": "connected", "connection_status": "connected",
        }])
        connections.set_status(connection["id"],"reauth_required",error_code="token_expired")
        self.assertEqual(self.analytics.connected_meta_target_ids(),[])
        self.assertEqual(self.analytics.meta_target_connection_statuses()[0]["connection_status"],"reauth_required")
        connections.set_status(connection["id"],"connected")
        self.assertEqual(self.analytics.connected_meta_target_ids(),[target["id"]])

    def test_automatic_analytics_refresh_is_opt_in_bounded_and_rotates_due_rows(self) -> None:
        settings=AppSettingsRepository(self.database)
        scheduler=AnalyticsRefreshScheduler(settings,self.analytics,collector=None)
        self.assertFalse(scheduler.status()["enabled"])
        self.assertIsNone(scheduler.status()["next_run_at"])
        with self.assertRaises(ValueError):
            scheduler.configure({"interval_hours":3})
        configured=scheduler.configure({"enabled":True,"interval_hours":12,"days":90,
                                        "posts_per_run":3,"channels_per_run":2})
        self.assertTrue(configured["enabled"])
        self.assertIsNotNone(configured["next_run_at"])
        self.assertEqual((configured["posts_per_run"],configured["channels_per_run"]),(3,2))

        with self.database.connection() as connection:
            connection.execute(
                "UPDATE publication_releases SET platform='youtube',status='succeeded',verification_status='verified',external_release_id='video-123' WHERE id=?",
                (self.release_id,),
            )
        self.assertEqual(self.analytics.due_release_ids(24,10),[self.release_id])
        run_id=self.analytics.start_run(self.release_id,"api_youtube_data_v3")
        self.analytics.finish_run(run_id,"needs_scope",0,"scope_missing")
        self.assertEqual(self.analytics.due_release_ids(24,10),[])

        account=AccountRepository(self.database).create("YouTube channel","youtube")
        target=TargetRepository(self.database).sync(account["id"],"youtube",[
            {"external_id":"UC_rotate1","name":"Rotate","url":"https://youtube.com/channel/UC_rotate1"},
        ])[0]
        self.assertEqual(self.analytics.due_channel_target_ids(24,10),[target["id"]])
        channel_run=self.analytics.start_channel_run(target["id"],"api_youtube_data_v3")
        self.analytics.finish_channel_run(channel_run,"needs_scope",0,"scope_missing")
        self.assertEqual(self.analytics.due_channel_target_ids(24,10),[])

    def test_meta_analytics_scheduler_is_separately_opt_in_and_dispatches_due_targets(self) -> None:
        class FakeMetaCollector:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str]] = []

            async def collect_release(self, release_id: str, days: int) -> dict[str, str]:
                self.calls.append(("post", release_id))
                return {"status": "succeeded"}

            async def collect_channel(self, target_id: str, days: int) -> dict[str, str]:
                self.calls.append(("channel", target_id))
                return {"status": "succeeded"}

        with self.database.connection() as connection:
            connection.execute(
                "UPDATE publication_releases SET platform='facebook',status='succeeded',verification_status='verified',external_release_id='page_post_1' WHERE id=?",
                (self.release_id,),
            )
        target_id = self.publications.get_release(self.release_id)["target_id"]
        collector = FakeMetaCollector()
        scheduler = AnalyticsRefreshScheduler(AppSettingsRepository(self.database), self.analytics, None, collector)
        config = scheduler.configure({"meta_enabled": True, "enabled": False, "posts_per_run": 2, "channels_per_run": 2})
        self.assertTrue(config["meta_enabled"])
        result = asyncio.run(scheduler._run_once(config))
        self.assertEqual((result["posts_attempted"], result["channels_attempted"]), (1, 1))
        self.assertEqual(collector.calls, [("post", self.release_id), ("channel", target_id)])
        self.assertEqual(self.analytics.due_release_ids(24, 10, "youtube", "api_youtube_data_v3"), [])

    def test_youtube_analytics_rate_limit_is_reported_as_actionable_status(self) -> None:
        async def scenario() -> None:
            def handler(_request: httpx.Request) -> httpx.Response:
                return httpx.Response(429,json={"error":{"message":"rate limited"}})
            transport=httpx.MockTransport(handler)
            collector=YouTubeAPIAnalyticsCollector(
                AccountRepository(self.database),TargetRepository(self.database),self.publications,
                self.analytics,object(),object(),client_factory=lambda **kwargs:httpx.AsyncClient(transport=transport,**kwargs),
            )
            with self.assertRaises(APIAnalyticsError) as raised:
                await collector._request_json("https://youtubeanalytics.googleapis.com/v2/reports","token",{},"YouTube Analytics API")
            self.assertEqual(raised.exception.status,"rate_limited")
            self.assertEqual(raised.exception.code,"rate_limited")
        asyncio.run(scenario())

    def test_channel_metric_upsert_keeps_latest_api_provenance(self) -> None:
        account=AccountRepository(self.database).create("YouTube","youtube")
        target=TargetRepository(self.database).sync(account["id"],"youtube",[
            {"external_id":"UC_abc123","name":"Channel","url":"https://youtube.com/channel/UC_abc123"},
        ])[0]
        self.analytics.upsert_channel(target["id"],{"subscribers":10},metric_date="2026-09-20",timezone_name="UTC",source="ui_chrome")
        self.analytics.upsert_channel(target["id"],{"subscribers":20},metric_date="2026-09-20",timezone_name="UTC",source="api_youtube_data_v3")
        rows=self.analytics.channel_metrics(target["id"])
        self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]["value"],rows[0]["source"]),(20.0,"api_youtube_data_v3"))


    def test_collects_release_and_channel_counts_through_official_api(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                database=Database(root/"data"/"tinix_social.db",root/"backups");database.initialize()
                accounts=AccountRepository(database);targets=TargetRepository(database);contents=ContentRepository(database)
                jobs=JobRepository(database);publications=PublicationRepository(database);analytics=AnalyticsRepository(database)
                account=accounts.create("YouTube","facebook")
                target=targets.sync(account["id"],"facebook",[
                    {"external_id":"UC_abc123","name":"Channel","url":"https://facebook.com/channel"},
                ])[0]
                content=contents.create({"title":"Post","caption":"Hello","hashtags":[],"platform_variants":{"facebook":{"caption":"Hello"}}})
                job=SchedulingService(jobs,accounts,targets,contents,publications=publications).schedule(
                    content["id"],account["id"],[target["id"]],None,True,0,0,"confirm",
                )[0]
                release_id=job["publication_release_id"]
                with database.connection() as connection:
                    connection.execute("UPDATE accounts SET platform='youtube' WHERE id=?",(account["id"],))
                    connection.execute("UPDATE publishing_targets SET platform='youtube',target_type='channel' WHERE id=?",(target["id"],))
                    connection.execute("UPDATE publication_releases SET platform='youtube',content_format='video',status='succeeded',external_url='https://youtu.be/abcdefghijk' WHERE id=?",(release_id,))

                calls=[]
                def handler(request: httpx.Request) -> httpx.Response:
                    calls.append(request.url.path)
                    if request.url.path.endswith("/videos"):
                        return httpx.Response(200,json={"items":[{"snippet":{"channelId":"UC_abc123"},"statistics":{"viewCount":"1000","likeCount":"44","commentCount":"9"}}]})
                    if request.url.path.endswith("/reports"):
                        self.assertEqual(request.url.params.get("dimensions"), "day")
                        if request.url.params.get("filters"):
                            self.assertEqual(request.url.params.get("filters"), "video==abcdefghijk")
                        return httpx.Response(200,json={
                            "columnHeaders":[{"name":"day"},{"name":"views"},{"name":"estimatedMinutesWatched"},
                                             {"name":"likes"},{"name":"comments"},{"name":"shares"},
                                             {"name":"subscribersGained"},{"name":"subscribersLost"}],
                            "rows":[["2026-09-20",12,5.5,2,1,1,3,0]],
                        })
                    return httpx.Response(200,json={"items":[{"statistics":{"viewCount":"9000","subscriberCount":"300","videoCount":"12"}}]})
                transport=httpx.MockTransport(handler)
                class Connections:
                    def list(self, **kwargs: object) -> list[dict[str, object]]:
                        return [{"id":"conn","provider":"youtube","status":"connected","transport":"official_api",
                                 "external_account_id":"UC_abc123","scopes":["https://www.googleapis.com/auth/youtube.readonly"]}]
                class ProviderAccounts:
                    async def access_token(self, connection_id: str) -> str:
                        return "fake-token"
                collector=YouTubeAPIAnalyticsCollector(
                    accounts,targets,publications,analytics,Connections(),ProviderAccounts(),
                    client_factory=lambda **kwargs:httpx.AsyncClient(transport=transport,**kwargs),
                )
                post=await collector.collect_release(release_id)
                channel=await collector.collect_channel(target["id"])
                self.assertEqual(post["status"],"succeeded")
                self.assertEqual({m["metric_key"]:m["value"] for m in post["metrics"] if m["release_id"]==release_id},
                                 {"views":1000.0,"likes":44.0,"comments":9.0})
                self.assertEqual(channel["status"],"succeeded")
                self.assertEqual({m["metric_key"]:m["value"] for m in channel["metrics"]},
                                 {"views":9000.0,"subscribers":300.0,"videos":12.0})
                self.assertEqual(post["trend"]["status"], "succeeded")
                self.assertEqual(channel["trend"]["status"], "succeeded")
                post_trend = [item for item in self.analytics_rows(analytics, release_id)
                              if item["source"] == "api_youtube_analytics_v2"]
                self.assertEqual({item["metric_key"]: item["value"] for item in post_trend}, {
                    "daily_views": 12.0, "watch_time_minutes": 5.5, "daily_likes": 2.0,
                    "daily_comments": 1.0, "daily_shares": 1.0,
                    "daily_subscribers_gained": 3.0, "daily_subscribers_lost": 0.0,
                })
                self.assertEqual({item["metric_key"]: item["unit"] for item in post_trend}["watch_time_minutes"], "minutes")
                self.assertEqual(calls,["/youtube/v3/videos","/v2/reports","/youtube/v3/channels","/v2/reports"])
        asyncio.run(scenario())

    @staticmethod
    def analytics_rows(analytics: AnalyticsRepository, release_id: str) -> list[dict[str, object]]:
        return analytics.for_release(release_id)

    def test_video_url_parser_accepts_youtube_formats_and_rejects_other_hosts(self) -> None:
        parser=YouTubeAPIAnalyticsCollector.video_id_from_url
        self.assertEqual(parser("https://youtu.be/abcdefghijk"),"abcdefghijk")
        self.assertEqual(parser("https://youtube.com/shorts/abcdefghijk"),"abcdefghijk")
        self.assertIsNone(parser("https://notyoutube.com/watch?v=abcdefghijk"))

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
