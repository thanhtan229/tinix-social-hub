# Checklist nghiệm thu publisher

Chrome publisher chỉ được chuyển từ `review_required` sang dùng đăng thật sau khi hoàn tất checklist này trên account thử nghiệm hoặc account có quyền đăng thật.

## Chuẩn bị chung

- Xác nhận phiên bản app, Chrome và `selector_version` trong catalog.
- Chạy **Kiểm tra sẵn sàng** trong Cài đặt; database, Chrome và dung lượng đĩa phải sẵn sàng.
- Tạo recovery bundle có mật khẩu, rồi đóng mọi Chrome Tinix.
- Tạo content thử nghiệm dễ nhận diện và target thử nghiệm riêng.
- Ghi ngày, account/target, format, selector version, URL kết quả và ảnh chụp lỗi nếu có.

## Cho từng nền tảng và format

1. Mở Chrome của đúng account và đăng nhập thủ công nếu cần.
2. Đồng bộ rồi chọn đúng Page, profile hoặc channel.
3. Chạy dry-run; xác nhận caption, hashtag, media và platform settings trước nút phát hành.
4. Chạy một lần đăng thật có giám sát.
5. Xác minh URL/kết quả trong nền tảng và đối soát Analytics nếu có URL.
6. Kiểm tra job history: không có `unknown_result`, retry ngoài ý muốn hoặc media khác snapshot.
7. Nếu thành công, lưu bằng chứng cùng selector version; nếu thất bại, giữ `review_required` và sửa đúng adapter trước khi thử lại.

| Nền tảng | Format cần nghiệm thu |
|---|---|
| Facebook | post có text, ảnh, carousel, video |
| Instagram | image, carousel |
| TikTok | short video, privacy, comments |
| YouTube Chrome | video, Short |
| YouTube Official API | OAuth, refresh token, video, Short, verification |
| X | post text, tối đa 4 ảnh, một video |

Không chạy nghiệm thu thật trên nội dung không thể xóa hoặc account production không có kế hoạch rollback.
