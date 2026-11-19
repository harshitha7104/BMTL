"""Data-quality checks. Every check only *flags*; nothing is removed or edited.

Severity levels:
    ERROR   – spectrum cannot be analysed as-is (e.g. empty / non-finite)
    WARNING – analysis possible but the result needs care / a user decision
    INFO    – noteworthy, no action expected
"""
from __future__ import annotations

import logging
from itertools import combinations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from .data_loader import SpectralDataset

log = logging.getLogger(__name__)

# The i.hyper.spectroscopy engine skips bands outside this range.
ENGINE_RANGE_NM = (400.0, 2500.0)

LOW_ALBEDO_MAX_REFL = 0.10       # max reflectance below this => weak absorption contrast
LOW_CONTRAST_REL_RANGE = 0.25    # (max-min)/mean below this => nearly featureless curve
SPIKE_WINDOW = 5                 # bands in the running-median filter
SPIKE_ROBUST_Z = 10.0            # residual > this many robust sigmas ...
SPIKE_MIN_ABS = 0.005            # ... AND larger than this in reflectance units
SPLICE_NEIGHBOURS = 10           # steps either side used as the local reference
SPLICE_ROBUST_Z = 6.0            # step this many robust sigmas off its neighbours ...
SPLICE_MIN_REL = 0.005           # ... AND >0.5% of mean reflectance (a quarter of the engine's 2% depth threshold)
# Edge-region noise is compared with the adjacent 50 nm on the same detector.
EDGE_REGIONS = {"350_400": ((350, 400), (400, 450)), "2450_2500": ((2450, 2501), (2400, 2450))}


def _flag(rows: list, sample: str, check: str, severity: str, value, threshold, detail: str):
    rows.append({"sample": sample, "check": check, "severity": severity,
                 "value": value, "threshold": threshold, "detail": detail})


def _robust_sigma(x: np.ndarray, axis=None) -> np.ndarray:
    med = np.median(x, axis=axis, keepdims=True)
    return 1.4826 * np.median(np.abs(x - med), axis=axis)


def spectral_angle(a: np.ndarray, b: np.ndarray) -> float:
    """Spectral angle (radians). Insensitive to overall brightness."""
    cos = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.arccos(np.clip(cos, -1.0, 1.0)))


def region_noise(spectrum: np.ndarray, wl: np.ndarray, lo: float, hi: float) -> float:
    """Median absolute second difference: a simple high-frequency noise proxy."""
    seg = spectrum[(wl >= lo) & (wl < hi)]
    return float(np.median(np.abs(np.diff(seg, 2)))) if seg.size > 3 else float("nan")


def find_spikes(spectrum: np.ndarray, wl: np.ndarray, lo: float = ENGINE_RANGE_NM[0],
                hi: float = ENGINE_RANGE_NM[1]) -> np.ndarray:
    """Indices (into the full spectrum) where a band departs sharply from its
    running median. Restricted to [lo, hi] so the uniformly noisy 350–400 nm
    edge, which is characterised by region_noise instead, does not swamp it."""
    sel = np.flatnonzero((wl >= lo) & (wl <= hi))
    seg = spectrum[sel]
    half = SPIKE_WINDOW // 2
    med = np.median(sliding_window_view(seg, SPIKE_WINDOW), axis=1)
    resid = seg[half:-half] - med
    sigma = max(float(_robust_sigma(resid)), 1e-9)
    hits = np.flatnonzero((np.abs(resid) > SPIKE_ROBUST_Z * sigma) & (np.abs(resid) > SPIKE_MIN_ABS))
    return sel[hits + half]


def splice_step_z(spectrum: np.ndarray, step_index: int) -> tuple[float, float]:
    """Return (step, robust z) for the step between bands step_index and step_index+1,
    relative to neighbouring steps. A real detector offset shows up as a large z."""
    steps = np.diff(spectrum)
    lo = max(0, step_index - SPLICE_NEIGHBOURS)
    hi = min(len(steps), step_index + SPLICE_NEIGHBOURS + 1)
    nb = np.delete(steps[lo:hi], step_index - lo)
    med = float(np.median(nb))
    sigma = max(float(_robust_sigma(nb)), 1e-6)
    step = float(steps[step_index])
    return step - med, (step - med) / sigma


def spectrum_flags(wl: np.ndarray, x: np.ndarray, m: dict | None = None) -> list[tuple]:
    """Per-spectrum checks shared by the dataset report and new-spectrum prediction.

    Returns (check, severity, value, threshold, detail) tuples. If `m` is given,
    the spike count is stored in it.
    """
    out = []
    finite = np.isfinite(x)
    if not finite.any():
        return [("empty_spectrum", "ERROR", 0, None, "no finite values")]
    xf = x[finite]
    n_nan, n_inf = int(np.isnan(x).sum()), int(np.isinf(x).sum())
    mean = float(xf.mean())
    rel_range = (float(xf.max()) - float(xf.min())) / mean if mean > 0 else float("nan")
    if n_nan or n_inf:
        out.append(("non_finite_values", "ERROR", n_nan + n_inf, 0, f"{n_nan} NaN and {n_inf} infinite values"))
    if (xf < 0).any():
        out.append(("negative_reflectance", "WARNING", int((xf < 0).sum()), 0,
                    "reflectance below 0 is physically impossible; check calibration"))
    if (xf > 1).any():
        out.append(("reflectance_above_1", "WARNING", int((xf > 1).sum()), 0,
                    "values >1 vs a white reference can be specular or calibration issues"))
    if float(xf.std()) == 0:
        out.append(("constant_spectrum", "ERROR", 0.0, 0, "all values identical"))
    if float(xf.max()) < LOW_ALBEDO_MAX_REFL:
        out.append(("low_albedo", "WARNING", round(float(xf.max()), 4), LOW_ALBEDO_MAX_REFL,
                    "dark sample: absorption depths will be small and noisier"))
    if rel_range < LOW_CONTRAST_REL_RANGE:
        out.append(("low_contrast", "WARNING", round(rel_range, 4), LOW_CONTRAST_REL_RANGE,
                    "nearly featureless curve: little spectral information to interpret"))
    in_range = (wl >= ENGINE_RANGE_NM[0]) & (wl <= ENGINE_RANGE_NM[1])
    if np.isfinite(x[in_range]).all() and in_range.sum() > SPIKE_WINDOW:
        spikes = find_spikes(x, wl)
        if m is not None:
            m["n_spikes"] = int(spikes.size)
        if spikes.size:
            out.append(("spike", "WARNING", int(spikes.size), SPIKE_ROBUST_Z,
                        "single-band outliers at " + ", ".join(f"{wl[i]:.1f} nm" for i in spikes[:10])))
    return out


def run_quality_checks(ds: SpectralDataset, samples: pd.DataFrame) -> dict:
    """Run all checks. Returns dataframes for per-sample metrics, flags,
    replicate consistency and cross-rock similarity, plus dataset-level facts."""
    wl, X, names = ds.wavelength_nm, ds.reflectance, ds.sample_names
    flags: list[dict] = []
    metrics: list[dict] = []
    splice_idx = [s["index"] for s in ds.wavelength_report.irregular_steps]
    below_engine = int(np.sum(wl < ENGINE_RANGE_NM[0]))
    above_engine = int(np.sum(wl > ENGINE_RANGE_NM[1]))

    for name, x in zip(names, X):
        finite = np.isfinite(x)
        m = {"sample": name, "n_nan": int(np.isnan(x).sum()), "n_inf": int(np.isinf(x).sum())}
        if not finite.any():
            _flag(flags, name, "empty_spectrum", "ERROR", 0, None, "no finite values")
            metrics.append(m)
            continue
        xf = x[finite]
        m.update({
            "n_negative": int((xf < 0).sum()), "n_above_1": int((xf > 1).sum()),
            "min": float(xf.min()), "max": float(xf.max()), "mean": float(xf.mean()),
            "std": float(xf.std()),
        })
        m["relative_range"] = (m["max"] - m["min"]) / m["mean"] if m["mean"] > 0 else float("nan")
        for key, ((lo, hi), (rlo, rhi)) in EDGE_REGIONS.items():
            edge, ref = region_noise(x, wl, lo, hi), region_noise(x, wl, rlo, rhi)
            m[f"noise_{key}"] = edge
            m[f"noise_ratio_{key}"] = edge / ref if ref > 0 else float("nan")

        for check, sev, value, thr, detail in spectrum_flags(wl, x, m):
            _flag(flags, name, check, sev, value, thr, detail)

        for i in splice_idx:
            step, z = splice_step_z(x, i)
            key = f"{wl[i]:.0f}"
            m[f"splice_step_{key}nm"] = step
            m[f"splice_z_{key}nm"] = z
            m[f"splice_rel_{key}nm"] = abs(step) / m["mean"]
            if abs(z) > SPLICE_ROBUST_Z and abs(step) / m["mean"] > SPLICE_MIN_REL:
                _flag(flags, name, "splice_discontinuity", "WARNING", round(z, 1), SPLICE_ROBUST_Z,
                      f"step of {step:+.4f} reflectance between {wl[i]:.1f} and {wl[i+1]:.1f} nm "
                      "(detector join); not corrected")
        metrics.append(m)

    metrics_df = pd.DataFrame(metrics)

    # --- duplicates / similarity --------------------------------------------------
    finite_rows = np.all(np.isfinite(X), axis=1)
    rock_of = dict(zip(samples["sample"], samples["rock_id"]))
    meas_of = dict(zip(samples["sample"], samples["measurement_id"]))
    pair_rows = []
    for i, j in combinations(range(len(names)), 2):
        if not (finite_rows[i] and finite_rows[j]):
            continue
        a, b = names[i], names[j]
        exact = bool(np.array_equal(X[i], X[j]))
        if meas_of[a] is not None and meas_of[a] == meas_of[b]:
            relation = "replicate"
        elif rock_of[a] is not None and rock_of[a] == rock_of[b]:
            relation = "same_rock"
        else:
            relation = "different_rock"
        pair_rows.append({"sample_a": a, "sample_b": b, "relation": relation,
                          "spectral_angle_rad": spectral_angle(X[i], X[j]),
                          "brightness_ratio": float(X[i].mean() / X[j].mean()), "identical": exact})
    pairs = pd.DataFrame(pair_rows, columns=["sample_a", "sample_b", "relation", "spectral_angle_rad",
                                             "brightness_ratio", "identical"])

    for _, p in pairs[pairs["identical"]].iterrows():
        _flag(flags, p["sample_a"], "duplicate_spectrum", "WARNING", p["sample_b"], None,
              f"identical values to {p['sample_b']} (possible copy/paste duplicate)")

    rep = pairs[pairs["relation"] == "replicate"]["spectral_angle_rad"]
    replicate_median = float(rep.median()) if len(rep) else float("nan")
    q1, q3 = (rep.quantile(0.25), rep.quantile(0.75)) if len(rep) else (np.nan, np.nan)
    replicate_outlier_cut = float(q3 + 3 * (q3 - q1)) if len(rep) else float("nan")

    # Replicate consistency: each replicate's median angle to the others in its group.
    rep_rows = []
    for mid, grp in samples.dropna(subset=["measurement_id"]).groupby("measurement_id"):
        members = grp["sample"].tolist()
        if len(members) < 2:
            continue
        for s in members:
            mask = (pairs["relation"] == "replicate") & ((pairs["sample_a"] == s) | (pairs["sample_b"] == s))
            sub = pairs[mask]
            if sub.empty:  # replicates with non-finite values are not compared
                continue
            ratios = np.where(sub["sample_a"] == s, sub["brightness_ratio"], 1 / sub["brightness_ratio"])
            med_angle = float(sub["spectral_angle_rad"].median())
            rep_rows.append({"measurement_id": mid, "sample": s, "n_replicates": len(members),
                             "median_angle_to_replicates_rad": med_angle,
                             "median_brightness_ratio": float(np.median(ratios)),
                             "outlier": bool(med_angle > replicate_outlier_cut)})
            if med_angle > replicate_outlier_cut:
                _flag(flags, s, "replicate_inconsistent", "WARNING", round(med_angle, 4),
                      round(replicate_outlier_cut, 4),
                      f"spectral shape differs from its replicates in {mid} more than usual")
    replicates_df = pd.DataFrame(rep_rows)

    # Different rocks that look as alike as technical replicates: worth knowing,
    # not an error (could be the same lithology, or a labelling mix-up).
    # Kept as a table (input to the Phase 6 similarity analysis), not as flags.
    cross_similar = pairs[(pairs["relation"] == "different_rock")
                          & (pairs["spectral_angle_rad"] < replicate_median)].sort_values("spectral_angle_rad")
    counts = pd.concat([cross_similar["sample_a"], cross_similar["sample_b"]]).value_counts()
    metrics_df["n_cross_rock_replicate_like"] = metrics_df["sample"].map(counts).fillna(0).astype(int)

    flags_df = pd.DataFrame(flags, columns=["sample", "check", "severity", "value", "threshold", "detail"])
    log.info("Quality checks: %d flags (%s)", len(flags_df),
             flags_df["severity"].value_counts().to_dict() if len(flags_df) else {})

    return {
        "metrics": metrics_df,
        "flags": flags_df,
        "pairs": pairs,
        "replicates": replicates_df,
        "cross_rock_similar": cross_similar,
        "dataset": {
            "bands_below_engine_range": below_engine,
            "bands_above_engine_range": above_engine,
            "engine_range_nm": ENGINE_RANGE_NM,
            "replicate_angle_median_rad": replicate_median,
            "replicate_outlier_cut_rad": replicate_outlier_cut,
            "splice": {
                f"{wl[i]:.0f}nm": {
                    "n_statistically_detectable": int((metrics_df[f"splice_z_{wl[i]:.0f}nm"].abs() > SPLICE_ROBUST_Z).sum()),
                    "max_abs_step": float(metrics_df[f"splice_step_{wl[i]:.0f}nm"].abs().max()),
                    "max_relative_step": float(metrics_df[f"splice_rel_{wl[i]:.0f}nm"].max()),
                    "n_flagged_material": int((metrics_df[f"splice_rel_{wl[i]:.0f}nm"] > SPLICE_MIN_REL).sum()),
                } for i in splice_idx},
            "edge_noise_ratio_median": {k: float(metrics_df[f"noise_ratio_{k}"].median()) for k in EDGE_REGIONS},
            "different_rock_angle_median_rad": float(
                pairs[pairs["relation"] == "different_rock"]["spectral_angle_rad"].median()),
        },
    }
