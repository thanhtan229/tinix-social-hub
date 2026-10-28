# Tiến độ agent — Tinix Social Hub

Cập nhật: 27-10-2026. Bản ghi handoff ngắn theo TINIX V2.1 mục 14; không thay thế Git hay bằng chứng test.

## Milestone hiện tại
Hoàn tất các đợt Postiz 01–10 ở mức code/fixture; live acceptance Facebook Page đã có (text, ảnh đơn, album 2–4 ảnh, video Page thường, Reel). Checkpoint commit `c53ce01`.

## Đã hoàn thành
- Remediation FINAL_REVIEW F01–F08 (1.0.44).
- Facebook Page API live-verified trên Page Tinix: bài chữ, ảnh đơn, album 2–3 ảnh, video Page thường, Reel.
- Album 4 ảnh live (27-10-2026): content `57a2a057-…`, release `fdfbfa91-…`, post `1106784475845782_122137896080779083`, 4 photo ID, verification `verified` (publisher). Đây là bài thử công khai, có thể xóa sau khi kiểm tra.
- Analytics YouTube và Meta: fetch thủ công qua API thật đã PASS.
- Build xác minh 27-10-2026: `BUILD.bat --no-bump` PASS, "Kiểm thử: 100% PASSED!", version 1.0.44.
- AI: cấu hình Gemini trong app (DB) dùng key mới, làm mới được danh sách model.
- `.env`: đã xóa giá trị `TINIX_AI_API_KEY` (key cũ bị Google báo lộ).

## Đang mở / chưa nghiệm thu
- Album Facebook: đã live 2, 3, 4, 5 và 10 ảnh (28-10-2026, dry-run rồi real `succeeded`). Album 5 ảnh: https://www.facebook.com/122132248658779083/posts/122137990040779083. Album 10 ảnh: https://www.facebook.com/122132248658779083/posts/122137991528779083. Caption có nhãn BÀI THỬ.
- Instagram carousel 2 ảnh: đã phát triển publisher carousel (container con, container CAROUSEL, checkpoint khôi phục, test fixture PASS) và đăng thật thành công: https://www.instagram.com/p/DfBnqUhibGq/ . Đã commit `1f5778c`. Carousel 5 ảnh: https://www.instagram.com/p/DfBozoWiXM0/ (5 container con xác nhận). Carousel 6–10 ảnh: chưa thử.
- Video Page thường sau bản sửa: fixture PASS, chưa live lần hai.
- Instagram 1 ảnh live: đã kết nối `@tannguyen3569` (Huong Vo), R2 đã cấu hình. Đăng thử 1 ảnh JPEG thành công (job `a06e9ae4-…`, release `verified`, post `DfARbESEyNj`). Người dùng đã xem và xóa bài thử.
- Lỗi chưa rõ nguyên nhân: lượt kết nối đầu bị Meta `code=100` "Unsupported request - method type: get" ở bước `ig_exchange_token`. Lượt sau thành công, không có thay đổi cấu hình rõ ràng nào được xác nhận. Có khả năng liên quan đến việc tài khoản tester chưa chấp nhận lời mời, nhưng chưa được xác minh.
- Instagram carousel, Reel, nhiều ảnh: chưa thử.
- Thay đổi chưa commit: sửa provider trong `integrations.js`; miễn kiểm tra cross-site cho đúng callback Instagram trong `local_boundary.py` (có test); log chẩn đoán Meta trong `instagram_accounts.py`.
- Git remote: chưa cấu hình. Chưa push; cần URL remote từ người dùng.
- Multi-Page (01): fixture/UI xong, chưa live.
- Giai đoạn 02–05: fixture/UI xong, chưa nghiệm thu live.
- Analytics tự động (09): scheduler opt-in, mặc định tắt; chưa có chu kỳ live.
- TikTok, X: scaffold, chưa bật.
- NOT TESTED: lint/typecheck, CI Python 3.11, clean install, power loss, workload lớn.

## Quyết định kỹ thuật
- Test `test_snapshots_use_latest_value_instead_of_adding_daily_counts`: ngày snapshot cố định nằm ngoài cửa sổ `summary(30)`. Đổi sang ngày tương đối.
- Test `test_integration_buttons_open_dialog`: chặn `POST /api/integrations/ai/legacy-models` trong test.
- Tài liệu đồng bộ: README, PLAN.md, docs/LOCAL_AUTOMATION.md, docs/PLATFORM_ARCHITECTURE.md.

## Runtime
- Server Tinix đang chạy sau `START.bat` (health `ok`, version 1.0.44).

## Bước tiếp theo đề xuất
1. Commit các thay đổi chưa commit (sửa lỗi UI, boundary Instagram, log chẩn đoán) sau khi người dùng yêu cầu rõ.
2. Git remote: người dùng cung cấp URL remote; sau đó push nhánh `master`.
3. Thu hồi key Gemini cũ đã bị lộ trong Google AI Studio (người dùng xác nhận đã làm chưa).
4. Tùy chọn, theo chỉ thị: album 5–10 ảnh Facebook; Instagram carousel hoặc nhiều tài khoản.
