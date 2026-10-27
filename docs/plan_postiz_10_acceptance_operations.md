# Giai đoạn 10 — Nghiệm thu vận hành và hoàn thiện tài liệu

Trạng thái: **Facebook một ảnh, album hai/ba ảnh, video Page thường và Reel đã live-verified trên Page Tinix. Instagram publishing và album 4–10 ảnh còn nghiệm thu.** Ngày cập nhật: 29-09-2026.  
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

Phạm vi fixture/code đã rà gồm 01–05, 06A (một ảnh), 07 (Reel và video Page thường), 09 và kết nối identity 08. 06B album ảnh đã được thêm sau mốc build này; lúc đó Instagram publishing còn mở. Live acceptance Facebook vẫn cần Page/App có quyền phù hợp và chỉ thị bài thử cụ thể. Instagram publishing vẫn cần URL media HTTPS công khai và lựa chọn storage.

### Bổ sung nghiệm thu live — 28-09-2026

Theo chỉ thị của người dùng, đã đăng thử ảnh và video Page thường trên Page Tinix (`1106784475845782`). [Bài ảnh](https://www.facebook.com/122132248658779083/posts/122132248592779083) được Tinix xác minh tự động; [video](https://www.facebook.com/reel/1433112448754530/) được Graph xác nhận `publish_status=published` và đã finalize thủ công trong Tinix sau khi xử lý `unknown_result`. Video đi qua Page Videos API, dù Meta trả permalink `/reel/`. Lỗi live phát hiện ở preflight MIME và việc không giữ video ID từ bước start đã được sửa cùng regression tests. Tự xác minh video sau bản sửa mới đạt fixture; chưa tạo bài live thứ hai để chứng minh.

### Bổ sung triển khai album ảnh Facebook — 28-09-2026

Đã triển khai 06B và fixture-test upload ảnh unpublished theo thứ tự, gắn chúng vào một feed post, hủy/khôi phục và chống retry mù khi timeout. 128 targeted tests và `BUILD.bat --no-bump` đạt; backend PID 52504, version 1.0.43, health/database `ok`, worker idle. Tại mốc triển khai này, capability chưa live-verified và chưa có bài thử album công khai.

### Nghiệm thu album ảnh — 28-09-2026

Theo chỉ thị của người dùng, đã đăng [một album hai ảnh](https://www.facebook.com/122132248658779083/posts/122132264210779083) trên Page Tinix. Preflight/dry-run đạt, job `47372f00-d520-4d75-8821-963b5e3f32c1` kết thúc `succeeded`. Graph xác nhận post thuộc Page `1106784475845782`, attachment type `album` có đúng hai ảnh `122132263586779083` và `122132264180779083` theo thứ tự. Lỗi chuyển `uploading` lặp ở ảnh thứ hai được phát hiện qua live run và đã sửa, kèm regression test trạng thái.

Sau bản sửa, 90 tests Meta/state machine đạt và `BUILD.bat --no-bump` đạt 100%. Backend mới PID 53912 trả `/api/health` `ok` (v1.0.43), database `ok`, worker idle, không warning.

### Nghiệm thu Reel — 29-09-2026

Theo chỉ thị của người dùng, đã đăng [Reel thử](https://www.facebook.com/reel/1329975209041799/) trên Page Tinix qua `video_reels`. Job `c944e4e0-b3d0-4d68-ac11-d6c37f9cd20b` kết thúc `succeeded` một attempt; Graph xác nhận đúng Page, upload/processing complete, publish_status `published`, caption và permalink. Session thử đầu RUpload HTTP 400, không gửi finish; job đã đối soát `permanent_failure`. Review bổ sung kiểm tra owner/published/permalink, `Content-Length` upload và giữ diagnostic trong job `unknown_result`. 94 targeted tests và `BUILD.bat --no-bump` đạt 100%; backend PID 40096 health/database `ok`, worker idle, không warning sau đối soát.

Nghiệm thu analytics bổ sung: Graph từ chối `shares` trên Reel nên collector dùng `views` cho video/Reel, giữ `shares` cho post/ảnh. Sau sửa, fetch Reel live trả `succeeded`, lưu likes/comments/views đều 0 theo Meta và URL đầy đủ; fetch Page Tinix trả `succeeded`, lưu followers/page_likes đều 0. Targeted tests và full `BUILD.bat --no-bump` đạt 100%; backend PID 18992 health/database `ok`, worker idle, không warning. Chưa bật lịch fetch analytics tự động, chưa nghiệm thu live các nhánh album 4–10 ảnh và Instagram publishing.

Album ba ảnh cũng đã đăng thử trên Page Tinix sau preflight/dry-run. Job `49060e3f-ab23-4e22-bb24-38eadc474c7f` thành công trong một attempt; Graph xác nhận đúng Page và attachment album có ba ảnh theo thứ tự. [Permalink album thử](https://www.facebook.com/122132248658779083/posts/122132332970779083). Không có thay đổi code trong lượt nghiệm thu này. Album 4–10 ảnh, scheduler Meta tự động và Instagram publishing vẫn còn mở.
