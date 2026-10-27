# Giai đoạn 03 — Bộ kênh lưu sẵn, chữ ký và chọn media thuận tiện

Trạng thái: **Hoàn tất fixture/UI; chưa nghiệm thu live publish**. Hoàn tất: 28-09-2026.  
Thuộc [kế hoạch tổng](plan_postiz.md), chi tiết hóa M4.

## Mục tiêu và phụ thuộc

Giảm thao tác lặp khi tạo bài thường ngày: nạp bộ Page/kênh, chèn thông tin liên hệ/hashtag và chọn nhiều media trong một lần.

Yêu cầu tối thiểu giai đoạn 01. Có thể giao cho Facebook trước; hỗ trợ preset đa nền tảng sau giai đoạn 02. Không phụ thuộc API media mới.

## Phạm vi

- Bộ target và settings mặc định có tên dễ nhớ.
- Chữ ký/hashtag mẫu có thể chèn vào draft và chỉnh sửa.
- Media picker chọn nhiều, tìm kiếm/lọc, xem thứ tự và compatibility.
- Không tự tạo job khi chọn preset, không tự sửa hàng loạt bài đã lưu.

## Các bước triển khai

### 03A. Bộ Page/kênh

1. Khảo sát app settings/repository hiện có và chọn cách lưu tối thiểu, có version và được backup. Không dùng browser storage làm nguồn chính.
2. Lưu ID target, nhãn preset, format/settings mặc định cần thiết. Không lưu token, approval, evidence hay nội dung riêng của bài cũ.
3. Khi áp dụng, kiểm tra lại target/account/connection. Đích mất quyền/tắt/xóa hiện lỗi; không thay bằng Page cùng tên và không tự bỏ chọn.
4. Nếu draft đã có lựa chọn, hiển thị rõ hành động thay thế hoặc gộp; gộp không trùng target và không ghi đè override âm thầm.
5. Sửa/xóa preset chỉ ảnh hưởng lần dùng sau. Không đổi kế hoạch/release đã tạo.

### 03B. Chữ ký và hashtag mẫu

1. Cho tạo/sửa/xóa mẫu; mặc định chèn thủ công. Auto-add chỉ là tùy chọn người dùng bật rõ.
2. Chèn vào draft trước validation/duyệt, có preview và khả năng sửa.
3. Chốt vị trí chèn và cách nhận biết phần chữ ký để áp dụng lại không nhân đôi; không tìm/xóa tùy tiện đoạn caption người dùng viết giống mẫu.
4. Mẫu thay đổi không làm bài cũ đổi nội dung. Áp dụng lại vào draft là thao tác sửa revision bình thường.
5. Hashtag/chữ ký tham gia giới hạn caption của từng đích; không âm thầm cắt nội dung để đạt giới hạn.

### 03C. Media picker

1. Chọn nhiều asset bằng checkbox, xem số đã chọn và giữ selection khi lọc.
2. Có vùng xem lại thứ tự; phân biệt bỏ khỏi lựa chọn với xóa file.
3. Cảnh báo/chặn asset không phù hợp theo target và route hiện tại, dùng validator chung.
4. Áp dụng một lần vào editor; hủy dialog/editor không đổi record đã lưu. Nếu asset bị xóa hoặc đổi trong lúc chọn, kiểm tra lại khi lưu.
5. Giữ tags, alt text, thumbnail và dedupe đã có; không xây thư viện media mới.

## Kiểm thử và nghiệm thu

- Tạo một bài mới từ preset chỉ cần một lần chọn bộ target; target không hợp lệ được nêu đúng.
- Gộp hai preset không nhân đôi Page; đổi preset không làm mất bản riêng chưa lưu.
- Chèn chữ ký hai lần không nhân đôi; sửa chữ ký thủ công vẫn được giữ; mẫu mới không đổi release cũ.
- Chọn nhiều media qua nhiều lần lọc, sắp xếp, hủy/lưu đúng; lỗi attach không báo thành công giả.
- Preset/mẫu sống qua restart và backup/restore; không chứa credential.
- Test UI và repository liên quan đạt; regression revision/validation/media đạt.

## Vùng mã và bàn giao

`posts.js`, HTML/CSS, API content/media hiện có, app settings hoặc repository tối thiểu cần thiết; chưa chốt thêm bảng trước khi khảo sát storage hiện tại.

Giao từng phần 03A → 03B → 03C nếu cần. Mỗi phần phải có test, build, restart/health và hướng dẫn theo kế hoạch tổng. Giai đoạn 04 có thể bắt đầu độc lập khi giai đoạn 01 đã đủ dữ liệu release.

Tiếp theo: [giai đoạn 04](plan_postiz_04_release_reconciliation.md).

## Kết quả triển khai và review

- Dùng `target_groups` sẵn có, bổ sung `defaults_json` qua migration 25 để lưu format và settings theo target; UI lịch hỗ trợ thay thế, gộp, cập nhật, xóa và tạo bộ Page/kênh. Target bị mất/không khả dụng làm thao tác áp dụng bị chặn, không tự rơi khỏi lựa chọn. Cập nhật membership/default chạy trong một transaction.
- Chữ ký/hashtag dùng app settings versioned key, có UI tạo/sửa/xóa; mặc định chỉ chèn thủ công. Chèn không nhân đôi exact text/tag và chỉ sửa draft đang mở.
- Media Library hỗ trợ checkbox multi-select, giữ lựa chọn qua lọc, stage tới khi lưu bài và giữ thứ tự chọn. Editor hủy không ghi attach. Lỗi lưu hiện lên thay vì báo thành công; server kiểm tra asset còn tồn tại.
- Media riêng theo target của giai đoạn 02 dùng chung picker; explicit empty khác với inherit, asset reference/revision/restore được bảo vệ.
- Kiểm tra: nhóm repository/API, chữ ký API, media revision và Playwright composer/target picker đạt; `node --check` và `compileall` đạt. Build full suite: 100% passed, tạo `v1.0.42`.
- Restart/health: Build dừng server cũ; server mới PID 8248 chạy `pythonw.exe -m app`, `/api/health` trả `ok`/`v1.0.42`; `posts.js` đang phục vụ nhóm Page/kênh và chữ ký.
- Không thực hiện đăng thật để nghiệm thu nhóm Page/kênh hoặc media.
