# PC-first, VPS-ready boundaries

Tinix currently remains a Windows PC application. `GET /api/runtime` reports the active adapters and explicit blockers; it must not claim `vps_deployable` while local-only backends are active.

The code now depends on five runtime contracts: `StateDatabase`, `DurableQueue`, `ManagedStorage`, `SecretStore`, and `BrowserRuntime`. Current implementations are SQLite/WAL, the job repository, local managed paths, Windows DPAPI, and managed local Chrome/CDP.

## Split controller and worker on one PC

Set `TINIX_EMBEDDED_WORKER=false` for the WebUI process, then run the worker separately:

```powershell
.\.venv\Scripts\python.exe -m app
.\.venv\Scripts\python.exe -m app.worker_entry
```

Both processes use the same append-only schema and durable job state. Run only one standalone worker with SQLite.

## Required adapters before VPS deployment

- PostgreSQL implementation of `StateDatabase`/`DurableQueue`, including leases and transactional claims.
- Object storage implementation of `ManagedStorage` with local staging for Chrome file inputs.
- Server secret manager implementation of `SecretStore`; DPAPI is intentionally Windows-user-bound.
- Remote Chrome worker implementing `BrowserRuntime`, preserving one isolated profile per account.
- Authentication for the full WebUI and legacy `/api` surface before any non-loopback bind.

Redis or Temporal is not a prerequisite. Add one only when measured scale or recovery requirements exceed the database queue.
