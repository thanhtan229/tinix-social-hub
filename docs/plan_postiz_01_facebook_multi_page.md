# Giai đoạn 01 — Composer và lập lịch nhiều Facebook Page

Trạng thái: **Đã triển khai và kiểm thử**. Hoàn tất: 28-09-2026.  
Thuộc [kế hoạch tổng](plan_postiz.md), chi tiết hóa M0–M2. Đây là ưu tiên người dùng đã xác nhận.

## Mục tiêu và điều kiện bắt đầu

Một bài có thể chọn nhiều Facebook Page thuộc nhiều account, chỉnh nội dung riêng từng Page, duyệt và tạo một kế hoạch có kết quả độc lập cho mỗi Page.

Trước khi sửa mã, kiểm tra lại working tree, entrypoint UI và baseline tests. Kết nối Meta nhiều Page đã có; không xây lại OAuth hay System User. Nghiệm thu dùng target/format đã xác định, không giả định mọi adapter đều sẵn sàng.

## Phạm vi

- Global và bản riêng theo Page; giữ tương thích variants theo platform.
- Một giờ chung, cho chỉnh giờ từng Page; dry-run là mặc định.
- Preflight toàn bộ đích và tạo plan/releases/jobs nguyên tử, chống submit trùng.
- Chrome/API theo khả năng hiện có. Official API Facebook vẫn text-only cho tới giai đoạn 06.
- Bảng trạng thái từng Page, gồm thành công một phần và cần đối soát.

## Các bước triển khai

### 01A. Chốt dữ liệu và hợp đồng

1. Chốt dữ liệu kế thừa Global → platform → target và phiên bản cấu hình. Phương án ưu tiên là JSON có version trên content, snapshot vào revision; media vẫn có reference chính thức.
2. Chốt cách đọc bài legacy và thao tác chuyển sang cấu hình mới. Bài đã lên lịch và revision lịch sử không được diễn giải lại theo quy tắc mới.
3. Chốt request preflight/commit, revision mong đợi và mã yêu cầu chống trùng. Giữ request một account hiện tại tương thích.
4. Chốt nội dung được duyệt: target overrides, media và settings ảnh hưởng bài xuất bản đều phải được lưu trước khi duyệt. Lịch chạy thuần túy theo policy reschedule riêng.
5. Chốt boundary transaction dùng chung cho plan, releases, jobs và liên kết; không gọi scheduler riêng từng account rồi gộp kết quả.

### 01B. Nội dung chung và riêng

1. Thêm Global độc lập với variant chính trong editor đang dùng ở `posts.js`.
2. Cho Page kế thừa hoặc tách bản riêng. Khi tách, sao chép bản hiệu lực; khi quay về dùng chung, báo rõ phần tùy chỉnh sẽ bị bỏ.
3. Giữ giá trị rỗng có chủ đích, đặc biệt hashtag/CTA; không dùng fallback theo truthiness cho cấu hình mới.
4. Lưu/tải lại, duplicate, restore và revision phải giữ đúng chế độ. Client cũ cập nhật trường cũ không được xóa cấu hình mới.
5. Media chọn trong editor được stage tới lúc lưu; hủy không đổi bài đã lưu. Không báo lưu thành công nếu liên kết media bắt buộc thất bại.

### 01C. Preflight và tạo lịch

1. Chọn target qua nhiều account, phân biệt Page trùng tên bằng account/identity.
2. Resolve nội dung, media, format, settings và route bằng backend dùng chung cho preview và schedule.
3. Hiển thị tất cả lỗi theo Page; một đích lỗi thì chưa ghi batch. Người dùng chủ động bỏ chọn hoặc sửa đích lỗi.
4. Trước commit, kiểm tra lại revision, approval, trạng thái target và fingerprint credential/binding. Có thay đổi thì yêu cầu preflight lại.
5. Ghi nguyên tử; worker chỉ thấy jobs sau commit. Gửi lại cùng mã/cùng payload trả cùng plan, cùng mã khác payload bị từ chối.
6. Giữ due time và delay/random delay ổn định qua retry. Giữ concurrency/khóa profile hiện có.
7. Nối “Lên lịch nhanh” và tab Lịch vào cùng đường xử lý, không nhân bản logic validation.

## Kiểm thử và nghiệm thu

- Fixture ít nhất hai account, ba Page, một Page có bản riêng; đúng một plan và ba releases/jobs.
- Sửa Global không ghi đè bản riêng; caption/hashtag rỗng được xử lý đúng; tải lại/duplicate/restore không mất cấu hình.
- Sửa nội dung đã duyệt làm mất hiệu lực approval theo policy; snapshot đã tạo bất biến.
- Lỗi validation hoặc lỗi ghi DB ở job thứ hai không để batch dở.
- Hai submit đồng thời, timeout sau commit và gửi lại không tạo thêm jobs.
- Credential/binding/revision đổi giữa preflight và commit không dùng dữ liệu cũ.
- Một Page thành công, một Page lỗi, một Page unknown vẫn hiển thị đúng; không retry cả nhóm.
- Request cũ, Chrome publishing, YouTube API và Meta Page binding qua hồi quy.

Suite trọng tâm: content/scheduling, API, state/migrations, publisher routing, Meta, reliability và frontend. Chạy full suite trước giao thay đổi persistence/scheduling; build và restart theo mục 8 của kế hoạch tổng.

## Vùng mã và đầu ra

`posts.js`, `compose.js`, `index.html`, `style.css`, `api/content.py`, `services/scheduling.py`, content/publication/job repositories; migration chỉ khi phương án đã chốt yêu cầu.

Đầu ra là đợt nhiều Page dùng được với capability hiện tại, hướng dẫn thao tác và kết quả test/build/restart thực tế. Có thể giao các bước 01B/01C riêng, nhưng chỉ đánh dấu giai đoạn 01 hoàn tất khi toàn bộ luồng đạt tiêu chí.

## Kết quả triển khai và review

- Đã thêm composition versioned theo Global → platform → Page; editor giữ giá trị rỗng có chủ đích, cho kế thừa/tách bản, và giữ cấu hình qua cập nhật từ client cũ, duplicate và restore.
- Revision hiện chụp media reference. Gắn/bỏ media tạo revision mới và làm approval cũ hết hiệu lực; restore khôi phục danh sách media. Xóa asset bị chặn khi release hoặc revision còn tham chiếu.
- Quick Schedule chọn Facebook Page qua nhiều account, cho đặt giờ riêng mỗi Page, xem caption/media/route từng đích và preflight toàn bộ. Calendar Facebook dùng cùng API preflight/batch; các nền tảng khác giữ endpoint hiện tại.
- Batch tạo plan, releases, jobs, event và liên kết trong một transaction. Kiểm tra lại revision, approval, account, target và Meta binding trong transaction. Cùng request key/payload trả lại job cũ; payload khác bị từ chối. Random delay được cố định theo request key.
- Bộ test xác nhận ba Page trên hai account, override rỗng, giờ riêng, delay ổn định, preflight không ghi DB, retry idempotent và lỗi không tạo batch một phần. Có API và Playwright coverage.
- Không thực hiện đăng bài thật. Giai đoạn này chỉ mở Facebook Page dạng `post`; API của Meta vẫn bị ràng buộc bởi capability text-only và dry-run evidence đang có. Chưa mở media/API mới.

Build full suite thành công, cập nhật v1.0.39 → v1.0.40. Backend cũ được thay; PID mới 26568 chạy từ thư mục Tinix, `/api/health` trả `ok`/v1.0.40, bundle `main.js` đúng version và asset `posts.js` có preflight. Live publish không nằm trong phạm vi xác minh.

Chuyển sang [giai đoạn 02](plan_postiz_02_multi_platform.md). Các quy tắc duyệt, chống trùng, tương thích, build/restart và không tự commit trong kế hoạch tổng áp dụng đầy đủ. Kế hoạch chưa cho phép đăng bài thật.
