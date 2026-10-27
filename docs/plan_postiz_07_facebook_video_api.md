# Giai đoạn 07 — Facebook Page Official API cho video

Trạng thái: **Reel và video Page thường đã đăng thật trên Page Tinix; Reel tự xác minh `succeeded`, video thường đã đối soát thủ công.** Ngày cập nhật: 29-09-2026.  
Thuộc [kế hoạch tổng](plan_postiz.md), tách phần video của M6.

## Mục tiêu và phụ thuộc

Đăng cả Facebook Reel và video Page thường qua API, với tiến trình upload/xử lý/xuất bản có thể theo dõi và phục hồi an toàn. Hai định dạng là hai contract riêng: triển khai, validation và nghiệm thu độc lập; không dùng flow Reel cho video Page thường.

Đi sau giai đoạn 06 theo lộ trình đề xuất để tận dụng credential, media validation và bằng chứng vận hành. Phần bắt buộc là contract media, route/evidence và lifecycle publish đã ổn; không cần chờ mọi tính năng UX.

## Điều kiện bắt đầu

- Xác minh endpoint, quyền, Graph version, loại video đầu tiên, metadata/codec và phương thức upload từ máy local.
- Xác minh API có upload session/resume hay không và thời hạn của các ID/URL; không giả định resumable giống YouTube.
- Vạch ranh giới bước upload, processing và công khai bài. Chốt khi nào timeout là có thể retry, khi nào là unknown.
- Kiểm tra Publisher/worker hiện tại có biểu diễn pending/check/finalize đủ không. Chỉ bổ sung trạng thái/progress tối thiểu có test nếu cần.

## Các bước triển khai

### 07A. Validation và upload

1. Đọc metadata local bằng công cụ đang có; báo thiếu metadata hoặc format không hỗ trợ. Không tự cài transcoder hay chuyển đổi video trong phạm vi này.
2. Lưu asset hash, kích thước, session/progress cần thiết nếu provider hỗ trợ; không lưu secret trong payload/UI.
3. Kiểm tra file còn đúng snapshot trước upload; thay file không được tiếp tục session cũ như cùng nội dung.
4. Giới hạn concurrency theo provider/account và nguồn lực local hiện có.

### 07B. Processing và publish

1. Thể hiện các bước có ý nghĩa: đang tải, đang xử lý, đang xác minh; không coi upload xong là đã đăng.
2. Poll có giới hạn và backoff theo phản hồi provider; nhả tài nguyên worker phù hợp khi chờ dài.
3. Persist ID/trạng thái để restart tiếp tục kiểm tra đối tượng đã có, không tạo video mới.
4. Hủy trước publish dừng bước tiếp theo; hủy sau commit không hứa xóa video từ nền tảng.
5. Ghi commit point và kết quả chưa xác định như contract đã chốt; chỉ đánh dấu thành công sau bằng chứng phù hợp.

### 07C. UI và nghiệm thu

1. Hiển thị tiến trình, thời gian kiểm tra cuối, lỗi có hướng xử lý và link sau xác minh.
2. Phân biệt lỗi upload, processing, quyền và unknown sau publish.
3. Nếu muốn thêm Reel, lập acceptance substage riêng với format, endpoint, validation và evidence riêng; không bật cùng video thường mặc định.

## Kiểm thử và nghiệm thu

- Upload gián đoạn, session hết hạn, media thay đổi, rate limit và mất quyền.
- Restart ở upload/processing/sau commit; tiếp tục đúng ID, không upload/publish lại ngoài policy.
- Processing thành công/lỗi/quá hạn; không polling vô hạn hoặc giữ khóa Chrome không liên quan.
- Cancel ở mỗi boundary; timeout sau publish; xác minh đúng Page và identity.
- Batch nhiều Page lỗi độc lập; Chrome, YouTube resumable và Facebook ảnh không đổi hành vi.
- Live chỉ cho loại video và Page được phép; báo rõ định dạng chưa được nghiệm thu.

## Vùng mã và bàn giao

Meta publisher, publisher contracts/worker/provider progress nếu cần, validation/media metadata, job/release detail và test tương ứng. Nếu cần migration durable progress, bắt buộc kiểm tra backup/restore và dữ liệu cũ.

Giao theo upload → processing/finalize → UI/acceptance; build/restart theo kế hoạch tổng sau mỗi đợt code. Không giao nhãn “hỗ trợ video” khi mới upload được nhưng chưa xác minh publish.

Tham chiếu cần xác minh: [Meta Video Publishing](https://developers.facebook.com/docs/video-api/guides/publishing/). Trang trả HTTP 429 trong lượt lập kế hoạch; giới hạn và flow cụ thể chưa được xác minh lại.

## Kết quả rà soát tại mốc triển khai

- Workspace [Facebook API chính thức của Meta trên Postman](https://www.postman.com/meta/facebook/documentation/r56bjfd/facebook-api) hiện mô tả luồng Facebook Reels: khởi tạo upload, gửi file local hoặc URL CDN, đọc trạng thái tùy chọn và hoàn tất publish. Ví dụ chỉ ra các boundary upload/processing/publish; điều này đủ làm contract ứng viên để lập kế hoạch, chưa phải bằng chứng Tinix đã tương thích hoặc Page của người dùng có entitlement.
- Phần Reel trong collection ghi giới hạn riêng (dọc 9:16, tối thiểu 4 giây/tối đa 60 giây, độ phân giải dọc tối thiểu 540×960). Xem đây là baseline của collection cần đối chiếu lại với tài liệu developer theo Graph version/app được chọn trước khi code; tuyệt đối không áp dụng cho Page video thường.
- Người dùng đã chọn cả Reel và video Page thường. Reel được tách làm format riêng trên Official API; Chrome và video Page thường chưa được mở.
- Rà soát lại ngày 28-09-2026: workspace Facebook chính thức trên Postman có mục Reel rõ ràng, nhưng không tìm thấy contract publish video Page thường trong collection truy cập được; trang Meta Video API tiếp tục trả HTTP 429. Mẫu “Upload video” trong Facebook Marketing API không được lấy làm bằng chứng cho bài video organic trên Page. Giữ video Page thường ở trạng thái gated cho đến khi endpoint, quyền và local upload flow được xác minh từ tài liệu Graph API phù hợp.
- Reel dùng local upload qua `rupload.facebook.com`, so khớp kích thước/SHA-256 với bản release, lưu video ID vào provider request trước finalize, rồi poll trạng thái publish có giới hạn. Timeout sau finalize giữ kết quả `unknown_result`, không tạo upload/session thứ hai. Dry-run không gửi request tới Meta.
- Reel preflight dùng `ffprobe` có sẵn trên máy để kiểm tra MP4/MOV/M4V, tỷ lệ gần 9:16, tối thiểu 540×960, 23 fps và 4–60 giây. Thiếu `ffprobe` hoặc đọc lỗi thì dry-run chặn upload với hướng dẫn rõ; Tinix không tự cài transcoder hay chuyển đổi file.
- Chưa có Page thử nghiệm/entitlement để xác nhận live; giới hạn và acceptance cụ thể vẫn cần thử với Graph version/App/Page đang cấu hình trước khi coi giai đoạn hoàn tất.
- Video Page thường vẫn chờ reference chính thức đủ chi tiết về endpoint, upload flow và Graph version; không dùng lại Reel flow. Không tự đăng thật.

### Review phase sau triển khai — 28-09-2026

- Kiểm tra lại collection Facebook chính thức của Meta trên Postman: Reel có ví dụ upload file local qua RUpload, trạng thái processing và bước publish; đây là contract được dùng cho implementation fixture-tested. Kiểm tra lại trang Video API chính thức vẫn không đọc được; collection truy cập được không mô tả video Page thường.
- Review implementation xác nhận Reel có preflight file local/hash/metadata, lưu upload session trước commit, chỉ tiếp tục cùng video ID sau restart và không tự tạo session/retry publish khi kết quả chưa rõ. Tests tương ứng có trong Meta API suite; build đầy đủ gần nhất đạt 283 tests.
- Không tìm thấy vấn đề cần sửa trong nhánh Reel bằng bằng chứng hiện có. Không nâng nhãn lên live-verified: chưa có Page thử nghiệm/entitlement và chưa đăng thật.
- Phần video Page thường còn mở theo yêu cầu người dùng. Cần tài liệu Graph API chính thức nêu endpoint, quyền, Graph version, local upload/resume và trạng thái publish; không lấy luồng Reel hoặc Facebook Marketing API thay thế.

### Triển khai video Page thường — 28-09-2026

- Xác minh [Page Videos Graph API reference](https://developers.facebook.com/docs/graph-api/reference/page/videos/) và [Video API Publishing guide](https://developers.facebook.com/docs/video-api/guides/publishing/) ở Graph API v26.0. Page video organic dùng `POST /{page-id}/videos`, Page access token, task `CREATE_CONTENT` và scopes `pages_manage_posts`, `pages_read_engagement`, `pages_show_list`. API reference nêu các phase `start`, `transfer`, `finish`, `cancel`, `file_size`, `upload_session_id`, offset và multipart `video_file_chunk`; `published` mặc định là true. Guide trả video ID khi publish thành công.
- Tinix hỗ trợ một file MP4 mỗi bài, upload theo đúng offset Meta trả về. Mỗi chunk được đánh dấu đang chờ trước request và chỉ lưu offset tiếp theo sau phản hồi xác nhận; restart chỉ tiếp tục ở offset đã xác nhận. Chunk/finish không rõ kết quả chuyển `unknown_result`, không gửi lại mù. Finish thành công phải trả video ID mới được báo đã đăng; status polling không được tự giả định vì publishing guide không mô tả bước này.
- Đã mở lập lịch batch Facebook cho format hiện có, gồm ảnh/video/Reel; format được đưa vào chữ ký preflight để thay đổi lựa chọn không bỏ qua lần kiểm tra.
- Fixture tests bao quát endpoint/host, Page token, chunk upload, resume offset xác nhận, chunk chưa xác định, timeout khi finish, khôi phục ID hoàn tất, file đổi và dry-run. Không tạo bài đăng thật. Page video chưa được kiểm tra live với App/Page của người dùng.
- **Video Page thường đạt ở mức code + fixture.** Nghiệm thu live còn cần Meta App/Page đang kết nối có quyền phù hợp và chỉ thị cụ thể về bài thử; không cần CDN/HTTPS storage cho upload local Facebook này.

Nhánh tiếp theo tùy nhu cầu: [Instagram API](plan_postiz_08_instagram_api.md) hoặc [analytics](plan_postiz_09_analytics_refresh.md).

### Nghiệm thu live video Page thường — 28-09-2026

- Page `Tinix` (`1106784475845782`), MP4 H.264/AAC 5 giây và caption thử nghiệm. Preflight/dry-run đạt; luồng `POST /{page-id}/videos` start → transfer → finish đều HTTP 200.
- Meta xác nhận video ID `1433112448754530`, `from.id` đúng Page và `publishing_phase.publish_status=published`. [Video đã đăng](https://www.facebook.com/reel/1433112448754530/). Meta trả permalink dạng `/reel/` dù request dùng Page Videos API; đây là URL thực tế, không có nghĩa Tinix đã gọi Reel publishing API.
- Lần đăng này Tinix ban đầu để `unknown_result` vì finish trả `success=true` nhưng không lặp lại `video_id` đã có từ start. Đã đối soát qua Graph và finalize job theo bằng chứng, không upload lại. Publisher nay lưu video ID từ start, xác minh trạng thái/Page/permalink sau finish, và chỉ khôi phục bằng GET khi kết quả finish chưa rõ. Fixture regression đã bổ sung. Cần thêm lần live sau khi sửa nếu muốn xác nhận tự động kết thúc `succeeded` trên App/Page thật; không đăng thêm bài công khai chỉ để lặp thử trong đợt này.

### Nghiệm thu live Reel — 29-09-2026

- Người dùng cho phép đăng Reel thật trên Page Tinix (`1106784475845782`). Preflight/dry-run `official_api_only` đạt với MP4 dọc 720×1280, 30 fps, 6 giây.
- Trước khi đăng, review phát hiện Reel chỉ dựa vào `publishing_phase.status=complete`. Đã bổ sung kiểm tra `from.id`, `publish_status=published`, video ID và chuẩn hóa permalink; test chống xác nhận nhầm Page và kiểm tra khôi phục được thêm.
- Attempt đầu: Meta tạo session `2534252100425049`, nhưng RUpload trả HTTP 400; Graph vẫn cho thấy `uploading=in_progress`, `processing/publishing=not_started`. Không gửi finish, không tạo bài công khai từ session này; job được đối soát `permanent_failure`.
- [Collection Facebook API chính thức của Meta](https://www.postman.com/meta/facebook/documentation/r56bjfd/facebook-api) mô tả upload nhị phân với `file_size` và `offset`. Tinix bổ sung `Content-Length` cho request streaming và ghi mã lỗi HTTP/Graph vào job khi upload bị từ chối. Clip thử tiếp theo có chuyển động và bitrate khoảng 1,24 Mbps; không thể quy riêng lỗi 400 ban đầu cho thiếu header hay đặc điểm clip.
- Job live `c944e4e0-b3d0-4d68-ac11-d6c37f9cd20b` hoàn tất `succeeded` trong một attempt. [Reel công khai](https://www.facebook.com/reel/1329975209041799/); Graph xác nhận ID `1329975209041799`, đúng Page, bytes uploaded `942982`, processing complete, `publish_status=published` và caption đúng.
- Review sau triển khai: 94 targeted tests Meta/state machine đạt, `BUILD.bat --no-bump` full suite 100%. Backend PID 40096 chạy v1.0.43, health/database `ok`, worker idle, không warnings sau đối soát. Kết quả live giới hạn ở Page/App và clip này.
