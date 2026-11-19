"""
HTTP hardening middleware.

- Security headers on every response (CSP, framing, sniffing, referrer, permissions, HSTS over HTTPS).
- Request body cap from Content-Length *before* the body is read (uploads are re-checked while streaming).
- CSRF defence in depth: state-changing requests must come from this origin (Origin/Referer check),
  on top of the SameSite=Strict session cookie.
- EarlyGuard (outermost, pure ASGI): Host allow-list, early 401 for unauthenticated writes, streamed size cap.
"""
from __future__ import annotations

from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings

CSP = ("default-src 'self'; "
       "script-src 'self'; "
       "style-src 'self' https://fonts.googleapis.com; "          # audit I-03/N-09: no inline styles, no cdnjs
       "font-src 'self' data: https://fonts.gstatic.com; "
       "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; "
       "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_request_mb * 1024 * 1024:
            return JSONResponse({"success": False, "error": "REQUEST_TOO_LARGE", "message": f"Request exceeds {settings.max_request_mb} MB"},
                                status_code=413)
        if request.method in UNSAFE_METHODS and not self._same_origin(request):
            return JSONResponse({"success": False, "error": "CROSS_SITE_REQUEST", "message": "Cross-site request refused"}, status_code=403)
        response = await call_next(request)
        h = response.headers
        h.setdefault("Content-Security-Policy", CSP)
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy", "camera=(self), microphone=(self), geolocation=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.url.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
        if settings.cookie_secure:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @staticmethod
    def _same_origin(request: Request) -> bool:
        source = request.headers.get("origin") or request.headers.get("referer")
        if not source:
            return True  # non-browser clients (curl, tests) send neither; the cookie is SameSite=Strict anyway
        parsed = urlparse(source)
        host = request.headers.get("host", "")
        if parsed.netloc == host:
            return True
        return f"{parsed.scheme}://{parsed.netloc}" in settings.cors_origins_list


# ----------------------------------------------------------------------------------------------- early guard
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
AUTH_EXEMPT = {"/api/v1/auth/login"}


def allowed_hosts() -> set[str] | None:
    """Host names this server answers to (None = any, only allowed when TRUSTED_HOSTS is unset outside production).

    Audit H-01: with login paused, a DNS-rebinding web page could reach the local server under its own host name.
    In local-dev mode only this computer's names are accepted unless TRUSTED_HOSTS says otherwise."""
    hosts = {h.strip().lower() for h in settings.trusted_hosts.split(",") if h.strip()}
    if settings.auth_mode == "disabled_local_dev":
        return hosts | LOOPBACK_HOSTS
    return (hosts | {"localhost", "127.0.0.1"}) if hosts else None   # loopback kept for container health checks


def _host_only(host_header: str) -> str:
    h = host_header.strip().lower()
    if h.startswith("["):                       # [::1]:8010
        return h.split("]")[0] + "]"
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def _has_valid_session(cookie_header: str) -> bool:
    from http.cookies import CookieError, SimpleCookie

    from app.core.security import COOKIE_NAME, read_token

    try:
        jar = SimpleCookie()
        jar.load(cookie_header)
    except CookieError:
        return False
    morsel = jar.get(COOKIE_NAME)
    return bool(morsel and read_token(morsel.value, settings.secret_key))


class EarlyGuard:
    """Pure-ASGI guard that runs BEFORE any request body is read (audit H-01, M-01):

    1. Host allow-list on every request (DNS rebinding / Host-header attacks).
    2. With login required, a state-changing /api request without a validly signed session cookie is refused with 401
       before FastAPI parses (and spools to disk) a multipart body. Full checks (revocation, disabled users) still run
       in ``current_user``; this is only the cheap, early filter.
    3. The request-size cap is enforced on the bytes actually streamed, so a chunked body without Content-Length
       cannot exceed MAX_REQUEST_MB.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        allowed = allowed_hosts()
        if allowed is not None and _host_only(headers.get("host", "")) not in allowed:
            return await JSONResponse({"detail": "Invalid host header"}, status_code=400)(scope, receive, send)
        path, method = scope.get("path", ""), scope.get("method", "GET")
        if (settings.auth_mode in ("required", "public_demo") and method in UNSAFE_METHODS and path.startswith("/api/")
                and path not in AUTH_EXEMPT and not _has_valid_session(headers.get("cookie", ""))):
            return await JSONResponse({"detail": "Sign in required"}, status_code=401)(scope, receive, send)

        limit, seen, over, replaced = settings.max_request_mb * 1024 * 1024, 0, False, False

        class _TooLarge(Exception):
            pass

        async def capped_receive():
            nonlocal seen, over
            message = await receive()
            if message.get("type") == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    over = True
                    raise _TooLarge()
            return message

        too_large = JSONResponse({"detail": f"Request exceeds {settings.max_request_mb} MB"}, status_code=413)

        async def guarded_send(message):
            nonlocal replaced
            if over:   # whatever the app answered after the overflow (often a generic 400), the real answer is 413
                if message["type"] == "http.response.start" and not replaced:
                    replaced = True
                    await too_large(scope, receive, send)
                return
            await send(message)

        try:
            return await self.app(scope, capped_receive, guarded_send)
        except _TooLarge:
            if not replaced:
                await too_large(scope, receive, send)
