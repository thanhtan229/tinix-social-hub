# PLAN — API publishing và analytics cho Tinix Social Hub

**Trạng thái:** đã nghiệm thu live YouTube channel analytics trên cả hai account và đăng thử đúng một video riêng tư qua API trên `thanhtan229`; snapshot theo bài đã lưu thành công. Facebook Page API có OAuth/System User, bài chữ, ảnh đơn, album 2–3 ảnh, video Page thường, Reel và analytics snapshot; các định dạng này đã live-verified trên Page Tinix, album 4–10 ảnh chưa thử. Instagram publishing đã có code/fixture nhưng chưa live (chờ R2 và OAuth). TikTok và X vẫn gated/scaffold. Nguồn trạng thái chi tiết: docs/plan_postiz_*.md và FINAL_REVIEW.md.
**Ngày lập:** 27-09-2026.  
**Đầu vào:** yêu cầu hiện tại, [RESEARCH_postiz.md](RESEARCH_postiz.md), mã Tinix tại commit a097762 (16-09-2026), [PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md), [PLATFORM_ARCHITECTURE.md](docs/PLATFORM_ARCHITECTURE.md).  
**Thiếu đầu vào:** Không tìm thấy PROJECT_STATUS.md ở thư mục dự án hoặc thư mục cha khi lập kế hoạch. Trước khi bắt đầu giai đoạn triển khai, Codex phải đọc file đó nếu được cung cấp; ghi nhận mọi thay đổi so với kế hoạch này rồi mới sửa mã. Không tự suy diễn nội dung của file.

**Kết quả triển khai tự động (27-09-2026):** Các phần trong phạm vi local đã triển khai: migration additive v19–v20, ràng buộc route theo target/connection/scope, YouTube post/channel snapshots + daily reports, filters/history/pagination, refresh thủ công và lịch refresh tùy chọn có giới hạn, capability/docs. Đã thêm nút `Kết nối lại API` cho YouTube connection không còn hiệu lực; OAuth consent cập nhật connection hiện có mà không cần xóa trước. Nghiệm thu live: cả `thanhtan229` và `Tini Baby Studio` đều trả thành công với Data API và YouTube Analytics API sau khi bật API trong Google Cloud project `729460300489`; channel history/summary được lưu trong Tinix. `thanhtan229` có snapshot 40 subscribers, 62 videos, 63.868 views; snapshot channel của `Tini Baby Studio` là 0/0/0. Đã đăng đúng một clip kiểm thử 5 giây ở chế độ `private` qua official API trên target `Tí Nị Studio`; video `0SXIN767L2M`, release đã `succeeded` và `verified`. Post collector lưu thành công `views=0`, `likes=0`, `comments=0` qua Data API; YouTube Analytics API v2 trả `no_data` cho trend ở lần đọc tức thời. Không đăng bài nào khác. Meta/Instagram, TikTok và X giữ trạng thái `scaffold` vì chưa có OAuth adapter, app entitlement/account acceptance; không bật publisher hoặc analytics giả.

| Phần | Trạng thái mã | Bằng chứng / bước tiếp theo |
|---|---|---|
| Baseline, backup, frozen identity/dry-run | Hoàn tất trong mã | Migration v19–v20 additive, tests cho connection/scope/target mismatch; nghiệm thu live phụ thuộc OAuth connection hợp lệ |
| YouTube publish API | Đã có từ trước, được giữ nguyên | OAuth upload/read, dry-run, resumable upload, verify; CI chỉ mock |
| YouTube post + channel analytics | Hoàn tất trong mã; live acceptance đã chạy | Channel snapshot + daily reports đã lưu trên cả hai account. Một video private đã đăng/xác minh trên `thanhtan229`; views/likes/comments snapshot đã lưu, trend API trả `no_data` ngay sau khi đăng |
| Analytics UX, filters, pagination, refresh | Hoàn tất trong mã | Account/target/platform, history/summary, latest-first pages; lịch nền mặc định off và capped |
| Meta/Facebook Page API | Bài chữ, ảnh, album 2–3, video Page thường, Reel đã live-verified trên Page Tinix; album 4–10 chưa thử | Hỗ trợ OAuth/System User và post/Page analytics. Instagram one-photo publisher đã code/fixture; chờ R2 và OAuth/quyền live |
| TikTok API | Scaffold, chưa bật | Cần OAuth/creator consent, Content Posting app audit và account acceptance |
| X API | Scaffold, chưa bật | Cần OAuth user context, endpoint entitlement/quota và cấu hình kiểm soát chi phí |

Hoàn tất kiểm thử tự động/build/server ở phần báo cáo cuối của lần triển khai; đây không thay thế acceptance social-network thật.

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

#### Kế hoạch triển khai kế tiếp — 3A: Facebook Page API

**Quyết định phạm vi:** Hoàn thiện một Page Facebook trước, theo thứ tự OAuth/định danh → analytics chỉ đọc → đăng text qua API → ảnh nếu text đạt gate. Page nghiệm thu do người dùng chọn là **Tí Nị Studio - Chụp ảnh cho bé và gia đình**, URL [facebook.com/tiniphotos](https://www.facebook.com/tiniphotos/), target Tinix `6865e41b-d0e0-4926-a114-7f1edde53100` thuộc account Facebook `Đỗ Minh Duy`. Khi OAuth phải xác minh người đăng nhập có quyền quản trị đúng Page này và đối chiếu Page ID do Graph API trả về; không thay bằng một Page khác khi chưa có chỉ định của người dùng. Instagram Professional là giai đoạn 3B riêng. Giữ Chrome publishers, release/job/approval/dry-run và nguồn metrics cũ hoạt động. Không bật `ready` cho toàn bộ Meta chỉ vì kết nối OAuth thành công.

**Baseline đã kiểm tra (27-09-2026):** Người dùng xác nhận có Meta Developer App và Page để thử, nhưng Tinix hiện chưa đăng ký Meta Platform App và chưa có Meta `account_connection`; hai connection API hiện có đều là YouTube. `ProviderAccountService` và UI kết nối account mới chỉ thực thi YouTube. Target `tiniphotos` đang enabled/accessible qua Chrome, `external_id=url:tiniphotos`, chưa có publication release trên target này; trạng thái Chrome không chứng minh Graph Page ID hay Page tasks. Các Page Chrome đã khám phá nằm dưới account Facebook `Đỗ Minh Duy`; đa số `publishing_targets.external_id` là alias dạng `url:...`, trong khi Graph API trả Page ID số. `PublisherRouter` hiện so khớp `account_connections.external_account_id` trực tiếp với `target.external_id`, đủ cho một YouTube channel nhưng không đủ cho một Meta user quản lý nhiều Page. Không ghi đè Page ID/URL alias hoặc release Chrome cũ.

1. **Kiểm chứng điều kiện Meta App bằng quyền thực tế.** Chọn một Page nghiệm thu do người dùng quản trị; kiểm tra app mode/role, Graph API version được app hỗ trợ, URI callback local, các quyền đã cấp và Page tasks. Các quyền ứng viên cho discovery/publish/insights gồm `pages_show_list`, `pages_manage_posts`, `pages_read_engagement`, `read_insights`; chốt từng quyền bằng consent và phản hồi Graph API trên app này, không coi danh sách trong catalog là bằng chứng. Đăng ký App ID/Secret qua Platform App UI hiện có, không ghi secret vào tài liệu/log. Nếu redirect local không được Meta chấp nhận, giải quyết callback hợp lệ trước khi xây publisher.
2. **Ràng buộc danh tính và token theo Page.** Tận dụng `platform_apps`, `oauth_states`, `account_connections`, DPAPI, `publishing_targets`, `publication_releases` và `PublisherRouter`. OAuth state dùng một lần và bind account/app; xử lý user token theo tuổi thọ/reauthorization thực tế của Meta. Dùng `/me/accounts` để lấy Page ID, Page token và `tasks`; lưu Page token được mã hóa riêng theo connection + Page/target (migration additive sau v20 nếu cần). Ánh xạ Page ID số vào target Chrome sau khi so URL/identity và người dùng xác nhận; giữ nguyên target ID lịch sử. Route API cần đóng băng connection ID, Page binding ID, Graph Page ID và fingerprint quyền; trước commit kiểm tra lại, sau commit không fallback sang Chrome hoặc retry mù. Page khác hoặc token chỉ có quyền đọc phải bị chặn publish.
3. **Analytics chỉ đọc trước.** Trên Page đã bind, thử Graph API có kiểm soát để xác định metric cấp Page và post thật sự còn được hỗ trợ ở version đã chọn, kỳ đo, timezone, quota và quyền. Lưu vào `channel_metrics`/`release_metrics` và fetch runs đang có, với nguồn/định nghĩa/thời điểm rõ. Chỉ liên kết post metrics khi post ID thuộc đúng Page; không tự ghép URL gần giống. Trạng thái `no_data`, `needs_scope`, `unsupported`, `rate_limited` và lỗi khác phải phân biệt; không cộng snapshot tích lũy nhiều lần hoặc cộng đôi Chrome/API. Ghi capability matrix chỉ cho metric đã xác minh.
4. **Publisher đầu tiên: Page text post.** Dùng format đơn giản, một Page đích, qua router/worker hiện có. Validation kiểm tra Page tasks, scope, content, target và approval; dry-run không gọi API tạo bài. Lệnh tạo bài lưu post ID/request evidence, xác minh Page + post và permalink; nếu timeout sau commit thì `unknown_result` và đối soát ID, không đăng lại. Chỉ mở tính năng trong UI khi contract tests và live acceptance trên Page thử qua. Ảnh là lát cắt tiếp theo: dùng media library, kiểm tra Graph photo upload/processing, commit point và verification riêng; video/Reels để sau.
5. **Giao diện và vận hành.** Trong Tài khoản & Page, hiển thị App/connection/Page binding, scope và Page tasks, nút kết nối lại, trạng thái cụ thể từng Page; Page chưa ánh xạ giữ route Chrome. Composer chỉ cho chọn `official_api` ở format/target đã đủ điều kiện; Analytics hiển thị source, metric, last fetched và lỗi có thể hành động. Hạn chế refresh nền theo quota; token và Page token không xuất qua API/UI/log/backup không mã hóa.
6. **Kiểm thử và nghiệm thu.** Test migration/backup, OAuth state và callback, token expiry/reauth, nhiều Page dưới một user, alias `url:` ↔ Graph Page ID, đổi/revoke quyền, route snapshot, dry-run, approval, timeout trước/sau commit, không duplicate, Page analytics và post analytics/rate limit. Chạy targeted tests rồi regression Chrome 5 nền tảng và YouTube API, full suite, `Build.bat`, restart server đúng dự án và health/revision check theo AGENTS.md. Acceptance thực tế: kết nối App/đúng Page, đọc metric có source, dry-run không tạo bài, một bài text thử có cho phép đăng thật, post ID/permalink/metrics lưu đúng Page. Báo metric chưa được Meta cấp là unsupported/needs_scope, không báo thành công giả.

**Điểm dừng:** Nếu App thiếu quyền/Page task, callback không hợp lệ hoặc Page ID không xác minh được, hoàn thiện phần không phụ thuộc và giữ official API ở trạng thái gated. Không nhập secret hoặc token bằng tay vào bảng account; không lấy cookie/private endpoint để lách entitlement. Việc người dùng chọn Page nghiệm thu trong kế hoạch chưa phải là cho phép đăng thật lên Page đó.

**Các lát cắt để Codex triển khai lần sau:**

| Lát cắt | Thay đổi tối thiểu | Bằng chứng để chuyển tiếp |
|---|---|---|
| 3A.0 — Quyền và cấu hình | Kiểm tra Meta App, callback, Graph version, Page role/tasks và scope; đưa App vào Platform App UI | OAuth test trên account quản trị, `/me/accounts` trả đúng Page ID và Page token; không ghi secret ra log |
| 3A.1 — Liên kết Page | Thêm Meta OAuth/connection, Page token bảo vệ, bảng ánh xạ Page ID ↔ target hiện có nếu cần; giữ nguyên alias/target/release cũ | Có ít nhất hai Page trong fixture; chỉ đúng Page/token được chọn có thể route API; mismatch bị chặn |
| 3A.2 — Đọc số liệu | Thu thập Page và post metrics thực sự được version/quyền cấp, lưu snapshot/fetch run hiện có | Một Page và một post có dữ liệu thật hoặc `no_data` đúng nghĩa; source/time/metric definition kiểm tra được |
| 3A.3 — Đăng text | Publisher text theo worker hiện có, dry-run, approval, commit/verify/unknown_result | Dry-run không tạo post; sau xác nhận đăng thật một post đúng Page, ID/permalink đối chiếu được; không retry trùng |
| 3A.4 — Ảnh và UI | Chỉ mở ảnh sau gate text; hiển thị binding, readiness, reconnect, metrics và lỗi | Ảnh test được xác minh đúng Page; Chrome/YouTube regression, full suite, build và local restart đạt |

**Quy tắc chọn target:** Target `Tí Nị Studio - Chụp ảnh cho bé và gia đình` hiện có external ID `url:tiniphotos`, chưa phải Graph Page ID; không dùng alias đó để gọi Graph API. Chỉ dùng ID số do Meta trả về sau OAuth và ánh xạ có xác minh vào target `6865e41b-d0e0-4926-a114-7f1edde53100`. Nếu `tiniphotos` không nằm trong các Page/token mà app được phép quản lý, giữ official API ở trạng thái `needs_app_approval`/`needs_scope` hoặc `needs_page_access`, nêu bằng chứng và bước khắc phục; không tự chuyển nghiệm thu sang Page khác.

**Sau gate 3A:** Giai đoạn 3B kiểm tra Instagram Professional của cùng Meta App. Nếu dùng Instagram API with Facebook Login thì IG phải liên kết Page; Meta cũng cung cấp Instagram Login riêng với scope `instagram_business_*`, nên chọn đúng flow theo account/app thực tế thay vì trộn token. Bắt đầu ảnh sau khi xác nhận public media URL, container processing/publish và quyền insights; carousel/Reel/Story chỉ theo capability đã thử.

**Nguồn kiểm chứng cho giai đoạn 3A/3B:** [Meta official Facebook API collection](https://www.postman.com/meta/facebook/overview), [Meta Page token và tasks qua `/me/accounts`](https://www.postman.com/meta/facebook/request/bqfxwbp/get-access-tokens-of-pages-you-manage), [Meta Instagram API with Facebook Login](https://www.postman.com/meta/instagram/folder/9cgqucg/instagram-api-with-facebook-login), [Meta Instagram API with Instagram Login](https://www.postman.com/meta/instagram/folder/6raa77c/instagram-api-with-instagram-login). Trang developer Facebook về publish/insights đang trả giới hạn truy cập khi lập kế hoạch; trước khi viết adapter phải xác minh lại endpoint/metric trên Graph API version của app và quyền thực được cấp.

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

## 10. Kết quả xác minh lần triển khai

- `compileall -q app tests`: đạt.
- Analytics/API/frontend smoke tests: đạt sau khi chạy lại test UI bị flaky một lần; toàn bộ smoke test qua trong bộ test đầy đủ.
- Test UI reauthorization: connection `reauth_required` hiển thị nút `Kết nối lại API` ngay trên dòng account và ở panel chi tiết, mở URL OAuth và không gửi DELETE connection.
- Trạng thái account: danh sách hiển thị nhãn API `Đã kết nối`, `Chưa kết nối` hoặc `Cần kết nối lại`; khi quay về app sau OAuth, connection được tải lại tự động. Runtime hiện xác nhận `thanhtan229=connected`, `Tini Baby Studio=connected`.
- Toàn bộ unittest suite: đạt trong `BUILD.bat --no-bump` (script báo `100% PASSED`). Catalog test đã cập nhật assertion từ 6 lên 7 boundary sau khi bổ sung analytics.
- `git diff --check`: đạt.
- `BUILD.bat --no-bump`: đạt cho milestone analytics, giữ version `1.0.24`.
- Bản sửa nút reconnect: `BUILD.bat --bump patch` đạt và nâng lên `1.0.25`, đổi cache key, tạo icon/shortcut thành công. Local server được restart bằng `START.bat`; PID `45088` được thay bằng `33416`. `/api/health` trả `ok`, version `1.0.25`, database integrity `ok`; trang và `/static/js/accounts.js` trả HTTP 200, JS chứa action trên dòng account.
- Bản trạng thái API: `BUILD.bat --bump patch` đạt, nâng version lên `1.0.26`; `START.bat` thay PID `33416` bằng `43280`. `/api/health` trả `ok`, trang và JS trả HTTP 200; JS hiện có nhãn ba trạng thái và tự refresh sau OAuth.
- Nghiệm thu live chỉ đọc sau khi bật API: cả `thanhtan229` (channel `UCqtQDcDiVtIn252csxg36gQ`) và `Tini Baby Studio` (channel `UCXdYgfzFMlVyE-tgjosC6MQ`) trả `succeeded` cho collector Data API và YouTube Analytics API v2; daily report trả dữ liệu cho khoảng ngày `2026-08-27` đến `2026-09-25`. Channel history và summary xác nhận dữ liệu đã lưu. Summary `thanhtan229`: 40 subscribers, 62 videos, 63.868 lifetime views, 6 daily views trong cửa sổ 30 ngày. Summary `Tini Baby Studio`: snapshot 0 subscribers/videos/views, 1 daily view. API enablement blocker cũ (`403 accessNotConfigured`) đã được giải quyết. Tham chiếu quyền/query: [Google YouTube Analytics reports.query](https://developers.google.com/youtube/analytics/reference/reports/query).
- Bài test release `497c1dae-82e9-4b43-a20b-4a65600f1ac2` trên account `thanhtan229`, target `e006f5ba-ac53-47a4-9a2b-1936ed61a8bb`: dry-run `dry_run_ready`, route `official_api`, connection khớp external channel; một job đăng thật hoàn tất `succeeded`, release `verified`, external video ID `0SXIN767L2M`, URL https://www.youtube.com/watch?v=0SXIN767L2M. Privacy là `private`; không thông báo subscribers. Collector post chỉ đọc lưu ba snapshot Data API (`views=0`, `likes=0`, `comments=0`) và Analytics API v2 trend `no_data` (0 metrics) cho cửa sổ 2026-08-27 đến 2026-09-25. Giá trị 0 là snapshot thật tại thời điểm fetch; trend chưa có dữ liệu cho video vừa tạo.
- Đã tạo một content thử mới và media clip 5 giây riêng tư, không sửa nội dung cũ. Không có bài nào khác được tạo. Meta/Instagram, TikTok và X vẫn scaffold theo entitlement/review gate đã nêu.
- Không tạo Git commit triển khai.

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

## 11. Kết quả triển khai milestone Facebook Page API — 27-09-2026

- Đã thêm migration v21: bảng Page-binding lưu Page ID, tasks và Page access token được DPAPI bảo vệ, tách khỏi user-token connection. Binding khóa theo connection + Tinix target; target alias/URL Chrome hiện hữu không bị đổi.
- Đã thêm Meta OAuth callback, đổi code/token, lấy quyền được cấp, discovery `/me/accounts` có phân trang và đồng bộ Page vào binding. Giao diện Tài khoản & Page có trạng thái Meta API, nút kết nối lại/ngắt kết nối/đồng bộ Page và danh sách Page binding cùng trạng thái quyền đăng. Cấu hình yêu cầu Meta Platform App và Graph API version rõ ràng trong Tích hợp.
- Router/release/job snapshot hỗ trợ connection + Page binding + numeric Graph Page ID. Release API bị đóng băng theo binding và scope; không tự chuyển sang Chrome khi binding thay đổi. Dry-run chỉ xác thực cấu hình/quyền, không tạo bài trên Meta.
- Đã thêm publisher Facebook Page API cho text post. Trước khi commit yêu cầu Page task `CREATE_CONTENT`/quyền tương ứng; sau POST lấy post ID, tải lại `id/from/permalink_url` để xác minh Page. Nếu không chắc kết quả sau commit, chuyển `unknown_result` để đối soát, không tự đăng lại. Ảnh/video API chưa bật; API schedule từ chối nội dung có media, trong khi Chrome publisher hiện tại giữ nguyên.
- Đã thêm collector thủ công cho snapshot từng post (`likes`, `comments`, `shares` khi Graph API trả) và snapshot cấp Page (`followers_count`, `fan_count` khi được cấp). Lưu vào kho analytics hiện có, ghi provider metric name/source và không cộng snapshot như số phát sinh. **Views/reach/impressions và chuỗi lịch sử Insights chưa được bật** vì chưa xác minh trên Graph API version/quyền của Meta App người dùng; không hiển thị số giả định. Analytics tự động vẫn là phạm vi lịch tiếp theo.
- Kiểm thử: `compileall` đạt; full suite **206 tests OK**; `Build.bat --no-bump` đạt và báo kiểm thử tự động **100% PASSED**; `git diff --check` đạt (chỉ có cảnh báo line-ending CRLF của Git). Không tạo bài đăng Facebook thật và không tạo Git commit.
- Build giữ version `1.0.27`. Đã restart backend local theo lệnh khởi động nền của `START.bat`: backend trước milestone là PID `42572` (process cha `26364`) đã được thay; sau build cuối listener mới là PID `26004`, command `pythonw.exe -m app`, cwd đúng thư mục dự án. `/api/health`: `ok`, version `1.0.27`, worker idle, database integrity `ok`; migration v21 và bảng Page binding đã tồn tại; trang, `/static/js/accounts.js?v=1.0.27` và `/static/js/integrations.js?v=1.0.27` trả HTTP 200, UI Meta API và thông báo gate cấu hình App đã được nạp. Chrome App Mode được giữ mở.
- Chưa nghiệm thu live: tuy người dùng có Meta Developer App và Page **Tí Nị Studio - Chụp ảnh cho bé và gia đình**, App ID/Secret và Graph API version chưa được đăng ký trong Tinix. Chưa có OAuth consent, Page ID/tasks/token binding được xác nhận trên Page này; do đó không chạy live analytics hay đăng thử Facebook. Bước kế tiếp: thêm Meta Platform App trong Tích hợp, điền đúng callback `/api/oauth/meta/callback` và Graph API version, xác nhận Meta chấp nhận redirect/scopes, rồi kết nối account Facebook quản lý Page và kiểm tra target bind chính xác `tiniphotos`. Sau đó mới dry-run API và thu thập analytics chỉ đọc; đăng thử thật cần được người dùng cho phép riêng.

## 12. Kết quả triển khai Meta System User token — 27-09-2026

- Đã thêm luồng **Kết nối Meta API / Cập nhật Meta API** nhận System User token và Page ID dạng số. Tinix kiểm tra token và Page trước khi ghi; khi thành công, user token và Page binding được cập nhật trong cùng transaction, DPAPI bảo vệ cả hai. Token không được trả về UI/API response.
- System User token có thể dùng `/me/accounts` để tìm Page; nếu endpoint này không có với loại token đó, Tinix thử truy vấn trực tiếp Page ID. Page task lấy từ Meta nếu được trả; nếu không, quyền đã cấp được dùng để bật capability phù hợp. Nếu quyền đăng không được xác nhận, kết nối chỉ đọc.
- Meta App có thể lưu App ID và Graph API version mà không cần App Secret hay Redirect URI cho chế độ thủ công. OAuth hiện hữu vẫn giữ làm lựa chọn phụ và cần Secret/Redirect URI riêng.
- Lưu `auth_method` và `credential_revision` trong metadata hiện có; route snapshot Meta gắn với credential generation. Khi đổi token/phương thức/Page, release API cũ bị chặn để duyệt lại; Page binding của các Page khác bị ngắt nhằm tránh token cũ tiếp tục được dùng nhầm.
- Hướng dẫn sử dụng đã cập nhật. Kiểm thử: full suite **214 tests OK**, `BUILD.bat` báo **100% PASSED**, `node --check` cho hai JS entrypoint và `git diff --check` đạt. Build lên `1.0.28`; backend cũ PID `26004` được thay bởi PID `37456` từ đúng thư mục dự án; `/api/health` trả `ok`, worker idle, database integrity `ok`, trang và hai JS mới trả HTTP 200. Không có Meta token thật nên live validation, analytics thật và bài đăng thử Facebook chưa chạy. Không tạo Git commit.

## 13. Kế hoạch hỗ trợ nhiều Facebook Page trên một kết nối Meta System User

### Mục tiêu và quyết định sản phẩm

- Một account Facebook trong Tinix giữ một kết nối Meta; kết nối này có thể gắn **nhiều Page**. Mỗi Page là một `publishing_target` và một `provider_target_connection` riêng, nên lịch đăng, quyền và analytics tiếp tục được phân tách theo Page. Giữ nguyên account, target ID, lịch sử bài và Chrome profile hiện có.
- Người dùng nhập System User token một lần, chọn nhiều Page Tinix cần quản lý. Giao diện thử lấy danh sách Page truy cập được; khi token không hỗ trợ liệt kê, cho nhập nhiều Page ID dạng số và xác minh từng Page. Không tự gắn tất cả Page mà token nhìn thấy.
- Thêm Page bằng token đang lưu là thao tác riêng; không yêu cầu dán lại token và không làm mất binding của Page khác. Thay token là thao tác riêng có bước xem trước Page nào còn quyền, Page nào sẽ mất quyền.
- OAuth vẫn dùng luồng đồng bộ Page hiện có. Không mở phạm vi Instagram, đăng ảnh/video hoặc thêm metric mới trong milestone này.

### Bằng chứng và giới hạn hiện tại

- Schema v21 đã hỗ trợ nhiều binding theo `connection_id + target_id`; API publisher, router và analytics đã sử dụng binding/target cụ thể. Giới hạn nằm ở `connect_system_user`, metadata `page_id` đơn và `upsert_system_user_binding`: luồng này ngắt các binding khác; `sync_targets` của System User chỉ đồng bộ Page ID đơn. Giao diện hiện có một ô Page ID và lấy binding đầu tiên khi mở lại.
- Tài liệu Meta cho `/me/accounts` mô tả **User Access Token**, không bảo đảm System User token sẽ liệt kê Page. Tài liệu Meta cũng mô tả truy vấn Page ID cụ thể để lấy Page token với User Access Token. Vì vậy phải kiểm chứng cả việc liệt kê và truy vấn trực tiếp với Graph API version/System User token thật bằng yêu cầu chỉ đọc; nhập Page ID thủ công chỉ thành công nếu token có quyền truy cập Page đó. Nguồn: [Meta Pages token collection](https://www.postman.com/meta/facebook/documentation/r56bjfd/facebook-api?entity=request-23987686-a9ea20fe-d410-4804-8bbe-5cc5985e9443).

### Trình tự triển khai

1. **Chốt trạng thái trước khi sửa.** Đọc trạng thái Git, schema v21, service Meta, repository binding, UI account, route snapshot và các test liên quan. Giữ các sửa đổi chưa commit. Ghi nhận Graph API version và quyền thực tế từ Meta App được cấu hình; không đưa token vào log hoặc tài liệu.
2. **Xem trước Page.** Thêm thao tác chỉ đọc nhận token trong request, gọi Graph API với phân trang và giới hạn số trang/thời gian. Chỉ trả Page ID, tên, URL và quyền cần hiển thị; không trả Page token. Phân biệt `discovery_available`, `empty`, `permission_denied`, `unsupported`. Nếu không thể liệt kê, cho nhập nhiều ID rồi kiểm tra từng ID trực tiếp. Không đánh đồng `empty` với token không có Page nào.
3. **Kết nối nhiều Page.** Mở rộng luồng System User nhận danh sách Page ID, giữ tương thích request `page_id` cũ. Xác minh từng Page và Page token/quyền trước khi ghi; nếu Meta không trả Page task, hiển thị quyền chưa xác minh thay vì suy ra chắc chắn từ scope chung. Dùng một transaction để cập nhật connection và các binding đã chọn; lỗi ở một Page không để lại kết nối nửa chừng. Dùng ID số làm khóa định danh; chỉ ghép với target Chrome theo URL/slug khi khớp duy nhất, nếu mơ hồ yêu cầu chọn rõ. Không tạo bản sao tự động nếu Page đang được gắn với account Tinix khác.
4. **Quản lý vòng đời.** Nguồn sự thật của Page đã kết nối là các binding `connected`, thay cho metadata `page_id` đơn; dữ liệu một Page đã lưu vẫn đọc được. Thêm Page mới bằng token hiện tại chỉ tạo/cập nhật Page đó và giữ credential revision cùng binding khác. Khi thay token hoặc đổi phương thức xác thực, xem trước tất cả Page đang gắn: xác minh lại từng Page, báo rõ Page mất quyền, và chỉ cập nhật sau khi người dùng xác nhận danh sách thay đổi. Page bị bỏ liên kết chuyển `disconnected`; không xóa target, lịch sử, metrics hay schedule. Khi quyền/token của binding đang dùng thay đổi, tăng revision để release cũ phải dry-run/duyệt lại. Không chuyển job đã đóng băng sang Page hay transport khác.
5. **Giao diện.** Đổi ô Page ID đơn thành danh sách Page có checkbox, tên, Page ID, trạng thái đã gắn/chưa gắn, quyền đăng/chỉ đọc và lỗi. Có thao tác “Thêm Page ID thủ công”, “Thêm Page bằng token hiện tại”, “Thay token” và “Ngắt Page” riêng. Account hiển thị số Page API đang kết nối; panel chi tiết liệt kê từng Page và trạng thái. Khi discovery lỗi, giữ nguyên các Page đã gắn và hiển thị hướng xử lý. Xóa token khỏi input sau mỗi lần dùng, không lưu ở browser storage.
6. **Đồng bộ và kiểm soát phạm vi.** Lệnh “Đồng bộ Page API” của System User chỉ kiểm tra lại các Page đã chọn; kết quả discovery chỉ là ứng viên, không tự thêm/bỏ Page. Page mất quyền được đánh dấu rõ và chặn API publish/analytics cho Page đó. OAuth hiện tại tiếp tục hoạt động, nhưng trạng thái Page trên UI phải đếm binding `connected` thay vì đếm cả binding đã ngắt.
7. **Kiểm thử và nghiệm thu.** Test transaction rollback, hai Page cùng token, thêm Page thứ ba không làm đổi Page trước, ID sai/không có quyền, token thay thế thiếu một Page, Page trùng giữa account, phân trang, discovery lỗi, trạng thái UI và tương thích request cũ. Kiểm tra frozen release/approval/dry-run sau khi đổi token hoặc quyền; kiểm tra Chrome/OAuth/YouTube không đổi hành vi; analytics từng Page không trộn số. Chạy các test liên quan rồi full suite và `BUILD.bat`; theo AGENTS.md khởi động lại đúng server Tinix và kiểm tra health/version. Nghiệm thu Graph chỉ đọc bằng token nhập trực tiếp trong Tinix; mọi bài đăng thử thật cần chỉ thị riêng của người dùng.

### Tiêu chí hoàn thành

- Một token liên kết được ít nhất hai Page hợp lệ trong cùng account; mỗi Page có target/binding/quyền và analytics riêng. Thêm hoặc ngắt một Page không đổi binding của Page khác.
- Khi Meta không cho liệt kê Page, người dùng vẫn thêm nhiều Page ID thủ công và nhận lỗi cụ thể theo từng ID. Discovery thất bại không xóa kết nối đang dùng.
- Token thay thế không để Page cũ chạy bằng token cũ. Lịch đăng/release cũ không bị chuyển nhầm Page; trường hợp quyền thay đổi cần xác minh và duyệt lại.
- OAuth, Chrome và các nền tảng khác vẫn qua kiểm thử hồi quy; build và server local được xác minh sau khi triển khai.

### 14. Kết quả triển khai — 27-09-2026

- **Đã hoàn thành phần triển khai trong Tinix:** kết nối Meta System User hỗ trợ nhiều Facebook Page trên một account; có thể khám phá Page qua API hoặc nhập nhiều Page ID thủ công, thêm Page bằng token đang lưu, thay token với danh sách Page bị ngắt được xác nhận rõ, và ngắt riêng từng Page. Discovery không tự gắn Page; token/Page token không được trả về UI; quyền đăng không còn được suy đoán khi Meta không trả Page tasks. Trạng thái connection hiển thị số Page API đang kết nối.
- **Bảo toàn dữ liệu/vòng đời:** cập nhật connection và bindings trong transaction; thêm Page không làm đổi binding khác; kiểm tra Page trùng account; thay đổi credential/quyền cập nhật revision; ngắt Page giữ target, bài đăng, metrics và lịch sử hiện có. Giữ tương thích request `page_id` đơn và OAuth hiện tại.
- **Kiểm tra:** full suite **219 tests OK**; sau các chỉnh sửa cuối cùng, focused suite `tests.test_meta_page_api` và `tests.test_api` **48 tests OK**; `node --check app/static/js/accounts.js`, `python -m compileall -q app`, và `git diff --check` đạt. `BUILD.bat` thành công, tự động báo **100% PASSED**, tạo build version **1.0.30**.
- **Restart/health:** Tinix được khởi động lại bằng `START.bat`; listener cũ được thay. Listener hiện tại PID **6364**, command `pythonw.exe -m app` từ virtualenv của dự án; log ghi `Tinix Social Hub 1.0.30 is ready` lúc **22:18:00**. `/api/health` trả `ok`, version `1.0.30`, database `ok`, worker idle, không có warnings.
- **Trạng thái lúc hoàn tất triển khai:** chưa dùng Meta System User token thật và chưa đăng bài trong lượt code/build. Nghiệm thu live được thực hiện riêng sau đó; xem mục 15. Không tạo Git commit ở lượt triển khai.

## 15. Nghiệm thu Meta live — 27-09-2026

- **Connection:** dùng Meta System User connection `Tinix Fads` trên account Tinix `Thanh229tan`; connection có 6 Page bindings. Các binding cho Page ID `139438959247389` và Page ID `131419466718163` đều trả task `CREATE_CONTENT`.
- **Analytics cấp Page:** đọc thành công qua Graph API cho hai Page trên cùng connection, nhưng metrics được lưu riêng theo target. Page `Tí Nị Studio - Chụp ảnh cho bé và gia đình` (`139438959247389`) trả **3.634 followers / 3.634 page likes**; Page `Tí Nị - Chụp Ảnh Cho Bé Yêu` (`131419466718163`) trả **5 / 5**. Đây là snapshot tại thời điểm gọi, không phải dữ liệu lịch sử.
- **Đăng thật:** tạo đúng một bài văn bản thử nghiệm trên Page target có tên `Tí Nị Studio - Chụp ảnh cho bé và gia đình`, Page ID `139438959247389`; dùng `official_api_only`, dry-run đạt trước, release được Meta publisher xác minh `from.id` trùng Page ID. Release `a06d1921-3726-47c3-bfc1-78fc87e149ef` ở trạng thái `succeeded`/`verified`; permalink Meta trả về và HEAD trả HTTP 200: https://www.facebook.com/122219959346052215/posts/122219959340052215
- **Analytics cấp bài:** gọi lại thành công ngay sau khi đăng; snapshot ban đầu **0 likes, 0 comments**. API không trả shares ở lần đọc này. Collector hiện không có metric views; analytics kênh hiện chỉ cung cấp snapshot followers/page likes và không có chuỗi lịch sử.
- **Đối chiếu Page:** Meta xác nhận bài thuộc Page ID `139438959247389` và tên hiển thị khớp Page người dùng đã nêu. Tinix còn có target Chrome cũ dùng alias `url:tiniphotos` trên account khác; chưa có bằng chứng Graph độc lập trong lần nghiệm thu này để xác nhận alias cũ và Page ID mới là cùng một đối tượng. Link bài thật ở trên có thể dùng để người dùng đối chiếu trực tiếp.
- **Phạm vi:** chỉ đăng một bài text; không đăng media hay đăng lên Page khác. Kiểm tra bằng trình tải web bên ngoài bị Facebook throttling; link được Meta trả và endpoint HEAD phản hồi HTTP 200. Không có code thay đổi hoặc build/restart mới trong bước nghiệm thu này; không tạo Git commit.

## 16. Cải tiến sau review — 28-09-2026

- Giữ tính năng xem lại **System User token**: token tiếp tục được mã hóa bằng DPAPI và nút **Hiện** trong chi tiết account có thể giải mã để xem lại trên máy Tinix cục bộ. Cập nhật hướng dẫn sử dụng để mô tả đúng hành vi này.
- Bài thử nghiệm ở mục 15 đã được người dùng kiểm tra và xóa sau đó. Không đăng lại. Khi gọi analytics cho release `a06d1921-3726-47c3-bfc1-78fc87e149ef`, Meta trả Graph API 400; Tinix nay ghi trạng thái `unavailable`/`meta_post_unavailable` với thông báo bài có thể đã bị xóa, thay vì lỗi 500. Snapshot metrics của lần đọc thành công trước được giữ nguyên và giao diện nêu rõ dữ liệu đang xem là snapshot cũ.
- Siết liên kết Page với Tinix target: đồng bộ System User giữ nguyên target đã bind thay vì ánh xạ lại theo slug; kiểm tra Page ID/loại Facebook/account và từ chối trường hợp slug mơ hồ hoặc Page ID trùng account khác. Discovery `/me/accounts` tiếp tục phân trang, giới hạn 20 trang × 100 kết quả.
- Tạo target mới, connection và Page binding trong cùng transaction để lỗi lưu binding không để lại target hoặc connection mồ côi. Bổ sung xử lý lỗi Graph API theo HTTP status để analytics phân biệt bài không khả dụng, cần kết nối lại, rate limit và lỗi provider.
- **Kiểm tra:** full suite `python -m unittest discover -s tests` đạt **226 tests OK**; focused suite đạt **75 tests OK**; `node --check` cho `accounts.js` và `analytics.js`, `compileall`, và `git diff --check` đạt. `BUILD.bat` thành công, tự động báo **100% PASSED**, tạo build version **1.0.33**.
- **Restart/health:** đã thay backend Tinix cũ bằng listener mới PID **27828** (command chạy module `app` bằng Python virtualenv của dự án). `/api/health` trả `ok`, version **1.0.33**, database `ok`, worker idle, không có warnings. Analytics của release đã xóa trả `unavailable` thay vì 500; GET metrics xác nhận hai metric snapshot cũ vẫn còn.
- Không tạo bài đăng thử nghiệm mới và không tạo Git commit.

## 17. Khắc phục các điểm review Meta — 28-09-2026

- Ngăn tái sử dụng Tinix target đã bind vào Meta Page ID khác. Kiểm tra được thực hiện bên trong transaction lưu binding; nếu slug cũ khớp Page mới, request bị từ chối và binding/historical target hiện tại được giữ nguyên.
- Phân loại Meta Graph lỗi quyền, rate limit, object không còn khả dụng và lỗi yêu cầu khác cho cả analytics từng bài lẫn analytics cấp Page. HTTP 400 chung không còn mặc định là bài đã xóa; lỗi được ghi trong fetch run, snapshot cũ không bị thay khi fetch thất bại.
- Thêm endpoint trạng thái fetch mới nhất theo channel/Page và hiển thị trạng thái, thời điểm cập nhật trong Analytics. Bật thao tác cập nhật thủ công Facebook Page trong UI; trước đó collector Page đã có ở backend nhưng UI chỉ cho bấm cập nhật YouTube.
- Khi khám phá Page lại, nhãn quyền đăng được tính từ task mới thay vì giữ kết quả `can_publish` cũ. Nút xem lại System User token vẫn được giữ.
- **Kiểm tra:** full suite **230 tests OK**; focused suite **72 tests OK**; `node --check`, `compileall` và `git diff --check` đạt. Smoke test phát hiện endpoint trạng thái lỗi khi không có filter; đã sửa lỗi nối SQL và chạy lại full suite thành công. `BUILD.bat` thành công, tự động báo **100% PASSED**, tạo build **1.0.34**.
- **Restart/health:** backend trước build đã được dừng bởi `BUILD.bat`; `START.bat` khởi chạy backend mới PID **37804** từ virtualenv dự án. `/api/health` trả `ok`, version **1.0.34**, database `ok`, worker idle, không warnings. Endpoint `/api/analytics/channels/runs` trả HTTP 200; trang, module `main.js` và `analytics.js` tải asset version 1.0.34.
- Không gọi Meta để đăng bài và không tạo Git commit.

## 18. Hoàn tất follow-up sau review — 28-09-2026

- **OAuth Page binding nguyên tử:** đồng bộ Page OAuth nay xác thực toàn bộ mapping trong một transaction. Một Tinix target không thể bị đổi sang Meta Page ID khác; Page ID không thể bị gắn sang target khác. Nếu bất kỳ binding nào không hợp lệ, toàn bộ đồng bộ rollback và giữ target/binding trước đó. System User binding cũng dùng cùng quy tắc Page–target.
- **Analytics cấp kênh cho Page mới:** endpoint analytics liệt kê các Facebook Page đang kết nối kể cả khi chưa có fetch run hay metric snapshot. Vì vậy Page mới kết nối vẫn hiện trong analytics và có thể bắt đầu lần thu thập đầu tiên.
- **Trạng thái analytics từng bài:** giao diện cảnh báo mọi lần fetch gần nhất không thành công, nêu trạng thái/lỗi; nếu có snapshot cũ thì nói rõ đang hiển thị dữ liệu cũ, nếu chưa có thì báo chưa có snapshot hợp lệ. Giữ nguyên chức năng xem lại System User token.
- **Kiểm thử:** `python -m unittest discover -s tests` đạt **232 tests OK**; `compileall`, `node --check` cho `accounts.js`/`analytics.js`, và `git diff --check` đạt (Git chỉ cảnh báo chuẩn hóa line ending CRLF). `BUILD.bat` thành công, self-test **100% PASSED**, build version **1.0.35**.
- **Restart và xác minh:** backend Tinix mới chạy qua `START.bat`, listener PID **35556** (`pythonw.exe -m app`) trên cổng 8765. `/api/health` trả `ok`, version **1.0.35**, database `ok`, worker idle, không warnings. `/api/analytics/channels/connected-meta-targets` trả danh sách 6 target; `/api/analytics/channels/runs` trả HTTP 200; giao diện nạp asset version 1.0.35.
- Không tạo bài đăng mới, không thực hiện gọi Meta để đăng bài, và không tạo Git commit.

## 19. Sửa hai phát hiện trong review OAuth/Analytics — 28-09-2026

- OAuth callback nay đổi code lấy token, xác minh danh tính/quyền và khám phá Page trước. Sau khi mapping Page–Tinix hợp lệ, một transaction mới ghi connection/token, tăng credential revision, cập nhật target và binding. Nếu Page mapping bị từ chối, transaction rollback và connection/binding cũ tiếp tục nguyên trạng; lỗi callback không còn đổi connection cũ sang `scope_missing`.
- Trạng thái Page xuất hiện trong Analytics nay yêu cầu binding Meta và account connection cha cùng `connected`, đúng provider/transport. Binding còn lưu nhưng connection cần OAuth lại không được tính là Page đang kết nối analytics.
- Bổ sung hồi quy: OAuth re-connect với Page ID khác nhưng slug trùng giữ nguyên status, user token, revision, Page ID và Page token cũ khi bị từ chối; analytics bỏ Page khỏi danh sách khi connection chuyển `reauth_required` và hiện lại sau khi kết nối trở lại.
- **Kiểm tra:** focused suite `tests.test_meta_page_api tests.test_analytics` đạt **42 tests OK**; full suite đạt **233 tests OK**; `compileall`, `node --check` cho `accounts.js`/`analytics.js` và `git diff --check` đạt (Git có cảnh báo line-ending CRLF).
- **Build/restart:** `BUILD.bat` thành công, self-test **100% PASSED**, version **1.0.36**. `START.bat` đã khởi động listener mới PID **42960** từ virtualenv dự án. `/api/health` trả `ok`, version **1.0.36**, database `ok`, worker idle, không warnings. Endpoint Page đã kết nối trả 6 target, channel runs HTTP 200 và UI nạp asset version 1.0.36.
- Không đăng bài Meta mới và không tạo Git commit.

## 20. Hoàn tất cải tiến OAuth/Analytics sau review — 28-09-2026

- OAuth callback và đồng bộ OAuth thủ công xác minh danh sách Page trước khi ghi. Danh sách phân trang thiếu cursor hoặc vượt giới hạn 2.000 Page bị từ chối, không cập nhật connection/binding. Nếu token mới không còn quyền với Page đang gắn, Tinix trả tên và ID Page bị thiếu, giữ nguyên connection hiện tại; người dùng cần ngắt rõ Page đó trong Tài khoản & Page rồi thực hiện OAuth lại.
- Việc lưu OAuth connection/token, tăng revision, cập nhật target và binding vẫn nằm trong một transaction. Credential revision tăng đúng **một lần** cho mỗi lần OAuth thành công.
- Analytics thêm trạng thái connection/binding cho Page có số liệu. Thẻ có lịch sử vẫn giữ snapshot để xem, nêu rõ API đang cần kết nối lại/thiếu quyền/đã ngắt và khóa nút thu thập cho đến khi cả connection lẫn binding hoạt động. Page mới chưa có snapshot vẫn được liệt kê khi đang kết nối.
- **Kiểm thử:** focused suite `tests.test_meta_page_api tests.test_analytics` đạt **45 tests OK**; full suite đạt **236 tests OK**; `compileall`, `node --check app/static/js/analytics.js` và `git diff --check` đạt (cảnh báo line-ending CRLF của Git).
- **Build/restart:** `BUILD.bat` thành công, self-test **100% PASSED**, version **1.0.37**. `START.bat` khởi động listener mới PID **46616** từ virtualenv dự án. `/api/health` trả `ok`, version **1.0.37**, database `ok`, worker idle, không warnings. `/api/analytics/channels/meta-target-statuses` trả 6 binding, `/api/analytics/channels/runs` trả HTTP 200 và UI nạp asset version 1.0.37.
- Không gọi Meta để đăng bài và không tạo Git commit.

## 21. Khắc phục race giữa OAuth và đồng bộ Page — 28-09-2026

- OAuth callback chụp `credential_revision` ngay sau khi dùng OAuth state; transaction chỉ ghi token/binding nếu connection và revision vẫn khớp. Kiểm tra trong transaction cũng từ chối Page vẫn `connected` nhưng không nằm trong quyền OAuth vừa cấp, kể cả Page được thêm sau bước kiểm tra trước đó. Lỗi rollback giữ nguyên token và bindings cũ.
- Đồng bộ OAuth thường và System User nay gửi revision đã đọc trước các lệnh Graph; repository từ chối kết quả cũ nếu credential đã đổi trong lúc chờ Meta. Ngắt Page và tăng revision được thực hiện trong cùng transaction, nên thao tác đồng bộ đang chạy không thể ghi đè lựa chọn ngắt.
- Bổ sung hồi quy cho Page xuất hiện sau precheck, revision đổi giữa lúc OAuth gọi Meta, revision cũ ở hai kiểu đồng bộ và thao tác ngắt Page nguyên tử. Không thay đổi schema, không bỏ nút xem lại System User token.
- **Kiểm tra:** focused suite `tests.test_meta_page_api tests.test_analytics` đạt **50 tests OK**; full suite đạt **241 tests OK**; `compileall`, `node --check` cho `accounts.js`/`analytics.js`, và `git diff --check` đạt (cảnh báo chuẩn hóa line-ending CRLF).
- **Build/restart:** `BUILD.bat` thành công, self-test **100% PASSED**, version **1.0.38**. `START.bat` được chạy ẩn; listener mới PID **43716** chạy `pythonw.exe -m app` trong virtualenv dự án. `/api/health` trả `ok`, version **1.0.38**, database `ok`, worker/scheduler hoạt động và không warnings; giao diện trả asset `main.js?v=1.0.38`.
- Không gọi Meta để đăng bài và không tạo Git commit. `PROJECT_STATUS.md` không có trong thư mục dự án khi bắt đầu lượt này.

## 22. Khắc phục race khi đổi System User token và cập nhật Page count — 28-09-2026

- Tính và lưu `connected_page_count` bên trong transaction, đọc metadata mới nhất trước khi cập nhật để không ghi lùi `credential_revision` hoặc làm mất trường metadata khác.
- Khi System User credential thay đổi, transaction kiểm tra lại các Page đang `connected`. Mọi Page phải nằm trong danh sách được xác minh bằng credential mới hoặc danh sách ngắt Page đã xác nhận; Page bị thêm sau bước preflight khiến toàn bộ đổi token rollback.
- Bổ sung hồi quy cho metadata revision sau thao tác ngắt Page và cho Page mới xuất hiện trước transaction thay token. Cập nhật test chống ghép target/Page để xác nhận Page cũ bị ngắt rõ trước khi chạy kiểm tra chống gắn lại. Không đổi schema, không bỏ chức năng xem lại System User token.
- **Kiểm tra:** focused suite `tests.test_meta_page_api tests.test_analytics` đạt **52 tests OK**; full suite đạt **243 tests OK**; `compileall`, `node --check` cho `accounts.js`/`analytics.js`, và `git diff --check` đạt.
- **Build/restart:** `BUILD.bat` thành công, self-test **100% PASSED**, version **1.0.39**. `START.bat` chạy ẩn; listener PID **49288** chạy `pythonw.exe -m app` từ virtualenv dự án. `/api/health` trả `ok`, version **1.0.39**, database `ok`, scheduler hoạt động, không warnings.
- Không gọi Meta để đăng bài và không tạo Git commit.

## 23. Facebook Page API cho một ảnh và video thường — 28-09-2026

- Xác minh tài liệu chính thức Meta Graph API v26.0 cho Page Photos và Page Videos. Một ảnh dùng multipart `POST /{page-id}/photos`; video thường dùng chunk upload `start/transfer/finish` trên `/videos`. Cả hai dùng đúng Page token/binding và quyền publish hiện có; upload Facebook từ máy local không cần CDN HTTPS.
- Publisher ảnh kiểm tra snapshot/hash, giới hạn định dạng/kích thước, khôi phục bằng photo ID và xác minh ảnh thuộc đúng Page. Publisher video chỉ nhận một MP4, tiếp tục từ offset chunk đã xác nhận; chunk đang chờ hoặc finish timeout chuyển `unknown_result` và không tự gửi lại. Chỉ báo thành công sau khi finish trả video ID.
- Composer batch Facebook cho phép lập lịch format ảnh/video/Reel; nội dung format được đưa vào chữ ký preflight để đổi format thì kiểm tra lại.
- Tests fixture mục tiêu: Meta API, platform catalog và publisher routing đạt **81 tests**; compileall và `node --check app/static/js/compose.js` đạt. `BUILD.bat --no-bump` full suite **300 tests**, self-test báo **100% PASSED**. Không gọi Meta để đăng bài thật; chưa live-acceptance với App/Page/token thật. Nhiều ảnh trong cùng bài còn mở; Instagram publishing tiếp tục phụ thuộc media URL HTTPS.
- Backend cũ PID **22612** đã được thay bằng PID **43588** từ đúng workspace. `/api/health` trả `ok`, version **1.0.43**, database `ok`, worker idle, scheduler running, không warnings; `/api/platforms` và composer JS mới trả HTTP 200. Không tạo Git commit.
