# Kế hoạch cải tiến quản lý AI Provider và Platform Developer App

Trạng thái: Đã duyệt hướng tiếp cận, chưa triển khai mã  
Ngày lập: 2026-09-09  
Phạm vi ứng dụng: Tinix Social Hub desktop-local, Windows-first

## 1. Mục tiêu

Cho phép người dùng thêm, sửa, vô hiệu hóa, kiểm tra và lựa chọn credential ngay trong WebUI thay vì sửa `.env` rồi khởi động lại ứng dụng.

Phạm vi gồm hai nhóm độc lập:

1. **AI Provider**: Google Gemini, DeepSeek và OpenAI; hỗ trợ chọn model theo provider, test API và chọn cấu hình mặc định.
2. **Platform Developer App**: Meta (Facebook + Instagram), TikTok, Google/YouTube và X; quản lý client/app credential dùng để khởi tạo OAuth cho từng social account.

Credential của developer app và OAuth token của social account là hai tầng khác nhau:

```text
Platform Developer App (dùng chung)
  -> OAuth authorization
  -> Account Connection (riêng từng account)
  -> Official API Publisher
```

## 2. Trạng thái hiện tại cần bảo toàn

- `Settings` đang đọc một AI configuration duy nhất và YouTube OAuth client từ `.env`.
- `OpenAICompatibleProvider` đang được khởi tạo một lần trong `build_services`; thay đổi runtime hiện phải restart app.
- `SecretProtector` đã hỗ trợ Windows DPAPI.
- `account_connections` đã lưu OAuth access/refresh token được bảo vệ và không trả secret về frontend.
- `oauth_states` đã có state binding; YouTube OAuth đã hoạt động.
- `PublisherRouter` đã hỗ trợ `chrome`, `official_api` và bốn routing preference.
- Official API publisher hiện chỉ có YouTube video/Short. Facebook, Instagram, TikTok và X vẫn dùng Chrome.
- Dry-run, commit point, frozen route và `unknown_result` là các safety invariant, không được làm yếu đi.

## 3. Quyết định thiết kế

### 3.1. Không dùng `app_settings` để lưu secret

Tạo repository và bảng chuyên biệt. `app_settings.value_json` chỉ phù hợp với tùy chọn không nhạy cảm.

Mọi API key, client secret, access token và refresh token phải:

- được mã hóa bằng DPAPI trước khi ghi SQLite;
- không có plaintext fallback cho credential mới;
- không xuất hiện trong response, log, exception, backup metadata hoặc export;
- chỉ hiển thị `has_secret` và hint ngắn, ví dụ `••••a1b2`;
- được thay thế bằng thao tác ghi mới, không có endpoint đọc lại plaintext.

### 3.2. Tách AI credential khỏi AI profile/agent

Milestone đầu quản lý provider credential và model mặc định. Không gắn API key trực tiếp vào prompt template hoặc agent.

Thiết kế phải cho phép bổ sung `AI profile/agent -> provider config + model + system prompt` sau này mà không đổi cách lưu credential.

### 3.3. Tách Platform App khỏi Account Connection

- `platform_apps`: App ID/Client ID, Client Secret, redirect URI và metadata dùng chung.
- `account_connections`: token/scope/trạng thái của một social account sau OAuth.
- Một Platform App có thể phục vụ nhiều Account Connection.
- Meta App được dùng chung cho Facebook và Instagram.

### 3.4. Model lấy động, catalog nội bộ làm bộ lọc

- Backend gọi model-list endpoint bằng credential đã lưu.
- Cache danh sách để UI vẫn hiển thị lựa chọn gần nhất khi provider tạm lỗi.
- Catalog nội bộ đánh dấu capability `text`, `image`, `embedding`, `audio`, `realtime`.
- UI chỉ hiện capability Tinix đang hỗ trợ.
- Luôn có lựa chọn **Model tùy chỉnh** để không chặn model mới.
- Không hard-code model hiện hành làm nguồn sự thật duy nhất.

OpenAI, DeepSeek và Gemini đều có API liệt kê model:

- OpenAI: <https://platform.openai.com/docs/api-reference/models/list>
- DeepSeek: <https://api-docs.deepseek.com/api/list-models>
- Gemini OpenAI compatibility: <https://ai.google.dev/gemini-api/docs/openai>
- Gemini native model metadata: <https://ai.google.dev/api/models>

### 3.5. Thay đổi runtime không cần restart

Khi bắt đầu một AI request, hệ thống resolve một immutable configuration snapshot. Request đang chạy tiếp tục dùng snapshot đó; request mới dùng cấu hình vừa lưu.

Không sửa trực tiếp frozen `Settings` hoặc giữ API key động trong đó. Thêm một resolver/manager chuyên trách và đóng/evict `httpx.AsyncClient` cũ khi credential được sửa, vô hiệu hóa hoặc xóa.

### 3.6. `.env` là fallback tương thích ngược

Thứ tự ưu tiên:

1. Cấu hình active trong database.
2. Cấu hình legacy từ `.env`.
3. Trạng thái chưa cấu hình.

WebUI hiển thị cấu hình `.env` là **Legacy / chỉ đọc**. Có thể cung cấp nút “Chuyển vào kho bảo mật”; không tự động sao chép secret khi nâng cấp.

## 4. Mô hình dữ liệu đề xuất

Thêm migration kế tiếp sau version hiện tại; không sửa migration cũ.

### 4.1. `ai_provider_configs`

| Cột | Ý nghĩa |
|---|---|
| `id` | UUID |
| `provider` | `gemini`, `deepseek`, `openai` |
| `name` | Tên người dùng đặt |
| `base_url` | Endpoint preset; không cho URL tùy ý trong MVP |
| `api_key_protected` | DPAPI ciphertext |
| `key_hint` | Tối đa bốn ký tự cuối, không đủ để tái tạo key |
| `text_model` | Model text đã chọn |
| `image_model` | Model ảnh, nullable |
| `enabled` | Có được resolver sử dụng không |
| `last_test_status` | `untested`, `ok`, `failed` |
| `last_test_at` | Thời điểm test UTC |
| `last_error_code` | Mã lỗi đã chuẩn hóa, không chứa secret |
| `last_error_message` | Thông báo đã sanitize |
| `created_at`, `updated_at` | Audit timestamp |

Default text/image nên lưu bằng khóa không nhạy cảm trong `app_settings`, ví dụ `ai.default_text_config_id` và `ai.default_image_config_id`. Service phải cập nhật default và enabled trong cùng transaction, từ chối tham chiếu config không tồn tại hoặc bị tắt.

### 4.2. `ai_provider_models`

| Cột | Ý nghĩa |
|---|---|
| `config_id` | FK tới `ai_provider_configs` |
| `model_id` | ID gửi cho provider |
| `display_name` | Tên hiển thị |
| `capabilities_json` | Capability đã chuẩn hóa |
| `raw_metadata_json` | Chỉ metadata công khai cần thiết, giới hạn kích thước |
| `fetched_at` | Thời điểm làm mới |

Primary key: `(config_id, model_id)`. Xóa config phải cascade model cache.

### 4.3. `platform_apps`

| Cột | Ý nghĩa |
|---|---|
| `id` | UUID |
| `provider` | `meta`, `tiktok`, `google_youtube`, `x` |
| `name` | Tên môi trường/app |
| `client_id` | App ID, Client ID hoặc Client Key; không phải secret |
| `client_secret_protected` | DPAPI ciphertext |
| `secret_hint` | Hint đã che |
| `redirect_uri` | Callback tuyệt đối đã đăng ký với provider |
| `api_version` | Nullable; chủ yếu dùng cho Meta |
| `scopes_json` | Scope Tinix dự kiến yêu cầu |
| `enabled` | Cho phép tạo OAuth mới |
| `last_test_status` | `untested`, `syntax_ok`, `oauth_required`, `ok`, `failed` |
| `last_test_at` | Thời điểm test UTC |
| `last_error_code`, `last_error_message` | Lỗi đã sanitize |
| `created_at`, `updated_at` | Audit timestamp |

Unique tối thiểu: `(provider, name)`. Không ép mỗi provider chỉ có một app vì người dùng có thể có dev/prod app.

### 4.4. Liên kết OAuth

- Thêm nullable FK `platform_app_id` vào `account_connections`.
- Thêm nullable FK `platform_app_id` vào `oauth_states` để callback dùng đúng credential đã bắt đầu flow.
- Dữ liệu YouTube cũ từ `.env` tiếp tục hoạt động với `platform_app_id = NULL` qua legacy fallback.
- Không đổi hoặc mất token OAuth hiện có.

### 4.5. Ràng buộc xóa

- Config đang là default không được hard-delete; phải đổi default hoặc vô hiệu hóa trước.
- Platform App đang có Account Connection không được hard-delete. Cho phép disable; nếu muốn xóa phải ngắt/rebind các connection trước.
- Thao tác xóa chỉ xóa ciphertext sau khi đã xác định chính xác ID.

## 5. Backend architecture

### 5.1. Provider catalog

Thêm catalog tĩnh, không chứa secret, mô tả:

- provider ID và display name;
- endpoint preset;
- kiểu auth;
- model-list strategy;
- capability được Tinix hỗ trợ;
- trường credential cần nhập;
- default callback path và scope tối thiểu;
- trạng thái official publisher: `available`, `planned`, `unsupported`.

Catalog phải là nguồn chung cho API validation và WebUI, tránh lặp enum ở JavaScript.

### 5.2. Repository

Tạo repository riêng, dự kiến:

- `AIProviderConfigRepository`
- `PlatformAppRepository`

Repository public methods phải trả DTO đã loại toàn bộ cột `*_protected`. Chỉ method có tên rõ như `secrets(id)` mới được giải mã.

Mọi create/update/default switch phải chạy transaction. Update phân biệt:

- không gửi secret: giữ secret cũ;
- gửi secret mới không rỗng: mã hóa và thay thế;
- không hỗ trợ gửi `null` để vô tình xóa secret;
- xóa secret chỉ qua thao tác riêng nếu thực sự cần.

### 5.3. AI runtime

Refactor nhỏ theo hướng:

```text
AIConfigService
  -> resolve_text() / resolve_image()
  -> AIProviderManager
  -> concrete provider client
```

Yêu cầu:

- `AIContentStudioService` và `LocalWorker` resolve provider một lần ở đầu tác vụ.
- AIGeneration lưu đúng `provider`, `config_id` và model thực tế đã dùng.
- Nếu cấu hình đổi giữa request, request cũ không bị đổi client/header.
- Shutdown đóng mọi managed client.
- Không dùng một `AsyncClient` cũ sau khi key/base URL đổi.
- Không tự fallback sang provider khác trong MVP, trừ khi sau này có cấu hình fallback rõ ràng.

Giữ adapter OpenAI-compatible cho text để giảm thay đổi. Image model chỉ được quảng bá khi adapter thực sự hỗ trợ endpoint tương ứng; không coi Pollinations fallback là test thành công của Gemini/OpenAI credential.

### 5.4. Model discovery và test AI

Hai thao tác khác nhau:

1. **Làm mới model**: gọi model-list endpoint, chuẩn hóa và cache kết quả.
2. **Test API**: gửi một request text rất nhỏ bằng đúng model đã chọn, giới hạn output thấp, không ghi content draft.

Kết quả test chuẩn hóa:

```json
{
  "status": "ok",
  "provider": "openai",
  "model": "...",
  "latency_ms": 123,
  "tested_at": "...",
  "models_refreshed": true
}
```

Các mã lỗi tối thiểu: `authentication`, `quota`, `rate_limit`, `model_not_found`, `timeout`, `network`, `provider_unavailable`, `invalid_response`.

Không log response body thô của lỗi auth. Giới hạn timeout, số byte response, số model cache và độ dài metadata.

### 5.5. Platform App validation và OAuth

“Test App” không được báo `connected` nếu chưa hoàn tất OAuth account:

- Kiểm tra field bắt buộc, scheme/host/port callback và provider catalog.
- Nếu provider có client-credential/app-token endpoint an toàn thì gọi để xác minh app credential.
- Nếu credential chỉ có thể xác minh trong authorization-code exchange, trả `oauth_required` với hướng dẫn rõ.
- “Kết nối tài khoản” mới mở authorize URL, kiểm tra state/PKCE, đổi code lấy token và kiểm tra identity/scope.
- “Kiểm tra quyền” dùng token của Account Connection gọi identity/capability endpoint không tạo nội dung.
- “Đăng thử” không nằm trong nút test credential và luôn tuân thủ dry-run/approval hiện tại.

Callback phải match chính xác cấu hình provider. Google yêu cầu redirect URI match chính xác; TikTok Desktop hỗ trợ loopback callback và yêu cầu PKCE; X OAuth 2.0 yêu cầu callback match và PKCE. Tham khảo:

- Google OAuth: <https://developers.google.com/identity/protocols/oauth2/web-server>
- TikTok Desktop Login Kit: <https://developers.tiktok.com/docs/en/login-kit-desktop>
- TikTok token security: <https://developers.tiktok.com/docs/en/login-kit-manage-user-access-tokens>
- X OAuth 2.0: <https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code>

Meta endpoints, scopes và API version phải được đối chiếu lại với tài liệu developer chính thức tại thời điểm triển khai milestone Meta; không khóa version vào kế hoạch này.

### 5.6. Log redaction

`SecretRedactionFilter` hiện chỉ nhận key từ startup settings. Thay bằng secret registry thread-safe có thể cập nhật khi credential được thêm/sửa/xóa.

Ngoài exact-value redaction, không đưa request body, authorization header, OAuth code hoặc provider error body thô vào log.

## 6. API nội bộ đề xuất

Các endpoint WebUI nằm dưới `/api`; không mở rộng public `/api/v1` trong milestone đầu.

### 6.1. Catalog

- `GET /api/integrations/catalog`

Trả provider metadata, capability, field schema và official publisher readiness; không chứa credential.

### 6.2. AI Provider

- `GET /api/integrations/ai`
- `POST /api/integrations/ai`
- `PUT /api/integrations/ai/{config_id}`
- `DELETE /api/integrations/ai/{config_id}`
- `PUT /api/integrations/ai/defaults`
- `POST /api/integrations/ai/{config_id}/models/refresh`
- `GET /api/integrations/ai/{config_id}/models`
- `POST /api/integrations/ai/{config_id}/test`
- `POST /api/integrations/ai/import-legacy` nếu thực hiện one-click migration

Test có thể nhận model override tạm thời nhưng không nhận lại plaintext key từ database. Test credential chưa lưu có thể dùng endpoint preview riêng hoặc lưu ở trạng thái `untested` trước; ưu tiên luồng **Lưu -> Test** để giảm nguy cơ secret xuất hiện trong nhiều request.

### 6.3. Platform App

- `GET /api/integrations/platform-apps`
- `POST /api/integrations/platform-apps`
- `PUT /api/integrations/platform-apps/{app_id}`
- `DELETE /api/integrations/platform-apps/{app_id}`
- `POST /api/integrations/platform-apps/{app_id}/test`

Điều chỉnh endpoint OAuth hiện tại:

- `POST /api/accounts/{account_id}/connections/{provider}/authorize` nhận `platform_app_id` rõ ràng, hoặc tự chọn khi provider chỉ có một app enabled.
- Callback resolve `platform_app_id` từ OAuth state, không tin ID từ query do client gửi lại.
- Connection response bổ sung public `platform_app_id`, `platform_app_name`, scope status và expiry status.

Tất cả response CRUD phải đi qua public serializer và có test chứng minh ciphertext/plaintext không xuất hiện.

## 7. WebUI/UX

Trong tab **Cài đặt & Dữ liệu**, thêm khu vực **Tích hợp & API**; nên tách JavaScript sang `app/static/js/integrations.js` thay vì làm `settings.js` quá lớn.

### 7.1. AI Providers

Mỗi card hiển thị:

- provider, tên cấu hình;
- enabled/default text/default image;
- API key masked;
- text model và image model;
- trạng thái/lần test/latency gần nhất;
- nút `Test API`, `Làm mới model`, `Sửa`, `Vô hiệu hóa`, `Xóa`.

Form:

- provider dropdown;
- tên cấu hình;
- API key dạng password và nút mắt chỉ áp dụng cho giá trị đang nhập;
- base URL preset ở chế độ chỉ đọc trong MVP;
- dropdown text/image model;
- tùy chọn model tùy chỉnh;
- thông báo chi phí cho test image nếu sau này thêm nút riêng.

Không đưa embedding/audio/realtime model vào dropdown text.

### 7.2. Platform Developer Apps

Card hiển thị:

- Meta, TikTok, Google/YouTube hoặc X;
- tên app/môi trường;
- Client/App ID;
- Client Secret masked;
- Redirect URI có nút copy;
- scope dự kiến;
- trạng thái cấu hình và số account đang kết nối;
- readiness của official publisher.

Nếu official publisher chưa có, UI phải ghi rõ: **Credential đã lưu; Tinix chưa hỗ trợ đăng official API cho nền tảng này**.

### 7.3. Account UI

- Nút `Kết nối API` mở lựa chọn Platform App phù hợp nếu có nhiều app.
- Sau OAuth hiển thị app đã dùng, scope thiếu, expiry và `Kết nối lại`.
- Chỉ cho chọn `official_api_preferred`/`official_api_only` khi có adapter và connection đủ điều kiện; hoặc vẫn cho lưu nhưng hiển thị warning rõ và router tiếp tục trả unsupported an toàn.
- Chrome routing hiện tại vẫn là mặc định.

### 7.4. Accessibility và trạng thái thao tác

- Disable nút khi request đang chạy.
- Có `role=status`/`aria-live` cho kết quả test.
- Không chỉ dùng màu để biểu diễn trạng thái.
- Confirm trước khi xóa/disable config đang được dùng.

## 8. Lộ trình triển khai cho subagent

Mỗi milestone phải hoàn tất test và review diff trước khi chuyển milestone tiếp theo. Không giao nhiều subagent sửa đồng thời `database.py`, `main.py`, `routes.py` hoặc `index.html` vì repository đang có thay đổi chưa commit.

### Milestone 0 — Baseline và hợp đồng

1. Ghi nhận `git status` và không sửa/revert thay đổi ngoài phạm vi.
2. Chạy targeted baseline hiện có: AI provider, API, migration, provider connection, routing.
3. Chốt provider catalog DTO, error codes và public serializer bằng test trước.
4. Xác nhận version migration hiện tại trước khi chọn version mới; không giả định luôn là 15 nếu nhánh đã đổi.

Điều kiện hoàn tất: baseline failures được ghi nhận, schema/API contract được thống nhất, chưa thay runtime behavior.

### Milestone 1 — Secure credential foundation

1. Thêm migration cho `ai_provider_configs`, `ai_provider_models`, `platform_apps` và FK cần thiết.
2. Thêm repositories và strict DPAPI methods.
3. Thêm public serialization, secret replacement semantics và delete guards.
4. Thêm dynamic secret redaction registry.
5. Thêm unit tests migration từ v1/latest, CRUD, transaction, DPAPI failure và no-secret response.

Điều kiện hoàn tất: có thể lưu/đọc metadata credential an toàn nhưng chưa chuyển AI runtime.

### Milestone 2 — AI management end-to-end

1. Thêm AI config service, provider manager/resolver và `.env` fallback.
2. Thêm model discovery/cache cho Gemini, DeepSeek và OpenAI.
3. Thêm test request nhỏ và error normalization.
4. Chuyển `AIContentStudioService` và worker sang immutable resolved config.
5. Ghi provider/config/model thực tế vào AI generation audit; nếu cần schema bổ sung thì dùng migration kế tiếp, không sửa migration Milestone 1 đã phát hành.
6. Thêm API CRUD/default/model/test.
7. Thêm WebUI AI cards/form/dropdown/test.
8. Cập nhật health để phản ánh active DB config hoặc legacy fallback.

Điều kiện hoàn tất:

- thêm key và chọn model hoàn toàn từ UI;
- test phân biệt auth/quota/model/network;
- cấu hình mới có hiệu lực không restart;
- không có secret trong API/log;
- `.env` cũ vẫn hoạt động.

### Milestone 3 — Platform App management và chuyển YouTube

1. Thêm Platform App CRUD/test UI/API.
2. Chuyển YouTube authorize/token refresh sang resolve Google/YouTube Platform App.
3. Bind OAuth state và connection với `platform_app_id`.
4. Giữ legacy `.env` fallback cho YouTube.
5. Hỗ trợ nhiều Google OAuth client và lựa chọn client khi connect account.
6. Test callback dùng đúng app, token refresh đúng secret và không làm mất connection cũ.

Điều kiện hoàn tất: YouTube official API hoạt động không cần sửa `.env`; existing connection và Chrome fallback không bị hỏng.

### Milestone 4 — Meta official API

Tách thành task riêng sau khi xác minh app review/scope/version hiện hành:

1. Meta OAuth cho Facebook/Instagram và token lifecycle.
2. Identity/target discovery cho Page/Instagram Business account.
3. Capability matrix theo content format.
4. Official publisher adapter, dry-run, commit point, request ID và verifier.
5. Router chỉ coi API ready khi app, connection, scope, target và format đều đủ.

Không mở Instagram personal account hoặc format chưa có endpoint/permission phù hợp.

### Milestone 5 — TikTok official API

1. Desktop Login Kit với loopback redirect và PKCE S256.
2. Token refresh, scope/status validation.
3. Content Posting API capability/dry-run/direct-post hoặc upload flow đúng app approval.
4. Commit/unknown-result safety và target reconciliation.

Không coi client access token là user posting token.

### Milestone 6 — X official API

1. OAuth 2.0 Authorization Code + PKCE cho user context.
2. Scope tối thiểu gồm read/write/offline theo capability thực tế.
3. Media upload và post adapter theo API entitlement.
4. Rate-limit/error normalization và routing safety.

Không coi app-only bearer token là đủ để đăng thay người dùng.

## 9. File dự kiến bị tác động

Tên file mới có thể điều chỉnh theo convention hiện hành, nhưng phạm vi dự kiến:

- `app/db/database.py`
- `app/db/provider_repositories.py` hoặc repository mới dành cho integrations
- `app/core/secrets.py`
- `app/core/logging.py`
- `app/core/config.py`
- `app/services/ai.py`
- `app/services/ai_studio.py`
- `app/services/provider_accounts.py`
- `app/services/publisher_router.py`
- `app/main.py`
- `app/api/routes.py` hoặc `app/api/integrations.py` mới
- `app/static/index.html`
- `app/static/js/settings.js`
- `app/static/js/integrations.js` mới
- `app/static/js/accounts.js`
- `app/static/js/main.js`
- `app/static/style.css`
- `.env.example`, `README.md`, `docs/HUONG_DAN_SU_DUNG.md`
- tests repository/API/AI/OAuth/frontend tương ứng

Ưu tiên thêm module mới và chỉnh wiring tối thiểu, không dồn toàn bộ logic vào `routes.py` hoặc `settings.js`.

## 10. Kiểm thử bắt buộc

### Unit/repository

- migration fresh database và upgrade database cũ không mất dữ liệu;
- migration tạo pre-migration backup và integrity vẫn OK;
- ciphertext khác plaintext;
- public DTO không chứa secret/protected fields;
- update không gửi secret giữ nguyên ciphertext;
- rotate secret thay ciphertext và invalidates client cache;
- delete/default/reference guards;
- model normalization/filter/cache/stale fallback;
- redirect URI/provider validation;
- OAuth state bound đúng Platform App và chỉ consume một lần.

### HTTP service với `httpx.MockTransport`

- model list ba AI provider;
- successful minimal completion test;
- 401/403, 404, 429, quota, timeout, network và malformed JSON;
- response-size/model-count limit;
- OAuth token exchange/refresh không log secret;
- credential đổi trong lúc request không thay snapshot request đang chạy.

### API

- CRUD/default/test happy path;
- validation 422 và reference conflict 409;
- mọi list/detail response không lộ key/secret;
- health phản ánh DB config và `.env` fallback;
- mutating endpoints vẫn đi qua application lock hiện có.

### Frontend

- tạo/sửa cấu hình mà không render lại secret;
- provider đổi thì schema/model list đổi;
- custom model hoạt động;
- loading/error/success state của test;
- nhiều Platform App và chọn app khi OAuth;
- warning official publisher chưa hỗ trợ;
- keyboard focus, label và `aria-live` cơ bản.

### Regression

Chạy ít nhất:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_ai_provider -v
.\.venv\Scripts\python.exe -m unittest tests.test_provider_connections -v
.\.venv\Scripts\python.exe -m unittest tests.test_publisher_routing -v
.\.venv\Scripts\python.exe -m unittest tests.test_api -v
.\.venv\Scripts\python.exe -m unittest tests.test_state_and_migrations -v
.\.venv\Scripts\python.exe -m unittest tests.test_frontend_playwright -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Playwright có thể skip nếu Chrome không có; không được thay test thật bằng việc chỉ đọc code.

Không thực hiện OAuth hoặc đăng bài thật trong automated tests. Kiểm thử thực tế dùng account test, dry-run trước và ghi rõ thao tác nào có thể tạo dữ liệu/chi phí.

## 11. Tiêu chí nghiệm thu chung

- Người dùng không cần sửa `.env` để thêm mới AI hoặc YouTube app credential.
- Gemini, DeepSeek, OpenAI có dropdown model động, custom fallback và test thật.
- Key/secret/token được mã hóa DPAPI và không lộ qua frontend/API/log.
- Cấu hình AI mới có hiệu lực không restart.
- Platform App và Account Connection được biểu diễn tách biệt.
- Credential test không bị hiểu nhầm là account đã OAuth hoặc publisher đã sẵn sàng.
- YouTube official API vẫn hoạt động; Chrome transport và routing safety không đổi.
- Facebook/Instagram/TikTok/X chỉ được đánh dấu official-ready khi adapter, OAuth, scope và capability thực sự hoàn tất.
- Toàn bộ regression suite liên quan pass; failure có sẵn từ baseline được báo riêng.

## 12. Hướng dẫn giao việc cho subagent

Nên giao từng milestone theo thứ tự và yêu cầu subagent:

1. Đọc `AGENTS.md`, tài liệu này và các file trực tiếp liên quan trước khi sửa.
2. Kiểm tra `git status`; bảo toàn mọi thay đổi người dùng có sẵn.
3. Không sửa rộng ngoài milestone hiện tại và không thêm dependency.
4. Không triển khai official publisher của nền tảng tiếp theo khi milestone nền tảng/credential trước chưa pass.
5. Báo rõ file đã đổi, migration version, test đã chạy và failure còn lại.
6. Dừng sau hai hướng sửa suy đoán thất bại và chuyển sang chẩn đoán dựa trên evidence theo `AGENTS.md`.

Điểm chia việc an toàn nhất là theo milestone, không chia theo frontend/backend chạy song song trên cùng worktree vì các file wiring và schema có mức xung đột cao.
