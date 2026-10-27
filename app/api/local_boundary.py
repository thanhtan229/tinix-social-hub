from urllib.parse import urlsplit

from fastapi import Request
from starlette.responses import JSONResponse


def install_local_boundary(app, configured_host: str) -> None:
    allowed_hosts = {"localhost", "127.0.0.1", "::1"}
    if configured_host not in {"0.0.0.0", "::", ""}:
        allowed_hosts.add(configured_host.lower())

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        try:
            host = urlsplit("//" + request.headers.get("host", "")).hostname
        except ValueError:
            host = None
        if not host or host.lower() not in allowed_hosts:
            return JSONResponse({"detail": "Host không được phép."}, status_code=403)
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.url.netloc}"
        if (origin and origin != expected) or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Yêu cầu khác origin bị từ chối."}, status_code=403)
        mutation = request.method in {"POST", "PUT", "PATCH", "DELETE"}
        credential_read = request.url.path.startswith("/api/accounts/") and request.url.path.endswith("/credentials")
        # A custom header forces cross-origin browsers to preflight. No CORS permission is granted.
        if (mutation or credential_read) and not request.url.path.startswith("/api/v1/"):
            if request.headers.get("x-tinix-request") != "1":
                return JSONResponse({"detail": "Thiếu header bảo vệ yêu cầu local."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
