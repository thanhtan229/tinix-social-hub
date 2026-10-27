# Tổng quan Tinix Social Studio 1.0 RC

## Mục tiêu và quyết định cố định

Tinix là ứng dụng desktop-local, PC-first cho một người dùng: quản lý nội dung, approval, lịch phát hành, Chrome profiles, đối soát và automation nội bộ. Chrome automation là transport mặc định; YouTube video/Short và Facebook Page post/ảnh đơn/album ảnh/video MP4/Reel có official API. Một ảnh, album hai ảnh, video Page thường và Reel đã được thử live trên Page Tinix. Cookie/session Chrome ở nguyên trong profile, còn credential API được bảo vệ bằng DPAPI trên Windows.

## Luồng dữ liệu

```text
WebUI / CLI / local API v1
  -> content revision + approval
  -> publication plan -> frozen release per target
  -> durable job -> scheduler -> worker
  -> versioned Chrome/API adapter -> composer -> commit point -> verifier
  -> release/channel metrics (UI Chrome hoặc official read API) + notifications + webhook outbox
```

## Khối chức năng

| Khối | Trạng thái 1.0 RC |
|---|---|
| Calendar/composer | Week/month/list, range loading, timezone, posting slots, schema-driven settings |
| Content/approval | Revisions, variants, current-revision approval, AI structured drafts |
| Media Library | Streaming upload, SHA-256 dedupe, dimensions, alt/tags, references, orphan safety |
| Release control | Plans/releases, attempts/events/artifacts, retry preview, commit safety, manual finalize |
| Chrome providers | Facebook post; Instagram image/carousel; TikTok short video; YouTube video/Short; X post |
| Analytics | Post + channel snapshots; YouTube daily reports, source/unit/period provenance, manual or opt-in bounded refresh, account/target filters and pagination |
| Automation | Authenticated `/api/v1`, scoped DPAPI token, CLI, signed durable webhooks |
| Runtime | SQLite/local storage/DPAPI/managed Chrome behind explicit contracts; standalone worker supported |

## Safety gates

- Dry-run is the default and stops before the publish click.
- Real publishing requires approval of the current revision.
- Commit point is recorded before a non-idempotent click.
- Crash/timeout after commit becomes `unknown_result`; no automatic retry.
- Media and settings are frozen into each release snapshot.
- Unsupported analytics is distinct from a numeric zero; lifetime counters and daily intervals are stored and aggregated separately.
- Network publishing uses a per-target dual-transport router with frozen connection/scope evidence. YouTube official publishing is implemented; Facebook, Instagram, TikTok and X remain on Chrome pending official adapter and provider entitlement work.

## Operational status

Automated tests never log into or publish to a social network. All Chrome adapters remain `review_required` until a user performs dry-run against the current real UI for that account. VPS contracts exist, but `GET /api/runtime` correctly reports blockers and does not claim the local build is VPS-deployable.

Detailed references: [PLATFORM_ARCHITECTURE.md](PLATFORM_ARCHITECTURE.md), [LOCAL_AUTOMATION.md](LOCAL_AUTOMATION.md), [VPS_READINESS.md](VPS_READINESS.md), and [POSTIZ_BENCHMARK_PLAN.md](POSTIZ_BENCHMARK_PLAN.md).
