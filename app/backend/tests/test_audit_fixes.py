"""Regression tests for the 2026-11-17 security audit (docs/SECURITY_AUDIT_2026-11-17.md). Each test is an attack that
worked before the fix."""
from __future__ import annotations

import io
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import security
from app.core.config import settings
from app.main import app
from tests.test_security import PASSWORD, secure  # noqa: F401  (fixture)


# ---------------------------------------------------------------- H-01 DNS rebinding / Host header (login paused)
@pytest.mark.asyncio
async def test_h01_foreign_host_refused_in_local_dev(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "auth_mode", "disabled_local_dev")
    monkeypatch.setattr(settings, "trusted_hosts", "")
    monkeypatch.setattr(settings, "users_file", str(tmp_path / "security" / "users.json"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://evil.example:8010") as evil:
        r = await evil.get("/api/v1/admin/records/calendar", headers={"Origin": "http://evil.example:8010"})
        assert r.status_code == 400
        r = await evil.patch("/api/v1/library/" + "a" * 32, json={"pinned": True}, headers={"Origin": "http://evil.example:8010"})
        assert r.status_code == 400
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8010") as ok:
        assert (await ok.get("/api/v1/auth/me")).status_code == 200


# ---------------------------------------------------------------- H-02 local-dev must only serve this computer
@pytest.mark.asyncio
async def test_h02_lan_client_refused_in_local_dev(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "auth_mode", "disabled_local_dev")
    monkeypatch.setattr(settings, "users_file", str(tmp_path / "security" / "users.json"))
    t = ASGITransport(app=app, client=("192.168.1.50", 50000))
    async with AsyncClient(transport=t, base_url="http://localhost:8010") as lan:
        assert (await lan.get("/api/v1/auth/me")).status_code == 403


def test_h01_production_requires_trusted_hosts(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "required")
    monkeypatch.setattr(settings, "secret_key", "s" * 48)
    monkeypatch.setattr(settings, "cookie_secure", True)
    monkeypatch.setattr(settings, "trusted_hosts", "")
    with pytest.raises(RuntimeError, match="TRUSTED_HOSTS"):
        security.startup_security_check()


# ---------------------------------------------------------------- M-01 nothing is read before sign-in; chunked cap
@pytest.mark.asyncio
async def test_m01_unauthenticated_upload_refused_before_body(secure):  # noqa: F811
    _, anon, _ = secure
    read = {"bytes": 0}

    async def body():
        for _ in range(50):
            read["bytes"] += 1 << 20
            yield b"\0" * (1 << 20)

    r = await anon.post("/api/v1/copilot/chat", content=body(), headers={"Content-Type": "multipart/form-data; boundary=XB"})
    assert r.status_code == 401
    assert read["bytes"] <= 2 << 20          # the server stopped before consuming the 50 MB body


@pytest.mark.asyncio
async def test_m01_chunked_body_over_cap_is_413(secure, monkeypatch):  # noqa: F811
    clients, _, _ = secure
    monkeypatch.setattr(settings, "max_request_mb", 2)

    async def body():
        yield b'--XB\r\nContent-Disposition: form-data; name="files"; filename="x.bin"\r\nContent-Type: application/octet-stream\r\n\r\n'
        for _ in range(5):
            yield b"\0" * (1 << 20)
        yield b"\r\n--XB--\r\n"

    r = await clients["alice"].post("/api/v1/copilot/chat", content=body(), headers={"Content-Type": "multipart/form-data; boundary=XB"})
    assert r.status_code == 413


# ---------------------------------------------------------------- H-03 spreadsheet decompression bomb
def _bomb(mb: int) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        with z.open("xl/sharedStrings.xml", "w") as f:
            for _ in range(mb):
                f.write(b"A" * (1 << 20))
    return buf.getvalue()


@pytest.mark.asyncio
async def test_h03_xlsx_bomb_refused_without_parsing(secure):  # noqa: F811
    clients, _, _ = secure
    data = _bomb(30)
    assert len(data) < 200_000
    r = await clients["alice"].post("/api/v1/copilot/chat", data={"message": "check"},
                                    files=[("files", ("lot.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))])
    assert r.status_code == 413 and "unusually compressed" in r.json()["detail"]


# ---------------------------------------------------------------- M-03 one writer per conversation across workers
def test_m03_lease_blocks_second_writer(tmp_path, monkeypatch):
    from app.copilot.service import CopilotInputError, CopilotService

    monkeypatch.setattr(settings, "users_file", str(tmp_path / "security" / "users.json"))
    a, b = object.__new__(CopilotService), object.__new__(CopilotService)   # two "workers": no shared Python state
    with a._session_lease("abcdef12"):
        with pytest.raises(CopilotInputError) as exc:
            with b._session_lease("abcdef12"):
                pass
        assert exc.value.status_code == 409
    with b._session_lease("abcdef12"):    # released: the other worker can write now
        pass


# ---------------------------------------------------------------- M-04 lockout across addresses; L-03 password change
@pytest.mark.asyncio
async def test_m04_account_locks_across_addresses(secure):  # noqa: F811
    _, _, _ = secure
    codes = []
    for i in range(8):   # 8 addresses x 3 guesses: each address stays under its own limit
        t = ASGITransport(app=app, client=(f"10.9.0.{i + 1}", 40000))
        async with AsyncClient(transport=t, base_url="http://localhost") as c:
            for j in range(3):
                codes.append((await c.post("/api/v1/auth/login", json={"username": "bob", "password": f"guess-{i}-{j}"})).status_code)
    assert 429 in codes and codes.index(429) <= settings.login_max_failures * 4


def test_m04_ipv6_grouped_by_64():
    assert security.rate_key_ip("2001:db8:1:2::1") == security.rate_key_ip("2001:db8:1:2:ffff::9")
    assert security.rate_key_ip("2001:db8:1:2::1") != security.rate_key_ip("2001:db8:1:3::1")
    assert security.rate_key_ip("::ffff:10.0.0.1") == "10.0.0.1"


@pytest.mark.asyncio
async def test_l03_password_change_locks_out(secure):  # noqa: F811
    clients, _, _ = secure
    codes = [(await clients["alice"].post("/api/v1/auth/password", json={"current_password": f"x{i}", "new_password": "y" * 20})).status_code
             for i in range(settings.login_max_failures + 2)]
    assert codes[-1] == 429


# ---------------------------------------------------------------- M-05 CSV formula injection
def test_m05_csv_cells_neutralised():
    from app.api.routes.admin_records import _csv_cell

    assert _csv_cell('=HYPERLINK("http://x")') == "'=HYPERLINK(\"http://x\")"
    for bad in ("+1", "-2", "@SUM(A1)", "\t=1"):
        assert _csv_cell(bad).startswith("'")
    assert _csv_cell("nickel 31.8") == "nickel 31.8" and _csv_cell(None) == ""


# ---------------------------------------------------------------- M-08 reserved account names
def test_m08_local_dev_name_is_reserved(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "users_file", str(tmp_path / "security" / "users.json"))
    store = security.UserStore(settings.users_path)
    with pytest.raises(ValueError, match="reserved"):
        store.add("local-dev", PASSWORD, "user")
    with pytest.raises(ValueError, match="reserved"):
        store.add("Local-Dev", PASSWORD, "admin")
    assert store.authenticate("local-dev", PASSWORD) is None


# ---------------------------------------------------------------- M-06 lab labels need a lab report reference
@pytest.mark.asyncio
async def test_m06_icp_label_requires_lab_reference(secure):  # noqa: F811
    _, _, store = secure
    store.add("ada", PASSWORD + "a", "admin")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as ada:
        assert (await ada.post("/api/v1/auth/login", json={"username": "ada", "password": PASSWORD + "a"})).status_code == 200
        r = await ada.post("/api/v1/admin/records/observations/1/icp", json={"values": {"Ni": 19.0}})
        assert r.status_code == 422
