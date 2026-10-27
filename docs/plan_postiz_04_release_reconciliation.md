# Giai đoạn 04 — Chi tiết kết quả đăng và đối soát

Trạng thái: **Đã triển khai và kiểm tra bằng fixture/UI; chưa nghiệm thu live**. Ngày hoàn tất: 28-09-2026.  
Thuộc [kế hoạch tổng](plan_postiz.md), tách phần release/reconciliation của M5.

## Mục tiêu và phụ thuộc

Từ bài viết hoặc lịch, người dùng thấy rõ từng Page/kênh đã đăng gì, kết quả, link bài, lỗi và bước xử lý tiếp theo.

Phụ thuộc giai đoạn 01 và dữ liệu release/job hiện có; không phải chờ preset, calendar mới hoặc mở rộng API. Triển khai phần đọc/hiển thị trước, thay đổi thao tác đối soát sau.

## Các bước triển khai

### 04A. Chi tiết release và nhóm

1. Kiểm tra API hiện có, chỉ bổ sung dữ liệu còn thiếu; dùng snapshot release, không dùng draft mới nhất làm nội dung “đã đăng”.
2. Phần chính hiển thị target/account/platform, nội dung/media, thời gian, trạng thái, URL và thông báo lỗi có hướng xử lý.
3. Phần mở rộng chứa route, revision, attempts, events, artifacts và provider request reference. Không đưa token/secret vào UI/log.
4. Kết nối cùng màn detail từ bài viết, calendar, job và analytics bằng release ID ổn định.
5. Nhóm hiển thị tổng số đích và các số đã thành công/đang chờ/lỗi/cần đối soát. Dry-run không được tính là bài đã đăng thật.

### 04B. Hành động theo trạng thái

1. Backend quyết định action hợp lệ tại lúc xử lý: retry, cancel, mở bài, đối soát hoặc đổi lịch.
2. Retry chỉ cho đúng release/job còn đủ điều kiện trước commit. Không có nút retry cả nhóm làm chạy lại bài thành công.
3. Với `unknown_result`, dẫn tới đối soát; không tự đổi route hoặc tạo bài thay thế.
4. Nút hủy nêu rõ phạm vi. Hủy job local không được trình bày thành xóa bài trên mạng xã hội.

### 04C. Đối soát thủ công

1. Thay prompt URL bằng dialog có Page/kênh, nội dung snapshot, thời gian và bằng chứng đã lưu.
2. Kiểm tra URL/ID theo provider; kiểm tra đúng target và đúng post nếu API cho phép.
3. Nếu chỉ có xác nhận thủ công, lưu nguồn xác nhận đó và không gắn nhãn API-verified.
4. Ghi audit trước/sau khi đổi identity, lý do và phương thức xác nhận. Rà semantics metrics đã gắn identity cũ: giữ lịch sử có provenance, không âm thầm gán số cũ sang bài mới.
5. Gợi ý bài gần đây chỉ làm sau khi provider hỗ trợ đáng tin; cần người dùng chọn/xác nhận, không ghép tự động bằng caption giống nhau.

## Kiểm thử và nghiệm thu

- Nhóm ba release: thành công, lỗi trước commit, unknown; UI/action đúng từng dòng.
- Draft bị sửa sau schedule nhưng detail vẫn hiển thị snapshot đã đóng băng.
- Retry/cancel đồng thời worker đổi trạng thái phải bị backend kiểm tra lại.
- URL sai platform, sai Page, ID xung đột và bài không truy cập được không nhận thành verified giả.
- Đổi URL không làm mất audit hoặc trộn metrics hai identity.
- Metrics cũ có nhãn thời điểm/source và trạng thái lần fetch gần nhất; unsupported khác 0.
- Link artifact không bị mở rộng quyền/path ngoài cơ chế hiện có.

## Vùng mã và đầu ra

`jobs.js`, `analytics.js`, `compose.js`, `posts.js`, API routes, publication/analytics repositories và các test reliability/API/analytics/frontend.

Đầu ra là một đường xem và xử lý kết quả thống nhất. Không mở rộng public sharing hoặc xóa/sửa bài trên nền tảng trong giai đoạn này.

Kiểm tra, build, restart và báo cáo theo kế hoạch tổng. Tiếp theo: [giai đoạn 05](plan_postiz_05_calendar_slots.md).

## Kết quả triển khai

- Detail dùng payload/media/settings snapshot đã đóng băng, hiển thị Page/account, route, trạng thái, events, attempts và artifacts với các trường đã lọc; không trả raw payload hay secret.
- Bài viết hiển thị số release theo trạng thái (kể cả dry-run) và mở được từng Page/kênh.
- Retry/cancel chỉ hiện theo trạng thái hiện tại của job. Cancel giải thích rõ chỉ hủy job local; backend kiểm tra lại điều kiện.
- Dialog đối soát yêu cầu URL, ghi chú bằng chứng và xác nhận riêng Page/kênh cùng bài đăng. Phương thức manual được audit; URL đã gắn không thể chuyển sang identity khác.
- Kiểm tra API detail/snapshot, schedule regression, manual audit/identity và Playwright Calendar/detail đạt; build/restart thuộc lần nghiệm thu tổng sau các giai đoạn code.
- Chưa nghiệm thu live; analytics giữ provenance và không tự chuyển identity.
