"""Pull element readings out of unstructured input: tables, JSON, free text, PDF text, XRF screen photos.

PROVENANCE: works on whatever a user sends; nothing here invents a number. A value is returned only
when an element symbol (or name/oxide) and a number are both read from the input; a number whose
element cannot be read is reported as an unlabelled value, never assigned. "< LOD" / "ND" / "<0.1"
become censored (value None, below_lod True).

Outputs are lists of readings: {"label", "values": {El: wt%}, "below_lod": [El], "source", "basis_hint", "notes"}
where basis_hint is "icp" when the input says the numbers are ICP/lab results, else "xrf".
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any, Iterable

ELEMENTS = ["Li", "Ni", "Co", "Mn", "Fe", "Cu", "Al", "P", "Zn", "Cr", "Ti", "Zr", "Pb", "Mg", "Si", "S", "Ca", "Cd", "Mo", "W", "Ta",
            "Nb", "Sn", "V", "K", "Cl", "Ba", "La", "Ce", "Ag", "Au", "Pt", "Pd"]
NAMES = {"lithium": "Li", "nickel": "Ni", "cobalt": "Co", "manganese": "Mn", "iron": "Fe", "copper": "Cu", "aluminium": "Al",
         "aluminum": "Al", "phosphorus": "P", "zinc": "Zn", "chromium": "Cr", "titanium": "Ti", "zirconium": "Zr", "lead": "Pb",
         "magnesium": "Mg", "silicon": "Si", "sulphur": "S", "sulfur": "S", "calcium": "Ca", "cadmium": "Cd", "molybdenum": "Mo"}
OXIDES = {"Al2O3": ("Al", 2 * 26.9815 / 101.9613), "SiO2": ("Si", 28.0855 / 60.0843), "MgO": ("Mg", 24.305 / 40.3044),
          "K2O": ("K", 2 * 39.0983 / 94.196), "CaO": ("Ca", 40.078 / 56.077), "Fe2O3": ("Fe", 2 * 55.845 / 159.687),
          "MnO": ("Mn", 54.938 / 70.937), "NiO": ("Ni", 58.693 / 74.692), "CoO": ("Co", 58.933 / 74.932), "CuO": ("Cu", 63.546 / 79.545),
          "P2O5": ("P", 2 * 30.974 / 141.943), "Li2O": ("Li", 2 * 6.941 / 29.881)}
CORE = {"Ni", "Co", "Mn", "Fe", "Cu", "Al", "P", "Pb", "Zn", "Li"}
MAX_ROWS = 500
OFFICE_MEMBER_MAX = 20 * 1024 * 1024     # largest uncompressed part of an .xlsx / .docx we will parse
OFFICE_TOTAL_MAX = 60 * 1024 * 1024
OFFICE_RATIO_MAX = 100


class UnsafeOfficeFile(ValueError):
    """An Office (ZIP-based) file that would expand to an unsafe size if parsed (decompression bomb)."""


def check_office_zip(data: bytes, filename: str = "file") -> None:
    """Security audit H-03: a 0.5 MB .xlsx expanded to 500 MB and cost the server 3 GB of memory.
    Check every ZIP member's declared size and compression ratio BEFORE openpyxl / pandas touch the file."""
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
    except zipfile.BadZipFile:
        return                                   # not a ZIP: the parser will reject it on its own
    if len(infos) > 2000:
        raise UnsafeOfficeFile(f"'{filename}' has too many internal parts")
    total = 0
    for i in infos:
        total += i.file_size
        if i.file_size > OFFICE_MEMBER_MAX or total > OFFICE_TOTAL_MAX or i.file_size > OFFICE_RATIO_MAX * max(i.compress_size, 1) + 65536:
            raise UnsafeOfficeFile(f"'{filename}' is too large or unusually compressed to open safely")
_NUM = r"[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?"
CENSORED = re.compile(r"^\s*(<\s*lod|nd|n\.d\.?|bdl|not detected|<\s*" + _NUM + r")\s*%?\s*$", re.I)


# --------------------------------------------------------------------------- headers / values
def parse_header(header: str) -> tuple[str | None, float]:
    """Column header -> (element, multiplier to wt%). None if it is not an element concentration column."""
    h = str(header or "").strip()
    if not h or re.search(r"(err|sd|sigma|std|uncert|±|\+/-|lod\b|_lod|below|limit|conf)", h, re.I):
        return None, 1.0
    unit = 1.0
    if re.search(r"(mg/?kg|ppm|_mgkg)", h, re.I):
        unit = 1e-4
    core = re.sub(r"\(.*?\)|\[.*?\]", "", h)
    core = re.sub(r"(_?wt_?pct|_?pct|wt\s*%|%|_mgkg|mg/?kg|ppm|\bicp\b|\bxrf\b|\bconc\w*|_value)", "", core, flags=re.I).strip(" _-:")
    if core in OXIDES:
        el, f = OXIDES[core]
        return el, f * unit
    if core in ELEMENTS:
        return core, unit
    m = re.fullmatch(r"([A-Za-z]+)\s*\(?([A-Z][a-z]?)?\)?", core)
    word = core.lower().split()[0] if core else ""
    if word in NAMES:
        return NAMES[word], unit
    if m and m.group(2) in ELEMENTS:
        return m.group(2), unit
    return None, 1.0


def parse_value(raw: Any) -> tuple[float | None, bool]:
    """(value, censored). Unparseable -> (None, False)."""
    if raw is None:
        return None, False
    if isinstance(raw, (int, float)):
        return float(raw), False
    text = str(raw).strip()
    if not text:
        return None, False
    if CENSORED.match(text):
        return None, True
    m = re.match(r"^\s*[+~]?\s*(" + _NUM + r")\s*%?", text)
    if not m:
        return None, False
    try:
        return float(m.group(1).replace(",", ".")), False
    except ValueError:
        return None, False


def _reading(label: str, row: dict[str, Any], columns: dict[str, tuple[str, float]], source: str, hint: str) -> dict | None:
    values, lod = {}, []
    for col, (el, mult) in columns.items():
        v, cens = parse_value(row.get(col))
        if cens:
            lod.append(el)
        elif v is not None and el not in values:
            values[el] = round(v * mult, 6)
    if len(set(values) | set(lod)) < 2:
        return None
    return {"label": label, "values": values, "below_lod": sorted(set(lod) - set(values)), "source": source, "basis_hint": hint, "notes": []}


def _hint(text: str) -> str:
    return "icp" if re.search(r"\bicp\b|icp-?oes|icp-?ms|assay|laborator", text, re.I) else "xrf"


# --------------------------------------------------------------------------- tables
def readings_from_rows(rows: list[list[Any]], source: str, context: str = "") -> list[dict]:
    """Rows of cells, either orientation. Handles repeated header rows (Bruker Results.csv)."""
    rows = [r for r in rows if any(str(c).strip() for c in r if c is not None)][: MAX_ROWS * 2]
    out: list[dict] = []
    hint = _hint(context + " " + " ".join(str(c) for r in rows[:5] for c in r if c))
    # orientation 1: header row with element columns (may repeat)
    header, columns = None, {}
    for r in rows:
        cand = {str(c): parse_header(str(c)) for c in r if c is not None}
        cand = {k: v for k, v in cand.items() if v[0]}
        if len(cand) >= 3 and len({v[0] for v in cand.values()} & CORE) >= 2:
            header, columns = [str(c) if c is not None else "" for c in r], cand
            continue
        if header is None:
            continue
        rec = dict(zip(header, r))
        label = next((str(rec[k]) for k in header if k and re.search(r"sample|^id$|reading|file ?#|name|lot", k, re.I) and rec.get(k)), f"row {len(out) + 1}")
        reading = _reading(label, rec, columns, source, hint)
        if reading:
            out.append(reading)
        if len(out) >= MAX_ROWS:
            break
    if out:
        return out
    # orientation 2: element names down the first column, samples across
    first = [(i, parse_header(str(r[0]))) for i, r in enumerate(rows) if r and r[0] is not None]
    el_rows = [(i, v) for i, v in first if v[0]]
    if len({v[0] for _, v in el_rows} & CORE) >= 3:
        head_idx = max(0, el_rows[0][0] - 1)
        head = rows[head_idx]
        width = max(len(r) for r in rows)
        for j in range(1, width):
            label = str(head[j]) if j < len(head) and head[j] not in (None, "") else f"column {j + 1}"
            col_hint = _hint(label) if _hint(label) == "icp" else hint
            rec = {str(i): (rows[i][j] if j < len(rows[i]) else None) for i, _ in el_rows}
            reading = _reading(label, rec, {str(i): v for i, v in el_rows}, source, col_hint)
            if reading:
                out.append(reading)
    return out[:MAX_ROWS]


def readings_from_csv(data: bytes, filename: str) -> list[dict]:
    text = data.decode("utf-8-sig", errors="replace")
    sample = text[:5000]
    delim = "\t" if sample.count("\t") > sample.count(",") else ";" if sample.count(";") > sample.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    return readings_from_rows(rows, filename, filename)


def readings_from_xlsx(data: bytes, filename: str) -> list[dict]:
    import openpyxl   # uses defusedxml when installed (XML bomb protection)

    check_office_zip(data, filename)
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets[:10]:
        rows = [list(r) for _, r in zip(range(MAX_ROWS * 2), ws.iter_rows(values_only=True))]
        out += readings_from_rows(rows, f"{filename}:{ws.title}", f"{filename} {ws.title}")
    return out[:MAX_ROWS]


def readings_from_json(data: bytes, filename: str) -> list[dict]:
    obj = json.loads(data.decode("utf-8-sig", errors="replace"))
    records: list[tuple[str, dict]] = []

    def walk(o: Any, label: str, depth: int = 0) -> None:
        if depth > 6 or len(records) >= MAX_ROWS:
            return
        if isinstance(o, dict):
            if sum(1 for k in o if parse_header(str(k))[0]) >= 2:
                records.append((str(o.get("sample") or o.get("id") or o.get("SampleID") or label), o))
            for k, v in o.items():
                if isinstance(v, (dict, list)):
                    walk(v, str(k), depth + 1)
        elif isinstance(o, list):
            for i, v in enumerate(o[:MAX_ROWS]):
                walk(v, f"{label}[{i}]", depth + 1)

    walk(obj, filename)
    out = []
    for label, rec in records:
        cols = {k: parse_header(k) for k in rec}
        reading = _reading(label, {k: v for k, v in rec.items()}, {k: v for k, v in cols.items() if v[0]}, filename, _hint(json.dumps(rec)[:500]))
        if reading:
            out.append(reading)
    return out


def looks_like_element_table(data: bytes, filename: str) -> bool:
    try:
        return bool(readings_for_file(data, filename))
    except Exception:   # malformed input is simply "not a table"
        return False


def readings_for_file(data: bytes, filename: str) -> list[dict]:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext in ("csv", "tsv", "txt"):
        return readings_from_csv(data, filename)
    if ext in ("xlsx", "xlsm"):
        return readings_from_xlsx(data, filename)
    if ext == "json":
        return readings_from_json(data, filename)
    return []


# --------------------------------------------------------------------------- free text (PDF reports, messages, transcripts)
_LINE = re.compile(r"\b(" + "|".join(sorted(list(OXIDES) + ELEMENTS + list(NAMES), key=len, reverse=True)) + r")\b\s*[:=]?\s*"
                   r"(<\s*LOD|ND|<\s*" + _NUM + r"|" + _NUM + r")\s*(%|wt%|ppm|mg/kg)?", re.I)


def readings_from_text(text: str, source: str = "text") -> list[dict]:
    """'Co 15.02 0.04', 'nickel: 18.6 %', 'Ni = 1200 ppm'. Splits multi-reading reports on 'Measurement info' / 'ID nnn'."""
    blocks = re.split(r"(?=Measurement info:)|(?=\bSample\s*(?:ID|No\.?|#)\s*[:=])", text) if text else []
    out = []
    for block in blocks or [text]:
        values, lod = {}, []
        for m in _LINE.finditer(block):
            token = m.group(1)
            key = token if token in OXIDES or token in ELEMENTS else NAMES.get(token.lower())
            if token.lower() in NAMES and token not in ELEMENTS:
                key = NAMES[token.lower()]
            if key is None and token.capitalize() in ELEMENTS:
                continue   # lowercase symbol-like words ("co", "ni") in prose are too ambiguous
            el, mult = OXIDES.get(key, (key, 1.0)) if key in OXIDES else (key, 1.0)
            if el is None:
                continue
            unit = (m.group(3) or "").lower()
            if unit in ("ppm", "mg/kg"):
                mult *= 1e-4
            v, cens = parse_value(m.group(2))
            if cens:
                lod.append(el)
            elif v is not None and el not in values and 0 <= v * mult <= 100:
                values[el] = round(v * mult, 6)
        if len(set(values) & CORE) >= 2:
            label = (re.search(r"\bID\s+(\d+)", block) or re.search(r"([\w-]+\.pdz)", block))
            out.append({"label": label.group(1) if label else f"{source} reading {len(out) + 1}", "values": values,
                        "below_lod": sorted(set(lod) - set(values)), "source": source, "basis_hint": _hint(block), "notes": []})
    return out[:MAX_ROWS]


# --------------------------------------------------------------------------- OCR boxes (photos of instrument screens)
SYMBOLS = {e for e in ELEMENTS}
_VALUE = re.compile(r"^\s*([<+\-]?)\s*(" + _NUM + r")\s*%?\s*$")


def pair_ocr_boxes(boxes: Iterable[tuple[float, float, str, float]], image_height: float) -> dict:
    """boxes: (x_center, y_center, text, confidence). Returns element values read from an instrument screen.

    A value is assigned to the element label on the same row, to its right and nearest. '±' lines are
    uncertainties, not values. Values with no readable label are returned separately and never assigned.
    """
    labels, values, sigmas, lt_marks = [], [], [], []
    for x, y, text, conf in boxes:
        if text.strip() in ("<", "＜", "‹", "«"):
            lt_marks.append((x, y))   # OCR often splits "< 0.100" into "<" and "0.100": a censored value
            continue
        t = text.strip().replace("O", "0") if re.fullmatch(r"[<+\-]?\s*[\dO.,]+\s*%?", text.strip()) else text.strip()
        if t in SYMBOLS:
            labels.append((x, y, t, conf))
        elif re.match(r"^\s*(±|\+/-|�|±)", text) or "±" in text or "�" in text:
            m = re.search(_NUM, text)
            if m:
                sigmas.append((x, y, float(m.group(0).replace(",", "."))))
        else:
            m = _VALUE.match(t)
            if m:
                values.append((x, y, m.group(1), float(m.group(2).replace(",", ".")), conf))
    # Two OCR passes can read the same "± 0.04" line once with the "±" and once without (or as "10.04"): a number at
    # the same spot as a "±" reading is that uncertainty line, never a value (found by the 2026-11-18 photo sweep).
    values = [v for v in values
              if not any(abs(v[0] - sx) < 0.05 * image_height and abs(v[1] - sy) < 0.012 * image_height for sx, sy, _ in sigmas)]
    row_tol = 0.045 * image_height
    used, result, lod, flagged = set(), {}, [], []
    for lx, ly, el, _ in sorted(labels, key=lambda b: b[1]):
        cands = [(vx - lx, abs(vy - ly), i) for i, (vx, vy, *_rest) in enumerate(values)
                 if i not in used and vx > lx and abs(vy - ly) <= row_tol and vx - lx < 0.6 * image_height]
        if not cands:
            continue
        # values sit level with or slightly above their element tile; the "±" line sits below it
        def cost(c):
            vy_ = values[c[2]][1]
            below = max(0.0, vy_ - (ly + 0.01 * image_height))
            return c[1] * 2 + c[0] * 0.2 + below * 6
        _, _, i = min(cands, key=cost)
        used.add(i)
        vx, vy, sign, v, conf = values[i]
        if any(lx < mx < vx and abs(my - vy) <= row_tol * 0.6 for mx, my in lt_marks):
            sign = "<"
        # On screens that print "± x" under every measured value, a number with no ± line is a detection
        # limit whose "<" the OCR dropped: censored (UNKNOWN), never a measured value.
        if sign != "<" and len(sigmas) >= 2 and not any(abs(sx - vx) < 0.12 * image_height and 0 < sy - vy < 0.08 * image_height
                                                         for sx, sy, _ in sigmas):
            sign = "<"
        if sign == "<":
            lod.append(el)
        elif el not in result:
            result[el] = v
            if sign in "+-" and sign:
                flagged.append(el)   # xSORT +/- marks out-of-grade-spec, not a sign of the value
    unlabelled = [(x, y, v) for i, (x, y, s, v, _) in enumerate(values) if i not in used and s != "<"]
    out = {"values": result, "below_lod": sorted(set(lod) - set(result)), "unlabelled_values": [v for _, _, v in unlabelled],
           "unlabelled_positions": [(x, y) for x, y, _ in unlabelled], "grade_flags": flagged, "plausible": True, "plausibility_note": None}
    return check_plausible(out)


def check_plausible(reading: dict) -> dict:
    """Mass-balance guard: element wt% cannot add up to (much) more than 100 %. An implausible photo reading
    (crumpled paper, a mis-paired table) is kept for display but marked unusable, never assessed."""
    total = sum(v for v in reading["values"].values() if v is not None)
    if total > 105 or any(v > 100 for v in reading["values"].values()):
        reading["plausible"] = False
        reading["plausibility_note"] = f"values add up to {total:.1f} %; the photo was probably mis-read. Retake it flat and in focus, or type the values."
    return reading
