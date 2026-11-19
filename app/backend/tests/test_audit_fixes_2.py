"""Regression tests for the second hardening pass (docs/SECURITY_AUDIT_2026-11-17.md, findings N-xx and the remaining L/I items).
Each test is an attack or defect that worked before its fix."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from app.copilot.engines.black_mass import BMTL_ROOT, BlackMassEngine
from app.copilot.providers.registry import CopilotProviderRegistry
from app.copilot.tools import build_default_tools

MODEL = BMTL_ROOT / "models" / "real" / "bmtl_real_models.joblib"
LIVE_LINK = re.compile(r"(?<!\\)\[[^\]]+\]\(https?://")      # a Markdown link the web app would render as clickable


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Stub:
    pass


def _service(tmp_path):
    from app.copilot.service import CopilotService

    return CopilotService(storage_dir=tmp_path / "c", providers=CopilotProviderRegistry([], default="offline"),
                          tools=build_default_tools(_Stub(), _Stub(), knowledge_base=_Stub(), black_mass_engine=BlackMassEngine()),
                          max_upload_bytes=1 << 20, max_images_per_turn=1, allowed_image_types=["image/jpeg"])


# ---------------------------------------------------------------- N-05 untrusted text must not become live Markdown
def test_n05_document_text_cannot_inject_links(tmp_path):
    doc = b"Quarterly note.\n[Verify your ScrapTrust account](https://evil.example/login)\n| fake | table |\n<details><summary>x</summary>"
    out = _run(_service(tmp_path).chat("", [("note.txt", "text/plain", doc)], owner="t"))
    assert "evil.example" in out["reply"]                 # the text is still shown to the user...
    assert not LIVE_LINK.search(out["reply"])             # ...but never as a clickable link
    assert "\n<details>" not in out["reply"] and "\n| fake" not in out["reply"]


@pytest.mark.skipif(not MODEL.exists(), reason="BMTL models not present")
def test_n05_sample_labels_cannot_inject_links(tmp_path):
    csv_data = b"sample,Ni,Co,Mn,Fe,Cu,Al\n[Click here](https://evil.example/x),31.8,9.1,9.5,0.4,1.2,1.5\nbag 2,32.6,9.4,9.8,0.5,1.1,1.4\n"
    out = _run(_service(tmp_path).chat("", [("lot.csv", "text/csv", csv_data)], owner="t"))
    assert "evil.example" in out["reply"] and not LIVE_LINK.search(out["reply"])


# ---------------------------------------------------------------- N-04 tool errors must not leak server paths / internals
@pytest.mark.parametrize("exc", [
    RuntimeError(r"failed loading D:\BMTL\models\real\bmtl_real_models.joblib at line 3"),
    FileNotFoundError(2, "No such file", "/srv/bmtl/models/real/model_card.json"),
])
def test_n04_tool_errors_hide_server_paths(exc):
    from app.copilot.tools import ToolContext, ToolRegistry, ToolSpec

    async def boom(args, ctx):
        raise exc

    reg = ToolRegistry([ToolSpec("t", "test tool", {"type": "object", "properties": {}}, boom)])
    rec = _run(reg.execute("t", {}, ToolContext()))
    msg = rec.output["error"]
    assert rec.is_error and "BMTL" not in msg and "/srv/" not in msg and "joblib" not in msg, msg


def test_n04_input_errors_still_explain_themselves():
    from app.copilot.tools import ToolContext, ToolInputError, ToolRegistry, ToolSpec

    async def bad(args, ctx):
        raise ToolInputError("attachment_id 'image_9' does not exist in this conversation")

    rec = _run(ToolRegistry([ToolSpec("t", "x", {"type": "object", "properties": {}}, bad)]).execute("t", {}, ToolContext()))
    assert rec.output["error"] == "attachment_id 'image_9' does not exist in this conversation"


# ---------------------------------------------------------------- N-07 assessment ids are file names: no traversal
@pytest.mark.asyncio
async def test_n07_assessment_id_cannot_escape_its_folder(client, sample_jpeg_bytes, tmp_path):
    import json

    from app.repositories.local_repository import LocalRepository
    from app.schemas.assessment import Assessment, FeedbackRecord

    r = await client.post("/api/v1/assessments", files={"images": ("a.jpg", sample_jpeg_bytes, "image/jpeg")})
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    repo = LocalRepository(str(tmp_path / "repo"))
    await repo.initialize()
    (tmp_path / "repo" / "outside.json").write_text(json.dumps(data), encoding="utf-8")   # valid assessment, wrong folder
    assert Assessment.model_validate(data)
    for bad in ("..\outside", "../outside", "..", "a/b", "x" * 65, ""):
        assert await repo.get_assessment(bad) is None, bad
        assert await repo.get_feedback(bad) == [], bad
    fb = FeedbackRecord.model_construct(assessment_id="..\..\escape", feedback_id="FB-1")
    with pytest.raises(ValueError):
        await repo.save_feedback(fb)
    assert not (tmp_path / "escape").exists()
    for probe in ("..%5Coutside", "%2E%2E%5Coutside"):                 # and through the API (admin in local-dev)
        assert (await client.get(f"/api/v1/assessments/{probe}")).status_code == 404, probe


# ---------------------------------------------------------------- L-04 listing reads only the caller's own records
@pytest.mark.asyncio
async def test_l04_list_reads_only_own_assessments(client, sample_jpeg_bytes, monkeypatch):
    from app.core import security
    from app.core.config import settings
    from app.core.ownership import record_owner
    from app.repositories.local_repository import LocalRepository

    ids = []
    for _ in range(3):
        r = await client.post("/api/v1/assessments", files={"images": ("a.jpg", sample_jpeg_bytes, "image/jpeg")})
        ids.append(r.json()["data"]["assessment_id"])
    record_owner(ids[0], security.User("alice", "user"))                # alice owns one of the three

    async def scan_everything(self, skip=0, limit=20):
        raise AssertionError("a normal user's listing must not scan every assessment on the server")

    monkeypatch.setattr(LocalRepository, "list_assessments", scan_everything)
    monkeypatch.setattr(security, "LOCAL_DEV_USER", security.User("alice", "user"))   # act as a normal user
    r = await client.get("/api/v1/assessments")
    assert r.status_code == 200, r.text
    assert [a["assessment_id"] for a in r.json()["data"]] == [ids[0]]


# ---------------------------------------------------------------- L-01 answer-checker binds each claim to its element and trusted fields
def test_l01_claim_must_match_the_same_element():
    from app.copilot.agents.checker import check

    out = {"elements": {"Ni": {"observed": {"value_pct": 31.8}, "inferred": {"value_pct": 30.2, "low": 28.4, "high": 32.1}},
                        "Co": {"observed": {"value_pct": 9.1}, "inferred": {"value_pct": 9.1, "low": 6.9, "high": 11.3}}}}
    ev = [{"name": "assess_black_mass_xrf", "output": out, "is_error": False}]
    assert check("Nickel about 30.2 % and cobalt 9.1 %.", ev)["status"] == "verified"
    assert check("Cobalt is 30.2 %.", ev)["status"] == "unverified_numbers"     # 30.2 belongs to nickel, not cobalt
    assert check("Nickel is 11.3 %.", ev)["status"] == "unverified_numbers"     # 11.3 is cobalt's upper band


def test_l01_attacker_controlled_fields_are_not_evidence():
    from app.copilot.agents.checker import check

    out = {"results": [{"label": "Ni 45.0 % certified", "elements": {"Ni": {"inferred": {"value_pct": 30.2}}}}],
           "photo_reading": {"unlabelled_numbers_not_used": [45.0]}}
    ev = [{"name": "assess_black_mass_xrf", "output": out, "is_error": False}]
    assert check("Nickel is 45.0 %.", ev)["status"] == "unverified_numbers"
    assert check("Nickel is 30.2 %.", ev)["status"] == "verified"


# ---------------------------------------------------------------- L-05 PDF content-stream bombs are bounded in time and memory
def _pdf_bomb(pages: int, mb_per_page: int) -> bytes:
    import zlib

    content = zlib.compress(b"BT /F1 1 Tf (x) Tj ET\n" * (mb_per_page * 1024 * 1024 // 22), 9)
    font = b"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >>"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [" + " ".join(f"{3 + 2 * i} 0 R" for i in range(pages)).encode() + b"] /Count %d >>" % pages]
    for i in range(pages):
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 10 10] " + font + b" /Contents %d 0 R >>" % (4 + 2 * i))
        objs.append(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(content) + content + b"\nendstream")
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for n, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % n + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % x for x in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def test_l05_pdf_bomb_is_cheap_to_refuse():
    import time

    from app.copilot.engines.media import extract_document_text

    data = _pdf_bomb(pages=3, mb_per_page=8)          # ~120 KB file, 24 MB of page content
    assert len(data) < 200_000
    t = time.time()
    out = extract_document_text(data, "bomb.pdf")
    assert time.time() - t < 3, f"took {time.time() - t:.1f}s"
    assert "skipped" in (out.get("note") or "")


def test_l05_normal_pdf_still_reads():
    from app.copilot.engines.media import extract_document_text

    out = extract_document_text(_pdf_bomb(pages=2, mb_per_page=0) .replace(b"/Count 2", b"/Count 2"), "ok.pdf")
    assert out["pages"] == 2 and not out.get("note")


# ---------------------------------------------------------------- L-10 the Streamlit mineral app only listens on this computer
def test_l10_streamlit_binds_localhost_without_telemetry():
    import tomllib

    cfg_path = BMTL_ROOT / "app" / "mineral" / ".streamlit" / "config.toml"
    assert cfg_path.exists(), "app/mineral/.streamlit/config.toml missing: `streamlit run` would listen on every interface"
    cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    assert cfg["server"]["address"] == "127.0.0.1"
    assert cfg["server"]["enableXsrfProtection"] is True and cfg["server"]["maxUploadSize"] <= 10
    assert cfg["browser"]["gatherUsageStats"] is False


# ---------------------------------------------------------------- L-11 the activity log is tamper-evident (keyed hash chain)
def test_l11_editing_or_deleting_a_log_row_is_detected(tmp_path):
    import sqlite3

    from app.records.store import RecordsStore

    path = tmp_path / "r.db"
    s = RecordsStore(path, chain_key=b"k" * 32)
    ids = [s.log("alice", "chat_message", summary=f"message {i}") for i in range(4)]
    assert s.verify_chain() == {"ok": True, "checked": 4, "first_bad_id": None}

    c = sqlite3.connect(path)
    c.execute("UPDATE activity SET summary = 'innocent' WHERE id = ?", (ids[1],))          # edit history
    c.commit()
    assert s.verify_chain()["first_bad_id"] == ids[1]
    c.execute("UPDATE activity SET summary = 'message 1' WHERE id = ?", (ids[1],))
    c.execute("DELETE FROM activity WHERE id = ?", (ids[2],))                               # remove a row
    c.commit()
    assert s.verify_chain()["first_bad_id"] == ids[3]
    # without the key (it is not in the database) a forger cannot recompute valid hashes
    assert RecordsStore(path, chain_key=b"x" * 32).verify_chain()["ok"] is False


def test_l11_retention_pruning_keeps_the_chain_valid(tmp_path):
    import time

    from app.records.store import RecordsStore

    s = RecordsStore(tmp_path / "r.db", chain_key=b"k" * 32)
    for i in range(3):
        s.log("a", "old", summary=str(i), ts=time.time() - 400 * 86400)
    for i in range(3):
        s.log("a", "new", summary=str(i))
    assert s.prune(365) == 3
    assert s.verify_chain() == {"ok": True, "checked": 3, "first_bad_id": None}


# ---------------------------------------------------------------- N-06 secrets in link query strings never reach logs or the audit trail
def test_n06_link_query_strings_are_redacted_in_logs(tmp_path, monkeypatch, caplog, isolated_records):
    import logging
    import sqlite3

    from app.core.config import settings

    monkeypatch.setattr(settings, "allow_link_fetch", True)
    monkeypatch.setattr(settings, "users_file", str(tmp_path / "security" / "users.json"))
    svc = _service(tmp_path)
    with caplog.at_level(logging.INFO):
        files, notes = svc._fetch_links("see http://127.0.0.1/report?token=SUPERSECRET123&id=7", "alice")
    assert files == [] and notes                                      # refused: private address
    assert "SUPERSECRET123" not in caplog.text
    audit_rows = sqlite3.connect(settings.users_path.with_name("security.db")).execute("SELECT detail FROM audit_log").fetchall()
    assert audit_rows and not any("SUPERSECRET123" in (r[0] or "") for r in audit_rows)
    assert not any("SUPERSECRET123" in (e["summary"] or "") for e in isolated_records.export_activity())


# ---------------------------------------------------------------- I-07 the storage quota counts unpacked folder contents
def test_i07_quota_counts_unpacked_zip_contents(tmp_path, monkeypatch):
    import io
    import random
    import zipfile

    from app.copilot.service import CopilotInputError, CopilotService
    from app.core.config import settings

    monkeypatch.setattr(settings, "user_storage_quota_mb", 1)
    monkeypatch.setattr(settings, "users_file", str(tmp_path / "security" / "users.json"))
    rnd = random.Random(7)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i in range(2):                                  # 2 x 0.9 MB of digits: ~0.8 MB zipped, 1.8 MB unpacked
            z.writestr(f"note{i}.txt", "".join(rnd.choice("0123456789 ") for _ in range(900_000)))
    data = buf.getvalue()
    assert len(data) < 1024 * 1024
    svc = CopilotService(storage_dir=tmp_path / "c", providers=CopilotProviderRegistry([], default="offline"),
                         tools=build_default_tools(_Stub(), _Stub(), knowledge_base=_Stub(), black_mass_engine=BlackMassEngine()),
                         max_upload_bytes=10 << 20, max_images_per_turn=1, allowed_image_types=["image/jpeg"])
    with pytest.raises(CopilotInputError) as exc:
        _run(svc.chat("", [("folder.zip", "application/zip", data)], owner="quota-user"))
    assert exc.value.status_code == 413


# ---------------------------------------------------------------- N-09 / I-03 page template and CSP: no inline code, no unused third-party CSS
def test_n09_csp_has_no_inline_styles_or_cdn():
    from app.core.middleware import CSP

    assert "'unsafe-inline'" not in CSP and "cdnjs" not in CSP and "script-src 'self';" in CSP


def test_n09_index_html_has_no_inline_code_or_cdn_css():
    html = (BMTL_ROOT / "app" / "index.html").read_text(encoding="utf-8")
    assert "cdnjs.cloudflare.com" not in html and "font-awesome" not in html
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "inline <script> (blocked by CSP; listened to postMessage from any origin)"
    assert "<style" not in html


# ---------------------------------------------------------------- I-04 / I-05 / I-08 deployment and launcher configuration
def test_i08_launcher_hides_server_header():
    ps1 = (BMTL_ROOT / "app" / "run_scraptrust.ps1").read_text(encoding="utf-8")
    assert "--no-server-header" in ps1


def test_i05_caddy_access_log_drops_query_strings():
    caddy = (BMTL_ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    assert "format filter" in caddy and "request>uri" in caddy


def test_i04_production_env_example_is_safe():
    example = BMTL_ROOT / "deploy" / "production.env.example"
    text = example.read_text(encoding="utf-8")
    values = dict(l.split("=", 1) for l in text.splitlines() if "=" in l and not l.lstrip().startswith("#"))
    assert values["AUTH_MODE"] == "required" and values["COPILOT_PROVIDER"] == "offline" and values["COOKIE_SECURE"] == "true"
    assert values["SECRET_KEY"].startswith("<") and values["CORS_ORIGINS"] == "[]"     # placeholder, never a real secret
    compose = (BMTL_ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "production.env.example" in compose


# ---------------------------------------------------------------- L-08 production default trusts no other web origin
def test_l08_default_cors_origins_is_empty():
    from app.core.config import Settings

    assert Settings.model_fields["cors_origins"].default == "[]"


# ---------------------------------------------------------------- L-07 (re-opened): no Hugging Face network calls when downloads are off
def test_l07_hub_is_offline_before_any_model_library_loads():
    import subprocess
    import sys

    code = ("import os; os.environ.pop('HF_HUB_OFFLINE', None); os.environ.pop('TRANSFORMERS_OFFLINE', None); "
            "os.environ['ALLOW_MODEL_DOWNLOADS'] = 'false'; import app.main; "
            "import huggingface_hub.constants as c; print(os.environ.get('HF_HUB_OFFLINE'), c.HF_HUB_OFFLINE)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(BMTL_ROOT / "app" / "backend"), timeout=300)
    assert out.stdout.strip().splitlines()[-1] == "1 True", out.stdout + out.stderr[-500:]


# ---------------------------------------------------------------- sweep 2026-11-18: difference rows (negative wt%) are not readings
@pytest.mark.skipif(not MODEL.exists(), reason="BMTL models not present")
def test_negative_values_are_not_assessed_as_a_composition():
    out = BlackMassEngine().assess_readings([{"label": "Diff 90 s", "values": {"Ni": -0.28, "Co": 0.1, "Mn": 0.2}},
                                             {"label": "bag 1", "values": {"Ni": 31.8, "Co": 9.1, "Mn": 9.5}}], "sheet")
    by = {r["label"]: r for r in out["results"]}
    assert by["Diff 90 s"]["status"] == "NOT_ASSESSED" and "negative" in by["Diff 90 s"]["reason"]
    assert by["bag 1"].get("status") != "NOT_ASSESSED"


# ---------------------------------------------------------------- sweep 2026-11-18: photo answers show probabilities as percentages
def test_checker_accepts_probabilities_shown_as_percent_but_not_for_elements():
    from app.copilot.agents.checker import check

    out = {"most_likely": "Lead-acid batteries", "probability": 0.32, "top_matches": [{"material": "Zinc", "probability": 0.22}],
           "elements": {"Ni": {"inferred": {"value_pct": 0.32}}}}
    ev = [{"name": "identify_material", "output": out, "is_error": False}]
    assert check("Lead-acid batteries (32% that it is battery); Zinc 22%.", ev)["status"] == "verified"
    assert check("Nickel is 32 %.", ev)["status"] == "unverified_numbers"      # 0.32 % nickel is not 32 % nickel


def test_checker_battery_type_names_are_not_element_claims():
    from app.copilot.agents.checker import check

    out = {"top_matches": [{"material": "Lithium-ion batteries", "probability": 0.15}, {"material": "Lead-acid batteries", "probability": 0.32}],
           "elements": {"Li": {"inferred": {"value_pct": 5.2}}}}
    ev = [{"name": "identify_material", "output": out, "is_error": False}]
    assert check("Next closest: Lithium-ion batteries 15%, Lead-acid batteries 32%.", ev)["status"] == "verified"
    assert check("Lithium about 9.9 %.", ev)["status"] == "unverified_numbers"        # a real lithium claim is still checked


def test_checker_material_names_and_code_examples_are_not_claims():
    from app.copilot.agents.checker import check

    out = {"most_likely": "Aluminium", "probability": 0.4,
           "top_matches": [{"material": "Bauxite (aluminium ore)", "probability": 0.07}, {"material": "Magnetite (iron ore)", "probability": 0.15},
                           {"material": "Galena (lead ore)", "probability": 0.17}, {"material": "Aluminium", "probability": 0.1}],
           "elements": {"Fe": {"inferred": {"value_pct": 1.2}}}}
    ev = [{"name": "identify_material", "output": out, "is_error": False}]
    reply = ("Aluminium (Metal, 40% that it is metal); next: Bauxite (aluminium ore) 7%, Magnetite (iron ore) 15%, "
             "Galena (lead ore) 17%, Aluminium 10%. Or type the values, for example `Ni 31.8 Co 9.1 Mn 9.5`.")
    assert check(reply, ev)["status"] == "verified", check(reply, ev)
    assert check("Iron is 15 %.", ev)["status"] == "unverified_numbers"        # outside a material name it is still a claim
