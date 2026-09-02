# Tinix Profiles ZIP v1

Tinix Social Hub và Tinix FB Down dùng chung một file ZIP để chuyển toàn bộ account và Chrome profile trong một lần:

```text
Tinix-...-all-profiles.tinix-profiles.zip
├── manifest.json
└── profiles/
    ├── 0001/
    ├── 0002/
    └── ...
```

`manifest.json` có `bundle_format: "tinix-profiles"`, `format_version: 1`, `profile_content: "session-only-v1"` và mảng `accounts`. Mỗi account lưu tên, nền tảng, nguồn và đường dẫn profile tương ứng trong ZIP. Phần profile chỉ chứa trạng thái cần cho phiên đăng nhập (Local State, Preferences, cookies, Local/Session Storage, IndexedDB và WebStorage), không chứa cache hay model Chromium.

Trước khi Export, phải đóng Chrome của tất cả account. File ZIP chứa bản sao phiên đăng nhập Chrome nên cần được bảo mật. Cache, lock file, mật khẩu, mã 2FA, mật khẩu email và cookie lưu riêng trong cơ sở dữ liệu ứng dụng không được đưa vào ZIP.

Import vẫn chấp nhận thư mục `.tinix-profile` v1 cũ để tương thích ngược. FB Down chỉ nhập các profile Facebook; profile nền tảng khác trong ZIP sẽ được báo là đã bỏ qua.
