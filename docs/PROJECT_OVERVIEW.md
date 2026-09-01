# Tổng quan dự án để duyệt

## Mục tiêu sản phẩm

Tinix Social Studio là ứng dụng desktop-local, PC-first để quản lý account, xây dựng và duyệt nội dung, lập lịch, chạy Chrome automation có kiểm soát và lưu lịch sử phát hành bền vững. Facebook Page là MVP đầu tiên. Instagram, TikTok và YouTube hiện chỉ có khung tích hợp.

Quyết định sản phẩm: không dùng API của nền tảng để đăng. Toàn bộ publishing dùng Chrome automation và đăng nhập thủ công trong profile riêng.

## Luồng chính

```text
WebUI
  -> FastAPI routes
    -> content / approval / scheduling services
      -> repositories -> SQLite + media
      -> durable jobs -> scheduler -> worker
        -> platform publisher
          -> Chrome profile riêng -> composer -> commit point -> verifier
```

AI chỉ tạo structured draft. Approval và scheduling là bước riêng. Publisher không được tự suy diễn quyền đăng thật.

## Các khối đã có

| Khối | Vai trò | Trạng thái |
|---|---|---|
| WebUI 7 tab | Tổng quan, AI, content, lịch, job, account, settings | Có |
| Content domain | Revision, variant, media, approval | Có |
| Queue local | Scheduling, retry, cancellation, restart recovery | Có |
| Chrome manager | Profile riêng, ownership, debug port, shutdown an toàn | Có |
| Facebook adapter | Login detector, Page discovery, composer, verifier | Code xong; cần kiểm thử thật |
| Platform catalog | Capability/roadmap cho 4 nền tảng | Có |
| Instagram/TikTok/YouTube | Metadata, content variant, account/target schema, publisher stub | Scaffold |
| Backup/maintenance | SQLite backup/restore/integrity, retention | Có |

## Phần dùng chung và phần riêng

Dùng chung cho mọi nền tảng:

- Account identity và Chrome profile UUID.
- Publishing target/group schema.
- Content revision, platform variant, media và approval.
- Durable job, event, attempt, retry, cancellation và artifact.
- Commit-point rule và `unknown_result` safety rule.

Phải viết riêng theo từng nền tảng:

- Login/checkpoint detector.
- Target discovery/parser.
- Selector và Page Object.
- Composer, media constraints và verifier.
- Quy tắc URL/canonical external ID.

## Những gì scaffold hiện cho phép

- Tạo account record cho Instagram, TikTok hoặc YouTube để xem mô hình dữ liệu.
- Sinh và lưu content variant riêng qua AI/content domain.
- Hiển thị capability và milestone trong dashboard.
- Resolve publisher placeholder thành `unsupported`, không giả thành công.

Scaffold chưa cho phép sync Profile/Channel, dry-run composer thực tế, lập lịch qua form hay đăng thật.

## Các quyết định cần duyệt trước giai đoạn tiếp theo

1. Nền tảng thứ hai: Instagram, TikTok hay YouTube.
2. Format MVP đầu tiên của nền tảng đó; chỉ chọn một luồng nhỏ.
3. Có tiếp tục mô hình một Chrome profile cho mỗi account hay cho phép dùng chung session trong cùng hệ sinh thái.
4. Tiêu chí xác minh thành công tối thiểu và cách xử lý checkpoint.
5. Mức ưu tiên giữa đăng chéo cùng nội dung và tối ưu variant riêng.

Ma trận chi tiết nằm tại [PLATFORM_ARCHITECTURE.md](PLATFORM_ARCHITECTURE.md).

Kế hoạch nâng cấp sau khi benchmark Postiz nằm tại [POSTIZ_BENCHMARK_PLAN.md](POSTIZ_BENCHMARK_PLAN.md).
