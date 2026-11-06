# Giai đoạn 09 — Analytics định kỳ và dữ liệu có nguồn rõ ràng

Trạng thái: **Đã triển khai scheduler YouTube/Meta tùy chọn, bounded và có claim chống chạy trùng; Meta Reel và Page đã nghiệm thu thu thập thủ công qua API thật**. Cập nhật: 29-09-2026.  
Thuộc [kế hoạch tổng](plan_postiz.md), tách phần analytics của M6.

## Mục tiêu và phụ thuộc

Cho phép cập nhật analytics có kiểm soát trên những provider đã có collector hợp lệ, ưu tiên đưa Meta Page/post vào cơ chế định kỳ. Người dùng biết số liệu thuộc bài/Page nào, được đọc khi nào và có còn mới không.

YouTube API analytics, scheduler tùy chọn, Meta manual collector và fetch run đã có. Không xây lại chúng. Phụ thuộc identity/reconciliation đủ chắc của giai đoạn 04; không phụ thuộc Facebook ảnh/video hoặc Instagram API. Có thể làm sớm sau giai đoạn 04 khi nhu cầu báo cáo cao.

## Các bước triển khai

### 09A. Hợp đồng metric và identity

1. Rà metric đang thu thập, đơn vị, source, snapshot/cumulative hay số theo kỳ và điều kiện quyền.
2. Chốt khóa provider + target + external post + thời điểm/kỳ + metric; không gộp Page qua tên hoặc cộng nhiều snapshot thành tổng phát sinh.
3. Với release đổi identity sau đối soát, giữ provenance lịch sử, không trộn metrics của bài cũ và bài mới.
4. Chỉ mở metric collector thực sự hỗ trợ. Views/reach/impressions mới cần xác minh riêng, không suy ra từ likes.

### 09B. Scheduler cho nhiều provider

1. Mở rộng scheduler hiện có bằng dispatch collector theo provider đủ điều kiện, tránh refactor thành hệ thống orchestration mới.
2. Giữ cấu hình YouTube cũ; Meta tự động là opt-in riêng hoặc được chọn rõ theo provider/target.
3. Giới hạn số bài/kênh mỗi lượt, khoảng thời gian, cooldown và ngân sách request. Chống chạy chồng và starvation khi nhiều target đến hạn.
4. Dùng backoff/Retry-After theo phản hồi; lỗi quyền dừng retry dồn dập tới khi connection thay đổi phù hợp.
5. Wake sau sleep/restart chạy có giới hạn, không dồn mọi lần đã lỡ thành burst. Ứng dụng local đóng thì lịch không chạy; UI nêu lần chạy và lần dự kiến tiếp theo.
6. Thu thập thủ công và định kỳ cùng target không ghi kết quả cũ đè trạng thái mới; chốt thứ tự fetch run/timestamp và kiểm tra credential revision.

### 09C. Trải nghiệm báo cáo

1. Hiển thị lần fetch gần nhất, lần thành công gần nhất, source và thời điểm của dữ liệu đang xem.
2. Phân biệt chưa có dữ liệu, unsupported, cần kết nối lại, rate-limited, unavailable và giá trị 0 thật.
3. Biểu đồ chỉ nối các điểm cùng metric/đơn vị/ý nghĩa; khoảng thiếu dữ liệu không giả thành 0.
4. Account/binding ngắt vẫn giữ lịch sử, khóa fetch không hợp lệ và hướng người dùng tới đúng thao tác kết nối.
5. Thông báo khi có lỗi cần hành động hoặc thay đổi quan trọng, tránh thông báo sau mỗi lần thu thập thành công không đáng chú ý.

## Kiểm thử và nghiệm thu

- Hai Page chung token lưu metrics tách biệt; manual và scheduler không trộn trạng thái.
- Một provider rate-limit không làm provider khác bị bỏ đói; giới hạn request mỗi lượt được giữ.
- Lỗi mạng/quyền/bài đã xóa giữ snapshot cũ kèm trạng thái đúng; không đổi metric thành 0.
- Restart/máy ngủ dài không tạo request burst; opt-out dừng công việc theo policy rõ.
- Credential/identity đổi trong lúc fetch không gán dữ liệu cho binding mới.
- Cấu hình YouTube cũ và truy vấn lịch sử vẫn hoạt động; Page mới chưa có snapshot vẫn có thể bắt đầu fetch.
- Nghiệm thu API chỉ đọc theo phạm vi người dùng cho phép; không cần tạo bài mới để chứng minh analytics.

## Vùng mã và bàn giao

`analytics_scheduler.py`, `api_analytics.py`, analytics repositories/routes, `analytics.js` và tests analytics/provider/frontend. Migration chỉ khi thiếu provenance cần thiết, có kiểm tra dữ liệu cũ.

Giao Meta refresh giới hạn trước, sau đó lịch sử/biểu đồ theo nhu cầu. Kiểm tra/build/restart theo kế hoạch tổng. Không biến analytics thành cam kết mọi metric của mọi nền tảng.

Tiếp theo: [giai đoạn 10](plan_postiz_10_acceptance_operations.md).

## Kết quả triển khai

- Giữ nguyên opt-in YouTube; Facebook Page có công tắc opt-in riêng. Mỗi provider dùng collector/nguồn provenance riêng và giới hạn số bài/kênh mỗi lượt.
- Lịch chạy một lượt có giới hạn sau khi khởi động/wake, không phát bù burst; trạng thái cho biết lần gần nhất, số kết quả tổng hợp và lượt dự kiến. Tinix đóng thì scheduler dừng.
- Danh sách đến hạn lọc theo platform/source và cooldown riêng; collector xử lý tuần tự để lỗi/rate limit của provider không ngăn lượt provider khác.
- Repository claim theo identity + source trong transaction, ngăn manual và scheduler ghi đè/chạy chồng cùng một đối tượng; claim treo quá hai giờ được xem là stale. API báo 409 khi đã có lượt đang chạy.
- UI nêu trạng thái unsupported, lỗi/quyền và giữ snapshot cũ; metrics hiện có giữ source, ngày, đơn vị và trạng thái fetch. Không mở rộng tập metric trong đợt này.
- Kiểm tra scheduler opt-in/bounds/dispatch, claim trùng, provenance, collector mock và API settings đạt.
- Ngày 29-09-2026, thu thập thủ công trên Reel thử của Page Tinix đã phát hiện Graph video từ chối trường `shares` (code 100). Collector nay phân nhánh theo format: post/ảnh dùng `shares`, video/Reel dùng `views`; cả hai dùng summary của likes/comments khi Meta trả. Không tạo giá trị 0 thay cho metric vắng mặt. Phản hồi chuẩn hóa permalink tương đối thành URL Facebook đầy đủ.
- Sau sửa, live fetch Reel `1329975209041799` trả `succeeded`, lưu `likes=0`, `comments=0`, `views=0` với source `api_meta_graph`; đây là giá trị Meta trả tại thời điểm kiểm tra, không phải số lịch sử. Live fetch Page Tinix `1106784475845782` cũng `succeeded`, lưu `followers=0` và `page_likes=0`. Scheduler tự động vẫn mặc định opt-in, chưa bật trên Page người dùng.
- Targeted regression tests và full `BUILD.bat --no-bump` đạt 100%; backend mới PID 18992, `/api/health` `ok`, database `ok`, worker idle, không warnings. Chưa nghiệm thu một chu kỳ scheduler live tự động.

### Kiểm tra scheduler live — 28-10-2026

- Runtime có `enabled=false`, `meta_enabled=true`, chu kỳ 24 giờ; scheduler Meta vì vậy đang opt-in. Lần chạy 08:59 UTC thử một bài và ghi `needs_action`.
- Đối chiếu release `b53a5db5-e01d-44a1-b20e-9a595656a98b` với verification note đã lưu: Graph API v26.0 trước đó xác nhận Reel `1433112448754530` thuộc Page `1106784475845782`, published và caption khớp. Đã ghi `external_release_id=1433112448754530` qua `manual_connect`.
- Fetch API mới nhất trả `meta_post_unavailable` (Graph code 100), không có metric mới. Query scheduler sau đó xác nhận release không còn đến hạn trong cooldown 24 giờ; kết quả cũ vẫn được giữ.
- Tám kiểm thử mục tiêu cho batch scheduling, reschedule, frozen release/job, recovery sau commit và scheduler analytics đều PASS. Điều này xác minh các fixture tương ứng; chưa thay thế nghiệm thu toàn luồng Giai đoạn 10B hay một lần scheduled fetch thành công.
- Full suite `unittest` hiện tại cũng PASS **367 tests** trên Python 3.13 ngày 28-10; scheduler Meta vẫn cần một chu kỳ tự động thu metric thành công để nghiệm thu live.

### Instagram Insights live verification — 2026-10-29

- The connected Instagram Login account `@tannguyen3569` (`17841425556322045`) has scope `instagram_business_manage_insights`.
- A live Reel Insights request succeeded for media `17938602174125398`: reach=1, likes=2, comments=2, saved=0, shares=0, total_interactions=4. A profile Insights request also succeeded and returned reach=0.
- These are point-in-time snapshots; the collector does not fetch a historical trend in this run. No content was created and no App Review request was made.
- Runtime scheduler remains opt-in for Meta and Instagram at a 6-hour interval; automatic-cycle acceptance is still pending.
