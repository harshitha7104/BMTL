"""Inference with the REAL-data BMTL models (models/real/bmtl_real_models.joblib).

    from src.realmodels.predict import assess_reading
    assess_reading({"Ni": 20.1, "Co": 5.5, "Mn": 8.2, "Fe": 1.2, "Cu": 1.8, "Al": 1.8, "P": 0.86},
                   basis="type_standardised", instrument="S1 TITAN")

Returns OBSERVED gun values, INFERRED ICP-equivalent values with 90 % bands, INFERRED
lithium (LiX, never from a Li measurement), a material/chemistry call with confidence,
and UNKNOWN for anything that cannot be supported. No value is invented: an element the
gun did not report stays UNKNOWN.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.realmodels.compound import name_compound
from src.realmodels.train import ATOMIC_WEIGHT, ELEMENTS, MODELS, knn_predict, metal_moles, ratio_features, rule_flags

BASES = ("factory", "type_standardised")


@lru_cache(maxsize=1)
def load_models(path: str | None = None) -> dict:
    from src.realmodels.train import verified_model_path

    model_file = Path(path) if path else MODELS / "bmtl_real_models.joblib"
    return joblib.load(verified_model_path(model_file.parent))   # refuses a file that does not match its model card


def assess_reading(values: dict[str, float | None], *, basis: str, instrument: str = "S1 TITAN", below_lod: set[str] | None = None,
                   models: dict | None = None) -> dict:
    if basis not in BASES:
        raise ValueError(f"basis must be one of {BASES}")
    m = models or load_models()
    below_lod = below_lod or set()
    out = {"banner": m["banner"], "basis": basis, "instrument": instrument, "elements": {}, "lithium": None, "material": None}
    corrected = {}
    for e in ELEMENTS:
        raw = values.get(e)
        model = m["element"].get((basis, e))
        entry = {"observed": None if raw is None else {"value_pct": raw, "state": "OBSERVED", "source": instrument}}
        if e in below_lod:
            entry["observed"] = {"value_pct": None, "state": "UNKNOWN", "reason": "below limit of detection (censored)"}
        if raw is None or e in below_lod or model is None:
            entry["inferred"] = {"value_pct": None, "state": "UNKNOWN", "reason": "no gun value" if raw is None or e in below_lod else "no model for this basis"}
        else:
            est = max(0.0, model["a"] + model["b"] * float(raw))
            entry["inferred"] = {"value_pct": round(est, 3), "state": "INFERRED", "stage": model["stage"], "band_90": round(model["band_90"], 3),
                                 "low": round(max(0.0, est - model["band_90"]), 3), "high": round(est + model["band_90"], 3),
                                 "trained_on_samples": model["fit_samples"]}
            corrected[e] = est
        out["elements"][e] = entry
    li = m["lithium"].get(basis)
    needed = {"Ni", "Co", "Mn"}
    if li and needed <= corrected.keys():
        comp = pd.DataFrame([{e: corrected.get(e, 0.0) for e in ["Ni", "Co", "Mn", "Fe", "P"]}])
        if li.get("k_per_metal"):   # per-metal Li factors (Ni, Co, Mn, Fe paired with P)
            from src.realmodels.train import li_moles
            mol = li_moles(comp).iloc[0]
            est = float(ATOMIC_WEIGHT["Li"] * sum(li["k_per_metal"][m] * mol[m] for m in li["k_per_metal"]))
        else:
            est = float(li["k_li_per_metal_atom"] * ATOMIC_WEIGHT["Li"] * metal_moles(comp)[0])
        out["lithium"] = {"value_pct": round(est, 3), "state": "INFERRED", "method": "LiX: Li per transition-metal atom from corrected XRF metals",
                          "band_90": round(li["band_90"], 3), "low": round(max(0.0, est - li["band_90"]), 3), "high": round(est + li["band_90"], 3),
                          "note": "XRF cannot measure lithium; this is a stoichiometric inference, confirm by ICP"}
    else:
        out["lithium"] = {"value_pct": None, "state": "UNKNOWN", "reason": "Ni, Co and Mn estimates are all required"}
    frame = pd.DataFrame([{**{e: values.get(e) for e in ["Ni", "Co", "Mn", "Fe", "Cu", "P", "Pb"]}}])
    feats = ratio_features(frame).assign(instrument=instrument, alloy_sum=float(np.nansum([values.get(e) or 0 for e in ["Ni", "Co", "Mn", "Fe", "Cu", "Zr"]])))
    rule = rule_flags(feats).iloc[0]
    label, conf = knn_predict(m["detector_table"], feats)
    call = rule or (label[0] if conf[0] >= 0.4 else "UNKNOWN")
    out["material"] = {"label": call, "state": "INFERRED" if call != "UNKNOWN" else "UNKNOWN", "confidence": round(conf[0], 2),
                       "decided_by": "rule" if rule else "kNN on composition ratios", "nearest_class": label[0]}
    # cathode compound ("mineral"): from ICP-equivalent values where the model produced them, else the observed values
    comp = {e: (out["elements"][e]["inferred"].get("value_pct") if e in out["elements"] and out["elements"][e]["inferred"].get("value_pct") is not None
                else values.get(e)) for e in ["Ni", "Co", "Mn", "Fe", "P", "Al"]}
    if call == "INSTRUMENT_MODE_ARTIFACT":
        out["compound"] = {"name": None, "state": "UNKNOWN", "basis": "instrument was in an alloy mode; re-measure in a black-mass/mining mode"}
    else:
        out["compound"] = name_compound({k: v for k, v in comp.items() if v is not None}, call)
    return out
