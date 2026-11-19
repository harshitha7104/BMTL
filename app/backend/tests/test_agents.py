"""AI agent team: answer-checker, lot-analyst, report-writer, voice summary, and their wiring into the chat service."""
from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pytest

from app.copilot.agents.checker import check, repair_prompt
from app.copilot.agents.lot import analyse
from app.copilot.agents.report import build_docx
from app.copilot.agents.speech import speech_for
from app.copilot.engines.black_mass import BMTL_ROOT, BlackMassEngine
from app.copilot.providers.registry import CopilotProviderRegistry
from app.copilot.tools import ToolContext, build_default_tools

MODEL = BMTL_ROOT / "models" / "real" / "bmtl_real_models.joblib"
needs_model = pytest.mark.skipif(not MODEL.exists(), reason="BMTL real models not present")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Stub:
    pass


def _registry():
    return build_default_tools(_Stub(), _Stub(), knowledge_base=_Stub(), black_mass_engine=BlackMassEngine())


def _reading(label, ni, co, mn, li=None, material="NMC", compound="NMC622 (LiNi0.6Mn0.2Co0.2O2)"):
    values = {"Ni": ni, "Co": co, "Mn": mn}
    if li is not None:
        values["Li"] = li
    return {"label": label, "source": "test", "kind": "typed", "values": values, "bands": {k: 1.0 for k in values},
            "observed": {"Ni": ni, "Co": co, "Mn": mn}, "material": material, "material_confidence": 0.9,
            "compound": compound, "value_kind": "ICP-equivalent (INFERRED)"}


# ---------------------------------------------------------------- answer-checker
def test_checker_verifies_traceable_numbers_and_flags_invented_ones():
    evidence = [{"name": "assess_black_mass_xrf", "output": {"Ni": {"value_pct": 19.107}, "Co": 6.42}, "is_error": False}]
    ok = check("Nickel is about 19.1 % and Co 6.42 %. Confidence 90 %.", evidence)
    assert ok["status"] == "verified" and ok["numbers_checked"] == 2
    bad = check("Nickel is 19.1 % and lithium 7.9 %.", evidence)
    assert bad["status"] == "unverified_numbers" and [u["value"] for u in bad["ungrounded"]] == ["7.9"]
    assert "7.9" in repair_prompt(bad)
    # numbers the user typed count as evidence
    assert check("You gave Mn 12.5 %.", evidence, "my Mn is 12.5")["status"] == "verified"
    # general-knowledge answer with no tools
    assert check("NMC811 has about 48 % Ni.", [])["status"] == "no_evidence"
    # counts of readings are not composition claims
    assert check("I compared Ni across 3 readings.", evidence)["numbers_checked"] == 0


# ---------------------------------------------------------------- lot-analyst
def test_lot_finds_outlier_and_recommends_icp():
    readings = [_reading(f"bag {i}", 19.0 + 0.1 * i, 6.5, 6.0) for i in range(5)] + [_reading("bag X", 31.0, 6.5, 6.0)]
    out = analyse(readings)
    assert out["status"] == "ok" and out["readings"] == 6
    assert any(o["label"] == "bag X" and o["element"] == "Ni" for o in out["outliers"])
    assert out["send_for_icp_first"][0]["label"] == "bag X"
    assert len(out["send_for_icp_first"]) <= 3
    assert analyse([])["status"] == "no_readings"


def test_lot_flags_mixed_chemistry():
    out = analyse([_reading("a", 19, 6.5, 6), _reading("b", 0.2, 0.1, 0.1, material="LFP", compound="LFP (LiFePO4)")])
    assert out["chemistry_consistent"] is False


# ---------------------------------------------------------------- report-writer
def test_report_docx_contains_tables_banner_and_lithium_caveat():
    from docx import Document

    data = build_docx([_reading("bag 1", 19.1, 6.4, 6.0, li=5.2), _reading("bag 2", 19.4, 6.5, 6.1, li=5.3)], title="Lot T", author="tester")
    doc = Document(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs)
    cells = "\n".join(c.text for t in doc.tables for row in t.rows for c in row.cells)
    assert "Lot T" in text and "confirm by ICP-OES" in text
    assert "not measurable by XRF" in cells and "19.1" in cells
    assert "Lot analysis" in text


# ---------------------------------------------------------------- voice
def test_speech_is_short_plain_text():
    reply = "## Result\n| a | b |\n|---|---|\n| 1 | 2 |\n**It is NMC.** Nickel is high. " + "More detail. " * 80
    s = speech_for(reply, [])
    assert len(s) <= 420 and "|" not in s and "#" not in s and s.startswith("Result It is NMC.")


# ---------------------------------------------------------------- tools
@needs_model
def test_lot_and_report_tools_use_conversation_results():
    reg = _registry()
    saved = {}

    def save(name, ctype, data):
        saved.update(name=name, ctype=ctype, size=len(data))
        return {"attachment_id": "report_1", "filename": name, "size_bytes": len(data), "kind": "report"}

    ctx = ToolContext({}, save_file=save, user="tester")
    assert _run(reg.execute("write_assessment_report", {}, ctx)).is_error      # nothing assessed yet
    for vals in ({"Ni": 31.8, "Co": 9.1, "Mn": 9.5, "Fe": 0.4, "Cu": 1.2, "Al": 1.5},
                 {"Ni": 32.4, "Co": 9.3, "Mn": 9.7, "Fe": 0.5, "Cu": 1.1, "Al": 1.4}):
        assert not _run(reg.execute("assess_black_mass_xrf", {"values": vals, "instrument": "S1 TITAN"}, ctx)).is_error
    assert len(ctx.results) == 2
    lot = _run(reg.execute("analyse_lot", {}, ctx))
    assert not lot.is_error and lot.output["readings"] == 2
    rep = _run(reg.execute("write_assessment_report", {"title": "Lot <B>/../x"}, ctx))
    assert not rep.is_error and rep.output["readings_in_report"] == 2
    assert saved["name"].endswith(".docx") and "/" not in saved["name"] and "<" not in saved["name"] and saved["size"] > 5000


# ---------------------------------------------------------------- service wiring (offline provider, no AI key)
@needs_model
def test_service_returns_speech_verification_and_downloadable_report(tmp_path):
    from app.copilot.service import CopilotService

    service = CopilotService(storage_dir=tmp_path / "copilot", providers=CopilotProviderRegistry([], default="offline"),
                             tools=_registry(), max_upload_bytes=5 * 1024 * 1024, max_images_per_turn=3,
                             allowed_image_types=["image/jpeg"])
    first = _run(service.chat("Ni 31.8 Co 9.1 Mn 9.5 Fe 0.4 Cu 1.2 Al 1.5", owner="tester"))
    assert first["speech"] and len(first["speech"]) <= 420
    assert first["verification"]["status"] in ("verified", "unverified_numbers")
    sid = first["session_id"]
    _run(service.chat("Ni 32.6 Co 9.4 Mn 9.8 Fe 0.5 Cu 1.1 Al 1.4", session_id=sid, owner="tester"))
    third = _run(service.chat("compare the lot and write a Word report", session_id=sid, owner="tester"))
    names = {c["name"] for c in third["tool_calls"]}
    assert {"analyse_lot", "write_assessment_report"} <= names, names
    assert third["generated_files"] and third["generated_files"][0]["filename"].endswith(".docx")
    att_id = third["generated_files"][0]["attachment_id"]
    path, ctype, filename = service.attachment_file(sid, att_id, owner="tester")
    assert Path(path).read_bytes()[:2] == b"PK" and filename.endswith(".docx")
    # another user cannot fetch it
    with pytest.raises(Exception):
        service.attachment_file(sid, att_id, owner="someone-else")


@needs_model
def test_checker_asks_the_ai_to_repair_invented_numbers(tmp_path):
    """A provider that invents a lithium value is asked once to fix it; the repaired answer is kept."""
    from app.copilot.providers.base import ChatProvider, run_tool_calls
    from app.copilot.service import CopilotService
    from app.copilot.types import ProviderResult

    class Fibber(ChatProvider):
        name = display_name = "fibber"
        revised_with = None

        @property
        def model(self):
            return "fake"

        def is_configured(self):
            return True

        async def respond(self, *, system, history, user_turn, images, tools, ctx, max_rounds):
            recs = await run_tool_calls(tools, [("assess_black_mass_xrf", {"text": user_turn.text})], ctx)
            return ProviderResult("It is NMC. Lithium is 9.87 %.", self.name, self.model, recs)

        async def revise(self, *, system, draft, evidence, instruction):
            Fibber.revised_with = instruction
            return "It is NMC. Lithium is unknown here."

    service = CopilotService(storage_dir=tmp_path / "c", providers=CopilotProviderRegistry([Fibber()], default="fibber"),
                             tools=_registry(), max_upload_bytes=1 << 20, max_images_per_turn=1, allowed_image_types=["image/jpeg"])
    out = _run(service.chat("Ni 31.8 Co 9.1 Mn 9.5 Fe 0.4 Cu 1.2 Al 1.5", owner="t"))
    assert "9.87" in Fibber.revised_with
    assert "9.87" not in out["reply"] and out["verification"].get("repaired") is True


def test_checker_reads_markdown_tables():
    # band limits belong to their element (audit L-01: a nickel row may only cite nickel values)
    evidence = [{"name": "assess_black_mass_xrf", "output": {"Ni": {"value_pct": 19.107, "low": 17.2, "high": 21.0}}, "is_error": False}]
    ok = check("| Element | ICP-eq | range |\n|---|---|---|\n| **Ni** | 19.1 | 17.2 – 21.0 |", evidence)
    assert ok["status"] == "verified" and ok["numbers_checked"] == 3
    bad = check("| Element | value |\n|---|---|\n| Co | 8.8 |", evidence)
    assert bad["status"] == "unverified_numbers"


@needs_model
def test_failing_ai_service_falls_back_to_offline(tmp_path):
    from app.copilot.providers.base import ChatProvider, CopilotProviderError
    from app.copilot.service import CopilotService

    class Down(ChatProvider):
        name = display_name = "down"

        @property
        def model(self):
            return "x"

        def is_configured(self):
            return True

        async def respond(self, **kw):
            raise CopilotProviderError("down", "rate limited")

    service = CopilotService(storage_dir=tmp_path / "c", providers=CopilotProviderRegistry([Down()], default="down"),
                             tools=_registry(), max_upload_bytes=1 << 20, max_images_per_turn=1, allowed_image_types=["image/jpeg"])
    out = _run(service.chat("Ni 31.8 Co 9.1 Mn 9.5 Fe 0.4 Cu 1.2 Al 1.5", owner="t"))
    assert out["provider"] == "offline" and "built-in offline engine" in out["reply"]
    assert out["verification"]["status"] == "verified"


@needs_model
def test_black_mass_answer_starts_in_plain_language(tmp_path):
    from app.copilot.service import CopilotService

    service = CopilotService(storage_dir=tmp_path / "c", providers=CopilotProviderRegistry([], default="offline"), tools=_registry(),
                             max_upload_bytes=1 << 20, max_images_per_turn=1, allowed_image_types=["image/jpeg"])
    reply = _run(service.chat("is my black mass good? Ni 31.8 Co 9.1 Mn 9.5 Fe 0.4 Cu 1.2 Al 1.5", owner="t"))
    text = reply["reply"]
    assert text.index("In short") < text.index("| Element")                 # verdict before the table
    assert "lab (ICP-OES) before you buy, sell or price" in text
    assert "kNN" not in text.split("<details>")[0]                          # jargon only inside the fold-out
    assert reply["verification"]["status"] == "verified"
