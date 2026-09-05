# Tinix Social Hub

Hướng dẫn thao tác đầy đủ: [docs/HUONG_DAN_SU_DUNG.md](docs/HUONG_DAN_SU_DUNG.md).

Tinix Social Hub là ứng dụng Windows **PC-first** để xây dựng, duyệt, lập lịch, đăng và đối soát nội dung đa nền tảng. Mỗi account có thể chọn Chrome automation hoặc official API; Chrome vẫn là mặc định tương thích. Ứng dụng chạy local, không cần Docker, Redis, Celery, PostgreSQL, HTTPS hoặc reverse proxy.

> App cho phép Export/Import toàn bộ account và Chrome profile bằng một file ZIP dùng chung giữa các ứng dụng Tinix. Facebook, Instagram image/carousel, TikTok short video, YouTube video/Short và X post đã có Chrome adapter; selector vẫn phải qua dry-run trên từng account thực trước lần đăng thật đầu tiên.

Official API hiện đã có vertical slice hoàn chỉnh cho YouTube video/Short: OAuth, làm mới token, resumable upload và xác minh video. Meta, TikTok và X mới có contract/catalog để bổ sung adapter ở các giai đoạn tiếp theo.

## Cài đặt và Khởi động

Yêu cầu:
- Windows 10/11.
- Python 3.11 trở lên.
- Google Chrome hoặc Microsoft Edge.

### 1. Khởi động chế độ App Mode độc lập (Khuyên dùng)
Nhấp đúp [START.bat](START.bat) hoặc icon **Tinix Social Hub** trên màn hình Desktop:
- Máy chủ backend chạy ngầm hoàn toàn trong nền (`pythonw.exe`).
- Tự động mở giao diện trong cửa sổ ứng dụng độc lập (**App Mode** không thanh địa chỉ/tab), cảm giác như native Windows software.
- Tự động tạo Desktop Shortcut với logo màu vàng sang trọng nếu chưa có.
- Để dừng máy chủ ngầm, chỉ cần chạy [STOP.bat](STOP.bat).

### 2. Khởi động kèm Console (Debug / Development)
Nhấp đúp [Run.bat](Run.bat):
- Giữ cửa sổ terminal console để theo dõi log backend trực tiếp.
- Nhấn `Ctrl+C` tại cửa sổ để dừng an toàn.

### 3. Tự động cập nhật phiên bản & Rebuild
Nhấp đúp [BUILD.bat](BUILD.bat) hoặc chạy:
```powershell
.\.venv\Scripts\python.exe build.py
```
Script sẽ tự động:
1. Tăng phiên bản mới (`patch` bump, ví dụ `v1.0.1` -> `v1.0.2`).
2. Biên dịch icon vector SVG sang bộ icon Windows độ phân giải cao (`favicon.ico`).
3. Tạo/cập nhật Desktop shortcut ngoài màn hình.
4. Chạy toàn bộ 133+ test tự động để đảm bảo chất lượng.
5. Tạo Git commit cho bản build mới.

## Cấu hình AI

Chỉnh `.env` trên máy cá nhân:

```env
TINIX_AI_BASE_URL=https://api.deepseek.com
TINIX_AI_MODEL=deepseek-chat
TINIX_AI_API_KEY=your-key-here
TINIX_AI_TIMEOUT_SECONDS=60
TINIX_AI_MAX_RETRIES=2
```

API key chỉ được đọc ở backend, không gửi xuống frontend. Logging có bộ lọc redaction để loại key nếu một lỗi vô tình chứa key trong message.

## YouTube Official API (tùy chọn)

Tạo OAuth 2.0 Client loại Web application trong Google Cloud, bật YouTube Data API v3 và thêm callback `http://127.0.0.1:8765/api/oauth/youtube/callback`. Sau đó cấu hình:

```env
TINIX_YOUTUBE_CLIENT_ID=...
TINIX_YOUTUBE_CLIENT_SECRET=...
TINIX_YOUTUBE_REDIRECT_URI=http://127.0.0.1:8765/api/oauth/youtube/callback
```

Khởi động lại app, vào **Tài khoản & Page**, bấm **Kết nối API** trên account YouTube và cấp quyền. Chọn **Ưu tiên API** để dùng API khi kết nối còn hiệu lực và tự dùng Chrome trước commit nếu API không đủ điều kiện; chọn **Chỉ API** để tuyệt đối không chuyển sang Chrome. Token OAuth được lưu bằng DPAPI trên Windows và không được trả về frontend.

## Quy trình Chrome publishing

### 1. Account và đăng nhập

1. Mở tab **Tài khoản & Page**.
2. Thêm account Facebook, Instagram, TikTok, YouTube hoặc X.
3. Chọn **Mở Chrome**.
4. Đăng nhập nền tảng thủ công trong Chrome đó. Đây là profile riêng của Tinix, không phải profile Chrome cá nhân.
5. Chọn **Kiểm tra login**.
6. Chọn **Đồng bộ Page/kênh** sau khi trạng thái là “Đã đăng nhập”.

Profile nằm tại `chrome_profiles/<UUID>`. UUID không đổi khi sửa account hoặc xóa account khác.

Có thể dùng **Export Account & Sessions ZIP** để tạo một file `.tinix-profiles.zip` chứa toàn bộ tên account, nền tảng, username/UID, email, password, secret 2FA, mật khẩu email, cookie lưu trong database và dữ liệu phiên Chrome cần thiết; cache, model Chromium và file tạm không được đóng gói. **Import Profiles ZIP** tự tạo lại tất cả account trong một lần. Tinix không dùng chung thư mục profile sống. File ZIP không mã hóa và phải được bảo quản như dữ liệu đăng nhập.

Nút **Dọn dẹp profile** quét trước dung lượng có thể giải phóng rồi xóa cache/model có thể tạo lại của mọi profile. Cần đóng Chrome trước khi chạy; cookies, Local State, Preferences, Local Storage, Session Storage và IndexedDB được giữ nguyên.

Trong **Cài đặt → Tự động dọn Chrome profile**, Tinix mặc định kiểm tra mỗi 6 giờ và tự dọn khi tổng cache có thể xóa đạt 5 GB hoặc ổ chứa profile còn dưới 10 GB. Có thể tắt, chọn ngưỡng 2/5/10 GB hoặc nhập từ 0,5 đến 100 GB. Nếu Chrome đang mở, app chỉ thông báo và thử lại ở lần kiểm tra sau.

### 2. Nội dung và duyệt

1. Tạo nội dung trong **Kho nội dung**, hoặc tạo draft từ **AI Content Studio**.
2. Thêm nhiều ảnh hoặc một video.
3. Gửi duyệt rồi duyệt revision hiện tại.
4. Nếu sửa bài sau khi duyệt, approval bị vô hiệu và phải duyệt revision mới.

### 3. Dry-run

1. Vào **Calendar**.
2. Chọn content, account và Page chính xác.
3. Giữ bật **Dry-run an toàn**.
4. Worker mở composer, điền caption/media và dừng trước nút **Đăng**.
5. Kiểm tra Chrome thủ công. Job phải kết thúc ở `dry_run_ready`; không có automated test nào phát hành lên mạng xã hội.

Dry-run không bấm nút Đăng.

### 4. Đăng thật

Chỉ bỏ chọn dry-run khi:

- Account đã đăng nhập.
- Page đích đã được đồng bộ đúng.
- Revision hiện tại đã được duyệt.
- Media còn tồn tại và hợp lệ.
- Dry-run đã tới bước cuối thành công.
- Người vận hành xác nhận rõ đây là đăng thật.

Publisher ghi commit point trước khi bấm Đăng. Nếu đã bấm nhưng không xác minh được kết quả, job chuyển `unknown_result` và **không tự retry**, tránh đăng trùng.

## Xử lý login/checkpoint

Khi thấy `login_required`, `session_lost` hoặc `checkpoint`:

1. Mở Chrome của đúng account từ WebUI.
2. Hoàn tất đăng nhập, CAPTCHA, 2FA hoặc checkpoint trực tiếp trong Chrome.
3. Không nhập mật khẩu/2FA vào Tinix.
4. Chọn **Kiểm tra login** lại.
5. Chỉ tạo lại job sau khi trạng thái trở thành “Đã đăng nhập”.

Job checkpoint/login-required không tự retry. Chrome được giữ mở để người dùng xử lý.

## Trạng thái job quan trọng

- `dry_run_ready`: composer đã sẵn sàng, chưa bấm Đăng.
- `succeeded`: đã có tín hiệu xác minh sau đăng.
- `temporary_failure`: lỗi có thể retry sau exponential backoff.
- `permanent_failure`: lỗi không nên retry tự động.
- `login_required`: cần đăng nhập thủ công.
- `checkpoint`: cần xử lý checkpoint thủ công.
- `unknown_result`: có thể đã đăng; phải kiểm tra Facebook trước khi tạo job mới.

Mọi transition được lưu trong `publish_job_events`; mỗi lần chạy được lưu trong `publish_attempts`.

## Backup và khôi phục

- Database: `data/tinix_social.db`.
- Local automation: bearer-authenticated `/api/v1`, CLI và durable webhook outbox; xem `docs/LOCAL_AUTOMATION.md`.
- Runtime boundaries và controller/worker split: xem `docs/VPS_READINESS.md`; bản hiện tại vẫn bind loopback và không tự nhận là VPS-deployable.
- Backup luân phiên: `data/backups/`.
- Tinix tạo backup **trước** migration schema.
- Tạo backup thủ công trong tab **Cài đặt**.
- Restore chỉ chạy trong maintenance mode: request ghi khác bị khóa và worker được pause.
- Tinix tạo safety backup trước restore và kiểm tra integrity của file nguồn.

Để backup toàn bộ ứng dụng, đóng Tinix rồi sao chép:

- `data/`
- `media/`
- `chrome_profiles/`
- `.env` nếu cần giữ cấu hình máy

Không chia sẻ các thư mục này vì có thể chứa nội dung cá nhân hoặc cookie đăng nhập.

## An toàn dữ liệu và Git

Git ignore toàn bộ:

- `.env` và biến thể `.env.*`, ngoại trừ `.env.example`.
- `data/`, database và backup.
- `chrome_profiles/`.
- `media/`, `logs/`, `screenshots/`, `exports/`.
- `.venv/`, file tạm và test artifacts.

Khi xóa content, mặc định Tinix chỉ xóa record. Xóa file media là lựa chọn riêng và chỉ áp dụng cho file nằm an toàn dưới media root.

## Kiểm thử

Không có automated test nào gọi AI thật hoặc đăng mạng xã hội:

```powershell
.\.venv\Scripts\python.exe -m compileall -q app tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Test suite bao phủ migrations, repositories, state machine, retry/backoff, cancellation, restart recovery, Chrome ownership, login fixtures, target parsing, content/revision/approval, media safety/dedupe, MockAI, dual-transport routing, YouTube API publisher và Playwright frontend smoke.

## Phạm vi release candidate

- Facebook Page: post ảnh/nhiều ảnh/video qua composer Web.
- Instagram Web: image và carousel; Reel/Story vẫn khóa.
- TikTok Studio Web: một short video; photo post vẫn khóa.
- YouTube Studio Web: video và Short; community post vẫn khóa.
- X Web: post chữ, tối đa 4 ảnh hoặc một video.
- Calendar, posting slots, release control center, Media Library, UI-scraped analytics, local API v1, webhooks và CLI.

Năng lực `review_required` nghĩa là code và safety gate đã có nhưng selector cần được xác nhận bằng dry-run trên UI/account thực. Adapter không được chuyển một format bị khóa thành thành công giả.

Khung đa nền tảng và ma trận năng lực được mô tả tại [docs/PLATFORM_ARCHITECTURE.md](docs/PLATFORM_ARCHITECTURE.md). WebUI đọc cùng catalog qua `GET /api/platforms`, vì vậy phần tổng quan phản ánh đúng trạng thái code thay vì ngụ ý mọi nền tảng đã hoạt động.

Để duyệt toàn cảnh module, luồng dữ liệu và các quyết định còn mở, xem [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md).

Khả năng VPS chỉ được chuẩn bị qua module boundary, settings, repositories và durable queue. MVP không triển khai hạ tầng VPS, Linux, multi-user hoặc microservice.
