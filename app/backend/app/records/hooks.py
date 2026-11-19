"""
Turn chat activity into records: the admin activity log, the user's library and structured observations.

Called once per answered message by CopilotService. Everything here is best-effort: the store's methods
never raise, and this module catches its own errors, so recording can never break a user's answer.
"""
from __future__ import annotations

import io
import json
import logging
from typing import Any, Dict, List, Optional

from app.copilot.agents.readings import ELEMENTS, readings_from_output
from app.records.store import RecordsStore

log = logging.getLogger(__name__)

TOOL_TITLES = {
    "assess_black_mass_xrf": "Black-mass assessment",
    "identify_material": "Material identification",
    "analyze_waste_image": "Dataset similarity",
    "assess_image_quality": "Photo quality",
    "interpret_mineral_spectrum": "Mineral spectrum",
    "analyse_lot": "Lot analysis",
    "write_assessment_report": "Report",
}


def reading_text(r: Dict[str, Any]) -> str:
    lines = [f"Reading: {r.get('label')}  ({r.get('kind')})",
             f"Material: {r.get('material') or 'UNKNOWN'}"
             + (f" (confidence {r['material_confidence']})" if r.get("material_confidence") is not None else ""),
             f"Most likely compound: {r.get('compound') or 'UNKNOWN'}",
             f"Values: {r.get('value_kind')}", "",
             f"{'Element':<9}{'Read (OBSERVED)':>18}{'ICP-equivalent (INFERRED)':>28}{'90 % range':>20}"]
    for e in ELEMENTS + ["Li"]:
        if e not in r.get("values", {}) and e not in r.get("observed", {}):
            continue
        obs = "not measurable" if e == "Li" else (f"{r['observed'][e]:g}" if e in r.get("observed", {}) else "-")
        v = r["values"].get(e)
        b = r["bands"].get(e)
        rng = f"{max(0.0, v - b):.3g} - {v + b:.3g}" if v is not None and b is not None else "-"
        lines.append(f"{e:<9}{obs:>18}{('UNKNOWN' if v is None else f'{v:.3g}'):>28}{rng:>20}")
    lines += ["", "INFERRED values are model estimates; confirm by ICP-OES before commercial use. Lithium is inferred, never measured by XRF."]
    return "\n".join(lines)


def reading_title(r: Dict[str, Any]) -> str:
    """A name that says what was found: 'NMC622 · Ni 30.2 % · Co 9.1 %' (prefixed with the bag/file label when meaningful)."""
    what = (r.get("compound") or "").split(" (")[0] or r.get("material") or "Black mass"
    vals = " · ".join(f"{e} {r['values'][e]:.1f} %" for e in ("Ni", "Co") if e in r.get("values", {}))
    label = str(r.get("label") or "")
    generic = label.startswith(("message text reading", "typed values", "message")) or not label
    return (f"{what}" if generic else f"{label}: {what}") + (f" · {vals}" if vals else "")


def _compact(output: Any, limit: int = 4000) -> str:
    text = json.dumps(output, default=str, ensure_ascii=False, indent=1)
    return text if len(text) <= limit else text[:limit] + "\n... (truncated)"


def _docx_text(path: str) -> str:
    try:
        from docx import Document

        doc = Document(path)
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for t in doc.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(parts)
    except Exception:   # noqa: BLE001
        return ""


def _attachment_text(att: Any, calls: List[Dict[str, Any]]) -> str:
    parts = []
    if getattr(att, "text", None):
        parts += ["Text / transcript:", att.text.strip(), ""]
    if getattr(att, "note", None):
        parts += [f"Note: {att.note}", ""]
    for c in calls:
        if (c.get("input") or {}).get("attachment_id") != att.attachment_id or c.get("is_error"):
            continue
        if c["name"] == "assess_black_mass_xrf":
            for r in readings_from_output(c.get("output"), att.attachment_id):
                parts += [reading_text(r), ""]
        else:
            parts += [f"{TOOL_TITLES.get(c['name'], c['name'])}:", _compact(c.get("output")), ""]
    return "\n".join(parts).strip()


def record_chat_turn(store: RecordsStore, *, owner: Optional[str], session_id: str, message: str, new_attachments: List[Any],
                     tool_calls: List[Dict[str, Any]], reply: str, provider: str, model: str, verification: Dict[str, Any],
                     generated: List[Dict[str, Any]], all_attachments: Dict[str, Dict[str, Any]]) -> None:
    try:
        user = owner or "anonymous"
        atts = [{"attachment_id": a.attachment_id, "kind": a.kind, "filename": a.filename, "size_bytes": a.size_bytes,
                 "content_type": a.content_type, "source": a.source, "text": (a.text or "")[:20000], "note": a.note} for a in new_attachments]
        store.log(user, "chat_message", session_id=session_id, summary=(message or "(attachments only)")[:300],
                  detail={"message": message, "attachments": atts})
        for a in atts:
            if not a["source"]:
                store.log(user, f"upload:{a['kind']}", session_id=session_id, object_id=a["attachment_id"],
                          summary=f"{a['filename']} ({a['size_bytes']} bytes)", detail=a)
        for c in tool_calls:
            store.log(user, f"tool:{c['name']}", session_id=session_id, object_id=(c.get("input") or {}).get("attachment_id"),
                      summary=f"{TOOL_TITLES.get(c['name'], c['name'])}{' (error)' if c.get('is_error') else ''}",
                      detail={"input": c.get("input"), "output": c.get("output"), "is_error": c.get("is_error"), "duration_ms": c.get("duration_ms")})
        store.log(user, "assistant_reply", session_id=session_id, summary=reply[:300],
                  detail={"reply": reply, "provider": provider, "model": model, "verification": verification})

        if owner is None:
            return
        # ---- library: the user's own uploads, generated reports and assessments
        for a in new_attachments:
            if a.source:   # frames taken from a video are part of the video's item
                continue
            store.add_library_item(owner, kind=a.kind, title=a.filename, filename=a.filename, session_id=session_id,
                                   attachment_id=a.attachment_id, size_bytes=a.size_bytes, text=_attachment_text(a, tool_calls))
        for g in generated:
            att = all_attachments.get(g["attachment_id"]) or {}
            store.add_library_item(owner, kind="report", title=g["filename"], filename=g["filename"], session_id=session_id,
                                   attachment_id=g["attachment_id"], size_bytes=g.get("size_bytes", 0), text=_docx_text(att.get("path", "")))
            store.log(owner, "report_generated", session_id=session_id, object_id=g["attachment_id"], summary=g["filename"], detail=g)
        # ---- structured readings: library "assessment" items + observations (training candidates, UNLABELLED)
        for c in tool_calls:
            if c["name"] != "assess_black_mass_xrf" or c.get("is_error"):
                continue
            args = c.get("input") or {}
            output = c.get("output") or {}
            pdz = isinstance(output, dict) and "factory_calibration" in output
            for r in readings_from_output(output, args.get("attachment_id") or "message"):
                store.add_library_item(owner, kind="assessment", title=reading_title(r)[:200], session_id=session_id,
                                       attachment_id=args.get("attachment_id"), text=reading_text(r))
                # a gun reading the models corrected (has bands); lab values typed in as input are not XRF observations
                if r.get("observed") and r.get("bands"):
                    store.add_observation(owner, session_id, r, instrument=str(args.get("instrument") or output.get("instrument") or ""),
                                          basis="factory" if pdz else str(args.get("basis") or "type_standardised"))
    except Exception:   # noqa: BLE001
        log.exception("records: could not record chat turn")
