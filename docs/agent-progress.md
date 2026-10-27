# Tiến độ agent — Tinix Social Hub

Cập nhật: 27-10-2026. Bản ghi handoff ngắn theo TINIX V2.1 mục 14; không thay thế Git hay bằng chứng test.

## Milestone hiện tại
Hoàn tất các đợt Postiz 01–10 ở mức code/fixture; live acceptance Facebook Page đã có (text, ảnh, album 2–3, video Page thường, Reel). Đang ở giai đoạn ổn định trước khi commit checkpoint.

## Đã hoàn thành
- Remediation FINAL_REVIEW F01–F08 (1.0.44).
- Facebook Page API: bài chữ, ảnh đơn, album 2–3 ảnh, video Page thường, Reel đã live-verified trên Page Tinix.
- Analytics YouTube và Meta: fetch thủ công qua API thật đã PASS.
- Build xác minh 27-10-2026: `BUILD.bat --no-bump` PASS, "Kiểm thử: 100% PASSED!", version 1.0.44.
- Sửa 2 test lỗi trong suite (xem Quyết định kỹ thuật).

## Đang mở / chưa nghiệm thu
- Album Facebook 4–10 ảnh: chưa live (cần chỉ thị về Page và nội dung, vì bài công khai).
- Video Page thường sau bản sửa: fixture PASS, chưa live lần hai.
- Instagram publishing (08A/08B): code và fixture xong; chờ cấu hình Cloudflare R2 và OAuth/quyền Meta thật. Không gửi secret qua chat.
- Multi-Page (01): fixture/UI xong, chưa live.
- Giai đoạn 02–05: fixture/UI xong, chưa nghiệm thu live. Kéo-thả calendar đã hoãn.
- Analytics tự động (09): scheduler opt-in, mặc định tắt; chưa có chu kỳ live.
- TikTok, X: scaffold, chưa bật.
- NOT TESTED: lint/typecheck, CI Python 3.11, clean install, power loss, workload lớn.

## Trạng thái Git (chưa commit)
- Branch `master`, HEAD `fd0f788`. Không tạo commit theo AGENTS.md (chỉ commit khi người dùng yêu cầu).
- 73 file tracked đã sửa và 27 file untracked. Nhóm đề xuất khi commit: (1) Meta/Instagram providers, services, tests; (2) remediation F01–F08 (worker_lock, cleanup, restore, image recovery, production regressions); (3) Postiz UI/composer/calendar/analytics; (4) tài liệu plan_postiz_* và FINAL_REVIEW.md.
- Có file lock `.tinix-worker-*.lock` (nội dung `0`) — chưa xác định chủ sở hữu.

## Quyết định kỹ thuật
- Test `test_snapshots_use_latest_value_instead_of_adding_daily_counts`: ngày snapshot cố định 2026-09-20/21 nằm ngoài cửa sổ `summary(30)` khi chạy hôm nay. Đổi sang ngày tương đối với hôm nay. Đây là lỗi test, không phải lỗi sản phẩm.
- Test `test_integration_buttons_open_dialog`: request `POST /api/integrations/ai/legacy-models` gọi nhà cung cấp thật bằng cấu hình `TINIX_AI_*` trong `.env` local; key bị từ chối (422) và làm fail console-error assertion. Chặn route này trong test. Lưu ý: key trong `.env` local hiện không hợp lệ hoặc không có quyền; đây là việc của người dùng, không tự thay đổi.
- Tài liệu đồng bộ: README, PLAN.md (đầu file và bảng Meta), docs/LOCAL_AUTOMATION.md, docs/PLATFORM_ARCHITECTURE.md.

## Blocker đã biết
- Key AI legacy trong `.env` bị nhà cung cấp từ chối.
- Instagram live cần R2 + Meta OAuth/quyền.
- Album 4–10 và các live acceptance khác cần chỉ thị rõ.

## Runtime
- Server Tinix không chạy tại thời điểm cập nhật (health `127.0.0.1:8765` không phản hồi). Build có gọi STOP.bat và không khởi động lại. Chạy `START.bat` khi cần dùng app.

## Bước tiếp theo đề xuất
1. Người dùng quyết định checkpoint commit theo 4 nhóm trên.
2. Người dùng cung cấp hoặc sửa key AI trong `.env` nếu cần chức năng AI.
3. Cấu hình R2 và OAuth Meta để mở Instagram live, hoặc xác nhận hoãn.
4. Chỉ thị rõ về album 4–10 ảnh trước khi đăng công khai.
