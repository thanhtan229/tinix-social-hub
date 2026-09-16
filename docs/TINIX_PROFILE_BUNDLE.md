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

`manifest.json` có `bundle_format: "tinix-profiles"`, `format_version: 1`, `profile_content: "session-only-v1"`, `contains_account_secrets` và mảng `accounts`. Mỗi account luôn lưu tên, nền tảng, username/UID, email, nguồn và đường dẫn profile tương ứng trong ZIP. Export mặc định đặt `contains_account_secrets: false` và không ghi credential vào manifest. Khi người dùng chọn kèm credential, manifest đặt `contains_account_secrets: true`, `credential_protection: "windows_dpapi"` và chỉ lưu trường `credentials_protected`; password, secret 2FA, mật khẩu email, cookie database và recovery code không xuất hiện dạng rõ. Gói đó chỉ Import được bởi cùng tài khoản Windows đã Export. Phần profile chỉ chứa trạng thái cần cho phiên đăng nhập (Local State, Preferences, cookies, Local/Session Storage, IndexedDB và WebStorage), không chứa cache hay model Chromium.

Khi nhập mật khẩu lúc Export, Tinix tạo file `.tinix-profiles.enc` thay vì ZIP thường và mã hóa **toàn bộ** gói, gồm cả manifest lẫn dữ liệu profile, bằng AES-256-GCM. Khóa được dẫn xuất bằng PBKDF2-HMAC-SHA256; Import cần đúng mật khẩu và sẽ từ chối gói bị chỉnh sửa. Mật khẩu này không được lưu. Mã hóa gói không làm cookie Chrome vốn gắn với Windows/Chrome trở nên dùng được ở tài khoản Windows hoặc máy khác.

Trước khi Export, phải đóng Chrome của tất cả account. Bản sao phiên đăng nhập Chrome vẫn là dữ liệu nhạy cảm, kể cả khi không chọn kèm credential, nên phải được bảo quản cẩn thận. Cache, lock file, model Chromium và dữ liệu tạm không được đưa vào ZIP.

Import vẫn chấp nhận thư mục `.tinix-profile` v1 cũ để tương thích ngược. FB Down chỉ nhập các profile Facebook; profile nền tảng khác trong ZIP sẽ được báo là đã bỏ qua.
