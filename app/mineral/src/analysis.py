"""One spectrum through the deterministic chain:
resample -> smooth -> continuum removal -> features -> rule engine -> vector."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .engine import RuleResult, compute_ndre, run_rules
from .features import Feature, extract_features
from .preprocessing import PreprocessConfig, ProcessedSpectrum, preprocess_spectrum
from .quality import spectrum_flags

# Width of the bins used to turn the continuum-removed curve into the model's
# feature vector (210 values for 400–2500 nm). 10 nm keeps every mineral
# absorption (FWHM >= ~20 nm) while averaging out residual noise.
VECTOR_BIN_NM = 10


@dataclass
class Analysis:
    processed: ProcessedSpectrum
    features: list[Feature]
    rules: RuleResult
    ndre: float
    quality_flags: list[tuple]
    vector: np.ndarray
    notes: list[str] = field(default_factory=list)

    def has_flag(self, check: str) -> bool:
        return any(f[0] == check for f in self.quality_flags)


def cr_vector(cr: np.ndarray, step_nm: float, bin_nm: int = VECTOR_BIN_NM) -> np.ndarray:
    n = max(1, int(round(bin_nm / step_nm)))
    usable = (len(cr) // n) * n
    return cr[:usable].reshape(-1, n).mean(axis=1)


def analyse_spectrum(wl_nm: np.ndarray, refl: np.ndarray, cfg: PreprocessConfig | None = None) -> Analysis:
    cfg = cfg or PreprocessConfig()
    wl_nm, refl = np.asarray(wl_nm, float), np.asarray(refl, float)
    quality = spectrum_flags(wl_nm, refl)
    processed = preprocess_spectrum(wl_nm, refl, cfg)
    features = extract_features(processed.wavelength_nm, processed.continuum_removed, processed.smoothed)
    ndre = compute_ndre(processed.wavelength_nm, processed.reflectance)
    rules = run_rules(features, ndre)
    return Analysis(processed, features, rules, ndre, quality,
                    cr_vector(processed.continuum_removed, cfg.step_nm), list(processed.notes))
