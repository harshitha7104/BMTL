"""Spectral preprocessing: analysis range, resampling to a fixed grid, smoothing
and convex-hull continuum removal.

The original reflectance is never changed; every function returns new arrays.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

import numpy as np
from scipy.signal import savgol_filter

log = logging.getLogger(__name__)


class PreprocessError(ValueError):
    """Raised with a readable message when a spectrum cannot be preprocessed."""


@dataclass(frozen=True)
class PreprocessConfig:
    # The i.hyper.spectroscopy engine only interprets 400–2500 nm; 350–399 nm is
    # also ~7x noisier than 400–450 nm in this dataset (Phase 1 report).
    range_nm: tuple[float, float] = (400.0, 2500.0)
    # Common 1 nm grid. The source grid has two sub-nm offsets at detector joins;
    # linear interpolation onto integer nm moves values by <=0.1 nm.
    step_nm: float = 1.0
    # Savitzky–Golay smoothing of the copy used for feature detection. 11 nm is
    # about the native SWIR resolution of field spectrometers, so real mineral
    # absorptions (FWHM >= ~20 nm) survive while 1–3 nm ripples do not.
    smooth_window_nm: int = 11
    smooth_polyorder: int = 2
    # Largest gap (missing / non-finite values) that is bridged by interpolation.
    max_gap_nm: float = 10.0
    # How far a new spectrum may fall short of the range ends (edge values held).
    edge_tolerance_nm: float = 5.0

    def grid(self) -> np.ndarray:
        lo, hi = self.range_nm
        return np.arange(lo, hi + self.step_nm / 2, self.step_nm)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProcessedSpectrum:
    wavelength_nm: np.ndarray      # analysis grid
    reflectance: np.ndarray        # resampled, unsmoothed
    smoothed: np.ndarray           # smoothed copy used for continuum/feature work
    continuum: np.ndarray          # upper convex hull of the smoothed copy
    continuum_removed: np.ndarray  # smoothed / continuum, in (0, 1]
    notes: list[str]


def resample_spectrum(wl_nm: np.ndarray, refl: np.ndarray, cfg: PreprocessConfig) -> tuple[np.ndarray, list[str]]:
    """Linear interpolation of a spectrum onto the analysis grid."""
    wl_nm = np.asarray(wl_nm, dtype=float)
    refl = np.asarray(refl, dtype=float)
    if wl_nm.shape != refl.shape or wl_nm.ndim != 1:
        raise PreprocessError("Wavelength and reflectance arrays must be 1-D and the same length.")
    order = np.argsort(wl_nm)
    wl_nm, refl = wl_nm[order], refl[order]
    ok = np.isfinite(wl_nm) & np.isfinite(refl)
    if ok.sum() < 10:
        raise PreprocessError("Spectrum is empty or has fewer than 10 valid values.")
    wl_ok, r_ok = wl_nm[ok], refl[ok]
    notes = []
    lo, hi = cfg.range_nm
    if wl_ok[0] > lo + cfg.edge_tolerance_nm or wl_ok[-1] < hi - cfg.edge_tolerance_nm:
        raise PreprocessError(
            f"Spectrum covers {wl_ok[0]:.0f}–{wl_ok[-1]:.0f} nm but {lo:.0f}–{hi:.0f} nm is required "
            "(the model and the rule engine are defined on this range).")
    inside = wl_ok[(wl_ok >= lo - cfg.edge_tolerance_nm) & (wl_ok <= hi + cfg.edge_tolerance_nm)]
    gaps = np.diff(inside)
    if gaps.size and gaps.max() > cfg.max_gap_nm:
        i = int(np.argmax(gaps))
        raise PreprocessError(
            f"Gap of {gaps.max():.0f} nm in valid data between {inside[i]:.0f} and {inside[i+1]:.0f} nm "
            f"(max {cfg.max_gap_nm:.0f} nm can be bridged).")
    n_bad = int((~ok).sum())
    if n_bad:
        notes.append(f"{n_bad} non-finite value(s) bridged by linear interpolation")
    n_out = int(np.sum(wl_ok < lo) + np.sum(wl_ok > hi))
    if n_out:
        notes.append(f"{n_out} band(s) outside {lo:.0f}–{hi:.0f} nm excluded from analysis (kept in original)")
    # np.interp holds edge values for the (<= edge_tolerance) uncovered ends.
    return np.interp(cfg.grid(), wl_ok, r_ok), notes


def smooth_spectrum(refl: np.ndarray, cfg: PreprocessConfig) -> np.ndarray:
    window = int(round(cfg.smooth_window_nm / cfg.step_nm)) | 1  # odd number of points
    if window <= cfg.smooth_polyorder + 1:
        return refl.copy()
    return savgol_filter(refl, window, cfg.smooth_polyorder, mode="interp")


def upper_hull(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Upper convex hull of (x, y) evaluated at x (monotone-chain algorithm).
    x must be strictly increasing."""
    hull: list[int] = []
    for i in range(len(x)):
        while len(hull) >= 2:
            i0, i1 = hull[-2], hull[-1]
            # Remove i1 if it lies on or below the segment i0 -> i
            cross = (x[i1] - x[i0]) * (y[i] - y[i0]) - (y[i1] - y[i0]) * (x[i] - x[i0])
            if cross >= 0:
                hull.pop()
            else:
                break
        hull.append(i)
    return np.interp(x, x[hull], y[hull])


def continuum_remove(wl: np.ndarray, refl: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (continuum, refl / continuum). Values are <= 1 by construction."""
    if np.any(refl <= 0):
        refl = np.maximum(refl, 1e-6)
    cont = upper_hull(wl, refl)
    return cont, np.clip(refl / cont, 0.0, 1.0)


def preprocess_spectrum(wl_nm: np.ndarray, refl: np.ndarray, cfg: PreprocessConfig | None = None) -> ProcessedSpectrum:
    cfg = cfg or PreprocessConfig()
    resampled, notes = resample_spectrum(wl_nm, refl, cfg)
    grid = cfg.grid()
    smoothed = smooth_spectrum(resampled, cfg)
    cont, cr = continuum_remove(grid, smoothed)
    return ProcessedSpectrum(grid, resampled, smoothed, cont, cr, notes)
