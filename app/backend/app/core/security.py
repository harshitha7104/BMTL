"""
Authentication, authorisation and abuse protection for ScrapTrust / BMTL.

Threat model (the app is meant for tens of thousands of users):
  - anonymous access to other people's conversations, uploads and feedback   -> login + per-object ownership
  - password guessing / credential stuffing                                    -> scrypt hashes, per-account and per-IP lockout
  - session theft / CSRF                                                       -> HMAC-signed, expiring, revocable HttpOnly
                                                                                  SameSite=Strict cookie + Origin check
  - cost / resource exhaustion (LLM calls, Whisper, OCR, uploads)              -> per-user rate limits, body size limits
  - privilege escalation (feedback export poisons retraining)                  -> roles: user < reviewer < admin
Design notes:
  - Passwords are never stored or logged; only scrypt(N=2**14, r=8, p=1) hashes with a per-user salt.
  - Tokens carry user, role, issue/expiry time, the user's token_version (bumped to revoke all sessions)
    and a random nonce; they are signed with SECRET_KEY (HMAC-SHA256) and compared in constant time.
  - The user store is a JSON file written atomically; for multi-server deployments replace UserStore and
    RateLimiter with a shared database/Redis and put SSO (OIDC) in front - the interfaces stay the same.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Dict, Optional

from fastapi import Depends, HTTPException, Request, status

from app.core.config import settings
from app.core.db import connection, transaction

ROLES = ("user", "reviewer", "admin")
COOKIE_NAME = "st_session"
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}
USERNAME_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789._-@")
# Audit M-08: "local-dev" owns everything created while login was paused; a real account with that name would inherit it.
GUEST_PREFIX = "guest-"     # public_demo guests; never a stored account
RESERVED_USERNAMES = {"local-dev", "root", "system", "anonymous"}
MIN_PASSWORD_LEN = 12
DEFAULT_SECRETS = {"", "change-me-in-production", "changeme", "secret"}


# --------------------------------------------------------------------------- passwords
def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt_b64), **SCRYPT)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password(secrets.token_hex(16))   # equalises timing for unknown usernames


def validate_new_password(password: str, username: str) -> None:
    if len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LEN} characters")
    if username.lower() in password.lower():
        raise ValueError("password must not contain the username")
    if len(set(password)) < 6:
        raise ValueError("password is too repetitive")


def normalise_username(username: str) -> str:
    u = (username or "").strip().lower()
    if not (3 <= len(u) <= 64) or not set(u) <= USERNAME_CHARS:
        raise ValueError("username must be 3-64 characters: letters, digits, . _ - @")
    if u in RESERVED_USERNAMES or u.startswith(GUEST_PREFIX):
        raise ValueError(f"'{u}' is a reserved name; choose another username")
    return u


# --------------------------------------------------------------------------- user store
@dataclass
class User:
    username: str
    role: str
    token_version: int = 0
    disabled: bool = False

    def has_role(self, role: str) -> bool:
        return ROLES.index(self.role) >= ROLES.index(role)


class UserStore:
    """User accounts in the shared SQLite database (multi-process safe). ``path`` is the legacy users.json
    location; the database sits next to it (security.db). A legacy JSON file is imported once, then renamed."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.db = self.path.with_name("security.db")
        self._migrate_json()

    def _migrate_json(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        with transaction(self.db) as c:
            for name, rec in data.items():
                c.execute("INSERT OR IGNORE INTO users(username, password, role, token_version, disabled, created_at) VALUES (?,?,?,?,?,?)",
                          (name, rec["password"], rec["role"], rec.get("token_version", 0), int(rec.get("disabled", False)),
                           rec.get("created_at", int(time.time()))))
        os.replace(self.path, self.path.with_suffix(".json.migrated"))

    def _read(self) -> Dict[str, dict]:
        rows = connection(self.db).execute("SELECT * FROM users").fetchall()
        return {r["username"]: {"role": r["role"], "disabled": bool(r["disabled"])} for r in rows}

    def count(self) -> int:
        return int(connection(self.db).execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def get(self, username: str) -> Optional[dict]:
        r = connection(self.db).execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(r) if r else None

    def user(self, username: str) -> Optional[User]:
        rec = self.get(username)
        if not rec:
            return None
        return User(username=username, role=rec["role"], token_version=rec["token_version"], disabled=bool(rec["disabled"]))

    def add(self, username: str, password: str, role: str = "user") -> None:
        username = normalise_username(username)
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        validate_new_password(password, username)
        hashed = hash_password(password)
        with transaction(self.db) as c:
            if c.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                raise ValueError(f"user '{username}' already exists")
            c.execute("INSERT INTO users(username, password, role, token_version, disabled, created_at) VALUES (?,?,?,?,?,?)",
                      (username, hashed, role, 0, 0, int(time.time())))

    def update(self, username: str, *, password: Optional[str] = None, role: Optional[str] = None, disabled: Optional[bool] = None,
               revoke_sessions: bool = False) -> None:
        if password is not None:
            validate_new_password(password, username)
            hashed = hash_password(password)
        if role is not None and role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        with transaction(self.db) as c:
            if not c.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                raise ValueError(f"no such user '{username}'")
            if password is not None:
                c.execute("UPDATE users SET password = ? WHERE username = ?", (hashed, username))
                revoke_sessions = True
            if role is not None:
                c.execute("UPDATE users SET role = ? WHERE username = ?", (role, username))
                revoke_sessions = True
            if disabled is not None:
                c.execute("UPDATE users SET disabled = ? WHERE username = ?", (int(disabled), username))
                revoke_sessions = True
            if revoke_sessions:
                c.execute("UPDATE users SET token_version = token_version + 1 WHERE username = ?", (username,))

    def authenticate(self, username: str, password: str) -> Optional[User]:
        try:
            username = normalise_username(username)
        except ValueError:
            verify_password(password, _DUMMY_HASH)
            return None
        rec = self.get(username)
        if rec is None:
            verify_password(password, _DUMMY_HASH)
            return None
        if not verify_password(password, rec["password"]) or rec["disabled"]:
            return None
        return self.user(username)


# --------------------------------------------------------------------------- tokens
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(user: User, secret: str, ttl_s: int) -> str:
    now = int(time.time())
    body = {"u": user.username, "r": user.role, "v": user.token_version, "iat": now, "exp": now + ttl_s, "n": secrets.token_hex(8)}
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    sig = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token: str, secret: str) -> Optional[dict]:
    try:
        payload, sig = token.split(".")
        expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        body = json.loads(_unb64(payload))
        if int(body["exp"]) < time.time():
            return None
        return body
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


# --------------------------------------------------------------------------- rate limiting
class RateLimiter:
    """Sliding-window limiter shared by all worker processes: Redis when settings.redis_url is set
    (several hosts), else the SQLite security database (one host, any number of workers)."""

    def __init__(self) -> None:
        self._redis = None

    def _db(self) -> Path:
        return Path(settings.users_path).with_name("security.db")

    def _r(self):
        if settings.redis_url and self._redis is None:
            import redis   # optional dependency, only for multi-host deployments
            self._redis = redis.Redis.from_url(settings.redis_url)
        return self._redis if settings.redis_url else None

    def hit(self, key: str, limit: int, window_s: float) -> bool:
        """Record one event; False when the limit is exceeded."""
        now = time.time()
        r = self._r()
        if r is not None:
            k = f"rl:{key}"
            pipe = r.pipeline()
            pipe.zremrangebyscore(k, 0, now - window_s)
            pipe.zcard(k)
            _, n = pipe.execute()
            if n >= limit:
                return False
            r.zadd(k, {f"{now}:{secrets.token_hex(4)}": now})
            r.expire(k, int(window_s) + 1)
            return True
        with transaction(self._db()) as c:
            n = c.execute("SELECT COUNT(*) FROM rate_events WHERE key = ? AND ts > ?", (key, now - window_s)).fetchone()[0]
            if n >= limit:
                return False
            c.execute("INSERT INTO rate_events(key, ts) VALUES (?, ?)", (key, now))
            return True

    def count(self, key: str, window_s: float) -> int:
        now = time.time()
        r = self._r()
        if r is not None:
            r.zremrangebyscore(f"rl:{key}", 0, now - window_s)
            return int(r.zcard(f"rl:{key}"))
        return int(connection(self._db()).execute("SELECT COUNT(*) FROM rate_events WHERE key = ? AND ts > ?",
                                                  (key, now - window_s)).fetchone()[0])

    def reset(self, key: str) -> None:
        r = self._r()
        if r is not None:
            r.delete(f"rl:{key}")
            return
        with transaction(self._db()) as c:
            c.execute("DELETE FROM rate_events WHERE key = ?", (key,))


def audit(event: str, username: Optional[str] = None, ip: Optional[str] = None, detail: str = "") -> None:
    """Append-only security audit trail (sign-ins, lockouts, refused links, role changes...). Never stores secrets."""
    try:
        with transaction(Path(settings.users_path).with_name("security.db")) as c:
            c.execute("INSERT INTO audit_log(ts, event, username, ip, detail) VALUES (?,?,?,?,?)",
                      (time.time(), event, username, ip, detail[:500]))
    except Exception:   # auditing must never break a request
        logging.getLogger("app.security").exception("audit write failed")
    # mirror into the end-to-end records log (admin calendar / search); the records store never raises
    from app.records.store import get_records

    get_records().log(username, f"security:{event}", summary=(detail or event)[:300], detail={"ip": ip, "detail": detail[:500]})


limiter = RateLimiter()
_store: Optional[UserStore] = None


def user_store() -> UserStore:
    global _store
    if _store is None or _store.path != Path(settings.users_path):
        _store = UserStore(settings.users_path)
    return _store


def client_ip(request: Request) -> str:
    # Only trust X-Forwarded-For when explicitly running behind a known reverse proxy.
    ip = request.client.host if request.client else "unknown"
    if settings.trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            ip = fwd.split(",")[0].strip()
    return ip


def rate_key_ip(ip: str) -> str:
    """Audit M-04: one IPv6 customer owns a whole /64 (2^64 addresses), so per-IP limits group IPv6 by /64."""
    import ipaddress

    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return ip
    if addr.version == 6:
        if addr.ipv4_mapped:
            return str(addr.ipv4_mapped)
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


def login_locked(name: str, ip: str) -> bool:
    """Locked when this account failed too often from this network, from ANY network (audit M-04: rotating IPs),
    or when this network failed too often across all accounts (password spraying)."""
    window = settings.login_lockout_minutes * 60
    net = rate_key_ip(ip)
    return (limiter.count(f"login:{name}:{net}", window) >= settings.login_max_failures
            or limiter.count(f"login-acct:{name}", window) >= settings.login_max_failures * 4
            or limiter.count(f"login-ip:{net}", window) >= settings.login_max_failures * 10)


def record_login_failure(name: str, ip: str) -> None:
    window = settings.login_lockout_minutes * 60
    net = rate_key_ip(ip)
    for key in (f"login:{name}:{net}", f"login-acct:{name}", f"login-ip:{net}"):
        limiter.hit(key, 10 ** 6, window)


# --------------------------------------------------------------------------- FastAPI dependencies
LOCAL_DEV_USER = User(username="local-dev", role="admin")


def issue_guest(response) -> User:
    """AUTH_MODE=public_demo: a new anonymous identity for this browser (signed cookie, own private space, role user)."""
    user = User(username=GUEST_PREFIX + secrets.token_hex(6), role="user")
    now = int(time.time())
    ttl = settings.guest_ttl_days * 86400
    body = {"u": user.username, "r": "user", "v": 0, "g": 1, "iat": now, "exp": now + ttl, "n": secrets.token_hex(8)}
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    sig = _b64(hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).digest())
    response.set_cookie(COOKIE_NAME, f"{payload}.{sig}", max_age=ttl, httponly=True, secure=settings.cookie_secure,
                        samesite="strict", path="/")
    return user


def current_user(request: Request) -> User:
    if settings.auth_mode == "disabled_local_dev":
        # Audit H-02: the startup check trusts a setting, so enforce "this computer only" on every request too.
        ip = request.client.host if request.client else ""
        if ip not in ("127.0.0.1", "::1", "localhost"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Local development mode only accepts requests from this computer")
        return LOCAL_DEV_USER
    token = request.cookies.get(COOKIE_NAME) or ""
    body = read_token(token, settings.secret_key) if token else None
    if body is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    if body.get("g"):   # a public_demo guest: valid only while that mode is on, never an admin, never a stored account
        if settings.auth_mode != "public_demo" or not str(body.get("u", "")).startswith(GUEST_PREFIX) or is_revoked(body.get("n", "")):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, sign in again")
        return User(username=body["u"], role="user")
    user = user_store().user(body["u"])
    if user is None or user.disabled or user.token_version != body["v"] or is_revoked(body.get("n", "")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, sign in again")
    return user


def _security_db() -> Path:
    return Path(settings.users_path).with_name("security.db")


def revoke_token(token: str) -> None:
    """Sign-out: this one session stops working immediately, even if the cookie was copied."""
    body = read_token(token, settings.secret_key) if token else None
    if body:
        with transaction(_security_db()) as c:
            c.execute("INSERT OR IGNORE INTO revoked_tokens(nonce, exp) VALUES (?, ?)", (body["n"], body["exp"]))


def is_revoked(nonce: str) -> bool:
    return bool(nonce) and connection(_security_db()).execute("SELECT 1 FROM revoked_tokens WHERE nonce = ?", (nonce,)).fetchone() is not None


def require_role(role: str):
    def dependency(user: User = Depends(current_user)) -> User:
        if not user.has_role(role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
        return user
    return dependency


def rate_limited(bucket: str, limit_setting: str, window_s: float = 60.0):
    """Per-user limit for expensive endpoints (LLM, Whisper, OCR, link fetches)."""
    def dependency(request: Request, user: User = Depends(current_user)) -> User:
        limit = int(getattr(settings, limit_setting))
        if not limiter.hit(f"{bucket}:{user.username}", limit, window_s):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Too many requests; limit is {limit} per minute")
        # public_demo: a new guest is one cookie away, so the same network shares one budget across all its guests
        if settings.auth_mode == "public_demo" and user.username.startswith(GUEST_PREFIX):
            net_limit = max(limit, settings.guest_ip_chat_per_minute)
            if not limiter.hit(f"{bucket}-net:{rate_key_ip(client_ip(request))}", net_limit, window_s):
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests from this network; wait a minute")
        return user
    return dependency


def startup_security_check() -> None:
    """Refuse to start in an unsafe configuration."""
    if settings.auth_mode not in ("required", "disabled_local_dev", "public_demo"):
        raise RuntimeError("AUTH_MODE must be 'required', 'public_demo' or 'disabled_local_dev'")
    if settings.auth_mode in ("required", "public_demo"):
        if settings.cookie_secure and not settings.trusted_hosts.strip():
            raise RuntimeError("TRUSTED_HOSTS must list this site's host name(s) in production (COOKIE_SECURE=true), "
                               "e.g. TRUSTED_HOSTS=scraptrust.example.com")
        if settings.secret_key in DEFAULT_SECRETS or len(settings.secret_key) < 32:
            raise RuntimeError("SECRET_KEY must be set to a random value of at least 32 characters "
                               "(e.g. python -c \"import secrets; print(secrets.token_urlsafe(48))\").")
    elif settings.host_binding not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError("AUTH_MODE=disabled_local_dev is only allowed when the server binds to localhost")
