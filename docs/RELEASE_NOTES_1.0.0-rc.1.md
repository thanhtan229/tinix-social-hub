# Tinix Social Studio 1.0.0-rc.1

This release candidate implements the approved Postiz-inspired roadmap while preserving Tinix's single-user, PC-first, Chrome-only design.

Highlights:

- Durable publication plans/releases and frozen snapshots.
- Calendar, timezone-aware posting slots and universal composer schemas.
- Release control center, notification center, safe retry/finalize and health warnings.
- Reusable SHA-256 Media Library with reference protection.
- Versioned Chrome adapters for four platforms with dry-run and commit-point gates.
- UI-scraped analytics and manual reconciliation.
- Scoped local API v1, DPAPI token, CLI and signed durable webhook outbox.
- Runtime contracts and optional standalone worker, with explicit VPS readiness blockers.

Schema history is append-only through v10. The upgrade creates a pre-migration SQLite backup. Live social-network publishing was deliberately not exercised by automated tests; run provider/account-specific dry-runs before any real publish.
