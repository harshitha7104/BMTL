"""
Lot-analyst agent: compares every black-mass reading in a conversation.

Deterministic statistics (no AI needed): per-element mean / range / spread, robust outliers
(median and MAD, |z| > 3.5 with at least 4 readings), chemistry consistency, and a plan for which
readings to send for ICP-OES first (outliers, the most uncertain, and one per chemistry group).
It never invents values: everything is computed from readings the tools produced.
"""
from __future__ import annotations

import statistics
from typing import Any, Dict, List

from app.copilot.agents.readings import ELEMENTS

MAX_ICP_PICKS = 3


def analyse(readings: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not readings:
        return {"status": "no_readings", "message": "No black-mass readings in this conversation yet. Send XRF values, a .pdz, a table, a report or a photo first."}
    elements = ELEMENTS + ["Li"]
    stats: Dict[str, Any] = {}
    outliers: List[Dict[str, Any]] = []
    for e in elements:
        vals = [(r["label"], r["values"][e]) for r in readings if e in r["values"]]
        if not vals:
            continue
        xs = [v for _, v in vals]
        mean = statistics.fmean(xs)
        sd = statistics.pstdev(xs) if len(xs) > 1 else 0.0
        stats[e] = {"n": len(xs), "mean": round(mean, 3), "min": round(min(xs), 3), "max": round(max(xs), 3),
                    "spread_pct": round(100 * sd / mean, 1) if mean else None}
        if len(xs) >= 4:
            med = statistics.median(xs)
            mad = statistics.median([abs(x - med) for x in xs]) or 1e-9
            for label, x in vals:
                z = 0.6745 * (x - med) / mad
                if abs(z) > 3.5:
                    outliers.append({"label": label, "element": e, "value": round(x, 3), "lot_median": round(med, 3), "robust_z": round(z, 1)})
    groups: Dict[str, List[str]] = {}
    for r in readings:
        groups.setdefault(r.get("compound") or r.get("material") or "UNKNOWN", []).append(r["label"])
    consistent = len(groups) == 1
    # ICP plan: outliers first, then the most uncertain reading (widest relative Ni/Co band), then one per chemistry group
    picks: List[Dict[str, str]] = []

    def add(label: str, why: str) -> None:
        if len(picks) < MAX_ICP_PICKS and label not in {p["label"] for p in picks}:
            picks.append({"label": label, "why": why})

    for o in outliers:
        add(o["label"], f"{o['element']} {o['value']} % is far from the lot median {o['lot_median']} % (robust z {o['robust_z']})")

    def rel_uncertainty(r):
        rel = [r["bands"][e] / r["values"][e] for e in ("Ni", "Co") if e in r["bands"] and r["values"].get(e)]
        return max(rel) if rel else 0.0
    for r in sorted(readings, key=rel_uncertainty, reverse=True)[:1]:
        if rel_uncertainty(r) > 0:
            add(r["label"], f"widest relative uncertainty (Ni/Co band about ±{rel_uncertainty(r):.0%} of the estimate)")
    if not consistent:
        for g, labels in groups.items():
            add(labels[0], f"representative of the '{g}' group (the lot mixes chemistries)")
    return {
        "status": "ok",
        "readings": len(readings),
        "per_element": stats,
        "chemistry_groups": groups,
        "chemistry_consistent": consistent,
        "outliers": outliers,
        "send_for_icp_first": picks,
        "note": "Statistics of the model's ICP-equivalent estimates (INFERRED). Spread includes real lot variation and measurement error. "
                "Lab confirmation of the selected samples is the next step.",
    }
