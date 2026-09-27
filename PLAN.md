# PLAN — API publishing và analytics cho Tinix Social Hub

**Trạng thái:** kế hoạch triển khai cho Codex; chưa sửa mã ứng dụng.  
**Ngày lập:** 27-09-2026.  
**Đầu vào:** yêu cầu hiện tại, [RESEARCH_postiz.md](RESEARCH_postiz.md), mã Tinix tại commit a097762 (16-09-2026), [PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md), [PLATFORM_ARCHITECTURE.md](docs/PLATFORM_ARCHITECTURE.md).  
**Thiếu đầu vào:** Không tìm thấy PROJECT_STATUS.md ở thư mục dự án hoặc thư mục cha khi lập kế hoạch. Trước khi bắt đầu giai đoạn triển khai, Codex phải đọc file đó nếu được cung cấp; ghi nhận mọi thay đổi so với kế hoạch này rồi mới sửa mã. Không tự suy diễn nội dung của file.

## 1. Mục tiêu và kết quả phải giao

Bổ sung đường đăng bài qua API chính thức và số liệu **theo từng bài đã đăng** lẫn **cấp kênh** cho các nền tảng hiện có trong Tinix, theo đúng quyền mà từng nền tảng cấp. Tận dụng kiến trúc local đang hoạt động: Platform App, OAuth Account Connection, PublisherRouter, SchedulingService, Content/Plan/Release/Job, durable worker, release metrics và giao diện Analytics. Chrome tiếp tục là một transport có thể chọn; thu thập analytics có thể dùng API ngay cả khi release trước đó đăng bằng Chrome, sau khi xác minh danh tính bài/kênh.

Kết quả cần giao theo từng provider:

1. Danh mục khả năng công khai, trung thực: format có thể đăng qua API; loại metric theo bài/kênh; scope; account/target hỗ trợ; lý do chưa sẵn sàng.
2. OAuth/connection/target binding an toàn. Credential nhà phát triển và token tài khoản được tách biệt, bảo vệ bằng DPAPI, không trả secret ra UI/API/log.
3. API publisher cho format được phép, với dry-run không tạo bài, approval, route đóng băng, commit point, verification và trạng thái kết quả chưa xác định.
4. API analytics theo bài và kênh, lịch sử thu thập, nguồn dữ liệu, thời điểm cập nhật, trạng thái thiếu quyền/không hỗ trợ/dữ liệu cũ.
5. UI cấu hình, đăng và xem metrics theo provider; mô hình tổng hợp không đếm trùng snapshot.
6. Bộ test thích hợp, build desktop, thay server local đúng dự án, xác nhận health/runtime và báo cáo cuối.

**Không hứa parity 34 nền tảng của Postiz.** Danh sách ban đầu chỉ là 5 nền tảng Tinix hiện có: Facebook, Instagram, TikTok, YouTube, X. Readiness được nâng từng format/metric khi có quyền API và bằng chứng thực tế.

## 2. Phần đáng áp dụng từ nghiên cứu Postiz

| Học từ Postiz | Áp dụng vào Tinix | Mức |
|---|---|---|
| Provider contract mô tả format, settings, quyền và analytics | Mở rộng catalog/adapter hiện có; API và UI đọc cùng capability | Bắt buộc |
| Analytics theo bài gắn external post ID | Dùng publication_release làm đơn vị định danh, lưu ID/URL/phương thức xác minh | Bắt buộc |
| Analytics cấp channel | Lưu snapshot theo publishing_target, không gộp nhiều Page/channel của cùng account | Bắt buộc |
| Quy trình ghép bài thiếu ID | Cho người dùng xác nhận bài thật; không tự ghép bằng caption/URL gần giống | Bắt buộc |
| Hiển thị giới hạn platform/metric | Unsupported, permission missing, no data, stale, fetch failed là các trạng thái riêng | Bắt buộc |
| Composer validation theo provider | Ràng buộc format/media/settings trước khi lập lịch và trước lệnh API | Cần cho từng API publisher |
| Reusable channel sets, day view, review link, RSS/plugs, agent | Làm sau nếu có nhu cầu; không cản công việc API/analytics hiện tại | Hoãn |

Giữ mô hình Windows local, SQLite và worker hiện tại. Không thêm Temporal/Redis/Postgres, multi-tenant, billing hay code sao chép từ Postiz. Xem [RESEARCH_postiz.md](RESEARCH_postiz.md) để biết lý do sản phẩm và rủi ro giấy phép AGPL của upstream.

## 3. Baseline đã kiểm tra trong mã Tinix

- Schema mới nhất trong app/db/database.py hiện là **migration 18**. Migration 13 có account_connections, oauth_states và route snapshot; migration 15 có platform_apps; migration 9 có release_metrics và analytics_fetch_runs.
- app/platforms/catalog.py chứa 5 platform. Official API mới sẵn sàng cho YouTube video/Short; Facebook, Instagram, TikTok và X vẫn là scaffold, không được nâng nhãn sớm.
- app/services/provider_accounts.py chỉ có luồng OAuth/refresh YouTube. app/platforms/providers/youtube.py là official publisher duy nhất. app/main.py đăng ký Chrome publisher của 5 nền tảng và YouTube API publisher.
- app/services/publisher_router.py chọn transport theo account; app/services/scheduling.py kiểm tra approval, target, dry-run evidence và tạo snapshot Plan → Release → Job. app/services/worker.py và app/db/repositories.py lưu attempt/commit, giữ quy tắc unknown_result và không retry mù.
- app/services/ui_analytics.py chỉ đọc số liệu hiển thị trong Chrome sau khi release có URL. app/db/analytics_repositories.py lưu snapshot từng bài; app/static/js/analytics.js hiển thị tổng hợp và thu thập thủ công. Chưa có collector API, bảng analytics cấp kênh hoặc refresh định kỳ.
- app/db/analytics_repositories.py::summary hiện cộng các giá trị tích lũy từ nhiều ngày và nhiều nguồn. Cùng một bài có 100 lượt thích hôm qua và 110 hôm nay có thể bị cộng thành 210. Phải sửa định nghĩa tổng hợp trước khi hiển thị số liệu API mới.
- app/db/publication_repositories.py có external_release_id. Cần rà và hoàn thiện đường ghi ID/URL trả từ YouTube official publisher vào release; hiện đường đồng bộ job chưa ghi đầy đủ external ID.
- Giao diện lịch hiện tạo schedule theo một account rồi chọn nhiều target thuộc account đó. Việc soạn đồng thời nhiều account không phải điều kiện tiên quyết cho API/analytics và được để một task UX riêng.
- docs/API_INTEGRATIONS_IMPROVEMENT_PLAN.md là tài liệu lịch sử: một số mục ghi “chưa triển khai” nhưng credential foundation và YouTube đã có trong mã. Mã hiện tại và test là nguồn kiểm chứng.

Các phát hiện trên là baseline đọc mã, chưa phải kết quả test runtime hay xác nhận trên tài khoản thật.

## 4. Bất biến không được phá

1. Chrome vẫn là lựa chọn mặc định cho account cũ. Không tự chuyển account hiện có sang API. Các giá trị chrome_preferred, official_api_preferred, chrome_only và official_api_only giữ ngữ nghĩa hiện có.
2. Mọi lần đăng thật phải có approval của revision hiện tại và dry-run evidence khớp account, target, format, transport, publisher version. Mở rộng bằng connection ID, external target ID và fingerprint của scope/consent để bằng chứng cũ không hợp lệ sau reconnect/đổi quyền.
3. Khi tạo release, đóng băng transport, provider/connection, target, revision, payload, media và settings. Retry không được đổi route hoặc connection ngầm.
4. Trước request API có thể tạo bài, ghi commit point. Nếu timeout/mất phản hồi sau thời điểm có thể đã tạo bài, ghi unknown_result và đối soát; không retry hoặc fallback sang Chrome tự động.
5. Dry-run API chỉ kiểm tra token/scope/target/format/media/payload; không gọi endpoint tạo bài, upload session có tác dụng phụ hay publish container.
6. Mỗi request API phải dùng OAuth user/page token đúng account và target. Không coi Platform App credential, client token, cookie Chrome, hoặc “connected” chung chung là đủ quyền đăng.
7. Secret/token không xuất hiện trong API response, log, error message, webhook, export hoặc UI. Giữ DPAPI và state/PKCE/refresh logic hiện có.
8. Không coi API trả HTTP 2xx là bài đã đăng thành công nếu provider còn xử lý/moderation. Cần ID thật, verify status hoặc pending rõ ràng.
9. Analytics đọc dữ liệu không được làm thay đổi publish job. Lỗi thu thập không sửa status release đã đăng.
10. Dữ liệu không có/không hỗ trợ/thiếu quyền khác với giá trị 0. Mọi metric có nguồn, thời điểm đo và định nghĩa phép tổng hợp.

## 5. Kiến trúc mở rộng tối thiểu

### 5.1 Danh tính và capability

Nguồn hiện có: platform_apps → account_connections → publishing_targets → publication_releases. Bổ sung ràng buộc để biết một OAuth connection được phép thao tác với external target nào. Một account Facebook có nhiều Page hoặc một Meta connection có Facebook Page và Instagram Professional không được dùng nhầm Page token/target. Target discovery từ API ghi vào TargetRepository hiện tại; không tạo hệ thống kênh song song với Chrome.

Platform catalog mô tả riêng cho mỗi format: API publishing readiness, scopes, target/account type, media constraints, verify method, API analytics readiness theo bài/kênh. Trạng thái tối thiểu: unavailable, needs_app_approval, needs_connection, needs_scope, review_required, ready. Chỉ report ready sau test hợp đồng và acceptance thực tế. UI phải nói rõ capability nào còn dùng Chrome.

### 5.2 Publish adapter

Giữ PublisherRegistry/PublisherRouter và contract hiện có. Trước khi thêm provider, thống nhất interface thực tế với YouTube: validate, dry_run, publish, verify/pending; hiện Protocol và implementation có điểm chưa khớp tên method. Sửa cục bộ, không refactor rộng. Mỗi publisher trả kết quả chuẩn gồm external ID, URL, provider request ID, status (completed/pending/unknown), verification method và metadata an toàn. Worker ghi kết quả vào release/attempt/event hiện có. Với upload nhiều bước, đánh dấu chính xác bước nào là non-idempotent commit.

Router phải xét đủ: connection sống, required scopes, token refresh khả dụng, account/target identity match, format và adapter đã đăng ký. Frozen route khi chạy phải tham chiếu đúng connection ID đã snapshot, không tìm “một connection đang connected” bất kỳ. Nếu điều kiện không còn đúng, trả needs_reconnect/needs_scope hoặc lỗi rõ; không đổi sang transport khác sau commit.

### 5.3 Analytics adapter độc lập với publish route

AnalyticsCollectorRegistry chọn adapter theo provider + metric capability + connection/target, độc lập với publication_transport. Ví dụ bài đăng bằng Chrome vẫn có thể lấy API metrics nếu đã nối chính xác post ID, target và OAuth connection. Không dùng API analytics để lén thay đổi phương thức đăng.

Phân tách:

- PostMetricCollector: release ID thật → metrics của bài.
- ChannelMetricCollector: target external ID thật → metrics cấp Page/profile/channel.
- UIAnalyticsCollector hiện có: nguồn phụ cho metric nhìn thấy, không tự trộn với API source.
- AnalyticsSyncService: gọi collector đọc dữ liệu, ghi fetch run, chuẩn hóa lỗi/quota/backoff/freshness và lưu snapshot. Bắt đầu bằng nút refresh thủ công; sau đó mới thêm lịch refresh bounded khi app đang chạy.

### 5.4 Dữ liệu và cách tính

Migration **mới sau v18**; không sửa migration đã phát hành, có backup trước migration theo Database hiện có. Dùng cấu trúc đang có cho release_metrics; thêm metadata tối thiểu cần cho metric_kind (counter_snapshot hoặc interval_value), unit, provider_metric_name, period_start/end và target identity nếu cần. Thêm channel_metrics cùng fetch-run log riêng theo target. Lưu raw JSON giới hạn kích thước chỉ khi thật cần chẩn đoán và đã loại secret/PII.

Quy tắc chuẩn hóa:

- Counter tích lũy (views, likes, followers): “hiện tại” lấy snapshot mới nhất của mỗi bài/kênh/metric trong thời hạn; không cộng nhiều ngày của cùng bài.
- Tổng nhiều bài: lấy **một snapshot ưu tiên** cho mỗi release + metric, rồi mới cộng qua các release phù hợp. API source ưu tiên khi xác minh được; UI source hiển thị riêng hoặc dùng khi API unavailable, không cộng cả hai.
- Metric theo khoảng thời gian (daily impressions/watch time): chỉ cộng các khoảng không chồng lấn, đúng timezone và định nghĩa của provider.
- Xu hướng: so sánh hai snapshot hoặc hai cửa sổ tương đương; không suy ra “lượt mới” từ tổng lifetime nếu thiếu điểm đầu.
- Dữ liệu thiếu scope, platform trả rỗng, chưa có post ID và quota exceeded phải có trạng thái khác nhau. Hiển thị last_fetched_at và source.
- Không sửa/ghi đè snapshot Chrome cũ; migration tương thích dữ liệu đã có. Test bằng ví dụ 100→110 likes và hai nguồn API/UI để chứng minh kết quả không bị 210 hoặc 310.

### 5.5 API và UI Tinix

Tận dụng endpoint release/metrics/summary hiện có; bổ sung endpoint có filter account/target/date/source, phân trang, refresh theo bài và kênh, fetch-run status. Không mở một API công khai mới nếu chưa cần; internal /api và /api/v1 có scope phù hợp, tuyệt đối không để token read gọi publish/refresh mutation. Thu thập lâu phải đi qua worker bền vững hoặc trả job ID; không giữ request HTTP mở trong lúc quét Chrome/API hàng loạt.

Trong Analytics tab, tách “Bài đăng” và “Kênh”, chọn platform/account/target, thời gian, nguồn dữ liệu; từng card cho biết metric, thời điểm, trạng thái và lỗi có thể hành động. Chi tiết release hiển thị external ID/URL, identity, metric history và nút đối soát. Danh sách cần pagination/sort mới nhất, không giới hạn ngầm 200 release đầu.

## 6. Giai đoạn triển khai bắt buộc

Mỗi giai đoạn là một thay đổi nhỏ có thể review. Chỉ chuyển giai đoạn khi test liên quan qua và capability/state được báo đúng. Nếu điều kiện từ provider ngoài Tinix chưa đạt, hoàn tất adapter ở trạng thái gated và báo blocker; không fake ready.

### Giai đoạn 0 — Baseline và phạm vi thật

1. Đọc PROJECT_STATUS.md nếu được cung cấp; nếu vẫn không tồn tại, ghi rõ trong báo cáo thay vì tự tạo nội dung. Đọc AGENTS.md và hai tài liệu kế hoạch/kiến trúc có liên quan.
2. Ghi git status/diff để không ghi đè file người dùng; không tạo commit tự động. Ghi migration mới nhất, version, cấu hình local/server, danh sách test baseline.
3. Chạy baseline các test hiện có về provider connections, routing, YouTube publisher, migrations, analytics, scheduling/reliability/API. Phân biệt lỗi có từ trước.
4. Xác minh tài liệu API chính thức và quyền/chi phí hiện hành cho từng provider trước khi khóa format và scope. Lập capability matrix có link nguồn và trạng thái app review/account test.
5. Viết acceptance matrix: platform × account type × target × content format × publish/verify × post metrics × channel metrics. Nêu rõ metric không có API.

**Gate:** baseline và capability matrix được lưu; chưa mở API route mới chỉ vì đã lưu credential.

### Giai đoạn 1 — Sửa nền định danh, an toàn và phép tính

1. Hoàn thiện ghi external_release_id/URL từ YouTube publisher vào publication release và verify đúng video/channel. Mọi provider sau đó dùng cùng quy tắc.
2. Ràng buộc connection ↔ external target; API target discovery populate TargetRepository. Ngăn account OAuth đăng lên Page/channel khác account đã chọn.
3. Bổ sung dry-run evidence binding theo connection ID, external target và quyền đã consent; thu hồi bằng chứng khi token/reconnect/scopes thay đổi. Giữ bằng chứng Chrome cũ và compatibility migration.
4. Router/worker dùng frozen connection ID; trước commit kiểm tra connection còn hợp lệ; sau commit không fallback/retry.
5. Siết manual connect: chỉ nhận release đã publish hoặc trạng thái đối soát rõ, kiểm tra URL cùng provider; người dùng xác nhận target/post identity, không đặt verified nếu mới chỉ có URL hợp lệ.
6. Định nghĩa metric_kind/source preference và sửa summary để không cộng snapshot tích lũy hoặc trộn nguồn. Giữ response tương thích khi có thể; nếu cần đổi contract, version endpoint rõ.
7. Thêm migration additive + tests upgrade v18 và dữ liệu release_metrics cũ.

**Gate:** YouTube cũ vẫn đăng được; Chrome routing, approval, dry-run, unknown_result, backup/restore và analytics UI cũ không regress; phép tổng hợp có kết quả đúng.

### Giai đoạn 2 — YouTube analytics end-to-end

1. Tái sử dụng Google/YouTube Platform App, OAuth callback, refresh và connection DPAPI hiện có. Xác minh scopes hiện tại với Data API; nếu Analytics API đòi scope bổ sung thì yêu cầu incremental consent có hiển thị lý do, không ngắt connection cũ.
2. Post metrics trước: từ video ID đã verify, đọc counts có sẵn qua YouTube Data API, chuẩn hóa view/like/comment và trường unavailable. Không giả định mọi chỉ số đều được hiển thị theo privacy của video.
3. Channel metrics: dùng channel ID đã bind, đọc public/current stats từ Data API; cho time series sâu hơn dùng YouTube Analytics API khi scope và dữ liệu cho phép, ghi rõ độ trễ dữ liệu.
4. Thêm channel_metrics, fetch runs, service/endpoint/UI. Bắt đầu bằng refresh thủ công có quota/rate limit. Sau khi ổn định, cho lịch refresh khi app đang chạy với giới hạn số bài/kênh và backoff.
5. API publisher YouTube hiện có phải đi qua contract và metadata mới mà không đổi hành vi publish ngoài phạm vi.

**Gate:** một video test và kênh test có metric hợp lệ, source/timestamp rõ; dữ liệu chưa sẵn sàng hiển thị no_data; test mocked pass; không thực hiện đăng thật trong CI.

### Giai đoạn 3 — Meta: Facebook Page, rồi Instagram Professional

1. Dùng Platform App Meta hiện có; hoàn thành OAuth, refresh/expiry, scopes và Page/Instagram professional target discovery theo API/version được duyệt. Lưu token Page đúng target bằng kho secret bảo vệ. Không nhận Facebook personal profile hoặc Instagram personal nếu API không hỗ trợ.
2. Facebook Page: bắt đầu format đơn giản được API cấp quyền (text/image), sau đó video nếu flow upload/processing/verify riêng đạt gate. Mỗi format có schema, dry-run, publisher, post ID/URL, pending/verify và lỗi chuẩn hóa.
3. Facebook Page post/channel analytics: lấy các metric được Graph API cho phép; không giả định metric cũ còn tồn tại ở API version mới. Ghi khoảng thời gian, định nghĩa và source.
4. Instagram Professional: bind đúng IG user ↔ Facebook Page khi provider yêu cầu; triển khai image trước, carousel/video/Reel chỉ khi API entitlement và verification được thử. Container upload/processing phải có pending workflow bền vững.
5. Instagram post/channel insights riêng theo loại media và quyền account; thiếu insight không chặn đăng nếu publisher hợp lệ, nhưng UI phải báo chính xác.
6. Test contract/fixtures và acceptance trên account test. Bật ready theo provider/format/metric đã qua, không bật cả nền tảng cùng lúc.

**Gate:** app review/scopes thật đã cấp; target binding, publish, verify và metric mapping thực tế được ghi nhận; không có đường đăng profile cá nhân sai quyền.

### Giai đoạn 4 — TikTok và X theo entitlement

**TikTok:** Desktop Login Kit/OAuth + PKCE, user token và scope phù hợp; Content Posting API cho short video, upload/status/moderation/pending; post metrics theo quyền đọc video, channel/profile stats theo quyền riêng. Direct Post cần approval/audit; app chưa audited có thể bị giới hạn private. Chỉ bật format và metrics khi app và account test qua gate.

**X:** OAuth user context + scopes read/write/offline theo endpoint thực dùng; media upload và tạo post với idempotency/unknown_result; per-post public/private metrics và profile metrics theo entitlement/thời hạn. Kiểm tra chi phí pay-per-use/quota trước khi bật tự động thu thập. Dữ liệu không được cấp thì unsupported, không scrape thầm bằng cookie.

Hai provider là hai milestone độc lập. Nếu quyền API/chi phí không cho phép, giữ official_api ở needs_app_approval/unavailable, Chrome tiếp tục hoạt động; báo blocker cụ thể. Không đổi thứ tự chỉ để đủ “5/5”.

### Giai đoạn 5 — Hoàn thiện vận hành và UX

1. Release detail gom route, connection/target identity, request ID, post ID/URL, verification, attempts, lỗi, post metrics và lịch sử fetch.
2. UI filter/pagination/sort cho bài/kênh; biểu đồ chỉ thể hiện dữ liệu có định nghĩa nhất quán. Cho người dùng chọn API hoặc UI source khi cả hai có, đồng thời giải thích độ lệch.
3. Lịch refresh bền vững khi app chạy: ưu tiên bài mới, dừng ở quota/rate-limit, retry read-only có backoff, không chạy dồn vô hạn sau máy tắt lâu. Có nút refresh thủ công và thời điểm cập nhật gần nhất.
4. Health/notifications chỉ báo thiếu quyền/reconnect/quota/stale khi có thể hành động. Webhook metric nếu cần phải tôn trọng local API scopes và không lộ dữ liệu nhạy cảm.
5. Cập nhật README, hướng dẫn account/API và capability matrix theo thực tế.

**Gate:** người dùng hiểu bài/kênh nào có số liệu, metric nào không có và lần cập nhật gần nhất.

## 7. Bộ kiểm thử và kiểm tra hồi quy

Sau từng milestone chạy targeted tests liên quan; sau thay đổi cuối chạy full suite. Test mạng xã hội dùng mock HTTP/fixtures; không gọi publish thật trong CI.

- Migration: DB mới, upgrade từ v18 và bản cũ được hỗ trợ, backup trước migration, integrity, giữ metrics/release/token cũ.
- OAuth: state/PKCE một lần, callback bind đúng Platform App/account, refresh/rotation, expired/revoked/missing scope, không lộ secret.
- Identity: nhiều Page dưới một Meta user, nhiều channel/account, target mismatch, changed connection, release ID thiếu/sai, manual connect đúng/sai.
- Router/publisher: 4 routing preferences, format capability, API dry-run không có side effect, approval/revision, route snapshot, pending/verify, timeout trước và sau commit, restart recovery, không đăng trùng.
- Analytics: post + channel collectors, provider rate limit/quota/403/404/empty/malformed response, snapshot upsert, source preference, stale data, timezone, 100→110 không thành 210, Chrome/API không cộng đôi.
- UI/API: readiness/unsupported hiển thị đúng; filters/pagination; refresh không publish; response không chứa credential; local API scopes giữ nguyên; frontend smoke.
- Regression cụ thể: Chrome publishers của 5 platform, YouTube official publish, release/retry, content approval, media, backup/restore, local API, analytics cũ.

Lệnh baseline/đích trong workspace Windows (điều chỉnh tên test khi code mới thêm):

    .\.venv\Scripts\python.exe -m compileall -q app tests
    .\.venv\Scripts\python.exe -m unittest tests.test_provider_connections tests.test_publisher_routing tests.test_youtube_official_publisher tests.test_analytics tests.test_state_and_migrations tests.test_content_ai_scheduling tests.test_reliability tests.test_api -v
    .\.venv\Scripts\python.exe -m unittest discover -s tests -v

Nếu một check thất bại, đọc log/diff để phân biệt failure cũ và mới; sửa lỗi thuộc milestone. Không gọi automated real publish. Acceptance thực tế dùng account test do người dùng sở hữu: OAuth, read-only metric, dry-run, rồi một bài test thật có xác nhận, chụp bằng chứng post ID/URL và số liệu. Thiếu credential/scope/app review là blocker external, không được báo đã hoàn tất provider.

## 8. Build, thay server local và báo cáo cuối

1. Sau final edit và tests, chạy BUILD.bat **một lần** từ root, ưu tiên --no-bump nếu đây không phải bản phát hành; script hiện tự chạy test và gọi STOP.bat. Ghi nhận nếu build làm gián đoạn job đang chạy.
2. Xác định đúng server Tinix bằng command line/cwd/PID ownership hoặc process do launcher quản lý; không kill theo port đơn lẻ và không đụng server dự án khác.
3. Vì BUILD.bat dừng app, khởi động lại backend với cấu hình local bình thường bằng launcher/lệnh dự án; helper nền dùng cửa sổ ẩn. Xác nhận PID cũ đã thay, /api/health trả version/status, /api/runtime và capability mới đúng, frontend đã nạp mã mới. Nếu chỉ tài liệu PLAN.md thay đổi thì build/restart không áp dụng.
4. Báo cáo cuối: phạm vi đã làm theo provider/format/metric và readiness; file/migration đã đổi; targeted/full test và Build.bat; restart/health; acceptance thật đã/ chưa làm; quyền API/chi phí/blocker còn lại; job bị ngắt (nếu biết); Git commit chưa tạo trừ khi người dùng yêu cầu.

## 9. Các điều kiện dừng đúng đắn

- Chưa có PROJECT_STATUS.md: tiếp tục lập kế hoạch; trước khi triển khai mã, đọc file nếu người dùng cung cấp và điều chỉnh baseline.
- Thiếu app review/permission/paid entitlement: dừng kích hoạt provider đó, tiếp tục các provider độc lập; không dùng cookie/private endpoint để giả API chính thức.
- Không chứng minh được post ID hoặc target identity: không fetch metrics vào release đó và không báo verified.
- Không xác định được kết quả sau commit: unknown_result, yêu cầu đối soát, không retry.
- Hai hướng sửa suy đoán khác nhau thất bại: dừng sửa, ghi lỗi, bằng chứng, thử nghiệm đã làm và bước chẩn đoán tiếp theo theo AGENTS.md.

## 10. Tài liệu tham chiếu

- [Postiz analytics](https://docs.postiz.com/general/analytics), [Postiz post analytics API](https://docs.postiz.com/public-api/analytics/post), [Postiz architecture](https://docs.postiz.com/self-host/architecture).
- [YouTube Data API videos.list](https://developers.google.com/youtube/v3/docs/videos/list), [channels.list](https://developers.google.com/youtube/v3/docs/channels/list), [YouTube Analytics reports.query](https://developers.google.com/youtube/analytics/reference/reports/query), [Analytics data model và độ trễ](https://developers.google.com/youtube/analytics/data_model), [videos.insert và giới hạn app chưa audit](https://developers.google.com/youtube/v3/docs/videos/insert).
- [Google OAuth web server](https://developers.google.com/identity/protocols/oauth2/web-server).
- [Meta Pages publishing](https://developers.facebook.com/docs/pages-api/posts/), [Page insights](https://developers.facebook.com/docs/graph-api/reference/page/insights/), [post insights](https://developers.facebook.com/docs/graph-api/reference/post/insights/); [Instagram content publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing/) và [Insights](https://developers.facebook.com/docs/instagram-platform/insights/). Cần kiểm tra lại quyền và metric theo Graph API version/app được cấp, vì một số trang Meta trả giới hạn truy cập khi nghiên cứu.
- [TikTok Login Kit Desktop](https://developers.tiktok.com/docs/en/login-kit-desktop), [Content Posting API](https://developers.tiktok.com/docs/en/content-posting-api-get-started), [trạng thái bài đăng](https://developers.tiktok.com/docs/en/content-posting-api-reference-get-video-status), [video.query](https://developers.tiktok.com/docs/en/tiktok-api-v2-video-query), [user.info.stats](https://developers.tiktok.com/docs/en/tiktok-api-v2-get-user-info).
- [X tạo bài](https://docs.x.com/x-api/posts/create-post), [đọc metric của bài](https://docs.x.com/x-api/posts/get-post-by-id), [post analytics](https://docs.x.com/x-api/posts/get-post-analytics), [users/me](https://docs.x.com/x-api/users/get-my-user), [pricing](https://docs.x.com/x-api/getting-started/pricing).
- [Tinix research](RESEARCH_postiz.md), [project overview](docs/PROJECT_OVERVIEW.md), [existing integrations plan](docs/API_INTEGRATIONS_IMPROVEMENT_PLAN.md), [desktop build](DesktopBuild.md).
