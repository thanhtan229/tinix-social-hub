# Khung kiến trúc đa nền tảng

Tài liệu này dùng để duyệt hướng đi. Các mục đánh dấu **scaffold** chưa phải tính năng vận hành và tuyệt đối không được báo đăng thành công.

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
| Instagram | Có variant | Scaffold | Scaffold | Chưa làm |
| TikTok | Có variant | Scaffold | Scaffold | Chưa làm |
| YouTube | Có variant | Scaffold | Scaffold | Chưa làm |

Publisher placeholder của ba nền tảng mới luôn trả `unsupported`; chúng không giả lập thành công. Tab **Calendar** dùng universal composer theo schema; runtime chỉ nhận nền tảng đã được đánh dấu vận hành.

## Thứ tự triển khai đề xuất sau khi duyệt

1. Chốt Facebook MVP bằng dry-run và một bài test có giám sát.
2. Chọn một nền tảng tiếp theo dựa trên nhu cầu nội dung thực tế.
3. Làm session + target discovery và fixture parser trước.
4. Làm dry-run composer, bổ sung test mock và kiểm thử thủ công.
5. Chỉ sau đó mới mở real publish và verifier.

YouTube sẽ đi qua YouTube Studio bằng Chrome automation. Instagram/TikTok vẫn cần chốt format MVP đầu tiên; không nên triển khai đồng thời mọi định dạng.
