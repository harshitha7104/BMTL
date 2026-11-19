"""Data augmentation from the REAL ACE samples (manager request 2026-11-16: grow the training data ~100x).

PROVENANCE: every row produced here is AUGMENTED, derived from real readings; it is never a measurement
and is never used to report accuracy. Each row lists its parent sample(s) so that leave-one-sample-out
evaluation can drop every augmented row derived from the held-out sample (no leakage).

Two physically motivated generators:
  1. Measurement replicates: a real reading re-drawn with the gun's own repeatability, estimated from the
     real 90 s vs 120 s readings of the same samples (per element, floor 1 % relative), and ICP drawn with
     2 % relative repeatability (typical ICP-OES; an assumption, stated). Label = the parent's ICP.
  2. Blends: mass-weighted mixtures of two real samples of the same calibration basis, w ~ U(0.1, 0.9).
     ICP mixes exactly by mass balance; XRF is approximated as the same weighted mean, which ignores
     matrix effects between the two materials (stated caveat). Label = mixed ICP.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ELEMENTS = ["Ni", "Co", "Mn", "Fe", "Cu", "Al", "P", "Si", "S", "Ca", "Ti", "Cr", "Zn", "Mg"]
TARGETS = ["Ni", "Co", "Mn", "Fe", "Cu", "Al", "P", "Li"]
ICP_REL_SD = 0.02
MIN_REL_SD = 0.01


def gun_repeatability(pairs: pd.DataFrame) -> dict[str, float]:
    """Relative SD per element from real 90 s vs 120 s readings of the same samples (standardised basis)."""
    std = pairs[pairs.calibration_basis == "type_standardised"]
    g90, g120 = std[std.dwell_s == 90].set_index("sample"), std[std.dwell_s == 120].set_index("sample")
    common = g90.index.intersection(g120.index)
    out = {}
    for e in ELEMENTS:
        a, b = g90.loc[common, f"xrf_{e}"], g120.loc[common, f"xrf_{e}"]
        ok = a.notna() & b.notna() & ((a + b) > 0.05)
        rel = ((a[ok] - b[ok]).abs() / ((a[ok] + b[ok]) / 2) / np.sqrt(2)) if ok.any() else pd.Series(dtype=float)
        out[e] = float(max(MIN_REL_SD, rel.median())) if len(rel) else 0.05
    return out


def augment(pairs: pd.DataFrame, n_replicates: int = 50, n_blends_per_row: int = 50, seed: int = 20261116,
            exclude: tuple[str, ...] = ("6",)) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rel_sd = gun_repeatability(pairs)
    real = pairs[~pairs["sample"].isin(exclude)].reset_index(drop=True)
    rows = []
    for _, r in real.iterrows():
        for k in range(n_replicates):
            row = r.to_dict()
            for e in ELEMENTS:
                v = r[f"xrf_{e}"]
                if pd.notna(v):
                    row[f"xrf_{e}"] = max(0.0, v * (1 + rng.normal(0, rel_sd[e])))
            for t in TARGETS:
                if pd.notna(r[f"icp_{t}"]):
                    row[f"icp_{t}"] = max(0.0, r[f"icp_{t}"] * (1 + rng.normal(0, ICP_REL_SD)))
            row.update(record_id=f"AUG_REP_{r.record_id}_{k}", provenance="AUGMENTED replicate", parents=r["sample"],
                       label_source="AUGMENTED", source=f"replicate of {r.record_id}")
            rows.append(row)
    for basis, grp in real.groupby("calibration_basis"):
        grp = grp.reset_index(drop=True)
        n = len(grp) * n_blends_per_row
        for k in range(n):
            i, j = rng.choice(len(grp), 2, replace=False)
            a, b = grp.iloc[i], grp.iloc[j]
            if a["sample"] == b["sample"]:
                continue
            w = rng.uniform(0.1, 0.9)
            row = a.to_dict()
            for e in ELEMENTS:
                va, vb = a[f"xrf_{e}"], b[f"xrf_{e}"]
                row[f"xrf_{e}"] = w * va + (1 - w) * vb if pd.notna(va) and pd.notna(vb) else np.nan
                row[f"xrf_{e}_lod"] = bool(a[f"xrf_{e}_lod"]) and bool(b[f"xrf_{e}_lod"])
            for t in TARGETS:
                row[f"icp_{t}"] = w * a[f"icp_{t}"] + (1 - w) * b[f"icp_{t}"]
            row.update(record_id=f"AUG_MIX_{basis[:3]}_{k}", sample=f"{a['sample']}+{b['sample']}", provenance="AUGMENTED blend",
                       parents=f"{a['sample']}|{b['sample']}", blend_weight=round(w, 3), label_source="AUGMENTED",
                       source=f"{w:.2f} x {a.record_id} + {1 - w:.2f} x {b.record_id} (XRF mixed linearly: matrix effects ignored)")
            rows.append(row)
    aug = pd.DataFrame(rows)
    aug["data_origin"] = "AUGMENTED (derived from real ACE samples; not a measurement)"
    return aug


def drop_parents(aug: pd.DataFrame, held_out: str) -> pd.DataFrame:
    """Augmented rows that do not descend from the held-out sample."""
    return aug[~aug["parents"].astype(str).str.split("|").apply(lambda ps: held_out in ps)]
