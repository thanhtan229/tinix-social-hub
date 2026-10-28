# Tiến độ agent — Tinix Social Hub

Cập nhật: 28-10-2026. Bản ghi handoff ngắn theo TINIX V2.1 mục 14; không thay thế Git hay bằng chứng test.

## Milestone hiện tại
Postiz 01–10 hoàn tất ở mức code/fixture. Live đã có cho Facebook Page (text, ảnh đơn, album 2–5 và 10 ảnh, video, Reel) và Instagram (ảnh đơn, carousel 2 và 5 ảnh, Reel). Git remote `origin` đã cấu hình và `master` đã push.

## Đã hoàn thành
- Remediation FINAL_REVIEW F01–F08 (1.0.44).
- Facebook Page API live: bài chữ, ảnh đơn, album 2/3/4/5/10 ảnh, video Page thường, Reel.
- Instagram Login live: `@tannguyen3569` (Huong Vo). Ảnh đơn, carousel 2 và 5 ảnh, Reel (MP4 qua R2).
- Publisher carousel Instagram (2–10 JPEG) có checkpoint khôi phục; publisher Reel (REELS, chờ xử lý theo khuyến nghị Meta: mỗi phút, tối đa 5 lần).
- Làm mới token Instagram theo lịch: khi khởi động và mỗi 24 giờ, làm mới các token hết hạn trong 7 ngày. Token hiện tại hết hạn 26-12-2026.
- Analytics Facebook: scheduler đã bật (24 giờ). Số người theo dõi Page đọc được. Bài thử mới đọc được likes/comments qua API.
- AI: Gemini key mới trong app; key cũ đã thu hồi và xóa khỏi `.env`.
- Build xác minh 28-10-2026: `BUILD.bat --no-bump` PASS 100%.

## Bài thử đã đăng (có thể xóa)
- Album FB 5 ảnh: https://www.facebook.com/122132248658779083/posts/122137990040779083 (người dùng đã xóa; kiểm tra lại).
- Album FB 10 ảnh: https://www.facebook.com/122132248658779083/posts/122137991528779083
- Ảnh đơn FB (mới): https://www.facebook.com/122132248658779083/posts/122138021468779083
- Carousel IG 2 ảnh: https://www.instagram.com/p/DfBnqUhibGq/
- Carousel IG 5 ảnh: https://www.instagram.com/p/DfBozoWiXM0/
- Carousel IG 10 ảnh (10 container con xác nhận): https://www.instagram.com/p/DfCE4Gbid3r/
- Reel IG: https://www.instagram.com/reel/DfBrpiNG402/

## Đang mở / chưa nghiệm thu
- Analytics bài đăng cũ (album) vẫn `meta_permission_denied` / `meta_post_unavailable`; nguyên nhân chưa xác định. Chu kỳ scheduler đầu tiên (28-10 08:59) ghi 1 mục `needs_action`, chưa rõ lý do.
- Kết nối Đỗ Minh Duy: các Page đã thuộc Thanh229tan (chặn trùng binding là đúng). Kênh URL-based của Duy không phải Page số.
- Đường thu Chrome (`method=chrome`): không đọc được số liệu bài; chưa dùng. Bộ chọn chưa khớp giao diện tiếng Việt.
- Giới hạn Reel (dung lượng 100 MB, thời lượng) là giả định tự đặt, chưa xác minh từ tài liệu Meta.
- Lỗi đã biết, chưa rõ nguyên nhân: lượt kết nối Instagram đầu bị `ig_exchange_token` trả code 100 "Unsupported request - method type: get"; lượt sau thành công.
- Carousel IG 6–9 ảnh: chưa thử riêng (carousel 10 ảnh đã thành công).
- Multi-Page (01): fixture/UI xong, chưa live. Giai đoạn 02–05: fixture/UI, chưa nghiệm thu live.
- TikTok, X: scaffold, chưa bật.
- NOT TESTED: lint/typecheck, CI Python 3.11, clean install, power loss, workload lớn.

## Quyết định kỹ thuật
- Test `test_snapshots_use_latest_value...`: ngày tương đối thay cho ngày cố định.
- Test `test_integration_buttons_open_dialog`: chặn `legacy-models` trong test.
- Instagram publisher: carousel và Reel dùng checkpoint, không tạo container lần hai và không publish lần hai khi gián đoạn.
- Làm mới token Instagram chỉ khi còn dưới 7 ngày; lỗi từng kết nối không dừng các kết nối khác.

## Runtime
- Tinix đang chạy sau `START.bat` (health `ok`, version 1.0.44). Scheduler analytics Facebook đang BẬT.

## Bước tiếp theo đề xuất
1. Theo dõi chu kỳ analytics Facebook tiếp theo (khoảng 28-10 08:59 +24 giờ) và kiểm tra `last_run`.
2. Làm rõ nguyên nhân `meta_permission_denied` cho bài cũ, hoặc chấp nhận và bỏ qua bài cũ.
3. Ghi lịch nhắc làm mới token Instagram trước 26-12-2026 (tự động đã có, nhưng cần kiểm tra kết nối vẫn "connected" trước đó).
4. Tùy chọn, theo chỉ thị: carousel IG 6–10 ảnh; album FB 6–9 ảnh; Multi-Page live.
