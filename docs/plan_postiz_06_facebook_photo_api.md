# Giai đoạn 06 — Facebook Page Official API cho ảnh

Trạng thái: **Một ảnh và album hai/ba ảnh đã live-verified trên Page Tinix; album 4–10 ảnh chưa thử live.** Ngày cập nhật: 29-09-2026.  
Thuộc [kế hoạch tổng](plan_postiz.md), tách phần ảnh của M6.

## Mục tiêu và phụ thuộc

Mở rộng publisher Facebook text-only hiện có để đăng một ảnh, sau đó nhiều ảnh vào đúng Page bằng API chính thức. Không xây lại connection/System User/multi-Page binding.

Phụ thuộc giai đoạn 01 và contract media/validation của giai đoạn 02 hoặc phần tương đương đã hoàn tất. Không bắt buộc đợi preset/calendar; có thể đưa lên sau giai đoạn 02 nếu nhu cầu ảnh cao.

## Điều kiện trước triển khai

1. Kiểm tra Graph version đang cấu hình, loại credential, quyền/Page tasks và endpoint ảnh được Meta hỗ trợ cho account thực tế.
2. Xác minh đường gửi file local: ưu tiên upload trực tiếp nếu endpoint hỗ trợ; nếu cần URL công khai, chốt storage/delivery riêng. Không tự mở cổng máy local hoặc chọn dịch vụ có phí.
3. Xác định rõ bước nào tạo media chưa xuất bản, bước nào làm bài công khai và ID nào là ID bài. Không suy luận từ publisher text hiện có.
4. Ghi giới hạn file/số ảnh/MIME và cách xác minh theo tài liệu chính thức tại thời điểm thực hiện.

Nếu một điều kiện chưa xác minh được, chỉ triển khai phần fixture/preflight không phụ thuộc; capability thực tế giữ chưa sẵn sàng.

## Các bước triển khai

### 06A. Một ảnh

- Mở validation theo format/transport và metadata đã xác minh; lỗi nêu đúng asset.
- Tạo publisher path cho một ảnh, dùng binding Page và credential revision hiện có.
- API dry-run chỉ đọc/kiểm tra local và quyền phù hợp, không upload media hoặc tạo đối tượng bên ngoài.
- Ghi commit point trước thao tác có thể xuất bản; timeout sau đó là cần xác minh, không gửi lại mù.
- Lưu post/media ID đúng loại và permalink khi lấy được; xác minh chủ sở hữu Page và kết quả trước đánh dấu verified.

### 06B. Nhiều ảnh

- Chỉ bắt đầu sau 06A đạt. Chốt chuỗi upload/attach/publish thực tế được provider hỗ trợ.
- Persist từng bước cần phục hồi, ID và thứ tự ảnh; tránh tạo lại media đã biết chắc upload thành công.
- Kiểm tra hủy/lỗi giữa các ảnh: trước khi bài công khai có thể xử lý tiếp theo contract, sau khi có khả năng đã publish phải đối soát.
- Nếu cần xóa media chưa xuất bản, chỉ tác động artifact thuộc đúng job và có bằng chứng chưa công khai; không xóa theo tên/caption gần giống. Bài đã công khai không tự xóa để rollback batch.

### 06C. Nối UI và nghiệm thu

- Capability cho biết riêng text/một ảnh/nhiều ảnh và phạm vi đã nghiệm thu.
- Composer preview và route eligibility khớp với publisher. Chỉ mở lựa chọn đã hỗ trợ.
- Dry-run evidence phải phân biệt capability media mới với text-only cũ bằng version/format phù hợp; không tái dùng bằng chứng text để coi ảnh đã nghiệm thu.

## Kiểm thử và nghiệm thu

- File thiếu/sai loại/quá giới hạn, quyền thiếu, sai binding/Page, credential đổi trước publish.
- Một ảnh thành công; nhiều ảnh đúng thứ tự; upload ảnh thứ hai lỗi; hủy giữa bước; restart sau khi có media ID.
- Timeout trước/sau bước publish, response thiếu ID, xác minh sai Page và permalink chưa có.
- Không tự đổi Chrome sau API commit; không tạo bài trùng khi retry/restart.
- Hồi quy text API, Chrome media, batch multi-Page và analytics identity.
- Live một ảnh rồi nhiều ảnh chỉ theo chỉ thị cụ thể về Page/nội dung. Ghi bằng chứng thật riêng; fixture thành công chưa đủ bật nhãn live-verified.

## Vùng mã và bàn giao

Meta publisher/service, capability/validation/router, durable provider progress nếu cần, worker/finalize chỉ khi contract yêu cầu; test Meta/routing/reliability/frontend.

Giao 06A và 06B độc lập nếu cần, chạy kiểm tra/build/restart mỗi đợt code theo kế hoạch tổng. Không đưa video/Reels vào cùng thay đổi.

Tham chiếu: [Meta Graph API Page SDK](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/page.py) khai báo `create_photo` với `published` và `create_feed` với `attached_media: list<Object>`; [SDK Post](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/post.py) cũng khai báo `attached_media`. Đây là mã SDK do Meta phát hành. Tinix fixture-test form upload `published=false` và `attached_media[i]={"media_fbid": ...}`; điều này chưa thay cho đăng live để kiểm tra giới hạn/serialization theo App và Graph version thực tế.

## Kết quả rà soát tại mốc triển khai

- Đã mở lại hai trang chính thức về Page Posts và Page Photos; Meta trả HTTP 429. Không thêm endpoint/multipart flow theo phỏng đoán.
- Đã kiểm tra thêm [Facebook API collection trong workspace Meta trên Postman](https://www.postman.com/meta/facebook/documentation/r56bjfd/facebook-api). Bản tài liệu truy cập được có ví dụ publishing Reels nhưng chưa cho đủ contract ảnh Page trong phần được công bố/tìm thấy; nó không thay thế tài liệu Page Photos.
- Chưa xác nhận được Graph version, loại credential/quyền của Page dùng để nghiệm thu, giới hạn media hiện hành hay đường upload an toàn từ máy local.
- Đã hoàn tất lát cắt an toàn trước khi bật media: catalog công khai rõ Facebook Official API hiện text-only/media gated; kiểm thử regression xác nhận ảnh bị từ chối ở cả dry-run và live route trước mọi Graph API request.
- Publisher vẫn text-only; capability ảnh không được bật và 06A/06B chưa bắt đầu. Tiếp tục sau khi tài liệu chính thức có thể xác minh, có test Page/định dạng và quyết định media delivery. Kiểm thử fixture này không thay cho live acceptance.

### Rà soát tiếp theo — 28-09-2026

- Mở lại các tham chiếu chính thức `Page Photos` và `Page Posts`: trình duyệt tài liệu trả lỗi truy cập; tìm trong collection Facebook chính thức của Meta trên Postman cũng không tìm thấy hướng dẫn xuất bản ảnh Page. Các kết quả không chính thức hoặc ví dụ Marketing API không đủ làm contract cho bài organic.
- Vì vậy, 06A vẫn chưa thể triển khai an toàn. Cần một tài liệu Meta truy cập được hoặc xác nhận endpoint/Graph version, quyền, multipart upload local, phản hồi/ID và giới hạn media trước khi viết publisher. Không thay blocker bằng suy đoán dựa trên API cũ.
- Rà soát code xác nhận ảnh bị chặn trước request tới Meta, cả dry-run và live route; capability Facebook Official API vẫn không quảng bá ảnh.

### Triển khai 06A — một ảnh — 28-09-2026

- Tài liệu Meta Graph API hiện hành được mở trực tiếp ở v26.0: [Page Photos](https://developers.facebook.com/docs/graph-api/reference/page/photos/) cho phép `POST /{page-id}/photos`, tải file local bằng multipart `source`, caption và `published=true`. Tạo ảnh cần Page access token, Page task `CREATE_CONTENT` và các quyền `pages_manage_posts`, `pages_read_engagement`, `pages_show_list`.
- Tinix chỉ mở đúng một ảnh cho mỗi release API: JPEG/PNG/BMP/GIF/TIFF, tối đa 10 MB; kiểm tra MIME, extension, snapshot/hash và Page binding trước request. Sau khi Meta trả photo ID, Tinix xác minh `from.id` thuộc Page đã chọn; permalink bài là bổ sung. Timeout/khôi phục không đăng lại mù.
- Composer cho phép lên lịch ảnh cho nhiều Facebook Page trong một batch; đổi format buộc chạy lại preflight. Chrome transport vẫn chỉ nhận post format mà catalog đã khai báo.
- Đã fixture-test multipart, Page token, binding mismatch, dry-run, snapshot thay đổi, response ID, xác minh owner và phục hồi marker. Đây không thay thế thử đăng trên Page thật.
- **06A đạt ở mức code + fixture; UI Composer/lịch batch đã nối. 06B (nhiều ảnh trong cùng bài) còn mở; live acceptance cũng chưa làm.** Không tuyên bố carousel/multi-photo được hỗ trợ. Chưa thực hiện đăng thật.

Tiếp theo: [giai đoạn 07](plan_postiz_07_facebook_video_api.md).

### Nghiệm thu live 06A — 28-09-2026

- Page `Tinix` (`1106784475845782`), một ảnh PNG thử nghiệm và caption ghi rõ bài thử. Preflight và dry-run `official_api_only` đạt; Meta `POST /{page-id}/photos` trả photo ID `122132248574779083` và post ID `1106784475845782_122132248592779083`.
- Tinix xác minh `from.id` của ảnh/bài thuộc đúng Page. [Bài ảnh đã đăng](https://www.facebook.com/122132248658779083/posts/122132248592779083). Không dùng kết quả này để coi 06B nhiều ảnh đã được nghiệm thu.
- Trong preflight đã phát hiện và sửa lỗi thiếu MIME/đường dẫn/SHA-256 khi chuyển media sang bộ kiểm tra Meta; thêm regression test cho ảnh và video.

### Triển khai 06B — album nhiều ảnh — 28-09-2026

- Thêm format `multi_photo` riêng trên Facebook Official API; Tinix giới hạn 2–10 ảnh theo policy của composer. Đây không phải tuyên bố về giới hạn tối đa của Meta. Chrome transport giữ nguyên format `post`.
- Mỗi ảnh được kiểm tra loại/MIME/kích thước/snapshot rồi upload tuần tự với `published=false`. Sau mỗi response có photo ID, Tinix lưu ID và vị trí trước khi chuyển sang ảnh tiếp theo; cuối cùng tạo đúng một Page feed post với `attached_media[i]` theo thứ tự đã chọn.
- Recovery không upload lại ảnh khi request còn mơ hồ; sau commit, Tinix chỉ xác minh post ID/Page đã lưu và không gửi bài lần nữa. Nếu timeout xảy ra khi Meta có thể đã nhận ảnh nhưng chưa lưu ID, job cần đối soát thủ công. Tinix không tự xóa ảnh chưa xuất bản vì chưa có contract/ownership cleanup đủ chắc chắn.
- Composer, schema validation, routing, preflight metadata và selector evidence đã nối cho format mới. Dry-run kiểm tra tất cả file mà không gọi Meta.
- Fixture tests bao phủ upload chưa xuất bản, thứ tự ảnh, cancel giữa chừng, phục hồi sau checkpoint, timeout upload/publish, thiếu ID, sai Page, binding/ID trùng, MIME và dry-run.
- **06B đạt ở mức code + fixture. Chưa đăng live album; live acceptance vẫn cần chỉ thị cụ thể về Page và bài thử.** SDK chính thức xác nhận các endpoint/parameter được dùng; quyền, giới hạn media và runtime còn phụ thuộc App/Page/Graph version.
- Verification: 128 targeted tests passed; `BUILD.bat --no-bump` succeeded (full suite 100%). Backend PID 52504 thay PID cũ trên cổng 8765; `/api/health` ok, version 1.0.43, database ok, worker idle, no warnings. `/api/platforms` công bố `multi_photo` (2–10) trên Official API; `compose.js` trả HTTP 200.

### Nghiệm thu live 06B — 28-09-2026

- Người dùng cho phép đăng một album hai ảnh thử trên Page Tinix (`1106784475845782`). Preflight và dry-run `official_api_only` đạt; job live `47372f00-d520-4d75-8821-963b5e3f32c1` kết thúc `succeeded` với [permalink của bài](https://www.facebook.com/122132248658779083/posts/122132264210779083).
- Graph trả post ID `1106784475845782_122132264210779083`, `from.id` là đúng Page và attachment type `album` chứa đúng hai ảnh, theo thứ tự ID `122132263586779083`, `122132264180779083`.
- Ảnh thứ nhất upload xong ở attempt 1, sau đó lỗi chuyển trạng thái `uploading` lần nữa trước ảnh thứ hai. Tinix giữ checkpoint, attempt 2 chỉ upload ảnh còn lại rồi tạo đúng một feed post. Đã sửa publisher không chuyển `uploading` lặp trong một attempt; state machine nay chấp nhận `unknown_result` khi upload chưa rõ kết quả. Test có kiểm tra đường chuyển trạng thái thật.
- Bằng chứng live này xác nhận **album hai ảnh** với Page/App hiện tại. Giới hạn 2–10 là policy của Tinix; chưa thử mọi số lượng hoặc Page khác.
- Sau bản sửa: 90 tests Meta/state machine đạt; `BUILD.bat --no-bump` đạt 100%. Backend PID 53912 thay bản cũ, `/api/health` báo `ok`, v1.0.43, database `ok`, worker idle và không có warning.

### Nghiệm thu live album ba ảnh — 29-09-2026

- Đã tạo nội dung thử ghi rõ “BÀI THỬ API album 3 ảnh”, tải ba PNG khác nhau lên Tinix theo thứ tự 1–2–3, duyệt nội dung, rồi chạy preflight/dry-run trên Page Tinix với `official_api_only`. Dry-run xác nhận đúng binding/Page, đủ ba ảnh, chưa gọi publish.
- Job live `49060e3f-ab23-4e22-bb24-38eadc474c7f` kết thúc `succeeded` trong một attempt; release `338884cd-b72b-4bcd-92af-f38ccc0d1df3`. Graph xác nhận post `1106784475845782_122132332970779083` thuộc Page `1106784475845782`, attachment là `album` với ba photo ID theo đúng thứ tự: `122132332856779083`, `122132332898779083`, `122132332940779083`.
- [Bài thử album ba ảnh](https://www.facebook.com/122132248658779083/posts/122132332970779083). Kết quả này chứng minh ba ảnh với Page/App hiện tại; album 4–10 ảnh và Page/App khác vẫn chưa được thử live. Không có thay đổi code trong lần nghiệm thu này, nên build/restart không áp dụng.
