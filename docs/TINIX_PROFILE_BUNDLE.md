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

`manifest.json` có `bundle_format: "tinix-profiles"`, `format_version: 1`, `profile_content: "session-only-v1"`, `contains_account_secrets: true` và mảng `accounts`. Mỗi account lưu tên, nền tảng, username/UID, email, password, secret 2FA, mật khẩu email, cookie database, nguồn và đường dẫn profile tương ứng trong ZIP. Phần profile chỉ chứa trạng thái cần cho phiên đăng nhập (Local State, Preferences, cookies, Local/Session Storage, IndexedDB và WebStorage), không chứa cache hay model Chromium.

Trước khi Export, phải đóng Chrome của tất cả account. File ZIP chứa cả bí mật account và bản sao phiên đăng nhập Chrome, không được mã hóa, nên phải được bảo quản cẩn thận. Cache, lock file, model Chromium và dữ liệu tạm không được đưa vào ZIP.

Import vẫn chấp nhận thư mục `.tinix-profile` v1 cũ để tương thích ngược. FB Down chỉ nhập các profile Facebook; profile nền tảng khác trong ZIP sẽ được báo là đã bỏ qua.
