# Final Production Review

## STATUS

**Cập nhật sau yêu cầu sửa cả 8 lỗi (02-10-2026): F01–F08 đã sửa và kiểm chứng local; BUILD.bat PASS, 352 tests, version 1.0.44. Backend mới PID 111176 đã nạp code mới, health `ok`.** Phần audit 1.0.43 bên dưới giữ làm bằng chứng trước sửa; kết quả remediation ở cuối báo cáo. Các giới hạn live acceptance vẫn được giữ.

**Kết quả audit trước sửa: NOT READY** — 6 vấn đề MUST FIX BEFORE RELEASE và 2 vấn đề SHOULD FIX BEFORE RELEASE đã có bằng chứng tái hiện. Suite hiện có đạt nhưng chưa bao phủ các failure mode này.

Ngày review: **02-10-2026, UTC+7**. Phạm vi: toàn bộ ứng dụng Windows local hiện tại, version **1.0.43**, schema **25**, gồm cả thay đổi chưa commit. Không sửa source, không refactor, không commit, không đăng bài thật.

## BASELINE

- HEAD: `fd0f7888fceb843dbd1750514b8998190b55357d` — `docs: save Postiz research and implementation plan`.
- Khi bắt đầu: **61 tracked files modified, 23 untracked files, 0 staged**. Đây là trạng thái có sẵn, không phải thay đổi do review. Các file untracked gồm Instagram/Meta providers, services và tests mới.
- Đã lưu Git status và SHA-256 của 171 file visible trước kiểm thử. Sau test/build, toàn bộ hash và Git status vẫn khớp baseline; chỉ thêm báo cáo này ở bước cuối.
- Đã đọc `Agents.md`, `DesktopBuild.md`, README, `PLAN.md`, `RESEARCH_postiz.md`, tổng quan/kiến trúc, kế hoạch Postiz tổng và 01–10, tài liệu automation/runtime/acceptance. Hai kế hoạch benchmark/integrations cũ được xem là lịch sử, đối chiếu với implementation.
- Không tìm thấy `DEVELOPMENT_WORKFLOW.md`, `RELEASE_WORKFLOW.md`, `ARCHITECTURE.md`, `PROJECT_STATUS.md`. Tài liệu thay thế hiện có: `DesktopBuild.md`, `docs/PLATFORM_ARCHITECTURE.md`, `docs/PROJECT_OVERVIEW.md`, `.github/workflows/windows-ci.yml`. Không suy diễn nội dung tài liệu thiếu.
- Không thấy process `-m app`/`-m app.worker_entry` đang chạy trước review; health ở port mặc định 8765 không trả lời. Server sản phẩm đang dừng; không bật worker trên dữ liệu người dùng trong audit.
- Database người dùng chỉ đọc: integrity `ok`, schema 25, **0 foreign-key violations**, 10 accounts, 37 releases. Job: 12 real succeeded, 1 real permanent_failure; dry-run gồm 16 ready, 4 cancelled, 4 permanent_failure. Không có job đang thực thi trong snapshot này.
- 23/23 media asset được kiểm tra file/kích thước/hash: **không thiếu, không thay đổi, không nằm ngoài storage**, tổng 12.328.835 byte.

### Phân loại lỗi và regression

Không có failing automated test ở baseline; không phát hiện flaky test trong các lần chạy này. Các finding bên dưới là **lỗi hiện tại được mô phỏng bổ sung**, không được gọi là regression mới do review.

Các code path gây F01–F06 đã hiện diện ở HEAD trước review: restore/resume, thiếu bảo vệ HTTP, startup recovery không phân biệt worker còn sống, cleanup dùng port/PID, serializer thiếu recovery_codes và queue runner thiếu xử lý lỗi claim. F07 cũng có ở YouTube HEAD. Chưa chạy release cũ trên DB mới để suy đoán tương thích hoặc xác định ngày phát sinh lỗi.

## TEST / BUILD RESULTS

| Kiểm tra | Kết quả | Phạm vi/giới hạn |
|---|---|---|
| `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v` | **PASS: 332 tests**, 183,430 giây | Không có failure/skip; gồm **11 Playwright UI smoke/E2E** |
| `BUILD.bat --no-bump` | **PASS**, exit 0; full suite 100% | Version giữ 1.0.43; icon/shortcut tạo thành công |
| `python -m compileall -q app tests build.py` | **PASS** | Python syntax |
| `node --check` cho 14 JS modules | **PASS** | JavaScript syntax |
| `python -m pip check` | **PASS** | Không broken dependency |
| Hai function test trong `test_cleanup.py` | **PASS: 2/2** | Chạy bổ sung bằng FunctionTestCase, mock termination và paths cô lập; unittest discover không thu thập hai hàm cấp module này |
| Startup/index/static/runtime/health | **PASS** | Server riêng, DB/media/profiles riêng, embedded worker off |
| Process restart + draft persistence | **PASS** | Backend Uvicorn PID **103596 → 84532**, health 1.0.43 sau thay process, draft tồn tại |
| Failure/attack simulations | **FAIL theo expected safety**, F01–F08 bên dưới | Temp databases, fake credentials, mocked publishers/provider clients; không tác động mạng xã hội |
| Lint/typecheck | **NOT TESTED** | Không thấy workflow/config chuyên dụng; pytest/ruff không cài trong venv, không thêm dependency |
| CI Python 3.11 / clean-machine install | **NOT TESTED** | Máy audit dùng Python **3.13.14**; CI khai báo 3.11 |

Build được chạy với runtime directories cô lập và port riêng để cleanup không chạm dữ liệu/phiên Chrome của người dùng; không đổi launcher/source. Build vẫn dùng dependencies, test suite và assets của workspace hiện tại. Không có release archive/installer hoặc auto-updater riêng để kiểm tra.

**Restart sản phẩm không áp dụng:** đây là audit/documentation-only, source/runtime config không đổi và server sản phẩm vốn dừng. Hai backend thử nghiệm đã dừng sau smoke test; không có task production bị gián đoạn. Không tuyên bố server sản phẩm đã cập nhật hoặc sẵn sàng chạy thật.

Bằng chứng tạm nằm tại `C:\Users\Admin\AppData\Local\Temp\tinix-final-review-20261002\`: `baseline.json`, `unittest.log`, `build.log`, `reproduce.py`, `reproductions.json`, `extra.py`, `extra-results.json`, `smoke.py`, `smoke-results.json`, `smoke-server.log`, `db_lock.py`, `db-lock-results.json`, `live-data-integrity.json`. Đây là evidence của lượt chạy, không phải test mới được thêm vào source.

## CRITICAL FINDINGS

### F01 — Restore backup có thể tự đăng lại bài đã thành công

- **Severity:** CRITICAL.
- **Problem:** Restore thay toàn bộ lịch sử job bằng snapshot cũ rồi tự resume worker. Bài đã đăng ngoài mạng xã hội sau mốc backup mất trạng thái succeeded/commit/URL; job queued trong backup trở thành công việc mới có thể claim.
- **Evidence:** `app/api/routes.py:1718` và `:1759`; bundle restore cũng resume tại `:1824`. `app/db/database.py:894` restore snapshot nguyên trạng; `JobRepository.claim_next` nhận queued mà không có ledger độc lập với backup. `extra-results.json` tái hiện bằng **content đã approval và đã có dry-run evidence**, real publication hợp lệ: release `succeeded → queued`, URL thành null, restore HTTP 200, **cùng real job được claim lại**. Mô phỏng không gọi social API.
- **User impact:** Người dùng bấm khôi phục trong Cài đặt có thể phát hành lại bài đã đăng, với cùng nội dung/đích; một backup có nhiều queued/scheduled jobs có thể gây nhiều bài trùng.
- **Reproduction:** Tạo lịch real hợp lệ → backup trước khi job chạy → cho job succeeded → restore backup đó → worker resume/claim lại cùng job. Tác động đã tái hiện cho database restore; bundle restore có cùng cơ chế, chưa chạy riêng kịch bản replay bundle.
- **Recommended fix:** Khi restore, giữ worker paused và quarantine các real jobs có thể thực thi trong dữ liệu khôi phục; bắt buộc đối soát/xác nhận riêng trước khi mở lại queue. Giữ/lưu bằng chứng commit và external identity ngoài việc rollback snapshot nếu cần tự động phục hồi. Safety backup tự nó không ngăn replay.
- **Release decision:** **MUST FIX BEFORE RELEASE**.

## HIGH FINDINGS

### F02 — Legacy HTTP API chấp nhận thao tác từ origin khác và Host tùy ý

- **Severity:** HIGH.
- **Problem:** Bind loopback là giới hạn mạng, nhưng legacy `/api` không kiểm tra Origin/Host hoặc yêu cầu session/CSRF cho mutation. Các endpoint trả credential cũng không có lớp bảo vệ browser origin.
- **Evidence:** `app/main.py:269–282` chỉ include routers và serialize mutation. `app/api/routes.py:570` trả credentials; `:1711` tạo backup không cần body/auth. Test trên **actual app server + Chrome headless**: form từ `http://localhost:52050` gửi tới `http://127.0.0.1:52034/api/database/backups`, **HTTP 200**, backups **0 → 1**. TestClient với fake password, foreign Origin và `Host: attacker.example:8765` trả credential HTTP 200; actual app foreign Host cũng HTTP 200.
- **User impact:** Trang web khác có thể kích hoạt các mutation nhận simple POST, ví dụ backup hoặc đóng phiên Chrome. Host tùy ý cùng credential API tạo điều kiện cho DNS rebinding đọc secret. **Không khẳng định đã thử DNS rebinding hoàn chỉnh hoặc đọc credential qua cross-origin fetch**: SOP/CORS vẫn là một lớp riêng; browser form mutation đã được chứng minh trực tiếp.
- **Reproduction:** Mở form trên origin khác, submit POST không body tới `/api/database/backups`. Gửi GET credential với Host lạ trên server fixture để kiểm tra không có Host gate.
- **Recommended fix:** Thêm allowlist Host và same-origin/CSRF protection cho WebUI mutations; bảo vệ credential endpoints bằng session/token hợp lệ. Giữ callback OAuth có state validation và ngoại lệ được giới hạn rõ. Kiểm tra mọi legacy route, không chỉ `/api/v1`.
- **Release decision:** **MUST FIX BEFORE RELEASE**.

### F03 — Worker thứ hai “recover” job của worker vẫn đang chạy

- **Severity:** HIGH.
- **Problem:** Mỗi `LocalWorker.start()` chạy recovery trên toàn bộ execution jobs, không chứng minh worker cũ đã chết. Hai worker dùng cùng SQLite có thể cùng thực thi một publication.
- **Evidence:** `app/services/worker.py:41–42`; `app/db/repositories.py:899` đưa uploading về queued không xét owner/lease. Fixture: worker A đang giữ một real job ở uploading → khởi động worker B → **publisher nhận cùng job 2 lần, attempts=2**, sau đó còn có invalid transition do hai executor tranh trạng thái. Không có request ra ngoài.
- **User impact:** Chạy standalone worker khi embedded worker còn bật, hoặc mở hai worker, có thể upload/publish trùng và làm state không nhất quán. Tài liệu `docs/VPS_READINESS.md` yêu cầu một worker nhưng implementation không ngăn cấu hình sai này.
- **Reproduction:** Cho worker A dừng chờ ở uploading; khởi động B cùng database; quan sát B recover rồi claim cùng job.
- **Recommended fix:** Với SQLite local, thêm khóa single-worker có kiểm tra owner còn sống, từ chối worker thứ hai trước recovery. Chỉ recover job của owner đã chết; không cần đưa hệ thống phân tán mới vào project.
- **Release decision:** **MUST FIX BEFORE RELEASE**.

### F04 — START/STOP/BUILD có thể terminate process không thuộc project

- **Severity:** HIGH.
- **Problem:** Cleanup chọn listener chỉ theo port và Chrome session chỉ theo PID đã lưu. Không xác minh command line/cwd/profile/start-time ở hai đường này trước termination.
- **Evidence:** `app/cleanup.py:76–107` append listener theo port; `:112–124` append PID từ `chrome_sessions.json`. `START.bat`, `RUN.bat`, `STOP.bat`, `BUILD.bat` gọi module này. Mock isolated: process không liên quan PID 34567 đang nghe port được chọn làm backend; stale session PID 45678 được chọn làm Chrome dù có thể đã được tái sử dụng. **Không terminate process thật trong reproduction.**
- **User impact:** Port trùng hoặc PID reuse sau restart máy có thể đóng app/server khác và các child processes, gây gián đoạn hoặc mất công việc chưa lưu.
- **Reproduction:** Mock listener không thuộc Tinix tại configured port hoặc session file trỏ PID không còn thuộc Chrome profile; cleanup vẫn đưa process vào termination list.
- **Recommended fix:** Áp dụng kiểm tra ownership chính xác cho mọi candidate: executable/command line/cwd của project hoặc Chrome `--user-data-dir` đúng profile; so PID creation time nếu có. Nếu không xác minh được, báo port conflict/stale session thay vì kill.
- **Release decision:** **MUST FIX BEFORE RELEASE**.

### F05 — Token chỉ có scope read nhận plaintext recovery codes

- **Severity:** HIGH.
- **Problem:** Serializer account của API v1 bỏ password/2FA/cookie nhưng bỏ sót `recovery_codes` đã được repository giải mã.
- **Evidence:** `app/api/v1.py:23–29` hidden set thiếu recovery_codes; `app/db/repositories.py:40–81` hydrate cả credential này. Fixture account có fake recovery code và token được giới hạn **chỉ `read`**: `GET /api/v1/accounts` HTTP 200, **recovery code nguyên văn vẫn xuất hiện**, password không xuất hiện. Legacy public serializer đã loại trường này, cho thấy hai bề mặt không nhất quán.
- **User impact:** Automation có quyền đọc account có thể lấy mã khôi phục đăng nhập thay vì chỉ metadata; DPAPI không giúp khi backend đã giải mã và trả ra API.
- **Reproduction:** Lưu fake recovery code → token read → GET `/api/v1/accounts` → kiểm tra field recovery_codes.
- **Recommended fix:** Dùng cùng serializer public và cùng denylist credential đầy đủ; chỉ trả `has_recovery_codes`. Thêm kiểm thử tất cả credential fields ở các endpoint account của v1.
- **Release decision:** **MUST FIX BEFORE RELEASE**.

### F06 — SQLite lock tạm thời làm queue runner chết, vẫn báo idle

- **Severity:** HIGH.
- **Problem:** Lỗi `claim_next` thoát khỏi `_run`; runner không retry/backoff và trạng thái worker không chuyển sang failed. Database hết lock vẫn không xử lý job mới.
- **Evidence:** `app/services/worker.py:51–70` không catch DB exception quanh claim; scheduler có cùng kiểu thiếu catch tại `:263–273`. `app/db/database.py:820` busy timeout 10.000 ms. Fixture giữ `BEGIN IMMEDIATE` **11,2 giây**: runner finished, exception **OperationalError**, state vẫn **idle**; sau rollback database ping `ok`, job mới vẫn queued. Lỗi runner đã kiểm chứng trực tiếp; scheduler path được rà code, chưa tái hiện riêng.
- **User impact:** Một lần write lock dài từ công cụ SQLite hoặc process khác làm mọi lịch tiếp theo ngừng chạy cho tới restart, dù UI còn hoạt động và worker có thể hiển thị idle.
- **Reproduction:** Worker polling trên DB test → giữ write transaction hơn busy timeout → nhả lock → tạo job → không được claim.
- **Recommended fix:** Xử lý lỗi SQLite tạm thời với backoff hữu hạn trong runner/scheduler; báo health degraded/failed nếu task chết; giữ queue claim transaction an toàn, không retry publish sau commit.
- **Release decision:** **MUST FIX BEFORE RELEASE**.

## MEDIUM FINDINGS

### F07 — Một số publisher không đối chiếu bytes media với snapshot đã duyệt

- **Severity:** MEDIUM.
- **Problem:** YouTube official và Chrome media paths kiểm tra tồn tại rồi dùng file hiện tại; hash/kích thước snapshot không được đối chiếu như Meta/Instagram API.
- **Evidence:** `app/platforms/providers/youtube.py:121`, `app/services/facebook_publisher.py:118–124`, `app/services/web_platform_publisher.py:244`. Mock YouTube: snapshot chứa hash của file gốc → thay bytes file cùng path → publish báo **published** và gửi bytes thay thế, hash upload **không khớp snapshot**. Chỉ YouTube được mô phỏng upload thực qua client mock; Chrome được đối chiếu code.
- **User impact:** File bị sửa/corrupt/khôi phục không khớp database có thể được đăng khác bản người dùng đã duyệt. **Không có asset hiện tại bị sai hash** trong 23 file đã kiểm tra.
- **Reproduction:** Schedule với media snapshot/hash → thay nội dung file giữ path → chạy publisher fixture → file mới vẫn được gửi.
- **Recommended fix:** Kiểm tra size/hash trước upload cho các publisher còn thiếu, báo lỗi trước commit nếu lệch. Giữ snapshot hiện có; không cần schema mới.
- **Release decision:** **SHOULD FIX BEFORE RELEASE**.

### F08 — Image generation mất coordinator sau shutdown/restart

- **Severity:** MEDIUM.
- **Problem:** Image tasks chỉ sống trong bộ nhớ. Shutdown cancel task mà không cập nhật trạng thái hoặc khôi phục theo external_run_id; service mới không nhận lại pending runs.
- **Evidence:** `app/services/image_generation.py:25`, `:78`, `:112–125`, startup tại `app/main.py:230` không recover image runs. Fixture gọi `create_job`, Media Creator mock đã có run ID → `close()` → service mới: row vẫn **running**, finished_at null, external_run_id tồn tại, **không có recovery task**.
- **User impact:** Người dùng đóng/rebuild app trong lúc tạo ảnh có thể thấy job đang chạy vô thời hạn và không tự nhận kết quả từ Media Creator. Chưa có bằng chứng phát sinh khoản phí trùng, nên không kết luận về billing.
- **Reproduction:** Bắt đầu image job với provider mock, chờ bước polling, close coordinator, tạo service mới cùng DB, GET job vẫn running.
- **Recommended fix:** Khi startup, reconcile các queued/running image runs đã có external_run_id; nhận kết quả hoặc đánh dấu interrupted có hướng xử lý. Shutdown phải lưu trạng thái nhất quán; không tạo lại external run mù.
- **Release decision:** **SHOULD FIX BEFORE RELEASE**.

## REGRESSION RISKS

- Test approval/revision, multi-target atomic creation, request-key idempotency, target overrides, route binding, stale scope/selector, reschedule rollback và unknown-result đều đạt.
- Các lỗi F01/F03 vượt qua những bảo vệ này vì chúng thay durable state hoặc ownership, không phải lỗi validation đầu vào.
- F05 là lỗi serializer dùng chung v1 có sẵn; không quy cho integration mới. F07 thể hiện khác biệt validation giữa publisher cũ và Meta/Instagram mới.
- Không chạy HEAD cũ trên DB schema 25; không khẳng định mọi pending change giữ tương thích release cũ. Full suite hiện tại là bằng chứng hồi quy, không phải nghiệm thu tất cả social UI live.

## DATA INTEGRITY

- **PASS:** SQLite WAL/foreign keys; migration transaction + pre-migration backup; dữ liệu hiện tại integrity/hash đạt; content revision và target media invalidate approval; batch/release/job creation nguyên tử; media references và historical snapshots chống xóa asset.
- **FAIL:** F01 restore làm mất bằng chứng publish mới và cho replay; F03 ownership cho duplicate executor; F07 file bytes chưa được đối chiếu đầy đủ.
- Crash sau commit đơn worker chuyển unknown_result và retry bị chặn trong suite. Không suy rộng kết quả này sang restore snapshot cũ hoặc multiple workers.
- Recovery/profile bundle có AES-GCM/password, path-traversal checks, safety copies và rollback tests đạt. Recovery bundle trên Windows user/máy khác chưa được nghiệm thu; DPAPI credential không mặc nhiên portable.

## SECURITY

- **FAIL:** F02 browser boundary; F05 recovery code exposure; F04 unsafe process termination.
- **PASS trong tests/code đã rà:** provider credentials DPAPI, public connection responses bỏ encrypted secret fields, OAuth state/identity checks, managed-path containment, ZIP traversal rejection, loopback-only Media Creator client, R2 private delivery + signed URLs trong fixture.
- Không đưa actual password/token/cookie từ dữ liệu người dùng vào report; security reproduction dùng fake credentials.
- Không thực hiện dependency vulnerability scan hoặc full DNS-rebinding exploit; `pip check` chỉ chứng minh consistency dependencies, không chứng minh không CVE.

## STABILITY / RECOVERY

- Startup/replacement process/draft persistence đạt trên isolated runtime; execution crash recovery và cancellation tests đạt.
- **FAIL:** snapshot restore replay, duplicate worker startup, long SQLite lock, image task restart — F01/F03/F06/F08.
- Network timeout trước/sau commit, expired/revoked API connection, upload checkpoint và unknown-result paths được kiểm tra bằng mocks trong suite. Không ngắt Internet hoặc restart máy thật trong audit.
- Filesystem unavailable/full disk, forced power loss, backup restore trong lúc image/analytics background task đang chạy: **NOT TESTED toàn luồng**. Không tự tạo finding nếu chưa có bằng chứng hậu quả.

## PERFORMANCE

- UI smoke trên fixture và đọc local dataset hiện có đạt; scheduling giới hạn 100 targets, list/pagination và bounded opt-in analytics có trong mã.
- Không có finding performance release-blocking được đo. Không báo N+1/micro-optimization như lỗi release chỉ từ cấu trúc code.
- Thousands of releases, profiles nhiều GB, video gần 1 GB, large recovery encryption và nhiều analytics intervals: **NOT TESTED theo tải production**. Dataset hiện tại nhỏ, không dùng nó để hứa khả năng chịu tải lớn.

## RELEASE / UPDATE

- Build giữ version 1.0.43; UI cache-busting assertions trong Playwright đạt; generated icon và desktop shortcut thành công. Build không tự commit khi không truyền `--commit`.
- Chưa có auto-update/download/apply/signature implementation hoặc release artifact riêng trong project. Đây là desktop source/venv local workflow; không tạo lỗi updater giả định.
- F04 áp dụng trực tiếp launcher/build/shutdown; F01 áp dụng rollback dữ liệu. Run version cũ trên DB mới không được chứng minh an toàn.
- **Documentation mâu thuẫn:** README và phần đầu PLAN còn nói Facebook media chưa live, trong khi nhật ký 06/07 ghi ảnh, album 2/3 và Reel đã live. `PROJECT_OVERVIEW.md` có safety-gate paragraph vẫn nói Meta scaffold; kiến trúc analytics nói ngoài YouTube unsupported dù collector Meta đang có. Ma trận giai đoạn 10 ghi Instagram publisher chưa triển khai nhưng actual `app/main.py` đã register `InstagramOfficialPublisher`, có one-JPEG/R2 tests và plan 08 cập nhật. `LOCAL_AUTOMATION.md` vẫn nói publishing chỉ Chrome.
- Những đoạn stale này được ghi nhận, không tách thành nhiều findings. Nhật ký live lịch sử không được dùng làm bằng chứng đã chạy lại trong audit này. Cần sửa nhãn phạm vi/bằng chứng khi bàn giao release; không “nâng” Instagram live-ready chỉ vì fixture pass.

## MANUAL ACCEPTANCE

“Manual” bên dưới gồm các scenario do reviewer thực hiện/mô phỏng ngoài suite, không đồng nghĩa đã đăng live.

| Scenario | Kết quả | Bằng chứng/giới hạn |
|---|---|---|
| Mở app, health/runtime, index/static | **PASS** | Isolated actual backend HTTP 200, version 1.0.43 |
| Các tab/account/composer/media/calendar/detail/analytics/settings | **PASS** | 11 Playwright cases, không console error theo test |
| Draft/media/revision → approval → multi-target preflight/schedule → frozen detail | **PASS** | Unit/API/E2E fixtures, không publish ngoài mạng |
| Duplicate request, invalid target, batch rollback, reschedule group | **PASS** | Existing regression suite |
| Replace backend rồi đọc lại draft | **PASS** | Uvicorn PID 103596 → 84532, persisted caption đúng |
| Unknown result → chặn retry → manual finalize | **PASS** | Reliability/state/API fixtures |
| Backup trước publish → succeeded → restore → không replay | **FAIL** | Real publication fixture được claim lại, F01 |
| Cross-origin form gửi mutation local | **FAIL** | Chrome form POST 200, backup count tăng, F02 |
| Foreign Host + credential endpoint | **FAIL** | Host lạ được chấp nhận; fake credential trả 200, F02 |
| Worker thứ hai khi job uploading | **FAIL** | Cùng job vào publisher hai lần, F03 |
| Port conflict/PID reuse trong cleanup | **FAIL** | Mock chọn unrelated process để terminate, F04 |
| Read-only automation token không lấy credential | **FAIL** | Fake recovery code bị trả plaintext, F05 |
| DB write lock rồi nhả lock | **FAIL** | Worker runner chết, queue không chạy lại, F06 |
| Media bị thay sau snapshot | **FAIL** | YouTube mock upload bytes sai hash vẫn published, F07 |
| Image job đang polling → close/restart | **FAIL** | Running row không có coordinator phục hồi, F08 |
| DB + 23 media assets người dùng | **PASS** | Chỉ đọc, integrity/FK/hash đạt |
| Profile import/export, encrypted recovery, invalid password/path traversal | **PASS** | Existing fixture suite; không thay profiles người dùng |
| Social OAuth/publish/API analytics thật ở lượt này | **NOT TESTED** | Không có chỉ thị nội dung/đích live; tránh tạo bài/side effects |
| Instagram R2 + OAuth + one-photo live | **NOT TESTED** | Known acceptance gap trong plan 08; chưa chứng minh entitlement/storage live |
| Facebook album 4–10, video auto-finalize sau fix, scheduler analytics live | **NOT TESTED** | Nhật ký dự án cũng còn giới hạn riêng này |
| Machine reboot/power loss/clean install/large workload | **NOT TESTED** | Chưa thực hiện trên máy người dùng |

## MUST FIX BEFORE RELEASE

**6 issue độc lập, không gộp symptom thành issue mới:**

1. **F01:** Restore phải quarantine/reconcile real jobs trước resume.
2. **F02:** Bảo vệ Host/Origin/session/CSRF cho legacy HTTP API.
3. **F03:** Single-worker ownership trước startup recovery.
4. **F04:** Xác minh process ownership trước kill trong mọi cleanup path.
5. **F05:** Loại recovery_codes khỏi API account public.
6. **F06:** Worker/scheduler sống qua transient DB lock hoặc báo failed rõ ràng.

**Nên sửa trước release:** F07 kiểm tra media hash ở publisher còn thiếu; F08 recovery cho image generations. Các sửa này chưa được thực hiện trong task audit.

Sau sửa, chạy lại scenario gây lỗi cùng full suite/build. Nếu thay source/runtime thì restart đúng project và xác minh process/health/assets mới theo Agents.md. Live acceptance tiếp tục theo capability/account thực dùng, với chỉ thị riêng cho bài thử.

## SAFE TO DEFER

- Drag/drop/undo Calendar đã được kế hoạch hoãn; dialog/reschedule hiện có và tests đạt.
- TikTok/X official API scaffold, Instagram carousel/Reel/Story, VPS/multi-user: ngoài phạm vi release local hiện tại; không quảng bá như capability đã nghiệm thu.
- Album 4–10 và Instagram one-photo live acceptance có thể hoãn **nếu không nằm trong phạm vi vận hành được bàn giao** và UI/docs ghi rõ chưa xác minh. Nếu người dùng thực dùng, cần acceptance trước bật tự động.
- Không thêm naming/style/refactor/polish recommendations. F01–F06 không an toàn để hoãn; F07/F08 được giữ vì ảnh hưởng integrity/recovery thực tế.

## FINAL DECISION

**Quyết định tại thời điểm audit 1.0.43: NOT READY. SAFE TO USE NOW: No** cho việc giao toàn bộ ứng dụng để tự động đăng thật.

Lý do quyết định là duplicate/replay khi restore hoặc nhiều worker, lỗi ranh giới HTTP/credential và queue không tự phục hồi sau DB lock — không phải polish nhỏ hay số lượng test. Phần soạn draft/dry-run đã có nhiều kiểm thử tốt nhưng không thay cho an toàn production của các workflow còn lỗi.

Chỉ tạo `FINAL_REVIEW.md`. **Không sửa source, không tạo Git commit**, không khởi động worker trên dữ liệu production và không đăng bài mạng xã hội trong lượt review.


### Kết quả sửa F01–F08 — version 1.0.44

Theo yêu cầu tiếp theo của người dùng, đã sửa cả 6 lỗi bắt buộc và 2 lỗi khuyến nghị. Các finding giữ nguyên phía trên mô tả trạng thái trước sửa.

| Finding | Thay đổi và kiểm chứng |
|---|---|
| F01 | Chuẩn bị/migrate snapshot và cách ly job đăng thật chưa kết thúc **trước khi thay live DB**. Trạng thái `unknown_result`, `restore_reconciliation_required`, commit marker và event bền vững; restore backup/bundle, restart, release_due và retry không phát lại. Rollback safety backup giữ nguyên trạng thái trước restore. Pause đợi cả claim đang chạy; đóng rồi phục hồi image tasks quanh restore. Controller từ chối restore nếu standalone worker còn giữ khóa. |
| F02 | Middleware kiểm tra Host/Origin/Sec-Fetch-Site; legacy mutation và credential GET yêu cầu `X-Tinix-Request: 1`; UI tự gửi header, v1 vẫn dùng Bearer. Kiểm tra middleware và **Chrome gửi form từ HTTP server khác origin**: 403, không tạo backup. Backend thật sau build cũng chặn Host lạ/cross-origin/thiếu header. |
| F03 | OS file lock theo database, nằm ngoài data tree của recovery; acquire trước startup recovery. Worker thứ hai bị từ chối, không đổi trạng thái/attempt job đang chạy. Test tiến trình riêng xác minh lock giải phóng khi worker thoát; start/stop có thể chạy lại. |
| F04 | Cleanup chỉ chọn Python đúng cwd/project và entrypoint; Chrome phải có user-data-dir nằm đúng profile tree. Loại bỏ kill theo port và PID ghi cũ mà chưa xác minh. Fixture listener không liên quan/PID tái sử dụng/profile có prefix giống bị bỏ qua. |
| F05 | Serializer v1 ẩn recovery_codes cùng các credential khác, chỉ trả has_recovery_codes. API test với token chỉ có scope read không thấy mã hoặc mật khẩu fixture. |
| F06 | Worker/scheduler retry có backoff giới hạn và stop signal khi SQLITE_BUSY/LOCKED; lỗi không transient chuyển `failed`, health báo degraded. Test khóa SQLite thực rồi mở khóa xác minh cả hai runner còn sống và tự trở lại idle/running. |
| F07 | Bộ kiểm tra chung size/SHA256 của media snapshot tại YouTube API, Facebook Chrome và Chrome publishers trước upload/commit. Thiếu metadata hoặc file thay đổi bị từ chối; test thay bytes cùng size, đổi size, YouTube không gửi request và Facebook không submit. Meta/Instagram giữ kiểm tra có sẵn. |
| F08 | Lưu run ID trước dispatch, startup tìm image job chưa kết thúc và tiếp tục polling run đã lưu. Shutdown không mất ID; không tạo run thứ hai. Thiếu ID hoặc run không còn tồn tại chuyển failed với hướng dẫn kiểm tra. Cancellation chờ task dừng trước lưu cancelled; restore đóng task cũ trước thay DB. |

**Verification:** `BUILD.bat` exit 0; full unittest discover PASS (352 test cases, gồm 12 Playwright tests). Targeted UI/recovery/worker/provider suite PASS; compileall PASS; 14 JS modules `node --check` PASS; `pip check` PASS. Không thêm dependency, không thêm migration/schema.

**Local server:** backend trước build đã dừng, không có active task bị gián đoạn. Khởi động backend theo cấu hình .env của project, cửa sổ ẩn, không mở lại UI. Uvicorn PID **111176**, launcher PID 110572; process ownership theo cwd/command line, creation time sau code/build cuối. `http://127.0.0.1:8765/api/health`: version **1.0.44**, status **ok**, worker **idle**, active_jobs **0**, scheduler **running**. Index và api.js chứa version/header mới. Request kiểm tra an toàn không tạo job hoặc đăng bài.

**File thay đổi trong lượt sửa** (so sánh hash với baseline audit, giữ nguyên thay đổi có sẵn của người dùng):

- `.gitignore`
- `HUONG_DAN_SU_DUNG.md`
- `app/__init__.py`
- `app/api/routes.py`
- `app/api/v1.py`
- `app/cleanup.py`
- `app/db/content_repositories.py`
- `app/db/database.py`
- `app/db/repositories.py`
- `app/main.py`
- `app/platforms/providers/youtube.py`
- `app/services/facebook_publisher.py`
- `app/services/image_generation.py`
- `app/services/media.py`
- `app/services/recovery_bundle.py`
- `app/services/web_platform_publisher.py`
- `app/services/worker.py`
- `app/static/index.html`
- `app/static/js/api.js`
- `app/static/js/main.js`
- `docs/HUONG_DAN_SU_DUNG.md`
- `docs/VPS_READINESS.md`
- `hướng dẫn sử dụng.md`
- `tests/test_api.py`
- `tests/test_facebook_publisher.py`
- `tests/test_frontend_playwright.py`
- `tests/test_recovery_bundle.py`
- `tests/test_youtube_official_publisher.py`
- `app/api/local_boundary.py`
- `app/services/worker_lock.py`
- `tests/test_production_regressions.py`
- `FINAL_REVIEW.md`

Các file version/UI cache key/hướng dẫn sử dụng được Build cập nhật đồng bộ lên 1.0.44. `docs/VPS_READINESS.md` ghi quy tắc single-worker, restore reconciliation và header local API.

**Kết luận remediation:** hoàn tất sửa và kiểm chứng local cho 8/8 finding. Bản local đã build và đang chạy code mới. Chưa thực hiện thêm bài đăng thật, nghiệm thu provider live hay clean-machine/power-loss acceptance; các giới hạn đó trong audit vẫn áp dụng khi quyết định bật tự động cho capability cụ thể. Sau restore, cần xác minh các job bị cách ly với nền tảng trước khi tạo lần đăng thay thế. Refresh ứng dụng (Ctrl+F5 nếu tab cũ còn cache).

**Git:** không tạo commit, HEAD vẫn `fd0f7888fceb843dbd1750514b8998190b55357d`; staging vẫn trống. Evidence: `C:\Users\Admin\AppData\Local\Temp\tinix-final-review-20261002\fix-build.log`, `fix-ui.log`, `fix-regressions.log`, `fix-server-verification.json`, `fix-files.json`.


### Kiểm tra tiếp sau remediation — 03-10-2026 (UTC+7)

Backend 1.0.44 tiếp tục trả health `ok`, worker `idle` (0 active jobs), scheduler `running`; `/api/runtime` hoạt động. Kiểm tra read-only trên dữ liệu local: SQLite integrity `ok`, 0 foreign-key violations, schema vẫn 25; 23/23 media assets đúng size/SHA256 và nằm trong storage. Không có image job queued/running bị treo, không có publication job đang thực thi hoặc chờ chạy; phân bố trạng thái job giữ nguyên baseline audit. Log từ lần startup bản mới không ghi ERROR/CRITICAL.

Lượt này chỉ kiểm tra và cập nhật báo cáo; không sửa code/runtime, nên không cần build hoặc restart thêm. Kết quả build/full suite 352 tests của lượt remediation vẫn là kết quả kiểm chứng code. Chưa có dữ liệu để nghiệm thu bài đăng live: cần xác định account/target và nội dung cụ thể trước khi thực hiện bước đó. Evidence: `post-fix-integrity.json` trong thư mục evidence đã ghi phía trên.


### Live acceptance — 03-10-2026 (UTC+7)

Người dùng cho phép chọn account/nội dung bất kỳ để đăng thử và nhận URL. Đã chọn account **Thanh229tan**, Page **Tinix** (1106784475845782), route `official_api_only`, định dạng bài chữ. Nội dung ghi rõ thử nghiệm hệ thống Tinix Social Hub. Quy trình API bình thường: tạo content → request/approve revision → dry-run `dry_run_ready` → một real job → `succeeded`, publisher verification `verified`.

- Dry-run job: `0e96ee2a-b3f0-4b34-8cd1-861f60fe2a57`
- Real job: `92c05d2f-fb40-4ed4-b022-6acfef89bdd1`; attempts: 1
- Release: `e62a0b13-4d7f-48ec-bb18-0aba7ca28142`
- External ID: `1106784475845782_122133168092779083`
- URL bài đăng: [https://www.facebook.com/122132248658779083/posts/122133168092779083](https://www.facebook.com/122132248658779083/posts/122133168092779083)
- Published at: `2026-10-03T01:22:51.515274+00:00` (UTC)

Live acceptance **PASS cho Facebook Page text qua Meta API**. Không mở rộng kết luận này sang ảnh/video/album hoặc các nền tảng khác. Giữ bài đăng để người dùng kiểm tra URL. Lượt này không sửa code/runtime; không cần build/restart, không tạo Git commit.
