# Giai đoạn 08 — Instagram Official API theo phạm vi hẹp

Trạng thái: **08A connection và 08B publisher một ảnh đã triển khai, fixture-tested; nghiệm thu live còn chờ Cloudflare R2 và OAuth/quyền Meta thật**. Ngày rà soát: 29-09-2026.  
Thuộc [kế hoạch tổng](plan_postiz.md), tách phần Instagram của M6.

## Mục tiêu và phụ thuộc

Bổ sung đường Official API cho một định dạng Instagram đã xác minh, ưu tiên một ảnh. Giữ adapter Chrome hiện có theo capability của nó.

Phụ thuộc composer/validation đa nền tảng giai đoạn 02 và provider lifecycle đủ biểu diễn flow thực tế. Không phụ thuộc Facebook video; kinh nghiệm upload/pending từ giai đoạn 06/07 chỉ tái sử dụng khi contract tương thích.

## Điều kiện cần xác minh trước khi chọn triển khai

1. Nhu cầu thực tế có Instagram account nào, loại account nào và định dạng nào được ưu tiên.
2. Chọn đúng sản phẩm/login flow Meta hiện hành theo app/account. Nếu có nhiều flow, chọn một flow cho đợt đầu và giữ namespace token/scope rõ; không dùng lẫn credential. **Đã chọn và triển khai Instagram Login độc lập.**
3. Xác minh yêu cầu Page linkage nếu flow đã chọn cần nó; không mặc định mọi Instagram dùng Page token hiện có.
4. Xác minh cách API lấy media. Nếu cần URL truy cập công khai, làm rõ storage, thời hạn URL, quyền truy cập và chi phí trước phần triển khai phụ thuộc. Không tự mở public server trên PC.
5. Xác minh app mode/review/quyền, quota và format/constraints bằng tài liệu chính thức ở thời điểm triển khai.

Nếu thiếu điều kiện, ghi blocker và tiếp tục giai đoạn khác độc lập; không bật capability giả hoặc phát triển đồng thời nhiều flow để đoán.

## Các bước triển khai

### 08A. Kết nối và identity — đã triển khai

- OAuth riêng dùng Instagram App, callback riêng và namespace provider `instagram`; không dùng Meta Page token hay Facebook Page binding.
- OAuth yêu cầu `instagram_business_basic`; publisher cần thêm `instagram_business_content_publish`. Callback đổi code lấy short-lived token, đổi sang long-lived token, rồi xác minh `user_id`/username trước khi lưu connection mã hóa. Chỉ lưu scope mà token response thực sự trả về. Kết nối cũ chỉ có basic phải reconnect để cấp quyền publish.
- Reconnect chỉ chấp nhận cùng external user ID; username chỉ dùng để hiển thị, không làm khóa identity. Khi đổi profile, cần ngắt connection cũ trước.
- Có thao tác gia hạn khi token còn không quá 7 ngày, xác minh lại identity trước khi ghi token mới và tăng credential revision. Không tự thay đổi Chrome-discovered targets.
- Đã thêm trạng thái connection, kết nối/ngắt kết nối/gia hạn trong trang Accounts và fixture tests; chưa chạy OAuth thật với Instagram App.

### 08B. Một ảnh — code và fixture tests đã xong; live acceptance đang chờ cấu hình

- Publisher `official_api` hỗ trợ đúng một JPEG, tối đa 8 MB (8.000.000 byte) và caption 2.200 ký tự; Chrome adapter hiện có vẫn giữ nguyên.
- File được kiểm tra lại SHA-256 rồi tải lên bucket private R2. Tinix ký URL HTTPS chỉ-đọc 1 giờ (cấu hình giới hạn 5 phút–24 giờ); xóa object sau xác minh thành công, lifecycle là phương án dọn khi job dở dang.
- Flow publisher tạo container, poll trạng thái, lưu checkpoint để resume, ghi commit point trước `media_publish`, rồi xác minh ID/loại media/permalink và đúng profile. Sau commit point mà mất xác nhận, job thành `unknown_result` và không tự đăng lại.
- Dry-run chỉ kiểm tra local, identity, scope và JPEG; không upload R2, gọi Graph API ghi dữ liệu hay tạo container. Kết quả nêu riêng R2 đã cấu hình hay chưa.
- Fixture tests kiểm tra upload/ký/xóa, dry-run, thứ tự endpoint, resume từ container và bảo vệ duplicate sau unknown result.

### 08C. Mở rộng có chọn lọc

- Carousel chỉ sau một ảnh đạt, với thứ tự items, lỗi từng item và publish nhóm được kiểm tra riêng.
- Reel/Story chỉ khi người dùng có nhu cầu và entitlement đã xác minh; lập substage riêng, không coi là phụ kiện nhỏ của ảnh.
- Analytics Instagram là capability riêng; không bật chỉ vì publishing thành công.

## Kiểm thử và nghiệm thu

- Account không phải Instagram, app thiếu scope/secret/version, OAuth state sai/hết hạn; reconnect đổi identity; token hết hạn/mất quyền.
- Media URL không truy cập được/hết hạn, processing lỗi, rate limit và ID hết hạn nếu API có khái niệm đó.
- Restart/hủy giữa các bước, timeout sau publish, không duplicate và đúng account.
- Batch Facebook + Instagram + YouTube nhận đúng media/settings/route.
- OAuth live trên Instagram Professional account thử nghiệm, xác nhận identity, scope và gia hạn trước khi nâng authentication readiness.
- Live cho một ảnh chỉ sau khi có HTTPS media delivery trên account được chỉ định; carousel/Reel/Story có bằng chứng riêng mới nâng readiness tương ứng.

## Vùng mã và bàn giao

Provider/integration catalog, account service/bindings, publisher/router, media delivery nếu được chọn, composer và test provider/scheduling/reliability. Giữ public API cũ tương thích.

Giao kết nối, ảnh và mỗi format mở rộng thành các đợt riêng. Mọi đợt code chạy build/restart và báo cáo giới hạn theo kế hoạch tổng; đăng thật phải có chỉ thị cụ thể.

Tham chiếu: [Meta Instagram API với Instagram Login](https://www.postman.com/meta/instagram/folder/1z5vxzu/instagram-api-with-instagram-login), [tài liệu Meta về Instagram API](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api), [R2 presigned URLs](https://developers.cloudflare.com/r2/api/s3/presigned-urls/) và [R2 object lifecycle](https://developers.cloudflare.com/r2/buckets/object-lifecycles/). Tài liệu Meta xác nhận flow/login scope và việc Instagram Login không đòi Page linkage; fixture tests chưa thay thế nghiệm thu Graph API trên App/account thật.

## Kết quả rà soát và triển khai tại mốc này

- [Instagram API collection chính thức của Meta trên Postman](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api) mô tả hai flow tách biệt. Facebook Login yêu cầu Instagram Professional account được liên kết với Facebook Page; Instagram Login dùng cho Business/Creator và không yêu cầu Page liên kết.
- Meta dùng scope hiện hành `instagram_business_basic` và `instagram_business_content_publish`; các scope cũ `business_basic` và `business_content_publish` đã deprecated. Tinix tách credential Instagram khỏi Facebook và không yêu cầu Page linkage trong Instagram Login.
- Người dùng đã chọn flow Instagram Login độc lập, ưu tiên ảnh trước; trước đây xác nhận chưa có HTTPS media storage. Để mở đường publisher, Tinix dùng R2 private bucket + URL GET ký hạn ngắn thay vì mở máy Tinix ra Internet.
- Publisher one-JPEG và R2 delivery hiện đã tích hợp trong catalog/router/service và fixture-tested. Điều này chưa chứng minh R2 credentials, Meta App review/redirect/quyền hoặc token live đã hoạt động.
- Chưa đăng ký bucket hoặc token thay người dùng: chưa có phiên Cloudflare đăng nhập trong môi trường làm việc. Làm theo hướng dẫn cấu hình dưới đây; không gửi Access Key/Secret qua chat.

### Cấu hình Cloudflare R2 để mở live acceptance

1. Trong Cloudflare Dashboard → **R2 Object Storage**, tạo bucket **Standard** riêng, ví dụ `tinix-instagram-media`; giữ private và không bật public access/custom domain.
2. Tạo R2 API token với quyền **Object Read & Write**, giới hạn chỉ bucket này. Lưu Access Key ID và Secret Access Key vào máy; Cloudflare chỉ hiển thị secret khi tạo.
3. Trong bucket → **Settings → Object Lifecycle Rules**, thêm rule xóa sau **1 ngày** với prefix `tinix-instagram-tmp/`. Lifecycle thường xóa object trong vòng 24 giờ kể từ hạn; publisher cũng xóa object sau bài đã xác minh.
4. Lấy Account ID từ R2 Overview. Điền các biến dưới đây vào `.env` ở thư mục gốc Tinix rồi restart backend; không commit file `.env`:

   ```dotenv
   TINIX_INSTAGRAM_R2_ACCOUNT_ID=<Cloudflare Account ID>
   TINIX_INSTAGRAM_R2_BUCKET=tinix-instagram-media
   TINIX_INSTAGRAM_R2_ACCESS_KEY_ID=<R2 Access Key ID>
   TINIX_INSTAGRAM_R2_SECRET_ACCESS_KEY=<R2 Secret Access Key>
   TINIX_INSTAGRAM_R2_URL_TTL_SECONDS=3600
   ```

5. Trong Tinix Integrations, cấu hình Instagram App Login với scope basic + content publish, kiểm tra callback URI khớp Meta Dashboard, rồi reconnect account Instagram Professional để cấp cả hai scope. Nếu Meta yêu cầu App Review/Advanced Access cho người dùng ngoài app role thì phải hoàn tất quy trình đó trước khi mở rộng.
6. Chạy dry-run kiểm tra local trước. Sau khi người dùng cho phép nội dung/profile Instagram cụ thể, đăng một ảnh thử thật rồi xác nhận permalink, media type và account đích. Reel/carousel/Story là nghiệm thu riêng.

R2 Standard hiện có free tier theo tháng gồm 10 GB-month, 1 triệu Class A và 10 triệu Class B request; phần vượt mức có thể tính phí, dù egress miễn phí. Kiểm tra [bảng giá chính thức](https://developers.cloudflare.com/r2/pricing/) trước khi bật sử dụng.

### Review phase kết nối và publisher — 29-09-2026

- Review 08A/08B: identity giữ namespace độc lập; callback đồng bộ đúng target kiểu profile; reconnect/refresh giữ nguyên external ID. Publisher xác minh đúng target, scope, MIME/JPEG thật, hash, checkpoint và trạng thái unknown sau commit.
- 15 fixture tests Instagram đạt. Dry-run không tạo cloud/API side effect. Chưa chạy OAuth hay publish thật do R2 chưa cấu hình và chưa có quyền/token Instagram live; không ghi nhận phase là live-verified.
- Rủi ro vận hành còn lại là request mất mạng trong lúc tạo container có thể để lại object mồ côi; lifecycle một ngày dọn phần còn lại. Sau khi container ID được lưu, Tinix resume poll mà không tạo container thứ hai.
- Tiếp theo: người dùng tạo private R2 bucket/token theo checklist và cấu hình `.env`; Tinix reconnect để lấy scope publish, dry-run, sau đó yêu cầu xác nhận profile/nội dung ngay trước Instagram post thử thật.
