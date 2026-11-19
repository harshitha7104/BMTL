"""
Voice agent support: a short, natural spoken summary of an answer for hands-free mode.

Spoken from the measured/model results when there are any ("Material NMC, most likely NMC622.
Nickel about 19 percent ..."), otherwise from the first sentences of the answer with Markdown,
tables and links stripped. The browser speaks it with the device's own voices (no audio leaves the PC).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from app.copilot.agents.readings import collect

NAMES = {"Ni": "nickel", "Co": "cobalt", "Mn": "manganese", "Fe": "iron", "Cu": "copper", "Al": "aluminium", "P": "phosphorus", "Li": "lithium"}
MAX_CHARS = 420


def _plain(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = "\n".join(l for l in text.splitlines() if not l.strip().startswith("|"))   # drop tables
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[#*_`>]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _num(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def speech_for(reply: str, tool_records: List[Dict[str, Any]]) -> str:
    readings = collect(tool_records)
    if readings:
        r = readings[0]
        bits = []
        if len(readings) > 1:
            bits.append(f"I assessed {len(readings)} readings. The first one:")
        if r.get("material"):
            bits.append(f"material {r['material']}" + (f", most likely {r['compound'].split(' (')[0]}" if r.get("compound") else "") + ".")
        vals = [f"{NAMES[e]} about {_num(r['values'][e])} percent" for e in ("Ni", "Co", "Mn") if e in r["values"]]
        if vals:
            v = ", ".join(vals)
            bits.append(v[:1].upper() + v[1:] + ".")
        if "Li" in r["values"]:
            bits.append(f"Lithium is estimated at about {_num(r['values']['Li'])} percent; please confirm it by lab test.")
        text = " ".join(bits)
        text = text[:1].upper() + text[1:]
        if text:
            return text[:MAX_CHARS]
    plain = _plain(reply)
    sentences = re.split(r"(?<=[.!?])\s+", plain)
    out = ""
    for s in sentences:
        if len(out) + len(s) > MAX_CHARS:
            break
        out += s + " "
    return (out or plain[:MAX_CHARS]).strip()
