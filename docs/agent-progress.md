# Tiến độ agent — Tinix Social Hub

Cập nhật: 10-11-2026. Bản ghi handoff ngắn theo TINIX V2.1 mục 14; không thay thế Git hay bằng chứng test.

## Current authoritative handoff - 2026-11-10

The older dated notes below are retained as history; use this section for the current state.

### Current verification — 2026-11-10

- Latest pushed baseline before this documentation reconciliation: `bad0a5f`; build remains version 1.0.50. Previously recorded checks: targeted analytics/API/frontend tests 99/99, profile-transfer tests 16/16, `BUILD.bat --no-bump` full suite 100%.
- Read-only runtime health check during this review: API/database OK, worker idle, scheduler running, no queue-stuck/attention items; version 1.0.50. No code changed in this review, so no build/restart was needed.
- Latest recorded bounded scheduler cycle attempted 19 posts and 10 channels with 0 failures. Expected provider states included `needs_connection` and `unsupported`; inaccessible historical posts retain prior snapshots.

- Phase 10B fixture/UI/backup-restore acceptance remains recorded complete; it is not equivalent to a tested end-user clean-install or production deployment.
- Facebook live evidence: Page Tinix formats include text, photo, album 2–10, video and Reel; alternate Page `131419466718163` has photo, six-photo album and video-format evidence. On the alternate Page, the video-format result carried a `/reel/` permalink.
- Instagram Official API live evidence on `@tannguyen3569`: image, carousel counts 2 and 5–10, Reel, and point-in-time Insights. This does not prove other accounts, Apps, or formats.
- Historical analytics for inaccessible objects can remain unavailable due to provider permissions/object state; TikTok/X remain scaffold.
- Isolated staging rehearsal (2026-11-10, Python 3.11.9): started the tagged `v1.0.0-rc.20` app against a synthetic staging DB, retained a fixture account, then started current `1.0.50` against the same DB. Migration completed with integrity OK, preserved the fixture, and created pre-migration backup `tinix-pre-migration-v13-20261110-154510-832026.db`.
- Recovery UI rehearsal on that staging DB: Settings UI export and restore returned HTTP 200. A post-export sentinel account was removed by restore, the pre-restore safety copy retained it, and the pre-export fixture remained. Export excluded `.env`. Staging files were isolated under the OS temp directory and removed afterward; the primary runtime was not modified.
- Verification: Python 3.11 clean venv installed `requirements.txt`; fresh-data startup returned health/database OK and UI HTTP 200. Backup/recovery/profile-transfer tests passed 23/23 on Python 3.11; migration/state-machine tests passed 14/14 on the project venv (Python 3.13).
- Limits: this was a staged source/database upgrade simulation, not a `BUILD.bat`/desktop-shortcut run or a same-directory in-place packaged upgrade. No independent Orca QA/reviewer was available in this session; do not call this Release PASS.

## Milestone hiện tại
Postiz 01–10 hoàn tất ở mức code/fixture. Live evidence hiện được giới hạn như mô tả trong Current authoritative handoff: Facebook trên hai Page đã thử và Instagram trên `@tannguyen3569`; không suy rộng sang các account/App khác. TikTok/X vẫn scaffold.

## Đã hoàn thành
- Remediation FINAL_REVIEW F01–F08 (1.0.44).
- Facebook Page API live: bài chữ, ảnh đơn, album 2/3/4/5/10 ảnh, video Page thường, Reel.
- Instagram Login live: `@tannguyen3569` (Huong Vo). Ảnh đơn, carousel 2 và 5 ảnh, Reel (MP4 qua R2).
- Publisher carousel Instagram (2–10 JPEG) có checkpoint khôi phục; publisher Reel (REELS, chờ xử lý theo khuyến nghị Meta: mỗi phút, tối đa 5 lần).
- Làm mới token Instagram theo lịch: khi khởi động và mỗi 24 giờ, làm mới các token hết hạn trong 7 ngày. Token hiện tại hết hạn 26-12-2026.
- Analytics scheduler: Meta và Instagram đã bật theo chu kỳ 6 giờ; xem mục Current authoritative handoff để biết lượt chạy kế tiếp.
- AI: Gemini key mới trong app; key cũ đã thu hồi và xóa khỏi `.env`.
- Build xác minh 28-10-2026: `BUILD.bat --no-bump` PASS 100%.
- Xác minh lại 28-10-2026: full suite `unittest` PASS **367 tests** trên Python 3.13; 8 test mục tiêu và UI smoke cũng đã chạy riêng.

## Bài thử đã đăng (có thể xóa)
- Album FB 5 ảnh: https://www.facebook.com/122132248658779083/posts/122137990040779083 (người dùng đã xóa; kiểm tra lại).
- Album FB 10 ảnh: https://www.facebook.com/122132248658779083/posts/122137991528779083
- Ảnh đơn FB (mới): https://www.facebook.com/122132248658779083/posts/122138021468779083
- Carousel IG 2 ảnh: https://www.instagram.com/p/DfBnqUhibGq/
- Carousel IG 5 ảnh: https://www.instagram.com/p/DfBozoWiXM0/
- Carousel IG 10 ảnh (10 container con xác nhận): https://www.instagram.com/p/DfCE4Gbid3r/
- Reel IG: https://www.instagram.com/reel/DfBrpiNG402/

## Đang mở / chưa nghiệm thu
- Analytics các bài cũ (album) vẫn có `meta_permission_denied` / `meta_post_unavailable`; snapshot đã lưu được giữ nguyên.
- Đã đối soát release Facebook `b53a5db5-e01d-44a1-b20e-9a595656a98b` (Reel `1433112448754530`) bằng verification note lịch sử từ Graph API v26.0: video thuộc Page `1106784475845782`, `publish_status=published`, caption khớp. Đã ghi `external_release_id` bằng luồng `manual_connect`. Fetch metrics xác minh lại ngày 28-10 trả `meta_post_unavailable` (Graph code 100); không có metric mới và dữ liệu snapshot cũ được giữ. Release không còn đến hạn trong cooldown 24 giờ hiện tại.
- Kết nối Đỗ Minh Duy: các Page đã thuộc Thanh229tan (chặn trùng binding là đúng). Kênh URL-based của Duy không phải Page số.
- Đường thu Chrome (`method=chrome`) đã đọc được metric trên bài ảnh của Page Tinix qua release `bb9278fe-295d-4374-8271-b8f6141f9a1e`: 1 metric likes, 1.900, source `ui_chrome:facebook-web-v1` (30-10-2026). Snapshot API trước đó cho cùng release trả likes=1 và comments=1; giữ nguồn/snapshot tách biệt, không cộng hoặc coi hai giá trị tương đương. Chưa xác minh thu comments/shares bằng Chrome.
- Giới hạn Reel (dung lượng 100 MB, thời lượng) là giả định tự đặt, chưa xác minh từ tài liệu Meta.
- Lỗi đã biết, chưa rõ nguyên nhân: lượt kết nối Instagram đầu bị `ig_exchange_token` trả code 100 "Unsupported request - method type: get"; lượt sau thành công.
- Instagram carousel sizes 6–9 đã được live-verified; carousel sizes 2 and 5–10 are recorded for `@tannguyen3569`. Các account khác chưa được nghiệm thu.
- Multi-Page: fixture/UI và backup-restore acceptance được ghi nhận trong Giai đoạn 10B; live acceptance hiện gồm nhiều format trên đúng hai Page đã thử, không suy rộng sang Page/account khác.
- TikTok, X: scaffold, chưa bật.
- Chưa kiểm tra: lint/typecheck, CI Python 3.11, clean install, power loss, workload lớn.

## Quyết định kỹ thuật
- Test `test_snapshots_use_latest_value...`: ngày tương đối thay cho ngày cố định.
- Test `test_integration_buttons_open_dialog`: chặn `legacy-models` trong test.
- Instagram publisher: carousel và Reel dùng checkpoint, không tạo container lần hai và không publish lần hai khi gián đoạn.
- Làm mới token Instagram chỉ khi còn dưới 7 ngày; lỗi từng kết nối không dừng các kết nối khác.

## Runtime
- Runtime hiện tại: xem mục Current authoritative handoff phía trên; PID và thời điểm scheduler là thông tin biến động, không giữ lại trong ghi chú lịch sử này.

## Bước tiếp theo đề xuất
1. Chạy kiểm tra `BUILD.bat`/launcher và nâng cấp packaged in-place trên staging Windows riêng, xác minh shortcut/UI và dữ liệu; tránh chạy `BUILD.bat` trên app chính trong diễn tập.
2. Bổ sung independent QA/reviewer và CI/lint/typecheck nếu cần để đóng release gate; Python 3.11 startup/dependency và backup/restore tests hiện đã có bằng chứng.
3. Giữ unresolved analytics snapshot cũ, không tạo lại live post chỉ để lặp lại coverage đã có; xác minh giới hạn Reel bằng tài liệu Meta trước khi thay đổi validation.
4. TikTok/X và VPS là phạm vi riêng, cần quyết định sản phẩm trước khi triển khai.


### Instagram Official API live acceptance - 2026-10-29

In this continuation, the connected profile `@tannguyen3569` (`17841425556322045`) passed one-image, two-image carousel, and Reel live verification through Instagram Login Official API. New evidence: one image job `50506fdd-294c-49ed-a337-7275fe6b3a37`, permalink https://www.instagram.com/p/DfD2C-mGG_y/; carousel job `7ff70006-42ca-4bbe-b7fd-c4b530130833`, permalink https://www.instagram.com/p/DfD3FAMCQzP/; Reel job `ba9a41f1-5745-4ff1-aef7-de719c8d6b23`, permalink https://www.instagram.com/reel/DfD3jxTnSTF/. Graph verified corresponding media types and profile identity. Stories remain conditional: verify current Meta support for this Instagram Login flow and account entitlement before adding it.

Instagram Insights was verified live on 2026-10-29 for `@tannguyen3569` (`17841425556322045`). The connected token includes `instagram_business_manage_insights`; a Reel fetch succeeded with reach=1, likes=2, comments=2, saved=0, shares=0, and total_interactions=4. Account Insights also succeeded with a reach snapshot of 0. These are point-in-time snapshots, not historical trends.

Next: let the opted-in scheduler collect the remaining available releases; the one-shot check is scheduled after the next cycle. No App Review request was made.

### Facebook multi-photo live acceptance — 2026-11-09

- Reused approved content `fe8d780d-4f96-4c4a-a587-30a04b3e3dd2` with `FBALBUM10-1.png` through `FBALBUM10-10.png`.
- Target: Page Tinix, external Page ID `1106784475845782`; account `Thanh229tan`; routing `official_api_only`.
- Preflight and dry-run passed. Live job `a0f7fed8-50d9-4daf-bad3-ab731d2e5798` finished `succeeded` with no retry or error; commit point was reached once.
- Meta returned ten photo IDs and post ID `1106784475845782_122140968434779083`. Tinix marked release `515e7563-3477-4672-b4c8-9eeb726cb476` `verified` with permalink https://www.facebook.com/122132248658779083/posts/122140968434779083.
- This extends live evidence to a ten-photo album on the selected Page/App only; it does not generalize acceptance to other Pages or Apps.

### Instagram carousel 6-photo live acceptance — 2026-11-10

- Created approved test content `9c3fbc64-5a1f-4cab-b638-4f5e0bd78e5a` with exactly six JPEG assets (`IGCAROUSEL10-1.jpg` through `IGCAROUSEL10-6.jpg`).
- Target: connected profile `@tannguyen3569` (`17841425556322045`), account `Huong Vo`; routing `official_api_only`.
- Preflight passed and dry-run job `d716e74f-2a21-4a62-98fa-69ccfc85c751` reached `dry_run_ready`.
- Live job `a0344aac-8874-4df4-b520-23b1491de67a` succeeded in one attempt, reached its commit point once, and had no error. Tinix release `50414e43-8743-474a-8aa8-045cdaf71be0` is `succeeded` and `verified`.
- Instagram returned carousel media ID `18026268416929404`, six child media IDs, and [permalink](https://www.instagram.com/p/Dfi1vlJkhtm/). This extends live evidence to six-photo carousel publishing on the selected account/App only; it does not generalize acceptance to other accounts or formats.

### Instagram carousel 7-photo boundary acceptance — 2026-11-10

- Created approved test content `bc592c19-61db-4d65-b8b5-31f33d4edad0` with exactly seven JPEG assets (`IGCAROUSEL10-1.jpg` through `IGCAROUSEL10-7.jpg`).
- Preflight passed and dry-run job `200ce7aa-c7a3-4ab6-b8f7-5b881aeab5cb` reached `dry_run_ready` for `@tannguyen3569` (`17841425556322045`).
- Live job `f46f1f47-7056-427e-acf6-2c64e0e885b4` succeeded in one attempt, reached its commit point once, and had no error. Tinix release `765339e8-4180-4278-8fb7-d18e48750199` is `succeeded` and `verified`.
- Instagram returned carousel media ID `18099346670442388`, seven child media IDs, and [permalink](https://www.instagram.com/p/Dfi38EkGtFC/). This extends live evidence through seven-photo carousel publishing on the selected account/App only.

### Instagram carousel 8-photo boundary acceptance — 2026-11-10

- Created approved test content `3354fc4b-a33d-4907-ad7b-bbfb9f0077de` with exactly eight JPEG assets (`IGCAROUSEL10-1.jpg` through `IGCAROUSEL10-8.jpg`).
- Preflight passed and dry-run job `b8898578-5937-4efd-bcf6-955e44494f3e` reached `dry_run_ready` for `@tannguyen3569` (`17841425556322045`).
- Live job `9f475fa2-a231-4f81-94fd-08b5842c3067` succeeded in one attempt, reached its commit point once, and had no error. Tinix release `6206bbd6-0c31-4f17-bda2-59243ccf28bd` is `succeeded` and `verified`.
- Instagram returned carousel media ID `18124142816291056`, eight child media IDs, and [permalink](https://www.instagram.com/p/Dfi4sTxmqSl/). This extends live evidence through eight-photo carousel publishing on the selected account/App only.

### Instagram carousel 9-photo boundary acceptance — 2026-11-10

- Created approved test content `cc45f7dd-8ce7-4899-ae09-47389aecf8c3` with exactly nine JPEG assets (`IGCAROUSEL10-1.jpg` through `IGCAROUSEL10-9.jpg`).
- Preflight passed and dry-run job `893a1b13-397b-4ac5-ae5d-f084aa1b93c2` reached `dry_run_ready` for `@tannguyen3569` (`17841425556322045`).
- Live job `bcb60243-2f0e-4705-9ff2-aacacf3a9d86` succeeded in one attempt, reached its commit point once, and had no error. Tinix release `d3ad7369-41a7-4edd-8842-96c6c383d425` is `succeeded` and `verified`.
- Instagram returned carousel media ID `18085640192345751`, nine child media IDs, and [permalink](https://www.instagram.com/p/Dfi5dlsGmZE/). This completes the 6–9 photo carousel evidence range on the selected account/App only.

### Facebook six-photo album live acceptance — 2026-11-10

- Created approved test content `9b8e5339-0919-4e84-be94-765d0df64ba6` with exactly six PNG assets (`FBALBUM10-1.png` through `FBALBUM10-6.png`).
- Target: Page Tinix, external Page ID `1106784475845782`; routing `official_api_only`.
- Preflight passed and dry-run job `f009add5-a6d0-4798-9fe4-5426b4739ec3` reached `dry_run_ready`.
- Live job `317ddee7-8d3b-4caa-badb-cb22c38d90c3` succeeded in one attempt, reached its commit point once, and had no error. Tinix release `601a7b11-02ad-4a8b-a7dc-2dd373d9df2b` is `succeeded` and `verified`.
- Meta returned six photo IDs and post ID `1106784475845782_122141029778779083`; [album permalink](https://www.facebook.com/122132248658779083/posts/122141029778779083). This confirms six-photo album publishing on the selected Page/App only.

### Facebook seven-photo album live acceptance — 2026-11-10

- Created approved test content `a0771a42-9d0c-4634-acd8-2b3e573bd3e0` with exactly seven PNG assets (`FBALBUM10-1.png` through `FBALBUM10-7.png`).
- Target: Page Tinix, external Page ID `1106784475845782`; routing `official_api_only`.
- Preflight passed and dry-run job `d199558a-1866-49c0-a2f1-31fecae3649c` reached `dry_run_ready`.
- Live job `d0b2a911-6d0b-40a7-b36e-4e8d8d31032d` succeeded in one attempt, reached its commit point once, and had no error. Tinix release `1af4ea2a-fa18-4ca7-bbc5-a5bed7255809` is `succeeded` and `verified`.
- Meta returned seven photo IDs and post ID `1106784475845782_122141041706779083`; [album permalink](https://www.facebook.com/122132248658779083/posts/122141041706779083). This extends live album evidence through seven photos on the selected Page/App only.

### Facebook eight-photo album live acceptance — 2026-11-10

- Created approved test content `bc3e2e59-c33a-4e2d-975e-1acf8ec0961e` with exactly eight PNG assets (`FBALBUM10-1.png` through `FBALBUM10-8.png`).
- Target: Page Tinix, external Page ID `1106784475845782`; routing `official_api_only`.
- Preflight passed and dry-run job `c988ebcc-06a7-4385-9178-424534c10aff` reached `dry_run_ready`.
- Live job `e90281ef-85a1-46f9-9a16-446511f9f971` succeeded in one attempt, reached its commit point once, and had no error. Tinix release `ef84129b-bfc1-4eae-9a58-fbf0a9314123` is `succeeded` and `verified`.
- Meta returned eight photo IDs and post ID `1106784475845782_122141057324779083`; [album permalink](https://www.facebook.com/122132248658779083/posts/122141057324779083). This extends live album evidence through eight photos on the selected Page/App only.

### Facebook nine-photo album live acceptance — 2026-11-10

- Created approved test content `adb1f977-8292-4342-bb80-6fec232bd24c` with exactly nine PNG assets (`FBALBUM10-1.png` through `FBALBUM10-9.png`).
- Target: Page Tinix, external Page ID `1106784475845782`; routing `official_api_only`.
- Preflight passed and dry-run job `ba8363bf-f343-4277-b604-13fc1abe65fe` reached `dry_run_ready`.
- Live job `8e9d58c3-9e95-45f3-b73c-cbc9fcdb1442` succeeded in one attempt, reached its commit point once, and had no error. Tinix release `48331883-943b-4a75-919a-b0f17874b32f` is `succeeded` and `verified`.
- Meta returned nine photo IDs and post ID `1106784475845782_122141059178779083`; [album permalink](https://www.facebook.com/122132248658779083/posts/122141059178779083). This completes the 6–9 photo album evidence range on the selected Page/App only.

### Facebook alternate Page six-photo album live acceptance — 2026-11-10

- Created approved test content `7807360c-0bd0-48e8-b77e-094bb4f5d979` with six PNG assets (`FBALBUM10-1.png` through `FBALBUM10-6.png`).
- Target: alternate Page `Tí Nị - Chụp Ảnh Cho Bé Yêu`, external Page ID `131419466718163`; routing `official_api_only`.
- Preflight passed and dry-run job `487972c3-92ef-469d-9117-90db6987e86f` reached `dry_run_ready`.
- Live job `08a7d422-322c-48e6-a841-3dd30b1377b6` succeeded in one attempt, reached its commit point once, and had no error. Tinix release `dd436571-c66a-47f2-84a8-18a8ee0a0002` is `succeeded` and `verified`.
- Meta returned six photo IDs and post ID `131419466718163_122342317424030346`; [album permalink](https://www.facebook.com/122339557136030346/posts/122342317424030346). This confirms the album path on a second Page, but does not generalize to all Pages or Apps.

### Facebook alternate Page single-photo live acceptance — 2026-11-10

- Created approved test content `37a83b42-b67b-49cf-bd9b-5de9d3ad6487` with one PNG asset (`FBALBUM10-1.png`).
- Target: alternate Page `Tí Nị - Chụp Ảnh Cho Bé Yêu`, external Page ID `131419466718163`; routing `official_api_only`, format `photo`.
- Preflight passed and dry-run job `12d9c7ae-c171-4519-8f2c-5504eaea6a1b` reached `dry_run_ready`.
- Live job `2c3c4ad3-2e94-4368-9741-2f766d8635b4` succeeded in one attempt, reached its commit point once, and had no error. Tinix release `264a97ec-3520-407b-9b8f-5e2b2d75a0d1` is `succeeded` and `verified`.
- Meta returned photo ID `122342318096030346`, post ID `131419466718163_122342318114030346`, and [permalink](https://www.facebook.com/122339557136030346/posts/122342318114030346). This confirms the single-photo path on the second Page only.

### Facebook alternate Page video live acceptance — 2026-11-10

- Reused approved content `b48d4c3a-4f64-4f80-a764-f652f7f9adfc` with one MP4 asset (`tinix-test-video.mp4`), format `video`.
- Target: alternate Page `Tí Nị - Chụp Ảnh Cho Bé Yêu`, external Page ID `131419466718163`; routing `official_api_only`.
- Preflight passed and dry-run job `ec302d9e-a50e-4045-91e3-1b6154e12c6a` reached `dry_run_ready`.
- Live job `a09ea4e8-e75b-483c-8575-e2407cd3c196` succeeded in one attempt, reached its commit point once, and had no error. Tinix release `61c2caa7-0e93-463e-8426-8055f8bf804a` is `succeeded` and `verified`.
- Meta returned video ID `2016503212374207` and [permalink](https://www.facebook.com/reel/2016503212374207/). Tinix submitted this as Page `video`; Meta's permalink uses the `/reel/` URL form. This confirms the video publish path on the second Page only.
