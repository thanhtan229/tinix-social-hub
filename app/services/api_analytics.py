from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import httpx

from app.db.analytics_repositories import AnalyticsRepository
from app.db.provider_repositories import ProviderConnectionRepository
from app.db.publication_repositories import PublicationRepository
from app.db.repositories import AccountRepository, TargetRepository
from app.services.meta_accounts import MetaGraphAPIError
from app.services.provider_accounts import ProviderAccountService


class APIAnalyticsError(RuntimeError):
    def __init__(self, code: str, message: str, status: str = "failed") -> None:
        self.code = code
        self.status = status
        super().__init__(message)


class YouTubeAPIAnalyticsCollector:
    """Read-only YouTube Data API analytics bound to verified Tinix targets."""

    source = "api_youtube_data_v3"
    api_root = "https://www.googleapis.com/youtube/v3"
    reports_url = "https://youtubeanalytics.googleapis.com/v2/reports"
    report_source = "api_youtube_analytics_v2"
    report_metrics = (
        ("daily_views", "views", "count"),
        ("watch_time_minutes", "estimatedMinutesWatched", "minutes"),
        ("daily_likes", "likes", "count"),
        ("daily_comments", "comments", "count"),
        ("daily_shares", "shares", "count"),
        ("daily_subscribers_gained", "subscribersGained", "count"),
        ("daily_subscribers_lost", "subscribersLost", "count"),
    )

    def __init__(
        self,
        accounts: AccountRepository,
        targets: TargetRepository,
        publications: PublicationRepository,
        analytics: AnalyticsRepository,
        connections: ProviderConnectionRepository,
        provider_accounts: ProviderAccountService,
        client_factory: Callable[..., Any] = httpx.AsyncClient,
    ) -> None:
        self.accounts = accounts
        self.targets = targets
        self.publications = publications
        self.analytics = analytics
        self.connections = connections
        self.provider_accounts = provider_accounts
        self.client_factory = client_factory

    @staticmethod
    def video_id_from_url(url: str | None) -> str | None:
        if not url:
            return None
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        video_id: str | None = None
        if host in {"youtu.be", "www.youtu.be"}:
            video_id = parsed.path.strip("/").split("/", 1)[0]
        elif host == "youtube.com" or host.endswith(".youtube.com"):
            if parsed.path == "/watch":
                video_id = parse_qs(parsed.query).get("v", [None])[0]
            else:
                pieces = [piece for piece in parsed.path.split("/") if piece]
                if len(pieces) >= 2 and pieces[0] in {"shorts", "embed", "live"}:
                    video_id = pieces[1]
        if video_id and re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id):
            return video_id
        return None

    def _connection(self, account_id: str, target_external_id: str) -> dict[str, Any]:
        connection = next(
            (
                item for item in self.connections.list(account_id=account_id, transport="official_api")
                if item.get("provider") == "youtube"
                and item.get("status") == "connected"
                and item.get("external_account_id") == target_external_id
            ),
            None,
        )
        if not connection:
            raise APIAnalyticsError(
                "target_connection_mismatch",
                "Chưa có kết nối YouTube API được xác minh cho đúng channel đích.",
                "needs_connection",
            )
        scopes = set(connection.get("scopes") or [])
        if "https://www.googleapis.com/auth/youtube.readonly" not in scopes:
            raise APIAnalyticsError(
                "scope_missing", "Kết nối YouTube cần quyền đọc channel và video.", "needs_scope",
            )
        return connection

    async def _get_json(self, endpoint: str, token: str, params: dict[str, str]) -> dict[str, Any]:
        return await self._request_json(f"{self.api_root}/{endpoint}", token, params, "YouTube Data API")

    async def _request_json(
        self, url: str, token: str, params: dict[str, str], api_name: str,
    ) -> dict[str, Any]:
        try:
            async with self.client_factory(timeout=30) as client:
                response = await client.get(
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.HTTPError as exc:
            raise APIAnalyticsError("provider_unavailable", f"Không kết nối được {api_name}.") from exc
        if response.status_code == 401:
            raise APIAnalyticsError("reauth_required", "Kết nối YouTube cần cấp quyền lại.", "needs_connection")
        if response.status_code == 403:
            raise APIAnalyticsError("permission_or_quota", f"{api_name} từ chối quyền đọc hoặc đã hết quota.", "needs_scope")
        if response.status_code == 429:
            raise APIAnalyticsError("rate_limited", f"{api_name} đang giới hạn tần suất; hãy đợi trước khi thử lại.", "rate_limited")
        if response.status_code == 404:
            raise APIAnalyticsError("not_found", "YouTube không tìm thấy video hoặc channel đã liên kết.", "unsupported")
        if response.status_code >= 500:
            raise APIAnalyticsError("provider_unavailable", f"{api_name} tạm thời không khả dụng.")
        try:
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise APIAnalyticsError("invalid_response", "YouTube trả về phản hồi không hợp lệ.") from exc
        if not isinstance(body, dict):
            raise APIAnalyticsError("invalid_response", "YouTube trả về dữ liệu không hợp lệ.")
        return body

    @staticmethod
    def _report_dates(days: int) -> tuple[str, str]:
        # Reports are delayed; end two days ago so an incomplete latest day is not shown as zero.
        end = datetime.now(timezone.utc).date() - timedelta(days=2)
        start = end - timedelta(days=max(1, min(days, 90)) - 1)
        return start.isoformat(), end.isoformat()

    async def _collect_report(
        self, *, token: str, channel_id: str, target_id: str,
        release_id: str | None = None, video_id: str | None = None, days: int = 30,
    ) -> dict[str, Any]:
        run_id = (
            await asyncio.to_thread(self.analytics.start_run, release_id, self.report_source)
            if release_id else await asyncio.to_thread(
                self.analytics.start_channel_run, target_id, self.report_source,
            )
        )
        start_date, end_date = self._report_dates(days)
        metric_columns = [source for _key, source, _unit in self.report_metrics]
        params = {
            "ids": f"channel=={channel_id}",
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": "day",
            "metrics": ",".join(metric_columns),
            "sort": "day",
            "maxResults": "1000",
        }
        if video_id:
            params["filters"] = f"video=={video_id}"
        try:
            body = await self._request_json(self.reports_url, token, params, "YouTube Analytics API")
            headers = body.get("columnHeaders") or []
            rows = body.get("rows") or []
            names = [str(item.get("name") or "") for item in headers if isinstance(item, dict)]
            if not names or "day" not in names or any(name not in names for name in metric_columns):
                if rows or headers:
                    raise APIAnalyticsError("invalid_response", "YouTube Analytics trả cấu trúc báo cáo không hợp lệ.")
            index = {name: position for position, name in enumerate(names)}
            stored: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, list) or len(row) != len(names):
                    raise APIAnalyticsError("invalid_response", "YouTube Analytics trả dòng báo cáo không hợp lệ.")
                day = str(row[index["day"]])
                try:
                    datetime.strptime(day, "%Y-%m-%d")
                    values = {
                        key: float(row[index[provider_name]])
                        for key, provider_name, _unit in self.report_metrics
                        if row[index[provider_name]] is not None
                    }
                except (ValueError, TypeError, IndexError) as exc:
                    raise APIAnalyticsError("invalid_response", "YouTube Analytics trả giá trị metric không hợp lệ.") from exc
                if not values:
                    continue
                common = {
                    "metric_date": day, "timezone_name": "UTC", "source": self.report_source,
                    "metric_kind": "interval", "period_start": day, "period_end": day,
                    "provider_metric_names": {
                        key: provider_name for key, provider_name, _unit in self.report_metrics
                    },
                    "provider_metric_units": {
                        key: unit for key, _provider_name, unit in self.report_metrics
                    },
                }
                if release_id:
                    metrics = await asyncio.to_thread(self.analytics.upsert, release_id, values, **common)
                else:
                    metrics = await asyncio.to_thread(self.analytics.upsert_channel, target_id, values, **common)
                stored.extend(item for item in metrics if item.get("source") == self.report_source and item.get("metric_date") == day)
            await asyncio.to_thread(self.analytics.finish_run if release_id else self.analytics.finish_channel_run,
                                    run_id, "succeeded" if stored else "no_data", len(stored))
            return {
                "status": "succeeded" if stored else "no_data", "source": self.report_source,
                "metrics": stored, "range": {"start": start_date, "end": end_date},
            }
        except APIAnalyticsError as exc:
            finish = self.analytics.finish_run if release_id else self.analytics.finish_channel_run
            await asyncio.to_thread(finish, run_id, exc.status, 0, exc.code)
            return {"status": exc.status, "source": self.report_source, "code": exc.code,
                    "message": str(exc), "metrics": [], "range": {"start": start_date, "end": end_date}}
        except Exception:
            finish = self.analytics.finish_run if release_id else self.analytics.finish_channel_run
            await asyncio.to_thread(finish, run_id, "failed", 0, "provider_error")
            raise


    async def _token(self, connection: dict[str, Any]) -> str:
        try:
            return await self.provider_accounts.access_token(connection["id"])
        except (KeyError, RuntimeError) as exc:
            raise APIAnalyticsError(
                "reauth_required", "Kết nối YouTube cần cấp quyền lại.", "needs_connection",
            ) from exc

    async def collect_release(self, release_id: str, days: int = 30) -> dict[str, Any]:
        release = await asyncio.to_thread(self.publications.get_release, release_id)
        if not release:
            raise KeyError(release_id)
        if release.get("status") != "succeeded" and not (
            release.get("status") == "unknown_result" and release.get("verification_status") == "verified"
        ):
            raise APIAnalyticsError(
                "release_not_verified", "Chỉ thu thập metrics cho bài đã đăng hoặc đã đối soát.",
                "unsupported",
            )
        target = await asyncio.to_thread(self.targets.get, release["target_id"])
        if not target or target.get("platform") != "youtube":
            raise APIAnalyticsError("target_missing", "Không tìm thấy YouTube channel đích.", "unsupported")
        video_id = release.get("external_release_id") or self.video_id_from_url(release.get("external_url"))
        if not video_id:
            raise APIAnalyticsError(
                "post_id_missing", "Release chưa có YouTube video ID; hãy đối soát URL bài đăng.",
                "needs_reconciliation",
            )
        run_id = await asyncio.to_thread(self.analytics.start_run, release_id, self.source)
        try:
            connection = self._connection(release["account_id"], target["external_id"])
            token = await self._token(connection)
            body = await self._get_json(
                "videos", token, {"part": "statistics,snippet", "id": str(video_id)},
            )
            items = body.get("items") or []
            if not items:
                raise APIAnalyticsError("post_unavailable", "Video không có metrics đọc được.", "unsupported")
            video_channel_id = (items[0].get("snippet") or {}).get("channelId")
            if video_channel_id != target["external_id"]:
                raise APIAnalyticsError(
                    "target_identity_mismatch", "Video không thuộc channel YouTube đã chọn.", "unsupported",
                )
            statistics = items[0].get("statistics") or {}
            values = {
                key: float(statistics[source_key])
                for key, source_key in (
                    ("views", "viewCount"), ("likes", "likeCount"), ("comments", "commentCount"),
                )
                if statistics.get(source_key) is not None
            }
            if not values:
                raise APIAnalyticsError("metrics_empty", "YouTube hiện không trả metrics cho video.", "unsupported")
            zone = ZoneInfo(release.get("timezone") or "Asia/Bangkok")
            observed_at = datetime.now(timezone.utc).astimezone(zone)
            metrics = await asyncio.to_thread(
                self.analytics.upsert, release_id, values,
                metric_date=observed_at.date().isoformat(), timezone_name=zone.key,
                source=self.source, metric_kind="snapshot",
            )
            await asyncio.to_thread(self.analytics.finish_run, run_id, "succeeded", len(values))
            trend = await self._collect_report(
                token=token, channel_id=target["external_id"], target_id=target["id"],
                release_id=release_id, video_id=str(video_id), days=days,
            )
            return {"status": "succeeded", "source": self.source, "metrics": metrics,
                    "trend": trend}
        except APIAnalyticsError as exc:
            await asyncio.to_thread(self.analytics.finish_run, run_id, exc.status, 0, exc.code)
            return {"status": exc.status, "code": exc.code, "message": str(exc), "metrics": []}
        except Exception:
            await asyncio.to_thread(self.analytics.finish_run, run_id, "failed", 0, "provider_error")
            raise

    async def collect_channel(self, target_id: str, days: int = 30) -> dict[str, Any]:
        target = await asyncio.to_thread(self.targets.get, target_id)
        if not target:
            raise KeyError(target_id)
        if target.get("platform") != "youtube":
            return {"status": "unsupported", "message": "Channel analytics API chưa hỗ trợ nền tảng này.", "metrics": []}
        source = self.source
        run_id = await asyncio.to_thread(self.analytics.start_channel_run, target_id, source)
        try:
            connection = self._connection(target["account_id"], target["external_id"])
            token = await self._token(connection)
            body = await self._get_json(
                "channels", token, {"part": "statistics", "id": str(target["external_id"])},
            )
            items = body.get("items") or []
            if not items:
                raise APIAnalyticsError("channel_unavailable", "YouTube không trả metrics cho channel.", "unsupported")
            statistics = items[0].get("statistics") or {}
            values = {
                key: float(statistics[source_key])
                for key, source_key in (
                    ("views", "viewCount"),
                    ("subscribers", "subscriberCount"),
                    ("videos", "videoCount"),
                )
                if statistics.get(source_key) is not None
            }
            if not values:
                raise APIAnalyticsError("metrics_empty", "YouTube hiện không trả channel metrics.", "unsupported")
            zone = ZoneInfo("UTC")
            observed_at = datetime.now(timezone.utc)
            metrics = await asyncio.to_thread(
                self.analytics.upsert_channel, target_id, values,
                metric_date=observed_at.date().isoformat(), timezone_name=zone.key,
                source=source, metric_kind="snapshot",
            )
            await asyncio.to_thread(self.analytics.finish_channel_run, run_id, "succeeded", len(values))
            trend = await self._collect_report(
                token=token, channel_id=target["external_id"], target_id=target_id, days=days,
            )
            return {"status": "succeeded", "source": source, "metrics": metrics,
                    "trend": trend}
        except APIAnalyticsError as exc:
            await asyncio.to_thread(self.analytics.finish_channel_run, run_id, exc.status, 0, exc.code)
            return {"status": exc.status, "code": exc.code, "message": str(exc), "metrics": []}
        except Exception:
            await asyncio.to_thread(self.analytics.finish_channel_run, run_id, "failed", 0, "provider_error")
            raise


class MetaAPIAnalyticsCollector:
    """Read-only snapshots for Facebook Page posts and aggregate Page counts."""

    source = "api_meta_graph"

    def __init__(self, targets: TargetRepository, publications: PublicationRepository,
                 analytics: AnalyticsRepository, meta_accounts: Any, target_connections: Any) -> None:
        self.targets = targets
        self.publications = publications
        self.analytics = analytics
        self.meta_accounts = meta_accounts
        self.target_connections = target_connections

    @staticmethod
    def _summary(body: dict[str, Any], key: str) -> float | None:
        summary = ((body.get(key) or {}).get("summary") or {})
        value = summary.get("total_count")
        return float(value) if value is not None else None

    @staticmethod
    def _graph_error(exc: MetaGraphAPIError, entity: str) -> tuple[str, str, str]:
        code = str(exc.graph_code or "")
        detail = str(exc).lower()
        if exc.status_code in {401, 403} or code in {"10", "200", "190"}:
            return (
                "needs_connection", "meta_permission_denied",
                "Meta từ chối quyền đọc. Kiểm tra lại System User token, quyền Page và trạng thái Meta App.",
            )
        if exc.status_code == 429 or code in {"4", "17", "32", "613"}:
            return "rate_limited", "meta_rate_limited", "Meta đang giới hạn tần suất; hãy chờ rồi thử lại."
        missing_object = any(phrase in detail for phrase in (
            "object does not exist", "does not exist, cannot be loaded",
            "unsupported get request", "cannot be loaded due to missing permissions",
        ))
        if code == "100" and missing_object:
            if entity == "post":
                message = "Meta không còn cho phép đọc bài này. Bài có thể đã bị xóa hoặc quyền truy cập đã đổi; số liệu đã lưu trước đây được giữ nguyên."
                return "unavailable", "meta_post_unavailable", message
            message = "Meta không còn cho phép đọc Page này. Page có thể đã bị gỡ quyền hoặc không còn khả dụng; snapshot đã lưu trước đây được giữ nguyên."
            return "unavailable", "meta_page_unavailable", message
        return "failed", "meta_provider_error", f"Meta từ chối yêu cầu analytics: {exc}"

    async def collect_release(self, release_id: str, days: int = 30) -> dict[str, Any]:
        release = await asyncio.to_thread(self.publications.get_release, release_id)
        if not release:
            raise KeyError(release_id)
        if release.get("platform") != "facebook" or release.get("status") != "succeeded":
            return {"status": "unsupported", "message": "Chỉ hỗ trợ bài Facebook đã đăng và xác nhận.", "metrics": []}
        post_id = release.get("external_release_id")
        if not post_id:
            return {"status": "needs_reconciliation", "message": "Release chưa có Facebook post ID để tra cứu.", "metrics": []}
        binding = await asyncio.to_thread(self.target_connections.for_target, release["target_id"], release.get("connection_id"))
        if not binding:
            return {"status": "needs_connection", "message": "Không còn Page API binding cho Page của bài đăng.", "metrics": []}
        run_id = await asyncio.to_thread(self.analytics.start_run, release_id, self.source)
        try:
            is_video = release.get("content_format") in {"video", "reel"}
            fields = "id,from,permalink_url,likes.limit(0).summary(true),comments.limit(0).summary(true)"
            fields += ",views" if is_video else ",shares"
            body = await self.meta_accounts.graph_request(
                binding["connection_id"], binding["id"], "GET", str(post_id),
                params={"fields": fields},
            )
            page_id = str((body.get("from") or {}).get("id") or "")
            if str(body.get("id") or "") != str(post_id) or page_id != binding["external_target_id"]:
                raise APIAnalyticsError("target_identity_mismatch", "Bài không thuộc đúng Facebook Page đã liên kết.", "unsupported")
            values: dict[str, float] = {}
            names: dict[str, str] = {}
            for key, source_name in (("likes", "likes"), ("comments", "comments")):
                value = self._summary(body, source_name)
                if value is not None:
                    values[key] = value; names[key] = f"{source_name}.summary.total_count"
            if is_video:
                if body.get("views") is not None:
                    values["views"] = float(body["views"]); names["views"] = "views"
            else:
                shares = body.get("shares")
                if isinstance(shares, dict) and shares.get("count") is not None:
                    values["shares"] = float(shares["count"]); names["shares"] = "shares.count"
            if not values:
                raise APIAnalyticsError("metrics_empty", "Meta không trả metrics tương tác cho bài này.", "unsupported")
            observed = datetime.now(timezone.utc)
            rows = await asyncio.to_thread(
                self.analytics.upsert, release_id, values, metric_date=observed.date().isoformat(),
                timezone_name="UTC", source=self.source, provider_metric_names=names,
            )
            await asyncio.to_thread(self.analytics.finish_run, run_id, "succeeded", len(values))
            post_url = body.get("permalink_url")
            if isinstance(post_url, str) and post_url.startswith("/") and not post_url.startswith("//"):
                post_url = f"https://www.facebook.com{post_url}"
            return {"status": "succeeded", "source": self.source, "metrics": rows, "post_url": post_url}
        except APIAnalyticsError as exc:
            await asyncio.to_thread(self.analytics.finish_run, run_id, exc.status, 0, exc.code)
            return {"status": exc.status, "code": exc.code, "message": str(exc), "metrics": []}
        except MetaGraphAPIError as exc:
            status, code, message = self._graph_error(exc, "post")
            await asyncio.to_thread(self.analytics.finish_run, run_id, status, 0, code)
            return {"status": status, "code": code, "message": message, "metrics": []}
        except Exception:
            await asyncio.to_thread(self.analytics.finish_run, run_id, "failed", 0, "provider_error")
            raise

    async def collect_channel(self, target_id: str, days: int = 30) -> dict[str, Any]:
        target = await asyncio.to_thread(self.targets.get, target_id)
        if not target:
            raise KeyError(target_id)
        if target.get("platform") != "facebook":
            return {"status": "unsupported", "message": "Meta Page analytics không áp dụng cho nền tảng này.", "metrics": []}
        binding = await asyncio.to_thread(self.target_connections.for_target, target_id)
        run_id = await asyncio.to_thread(self.analytics.start_channel_run, target_id, self.source)
        try:
            if not binding:
                raise APIAnalyticsError("needs_connection", "Page chưa được liên kết Meta API.", "needs_connection")
            body = await self.meta_accounts.graph_request(
                binding["connection_id"], binding["id"], "GET", binding["external_target_id"],
                params={"fields": "id,name,followers_count,fan_count"},
            )
            if str(body.get("id") or "") != binding["external_target_id"]:
                raise APIAnalyticsError("target_identity_mismatch", "Meta Page ID không khớp Page đã chọn.", "unsupported")
            values: dict[str, float] = {}
            names: dict[str, str] = {}
            for key, source_name in (("followers", "followers_count"), ("page_likes", "fan_count")):
                if body.get(source_name) is not None:
                    values[key] = float(body[source_name]); names[key] = source_name
            if not values:
                raise APIAnalyticsError("metrics_empty", "Meta không trả số liệu tổng hợp cho Page.", "unsupported")
            observed = datetime.now(timezone.utc)
            rows = await asyncio.to_thread(
                self.analytics.upsert_channel, target_id, values,
                metric_date=observed.date().isoformat(), timezone_name="UTC", source=self.source,
                provider_metric_names=names,
            )
            await asyncio.to_thread(self.analytics.finish_channel_run, run_id, "succeeded", len(values))
            return {"status": "succeeded", "source": self.source, "metrics": rows, "trend": {"status": "unsupported", "message": "Meta endpoint này chỉ trả snapshot hiện tại; chưa có chuỗi lịch sử."}}
        except APIAnalyticsError as exc:
            await asyncio.to_thread(self.analytics.finish_channel_run, run_id, exc.status, 0, exc.code)
            return {"status": exc.status, "code": exc.code, "message": str(exc), "metrics": []}
        except MetaGraphAPIError as exc:
            status, code, message = self._graph_error(exc, "page")
            await asyncio.to_thread(self.analytics.finish_channel_run, run_id, status, 0, code)
            return {"status": status, "code": code, "message": message, "metrics": []}
        except Exception:
            await asyncio.to_thread(self.analytics.finish_channel_run, run_id, "failed", 0, "provider_error")
            raise
