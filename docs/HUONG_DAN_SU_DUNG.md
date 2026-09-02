# Hướng dẫn sử dụng Tinix Social Studio

Phiên bản áp dụng: `1.0.0-rc.5`

Tinix Social Studio là ứng dụng chạy trên máy cá nhân để xây dựng nội dung, quản lý media, lập lịch và điều khiển Chrome đăng bài. Tinix không dùng API đăng bài của Facebook, Instagram, TikTok hoặc YouTube. Mỗi tài khoản sử dụng một Chrome profile riêng và bạn đăng nhập trực tiếp trong Chrome.

## 1. Khởi động và dừng ứng dụng

### Khởi động thông thường

Nhấp đúp `Run.bat` tại thư mục dự án. Tinix sẽ:

1. Kiểm tra Python và Google Chrome.
2. Tạo hoặc cập nhật môi trường `.venv` khi cần.
3. Tạo các thư mục dữ liệu.
4. Sao lưu rồi migrate database nếu schema thay đổi.
5. Khởi động WebUI, scheduler và worker.
6. Mở trình duyệt tại [http://127.0.0.1:8765](http://127.0.0.1:8765).

Có thể chạy thủ công bằng PowerShell:

```powershell
.\.venv\Scripts\python.exe -m app
```

### Dừng ứng dụng

Nhấn `Ctrl+C` tại cửa sổ đang chạy Tinix. Ứng dụng sẽ ngừng nhận job mới, dừng các service và chỉ đóng những Chrome do Tinix quản lý.

Không nên tắt máy hoặc kết thúc cưỡng bức tiến trình khi một job đang ở trạng thái `publishing` hoặc `verifying`.

## 2. Tổng quan giao diện

| Khu vực | Công dụng |
|---|---|
| Tổng quan | Trạng thái hệ thống, job gần đây và năng lực từng nền tảng |
| AI Content Studio | Tạo structured draft; AI không tự duyệt, lập lịch hoặc đăng |
| Kho nội dung | Tạo, sửa, nhân bản, quản lý revision và approval |
| Media Library | Upload, tái sử dụng, gắn tag và quản lý media theo SHA-256 |
| Calendar | Xem lịch, cấu hình posting slots và tạo publication plan |
| Hàng đợi & Lịch sử | Theo dõi job, attempt, artifact, retry và finalize |
| Analytics | Kết nối bài đã đăng và đọc metric hiển thị trên giao diện Chrome |
| Tài khoản & Page | Quản lý account, Chrome profile và Page/profile/channel |
| Cài đặt | Kiểm tra database, backup, restore và maintenance |

## 3. Thêm tài khoản và đăng nhập

1. Mở **Tài khoản & Page**.
2. Chọn **+ Thêm account**.
3. Nhập tên dễ nhận biết, ví dụ `Facebook chính` hoặc `YouTube Tinix`.
4. Chọn nền tảng rồi lưu.
5. Tại account vừa tạo, chọn **Mở Chrome**.
6. Đăng nhập thủ công trong cửa sổ Chrome đó.
7. Quay lại Tinix và chọn **Kiểm tra login**.
8. Khi phiên đăng nhập hợp lệ, chọn **Đồng bộ Page/kênh**.

Mỗi account có một profile tại `chrome_profiles/<UUID>`. Không đăng nhập account khác vào cùng Chrome profile nếu muốn dữ liệu và target được tách biệt rõ ràng.

### Dùng phiên đăng nhập từ dự án khác

Trong **Tài khoản & Page**, mỗi account có bốn thao tác quản lý profile:

- **Import Profiles ZIP**: đọc một file `.tinix-profiles.zip`, tự tạo toàn bộ account cùng tên/nền tảng và sao chép các phiên Chrome trong một lần. Vẫn hỗ trợ thư mục `.tinix-profile` cũ.
- **Export All Profiles ZIP**: tạo một file ZIP di động tại `exports/chrome_profiles/`, gồm manifest chung và toàn bộ Chrome profile của app.
- **Backup**: tạo điểm khôi phục nội bộ tại `data/backups/chrome_profiles/<ACCOUNT_ID>/`.
- **Khôi phục**: thay profile hiện tại bằng một backup đã chọn; profile trước khôi phục lại được backup tự động.

Trước mọi thao tác, hãy đóng Chrome đang dùng cả profile nguồn lẫn profile đích. Account không được có job chưa kết thúc. Tinix chặn Chrome đang giữ `--user-data-dir`, chặn symlink/junction, bỏ cache và lock file, chép vào thư mục tạm rồi kiểm tra cấu trúc trước khi đổi profile.

Import/Export dùng để **di chuyển account cùng tên, nền tảng và bản sao phiên Chrome giữa các dự án Tinix hoặc máy**. Backup/Khôi phục dùng để **quay lại trạng thái cũ của chính account trong Tinix**. Không trỏ hai dự án vào cùng một thư mục profile vì hai Chrome có thể làm hỏng dữ liệu phiên.

### Khi gặp CAPTCHA, 2FA hoặc checkpoint

Tinix không thu thập mật khẩu, mã 2FA hay cookie. Hãy xử lý trực tiếp trong Chrome:

1. Mở Chrome của đúng account.
2. Hoàn thành CAPTCHA, 2FA hoặc checkpoint.
3. Chọn **Kiểm tra login** lại.
4. Chỉ chạy lại job khi trạng thái phiên đã trở về đăng nhập hợp lệ.

## 4. Tạo và duyệt nội dung

### Tạo thủ công

1. Mở **Kho nội dung**.
2. Chọn **+ Tạo bài**.
3. Nhập tiêu đề nội bộ, caption, hashtag và CTA.
4. Chọn ảnh hoặc video nếu muốn upload trực tiếp vào content.
5. Lưu bản nháp.

Mỗi lần sửa content sẽ tạo revision mới. Nếu content đã được duyệt rồi bị sửa, approval cũ sẽ mất hiệu lực.

### Tạo bằng AI

1. Mở **AI Content Studio**.
2. Chọn thao tác như viết mới, viết lại, rút gọn hoặc chuyển đa nền tảng.
3. Chọn Brand Profile nếu có.
4. Nhập brief và chọn các nền tảng cần tạo variant.
5. Chọn **Tạo bản nháp**.
6. Kiểm tra và chỉnh sửa kết quả trong **Kho nội dung**.

AI chỉ tạo draft. AI không tự approval, không tự lập lịch và không tự đăng.

### Approval trước khi đăng thật

Dry-run có thể dùng với draft để kiểm tra kỹ thuật. Đăng thật yêu cầu revision hiện tại đã được duyệt.

Quy trình khuyến nghị:

1. Hoàn thiện nội dung và media.
2. Gửi revision hiện tại để duyệt.
3. Duyệt revision.
4. Không chỉnh sửa sau khi duyệt, trừ khi sẵn sàng duyệt lại.

## 5. Sử dụng Media Library

1. Mở **Media Library**.
2. Chọn **+ Upload media**.
3. Chọn ảnh hoặc video.
4. Dùng **Metadata** để nhập alt text và tag.
5. Dùng **Gắn content** để tái sử dụng asset trong một content có sẵn.

Tinix tính SHA-256 để nhận diện file trùng. Upload cùng một file nhiều lần không tạo thêm bản vật lý.

Quy tắc media:

- Không trộn video với ảnh trong cùng content.
- Một content video chỉ dùng một video theo các format đang hỗ trợ.
- Asset đang được content hoặc release snapshot sử dụng sẽ bị khóa xóa.
- Bộ lọc **Chỉ orphan** hiển thị asset chưa gắn với content nào.

## 6. Lập lịch bằng Calendar

### Xem lịch

Calendar có ba chế độ:

- **Tuần**: xem release trong bảy ngày.
- **Tháng**: xem tổng quan theo tháng.
- **Danh sách**: xem release theo trình tự thời gian.

Có thể lọc theo nền tảng và trạng thái. Nhấn vào release trên lịch để đổi thời gian; Tinix chỉ cho đổi lịch khi job chưa chạy và chưa tới commit point. Mọi lần đổi lịch được ghi audit event.

### Cấu hình posting slots

1. Chọn Page/profile/channel.
2. Nhập timezone, ví dụ `Asia/Bangkok`.
3. Nhập mỗi slot trên một dòng theo định dạng `thứ giờ`.

Quy ước thứ:

```text
0 = Thứ Hai
1 = Thứ Ba
2 = Thứ Tư
3 = Thứ Năm
4 = Thứ Sáu
5 = Thứ Bảy
6 = Chủ Nhật
```

Ví dụ:

```text
0 09:00
2 14:30
4 09:00
```

Chọn **Dùng slot kế tiếp** để Tinix tìm slot trống gần nhất. Slot engine lưu thời gian UTC, tôn trọng timezone và bỏ qua giờ không tồn tại khi chuyển DST.

### Tạo lịch phát hành

1. Chọn content.
2. Chọn account.
3. Chọn một hoặc nhiều Page/profile/channel.
4. Chọn định dạng nội dung.
5. Điền các thiết lập riêng của nền tảng.
6. Chọn ngày giờ hoặc dùng posting slot.
7. Chọn chính sách khi job bị lỡ.
8. Giữ bật **Dry-run an toàn** cho lần kiểm tra đầu tiên.
9. Chọn **Lưu lịch**.

Mỗi target tạo một release riêng. Caption, settings, media và revision được đóng băng tại thời điểm lập lịch, nên việc sửa content sau đó không làm thay đổi release đã tạo.

## 7. Dry-run và đăng thật

### Dry-run

Dry-run mở Chrome, kiểm tra phiên, vào composer, điền caption/media và chờ nút phát hành sẵn sàng. Tinix dừng trước khi click nút đăng.

Một dry-run thành công có trạng thái `dry_run_ready`.

Trước khi đăng thật, hãy kiểm tra trong Chrome:

- Đúng account và đúng target.
- Đúng caption, hashtag và CTA.
- Đúng media và thứ tự media.
- Đúng format, privacy, title hoặc playlist nếu có.
- Nút phát hành đang sẵn sàng.

### Đăng thật

Chỉ tắt **Dry-run an toàn** khi:

- Đã chạy dry-run thành công cho cùng loại nội dung.
- Revision hiện tại đã được duyệt.
- Account và target đã được kiểm tra.
- Bạn chấp nhận thao tác phát hành thật.

Tinix ghi commit point trước khi click nút phát hành. Nếu lỗi xảy ra sau commit point và không xác minh được kết quả, job chuyển thành `unknown_result` thay vì tự retry.

## 8. Phạm vi từng nền tảng

| Nền tảng | Format đang mở | Format còn khóa |
|---|---|---|
| Facebook Web | Post ảnh, nhiều ảnh hoặc video | Reel chưa được xác nhận ổn định |
| Instagram Web | Image, carousel | Reel, Story |
| TikTok Studio Web | Short video | Photo post |
| YouTube Studio Web | Video, Short | Community post |

Các adapter có trạng thái `review_required`: code và safety gate đã có, nhưng selector phải được xác nhận bằng dry-run trên giao diện thật của từng account. Giao diện mạng xã hội có thể thay đổi bất kỳ lúc nào.

## 9. Theo dõi job và xử lý sự cố

Mở **Hàng đợi & Lịch sử** để xem trạng thái, attempt, event, artifact và screenshot lỗi.

| Trạng thái | Ý nghĩa | Xử lý |
|---|---|---|
| `scheduled` | Đang chờ tới lịch | Không cần thao tác |
| `queued` | Đang chờ worker | Kiểm tra worker nếu chờ quá lâu |
| `opening_browser` | Đang mở Chrome | Chờ Chrome sẵn sàng |
| `checking_login` | Đang kiểm tra phiên | Xử lý login nếu được yêu cầu |
| `uploading` | Đang upload media | Không đóng Chrome |
| `publishing` | Composer đã sẵn sàng hoặc đang thao tác | Không kết thúc cưỡng bức tiến trình |
| `verifying` | Đã qua commit, đang xác minh | Không retry thủ công |
| `dry_run_ready` | Dry-run thành công, chưa đăng | Kiểm tra Chrome |
| `succeeded` | Đã có tín hiệu xác minh | Có thể đối soát URL/analytics |
| `temporary_failure` | Lỗi có thể retry | Chờ backoff hoặc retry an toàn |
| `permanent_failure` | Lỗi cần xử lý | Xem event/artifact trước khi retry |
| `login_required` | Chưa đăng nhập hoặc mất phiên | Đăng nhập trong Chrome rồi retry |
| `checkpoint` | CAPTCHA/2FA/checkpoint | Xử lý thủ công trong Chrome |
| `unknown_result` | Có thể đã đăng | Kiểm tra nền tảng rồi finalize |
| `cancelled` | Job đã hủy | Tạo kế hoạch mới nếu cần |

### Retry an toàn

Retry chỉ được mở cho trạng thái phù hợp trước commit point. Có thể chọn nhiều job và dùng **Xem trước** để biết job nào hợp lệ trước khi thực hiện bulk retry.

Không tạo job mới hoặc retry `unknown_result` trước khi kiểm tra bài đã xuất hiện trên nền tảng hay chưa.

### Finalize `unknown_result`

1. Mở chi tiết job.
2. Kiểm tra trực tiếp trên Page/profile/channel.
3. Nhập ghi chú xác minh.
4. Nhập URL bài đăng nếu tìm thấy.
5. Chọn xác nhận thành công hoặc thất bại.

## 10. Analytics và reconciliation

Analytics của Tinix chỉ đọc số liệu đang hiển thị trong giao diện Chrome, không gọi API analytics của nền tảng.

1. Mở **Analytics**.
2. Chọn khoảng 7, 30 hoặc 90 ngày và nền tảng.
3. Nếu release chưa có URL, chọn **Kết nối** và nhập URL bài đăng đúng nền tảng.
4. Chọn **Thu thập UI**.
5. Tinix mở Chrome của account và đọc các metric hỗ trợ từ DOM.

Mỗi metric lưu timezone, source selector và thời điểm fetch. Nếu UI không cung cấp metric, Tinix hiển thị `Không hỗ trợ / chưa có dữ liệu`, không ghi số 0 giả.

## 11. Backup, restore và maintenance

Mở **Cài đặt** để:

- Chạy database integrity check.
- Tạo backup thủ công.
- Khôi phục backup gần nhất.
- Dọn screenshot và file tạm theo retention.

Database nằm tại `data/tinix_social.db`; backup nằm tại `data/backups/`. Tinix tự tạo backup trước mỗi migration schema.

Backup database trong **Cài đặt** không chứa Chrome profile. Backup profile được tạo riêng tại từng account trong **Tài khoản & Page**.

Để sao lưu toàn bộ ứng dụng, hãy dừng Tinix rồi sao chép:

- `data/`
- `media/`
- `chrome_profiles/`
- `.env`

Các thư mục trên có thể chứa nội dung cá nhân, local API token được bảo vệ hoặc phiên đăng nhập Chrome. Không chia sẻ chúng.

## 12. Local API và CLI

Tinix có API nội bộ `/api/v1`. Đây là API điều khiển Tinix, không phải API đăng bài của mạng xã hội.

Xem token local:

```powershell
.\.venv\Scripts\python.exe -m app.cli token
```

Một số lệnh hữu ích:

```powershell
.\.venv\Scripts\python.exe -m app.cli health
.\.venv\Scripts\python.exe -m app.cli platforms
.\.venv\Scripts\python.exe -m app.cli jobs --limit 20
.\.venv\Scripts\python.exe -m app.cli releases --limit 20
```

Tạo lịch dry-run:

```powershell
.\.venv\Scripts\python.exe -m app.cli schedule `
  --content CONTENT_ID `
  --account ACCOUNT_ID `
  --targets TARGET_ID `
  --format post
```

CLI chỉ tạo đăng thật khi thêm cờ `--real`; approval hiện tại vẫn là bắt buộc. Chi tiết API và webhook nằm trong `docs/LOCAL_AUTOMATION.md`.

## 13. Checklist lần sử dụng đầu tiên

- [ ] Khởi động Tinix và kiểm tra trang Tổng quan không có cảnh báo nghiêm trọng.
- [ ] Tạo account và mở đúng Chrome profile.
- [ ] Đăng nhập thủ công, kiểm tra login và đồng bộ target.
- [ ] Tạo content và thêm media.
- [ ] Chạy dry-run với một nội dung đại diện.
- [ ] Kiểm tra composer trực tiếp trong Chrome.
- [ ] Duyệt revision hiện tại.
- [ ] Chỉ sau đó mới cân nhắc một job đăng thật có giám sát.
- [ ] Kiểm tra Release detail và URL sau khi đăng.
- [ ] Tạo một backup thủ công sau khi cấu hình hoàn tất.

## 14. Khi cần hỗ trợ

Khi báo lỗi, nên cung cấp:

- Phiên bản Tinix hiển thị ở sidebar.
- Nền tảng, format và selector version.
- Trạng thái job cuối cùng.
- Event/attempt trong Release detail.
- Screenshot artifact nếu có.
- Mô tả bước đang thực hiện khi lỗi xảy ra.

Không gửi mật khẩu, mã 2FA, cookie Chrome, nội dung file `.env` hoặc local API token.
