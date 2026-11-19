"""
Report-writer agent: a downloadable Word (.docx) assessment report from the conversation's readings.

All numbers come straight from the tool results (OBSERVED gun value, INFERRED ICP-equivalent with its
90 % band, INFERRED lithium, material and compound). An optional narrative summary may be written by
the Copilot (Claude); it is labelled as AI-written and placed above the tables, which remain the source.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.copilot.agents.lot import analyse
from app.copilot.agents.readings import ELEMENTS

BANNER = ("Assessment from handheld XRF using BMTL models trained on 9 ICP-referenced ACE samples. "
          "INFERRED values are model estimates with 90 % ranges; confirm by ICP-OES before any commercial use.")


def _auto_summary(readings: List[Dict[str, Any]], lot: Dict[str, Any]) -> str:
    parts = [f"{len(readings)} reading(s) assessed."]
    groups = lot.get("chemistry_groups") or {}
    if groups:
        parts.append("Chemistry: " + "; ".join(f"{g} ({len(v)})" for g, v in groups.items()) + ".")
    pe = lot.get("per_element") or {}
    if "Ni" in pe and "Co" in pe:
        parts.append(f"Average ICP-equivalent nickel {pe['Ni']['mean']} % and cobalt {pe['Co']['mean']} %"
                     + (f"; lithium {pe['Li']['mean']} % (inferred)." if "Li" in pe else "."))
    if lot.get("outliers"):
        parts.append(f"{len(lot['outliers'])} outlier value(s) flagged.")
    if lot.get("send_for_icp_first"):
        parts.append("Send first for ICP-OES: " + ", ".join(p["label"] for p in lot["send_for_icp_first"]) + ".")
    return " ".join(parts)


def build_docx(readings: List[Dict[str, Any]], *, title: str = "Black mass assessment", author: str = "",
               ai_summary: Optional[str] = None) -> bytes:
    from docx import Document
    from docx.shared import Pt

    lot = analyse(readings)
    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(10)
    doc.add_heading(title[:120], level=0)
    meta = doc.add_paragraph()
    meta.add_run(f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}").italic = True
    if author:
        meta.add_run(f" · prepared for {author}").italic = True
    doc.add_paragraph(BANNER).runs[0].bold = True

    doc.add_heading("Summary", level=1)
    if ai_summary:
        p = doc.add_paragraph(ai_summary.strip()[:3000])
        doc.add_paragraph("Summary written by the AI assistant from the tables below; the tables are the source of every number.").runs[0].italic = True
    else:
        doc.add_paragraph(_auto_summary(readings, lot))

    doc.add_heading("Readings", level=1)
    for r in readings[:50]:
        doc.add_heading(f"{r['label']}  ({r['kind']})", level=2)
        doc.add_paragraph(f"Material: {r.get('material') or 'UNKNOWN'}"
                          + (f" (confidence {r['material_confidence']})" if r.get("material_confidence") is not None else "")
                          + f" · Most likely compound: {r.get('compound') or 'UNKNOWN'} · {r.get('value_kind')}")
        rows = [e for e in ELEMENTS + ["Li"] if e in r["values"] or e in r["observed"]]
        table = doc.add_table(rows=1, cols=4)
        table.style = "Light Grid Accent 1"
        hdr = table.rows[0].cells
        for cell, text in zip(hdr, ["Element", "Read (OBSERVED, wt%)", "ICP-equivalent (INFERRED, wt%)", "90 % range"]):
            cell.text = text
        for e in rows:
            cells = table.add_row().cells
            cells[0].text = e
            cells[1].text = "not measurable by XRF" if e == "Li" else (f"{r['observed'][e]:g}" if e in r["observed"] else "–")
            v = r["values"].get(e)
            cells[2].text = "UNKNOWN" if v is None else f"{v:.3g}"
            b = r["bands"].get(e)
            cells[3].text = f"{max(0.0, v - b):.3g} – {v + b:.3g}" if v is not None and b is not None else "–"

    if lot.get("status") == "ok" and len(readings) > 1:
        doc.add_heading("Lot analysis", level=1)
        t = doc.add_table(rows=1, cols=5)
        t.style = "Light Grid Accent 1"
        for cell, text in zip(t.rows[0].cells, ["Element", "Readings", "Mean", "Min – max", "Spread"]):
            cell.text = text
        for e, s in lot["per_element"].items():
            c = t.add_row().cells
            c[0].text, c[1].text, c[2].text = e, str(s["n"]), f"{s['mean']:g}"
            c[3].text, c[4].text = f"{s['min']:g} – {s['max']:g}", (f"{s['spread_pct']} %" if s["spread_pct"] is not None else "–")
        if lot["outliers"]:
            doc.add_paragraph("Outliers: " + "; ".join(f"{o['label']} {o['element']} {o['value']} % (lot median {o['lot_median']} %)" for o in lot["outliers"]))
        if lot["send_for_icp_first"]:
            doc.add_heading("Recommended ICP-OES confirmation", level=2)
            for p in lot["send_for_icp_first"]:
                doc.add_paragraph(f"{p['label']}: {p['why']}", style="List Bullet")

    doc.add_heading("Method and limits", level=1)
    for line in (
        "XRF gun values are corrected per element to ICP-equivalent wt% (linear or proportional correction, or the gun value where no "
        "correction beats it), tested leave-one-sample-out on ACE's ICP-referenced samples.",
        "Lithium cannot be measured by XRF; it is inferred from the corrected Ni, Co, Mn and Fe-with-P content (Li per metal atom).",
        "The material and cathode compound are inferred from element ratios; they are not phase measurements.",
        "Ranges are 90 % prediction ranges; with few reference samples they can be too narrow for some elements.",
    ):
        doc.add_paragraph(line, style="List Bullet")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
