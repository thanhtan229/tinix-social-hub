# Kế hoạch áp dụng các phần còn phù hợp của Postiz vào Tinix

Ngày lập: 28-09-2026.  
Trạng thái: **Facebook một ảnh, album hai/ba ảnh, video Page thường và Reel đã live-verified trên Page Tinix; Instagram one-photo publisher đã triển khai/test fixture, chờ R2 và OAuth live acceptance.**  
Cơ sở: `RESEARCH_postiz.md`, mã nguồn trong working tree hiện tại, các kết quả triển khai ghi trong `PLAN.md` và quy tắc dự án do người dùng cung cấp.

## 1. Mục tiêu và phương án đề xuất

Hoàn thiện quy trình **soạn một nội dung → chọn nhiều Page/kênh → xem trước và kiểm tra từng đích → duyệt → tạo lịch một lần → theo dõi kết quả riêng từng đích**.

Chọn hướng nâng cấp composer và lập lịch đa đích trên kiến trúc hiện có. Đây là khoảng trống sử dụng lớn nhất còn lại trong nghiên cứu. Không cần xây lại content, media library, provider catalog, calendar hay hệ thống jobs.

Lộ trình đề xuất:

1. Chốt quy tắc nội dung kế thừa, revision và tạo lịch nguyên tử.
2. Hoàn thiện luồng nhiều Facebook Page, bao gồm Page thuộc nhiều account.
3. Mở rộng cùng luồng sang những định dạng/nền tảng đã có adapter phù hợp.
4. Bổ sung bộ Page/kênh lưu sẵn, chữ ký, chi tiết kết quả và thao tác calendar thuận tiện.
5. Phát triển API media hoặc analytics tiếp theo theo nhu cầu thực tế.

**Ưu tiên đã được người dùng xác nhận:** soạn và lên lịch một bài cho nhiều Facebook Page trước, sau đó mở rộng đa nền tảng. Thiết kế lõi dùng target cụ thể để tránh phải viết lại khi mở rộng. Facebook media API không phải điều kiện hoàn thành đợt đầu; sử dụng những format/transport hiện có và đủ điều kiện.

Tài liệu này theo dõi việc triển khai lần lượt theo từng giai đoạn. Việc triển khai tính năng không tự cho phép đăng bài thật; live publish chỉ làm khi có chỉ thị rõ về nội dung và đích.

## 2. Hiện trạng đã đối chiếu và những nhận định cần cập nhật

| Hạng mục | Hiện trạng trong mã/tài liệu dự án | Hệ quả đối với kế hoạch |
|---|---|---|
| Domain | Có Content → Publication Plan → Release → Job, revision, approval và snapshot | Mở rộng đường tạo kế hoạch; giữ mô hình vận hành hiện tại |
| Lập lịch | `ScheduleBody` và `SchedulingService.schedule()` nhận một `account_id`; nhiều target phải thuộc account đó | Multi-account cần xử lý backend, không chỉ thêm checkbox trên UI |
| Nội dung | UI chính là `posts.js`, có tab variants theo platform; nội dung chung khi lưu được lấy từ variant chính | Cần nội dung chung độc lập và chế độ kế thừa rõ; không tạo lại editor từ đầu |
| Media | `posts.js` đã có chọn asset từ Media Library trong form và preview media | Nâng chọn nhiều asset, thứ tự và tính tương thích; không lấy `media.js` cũ làm hiện trạng UI chính |
| Kế thừa | Scheduler đang dùng fallback theo giá trị có nội dung, như `variant.caption or content.caption` | Phải phân biệt kế thừa với chủ động để rỗng khi giới thiệu chế độ mới |
| Ghi kế hoạch | Tạo plan, release, job và liên kết hiện qua các thao tác repository riêng | Không được giả định gọi scheduler nhiều lần sẽ tạo được một batch nguyên tử |
| Validation | Schema có giới hạn caption, loại/số media và settings; chưa có constraint media đầy đủ | Bổ sung có chọn lọc, theo platform + format + transport thực tế |
| Facebook API | Có publisher text/photo/album/video/Reel, OAuth/System User và nhiều Page binding; một ảnh, album hai/ba ảnh, video Page thường và Reel đã thử live trên Page Tinix | Nghiên cứu nói YouTube là API duy nhất đã cũ; không đưa Facebook OAuth/multi-Page thành việc xây mới |
| YouTube analytics | Có API metrics và scheduler cập nhật tùy chọn | Không lập lại hạng mục xây analytics từ đầu; scheduler hiện tập trung YouTube |
| Calendar | Có tuần/tháng/list và posting slots; đổi lịch dùng prompt | Thay bằng dialog trước; day view và kéo-thả làm sau |
| Kết quả/đối soát | Có job detail, events/artifacts, URL connect và metrics; trải nghiệm còn phân tán | Gom thành chi tiết release dễ đọc, tận dụng API và dữ liệu đang có |

Đối chiếu này là phân tích mã và nhật ký dự án, không phải nghiệm thu live mới. Không suy rộng một lần nghiệm thu Facebook text thành việc mọi Page, định dạng hoặc Chrome adapter đều đã ổn định.

## 3. Phạm vi và các lựa chọn

| Phương án | Khi phù hợp | Đánh giá |
|---|---|---|
| A. Composer và lịch đa đích | Thường lặp lại cùng bài trên nhiều Page/kênh | **Đã chọn: nhiều Facebook Page trước**; tận dụng nền tảng hiện tại, giảm thao tác thường ngày |
| B. Facebook media API trước | Nhu cầu chính là ảnh/video Facebook và Chrome đang cản trở vận hành | Đổi thứ tự nếu người dùng xác nhận; làm ảnh trước, video thành mốc riêng |
| C. Toàn bộ composer + API + calendar + analytics cùng lúc | Chỉ phù hợp khi có yêu cầu và nguồn lực rõ cho toàn bộ phạm vi | Không chọn cho đợt đầu vì khó cô lập lỗi và nghiệm thu |

### 3.1. Phạm vi cốt lõi

- Chọn target qua nhiều account; cấu hình và kiểm tra từng đích.
- Nội dung chung, variant theo platform, override theo target.
- Lưu bản nháp, tải lại, nhân bản và revision giữ đúng nội dung người dùng đã chọn.
- Preview dùng cùng kết quả resolve/validation với backend.
- Tạo một kế hoạch gồm nhiều release/job trong một transaction.
- Duy trì approval, route snapshot, dry-run evidence, idempotency và xử lý `unknown_result`.
- Kết quả hiển thị riêng từng đích, kể cả khi chỉ một phần đăng thành công.

### 3.2. Phạm vi nối tiếp

- Bộ Page/kênh lưu sẵn và chữ ký nội dung.
- Media picker chọn nhiều asset và kiểm tra tương thích.
- Chi tiết release, đối soát và liên kết metrics.
- Dialog đổi lịch, lọc theo account/target, day/slot view; kéo-thả sau khi quy tắc thời gian ổn định.
- Constraint media và khả năng API bổ sung theo nhu cầu đã xác nhận.

### 3.3. Ngoài phạm vi hiện tại

- Team/organization, SaaS, billing, public review link.
- Temporal, Redis, Postgres, Docker, nhiều worker hoặc triển khai cloud.
- Provider mới chỉ để tăng số lượng, RSS tự đăng, MCP hay automation bỏ qua duyệt.
- Viết lại frontend bằng framework mới, đổi authentication hoặc refactor diện rộng.
- Sao chép mã Postiz; kế hoạch học luồng sản phẩm và tự triển khai bằng cấu trúc Tinix.

## 4. Quy tắc sản phẩm cần giữ nhất quán

### 4.1. Chọn Page/kênh

Đơn vị lựa chọn là `publishing_target`, không phải account hay tên hiển thị. Mỗi dòng cho biết tên Page/kênh, platform, account quản lý, định dạng và phương thức đăng dự kiến. Hai Page trùng tên vẫn phân biệt được bằng account và định danh thích hợp.

Một target xuất hiện tối đa một lần trong cùng kế hoạch. Không tự chọn thêm Page khi đồng bộ account hoặc áp dụng preset. Target bị ngắt/tắt/mất quyền hiện lỗi rõ, không âm thầm bỏ khỏi batch.

### 4.2. Nội dung chung và nội dung riêng

Thứ tự resolve: **Global → platform → target**. UI mặc định đơn giản: tab Nội dung chung và các Page/kênh đã chọn; tầng platform được dùng khi người dùng cần dùng chung một bản cho cùng nền tảng và để tương thích variants hiện có.

- Mỗi tầng có chế độ rõ: kế thừa hoặc tùy chỉnh. Khi tách, khởi tạo bản riêng từ nội dung hiệu lực đang thấy.
- Sửa Global chỉ lan tới phần còn kế thừa. Sửa một target không đổi target khác.
- Đợt đầu tách cả nhóm nội dung văn bản, tránh nhiều công tắc kế thừa riêng từng trường. Media có chế độ dùng chung/chọn riêng khi triển khai đa định dạng.
- Caption rỗng, danh sách hashtag rỗng và CTA bị xóa là giá trị có chủ đích ở chế độ tùy chỉnh; backend không tự lấy lại từ bản chung. Nếu định dạng không cho phép nội dung đó thì báo lỗi validation.
- Quay về dùng chung phải cho biết bản riêng sẽ bị bỏ và yêu cầu xác nhận khi có dữ liệu khác biệt.
- Settings như tiêu đề YouTube, privacy hoặc format thuộc đích tương ứng. Chỉ hiển thị/cho dùng trường mà adapter thực sự xử lý; không coi có field trong form là đã có khả năng publish.
- Bài cũ không có cấu hình kế thừa mới tiếp tục dùng cách resolve cũ. Khi chuyển sang composer mới, dựng bản hiệu lực trước rồi cho người dùng lưu thành revision mới; không tự đổi ý nghĩa bài hoặc release cũ.

### 4.3. Media và lưu bản nháp

- Chọn asset theo ID, giữ thứ tự và dùng cơ chế reference hiện có; không copy file cho từng đích.
- Media riêng cho target phải có reference được quản lý, không chỉ giấu ID trong JSON khiến chức năng dọn orphan xóa nhầm.
- Chọn/bỏ media trong editor được giữ tạm tới khi lưu; hủy editor không âm thầm thay nội dung đang lưu.
- Lưu bản nháp chỉ báo thành công khi nội dung và các liên kết media cần thiết đã lưu đủ. Khi lỗi, giữ dữ liệu đang nhập và nêu phần cần xử lý.
- Preview hiển thị media thực tế của đích. Không tự crop, chuyển codec hoặc tạo video để vượt validation trong đợt này.

### 4.4. Duyệt và snapshot

Nội dung chung, variants, target overrides và lựa chọn media ảnh hưởng bài đăng phải nằm trong revision được duyệt. Không nhận override mới trực tiếp từ màn lập lịch rồi dùng approval của nội dung cũ.

Màn duyệt hiển thị bản hiệu lực của các đích. Sửa nội dung hoặc settings làm thay đổi bài đăng phải được lưu/kiểm tra theo quy tắc revision đã chốt, và không được dùng approval cũ để xuất bản bản mới. Đổi giờ thuần túy đi qua quy tắc reschedule hiện có, không tạo lại nội dung.

Khi tạo kế hoạch, đóng băng nội dung, media, settings, target identity, route và revision cho từng release. Sửa draft về sau không thay snapshot đã tạo. Việc worker tiếp tục hay chặn job khi approval/revision thay đổi phải giữ đúng policy đang có và có test hồi quy; không tự nới điều kiện duyệt.

### 4.5. Validation và tạo lịch

- Kiểm tra theo tổ hợp platform + format + transport + account/target binding. Facebook Chrome, Facebook API ảnh/video/Reel có contract riêng; không suy rộng một transport sang transport khác.
- Preflight trả kết quả cho mọi đích, gồm lỗi cần sửa, cảnh báo, route và nội dung hiệu lực. Validation thuần không tạo job và không đăng bài.
- Mặc định có lỗi ở bất kỳ đích được chọn thì chưa tạo lịch cho cả nhóm. Người dùng có thể sửa hoặc bỏ chọn đích lỗi rồi kiểm tra lại; không tự tạo một phần.
- Preview là mô phỏng để rà nội dung, không cam kết giống giao diện mạng xã hội từng pixel. Backend là nguồn quyết định validation.
- Tạo kế hoạch thành công là ghi DB nguyên tử. Khi jobs chạy và gọi nền tảng bên ngoài, kết quả độc lập: không thể rollback bài đã đăng ở Page A vì Page B thất bại.
- Dry-run là chế độ mặc định; đăng thật cần approval và evidence đúng route như policy hiện tại.
- Giữ concurrency/khóa Chrome profile của worker. Đăng nhiều đích không mặc định đồng nghĩa chạy đồng thời.
- Job đã qua commit point hoặc có `unknown_result` cần đối soát, không retry cả nhóm hay tự đổi transport.

### 4.6. Thời gian và thao tác lặp

Đợt đầu dùng một giờ chung, có thể chỉnh riêng từng đích trước khi xác nhận. Hiển thị timezone rõ ràng; lưu thời điểm chuẩn UTC và giữ timezone phục vụ hiển thị/audit. Giữ posting slots và missed policy hiện có.

Không coi slot là quyền giữ chỗ tuyệt đối nếu chưa có cơ chế reservation. Khi lấy slot cho nhiều target phải tính riêng theo target. Delay/random delay nếu sử dụng phải được xác định một lần cho một yêu cầu và giữ ổn định khi gửi lại; không tính giờ mới ở mỗi retry.

## 5. Thiết kế kỹ thuật đề xuất

### 5.1. Một đường resolve và kiểm tra dùng chung

Tách phần chuẩn bị publication trong `SchedulingService` ở mức cần thiết: đọc revision, resolve nội dung/media/settings, xác định route, validation và kiểm tra evidence. Composer preflight và thao tác tạo lịch dùng cùng kết quả chuẩn hóa.

Không để frontend tự tính một bản caption còn worker dùng một bản khác. Frontend có thể kiểm tra nhanh khi gõ, nhưng trước khi duyệt/tạo lịch phải dùng kết quả authoritative từ backend.

### 5.2. Lưu cấu hình composer và tương thích dữ liệu

Mã hiện tại lưu variants theo platform; chưa có nơi lưu đầy đủ chế độ kế thừa và bản riêng theo target. Không dùng localStorage làm dữ liệu chính, không nhét target ID vào khóa platform để né mô hình dữ liệu.

**Phương án ưu tiên để khảo sát ở M0:** thêm một trường JSON có version trên content để lưu mode và target overrides; tiếp tục dùng bảng variants/media hiện có, đưa cấu hình mới vào revision snapshot. Các media được chọn phải nằm trong hệ thống reference chính thức. Chỉ tách bảng target variants nếu yêu cầu truy vấn hoặc ràng buộc không thể đáp ứng gọn bằng phương án này.

Đây là đề xuất migration tối thiểu khi thực sự cần cho chức năng mới, không phải thay schema trong lượt lập kế hoạch. M0 phải chốt hình dạng dữ liệu, defaults cho bản cũ, duplicate/restore, backup và kiểm tra migration trước khi triển khai. Nếu phạm vi đợt đầu chỉ là chọn nhiều đích với nội dung hiện có, hoãn phần migration override và giao thành mốc riêng; không báo đã hoàn thành Global/target override.

Đặc biệt rà `_snapshot()` trong `content_repositories.py`: hiện snapshot có content và variants; cần bảo đảm media hiệu lực và cấu hình mới cũng được version/duyệt đúng. Không viết lại snapshot lịch sử hay suy đoán media cũ khi thiếu bằng chứng.

### 5.3. Hợp đồng multi-target

Giữ request `/api/schedules` một account hiện tại và hành vi của client cũ. Bổ sung hợp đồng nội bộ cho batch, tên route chốt theo cấu trúc API ở M0, gồm:

- Content ID và revision mong đợi.
- Danh sách target ID; format, settings, thời gian và routing preference tương ứng.
- Chế độ dry-run, missed policy và mã yêu cầu dùng lại khi retry.
- Dấu kiểm tra bản preflight để phát hiện nội dung/route đã đổi trước khi tạo lịch.

Backend tự xác định account từ target và kiểm tra ownership; không tin cặp account/target do client gửi. Nội dung hiệu lực phải lấy từ revision đã lưu. Phản hồi trả plan cùng các release/job và lỗi có cấu trúc theo đích để UI chỉ đúng chỗ cần sửa.

Chỉ thêm trường/route cần thiết, không thay hoặc mở rộng quyền của local API v1, CLI, webhook hay authentication ngoài phạm vi. Client cũ không gửi trường mới phải tiếp tục hoạt động và không xóa mất cấu hình mới khi cập nhật các trường cũ.

### 5.4. Transaction và chống tạo trùng

Không gọi `schedule()` cũ lần lượt cho từng account rồi coi đó là một kế hoạch. Chuẩn bị tất cả đích trước; tại bước ghi, dùng cùng một connection/transaction cho plan, releases, jobs và liên kết.

1. Đọc và resolve dữ liệu, kiểm tra media/route ngoài transaction dài.
2. Mở transaction ghi; kiểm tra lại revision, approval, target status và fingerprint connection/binding đã dùng.
3. Nếu có thay đổi, trả yêu cầu kiểm tra lại; không ghi batch một phần.
4. Tạo toàn bộ bản ghi hoặc rollback toàn bộ. Worker chỉ nhìn thấy jobs sau commit.
5. Thông báo worker và side effect nội bộ sau commit. Không gọi mạng xã hội hoặc xử lý file dài trong transaction.

Idempotency gắn với một ý định tạo lịch, revision và tập đích đã chuẩn hóa. Cùng mã yêu cầu/cùng payload trả lại cùng plan; cùng mã nhưng payload khác bị từ chối. Bấm đúp, timeout sau commit và tải lại để gửi lại không sinh thêm jobs. Người dùng chủ động tạo lần đăng mới có ý định mới theo policy hiện có. Bài cũ và API cũ giữ semantics chống trùng đã có.

Với fingerprint, dùng cơ chế revision/route hiện có và kiểm tra ràng buộc target–Page; không sao chép token vào payload, preflight, log hoặc browser storage.

### 5.5. Phạm vi file dự kiến

| Nhóm | Vùng mã cần xem/sửa khi triển khai |
|---|---|
| Composer chính | `app/static/js/posts.js`, `app/static/index.html`, `app/static/style.css` |
| Lập lịch và calendar | `app/static/js/compose.js`, `app/services/scheduling.py`, `app/api/content.py` |
| Revision và batch persistence | `app/db/content_repositories.py`, `app/db/publication_repositories.py`, repository jobs trong `app/db/repositories.py`; `app/db/database.py` chỉ nếu migration cần thiết |
| Capability/validation | `app/platforms/catalog.py`, `app/platforms/validation.py`, `app/services/publisher_router.py` |
| Theo dõi release | `app/static/js/jobs.js`, `app/static/js/analytics.js`, `app/api/routes.py` |
| Kiểm thử | Các suite content/scheduling, API, state/migration, reliability, routing, Meta, YouTube và frontend hiện có |

Đây là bản đồ ảnh hưởng, không phải danh sách bắt buộc sửa toàn bộ. Không chỉnh `content.js`/`media.js` cũ chỉ vì nghiên cứu tham chiếu chúng; trước hết xác định entrypoint đang được `main.js` dùng. Working tree đang có nhiều thay đổi từ các công việc trước, phải bảo toàn và phân biệt với phần triển khai mới.

## 6. Các mốc triển khai và tiêu chí hoàn thành

### M0 — Chốt contract và kiểm tra nền tảng

- Áp dụng ưu tiên đã chốt: nhiều Facebook Page trước; chọn account/target và format thực tế cho nghiệm thu đợt đầu khi cần.
- Chốt mode kế thừa, cấu hình persist, phạm vi approval, semantics client cũ và danh sách format/transport của đợt đầu.
- Ghi nhận baseline bằng các test liên quan; phân biệt lỗi có sẵn với lỗi của thay đổi.
- Kiểm tra readiness theo account/target/format đang dùng. Không yêu cầu nghiệm thu cả năm platform trước khi hoàn thiện luồng Page.
- Chốt preflight/commit, transaction chung và idempotency. Cập nhật quyết định vào chính tài liệu này.

**Đạt khi:** có hợp đồng đủ để viết test hành vi, phương án dữ liệu tối thiểu và danh sách khả năng thực sự đưa vào UI. Chưa cần đăng bài thật.

### M1 — Nội dung chung và bản riêng có revision

- Bổ sung Global độc lập với variant chính; tận dụng editor hiện có.
- Thêm mode kế thừa/tùy chỉnh theo platform và target, cùng resolver backend.
- Persist, tải lại, duplicate, restore và approval bao phủ cấu hình mới.
- Tích hợp media selection có reference an toàn, không mất dữ liệu khi hủy hoặc lỗi lưu.

**Đạt khi:** sửa Global chỉ đổi đích đang kế thừa; Page B giữ bản riêng; xóa hashtag thật sự được giữ; tải lại không mất lựa chọn; sửa bản riêng làm approval không còn hiệu lực; bài/release cũ không bị đổi nghĩa.

### M2 — Lập lịch nhiều Facebook Page trong một kế hoạch

- Bộ chọn target từ nhiều account, preflight, bảng rà soát và giờ đăng từng đích.
- Ghi batch nguyên tử, idempotency và kiểm tra thay đổi giữa preview với submit.
- Dùng Chrome/API theo route đủ điều kiện; API Facebook mở format ảnh/video/Reel chỉ với Page binding và quyền phù hợp.
- Hai cửa vào “Lên lịch nhanh” và tab Lịch dùng cùng logic. Tránh tạo hai composer có quy tắc khác nhau.
- Hiển thị kết quả theo Page ngay sau tạo lịch và khi worker chạy.

**Đạt khi:** fixture có ít nhất hai account và ba Page tạo đúng một plan với ba releases/jobs; một đích lỗi làm không có batch mới; lỗi ghi ở giữa rollback đủ; gửi lại không trùng; thiếu dry-run đúng route chặn đăng thật; một job lỗi không khiến Page đã thành công bị đăng lại.

**Đây là mốc giao đầu tiên có giá trị sử dụng đầy đủ theo ưu tiên người dùng đã chọn.**

### M3 — Đa nền tảng với capability hiện có

- Mở các platform đã có adapter, format và readiness phù hợp trên cùng bộ chọn.
- Preview/settings riêng theo đích; media dùng chung hoặc chọn riêng khi định dạng yêu cầu.
- Validation dùng chung và thông báo cụ thể về caption, media, settings, connection và transport.
- Thêm constraint dimensions/aspect/duration/size chỉ khi metadata đọc được và quy tắc đã đối chiếu tài liệu chính thức của provider/transport. Metadata thiếu phải được báo là chưa xác minh, không coi như đạt.

**Đạt khi:** một kế hoạch fixture nhiều platform có payload đúng từng đích; ảnh Facebook không bị dùng như video YouTube; format/transport không hỗ trợ bị chặn trước tạo job; Chrome/API regression qua. Nghiệm thu live chỉ cho capability/account được chọn và được phép.

### M4 — Bộ kênh, chữ ký và media picker

- Lưu bộ target + settings để chọn lại nhanh; không lưu token, approval, evidence hoặc snapshot của bài cũ trong preset.
- Preset có target không còn dùng được phải nêu rõ; không tự bỏ hoặc thay target khác.
- Chữ ký/hashtag mẫu được chèn vào bản nháp trước validation và duyệt; sửa mẫu không đổi bài đã lưu/đã lên lịch, áp dụng lại không nhân đôi chữ ký.
- Chọn nhiều asset trong một lần, xem thứ tự và lỗi tương thích theo từng đích.

**Đạt khi:** tạo bài tiếp theo với cùng bộ Page không cần chọn lại; chữ ký tính vào giới hạn nội dung; references và thao tác hủy/lưu đúng.

### M5 — Chi tiết release, đối soát và calendar

- Từ thẻ lịch/bài viết mở chi tiết gồm đích, nội dung/media đã đóng băng, trạng thái, URL, lỗi, metrics; thông tin route/revision/attempts/events/artifacts nằm trong vùng chi tiết kỹ thuật.
- Hiển thị số đích thành công/lỗi/chưa xong/cần đối soát; không gắn nhãn cả nhóm “đã đăng” chỉ vì một Page thành công.
- Thay prompt đổi lịch và kết nối URL bằng dialog có thông tin ngữ cảnh.
- Giữ xác nhận đúng Page và đúng bài khi nối URL. Tìm gợi ý bài gần đây là phần tùy chọn theo provider; không tự ghép bằng caption gần giống.
- Lọc lịch theo account/target, thêm day/slot view sau dialog. Kéo-thả dùng cùng API reschedule và kiểm tra trạng thái tại lúc commit.
- Thao tác nhóm nêu rõ phạm vi. Nếu một release đã chạy, không âm thầm áp dụng đổi lịch một phần; cho người dùng chọn rõ các release còn hợp lệ.

**Đạt khi:** người dùng tìm được kết quả và lỗi từng đích từ cùng luồng; `unknown_result` dẫn tới đối soát; đổi lịch chỉ được với job còn đủ điều kiện, có timezone/audit và không làm thay snapshot bài.

### M6 — API media và analytics có điều kiện

Chỉ đưa lên trước nếu nhu cầu người dùng yêu cầu, hoặc triển khai sau khi M2/M3 ổn định.

- Facebook media API: 06A một ảnh, 06B album hai/ba ảnh và 07 video Page/Reel đã live-verified trên Page Tinix; album 4–10 ảnh còn fixture-only. Live acceptance vẫn theo từng App/Page/token.
- Instagram API: chọn phạm vi hẹp theo account/app thực tế, kiểm tra điều kiện media và lifecycle publish trước khi cam kết.
- Meta analytics tự động: tái sử dụng cơ chế fetch run, giới hạn tần suất và trạng thái snapshot; không coi scheduler YouTube hiện tại đã bao phủ Meta.
- Chỉ thêm metric thực sự lấy được. Giữ source, thời điểm, phân biệt snapshot với số phát sinh và dữ liệu cũ khi fetch lỗi.

**Đạt khi:** từng capability có test, điều kiện quyền rõ và bằng chứng nghiệm thu cho đúng account/format. Không yêu cầu hoàn thành M6 để giao composer nhiều Page.

## 7. Kế hoạch kiểm thử

| Nhóm | Tình huống bắt buộc |
|---|---|
| Kế thừa | Global → platform → target; detach/rejoin; rỗng có chủ đích; bài legacy giữ nội dung hiệu lực |
| Revision | Lưu/tải lại, duplicate/restore; sửa override/media/settings liên quan làm mất hiệu lực approval; snapshot cũ bất biến |
| Media | Chọn nhiều, thứ tự, hủy editor, lỗi attach/upload; reference của mọi target; asset dùng trong release không bị dọn nhầm |
| Batch | Nhiều account; target trùng/tắt/sai account; một đích lỗi; lỗi DB ở release/job thứ hai; worker không thấy batch chưa commit |
| Cạnh tranh | Nội dung, approval, credential hoặc binding đổi giữa preflight và commit; hai submit đồng thời; rollback không làm mất batch đã có |
| Idempotency | Bấm đúp; timeout sau commit; gửi lại cùng mã; cùng mã khác payload; delay/random delay ổn định |
| Routing | Chrome/API, Facebook API theo format đã khai báo, YouTube; không có route hợp lệ; evidence cũ hoặc sai target/connection; không đổi route sau commit |
| Vận hành | Một đích thành công, một lỗi, một unknown; retry riêng đích đủ điều kiện; phục hồi restart không đăng trùng |
| Calendar | UTC/timezone, giờ quá khứ/missed policy, slot từng target; đổi lịch đồng thời với worker claim; DST với timezone có DST |
| Tương thích | Request cũ, client cũ, local API/CLI liên quan; dữ liệu/backup trước migration; Page binding và metrics không bị trộn |
| UI | Tạo/sửa, đổi tab không mất dữ liệu, lựa chọn target, lỗi đúng đích, preview, duyệt, submit, kết quả một phần; không lỗi console |

Quy trình cho mỗi mốc có code:

1. Chạy test nhỏ nhất bao phủ hành vi vừa sửa. Viết test theo kết quả người dùng và ràng buộc dữ liệu, không chỉ lặp lại implementation.
2. Mở rộng các suite liên quan: `tests.test_content_ai_scheduling`, `tests.test_api`, `tests.test_state_and_migrations`, `tests.test_reliability`, `tests.test_publisher_routing`, `tests.test_meta_page_api`, `tests.test_youtube_official_publisher`, `tests.test_platform_catalog` và frontend theo phạm vi thực tế.
3. Trước khi giao thay đổi cốt lõi scheduling/persistence, chạy full suite bằng `.\.venv\Scripts\python.exe -m unittest discover -s tests`; chạy `node --check` cho JS đã sửa và `git diff --check`.
4. Chạy `BUILD.bat` từ root sau thay đổi cuối cùng, tuân thủ AGENTS và mục 8. Nếu build đã chạy đầy đủ test thì không lặp lại khi không có thay đổi/lỗi mới.
5. Nghiệm thu live tách khỏi fixture. Kế hoạch không tự cấp quyền đăng; mỗi lần đăng thật cần nằm trong chỉ thị cụ thể của người dùng về đích/nội dung. Không tái sử dụng hoặc đăng lại bài thử đã xóa trong `PLAN.md`.

Không lấy số test từng đạt trong `PLAN.md` làm kết quả kiểm tra của lần triển khai mới.

## 8. Build, restart và bàn giao sau triển khai

Chỉ áp dụng khi có code/UI/runtime thay đổi; lượt tạo tài liệu này không chạy build hoặc restart.

- Đọc quy tắc dự án và `DesktopBuild.md` trước khi giao. Hoàn tất thay đổi và các kiểm tra cần thiết rồi chạy `BUILD.bat`.
- Hiện `BUILD.bat` gọi `STOP.bat`, và `STOP.bat` gọi `app.cleanup`; phải kiểm tra phạm vi cleanup trước khi chạy. Không dùng số port đơn lẻ làm bằng chứng sở hữu process, không kill tất cả Python/Node/Chrome.
- `START.bat` là launcher chuẩn và có mở App Mode. Khi chỉ cần thay backend, ưu tiên đúng nhánh khởi chạy backend/cấu hình tương đương đã kiểm tra từ launcher, với cửa sổ ẩn; dùng launcher chuẩn khi cần khởi động cả app. Không sửa launcher chỉ để phục vụ mốc composer.
- Sau build cuối cùng, thay đúng backend Tinix ngay cả khi có task đang chạy, theo quyền người dùng đã cấp. Ghi nhận task bị gián đoạn nếu có; không chờ idle chỉ vì có công việc đang chạy.
- Xác minh process cũ đã được thay, process mới thuộc dự án và bắt đầu sau thay đổi/build cuối; `/api/health` trả trạng thái/version phù hợp. Kiểm tra asset frontend dùng version mới; refresh UI nếu cần.
- Build thành công hoặc refresh trình duyệt không thay thế việc xác minh backend. Nếu restart/health thất bại, báo đúng blocker và không báo sẵn sàng dùng.
- Báo cáo cuối mỗi mốc: chức năng và file thay đổi, test/build, restart/health/version, hạn chế còn lại và Git commit. Không tự tạo commit.

## 9. Các quyết định cần chốt trước phần việc phụ thuộc

| Quyết định | Đề xuất hiện tại | Thời điểm cần chốt |
|---|---|---|
| Nhu cầu đợt đầu | Nhiều Facebook Page trước; mô hình sẵn cho đa nền tảng | **Đã được người dùng xác nhận ngày 28-09-2026** |
| Override | Global → platform → target; tách nhóm text, media chọn chung/riêng | M0 |
| Lưu cấu hình | JSON có version trên content, vào revision; media dùng reference chuẩn | M0, sau khi đối chiếu migration/compatibility |
| Batch có đích lỗi | Chặn cả lần tạo lịch; người dùng bỏ chọn đích lỗi nếu muốn tiếp tục | Dùng làm mặc định trong contract M0 |
| Lịch từng đích | Giờ chung, chỉnh riêng khi cần; slot theo target | M0 |
| API ảnh/video | Mốc độc lập; đưa lên trước nếu người dùng xác nhận ưu tiên | Trước M6 hoặc khi đổi lộ trình |
| Nghiệm thu live | Đúng account/format thực dùng; đăng thật theo chỉ thị cụ thể | Trước thao tác live tương ứng |

Các quyết định kỹ thuật thường lệ do người triển khai chốt theo mã và test; không cần hỏi người dùng về từng tên field hoặc route. Chỉ hỏi thêm khi làm thay đổi phạm vi sản phẩm, ý nghĩa dữ liệu cũ hoặc cách vận hành quan trọng.

## 10. Tiêu chí kết thúc đợt cốt lõi

- Người dùng tạo một bài, chọn nhiều Page qua nhiều account, chỉnh riêng một Page, lưu và mở lại vẫn đúng.
- Preview/validation và payload worker nhất quán; từng đích hiện đúng media, format, route và thời gian.
- Một thao tác tạo một kế hoạch đầy đủ; lỗi không để batch dở, gửi lại không trùng.
- Approval/evidence hợp lệ; snapshot và lịch sử cũ được bảo toàn; không đăng lại đích đã thành công khi đích khác lỗi.
- Kết quả từng Page có thể theo dõi và đối soát; không che trạng thái thành công một phần.
- Test/build đạt, backend đã thay và health/version/asset được kiểm tra theo quy tắc dự án.
- Tài liệu sử dụng liên quan được cập nhật cho luồng mới; cập nhật lại những nhận định đã cũ trong `RESEARCH_postiz.md` khi có kết quả triển khai, không sửa lịch sử nghiệm thu thành bằng chứng mới.

## 11. Tài liệu tham chiếu

- [Nghiên cứu Postiz hiện có](../RESEARCH_postiz.md).
- [Benchmark lịch sử](POSTIZ_BENCHMARK_PLAN.md): dùng để hiểu nguồn gốc, không coi toàn bộ backlog và giả định Chrome-only ban đầu là hiện trạng.
- [Kế hoạch và kết quả triển khai API/analytics](../PLAN.md).
- [Kiến trúc platform](PLATFORM_ARCHITECTURE.md), [Tổng quan dự án](PROJECT_OVERVIEW.md), [Quy tắc desktop build](../DesktopBuild.md).
- [Postiz Global/per-channel](https://docs.postiz.com/general/composer/global-vs-per-channel): cơ chế kế thừa, tách bản riêng và quay lại Global.
- [Postiz concepts](https://docs.postiz.com/general/concepts): channel, post group, sets, signatures và time slots.
- [Facebook API collection của Meta trên Postman](https://www.postman.com/meta/facebook/documentation/r56bjfd/facebook-api): tham khảo luồng Page access token và Facebook Reels; ví dụ collection là contract ứng viên, không thay thế xác minh Graph version/app/Page thực tế.
- [Instagram API collection của Meta trên Postman](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api): tham khảo hai login flow, scopes và các ví dụ publish; không coi quyền trong ví dụ là entitlement của app Tinix.

Các giới hạn/quyền API cụ thể phải được kiểm tra lại bằng tài liệu chính thức ở mốc triển khai tương ứng; kế hoạch này không cố định quota, Graph version hay giới hạn media chưa xác minh.

## 12. Bộ kế hoạch chi tiết theo giai đoạn

Bổ sung ngày 28-09-2026 theo yêu cầu tách file từng giai đoạn. Trạng thái từng đợt được cập nhật theo kết quả thực hiện; tạo kế hoạch tự nó không phải bằng chứng chức năng đã hoàn thành. M0–M6 ở trên là các mốc tổng; số 01–10 dưới đây là các đợt chi tiết, không thay đổi ưu tiên nhiều Facebook Page trước.

| Giai đoạn | File kế hoạch | Quan hệ với mốc tổng | Phụ thuộc chính |
|---|---|---|---|
| 01 | [Composer và nhiều Facebook Page](plan_postiz_01_facebook_multi_page.md) | M0–M2 | Hoàn tất fixture/UI; chưa live-verified |
| 02 | [Composer đa nền tảng](plan_postiz_02_multi_platform.md) | M3 | Hoàn tất fixture/UI; chưa live-verified |
| 03 | [Bộ kênh, chữ ký và media picker](plan_postiz_03_reusables_media.md) | M4 | Hoàn tất fixture/UI; chưa live-verified |
| 04 | [Chi tiết release và đối soát](plan_postiz_04_release_reconciliation.md) | Phần release của M5 | Fixture/UI/API đạt; chưa live-verified |
| 05 | [Calendar và posting slots](plan_postiz_05_calendar_slots.md) | Phần calendar của M5 | Day/week/month/list, slot gợi ý và reschedule nhóm đạt; drag-drop hoãn |
| 06 | [Facebook ảnh qua API](plan_postiz_06_facebook_photo_api.md) | Nhánh ảnh của M6 | 06A một ảnh và 06B album hai/ba ảnh live-verified trên Page Tinix; 4–10 ảnh chưa thử |
| 07 | [Facebook video qua API](plan_postiz_07_facebook_video_api.md) | Nhánh video của M6 | Video Page thường và Reel đã live-verified trên Page Tinix |
| 08 | [Instagram Official API](plan_postiz_08_instagram_api.md) | Nhánh Instagram của M6 | One-JPEG API publisher + private R2 delivery fixture-tested; chờ bucket/token, OAuth live và publish acceptance |
| 09 | [Analytics định kỳ](plan_postiz_09_analytics_refresh.md) | Nhánh analytics của M6 | Đã có opt-in theo provider; Reel và Page Tinix đã thu thập thủ công qua API thật; scheduler tự động chưa bật/nghiệm thu live |
| 10 | [Nghiệm thu vận hành và tài liệu](plan_postiz_10_acceptance_operations.md) | Đóng đợt core | Đã cập nhật ma trận bằng chứng, kết quả build/restart mới nhất và các blocker còn mở; không có live publish mới |

### Thứ tự giao đề xuất

1. **Đợt A:** giai đoạn 01 và phần nghiệm thu tương ứng của 10 — giao luồng nhiều Facebook Page hoàn chỉnh.
2. **Đợt B:** giai đoạn 02 — mở đa nền tảng với capability hiện có; hoàn tất fixture/UI, live acceptance vẫn theo từng account/capability.
3. **Đợt C:** giai đoạn 03, 04, 05 — giảm thao tác lặp, theo dõi kết quả và quản lý lịch. 04 có thể đưa lên ngay sau 01 nếu xử lý lỗi/đối soát là nhu cầu cấp thiết.
4. **Đợt D có điều kiện:** 06A, album hai/ba ảnh của 06B và cả hai format video của 07 đã live-verified trên Page Tinix. 08 là nhánh Instagram riêng; 09 không phải chờ media API.
5. **Đóng mỗi đợt:** chạy phần nghiệm thu 10 phù hợp với phạm vi thực tế. Không giữ lại bản nhiều Page đã đạt chỉ vì các API tùy chọn chưa đủ điều kiện.

Số giai đoạn là thứ tự tham khảo, không yêu cầu chạy mọi nhánh tuần tự. Không giao chạy nhiều agent mặc định. Mỗi file ghi rõ scope, bước triển khai, kiểm thử và đầu ra; quy tắc revision/approval, compatibility, build/restart tại tài liệu tổng vẫn áp dụng. Khi cần đổi quyết định chung, cập nhật cả kế hoạch tổng và file giai đoạn bị ảnh hưởng, không để hai bản mâu thuẫn.

Hiện chưa có thông tin đủ để ước lượng ngày công đáng tin cậy. Sau contract/baseline của giai đoạn 01, ước lượng từng đợt dựa trên phạm vi đã chốt; các nhánh API phải tính riêng thời gian chờ quyền và nghiệm thu bên ngoài.

**Kết quả cập nhật Facebook media — 28-09-2026:** Giai đoạn 06A (một ảnh) và 07 đã qua code review, 81 targeted tests và full `BUILD.bat --no-bump` với 300 tests. Backend PID 43588 chạy version 1.0.43, health `ok`; lúc ghi mốc này chưa có live publish. Sau đó đã đăng thử một ảnh và một video Page thường theo chỉ thị của người dùng. 06B nhiều ảnh còn chờ live acceptance.

**Triển khai album ảnh Facebook — 28-09-2026:** Đã thêm format `multi_photo` (2–10 ảnh theo policy Tinix), upload ảnh tuần tự ở trạng thái unpublished, gắn vào một bài theo thứ tự và phục hồi an toàn sau timeout. 128 targeted tests và full `BUILD.bat --no-bump` đều đạt. Backend mới PID 52504 trên cổng 8765 chạy v1.0.43; health/database `ok`, worker idle, không warnings; API công bố `multi_photo` riêng cho Official API và composer JS trả 200. Tại mốc triển khai này, album chưa được đăng live.

**Nghiệm thu album hai ảnh — 28-09-2026:** Theo chỉ thị của người dùng, đã đăng [một bài thử gồm hai ảnh trên Page Tinix](https://www.facebook.com/122132248658779083/posts/122132264210779083). Graph xác nhận post `1106784475845782_122132264210779083` do đúng Page sở hữu và attachment album chứa hai photo ID `122132263586779083`, `122132264180779083` theo thứ tự. Job Tinix `47372f00-d520-4d75-8821-963b5e3f32c1` kết thúc `succeeded` sau khi khôi phục từ checkpoint. Lần chạy đầu bộc lộ lỗi chuyển `uploading` lặp ở ảnh thứ hai; đã sửa publisher/state machine và bổ sung test dùng chuyển trạng thái thật.

**Nghiệm thu Reel — 29-09-2026:** Theo chỉ thị của người dùng, đã đăng [Reel thử trên Page Tinix](https://www.facebook.com/reel/1329975209041799/) bằng nhánh `video_reels`; job `c944e4e0-b3d0-4d68-ac11-d6c37f9cd20b` kết thúc `succeeded` trong một attempt. Graph xác nhận video `1329975209041799` thuộc Page `1106784475845782`, upload/processing hoàn tất, `publish_status=published` và caption đúng. Trước live run đã sửa xác minh Page/trạng thái và permalink; lần thử đầu bị RUpload HTTP 400 ở bước upload, chưa publish và đã đối soát job thất bại. Bản upload tiếp theo gửi `Content-Length` và dùng clip thử có chuyển động; nguyên nhân riêng lẻ của HTTP 400 đầu không thể xác định chắc chắn. 94 targeted tests và full `BUILD.bat --no-bump` đạt 100%; backend mới PID 40096, `/api/health` `ok`, worker idle, không warnings sau khi đối soát.

**Nghiệm thu analytics Meta — 29-09-2026:** Thu thập Reel live ban đầu gặp Graph code 100 vì `shares` không tồn tại trên video. Đã tách fields theo format và xác minh live `likes`, `comments`, `views` của Reel, cùng `followers`, `page_likes` của Page Tinix; các giá trị Meta trả hiện là 0. Kết quả trả URL Reel đầy đủ. Regression tests và full `BUILD.bat --no-bump` đạt 100%; backend PID 18992 health/database `ok`, worker idle, không warnings. Chưa bật scheduler analytics tự động; Instagram publishing vẫn chờ media storage HTTPS và kết nối/quyền Instagram phù hợp.

**Nghiệm thu album ba ảnh — 29-09-2026:** Bài [thử album ba ảnh](https://www.facebook.com/122132248658779083/posts/122132332970779083) trên Page Tinix đạt dry-run và đăng thành công trong một attempt (`49060e3f-ab23-4e22-bb24-38eadc474c7f`). Graph xác nhận đúng Page, attachment `album`, ba ảnh đúng thứ tự `122132332856779083`, `122132332898779083`, `122132332940779083`. Album 4–10 ảnh hoặc Page khác chưa thử live; không có thay đổi code/build/restart ở nghiệm thu này.
