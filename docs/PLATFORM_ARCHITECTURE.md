# Khung kiến trúc đa nền tảng

Tài liệu này mô tả trạng thái release candidate. Các mục `review_required` đã có adapter nhưng cần dry-run trên UI thực; format bị khóa tuyệt đối không được báo đăng thành công.

## Kiến trúc dual transport

Tinix hỗ trợ hai transport độc lập: `chrome` và `official_api`. Chrome automation tiếp tục là mặc định và giữ nguyên profile riêng. Official API dùng OAuth/System User connection, adapter riêng theo provider và chỉ được router chọn khi account đã kết nối, format được hỗ trợ và adapter đã đăng ký lúc chạy. YouTube Data API v3 hỗ trợ upload video/Short; Facebook Page API hỗ trợ post, một ảnh, album ảnh, video MP4 và Reel. Một ảnh, album hai ảnh, video Page thường và Reel đã được thử live trên Page Tinix. TikTok và X vẫn để `scaffold`.

Mỗi account có một `routing_preference`: `chrome_preferred`, `official_api_preferred`, `chrome_only` hoặc `official_api_only`. Khi lập lịch, route được gắn riêng với target, connection ID và fingerprint quyền đã cấp, rồi đóng băng vào release. Dry-run chỉ hợp lệ với đúng target/connection/quyền đó. Worker kiểm tra lại trước khi thực thi. Sau commit point, hệ thống không fallback sang transport khác; lỗi không xác định chuyển thành `unknown_result` để người dùng xác minh, tránh đăng trùng.

## Nguồn sự thật

`app/platforms/catalog.py` là catalog duy nhất mô tả nền tảng, loại account/target, định dạng nội dung, mức sẵn sàng của từng capability và milestone tiếp theo. API `GET /api/platforms` cung cấp catalog cho WebUI. Việc xuất hiện trong catalog không tự mở khóa scheduling hoặc publisher.

## Ranh giới module dự kiến

Mỗi tích hợp nền tảng sẽ đi qua cùng các ranh giới:

1. **Content variant**: caption, hashtag, title, hook và video script riêng.
2. **Account session**: profile Chrome riêng, phát hiện login/checkpoint; metadata đăng nhập Import từ gói Tinix được lưu để chuyển profile giữa các app.
3. **Target discovery**: Page, Profile hoặc Channel có external ID ổn định.
4. **Composer adapter**: chuẩn bị caption/media và dry-run dừng trước commit point.
5. **Publisher adapter**: thao tác đăng thật sau khi được duyệt.
6. **Verifier**: xác minh URL hoặc tín hiệu thành công; không rõ kết quả phải trả `unknown_result`.

Queue, retry, cancellation, approval, idempotency, artifact và browser ownership dùng chung. Selector, login detector, target parser, composer và verifier phải nằm riêng theo nền tảng.

## Trạng thái hiện tại

| Nền tảng | Nội dung | Session/target | Đăng/xác minh API | Analytics API |
|---|---|---|---|---|
| Facebook | Post, một ảnh, album ảnh, video MP4, Reel | Có, nhiều Page trên một Meta connection | Một ảnh, album hai ảnh, video Page thường và Reel đã thử live trên Page Tinix | Đã code, cần kiểm thử thật |
| Instagram | Image/carousel | Chrome profile + profile discovery | Đã code, cần kiểm thử thật | Đã code, cần kiểm thử thật |
| TikTok | Short video | Chrome profile + channel discovery | Đã code, cần kiểm thử thật | Đã code, cần kiểm thử thật |
| YouTube | Video/Short | Chrome profile hoặc OAuth 2.0 | API đã triển khai; cần acceptance trên account test | Snapshot Data API + chuỗi theo ngày Analytics API; cần acceptance thật |
| X | Post chữ/ảnh/video | Chrome profile + profile discovery | Đã code, cần kiểm thử thật | Đã code, cần kiểm thử thật |

Instagram, TikTok, YouTube và X có Chrome adapters versioned, login detector, target discovery, composer, commit point và UI verifier. Các format đã mở lần lượt là Instagram image/carousel, TikTok short video, YouTube video/Short và X post; Reel, Story, photo post và community post vẫn trả `unsupported`. YouTube còn có official adapter dùng resumable upload. Mọi adapter mặc định dry-run; dry-run API chỉ kiểm tra kết nối, payload và media, không tạo upload session.

## Analytics API

* **Bài YouTube:** snapshot hiện tại gồm lượt xem, thích và bình luận từ Data API; daily report theo video gồm views, likes, comments, shares, watch time và thay đổi subscriber. Bài phải là release đã đăng/đã đối soát, có video ID, thuộc đúng channel.
* **Kênh YouTube:** snapshot lượt xem, subscriber và video; report theo ngày giữ interval riêng. Snapshot lifetime không bị cộng dồn; interval trùng kỳ chỉ lấy một nguồn ưu tiên.
* `GET /api/analytics/channels/history` và `.../summary` hỗ trợ history/filter; Analytics UI lọc platform/account/target, bài phân trang mới nhất và thể hiện source/ngày.
* Cập nhật tự động mặc định tắt. Khi bật, hệ thống quét tối đa số bài/kênh cấu hình mỗi chu kỳ, giới hạn cửa sổ 7/30/90 ngày; lỗi scope/quota/rate-limit được ghi lại và nằm trong cooldown, không chạy dồn khi mở app.
* Analytics ngoài YouTube: chỉ Meta Graph collector (Page/post/Reel) đã có; provider khác báo scaffold/unsupported. Không đọc metric qua cookie hoặc private endpoint để giả API.

## Gate vận hành còn lại

1. Mở Chrome profile và đăng nhập thủ công cho đúng account.
2. Đồng bộ target rồi chạy dry-run với media đại diện.
3. Ghi nhận selector/version lỗi nếu UI đã thay đổi.
4. Chỉ tạo real schedule sau khi revision đã duyệt và dry-run thành công.
5. Sau commit point, mọi kết quả chưa xác định phải đối soát thay vì retry.

Không mở Reel, Story, TikTok photo post hay YouTube community post cho tới khi có page object và verifier riêng.
