# Tiến độ agent — Tinix Social Hub

Cập nhật: 09-11-2026. Bản ghi handoff ngắn theo TINIX V2.1 mục 14; không thay thế Git hay bằng chứng test.

## Current authoritative handoff - 2026-10-29

The older dated notes below are retained as history; use this section for the current state.

### Current verification — 2026-11-09

- Local `master` contains checkpoint `22e6d83` plus handoff documentation commits; the worktree was clean before the current documentation update.
- Targeted analytics/API/frontend tests passed 99/99; profile-transfer tests passed 16/16; `BUILD.bat --no-bump` passed with the full suite at 100% on version 1.0.50.
- Runtime restart through `START.bat` was verified on port 8765: health/database OK, worker idle, scheduler running, frontend HTTP 200, and no warnings.
- The latest bounded scheduler cycle attempted 19 posts and 10 channels with 0 failures. Expected provider states included `needs_connection` and `unsupported`; historical inaccessible posts retain their prior snapshots.

- Phase 10B fixture/UI/backup-restore acceptance is recorded complete in `docs/plan_postiz_10_acceptance_operations.md`. Live multi-Page text was verified for two Pages only; that does not extend acceptance to other formats or accounts.
- Instagram Official API image, carousel, Reel, and Insights have live evidence for `@tannguyen3569`; Insights are point-in-time snapshots, not historical trends.
- Read-only runtime check after the 2026-10-29 16:39 UTC restart: version 1.0.44, health/database OK, worker idle, scheduler running. Startup run attempted 0 posts and 0 channels with no failures; next scheduled run is 22:39 UTC.
- A one-time read-only follow-up is scheduled for 22:55 UTC to inspect the Reel metrics and health after that run. No collection was triggered and no App Review request was sent.

## Milestone hiện tại
Postiz 01–10 hoàn tất ở mức code/fixture. Live đã có cho Facebook Page (text, ảnh đơn, album 2–5 và 10 ảnh, video, Reel) và Instagram (ảnh đơn, carousel 2 và 5 ảnh, Reel). Git remote `origin` đã cấu hình và `master` đã push.

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
- Carousel IG 6–9 ảnh: chưa thử riêng (carousel 10 ảnh đã thành công).
- Multi-Page: fixture/UI và backup-restore acceptance được ghi nhận trong Giai đoạn 10B; live text post đã xác minh trên hai Page. Chưa suy rộng nghiệm thu sang định dạng hoặc account khác.
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
1. Kiểm tra heartbeat sau chu kỳ Meta kế tiếp (17:39 UTC ngày 29-10); đối chiếu `last_run`, tình trạng fetch Reel và health. Không kích hoạt collection thủ công.
2. Xác minh các bài cũ còn `meta_permission_denied`/`meta_post_unavailable`, hoặc chấp nhận giữ snapshot cũ không có metric mới.
3. Giai đoạn 10B fixture/UI/backup-restore đã được ghi nhận; giữ giới hạn live acceptance ở hai Page đăng bài chữ cho đến khi có nhu cầu nghiệm thu thêm định dạng/account.
4. Ghi lịch nhắc kiểm tra/làm mới token Instagram trước 26-12-2026 (tự động refresh đã có; cần xác minh kết nối vẫn `connected`).
5. Tùy theo nhu cầu: carousel IG 6–9 ảnh, album FB 6–9 ảnh, kiểm tra giới hạn Reel theo tài liệu Meta và đường analytics Chrome. TikTok/X vẫn là scaffold.


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
