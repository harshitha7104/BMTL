"""Normalise black-mass tool outputs (pdz / table / text / photo / typed values) into one reading shape."""
from __future__ import annotations

from typing import Any, Dict, List

ELEMENTS = ["Ni", "Co", "Mn", "Fe", "Cu", "Al", "P"]


def _reading(label: str, source: str, view: Dict[str, Any], kind: str) -> Dict[str, Any]:
    els = view.get("elements") or {}
    values, bands, observed = {}, {}, {}
    for e in ELEMENTS:
        entry = els.get(e) or {}
        inf = entry.get("inferred") or {}
        obs = (entry.get("observed") or {}).get("value_pct")
        if obs is not None:
            observed[e] = obs
        v = inf.get("value_pct")
        if v is None and inf.get("state") == "NOT_APPLICABLE":
            v = obs                      # lab (ICP) value given as input: it is the reference itself
        if v is not None:
            values[e] = float(v)
            if inf.get("band_90") is not None:
                bands[e] = float(inf["band_90"])
    li = view.get("lithium") or {}
    if li.get("value_pct") is not None:
        values["Li"] = float(li["value_pct"])
        if li.get("band_90") is not None:
            bands["Li"] = float(li["band_90"])
    return {
        "label": str(label), "source": source, "kind": kind,
        "values": values, "bands": bands, "observed": observed,
        "material": (view.get("material") or {}).get("label"),
        "material_confidence": (view.get("material") or {}).get("confidence"),
        "compound": (view.get("compound") or {}).get("name"),
        "value_kind": view.get("value_kind", "XRF gun values, corrected to ICP-equivalent"),
    }


def readings_from_output(output: Any, source: str) -> List[Dict[str, Any]]:
    if not isinstance(output, dict):
        return []
    if "factory_calibration" in output:          # .pdz: factory calibration is the un-fitted, clean view
        return [_reading(output.get("file") or source, source, output["factory_calibration"], "pdz (factory calibration)")]
    if "results" in output:
        return [_reading(r.get("label", source), source, r, "table/text/photo") for r in output["results"] if r.get("status") != "NOT_ASSESSED"]
    if "elements" in output:
        return [_reading("typed values", source, output, "typed values")]
    return []


def collect(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """All readings from a list of tool-call records ({name, input, output, is_error})."""
    out: List[Dict[str, Any]] = []
    for rec in records:
        if rec.get("name") != "assess_black_mass_xrf" or rec.get("is_error"):
            continue
        src = (rec.get("input") or {}).get("attachment_id") or "message"
        out += readings_from_output(rec.get("output"), src)
    # the same label can come from different messages/files ("message text reading 1" twice): make each unique
    seen: Dict[str, int] = {}
    for r in out:
        n = seen[r["label"]] = seen.get(r["label"], 0) + 1
        if n > 1:
            r["label"] = f"{r['label']} (#{n})"
    return out
