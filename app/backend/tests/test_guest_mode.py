"""AUTH_MODE=public_demo (open testing): no login screen, every browser gets its own private guest space.
Written from an attacker's point of view: guests must not see each other, must not be admins, and must not be able to
dodge the limits by minting new guests."""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core import security
from app.core.config import settings
from app.core.security import COOKIE_NAME
from app.main import app

PASSWORD = "correct-horse-battery-9"


@pytest_asyncio.fixture
async def demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "local_storage_path", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "copilot_warmup", False)
    monkeypatch.setattr(settings, "auth_mode", "public_demo")
    monkeypatch.setattr(settings, "secret_key", "d" * 48)
    monkeypatch.setattr(settings, "users_file", str(tmp_path / "security" / "users.json"))
    monkeypatch.setattr(security, "limiter", security.RateLimiter())
    import app.api.routes.auth as auth_routes
    monkeypatch.setattr(auth_routes, "limiter", security.limiter)
    store = security.user_store()
    store.add("owner", PASSWORD, "admin")
    async with app.router.lifespan_context(app):
        def browser(ip="203.0.113.10"):
            return AsyncClient(transport=ASGITransport(app=app, client=(ip, 40000)), base_url="http://localhost")
        yield browser, store


@pytest.mark.asyncio
async def test_first_visit_gets_a_private_guest_with_no_login(demo):
    browser, _ = demo
    async with browser() as a:
        me = await a.get("/api/v1/auth/me")
        assert me.status_code == 200 and me.json()["username"].startswith("guest-") and me.json()["role"] == "user"
        assert COOKIE_NAME in a.cookies
        again = await a.get("/api/v1/auth/me")
        assert again.json()["username"] == me.json()["username"]          # same browser keeps its space
        r = await a.post("/api/v1/copilot/chat", data={"message": "what can you do?"})
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_guests_cannot_see_each_other_or_records(demo):
    browser, _ = demo
    async with browser() as a, browser("198.51.100.7") as b:
        await a.get("/api/v1/auth/me")
        await b.get("/api/v1/auth/me")
        sid = (await a.post("/api/v1/copilot/chat", data={"message": "Ni 31.8 Co 9.1 Mn 9.5"})).json()["session_id"]
        assert (await b.get(f"/api/v1/copilot/sessions/{sid}")).status_code == 404
        assert (await b.get("/api/v1/copilot/sessions")).json()["sessions"] == []
        assert (await b.get("/api/v1/library")).json()["total"] == 0
        assert (await a.get("/api/v1/library")).json()["total"] >= 1
        for path in ("/api/v1/admin/records/calendar", "/api/v1/admin/records/activity", "/api/v1/admin/records/export"):
            assert (await a.get(path)).status_code == 403, path


@pytest.mark.asyncio
async def test_no_cookie_no_writes_and_forged_guests_rejected(demo):
    browser, _ = demo
    async with browser() as anon:
        assert (await anon.post("/api/v1/copilot/chat", data={"message": "hi"})).status_code == 401
        anon.cookies.set(COOKIE_NAME, "eyJ1IjoiZ3Vlc3QtYWRtaW4iLCJnIjoxfQ.forged")
        assert (await anon.get("/api/v1/copilot/sessions")).status_code == 401


@pytest.mark.asyncio
async def test_guest_tokens_stop_working_when_open_testing_ends(demo, monkeypatch):
    browser, _ = demo
    async with browser() as a:
        await a.get("/api/v1/auth/me")
        monkeypatch.setattr(settings, "auth_mode", "required")
        assert (await a.get("/api/v1/copilot/sessions")).status_code == 401


@pytest.mark.asyncio
async def test_new_guests_are_rate_limited_per_network(demo, monkeypatch):
    browser, _ = demo
    monkeypatch.setattr(settings, "guests_per_ip_per_hour", 3)
    codes = []
    for _ in range(5):
        async with browser("192.0.2.55") as fresh:                      # new browser = no cookie
            codes.append((await fresh.get("/api/v1/auth/me")).status_code)
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]
    async with browser("192.0.2.99") as other:                          # a different network is unaffected
        assert (await other.get("/api/v1/auth/me")).status_code == 200


@pytest.mark.asyncio
async def test_chat_limit_is_shared_by_all_guests_of_a_network(demo, monkeypatch):
    browser, _ = demo
    monkeypatch.setattr(settings, "rate_limit_per_minute", 2)
    monkeypatch.setattr(settings, "guest_ip_chat_per_minute", 3)
    codes = []
    for _ in range(3):                                                   # three fresh guests, same network
        async with browser("192.0.2.77") as g:
            await g.get("/api/v1/auth/me")
            for _ in range(2):
                codes.append((await g.post("/api/v1/copilot/chat", data={"message": "hello"})).status_code)
    assert codes.count(200) == 3 and 429 in codes


@pytest.mark.asyncio
async def test_owner_can_still_sign_in_as_admin(demo):
    browser, _ = demo
    async with browser() as owner:
        r = await owner.post("/api/v1/auth/login", json={"username": "owner", "password": PASSWORD})
        assert r.status_code == 200 and r.json()["role"] == "admin"
        assert (await owner.get("/api/v1/admin/records/calendar")).status_code == 200


def test_guest_names_cannot_be_registered(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "users_file", str(tmp_path / "security" / "users.json"))
    with pytest.raises(ValueError, match="reserved"):
        security.UserStore(settings.users_path).add("guest-abc123", PASSWORD, "admin")


def test_public_demo_requires_a_strong_secret_and_trusted_hosts(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "public_demo")
    monkeypatch.setattr(settings, "cookie_secure", True)
    monkeypatch.setattr(settings, "trusted_hosts", "")
    monkeypatch.setattr(settings, "secret_key", "s" * 48)
    with pytest.raises(RuntimeError, match="TRUSTED_HOSTS"):
        security.startup_security_check()
    monkeypatch.setattr(settings, "trusted_hosts", "x.example")
    monkeypatch.setattr(settings, "secret_key", "short")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        security.startup_security_check()


@pytest.mark.asyncio
async def test_public_records_are_view_only_and_hide_ips(demo, monkeypatch):
    browser, _ = demo
    monkeypatch.setattr(settings, "public_records", True)
    async with browser() as a, browser("198.51.100.20") as b:
        assert (await a.get("/api/v1/auth/me")).json()["records_visible"] is True
        await b.get("/api/v1/auth/me")
        await b.post("/api/v1/copilot/chat", data={"message": "Ni 31.8 Co 9.1 Mn 9.5 Fe 0.4"})
        acts = (await a.get("/api/v1/admin/records/activity")).json()
        assert acts["total"] >= 1 and all(not e["action"].startswith("security:") for e in acts["items"])
        assert any(e["action"] == "chat_message" for e in acts["items"])                 # everyone's test inputs are visible
        export = (await a.get("/api/v1/admin/records/export", params={"format": "jsonl"})).text
        assert "security:" not in export and "198.51.100.20" not in export and "203.0.113.10" not in export
        obs = (await a.get("/api/v1/admin/records/observations")).json()
        assert obs["total"] >= 1
        # but nobody except the admin can change anything
        assert (await a.post(f"/api/v1/admin/records/observations/{obs['items'][0]['id']}/icp",
                             json={"values": {"Ni": 20.0}, "note": "LAB-1"})).status_code == 403
        assert (await a.delete(f"/api/v1/admin/records/observations/{obs['items'][0]['id']}/icp")).status_code == 403
    monkeypatch.setattr(settings, "public_records", False)
    async with browser("198.51.100.30") as c:
        assert (await c.get("/api/v1/auth/me")).json()["records_visible"] is False
        assert (await c.get("/api/v1/admin/records/activity")).status_code == 403
