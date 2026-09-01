# Tinix Social Studio

MVP **PC-first, VPS-ready** chạy hoàn toàn trên Windows PC: FastAPI WebUI, SQLite (WAL), durable job queue, scheduler, một local worker, AI provider tương thích OpenAI và Chrome profile riêng cho từng account.

## Chạy lần đầu

1. Cài Python 3.11+ và Google Chrome.
2. Nhấp đúp `Run.bat`.
3. Lần đầu ứng dụng tự tạo `.venv`, cài dependency, tạo `.env`, migrate database và mở `http://127.0.0.1:8765`.

Không cần Docker, PostgreSQL, Redis, Celery, HTTPS hay reverse proxy. Dữ liệu nằm trong các thư mục cạnh ứng dụng nên có thể backup bằng cách đóng app rồi sao chép `data`, `media` và `chrome_profiles`.

## Cấu hình

Sao chép/chỉnh `.env.example` thành `.env`. Mặc định WebUI chỉ bind `127.0.0.1`. API key AI chỉ nằm ở backend; không được đưa xuống frontend hay ghi vào log.

Để dùng DeepSeek, đặt:

```env
TINIX_AI_BASE_URL=https://api.deepseek.com
TINIX_AI_MODEL=deepseek-chat
TINIX_AI_API_KEY=...
```

## Dữ liệu và khôi phục

- SQLite bật WAL, foreign keys và busy timeout; mỗi thao tác mở connection riêng.
- Job trạng thái `running` còn sót sau restart được trả lại hàng đợi.
- Backup tự động chỉ tạo khi có migration schema. Backup thủ công có trên WebUI/API và luân phiên giữ 7 bản.
- Kiểm tra: `GET /api/database/integrity`.
- Khôi phục: `POST /api/database/restore` với JSON `{"name":"ten-backup.db"}` khi không có job chạy. Hệ thống tạo safety backup trước khi restore.

## Chrome

Mỗi account nhận UUID/profile ổn định tại `chrome_profiles/<profile_key>`. Ứng dụng không dùng hay thay đổi Chrome profile cá nhân. Nút Đóng chỉ tác động các tiến trình Chrome do phiên Tinix hiện tại khởi tạo.

## Trạng thái MVP

Hạ tầng PC và preview publisher đã hoạt động. `PreviewPublisher` cố ý không đăng thật lên mạng xã hội; mỗi nền tảng cần một adapter riêng trong `app/services/publishers.py` và có thể dùng Chrome manager/profile hiện có. Đây là ranh giới an toàn để phát triển publisher mà không viết lại queue, scheduler, AI hay WebUI.

## Khả năng mở rộng sau này

Khi có nhu cầu đã đo lường: thêm bảo mật WebUI/reverse proxy, đổi repository SQLite sang PostgreSQL, tách worker thành tiến trình khác và thêm cơ chế tự khởi động trên VPS. Không cần thay đổi publisher contract, AI provider, durable job model hoặc application services.

