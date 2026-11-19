"""Security tests: written from an attacker's point of view against AUTH_MODE=required."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core import security
from app.core.config import settings
from app.core.security import COOKIE_NAME, hash_password, issue_token, read_token, User, verify_password
from app.main import app

PASSWORD = "correct-horse-battery-9"


@pytest_asyncio.fixture
async def secure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "local_storage_path", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "copilot_warmup", False)
    monkeypatch.setattr(settings, "auth_mode", "required")
    monkeypatch.setattr(settings, "secret_key", "t" * 48)
    monkeypatch.setattr(settings, "users_file", str(tmp_path / "security" / "users.json"))
    monkeypatch.setattr(security, "limiter", security.RateLimiter())
    import app.api.routes.auth as auth_routes
    monkeypatch.setattr(auth_routes, "limiter", security.limiter)
    store = security.user_store()
    store.add("alice", PASSWORD, "user")
    store.add("bob", PASSWORD + "x", "user")
    store.add("rita", PASSWORD + "r", "reviewer")
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        clients = {}
        for name, pw in (("alice", PASSWORD), ("bob", PASSWORD + "x"), ("rita", PASSWORD + "r")):
            c = AsyncClient(transport=transport, base_url="http://localhost")
            r = await c.post("/api/v1/auth/login", json={"username": name, "password": pw})
            assert r.status_code == 200, r.text
            clients[name] = c
        anon = AsyncClient(transport=transport, base_url="http://localhost")
        yield clients, anon, store
        for c in [*clients.values(), anon]:
            await c.aclose()


# ---------------------------------------------------------------- unit level
def test_password_hash_and_tokens():
    h = hash_password("x" * 20)
    assert h.startswith("scrypt$") and "x" * 20 not in h
    assert verify_password("x" * 20, h) and not verify_password("y" * 20, h)
    t = issue_token(User("alice", "user"), "s" * 40, 60)
    assert read_token(t, "s" * 40)["u"] == "alice"
    assert read_token(t, "other" * 10) is None                       # wrong key
    payload, sig = t.split(".")
    assert read_token(payload[:-2] + "AA." + sig, "s" * 40) is None   # tampered payload
    assert read_token(issue_token(User("a", "user"), "s" * 40, -1), "s" * 40) is None   # expired


def test_refuses_to_start_with_default_secret(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "required")
    monkeypatch.setattr(settings, "secret_key", "change-me-in-production")
    with pytest.raises(RuntimeError):
        security.startup_security_check()
    monkeypatch.setattr(settings, "auth_mode", "disabled_local_dev")
    monkeypatch.setattr(settings, "host_binding", "0.0.0.0")
    with pytest.raises(RuntimeError):
        security.startup_security_check()


def test_weak_passwords_rejected(tmp_path):
    store = security.UserStore(tmp_path / "u.json")
    for bad in ("short", "aaaaaaaaaaaaaaaa", "alice-is-my-password"):
        with pytest.raises(ValueError):
            store.add("alice", bad)


# ---------------------------------------------------------------- API level
@pytest.mark.asyncio
async def test_everything_requires_sign_in(secure):
    _, anon, _ = secure
    for method, url in [("GET", "/api/v1/copilot/sessions"), ("POST", "/api/v1/copilot/chat"), ("GET", "/api/v1/assessments"),
                        ("GET", "/api/v1/copilot/feedback/export"), ("POST", "/api/v1/copilot/transcribe")]:
        r = await anon.request(method, url)
        assert r.status_code == 401, (url, r.status_code)
    assert (await anon.get("/health")).status_code == 200
    assert (await anon.get("/docs")).status_code in (404, 405) or "swagger" not in (await anon.get("/docs")).text.lower()


@pytest.mark.asyncio
async def test_forged_cookie_rejected(secure):
    _, anon, _ = secure
    forged = issue_token(User("alice", "admin"), "not-the-server-key" * 3, 3600)
    anon.cookies.set(COOKIE_NAME, forged)
    assert (await anon.get("/api/v1/copilot/sessions")).status_code == 401


@pytest.mark.asyncio
async def test_users_cannot_see_each_others_conversations(secure):
    clients, _, _ = secure
    r = await clients["alice"].post("/api/v1/copilot/chat", data={"message": "What is black mass?"})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    assert sid in [s["session_id"] for s in (await clients["alice"].get("/api/v1/copilot/sessions")).json()["sessions"]]
    bob = clients["bob"]
    assert sid not in [s["session_id"] for s in (await bob.get("/api/v1/copilot/sessions")).json()["sessions"]]
    assert (await bob.get(f"/api/v1/copilot/sessions/{sid}")).status_code == 404            # 404, not 403: no probing
    assert (await bob.delete(f"/api/v1/copilot/sessions/{sid}")).status_code == 404
    r = await bob.post("/api/v1/copilot/chat", data={"message": "hi", "session_id": sid})
    assert r.status_code == 404
    assert (await bob.get(f"/api/v1/copilot/sessions/{sid}/attachments/document_1")).status_code == 404


@pytest.mark.asyncio
async def test_roles_and_feedback_export(secure):
    clients, _, _ = secure
    assert (await clients["alice"].get("/api/v1/copilot/feedback/export")).status_code == 403
    assert (await clients["rita"].get("/api/v1/copilot/feedback/export")).status_code == 200


@pytest.mark.asyncio
async def test_login_lockout_and_no_user_enumeration(secure):
    _, anon, _ = secure
    unknown = await anon.post("/api/v1/auth/login", json={"username": "nobody", "password": "x" * 12})
    wrong = await anon.post("/api/v1/auth/login", json={"username": "alice", "password": "x" * 12})
    assert unknown.status_code == wrong.status_code == 401 and unknown.json() == wrong.json()
    for _ in range(settings.login_max_failures):
        await anon.post("/api/v1/auth/login", json={"username": "alice", "password": "wrong-" * 3})
    locked = await anon.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD})
    assert locked.status_code == 429   # even the right password is refused during lockout


@pytest.mark.asyncio
async def test_disabling_a_user_revokes_live_sessions(secure):
    clients, _, store = secure
    assert (await clients["bob"].get("/api/v1/auth/me")).status_code == 200
    store.update("bob", disabled=True)
    assert (await clients["bob"].get("/api/v1/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_cookie_flags_and_security_headers(secure):
    _, anon, _ = secure
    r = await anon.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    h = r.headers
    assert "frame-ancestors 'none'" in h["content-security-policy"] and h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"


@pytest.mark.asyncio
async def test_cross_site_post_refused(secure):
    clients, _, _ = secure
    r = await clients["alice"].post("/api/v1/copilot/chat", data={"message": "hi"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_uploaded_html_is_never_served_inline(secure):
    clients, _, _ = secure
    evil = b"<html><script>fetch('/api/v1/copilot/sessions')</script></html>"
    r = await clients["alice"].post("/api/v1/copilot/chat", data={"message": "read this"}, files={"files": ("x.html", evil, "text/html")})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    att = (await clients["alice"].get(f"/api/v1/copilot/sessions/{sid}/attachments/document_1"))
    assert att.status_code == 200
    assert att.headers["content-type"].startswith("application/octet-stream")
    assert att.headers["content-disposition"].startswith("attachment")
    assert "sandbox" in att.headers["content-security-policy"]


@pytest.mark.asyncio
async def test_oversized_request_refused_before_reading(secure):
    clients, _, _ = secure
    r = await clients["alice"].post("/api/v1/copilot/chat", content=b"x", headers={"Content-Length": str(10 ** 10), "Content-Type": "multipart/form-data; boundary=x"})
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_zip_bomb_and_traversal(secure):
    clients, _, _ = secure
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("big.txt", b"0" * 50_000_000)
    r = await clients["alice"].post("/api/v1/copilot/chat", data={"message": "x"}, files={"files": ("bomb.zip", bomb.getvalue(), "application/zip")})
    assert r.status_code == 400 and "zip bomb" in r.text
    trav = io.BytesIO()
    with zipfile.ZipFile(trav, "w") as z:
        z.writestr("../../../../evil.csv", "Ni,Co,Mn,Fe\n18,7,9,1\n")
    r = await clients["alice"].post("/api/v1/copilot/chat", data={"message": "x"}, files={"files": ("t.zip", trav.getvalue(), "application/zip")})
    assert r.status_code == 200, r.text
    assert not (Path(settings.local_storage_path).parent / "evil.csv").exists()
    names = [a["filename"] for a in r.json().get("attachments", [])] if isinstance(r.json().get("attachments"), list) else []
    assert all("/" not in n and ".." not in n for n in names)


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost:8000/", "http://169.254.169.254/latest/meta-data/",
                                 "http://10.0.0.1/", "http://[::1]/", "file:///etc/passwd", "ftp://example.com/x",
                                 "http://user:pw@example.com/", "http://example.com:8080/"])
def test_ssrf_targets_refused(url):
    from app.copilot.engines.intake import IntakeRejected, vet_url
    with pytest.raises(IntakeRejected):
        vet_url(url)


# ---------------------------------------------------------------- production hardening (2026-11-17)
@pytest.mark.asyncio
async def test_logout_revokes_a_copied_cookie(secure):
    clients, anon, _ = secure
    stolen = clients["alice"].cookies.get(COOKIE_NAME)
    assert (await clients["alice"].post("/api/v1/auth/logout")).status_code == 200
    anon.cookies.set(COOKIE_NAME, stolen)
    assert (await anon.get("/api/v1/auth/me")).status_code == 401


def _hammer(args):
    users_file, n = args
    from app.core.config import settings as s
    s.users_file = users_file
    from app.core.security import RateLimiter
    lim = RateLimiter()
    return sum(lim.hit("shared-key", 25, 60) for _ in range(n))


def test_rate_limit_is_shared_across_worker_processes(tmp_path):
    """Four separate processes hitting one key: exactly the limit gets through in total (not 4x)."""
    import multiprocessing as mp
    users_file = str(tmp_path / "security" / "users.json")
    with mp.get_context("spawn").Pool(4) as pool:
        allowed = sum(pool.map(_hammer, [(users_file, 20)] * 4))
    assert allowed == 25


@pytest.mark.asyncio
async def test_storage_quota(secure, monkeypatch):
    clients, _, _ = secure
    monkeypatch.setattr(settings, "user_storage_quota_mb", 0)
    r = await clients["alice"].post("/api/v1/copilot/chat", data={"message": "x"}, files={"files": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 413 and "storage is full" in r.text


@pytest.mark.asyncio
async def test_sidebar_uses_owner_index(secure):
    clients, _, _ = secure
    for i in range(3):
        assert (await clients["bob"].post("/api/v1/copilot/chat", data={"message": f"question {i}"})).status_code == 200
    mine = (await clients["bob"].get("/api/v1/copilot/sessions")).json()["sessions"]
    theirs = (await clients["rita"].get("/api/v1/copilot/sessions")).json()["sessions"]
    assert len(mine) == 3 and theirs == []


def test_untrusted_host_refused(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    monkeypatch.setattr(settings, "trusted_hosts", "bmtl.example.com")
    monkeypatch.setattr(settings, "auth_mode", "disabled_local_dev")
    with TestClient(create_app()) as tc:
        assert tc.get("/health", headers={"Host": "evil.example"}).status_code == 400
        assert tc.get("/health", headers={"Host": "bmtl.example.com"}).status_code == 200


def test_heavy_jobs_answer_busy_when_full(monkeypatch):
    import app.core.limits as limits
    monkeypatch.setattr(settings, "heavy_job_slots", 1)
    monkeypatch.setattr(settings, "heavy_job_wait_s", 0)
    monkeypatch.setattr(limits, "_slots", None)
    with limits.heavy_job():
        with pytest.raises(limits.ServerBusy):
            with limits.heavy_job():
                pass
    monkeypatch.setattr(limits, "_slots", None)


def test_audit_log_records_failed_sign_in(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "users_file", str(tmp_path / "security" / "users.json"))
    security.audit("login_failed", "mallory", "203.0.113.9", "test")
    from app.core.db import connection
    row = connection(tmp_path / "security" / "security.db").execute("SELECT event, username, ip FROM audit_log").fetchone()
    assert tuple(row) == ("login_failed", "mallory", "203.0.113.9")
