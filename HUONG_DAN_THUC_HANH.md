# Hướng dẫn thực hành Tinix Social Hub

Tài liệu này bám theo 8 tab đang có trong ứng dụng. Làm theo luồng ở phần 1 để đăng bài an toàn; các phần sau giải thích từng tab và nút chính.

## 1. Luồng làm việc chuẩn

1. **Tạo tài khoản** trong **Tài khoản & Page**, mở Chrome riêng, đăng nhập nền tảng, kiểm tra login rồi đồng bộ Page/kênh.
2. **Tạo nội dung** trong **AI Content Studio** hoặc **Kho bài viết**. Kiểm tra caption, media và đúng nền tảng.
3. **Duyệt bài** trong Kho bài viết. Gửi duyệt rồi duyệt bản sửa đổi mới nhất. Nếu chỉnh bài sau đó, cần duyệt lại.
4. **Lập lịch Dry-run** trong **Calendar**: chọn bài, account, Page/kênh, định dạng và giờ; giữ chọn **Dry-run an toàn**.
5. Khi job thành `dry_run_ready`, xem Chrome: đúng account/Page, caption, ảnh/video và định dạng chưa. Dry-run dừng trước nút Đăng.
6. Sau khi thử thành công và bài đã duyệt, lập lịch mới, bỏ chọn Dry-run để đăng thật. Theo dõi kết quả trong **Hàng đợi & Lịch sử**.
7. Xem kết quả và số liệu trong **Tổng quan** hoặc **Analytics**.

> Đăng thật có thể tạo bài công khai. Nếu job báo `unknown_result`, kiểm tra nền tảng trước khi làm lại để tránh đăng trùng.

## 2. Tổng quan

- **Các thẻ số liệu**: xem nhanh lượng nội dung/tác vụ và tình trạng hiện tại.
- **Khung nền tảng**: xem catalog năng lực. “Bộ khung” chỉ là trạng thái hỗ trợ kiến trúc, không đảm bảo định dạng đã đăng được.
- **Job gần đây**: xem các tác vụ mới; chọn **Xem tất cả** để sang Hàng đợi.
- **Trạng thái hệ thống**: xem tình trạng các thành phần local.
- **+ Lập lịch**: mở Calendar để tạo lịch mới.

Dùng tab này để kiểm tra nhanh trước khi bắt đầu hoặc sau khi chạy bài.

## 3. AI Content Studio

### Soạn bài

1. Chọn **System Prompt** để chọn quy tắc viết. Nút **Thêm/Sửa** dùng quản lý prompt.
2. Chọn **Brand Profile** nếu muốn giữ đúng giọng thương hiệu; có thể thêm/sửa hồ sơ tại đây hoặc nút **Quản lý Brand Profile**.
3. Nhập **Brief**: ghi mục tiêu, sản phẩm, đối tượng và thông điệp mong muốn.
4. Thêm tối đa 4 **Ảnh tham chiếu** bằng Tải ảnh, Thư viện hoặc kéo thả. Ảnh tham chiếu giúp AI hiểu hình ảnh và có thể được gắn vào bản nháp.
5. Chọn các **Nền tảng xuất bản** cần tạo nội dung, rồi bấm **Tạo bản nháp**.
6. Xem kết quả ở khung **Kết quả**. Chuyển giữa **Trực quan** và **JSON**, sao chép JSON hoặc bấm **Xem bài viết** để mở bản nháp trong Kho bài viết.

### Lịch sử và tạo ảnh

- **Lịch sử tạo**, **Trước/Sau**: mở kết quả đã tạo; **Brief mới** bắt đầu yêu cầu khác; **Xóa** xóa lịch sử tạo.
- Sau khi có nội dung, xem/chỉnh **Prompt tạo ảnh**, chọn **Provider ảnh**, tỷ lệ và số lượng, rồi bấm **Tạo Ảnh**. Có thể **Hủy**, xem các ảnh, **Tải về** hoặc **Gắn vào bài viết**.
- AI chỉ tạo bản nháp, không tự lên lịch hoặc đăng. Hãy đọc và sửa nội dung trước khi duyệt.

## 4. Kho bài viết

### Tìm và lọc

- Các thẻ **Tất cả bài / Đã đăng / Đã lên lịch / Bản nháp / Đăng lỗi** lọc nhanh theo trạng thái.
- Bộ lọc **Nền tảng**, **Tình trạng**, **Loại bài** và **Sắp xếp theo** thu hẹp danh sách.
- Ô **Tìm kiếm** tìm theo tiêu đề, caption hoặc hashtag.
- Nút **Thẻ/Bảng** đổi cách hiển thị. **Làm mới** nạp lại dữ liệu.
- Chọn bài bằng checkbox để **Chọn tất cả** hoặc xóa nhiều bài; kiểm tra kỹ trước khi xóa.

### Tạo và quản lý bài

1. Bấm **+ Tạo bài viết**.
2. Điền tiêu đề nội bộ, caption và thông tin nội dung; chọn nền tảng và media phù hợp.
3. Lưu bản nháp, mở bài để rà soát.
4. Dùng thao tác gửi duyệt/phê duyệt trên bài để duyệt đúng revision hiện tại.
5. Lập lịch bài qua Calendar.

**Quản lý Media** mở thư viện file, gồm cả tệp chưa gắn bài. **Xuất Excel / CSV** tải danh sách bài để đối soát.

## 5. Calendar

### Xem lịch

- Chọn chế độ **Tuần / Tháng / Danh sách**.
- Dùng **← / →**, ô ngày hoặc **Hôm nay** để chuyển thời gian.
- Lọc theo **Nền tảng** và **Trạng thái**. Chọn một mục lịch để xem/kiểm tra tác vụ.
- Giờ hiển thị theo giờ máy; hệ thống lưu dữ liệu theo UTC.

### Lên lịch bài

1. Chọn **Nội dung** và **Account**.
2. Trong **Trang / kênh / profile**, chọn đúng đích đăng (có thể chọn nhiều đích nếu phù hợp).
3. Chọn **Định dạng**; đọc bộ đếm và các thiết lập nền tảng xuất hiện.
4. Chọn **Ngày giờ**. Chọn cách xử lý job lỡ giờ: chờ xác nhận, đăng bù hoặc bỏ qua.
5. Có thể đặt thời gian trễ giữa các Page và độ trễ ngẫu nhiên tối đa.
6. Giữ bật **Dry-run an toàn** cho lần thử. Bấm **Lưu lịch**.
7. Khung **Preview nội dung** giúp kiểm tra bài đã chọn.

### Posting slots (khung giờ)

1. Chọn Page/kênh và múi giờ.
2. Nhập mỗi dòng theo dạng `thứ giờ:phút`; thứ 0 là Thứ Hai, 6 là Chủ Nhật. Ví dụ: `0 09:00`.
3. Bấm **Lưu slots**. Khi cần lịch gần nhất, bấm **Dùng slot kế tiếp**, kiểm tra giờ được điền rồi lưu lịch.

## 6. Hàng đợi & Lịch sử

- **Cần chú ý** liệt kê cảnh báo; bấm **Đã đọc tất cả** để đánh dấu đã xem.
- Bảng hiển thị account, trạng thái, chế độ và thời gian. Mở chi tiết job để xem tiến trình, log hoặc ảnh lỗi nếu có.
- **Làm mới** cập nhật danh sách; **Dọn lịch sử** dọn các bản ghi theo lựa chọn của ứng dụng.
- Retry hàng loạt: chọn các job lỗi đủ điều kiện, bấm **Xem trước**, kiểm tra phạm vi rồi mới bấm **Retry đã chọn**. Retry chỉ khả dụng trước commit point.
- `dry_run_ready`: đã điền composer và dừng trước Đăng. `succeeded`: có tín hiệu xác minh thành công. `login_required`/`checkpoint`: xử lý đăng nhập trong Chrome. `unknown_result`: kiểm tra thủ công trên nền tảng trước khi tạo job khác.

## 7. Analytics

1. Chọn khoảng thời gian **7 / 30 / 90 ngày**.
2. Chọn nền tảng hoặc **Mọi nền tảng**.
3. Bấm **Làm mới** để đọc lại dữ liệu.
4. Thẻ số liệu là kết quả thu thập; phần **Release reconciliation** đối chiếu trạng thái phát hành.

Thu thập chỉ chạy khi bấm nút và đọc số liệu đang hiển thị trong Chrome. Mục “không hỗ trợ” nghĩa là không có dữ liệu, không phải giá trị 0.

## 8. Tài khoản & Page

### Account và phiên đăng nhập

1. Bấm **+ Thêm account**, đặt tên dễ nhớ, chọn nền tảng và lưu.
2. Chọn account ở danh sách. Có thể tìm theo tên/email/ID, lọc nền tảng/trạng thái và sắp xếp.
3. Dùng khung chi tiết để chỉnh thông tin account.
4. Bấm **Mở Chrome**, đăng nhập thủ công trong profile riêng của account.
5. Quay lại Tinix, bấm **Kiểm tra login**. Khi đã đăng nhập, bấm **Đồng bộ Page/kênh**.
6. Chọn Page/kênh đúng trong danh sách đã đồng bộ; tìm bằng ô tìm kiếm nếu cần.

Không nhập mật khẩu hay mã 2FA vào Tinix để xử lý checkpoint; hoàn tất trực tiếp trong Chrome rồi kiểm tra login lại.

### Profile và quản lý danh sách

- **Import Profiles**: nhập đường dẫn gói ZIP/ENC đã xuất; nhập mật khẩu nếu gói được mã hóa.
- **Export Profiles**: xuất profile; chỉ chọn kèm credential khi thực sự cần. Credential DPAPI gắn với tài khoản Windows đã xuất. Có thể đặt mật khẩu mã hóa toàn gói.
- **Đóng tất cả Chrome**: đóng các cửa sổ Chrome do Tinix mở.
- Lọc/tìm Page trong khung **Page / Kênh đã đồng bộ** để rà soát đích đăng.

## 9. Cài đặt & Dữ liệu

- **Database**: xem vị trí/tình trạng dữ liệu; **Integrity check** kiểm tra toàn vẹn; **Tạo backup** sao lưu thủ công; **Khôi phục gần nhất** phục hồi bản backup gần nhất.
- **Bảo trì – Chạy dọn ngay**: dọn dữ liệu tạm/screenshot và kiểm tra ngưỡng profile theo mô tả trạng thái.
- **Kiểm tra sẵn sàng – Kiểm tra ngay**: kiểm tra Chrome, database, ổ đĩa và tích hợp local.
- **Recovery bundle**: tạo gói phục hồi có mật khẩu; đóng Chrome trước khi tạo. Nếu kèm `.env`, giữ kín vì có thể chứa API key. Dùng **Khôi phục bundle** để phục hồi từ gói.
- **Tự động dọn Chrome profile**: bật/tắt, chọn ngưỡng cache hoặc nhập mức tùy chỉnh, rồi **Lưu thiết lập**. Cache có thể tạo lại được xóa; phiên đăng nhập được giữ. Nếu Chrome đang mở, việc dọn sẽ được hoãn.
- **Tích hợp & API**: thêm/chỉnh AI Provider, đặt AI mặc định cho nội dung và lưu. **Platform Developer Apps** dùng cấu hình ứng dụng nền tảng/OAuth; kết nối API vẫn cần cấu hình và cấp quyền riêng cho từng account.

## 10. Khi gặp lỗi

- Không có Page/kênh: kiểm tra login thành công rồi đồng bộ lại.
- Job báo `login_required`, `session_lost` hoặc `checkpoint`: mở Chrome đúng account, xử lý trực tiếp, kiểm tra login rồi tạo job sau.
- Job báo `unknown_result`: mở nền tảng kiểm tra bài đã xuất hiện chưa; không retry mù.
- Dry-run sai nội dung/đích: hủy hoặc không đăng, sửa bài/đích, duyệt lại revision mới và chạy dry-run lại.
- Sao lưu trước khi chuyển máy hoặc khôi phục dữ liệu; không chia sẻ file chứa cookie, profile hay credential.
