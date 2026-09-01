# Khung kiến trúc đa nền tảng

Tài liệu này mô tả trạng thái release candidate. Các mục `review_required` đã có adapter nhưng cần dry-run trên UI thực; format bị khóa tuyệt đối không được báo đăng thành công.

## Quyết định cố định: Chrome-only publishing

Tinix không dùng API của Facebook, Instagram, TikTok hoặc YouTube để đăng bài. Mọi adapter thực hiện đăng nhập thủ công, chuẩn bị composer, upload, commit và xác minh qua Chrome automation với profile riêng. “API” trong tài liệu Tinix chỉ có thể chỉ API nội bộ chạy local, không phải API phát hành của mạng xã hội.

## Nguồn sự thật

`app/platforms/catalog.py` là catalog duy nhất mô tả nền tảng, loại account/target, định dạng nội dung, mức sẵn sàng của từng capability và milestone tiếp theo. API `GET /api/platforms` cung cấp catalog cho WebUI. Việc xuất hiện trong catalog không tự mở khóa scheduling hoặc publisher.

## Ranh giới module dự kiến

Mỗi tích hợp nền tảng sẽ đi qua cùng các ranh giới:

1. **Content variant**: caption, hashtag, title, hook và video script riêng.
2. **Account session**: profile Chrome riêng, phát hiện login/checkpoint, không lưu mật khẩu.
3. **Target discovery**: Page, Profile hoặc Channel có external ID ổn định.
4. **Composer adapter**: chuẩn bị caption/media và dry-run dừng trước commit point.
5. **Publisher adapter**: thao tác đăng thật sau khi được duyệt.
6. **Verifier**: xác minh URL hoặc tín hiệu thành công; không rõ kết quả phải trả `unknown_result`.

Queue, retry, cancellation, approval, idempotency, artifact và browser ownership dùng chung. Selector, login detector, target parser, composer và verifier phải nằm riêng theo nền tảng.

## Trạng thái hiện tại

| Nền tảng | Nội dung | Session/target | Dry-run | Đăng/xác minh |
|---|---|---|---|---|
| Facebook | Có | Có | Đã code, cần kiểm thử thật | Đã code, cần kiểm thử thật |
| Instagram | Image/carousel | Chrome profile + profile discovery | Đã code, cần kiểm thử thật | Đã code, cần kiểm thử thật |
| TikTok | Short video | Chrome profile + channel discovery | Đã code, cần kiểm thử thật | Đã code, cần kiểm thử thật |
| YouTube | Video/Short | Chrome profile + channel discovery | Đã code, cần kiểm thử thật | Đã code, cần kiểm thử thật |

Instagram, TikTok và YouTube có Chrome adapters versioned, login detector, target discovery, composer, commit point và UI verifier. Các format đã mở lần lượt là Instagram image/carousel, TikTok short video và YouTube video/Short; Reel, Story, photo post và community post vẫn trả `unsupported`. Mọi adapter mặc định dry-run và tuyệt đối không gọi API đăng bài của nền tảng.

## Gate vận hành còn lại

1. Mở Chrome profile và đăng nhập thủ công cho đúng account.
2. Đồng bộ target rồi chạy dry-run với media đại diện.
3. Ghi nhận selector/version lỗi nếu UI đã thay đổi.
4. Chỉ tạo real schedule sau khi revision đã duyệt và dry-run thành công.
5. Sau commit point, mọi kết quả chưa xác định phải đối soát thay vì retry.

Không mở Reel, Story, TikTok photo post hay YouTube community post cho tới khi có page object và verifier riêng.
