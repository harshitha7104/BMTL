"""Name the most likely cathode compound ("mineral") from an element composition.

PROVENANCE: stoichiometric rules from the published formulas of commercial cathode materials, applied
to molar metal ratios. It is a chemistry inference (INFERRED), not a phase measurement: XRF/ICP give
elements, not crystal structure. Black mass is often a blend; when no single compound fits within
tolerance the answer is "mixed feed", with the ratios shown so a person can judge.
"""

from __future__ import annotations

import math

AW = {"Ni": 58.693, "Co": 58.933, "Mn": 54.938, "Fe": 55.845, "P": 30.974, "Al": 26.982}
# molar fractions of (Ni, Mn, Co) among Ni+Mn+Co for layered oxides
LAYERED = {
    "NMC111 (LiNi1/3Mn1/3Co1/3O2)": (1 / 3, 1 / 3, 1 / 3),
    "NMC532 (LiNi0.5Mn0.3Co0.2O2)": (0.5, 0.3, 0.2),
    "NMC622 (LiNi0.6Mn0.2Co0.2O2)": (0.6, 0.2, 0.2),
    "NMC811 (LiNi0.8Mn0.1Co0.1O2)": (0.8, 0.1, 0.1),
    "LCO (LiCoO2)": (0.0, 0.0, 1.0),
    "LMO (LiMn2O4)": (0.0, 1.0, 0.0),
}
FIT_TOLERANCE = 0.12   # max Euclidean distance in (Ni, Mn, Co) fraction space for a single-compound call


def name_compound(comp: dict[str, float | None], material_label: str | None = None) -> dict:
    """comp: element -> wt% (ICP-equivalent preferred). Returns name, state, ratios and how it was decided."""
    if material_label == "NOT_BLACK_MASS_LEAD":
        return {"name": "Lead-acid battery paste (PbSO4 / PbO / Pb)", "state": "INFERRED", "basis": "Pb-dominant composition"}
    if material_label in ("NO_TRANSITION_METAL_SIGNAL", "INSTRUMENT_MODE_ARTIFACT", None) and not comp:
        return {"name": None, "state": "UNKNOWN", "basis": "no usable composition"}
    mol = {e: max(0.0, float(comp.get(e) or 0.0)) / AW[e] for e in AW}
    tm = mol["Ni"] + mol["Mn"] + mol["Co"]
    total_metal = tm + mol["Fe"]
    if total_metal <= 0:
        return {"name": None, "state": "UNKNOWN",
                "basis": "no Ni/Mn/Co/Fe signal: could be a lithium salt (e.g. Li2CO3), graphite or another non-cathode material; XRF cannot see Li or C"}
    if mol["Fe"] > tm and "P" not in comp:
        return {"name": "Probably LFP (LiFePO4) - phosphorus not reported", "state": "INFERRED",
                "basis": "iron dominates the cathode metals, but P was not in the input, so LiFePO4 cannot be confirmed; measure P"}
    if mol["Fe"] > tm and mol["P"] > 0:
        pfe = mol["P"] / mol["Fe"]
        if 0.6 <= pfe <= 1.4:
            name = "LMFP (LiMnxFe1-xPO4)" if mol["Mn"] > 0.15 * mol["Fe"] else "LFP (LiFePO4)"
            return {"name": name, "state": "INFERRED", "basis": f"Fe-dominant with P/Fe molar ratio {pfe:.2f} (LiFePO4 = 1.0)",
                    "molar_ratios": {"P/Fe": round(pfe, 3)}}
        return {"name": "Fe/P-rich feed, not stoichiometric LFP", "state": "INFERRED",
                "basis": f"P/Fe molar ratio {pfe:.2f} is outside the LFP range 0.6-1.4", "molar_ratios": {"P/Fe": round(pfe, 3)}}
    if tm <= 0:   # iron present but no Ni/Mn/Co and no usable P (e.g. P reported as 0): no layered-oxide ratio exists
        return {"name": None, "state": "UNKNOWN",
                "basis": "iron without Ni/Mn/Co and without phosphorus: not a recognisable cathode composition"}
    frac = (mol["Ni"] / tm, mol["Mn"] / tm, mol["Co"] / tm)
    ratios = {"Ni": round(frac[0], 3), "Mn": round(frac[1], 3), "Co": round(frac[2], 3)}
    al_share = mol["Al"] / (mol["Ni"] + mol["Co"] + mol["Al"]) if (mol["Ni"] + mol["Co"] + mol["Al"]) else 0
    if frac[0] >= 0.75 and frac[1] < 0.05 and al_share >= 0.03:
        return {"name": "NCA (LiNi0.8Co0.15Al0.05O2)", "state": "INFERRED", "molar_ratios": ratios,
                "basis": "Ni-rich, almost no Mn, Al present (note: Al foil in black mass can mimic NCA's Al)"}
    dists = {name: math.dist(frac, ref) for name, ref in LAYERED.items()}
    best = min(dists, key=dists.get)
    if dists[best] <= FIT_TOLERANCE:
        return {"name": best, "state": "INFERRED", "molar_ratios": ratios, "distance": round(dists[best], 3),
                "basis": f"Ni:Mn:Co molar ratio {frac[0]:.2f}:{frac[1]:.2f}:{frac[2]:.2f} is closest to {best.split()[0]}"}
    for idx, (name, formula) in enumerate((("LCO", "LiCoO2"), ("LMO", "LiMn2O4"))):
        share = frac[2] if idx == 0 else frac[1]
        if share >= 0.75:
            return {"name": f"{name}-rich feed (mostly {formula}, blended with other cathode material)", "state": "INFERRED",
                    "molar_ratios": ratios, "basis": f"{'Co' if idx == 0 else 'Mn'} is {share:.0%} of Ni+Mn+Co: dominated by {name}, but not pure {name}"}
    ranked = sorted(dists, key=dists.get)[:2]
    return {"name": "Mixed feed (no single cathode grade)", "state": "INFERRED", "molar_ratios": ratios,
            "closest": [{"compound": n, "distance": round(dists[n], 3)} for n in ranked],
            "basis": f"Ni:Mn:Co {frac[0]:.2f}:{frac[1]:.2f}:{frac[2]:.2f} is not within {FIT_TOLERANCE} of any single grade; likely a blend of "
                     f"{ranked[0].split()[0]} and {ranked[1].split()[0]}-type material"}
