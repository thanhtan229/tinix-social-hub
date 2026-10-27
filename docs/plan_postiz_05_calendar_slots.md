# Giai đoạn 05 — Calendar, khung giờ và đổi lịch thuận tiện

Trạng thái: **Đã triển khai dialog, day view, slot gợi ý và đổi lịch nhóm nguyên tử; kéo-thả được hoãn**. Ngày hoàn tất: 28-09-2026.  
Thuộc [kế hoạch tổng](plan_postiz.md), tách phần calendar của M5.

## Mục tiêu và điều kiện

Quản lý lịch nhiều Page/kênh theo ngày/tuần/tháng, lọc nhanh và đổi lịch có kiểm tra trạng thái. Giai đoạn 01 phải hoàn tất; dùng màn release detail của giai đoạn 04 nếu đã có.

Mã hiện tại đã có posting slots, next-slot và transaction reschedule. Tái sử dụng; không xây một scheduler khác.

## Các bước triển khai

### 05A. Dialog và bộ lọc

1. Thay prompt bằng dialog gồm target, giờ cũ/mới, timezone và trạng thái.
2. Click thẻ mở detail; thao tác “Đổi lịch” riêng để tránh click xem vô tình sửa.
3. Lọc account/target/platform/status; giữ bộ lọc khi đổi view.
4. Điều hướng tháng theo tháng lịch thật, list view có khoảng ngày rõ; không hardcode số ngày khiến người dùng hiểu sai.

### 05B. Day view và posting slots

1. Day view hiển thị releases cùng slot gợi ý theo target.
2. Một nhóm có lịch khác nhau hiển thị từng release đúng thời điểm; không chỉ dùng giờ đầu của plan.
3. Tính next-slot riêng từng target và nêu đó là gợi ý. Muốn đảm bảo giữ chỗ phải có thiết kế reservation riêng; không giả định đã có.
4. Cho giờ ngoài slot theo policy hiện tại; không biến slot thành ràng buộc cứng ngoài yêu cầu.

### 05C. Đổi lịch nhóm và kéo-thả

1. Trước thao tác nhóm, hiển thị danh sách release cụ thể và các mục không còn đổi được.
2. Mặc định chọn cả nhóm mà một mục lỗi thì không áp dụng nhóm một phần. Muốn chỉ đổi các release hợp lệ, người dùng chọn rõ tập đó.
3. Kiểm tra và cập nhật release/job/events/plan trong transaction; worker claim xảy ra trước thì reschedule phải bị từ chối.
4. Kéo-thả chỉ thêm sau dialog và kiểm thử thời gian đạt; dùng cùng backend. Có thao tác tương đương bằng bàn phím/dialog.
5. Nếu thêm hoàn tác, thực hiện như một request đổi lịch mới và kiểm tra lại trạng thái; không hứa undo sau khi job đã chạy.

## Quy tắc thời gian

Lưu instant UTC và timezone hiển thị/audit. Không gửi giờ không có offset rồi để server đoán. Với giờ DST không tồn tại hoặc có hai cách hiểu, yêu cầu chọn thời điểm rõ. Hiển thị cảnh báo giờ quá khứ và áp dụng missed policy hiện có.

## Kiểm thử và nghiệm thu

- Ranh giới ngày/tháng/năm, tháng 28/29/30/31 ngày; timezone máy khác timezone đang xem.
- Slot qua nửa đêm, hai target có slot khác nhau, giờ quá khứ và DST.
- Kéo-thả/dialog tạo cùng kết quả; lỗi backend phục hồi vị trí hiển thị cũ.
- Reschedule đồng thời worker claim; sau commit point không sửa lịch được.
- Đổi lịch nhóm lỗi ở giữa rollback đủ; một release đổi giờ không đổi payload/media/route.
- Filters, view và detail dùng cùng ID; bài dry-run phân biệt bài thật.

## Vùng mã và bàn giao

`compose.js`, HTML/CSS, calendar/publication/job repositories, API routes và `tests/test_calendar.py` cùng scheduling/frontend.

Có thể giao 05A, 05B, 05C riêng. Mỗi phần tuân thủ test/build/restart trong kế hoạch tổng. Kéo-thả chưa đạt không chặn giao dialog/calendar đã ổn nếu báo rõ phạm vi.

Tiếp theo theo nhu cầu: [ảnh Facebook API](plan_postiz_06_facebook_photo_api.md) hoặc [analytics tự động](plan_postiz_09_analytics_refresh.md).

## Kết quả triển khai

- Calendar có day/week/month/list, lọc platform/account/target/status, điều hướng đúng ngày/tuần/tháng và detail release dùng chung.
- Day view lấy slot gợi ý riêng theo target qua API hiện có; UI ghi rõ gợi ý không giữ chỗ. Request gợi ý được giới hạn theo lô nhỏ.
- Dialog đổi lịch hiển thị từng release, lịch cũ, account/target, trạng thái và timezone. Giờ local được đổi sang UTC; từ chối giờ DST không tồn tại hoặc mơ hồ, cảnh báo giờ quá khứ và nêu chính sách job bị lỡ.
- Đổi lịch nhóm gọi một endpoint transaction: kiểm tra mọi job trước khi sửa, audit từng release/job và cập nhật plan; nếu một mục đã claim/chạm commit thì rollback cả nhóm. Người dùng thấy rõ danh sách mục sẽ đổi.
- Kiểm tra unit/API về rollback nguyên tử, lịch job, DST và Playwright day view/đổi lịch nhóm đạt.
- Chưa làm kéo-thả/undo; giữ dialog làm thao tác tương đương truy cập được và tránh thêm bề mặt thời gian trước nghiệm thu lâu dài.
