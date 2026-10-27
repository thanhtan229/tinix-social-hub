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

Worker startup now acquires an OS lock for the database before recovering interrupted jobs. A second worker is refused; the lock is released when its owning process exits. Stop the standalone worker before restoring through a controller with the embedded worker disabled.

Database and recovery-bundle restores quarantine unfinished real publication jobs as `unknown_result`, with `restore_reconciliation_required` and a commit marker. Verify each job against the social platform before resolving it or creating a replacement; restored jobs cannot automatically retry. Dry-run jobs retain their normal recovery behavior.

The local HTTP boundary validates Host and Origin. Legacy `/api` mutations and account credential reads require `X-Tinix-Request: 1`, which the WebUI supplies. Local automation should use Bearer-authenticated `/api/v1`; it does not require that browser header. These controls protect local browser access; they do not provide remote user authentication.

## Required adapters before VPS deployment

- PostgreSQL implementation of `StateDatabase`/`DurableQueue`, including leases and transactional claims.
- Object storage implementation of `ManagedStorage` with local staging for Chrome file inputs.
- Server secret manager implementation of `SecretStore`; DPAPI is intentionally Windows-user-bound.
- Remote Chrome worker implementing `BrowserRuntime`, preserving one isolated profile per account.
- Authentication for the full WebUI and legacy `/api` surface before any non-loopback bind.

Redis or Temporal is not a prerequisite. Add one only when measured scale or recovery requirements exceed the database queue.
