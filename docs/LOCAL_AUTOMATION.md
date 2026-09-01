# Local automation API v1

Tinix exposes a stable loopback API at `/api/v1`. This API controls Tinix itself; social publishing still runs exclusively through managed Chrome profiles.

## Authentication and scopes

The first startup creates a random `local-admin` token with `read`, `write`, and `publish` scopes. On Windows, its on-disk copy is encrypted with DPAPI for the current user. Retrieve it locally:

```powershell
.\.venv\Scripts\python.exe -m app.cli token
```

Use `Authorization: Bearer <token>`. Read routes need `read`; content changes and safe job control need `write`; a non-dry-run plan additionally needs `publish`.

## CLI

```powershell
.\.venv\Scripts\python.exe -m app.cli health
.\.venv\Scripts\python.exe -m app.cli jobs --limit 20
.\.venv\Scripts\python.exe -m app.cli releases --limit 20
.\.venv\Scripts\python.exe -m app.cli schedule --content ID --account ID --targets TARGET_ID --format post
```

`schedule` is dry-run unless `--real` is explicitly supplied. Real schedules still require the current content revision to be approved.

## Webhooks

Create subscriptions with `POST /api/v1/webhooks`. Deliveries use a durable SQLite outbox, exponential retry, `X-Tinix-Event`, `X-Tinix-Delivery`, and `X-Tinix-Signature: sha256=<HMAC>`. The signing secret is DPAPI-protected in the database and never returned by list endpoints.
