# Giai đoạn 02 — Composer đa nền tảng và validation theo từng đích

Trạng thái: **Hoàn tất phạm vi fixture/UI; chưa nghiệm thu live publish**. Hoàn tất: 28-09-2026.  
Thuộc [kế hoạch tổng](plan_postiz.md), chi tiết hóa M3. Phụ thuộc giai đoạn 01.

## Mục tiêu

Mở rộng cùng composer sang các nền tảng Tinix đã có adapter, cho phép nội dung/media/settings khác nhau trong cùng kế hoạch. Việc một platform xuất hiện trong catalog không tự chứng minh mọi account hay format dùng được.

## Phạm vi và điều kiện

- Facebook, Instagram, TikTok, YouTube và X chỉ hiển thị capability đúng theo mã và bằng chứng hiện có khi triển khai.
- Không triển khai provider mới hoặc Instagram Official API trong giai đoạn này; phần đó thuộc giai đoạn 08.
- Giai đoạn 01 đã có resolver, revision, transaction và idempotency đủ dùng. Nếu chưa đạt, hoàn thiện phần phụ thuộc trước.

## Các bước triển khai

### 02A. Ma trận capability và metadata

1. Lập bảng platform × format × transport: nội dung bắt buộc, settings, loại media, quyền kết nối, validation và cách xác minh kết quả.
2. Kiểm tra field UI có được publisher xử lý thực sự hay không; field chưa hỗ trợ phải được báo đúng trạng thái.
3. Đọc metadata bằng thư viện/công cụ đã có. Với constraint media mới, xác minh tài liệu provider tại thời điểm triển khai; không hardcode giới hạn suy đoán.
4. Metadata thiếu hoặc chưa xác minh phải có kết quả rõ: chặn nếu đó là kiểm tra bắt buộc, hoặc cảnh báo có lý do nếu chỉ là khuyến nghị.

### 02B. Media và settings riêng

1. Thêm lựa chọn media dùng chung hoặc riêng theo target, với danh sách asset có thứ tự.
2. Giữ reference cho mọi media mà draft/revision/release cần dùng. Chọn video riêng cho YouTube không làm mất ảnh của Facebook.
3. Form settings và preview theo target; source caption/hashtags/title phải khớp bản backend resolve.
4. Settings và media mới ảnh hưởng xuất bản phải đi qua lưu revision/duyệt; không truyền nội dung chưa duyệt từ form schedule.

### 02C. Mở luồng đa nền tảng

1. Bộ chọn target gom theo platform/account nhưng vẫn định danh từng đích riêng.
2. Preflight trả lỗi từng target, route dự kiến và bản xuất bản hiệu lực.
3. Dùng nguyên cơ chế batch giai đoạn 01. Không nới giới hạn worker để chạy đồng thời chỉ vì có nhiều nền tảng.
4. Tính trạng thái nhóm từ releases; không suy trạng thái toàn nhóm từ một bài đã thành công.

## Kiểm thử và nghiệm thu

- Một kế hoạch có Facebook ảnh, YouTube video và một adapter khác trong fixture; mỗi release nhận đúng asset/format/settings.
- Platform kế thừa Global, platform có variant, target có override cùng tồn tại đúng.
- Caption dài, thiếu title/settings, media sai loại/số lượng, metadata thiếu, transport không đủ khả năng đều báo đúng đích.
- Facebook API text-only từ chối media trước commit; route đã chọn không tự đổi vì lỗi sau commit.
- Reference count, duplicate, restore và xóa asset không phá media của đích khác.
- Dry-run theo account/target/format/transport; readiness chưa nghiệm thu không bị trình bày thành đã xác minh.
- Fixture, Playwright và hồi quy routing/validation/scheduling qua; nghiệm thu live ghi riêng từng capability có thực hiện.

## Vùng mã và đầu ra

Composer chính, `platforms/catalog.py`, `platforms/validation.py`, `publisher_router.py`, `scheduling.py`, media/content repositories và các suite tương ứng. Tái sử dụng cấu trúc giai đoạn 01; chỉ migration khi cần biểu diễn dữ liệu mới thực sự.

Đầu ra: một composer đa nền tảng thống nhất, bảng capability hiện hành và hướng dẫn lỗi theo đích. Không cần mọi platform đạt live acceptance mới giao các capability đã đủ điều kiện; báo rõ phần chưa được nghiệm thu.

Tiếp theo: [giai đoạn 03](plan_postiz_03_reusables_media.md). Quy tắc kiểm thử, build/restart, bảo vệ thay đổi có sẵn và không tự commit trong kế hoạch tổng áp dụng đầy đủ.

## Kết quả triển khai và review

- Composer/lịch batch nhận nhiều target qua nhiều account và platform; format, settings, thời điểm và media resolve riêng từng target. Chỉ platform/format/transport được catalog và publisher xác nhận mới qua preflight.
- Thêm target media override với ba trạng thái rõ: kế thừa media chung, danh sách riêng có asset, hoặc danh sách riêng rỗng. Chọn trong Media Library được stage ở client và chỉ ghi khi lưu; hủy editor không ghi thay đổi target media.
- Target media cùng content revision, approval invalidation, duplicate/restore và reference protection. Ghi lại lựa chọn giống hệt là no-op, không tạo revision thừa.
- Review bổ sung: lỗi attach không bị nuốt; luồng batch hiện dùng cùng resolver/validator backend; UI kiểm thử xác nhận asset IDs được gửi đúng và dialog lưu thành công.
- Kiểm tra: 137 test backend/API liên quan đạt; Playwright 9 test đạt; `node --check app/static/js/posts.js` và `python -m compileall -q app tests` đạt.
- Chưa chạy live publish trên Page/kênh người dùng. Bằng chứng hiện tại là fixture, route/preflight và UI; không xem đó là nghiệm thu quyền/account thật.
- `Build.bat`: full suite 100% passed; build tạo `v1.0.41`.
- Restart/health: backend cũ dừng theo build script; listener mới PID 55528 thuộc đúng thư mục dự án, `/api/health` trả `ok`/`v1.0.41`, `index` dùng `main.js?v=1.0.41` và bundle `posts.js` có route media target.
