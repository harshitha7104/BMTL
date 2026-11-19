"""Black-mass XRF tool: Copilot bridge to BMTL's real-data models (models/real/)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.copilot.engines.black_mass import BMTL_ROOT, BlackMassEngine
from app.copilot.tools import ToolContext, build_default_tools
from app.copilot.types import Attachment

PDZ = BMTL_ROOT / "data" / "raw" / "ace_company" / "bruker_s1titan" / "pdz_90s" / "01293-GeoMining.pdz"
MODEL = BMTL_ROOT / "models" / "real" / "bmtl_real_models.joblib"
pytestmark = pytest.mark.skipif(not (PDZ.exists() and MODEL.exists()), reason="BMTL real data / models not present")


def _run(coro):
    """Private event loop: asyncio.run() would clear the global loop other tests rely on."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Stub:  # engines the black-mass tools never touch
    pass


def _registry():
    return build_default_tools(_Stub(), _Stub(), knowledge_base=_Stub(), black_mass_engine=BlackMassEngine())


def test_engine_assesses_pdz_with_evidence_labels():
    r = BlackMassEngine().assess_pdz(str(PDZ))
    assert r["reading_id"] == "845"
    for view in ("factory_calibration", "type_standardised"):
        ni = r[view]["elements"]["Ni"]
        assert ni["observed"]["state"] == "OBSERVED"
        assert ni["inferred"]["state"] == "INFERRED" and ni["inferred"]["low"] <= ni["inferred"]["value_pct"] <= ni["inferred"]["high"]
        assert r[view]["lithium"]["state"] == "INFERRED"
        assert r[view]["material"]["label"] == "NMC"
    # factory Ni reads ~31.8 % on this sample; the correction must pull it toward ICP (18.65 %)
    assert abs(r["factory_calibration"]["elements"]["Ni"]["inferred"]["value_pct"] - 18.65) < 3


def test_tool_with_pdz_attachment_and_with_values():
    reg = _registry()
    att = Attachment("xrf_1", "xrf", PDZ.name, "application/octet-stream", str(PDZ), PDZ.stat().st_size)
    ctx = ToolContext({"xrf_1": att})
    rec = _run(reg.execute("assess_black_mass_xrf", {"attachment_id": "xrf_1"}, ctx))
    assert not rec.is_error and rec.output["file"] == PDZ.name
    rec = _run(reg.execute("assess_black_mass_xrf", {"values": {"Pb": 99.1, "Fe": 0.6, "Ni": 0.18, "Co": 0.14}, "instrument": "xSORT"}, ctx))
    assert rec.output["material"]["label"] == "NOT_BLACK_MASS_LEAD"
    rec = _run(reg.execute("assess_black_mass_xrf", {}, ctx))
    assert rec.is_error


def test_pdz_upload_is_classified_as_xrf(tmp_path):
    from app.copilot.service import CopilotService

    service = object.__new__(CopilotService)
    service.max_upload_bytes = service.max_media_bytes = 10 * 1024 * 1024
    kind = CopilotService._classify(service, PDZ.name, "application/octet-stream", PDZ.read_bytes())
    assert kind == "xrf"
