"""Parser for the Bruker S1 TITAN results export (`Results.csv`).

PROVENANCE: real export from the ACE Bruker XRF trial (19 and 26 Oct 2026).
The export repeats a header row whenever the element list changes (different
application / calibration), so each data row is read against the header line
immediately above it. "< LOD" is kept as censored (value None, below_lod True),
never converted to 0.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import pandas as pd

META = ["File #", "DateTime", "Operator", "UNIT", "ID", "Application", "Method", "ElapsedTime", "Alloy 1", "Match Qual 1", "Alloy 2",
        "Match Qual 2", "Alloy 3", "Match Qual 3", "Multiplier", "Cal Check"]


def read_results_csv(path: str | Path) -> pd.DataFrame:
    """Long table: one row per (reading, element)."""
    rows, header = [], None
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for line in csv.reader(handle):
            cells = [c.strip() for c in line]
            if not any(cells):
                continue
            if cells[0] == "File #":
                header = [c for c in cells if c]
                continue
            if header is None:
                raise ValueError("data row before any header row")
            record = dict(zip(header, cells))
            elements = [h for h in header if h not in META and not h.endswith(" Err")]
            for element in elements:
                raw, err = record.get(element, ""), record.get(f"{element} Err", "")
                censored = raw.upper().replace(" ", "") == "<LOD"
                rows.append({
                    "file_no": int(record["File #"]), "reading_id": int(record["ID"]),
                    "measured_at": datetime.strptime(record["DateTime"], "%m-%d-%Y %H:%M"),
                    "application": record["Application"], "method": record["Method"].rstrip("*"),
                    "type_standardised": record["Method"].endswith("*"), "elapsed_s": float(record["ElapsedTime"]),
                    "cal_check": record.get("Cal Check"), "analyte": element,
                    "value_pct": None if censored or raw == "" else float(raw), "below_lod": censored,
                    "error_pct": float(err) if err else None,   # instrument "Err" column
                })
    return pd.DataFrame(rows)
