"""Records: activity log (admin only), per-user library (rename, pin, open, TXT/PDF download), structured readings,
lab labels. Attacker view: other users' items are 404, non-admins get no records at all."""
from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.copilot.engines.black_mass import BMTL_ROOT
from app.main import app
from app.records.pdf import write_text_pdf
from app.records.store import RecordsStore
from tests.test_security import PASSWORD, secure  # noqa: F401  (fixture)

MODEL = BMTL_ROOT / "models" / "real" / "bmtl_real_models.joblib"
READING = "Ni 31.8 Co 9.1 Mn 9.5 Fe 0.4 Cu 1.2 Al 1.5"


# ---------------------------------------------------------------- store (unit)
def test_store_activity_calendar_search_and_library_scoping(tmp_path):
    s = RecordsStore(tmp_path / "r.db")
    s.log("alice", "chat_message", summary="nickel cobalt bag 7", detail={"message": "bag 7 reading"}, ts=1794900000)
    s.log("bob", "chat_message", summary="lead paste", ts=1794900000 + 86400 * 40)
    assert sum(s.calendar()["counts"].values()) == 2
    year = int(next(iter(s.calendar()["counts"])))
    assert s.calendar(year)["level"] == "months"
    hits = s.query_activity(q="cobalt")
    assert hits["total"] == 1 and hits["items"][0]["username"] == "alice"
    assert s.query_activity(q='bag" OR 1=1 --')["total"] >= 0          # hostile search text is just words
    assert s.query_activity(username="bob")["total"] == 1

    item = s.add_library_item("alice", kind="report", title="Lot report.docx", text="hello")
    assert s.get_library_item("bob", item) is None                       # never another user's
    assert s.update_library_item("bob", item, title="x") is None
    s.update_library_item("alice", item, title="Renamed", pinned=True)
    got = s.get_library_item("alice", item)
    assert got["title"] == "Renamed" and got["pinned"] is True
    assert s.list_library("alice", q="hell")["total"] == 1 and s.list_library("bob")["total"] == 0
    assert s.list_library("alice", q="%")["total"] == 0                  # LIKE wildcards are escaped


def test_icp_label_validation(tmp_path):
    s = RecordsStore(tmp_path / "r.db")
    oid = s.add_observation("alice", "sess", {"label": "bag 1", "observed": {"Ni": 31.8}, "values": {"Ni": 30.2}, "bands": {"Ni": 2.0}})
    with pytest.raises(ValueError):
        s.set_icp(oid, {"Ni": 150.0}, by="ada")
    with pytest.raises(ValueError):
        s.set_icp(oid, {"Bogus": 1.0}, by="ada")
    assert s.set_icp(oid, {"Ni": 19.1, "Co": 6.4, "Li": 5.1}, by="ada")["label_state"] == "CONFIRMED"
    assert len(s.confirmed_observations()) == 1
    s.clear_icp(oid)
    assert s.confirmed_observations() == []


def test_pdf_writer_makes_a_valid_multipage_pdf():
    data = write_text_pdf("Title (x)", "line\n" * 200, "sub")
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF") and data.count(b"/Type /Page ") >= 3


# ---------------------------------------------------------------- API, attacker view
@pytest.mark.skipif(not MODEL.exists(), reason="BMTL models not present")
@pytest.mark.asyncio
async def test_library_and_admin_records_end_to_end(secure, isolated_records):  # noqa: F811
    clients, anon, store = secure
    alice, bob = clients["alice"], clients["bob"]
    r = await alice.post("/api/v1/copilot/chat", data={"message": READING})
    assert r.status_code == 200, r.text
    session_id = r.json()["session_id"]

    lib = (await alice.get("/api/v1/library")).json()
    assessment = next(i for i in lib["items"] if i["kind"] == "assessment")
    item_id = assessment["item_id"]
    assert (await bob.get("/api/v1/library")).json()["total"] == 0
    assert (await bob.get(f"/api/v1/library/{item_id}")).status_code == 404
    assert (await bob.get(f"/api/v1/library/{item_id}/download?format=pdf")).status_code == 404
    assert (await bob.patch(f"/api/v1/library/{item_id}", json={"title": "mine"})).status_code == 404
    assert (await anon.get("/api/v1/library")).status_code == 401

    r = await alice.patch(f"/api/v1/library/{item_id}", json={"title": "Bag 7 (north yard)", "pinned": True})
    assert r.status_code == 200 and r.json()["title"] == "Bag 7 (north yard)" and r.json()["pinned"] is True
    opened = (await alice.get(f"/api/v1/library/{item_id}")).json()
    assert opened["session_id"] == session_id and "ICP-equivalent" in opened["text"]
    txt = await alice.get(f"/api/v1/library/{item_id}/download?format=txt")
    assert txt.status_code == 200 and "attachment" in txt.headers["content-disposition"] and "Bag 7" in txt.text
    assert txt.headers["content-security-policy"].startswith("sandbox")
    pdf = await alice.get(f"/api/v1/library/{item_id}/download?format=pdf")
    assert pdf.content.startswith(b"%PDF") and pdf.headers["content-type"] == "application/pdf"

    # records are admin-only
    for path in ("/api/v1/admin/records/calendar", "/api/v1/admin/records/activity", "/api/v1/admin/records/observations",
                 "/api/v1/admin/records/learning", "/api/v1/admin/records/export"):
        assert (await alice.get(path)).status_code == 403, path
        assert (await anon.get(path)).status_code == 401, path
    store.add("ada", PASSWORD + "a", "admin")
    ada = AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost")
    assert (await ada.post("/api/v1/auth/login", json={"username": "ada", "password": PASSWORD + "a"})).status_code == 200

    cal = (await ada.get("/api/v1/admin/records/calendar")).json()
    assert sum(cal["counts"].values()) > 0
    found = (await ada.get("/api/v1/admin/records/activity", params={"q": "31.8", "username": "alice"})).json()
    assert found["total"] >= 1
    event = (await ada.get(f"/api/v1/admin/records/activity/{found['items'][-1]['id']}")).json()
    assert event["username"] == "alice"
    actions = set((await ada.get("/api/v1/admin/records/actions")).json()["actions"])
    assert {"chat_message", "tool:assess_black_mass_xrf", "assistant_reply", "library_rename", "library_download", "security:login_ok"} <= actions
    assert (await ada.get("/api/v1/admin/records/activity", params={"period": "2026-13-99x"})).status_code == 422

    obs = (await ada.get("/api/v1/admin/records/observations")).json()
    assert obs["counts"] == {"UNLABELLED": 1}
    oid = obs["items"][0]["id"]
    assert obs["items"][0]["observed"]["Ni"] == 31.8
    assert (await ada.post(f"/api/v1/admin/records/observations/{oid}/icp", json={"values": {"Ni": 200}})).status_code == 422
    assert (await alice.post(f"/api/v1/admin/records/observations/{oid}/icp", json={"values": {"Ni": 20}})).status_code == 403
    labelled = await ada.post(f"/api/v1/admin/records/observations/{oid}/icp", json={"values": {"Ni": 19.6, "Co": 6.4, "Li": 5.0}, "note": "LAB-1"})
    assert labelled.status_code == 200 and labelled.json()["label_state"] == "CONFIRMED"

    export = await ada.get("/api/v1/admin/records/export", params={"format": "jsonl"})
    lines = [json.loads(l) for l in export.text.splitlines()]
    assert export.status_code == 200 and any(l["action"] == "chat_message" for l in lines)
    assert any(e["action"] == "admin:export" for e in isolated_records.export_activity())        # admins are audited too
    await ada.aclose()

    # deleting the conversation hides its library items (the admin record stays)
    assert (await alice.delete(f"/api/v1/copilot/sessions/{session_id}")).status_code == 200
    assert (await alice.get("/api/v1/library")).json()["total"] == 0
    assert isolated_records.query_activity(action="conversation_deleted")["total"] == 1


def test_user_can_remove_own_library_item_only(tmp_path):
    s = RecordsStore(tmp_path / "r.db")
    item = s.add_library_item("alice", kind="report", title="r.docx")
    assert s.remove_library_item("bob", item) is False
    assert s.remove_library_item("alice", item) is True
    assert s.get_library_item("alice", item) is None and s.list_library("alice")["total"] == 0
