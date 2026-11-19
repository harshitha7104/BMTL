"""Adapter around the unmodified i.hyper.spectroscopy rule engine.

The engine file is loaded the same way its authors' test suite does: with
`grass.script` replaced by a stub, so no GRASS GIS installation is needed.

Input representation (why it is not the raw 1 nm spectrum): the engine treats
every (center, fwhm, reflectance) triplet as a candidate absorption and
estimates its depth as 1 - R / max(R of other triplets within ±150 nm). We pass
it continuum-removed *features* instead:

  * one triplet per extracted feature: (center_nm, fwhm_nm, 1 - depth)
  * two "continuum anchor" triplets per feature at its shoulders with CR = 1.0
    (placed within 149 nm of the centre). Anchors have depth 0 so the engine
    never matches them to a species, but they make the engine's local
    continuum exactly 1.0 — so its depth equals our continuum-removed depth.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from .features import Feature

log = logging.getLogger(__name__)

ENGINE_PATH = Path(__file__).resolve().parent.parent / "i.hyper.spectroscopy-main" / "i.hyper.spectroscopy.py"
_ANCHOR_FWHM_NM = 1.0       # >= engine's 0.5 nm cut-off, so anchors are kept as neighbours
_MAX_ANCHOR_OFFSET_NM = 149.0
_engine = None


class EngineUnavailable(RuntimeError):
    pass


def load_engine(path: Path = ENGINE_PATH) -> types.ModuleType:
    """Import i.hyper.spectroscopy.py without GRASS. Cached after first call."""
    global _engine
    if _engine is not None:
        return _engine
    if not path.is_file():
        raise EngineUnavailable(f"Rule engine not found at {path}. Keep the i.hyper.spectroscopy-main folder "
                                "next to app.py.")
    sys.modules.setdefault("grass", MagicMock())
    sys.modules.setdefault("grass.script", MagicMock())
    spec = importlib.util.spec_from_file_location("i_hyper_spectroscopy", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["i_hyper_spectroscopy"] = module  # needed for its dataclasses
    # Do not write __pycache__ into the original repository folder.
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise EngineUnavailable(f"Could not load the rule engine: {exc}") from exc
    finally:
        sys.dont_write_bytecode = previous
    log.info("Loaded rule engine from %s (%d features, %d rules)", path.name,
             len(module.SPECTRAL_FEATURES_DB), len(module.COMPOSITE_RULES))
    _engine = module
    return module


def features_to_triplets(features: list[Feature]) -> list[tuple[float, float, float]]:
    triplets = []
    for f in features:
        triplets.append((f.center_nm, f.fwhm_nm, 1.0 - f.depth))
        left = max(f.start_nm, f.center_nm - _MAX_ANCHOR_OFFSET_NM)
        right = min(f.end_nm, f.center_nm + _MAX_ANCHOR_OFFSET_NM)
        if left < f.center_nm:
            triplets.append((left, _ANCHOR_FWHM_NM, 1.0))
        if right > f.center_nm:
            triplets.append((right, _ANCHOR_FWHM_NM, 1.0))
    return triplets


@dataclass
class RuleResult:
    hypotheses: list[dict]        # ranked; 'rule_score' is the engine's heuristic score
    chromophores: list[dict]      # species matched to individual features
    dominant_class: str | None    # engine's own choice (top score >= 0.60), may be None
    flags: list[str]


def compute_ndre(wl: np.ndarray, refl: np.ndarray) -> float:
    """NDRE as the engine computes it (865 nm vs 710 nm), for its vegetation gate."""
    eng = load_engine()
    nir = refl[eng._nearest_band_index(wl, eng._NDRE_NIR_NM)]
    red = refl[eng._nearest_band_index(wl, eng._NDRE_RED_EDGE_NM)]
    return float(eng._safe_ndre(np.array([nir]), np.array([red]))[0])


def run_rules(features: list[Feature], ndre: float | None, min_band_depth: float = 0.02) -> RuleResult:
    eng = load_engine()
    res = eng.interpret_spectrum(features_to_triplets(features), min_band_depth=min_band_depth, ndre=ndre)
    composite_names = {r["name"] for r in eng.COMPOSITE_RULES}
    hyps = [{
        "name": h.name,
        "kind": "composite_rule" if h.name in composite_names else "single_species",
        "category": h.category,
        "rule_score": float(h.confidence),
        "evidence": list(h.evidence),
        "species": list(h.atomic_species),
    } for h in res.hypotheses]
    chrom = [{"species": c.species, "mechanism": c.mechanism, "wavelengths_nm": list(c.supporting_features),
              "rule_score": float(c.confidence), "notes": c.notes} for c in res.chromophores]
    return RuleResult(hyps, chrom, res.dominant_class, list(res.flag_notes))


def rule_info(name: str) -> dict | None:
    """The engine's composite rule definition (for explanations)."""
    for r in load_engine().COMPOSITE_RULES:
        if r["name"] == name:
            return r
    return None
