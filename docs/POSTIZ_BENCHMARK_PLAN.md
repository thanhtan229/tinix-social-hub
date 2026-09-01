# Kế hoạch nâng cấp Tinix dựa trên nghiên cứu Postiz

Ngày nghiên cứu: 2026-09-01  
Postiz upstream đã kiểm tra: `gitroomhq/postiz-app`, nhánh `main`, commit `342f7003c447c30801a1e1f10f9ead9ccddca378`.

## Kết luận điều hành

Tinix nên trở thành một **local social publishing control plane lấy cảm hứng từ Postiz**, không trở thành bản sao Postiz.

### Quyết định cố định của Tinix

- Không dùng API của mạng xã hội để đăng bài.
- Không triển khai OAuth/access token/refresh token cho publishing.
- Mọi nền tảng dùng Chrome automation, đăng nhập thủ công và profile riêng.
- API nội bộ local của Tinix vẫn có thể được xây dựng để WebUI, CLI hoặc automation điều khiển Tinix; API này không thay đổi cơ chế Chrome-only ở phía nền tảng.

Giữ nguyên:

- PC-first, một người vận hành, FastAPI + SQLite + worker local.
- Chrome profile riêng và nguyên tắc dry-run/commit point/`unknown_result`.
- Content revision, approval và dữ liệu nhạy cảm nằm trên máy.

Học từ Postiz:

- Browser provider contract có schema cấu hình và validation riêng.
- Calendar ngày/tuần/tháng/danh sách cùng posting slots.
- Một nội dung gốc, có override theo từng kênh.
- Media library dùng lại được, có metadata đầy đủ.
- Publication group, release ID/URL và analytics theo bài.
- Pending/finalize workflow cho nền tảng xử lý bất đồng bộ.
- Notifications, reconnect flow, public API và webhooks.

Chưa mang vào Tinix:

- Temporal, Redis, PostgreSQL, Docker/Kubernetes.
- Organization, team, billing, marketplace và client approval link công khai.
- Hàng chục provider cùng lúc, AI video, RSS autopost và performance plugs.

## Những phát hiện đáng áp dụng

### 1. Provider là capability contract, không chỉ là hàm `publish`

Postiz provider gom authentication/refresh, settings DTO, giới hạn nội dung, validation media, post, pending status, finalize, analytics và dynamic tools. Tinix chỉ học cách gom capability; phần OAuth/token/post API được thay bằng session detector, Page Object và thao tác Chrome. Tinix hiện có manifest năng lực và publisher interface, nhưng validation/schemas vẫn nằm rải rác và Facebook service còn đặc thù.

Khuyến nghị: mở rộng `PlatformDefinition` thành manifest tĩnh + runtime adapter, nhưng không để manifest tự mở khóa tính năng.

```text
PlatformAdapter
  manifest()
  settings_schema(format)
  validate(draft, settings, media)
  open_browser_session(account)
  detect_login(page)
  discover_targets(page, account)
  open_composer(page, release)
  prepare_preview(page, release)
  commit(page, release)
  check_ui_status(page, pending_data)
  finalize_ui(page, pending_data)
  verify_from_ui(page, result)
  collect_visible_metrics(page, target_or_release)  # optional
```

Transport được cố định là `chrome`. Mỗi mutation vẫn phải khai báo capability state, commit point, idempotency class và selector version.

### 2. Cần tách nội dung, kế hoạch phát hành và release

Tinix hiện có `content_items`, platform variants và `jobs`, nhưng thông tin phát hành còn phụ thuộc nhiều vào JSON payload. Mô hình đề xuất:

```text
ContentItem + Revision
  -> PublicationPlan (một hành động người dùng nhìn thấy)
    -> PublicationRelease (một target/kênh, settings đã đóng băng)
      -> Job / Attempt / Event / Artifact
```

Lợi ích:

- Một bài đăng chéo có group rõ ràng.
- Reschedule/cancel từng kênh hoặc cả nhóm.
- Analytics gắn đúng release.
- Không bị thay đổi ngầm khi content draft được sửa sau lúc lập lịch.

### 3. Calendar và posting slots là nâng cấp UX có giá trị cao nhất

Postiz hỗ trợ day/week/month/list, lọc theo channel, di chuyển lịch và tìm slot trống tiếp theo. Với Tinix, phiên bản đầu chỉ cần:

- Week + month + list.
- Múi giờ hiển thị rõ, lưu UTC.
- Filter theo platform/account/target/status.
- Click để tạo; kéo-thả chỉ cho release chưa chạy.
- Posting slots theo target, có `find-next-slot`.
- Phát hiện xung đột và giới hạn một account browser job tại một thời điểm.

### 4. Composer phải được sinh từ settings schema

Mỗi format có fields và validation khác nhau. Thay vì hard-code form riêng ở nhiều file, adapter cung cấp JSON-compatible schema:

- Field: type, label, required, default, options, visibility condition.
- Constraint: character count, media count/type/size/aspect/duration.
- Preview model và warning/error.
- Dynamic options lấy từ UI: playlist, privacy, Page/Profile/Channel, thumbnail, first comment.

Validation phải chạy cả frontend và backend; backend là nguồn quyết định cuối.

### 5. Workflow bất đồng bộ cần `pending -> check -> finalize`

Một số giao diện nhận upload nhưng còn xử lý video/media trên trang. Tinix nên bổ sung kết quả publisher:

- `completed`: có release ID/URL.
- `pending`: lưu opaque pending data rồi chỉ poll bằng read-only call.
- `ready_to_finalize`: mutation cuối, không auto-retry mù.
- `unconfirmed`: đã qua commit point nhưng không xác minh được.

Tinix đã có commit point và `unknown_result`; đây là nền tốt. Phần cần thêm là pending/finalize contract và concurrency limit theo provider.

### 6. Release identity là điều kiện để có analytics đáng tin

Lưu `external_release_id`, canonical URL, published time và verification method cho từng release. Nếu bài đã đăng nhưng thiếu ID, cần workflow đối soát thủ công:

1. Adapter mở trang quản lý và đọc danh sách bài gần đây nếu UI cho phép.
2. Người dùng chọn bài đúng.
3. Gắn external ID vào release.
4. Sau đó mới bật analytics.

## Khoảng cách chức năng

| Nhóm | Tinix hiện tại | Pattern từ Postiz | Ưu tiên |
|---|---|---|---|
| Provider contract | Manifest + publisher cơ bản | Schema, validation, auth, tools, analytics | P0 |
| Publication model | Content + job payload | Group + release riêng mỗi kênh | P0 |
| Calendar | Form ngày giờ + job list | Day/week/month/list + reschedule | P1 |
| Posting slots | Chưa có | Slot theo channel + next available | P1 |
| Composer | Facebook-centric | Global content + per-channel override | P1 |
| Validation/preview | Media chung, Facebook runtime | Constraint + preview theo provider/format | P1 |
| Reliability | Tốt: event/attempt/commit point | Pending/finalize + provider queues | P2 |
| Notifications | Trạng thái trong job | Reconnect, failure, missing release | P2 |
| Media library | Media gắn content | Search, reuse, alt, thumbnail, dedupe | P3 |
| Reusables | Brand/prompt | Channel sets, tags, signatures, templates | P3 |
| Instagram | Scaffold | Provider hoàn chỉnh | P4 |
| Analytics | Chưa có | Channel/post series + reconciliation | P5 |
| Public automation | API nội bộ local | Versioned API, webhooks, CLI/MCP | P6 |
| Team/SaaS | Không có | Team, org, client groups, billing | Hoãn |

## Roadmap khuyến nghị

### Giai đoạn 0 — Khóa domain contract và schema v5

Mục tiêu: tạo nền để UI và worker không phụ thuộc Facebook.

- Tạo `PlatformAdapter`/`ProviderRegistry` thống nhất.
- Thêm settings schema, constraints, selector version và idempotency class vào catalog; transport luôn là Chrome.
- Tạo `publication_plans` và `publication_releases`.
- Freeze `content_revision_id`, target, settings và media snapshot khi schedule.
- Chuyển job thành execution record tham chiếu release; vẫn đọc job cũ để tương thích.
- Chuẩn hóa error taxonomy: auth, checkpoint, validation, rate limit, transient, permanent, unconfirmed.

Gate nghiệm thu:

- Migration backup/restore và dữ liệu v4 không mất.
- Contract test chạy chung cho mọi adapter.
- Scaffold provider không thể tạo real release.
- Cùng idempotency key không tạo trùng plan/release/job.

### Giai đoạn 1 — Calendar, slot engine và universal composer

Mục tiêu: hoàn thiện trải nghiệm lập kế hoạch trước khi thêm provider thật.

- Tab Calendar: week/month/list; day là enhancement sau.
- Filter platform/account/target/status và điều hướng Today/Prev/Next.
- Posting slots theo target; endpoint tìm slot kế tiếp.
- Reschedule bằng form trước, drag-and-drop sau khi test timezone ổn định.
- Composer dùng base content + per-channel variants.
- Render settings theo schema; character/media counter và preview.
- Các hành động: draft, schedule, publish now, duplicate, cancel group/release.

Gate nghiệm thu:

- Test timezone và DST bằng UTC/local conversion.
- Không kéo được release đã qua commit point.
- Mọi validation frontend được backend kiểm tra lại.
- Calendar load theo date range, không tải toàn lịch sử.

### Giai đoạn 2 — Reliability control center

Mục tiêu: vận hành nhiều kênh mà không mất dấu kết quả.

- Pending/check/finalize state machine.
- Concurrency limit theo provider và account.
- Notification center: reconnect, checkpoint, failed, unconfirmed, completed.
- Manual retry chỉ với trạng thái an toàn; bulk retry có preview phạm vi.
- Màn release detail hợp nhất event, attempt, screenshot, commit point và URL.
- Health cảnh báo stuck jobs, disk thấp, session sắp cần can thiệp.

Gate nghiệm thu:

- Crash tại mọi bước được fault-injection test.
- Mutation không idempotent không auto-retry sau timeout.
- Restart giữ nguyên pending data và recovery decision.

### Giai đoạn 3 — Media library và tài sản tái sử dụng

Mục tiêu: giảm thao tác lặp và kiểm soát media tốt hơn.

- `media_assets`: SHA-256, MIME, size, dimensions, duration, alt, thumbnail, source.
- Search/filter, tags, orphan detection và reference count.
- Upload một lần, gắn cho nhiều content/release.
- Thumbnail timestamp và alt text theo variant.
- Channel sets, signatures, hashtag sets và content templates.
- Recurring post chỉ sau khi có rule chống lặp và ngày kết thúc.

Gate nghiệm thu:

- Dedupe không làm mất ownership/reference.
- Xóa asset đang được dùng bị chặn.
- Video vẫn xử lý streaming, không đọc toàn file vào RAM.

### Giai đoạn 4 — Provider thứ hai: Instagram theo phạm vi hẹp

Khuyến nghị chọn Instagram Feed image/carousel trước vì gần mô hình Facebook và tận dụng content/media hiện có. Đây là suy luận kiến trúc, cần xác nhận nhu cầu sản phẩm.

- Chỉ dùng Instagram Web qua Chrome profile riêng; người dùng đăng nhập thủ công.
- Feed image trước, carousel sau; Reel/Story hoãn.
- Session detector, profile discovery, constraints, selectors, preview, commit và verifier.
- HTML/DOM fixtures và Playwright mock; dry-run thủ công trước real publish.

Sau Instagram:

- TikTok Web: một video, privacy/comment/duet/stitch settings, pending upload processing.
- YouTube Studio: video/Short, title/description/privacy/playlist/thumbnail và trạng thái xử lý upload.

Không triển khai ba provider đồng thời.

### Giai đoạn 5 — Analytics và post reconciliation

Mục tiêu: đo hiệu quả mà không làm sai danh tính bài đăng.

- `release_metrics` theo metric key/date/value/source; source là dữ liệu nhìn thấy trên UI.
- Snapshot account/channel và post-level.
- Dashboard range 7/30/90 ngày, so sánh kỳ trước.
- Manual connect cho release thiếu external ID.
- Không hỗ trợ analytics phải hiển thị `unsupported`, không hiển thị số 0 giả.

Gate nghiệm thu:

- Metric có timezone, source và fetched_at.
- Re-fetch là upsert idempotent.
- Xóa/reconnect account không làm mất lịch sử release.

### Giai đoạn 6 — Local automation API, webhooks và agent surface

Mục tiêu: cho phép n8n/CLI/agent điều khiển Tinix có giới hạn.

- `/api/v1` ổn định: platforms, accounts, slots, media, content, plans, releases, jobs.
- Local API token của riêng Tinix lưu qua Windows Credential Manager/DPAPI, scope read/write/publish.
- Publish thật cần scope riêng và approval rule; không dùng token để bỏ qua duyệt.
- Webhook outbox bền vững với signature, retry và delivery log.
- CLI mỏng xuất JSON; MCP chỉ làm sau khi API contract ổn định.

Gate nghiệm thu:

- Mặc định chỉ bind localhost.
- Rate limit, request size limit, audit event và secret redaction.
- Webhook SSRF protection nếu cho phép URL do người dùng nhập.

### Giai đoạn 7 — VPS-ready có điều kiện

Chỉ bắt đầu khi PC MVP ổn định và có nhu cầu chạy liên tục:

- Tách storage, local secret store và database interfaces.
- Cho worker chạy process riêng nhưng dùng cùng durable state contract.
- PostgreSQL/object storage là adapter tùy chọn.
- Multi-user/auth/team để sau cùng.
- Chỉ cân nhắc Temporal/Redis khi SQLite worker không còn đáp ứng độ tin cậy hoặc quy mô; không dùng chỉ để giống Postiz.

## Migration dữ liệu dự kiến

Các migration phải append-only và có pre-migration backup.

| Version dự kiến | Bảng/đổi mới |
|---|---|
| v5 | `publication_plans`, `publication_releases`, job tham chiếu release |
| v6 | `channel_posting_slots`, provider settings snapshot |
| v7 | `notifications`, pending/finalize data, provider concurrency policy |
| v8 | `media_assets`, `media_tags`, content-media references |
| v9 | `release_metrics`, analytics sync checkpoints, reconciliation events |
| v10 | Local API tokens, webhook subscriptions/outbox/deliveries |

Không có OAuth token/API secret của mạng xã hội. Cookie/session do Chrome quản lý trong profile riêng và không được đọc ra để mô phỏng API. Local API token hoặc AI key dùng Windows-native protected storage khi triển khai credential store.

## Thay đổi UI đề xuất

Giữ số tab gọn, không sao chép toàn bộ navigation Postiz:

1. **Tổng quan** — health, notifications, job/release cần chú ý.
2. **Calendar** — thay “Soạn & Lập lịch”, có week/month/list.
3. **Nội dung** — content, templates, approvals và variants.
4. **Media** — thư viện tái sử dụng.
5. **Kênh** — account/target, connection state, slots, capability.
6. **Phát hành** — plans/releases/jobs/history/artifacts.
7. **Analytics** — chỉ xuất hiện khi có provider hỗ trợ.
8. **Cài đặt** — AI, dữ liệu, automation API, backup.

AI Studio có thể là action trong Nội dung thay vì một tab riêng khi universal composer hoàn chỉnh.

## Chiến lược kiểm thử

- Contract suite chung cho adapter và settings schema.
- Provider fixture tests; không gọi mạng xã hội trong CI.
- Migration tests từ mọi schema version đã phát hành.
- Calendar/timezone/property tests.
- Fault injection trước/sau commit point và trong pending/finalize.
- Media corpus test cho size/type/dimension/duration/path traversal.
- API OpenAPI snapshot + permission tests.
- Playwright smoke cho calendar/composer/release detail.
- Manual acceptance checklist riêng từng provider; real publish luôn cần phê duyệt rõ.

## Thứ tự quyết định cần chốt

1. Duyệt mô hình `Content -> Plan -> Release -> Job`.
2. Duyệt Calendar + slot engine là ưu tiên tính năng số một.
3. Duyệt chính sách một Chrome profile/account hay chia sẻ session theo hệ sinh thái.
4. Chọn Instagram Feed image là provider/format tiếp theo hay đổi ưu tiên.
5. Duyệt phạm vi API nội bộ local; giữ team/VPS ở backlog.

## Nguồn nghiên cứu chính

- Repository: https://github.com/gitroomhq/postiz-app
- Documentation index: https://docs.postiz.com/llms.txt
- Architecture: https://docs.postiz.com/self-host/architecture
- Provider guide: https://docs.postiz.com/contributing/create-provider
- Public API: https://docs.postiz.com/public-api/introduction
