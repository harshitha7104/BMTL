"""Absorption-feature extraction from continuum-removed spectra.

A feature is a local minimum of the continuum-removed (CR) curve with enough
prominence and width to be a real absorption, not a single noisy 1 nm point.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy.signal import find_peaks, peak_widths

# Minimum local depth (prominence in CR units) for an absorption to be reported.
MIN_PROMINENCE = 0.01
# Minimum full width at half depth (nm); narrower minima are noise at 1 nm sampling.
MIN_FWHM_NM = 8.0

# Broad spectral regions, used only to describe where a feature lies.
REGIONS = [
    (400, 700, "VIS"),
    (700, 1300, "NIR (Fe crystal-field / charge-transfer)"),
    (1300, 1600, "SWIR-1 (OH / H2O overtones)"),
    (1600, 2100, "SWIR-1 (H2O combination ~1900 nm)"),
    (2100, 2400, "SWIR-2 (metal-OH, CO3)"),
    (2400, 2501, "SWIR-2 edge"),
]


@dataclass
class Feature:
    center_nm: float      # wavelength of the CR minimum
    depth: float          # 1 - CR at the minimum (depth below the hull continuum)
    prominence: float     # local depth relative to the neighbouring shoulders
    fwhm_nm: float        # width at half prominence
    start_nm: float       # left shoulder (prominence base)
    end_nm: float         # right shoulder (prominence base)
    area: float           # integral of (1 - CR) between shoulders, nm
    region: str
    reflectance: float    # smoothed reflectance at the minimum
    edge_truncated: bool  # touches the analysis range end; shape incomplete

    def to_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def _region(wl: float) -> str:
    for lo, hi, name in REGIONS:
        if lo <= wl < hi:
            return name
    return "outside"


def extract_features(wl: np.ndarray, cr: np.ndarray, smoothed: np.ndarray,
                     min_prominence: float = MIN_PROMINENCE, min_fwhm_nm: float = MIN_FWHM_NM) -> list[Feature]:
    """Return absorption features sorted by depth (deepest first)."""
    step = float(np.median(np.diff(wl)))
    signal = 1.0 - cr
    peaks, props = find_peaks(signal, prominence=min_prominence)
    if peaks.size == 0:
        return []
    widths, _, left_ip, right_ip = peak_widths(signal, peaks, rel_height=0.5, prominence_data=(
        props["prominences"], props["left_bases"], props["right_bases"]))
    feats = []
    for k, p in enumerate(peaks):
        fwhm = widths[k] * step
        if fwhm < min_fwhm_nm:
            continue
        lb, rb = int(props["left_bases"][k]), int(props["right_bases"][k])
        seg = slice(lb, rb + 1)
        feats.append(Feature(
            center_nm=float(wl[p]), depth=float(signal[p]), prominence=float(props["prominences"][k]),
            fwhm_nm=float(fwhm), start_nm=float(wl[lb]), end_nm=float(wl[rb]),
            area=float(np.trapezoid(signal[seg], wl[seg])), region=_region(float(wl[p])),
            reflectance=float(smoothed[p]),
            edge_truncated=bool(lb == 0 or rb == len(wl) - 1 or p >= len(wl) - 3),
        ))
    feats.sort(key=lambda f: f.depth, reverse=True)
    return feats
