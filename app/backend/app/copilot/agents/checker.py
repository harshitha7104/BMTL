"""
Answer-checker agent.

Every percentage / element value in a reply must be traceable to evidence: a number in this turn's
tool outputs (measured, read or model-estimated) or in the user's own message. Untraceable numbers are
reported; when Claude is configured the Copilot is asked once to repair the answer, and anything
still untraceable is flagged to the user. Deterministic: works with or without an AI key.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Set

ELEMENT_WORDS = (r"Ni|Co|Mn|Fe|Cu|Al|P|Li|Pb|Zn|nickel|cobalt|manganese|iron|copper|aluminium|aluminum|phosphorus|lithium|lead")
NUM = r"\d+(?:[.,]\d+)?"
# a number that is a composition claim: followed by %/wt%, or next to an element name/symbol
CLAIM = re.compile(rf"(?:\b(?P<ea>{ELEMENT_WORDS})\b(?!-)[^\d\n|]{{0,16}}(?P<a>{NUM})(?!\s*(?:samples?|readings?|lots?|bags?|files?|days?)\b))"
                   rf"|(?:(?P<b>{NUM})\s*(?:%|wt\s*%|percent)\s*(?:of\s+)?(?:\b(?P<eb>{ELEMENT_WORDS})\b)?)", re.I)
IGNORE = {90.0, 95.0, 85.0, 100.0, 50.0, 10.0, 5.0}   # confidence levels / generic percentages used in prose


SYMBOLS = {"ni": "Ni", "nickel": "Ni", "co": "Co", "cobalt": "Co", "mn": "Mn", "manganese": "Mn", "fe": "Fe", "iron": "Fe",
           "cu": "Cu", "copper": "Cu", "al": "Al", "aluminium": "Al", "aluminum": "Al", "p": "P", "phosphorus": "P",
           "li": "Li", "lithium": "Li", "pb": "Pb", "lead": "Pb", "zn": "Zn"}
# Security audit L-01: in tools that read the user's files these fields hold the user's own text (sample labels, file
# names, OCR numbers that were NOT used). They are never evidence, or a planted "Ni 45 %" label would "verify" a claim.
UNTRUSTED_KEYS = {"label", "source", "file", "filename", "text", "transcript", "title", "url", "sheet", "message",
                  "unlabelled_numbers_not_used", "raw_text", "ocr_text", "lines"}
USER_DATA_TOOLS = {"assess_black_mass_xrf", "analyse_lot", "write_assessment_report", "interpret_mineral_spectrum",
                   "identify_material", "analyze_waste_image", "assess_image_quality", None}


class Evidence:
    """Numbers a reply may cite. ``bound`` ties a number to the element it belongs to (a nickel claim must match a
    nickel value); ``free`` holds every trusted number (for claims that name no element)."""

    def __init__(self) -> None:
        self.bound: Set[tuple] = set()
        self.free: Set[float] = set()
        self.prose: Set[float] = set()      # numbers inside tool-written text (e.g. "molar ratio 0.62:0.20:0.19")

    def __bool__(self) -> bool:
        return bool(self.free)

    def add(self, value: float, element: str | None, prose: bool = False) -> None:
        self.free.add(value)
        if element:
            self.bound.add((element, value))
        if prose:
            self.prose.add(value)


def _symbol(word: Any) -> str | None:
    return SYMBOLS.get(str(word).strip().lower()) if isinstance(word, str) else None


def _collect(obj: Any, ev: Evidence, element: str | None, untrusted: bool) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        ev.add(float(obj), element)
        if 0 < obj <= 1:      # probabilities/shares are shown as percentages ("32% that it is a battery"): element-free only
            ev.free.add(round(float(obj) * 100, 6))
    elif isinstance(obj, str):
        for m in re.finditer(NUM, obj):
            ev.add(float(m.group(0).replace(",", ".")), element, prose=True)
    elif isinstance(obj, dict):
        local = _symbol(obj.get("element")) or element          # e.g. an outlier {"element": "Ni", "value": 33.4}
        for k, v in obj.items():
            if untrusted and str(k).lower() in UNTRUSTED_KEYS:
                continue
            _collect(v, ev, _symbol(k) or local, untrusted)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect(v, ev, element, untrusted)


def evidence_numbers(tool_records: Iterable[Dict[str, Any]], user_text: str = "") -> Evidence:
    ev = Evidence()
    for rec in tool_records:
        if not rec.get("is_error"):
            _collect(rec.get("output"), ev, None, untrusted=rec.get("name") in USER_DATA_TOOLS)
    # the user's own numbers: "Ni 31.8" binds 31.8 to nickel; every number counts for element-free claims
    for m in re.finditer(rf"\b({ELEMENT_WORDS})\b[^\d\n|]{{0,16}}({NUM})", user_text or "", re.I):
        ev.add(float(m.group(2).replace(",", ".")), _symbol(m.group(1)))
    for m in re.finditer(NUM, user_text or ""):
        ev.add(float(m.group(0).replace(",", ".")), None)
    return ev


def _close(value: float, decimals: int, e: float) -> bool:
    tol = 0.5 * 10 ** (-decimals) + 1e-9          # the reply may round: 19.107 shown as 19.1
    return abs(value - e) <= tol or bool(e) and abs(value - e) / abs(e) <= 0.005


def _grounded(value: float, decimals: int, element: str | None, ev: Evidence) -> bool:
    if element is None:
        return any(_close(value, decimals, e) for e in ev.free)
    return (any(_close(value, decimals, e) for el, e in ev.bound if el == element)
            or any(_close(value, decimals, e) for e in ev.prose))


MATERIAL_TOOLS = {"identify_material", "analyze_waste_image", "list_identifiable_materials"}
MATERIAL_KEYS = {"material", "most_likely", "name", "category", "family", "label"}


def _material_names(tool_records: Iterable[Dict[str, Any]]) -> List[str]:
    """Names the material tools themselves returned ("Bauxite (aluminium ore)", "Lithium-ion batteries")."""
    names: Set[str] = set()

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k in MATERIAL_KEYS and isinstance(v, str) and 2 < len(v) < 80:
                    names.add(v)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for rec in tool_records:
        if rec.get("name") in MATERIAL_TOOLS and not rec.get("is_error"):
            walk(rec.get("output"))
    return sorted(names, key=len, reverse=True)


def check(reply: str, tool_records: List[Dict[str, Any]], user_text: str = "") -> Dict[str, Any]:
    evidence = evidence_numbers(tool_records, user_text)
    # Not composition claims: `code` examples (e.g. how to type a reading) and material names the identification tools
    # returned, which may contain element words ("Bauxite (aluminium ore) 7%" is a 7 % match, not 7 % aluminium).
    reply = re.sub(r"`[^`\n]*`", " ", reply or "")
    for name in _material_names(tool_records):
        reply = re.sub(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", "MATERIAL", reply, flags=re.I)
    checked, ungrounded = 0, []
    for m in CLAIM.finditer(reply or ""):
        raw = m.group("a") or m.group("b")
        value = float(raw.replace(",", "."))
        if value in IGNORE and not m.group("a"):
            continue
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        checked += 1
        if not _grounded(value, decimals, _symbol(m.group("ea") or m.group("eb")), evidence):
            start = max(0, m.start() - 40)
            ungrounded.append({"value": raw, "context": reply[start:m.end() + 20].replace("\n", " ").strip()})
    # Markdown table rows that start with an element: every number in the row is a composition claim
    element_cell = re.compile(rf"^\s*\**\s*(?:{ELEMENT_WORDS})\b", re.I)
    for line in (reply or "").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else []
        row_el = element_cell.match(cells[0]) if len(cells) >= 2 else None
        if not row_el:
            continue
        row_symbol = _symbol(re.sub(r"[^A-Za-z]", "", row_el.group(0)))
        for cell in cells[1:]:
            for m in re.finditer(NUM, cell):
                raw = m.group(0)
                value = float(raw.replace(",", "."))
                decimals = len(raw.replace(",", ".").split(".")[1]) if re.search(r"[.,]", raw) else 0
                checked += 1
                if not _grounded(value, decimals, row_symbol, evidence):
                    ungrounded.append({"value": raw, "context": line.strip()[:120]})
    if not evidence and checked:
        status = "no_evidence"        # numbers in an answer that used no data tools (general knowledge)
    else:
        status = "verified" if not ungrounded else "unverified_numbers"
    return {"status": status, "numbers_checked": checked, "ungrounded": ungrounded[:10]}


REPAIR_INSTRUCTION = (
    "An automatic answer-checker compared your answer with the tool results of this turn. These numbers could not be traced "
    "to any tool result or to the user's message: {items}. Rewrite the answer so that every composition number comes from the "
    "tool results (copy them exactly or round them), or state that the value is unknown. Keep everything else the same. "
    "Return only the corrected answer."
)


def repair_prompt(result: Dict[str, Any]) -> str:
    return REPAIR_INSTRUCTION.format(items=json.dumps([u["value"] for u in result["ungrounded"]]))
