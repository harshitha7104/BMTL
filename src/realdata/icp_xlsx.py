"""Parser for the ACE "BMTL output vs ICP" workbooks (29 Oct 2026, R2).

PROVENANCE: real company workbooks (`data/raw/ace_company/icp_reference/`). They hold,
per sample (A, B, C, 1-6):
  - ICP: the in-house master ICP value (wt%), the reference used for training;
  - Gun 90 s / Gun 120 s: the S1 TITAN's own "Black mass powder" result;
  - BMTL 90 s / 120 s: outputs of the company's earlier model (kept for comparison only).
The 90 s gun values come from .pdz 01287-01295; the 120 s .pdz files (01305-01313) were
not supplied, so the workbook is the only source of 120 s readings.
"""

from __future__ import annotations

import re
from pathlib import Path

import openpyxl
import pandas as pd

BLOCK = ["ICP", "Gun 90 s", "BMTL 90 s", "Diff 90 s (points)", "Diff 90 s (%)", "Gun 120 s", "BMTL 120 s", "Diff 120 s (points)", "Diff 120 s (%)"]


def _element(label: str) -> tuple[str, str | None]:
    """'Cobalt (Co)' -> ('Co', None); 'Lithium (Li) — BMTL LiX-0.2 (proposed)' -> ('Li', 'LiX-0.2'); 'Silicon (Si, as SiO2)' -> ('Si', 'SiO2')."""
    match = re.search(r"\(([A-Z][a-z]?)(?:, as ([A-Za-z0-9]+))?\)", label)
    if not match:
        raise ValueError(f"unrecognised element label {label!r}")
    variant = re.search(r"(LiX-[0-9.]+)", label)
    return match.group(1), variant.group(1) if variant else match.group(2)


def read_icp_workbook(path: str | Path) -> pd.DataFrame:
    """Long table: sample, element, variant, column (ICP / Gun 90 s / ...), value."""
    ws = openpyxl.load_workbook(path, data_only=True).worksheets[0]
    grid = [list(r) for r in ws.iter_rows(values_only=True)]
    names_row = next(i for i, r in enumerate(grid) if r and any(isinstance(c, str) and c.startswith("Sample ") for c in r))
    header_row = names_row + 1
    starts = [j for j, c in enumerate(grid[header_row]) if c == "ICP"]
    samples = [str(grid[names_row][j]).split("·")[0].replace("Sample", "").strip() for j in starts]
    roles = [("teach" if "teach" in str(grid[names_row][j]) else "test" if "TEST" in str(grid[names_row][j]) else None) for j in starts]
    rows = []
    for r in grid[header_row + 1:]:
        if r and isinstance(r[0], str) and r[0].startswith("Average gap"):
            break   # summary tables below are derived, not data
        if not r or not isinstance(r[0], str) or "(" not in r[0]:
            continue
        element, variant = _element(r[0])
        for sample, role, j in zip(samples, roles, starts):
            for k, column in enumerate(BLOCK):
                value = r[j + k] if j + k < len(r) else None
                if value is None or value == "":
                    continue
                rows.append({"sample": sample, "role_in_workbook": role, "element": element, "variant": variant, "column": column,
                             "value": None if value == "not visible" else float(value), "note": value if value == "not visible" else None})
    out = pd.DataFrame(rows)
    out["source_file"] = Path(path).name
    return out


def icp_reference(path: str | Path) -> pd.DataFrame:
    """Wide ICP reference: one row per sample, one column per element (wt%)."""
    long = read_icp_workbook(path)
    icp = long[(long.column == "ICP") & long.value.notna()]
    icp = icp.drop_duplicates(["sample", "element"])   # Li appears once per LiX variant with the same ICP value
    return icp.pivot(index="sample", columns="element", values="value")
