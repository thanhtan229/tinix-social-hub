# Giai đoạn 10 — Nghiệm thu vận hành và hoàn thiện tài liệu

Status: 10B fixture/UI/backup-restore accepted; live multi-Page Facebook text and Instagram one-image, two-image carousel, and Reel accepted within stated account and format limits. Updated 2026-10-29.
Thuộc [kế hoạch tổng](plan_postiz.md), bổ sung bước đóng từng đợt phát hành.

## Mục tiêu và điều kiện

Xác nhận những capability đã chọn để giao hoạt động xuyên suốt từ draft đến lịch, kết quả và analytics, có khả năng phục hồi và hướng dẫn vận hành đúng thực tế.

Giai đoạn này áp dụng sau mỗi đợt lớn và khi đóng toàn bộ phạm vi đã chọn. Không chờ các nhánh tùy chọn 06–09 hoàn tất mới nghiệm thu/giao nhiều Facebook Page. Không dùng giai đoạn cuối để dồn kiểm thử bắt buộc của các giai đoạn trước.

## Các bước thực hiện

### 10A. Ma trận khả năng và bằng chứng

1. Liệt kê capability được giao theo platform/format/transport và loại account; tách có code, qua fixture, qua dry-run và qua live publish.
2. Ghi ngày, phiên bản adapter, phạm vi account và giới hạn đã biết. Không lưu token hoặc dữ liệu nhạy cảm vào tài liệu.
3. Capability chưa có bằng chứng giữ trạng thái trung thực; lỗi provider riêng không ngăn giao phần độc lập đã đạt.

### 10B. Kiểm tra toàn luồng và phục hồi

1. Chạy kịch bản draft → chọn nhiều Page → override → lưu/duyệt → preflight → schedule → kết quả riêng → đối soát/analytics trong môi trường test.
2. Kiểm tra restart ở queued, upload, pending và sau commit bằng fixture; khôi phục không tự đăng trùng.
3. Thử backup/restore trên bản sao dữ liệu và media, không ghi đè môi trường đang dùng. Kiểm tra migration, asset references và cấu hình preset/chữ ký mới.
4. Nếu migration có vấn đề, chốt cách phục hồi bản sao phù hợp. Không chạy phiên bản app cũ trên DB mới khi chưa chứng minh tương thích; không khôi phục lịch cũ rồi vô tình chạy lại bài đã đăng ngoài nền tảng.
5. Kiểm tra tải UI trên dữ liệu đại diện cho cách dùng thật; đo trước rồi chỉ xử lý nút thắt liên quan, không tối ưu suy đoán hoặc refactor ngoài phạm vi.

### 10C. Nghiệm thu live có giới hạn

1. Chọn account/target/format cần chứng minh cho đợt giao; kiểm tra readiness và điều kiện quyền.
2. Dry-run không tạo bài; live publish chỉ thực hiện khi người dùng có chỉ thị rõ về nội dung và đích.
3. Đối chiếu post ID/URL, đúng Page/account và metrics nếu được cấp. Một trường hợp đạt không đại diện tất cả account/format.
4. Ghi bài thử đã tạo và trạng thái xử lý; không tự xóa hoặc đăng lại bài thật ngoài phạm vi được phép.

### 10D. Tài liệu và bàn giao

1. Cập nhật hướng dẫn theo tác vụ: chọn Page, nội dung chung/riêng, lỗi preflight, đổi lịch, unknown, kết nối lại và số liệu cũ.
2. Cập nhật các nhận định đã cũ trong `RESEARCH_postiz.md` và tài liệu hiện trạng sau khi có bằng chứng; giữ nguyên ý nghĩa nhật ký nghiệm thu lịch sử.
3. Ghi trạng thái hoàn tất/chưa làm/blocker vào đúng file giai đoạn, cùng test/build/restart của đợt đó. Không tạo thêm báo cáo rời chỉ để lặp nội dung.
4. Tách backlog còn lại thành việc có nhu cầu rõ; SaaS/team/Temporal/provider mới không tự trở thành giai đoạn tiếp theo.

## Tiêu chí đóng đợt

- Mọi acceptance bắt buộc của phạm vi đã chọn đạt; hạn chế live và capability chưa nghiệm thu được ghi rõ.
- Không có lỗi gây đăng sai Page, bỏ qua duyệt, duplicate sau unknown hoặc mất dữ liệu trong luồng mới.
- Suite phù hợp và full regression theo mức rủi ro đạt; `BUILD.bat` thành công.
- Backend đúng dự án đã được thay sau thay đổi cuối, health/version/frontend asset được xác minh. Task bị gián đoạn khi restart được báo nếu có.
- Hướng dẫn phản ánh chức năng thực tế; người dùng tìm được cách xử lý lỗi mà không cần đọc log kỹ thuật cho thao tác thường ngày.
- Báo cáo ngắn: chức năng, file, kiểm thử, build, restart, giới hạn và tình trạng Git commit. Không tự commit.

## Vùng tác động

Ưu tiên kiểm thử và tài liệu. Chỉ sửa lỗi trực tiếp của phạm vi đang nghiệm thu; phát hiện ngoài phạm vi được ghi lại, không tiện tay sửa. Các thay đổi code phát sinh vẫn tuân thủ build/restart sau thay đổi cuối theo kế hoạch tổng.

## Ma trận capability trong đợt này

| Capability | Mức bằng chứng hiện có | Giới hạn |
|---|---|---|
| Nhiều Facebook Page, plan/release/job riêng và idempotency | Unit/API/fixture; full build hiện tại đạt 300 tests | Chưa thực hiện live publish mới trong đợt nghiệm thu này |
| Composer đa nền tảng, target overrides, nhóm/signature/media | Unit/API/Playwright fixture | Không suy rộng fixture thành live cho mọi adapter/format |
| Detail, audit, retry/cancel và đối soát manual | API/fixture và test identity | Người dùng xác nhận thủ công; không tự động xác thực phía mạng xã hội |
| Calendar theo ngày/tuần/tháng/list, slot gợi ý, reschedule nhóm | API/unit/Playwright, có kiểm tra DST và rollback | Gợi ý slot không giữ chỗ; kéo-thả/undo hoãn |
| Analytics YouTube và Meta, cập nhật nền opt-in | Mock/API/unit; scheduler chia provider, giới hạn và chống fetch trùng | Reel và Page Tinix đã fetch thủ công qua API thật; scheduler tự động chưa nghiệm thu live |
| Facebook ảnh API, một ảnh | Fixture, dry-run và đăng live trên Page Tinix; xác minh photo/post ID, owner và permalink | N/A |
| Facebook ảnh API, nhiều ảnh | Fixture, dry-run và album hai/ba ảnh đăng live trên Page Tinix; Graph xác nhận đúng Page, đúng ảnh và thứ tự | Chưa thử 4–10 ảnh hoặc Page/App khác |
| Facebook Reel API | Preflight/dry-run và Reel thật trên Page Tinix; Graph xác nhận đúng Page, trạng thái published và permalink | Chưa thử Page/App khác; lần upload đầu HTTP 400 đã đối soát không publish |
| Facebook Page video thường | Đăng live MP4 trên Page Tinix; Graph xác nhận đúng Page và `published`, đã đối soát job | Lần live này cần finalize thủ công; bản sửa tự xác minh còn chờ lần live riêng; chỉ MP4 một file |
| Instagram Login identity | Đã triển khai kết nối độc lập và fixture tests | Chưa live OAuth/App review |
| Instagram publishing | Chưa triển khai publisher | Tinix chưa có HTTPS media storage/CDN để Meta tải file |

Backup/migration được kiểm tra bằng test trên database cô lập/bản sao. Không khôi phục dữ liệu test vào database người dùng. Trong lượt cập nhật này, `BUILD.bat --no-bump` đạt **100%**, full suite có **300 tests**; focused Meta/catalog/routing có **81 tests**. Backend cũ đã được thay bằng PID **43588** từ workspace; `/api/health` trả `ok`, version **1.0.43**, database `ok`, worker idle, scheduler chạy, không warnings. `/api/platforms` công khai các Facebook format mới và composer JS trả HTTP 200. Không đăng Facebook thật.

### Kiểm tra mục tiêu tiếp theo — 28-10-2026

Tám kiểm thử mục tiêu chạy lại qua `unittest` đều PASS: batch scheduling API/idempotency, atomic multi-account schedule, per-target format/settings, bulk reschedule, frozen plan/release/job, plan state aggregation, recovery sau commit và scheduler bounded refresh. UI smoke PASS; full suite `unittest` PASS **367 tests** trên Python 3.13. Không chạy build vì chỉ cập nhật tài liệu, không chạy live publish. Runtime được xác minh riêng là version **1.0.44**, health/database `ok`, worker idle; Giai đoạn 10B vẫn cần acceptance toàn luồng trên môi trường test và kiểm tra backup/restore/restart theo phạm vi đã chọn.

### Bổ sung nghiệm thu fixture 10B — 28-10-2026

Hai mươi sáu kiểm thử `unittest` mục tiêu PASS trên Python 3.13: lập lịch nhiều Page nguyên tử/idempotent, format/settings theo target, snapshot release/job, tổng hợp trạng thái plan, reschedule nhóm, phục hồi queue, checkpoint upload/restart không đăng trùng, backup/restore database, recovery bundle mã hóa gồm media/profile/environment và khôi phục tham chiếu media. Hai Playwright smoke PASS cho tải các tab không lỗi console và xem/reschedule release trên lịch. Các fixture dùng dữ liệu cô lập; không chạy live publish. Phiên UI acceptance toàn luồng được ghi ở mục tiếp theo; migration trên bản sao dữ liệu thực được nghiệm thu ở mục sau.


### Preserved Facebook live acceptance history - September 2026

The previously recorded Facebook one-photo post and Page video on Page Tinix remain part of the acceptance history. The photo permalink was https://www.facebook.com/122132248658779083/posts/122132248592779083; the video permalink was https://www.facebook.com/reel/1433112448754530/. The video was verified by Graph as published and finalized manually in Tinix after an `unknown_result`; preflight MIME and video-ID checkpoint issues were corrected with regression tests. No second live video run was made after that correction.

Facebook album support was implemented for 2 to 10 unpublished photos attached to one feed post, including ordering, cancellation/recovery, and safe handling of timeout. The 128 targeted tests and `BUILD.bat --no-bump` passed at implementation. Later, an album of two photos was live-verified on Page Tinix: job `47372f00-d520-4d75-8821-963b5e3f32c1` succeeded, and Graph confirmed the Page owner and both photo attachments in order. The 90 Meta/state-machine tests and build passed after the state-transition fix.

A Facebook Reel was live-verified on Page Tinix on 2026-09-29 at https://www.facebook.com/reel/1329975209041799/. Job `c944e4e0-b3d0-4d68-ac11-d6c37f9cd20b` succeeded; Graph confirmed the Page, completed processing, `published` status, caption, and permalink. An initial upload attempt ended in HTTP 400 before finish and was reconciled as failure; no duplicate was published. Verification, content length handling, and diagnostics were reviewed; 94 targeted tests and build passed.

Meta analytics were also verified for the Reel and Page. Reel metrics used `views` after Graph rejected `shares`; reported likes/comments/views and Page followers/page_likes were all zero. Analytics scheduler was not enabled. A three-photo Facebook album was also verified on Page Tinix at https://www.facebook.com/122132248658779083/posts/122132332970779083 (job `49060e3f-ab23-4e22-bb24-38eadc474c7f`). Four-to-ten-photo albums remain unverified live.

### Facebook live multi-Page text acceptance - 2026-10-29

A user-approved plan published a text post through `official_api_only` to two Tini Pages after preflight and dry-run. Both jobs succeeded and Graph verified their post IDs and Page owners. The baby photography Page post was https://www.facebook.com/122339557136030346/posts/122339557100030346 (job `12406a1d-4744-4fd0-878a-b3077f8ddd10`, Page `131419466718163`). The family photography Page post was https://www.facebook.com/1140719948353725/posts/1140719911687062 (job `cc338d60-5078-4f99-a244-a0d93fea491c`, Page `106946975052940`). Plan `c9edbd8d-ff0f-44cc-87b7-68e6d94541ed`; approval `0c7dfbff-79ac-425a-92ec-7d821abbccca`. This acceptance applies only to text on these Pages/account.

### Instagram live acceptance and Facebook test-post removal status - 2026-10-29

Instagram R2 bucket access (`HeadBucket`) and OAuth identity/scope were verified for `@tannguyen3569` (`17841425556322045`). Preflight was ready; dry-run completed as `dry_run_ready`. The live one-image Official API job `50506fdd-294c-49ed-a337-7275fe6b3a37` succeeded; Graph confirmed media ID `18040813607844996`, type `IMAGE`, and [permalink](https://www.instagram.com/p/DfD2C-mGG_y/). Scope is limited to this account and one JPEG. No source code, build, or restart changed in this operational acceptance.

For the two previously published Facebook test posts, subsequent Graph GET/DELETE calls returned an ambiguous object-not-found/permission response. Their final deletion state could not be independently distinguished by Graph; do not repost them.

### Instagram two-image carousel acceptance - 2026-10-29

On `@tannguyen3569`, preflight was ready and dry-run completed `dry_run_ready`. The live job `7ff70006-42ca-4bbe-b7fd-c4b530130833` succeeded; Graph verified media `18101582774437499` as `CAROUSEL_ALBUM`, with two IMAGE children in order, on Instagram account `17841425556322045`. [Carousel permalink](https://www.instagram.com/p/DfD3FAMCQzP/). No source code changed; build/restart were not applicable.

### Instagram Reel acceptance - 2026-10-29

On `@tannguyen3569`, preflight passed and dry-run completed `dry_run_ready`. The live job `ba9a41f1-5745-4ff1-aef7-de719c8d6b23` succeeded in one attempt. Graph verified media `17938602174125398` as `VIDEO` on account `17841425556322045`. [Reel permalink](https://www.instagram.com/reel/DfD3jxTnSTF/). This confirms the Reel path on the selected account only. No source code changed; build/restart were not applicable.

### Facebook ten-photo album acceptance — 2026-11-09

The approved content `fe8d780d-4f96-4c4a-a587-30a04b3e3dd2` used ten existing PNG assets (`FBALBUM10-1.png` through `FBALBUM10-10.png`) and was routed with `official_api_only` to Page Tinix (`1106784475845782`). Preflight and dry-run passed. Live job `a0f7fed8-50d9-4daf-bad3-ab731d2e5798` succeeded in one attempt with no error; Meta returned ten photo IDs and post ID `1106784475845782_122140968434779083`. Tinix marked release `515e7563-3477-4672-b4c8-9eeb726cb476` verified. [Ten-photo album permalink](https://www.facebook.com/122132248658779083/posts/122140968434779083). This confirms ten-photo album publishing for the selected Page/App only; it does not generalize to other Pages or Apps.

### Instagram carousel 6-photo acceptance — 2026-11-10

The approved test content `9c3fbc64-5a1f-4cab-b638-4f5e0bd78e5a` used exactly six JPEG assets (`IGCAROUSEL10-1.jpg` through `IGCAROUSEL10-6.jpg`) and was routed with `official_api_only` to `@tannguyen3569` (`17841425556322045`). Preflight passed; dry-run job `d716e74f-2a21-4a62-98fa-69ccfc85c751` reached `dry_run_ready`. Live job `a0344aac-8874-4df4-b520-23b1491de67a` succeeded in one attempt with no error and one commit point. Tinix release `50414e43-8743-474a-8aa8-045cdaf71be0` is verified. Instagram returned carousel media ID `18026268416929404` with six child media IDs and [permalink](https://www.instagram.com/p/Dfi1vlJkhtm/). This confirms six-photo carousel publishing for the selected account/App only.

### Instagram carousel 7-photo boundary acceptance — 2026-11-10

The approved test content `bc592c19-61db-4d65-b8b5-31f33d4edad0` used exactly seven JPEG assets (`IGCAROUSEL10-1.jpg` through `IGCAROUSEL10-7.jpg`) and was routed with `official_api_only` to `@tannguyen3569` (`17841425556322045`). Preflight passed; dry-run job `200ce7aa-c7a3-4ab6-b8f7-5b881aeab5cb` reached `dry_run_ready`. Live job `f46f1f47-7056-427e-acf6-2c64e0e885b4` succeeded in one attempt with no error and one commit point. Tinix release `765339e8-4180-4278-8fb7-d18e48750199` is verified. Instagram returned carousel media ID `18099346670442388` with seven child media IDs and [permalink](https://www.instagram.com/p/Dfi38EkGtFC/). This confirms seven-photo carousel publishing for the selected account/App only.

### Instagram carousel 8-photo boundary acceptance — 2026-11-10

The approved test content `3354fc4b-a33d-4907-ad7b-bbfb9f0077de` used exactly eight JPEG assets (`IGCAROUSEL10-1.jpg` through `IGCAROUSEL10-8.jpg`) and was routed with `official_api_only` to `@tannguyen3569` (`17841425556322045`). Preflight passed; dry-run job `b8898578-5937-4efd-bcf6-955e44494f3e` reached `dry_run_ready`. Live job `9f475fa2-a231-4f81-94fd-08b5842c3067` succeeded in one attempt with no error and one commit point. Tinix release `6206bbd6-0c31-4f17-bda2-59243ccf28bd` is verified. Instagram returned carousel media ID `18124142816291056` with eight child media IDs and [permalink](https://www.instagram.com/p/Dfi4sTxmqSl/). This confirms eight-photo carousel publishing for the selected account/App only.

### Instagram carousel 9-photo boundary acceptance — 2026-11-10

The approved test content `cc45f7dd-8ce7-4899-ae09-47389aecf8c3` used exactly nine JPEG assets (`IGCAROUSEL10-1.jpg` through `IGCAROUSEL10-9.jpg`) and was routed with `official_api_only` to `@tannguyen3569` (`17841425556322045`). Preflight passed; dry-run job `893a1b13-397b-4ac5-ae5d-f084aa1b93c2` reached `dry_run_ready`. Live job `bcb60243-2f0e-4705-9ff2-aacacf3a9d86` succeeded in one attempt with no error and one commit point. Tinix release `d3ad7369-41a7-4edd-8842-96c6c383d425` is verified. Instagram returned carousel media ID `18085640192345751` with nine child media IDs and [permalink](https://www.instagram.com/p/Dfi5dlsGmZE/). This confirms nine-photo carousel publishing and completes the 6–9 evidence range for the selected account/App only.

### Facebook six-photo album acceptance — 2026-11-10

The approved test content `9b8e5339-0919-4e84-be94-765d0df64ba6` used exactly six PNG assets (`FBALBUM10-1.png` through `FBALBUM10-6.png`) and was routed with `official_api_only` to Page Tinix (`1106784475845782`). Preflight passed; dry-run job `f009add5-a6d0-4798-9fe4-5426b4739ec3` reached `dry_run_ready`. Live job `317ddee7-8d3b-4caa-badb-cb22c38d90c3` succeeded in one attempt with no error and one commit point. Tinix release `601a7b11-02ad-4a8b-a7dc-2dd373d9df2b` is verified. Meta returned six photo IDs and post ID `1106784475845782_122141029778779083`; [album permalink](https://www.facebook.com/122132248658779083/posts/122141029778779083). This confirms six-photo album publishing for the selected Page/App only.
