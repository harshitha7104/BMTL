"""Matplotlib figures used by the report and the Streamlit app."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .analysis import Analysis  # noqa: E402
from .fusion import MIN_OBSERVED_DEPTH  # noqa: E402


def plot_spectrum_analysis(analysis: Analysis, title: str = "", original: tuple | None = None,
                           highlight_nm: list[float] | None = None):
    """Top: reflectance with hull continuum. Bottom: continuum-removed curve with features.
    `original` = (wl_nm, reflectance) draws the untrimmed input in grey.
    `highlight_nm` marks the wavelengths that support the prediction."""
    p = analysis.processed
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.5), sharex=True, gridspec_kw={"height_ratios": [1.2, 1]})
    if original is not None:
        ax1.plot(original[0], original[1], color="0.75", lw=1, label="original (incl. <400 nm)")
    ax1.plot(p.wavelength_nm, p.reflectance, color="#1f5fa8", lw=1.2, label="reflectance (400–2500 nm)")
    ax1.plot(p.wavelength_nm, p.continuum, color="#d1495b", lw=1, ls="--", label="convex-hull continuum")
    ax1.set_ylabel("Reflectance (0–1)")
    ax1.set_title(title or "Spectrum")
    ax1.legend(loc="best", fontsize=8)

    ax2.plot(p.wavelength_nm, p.continuum_removed, color="#2b2d42", lw=1.1, label="continuum removed")
    highlight = set(round(w) for w in (highlight_nm or []))
    for f in analysis.features:
        if f.depth < MIN_OBSERVED_DEPTH:
            continue
        key = round(f.center_nm) in highlight
        ax2.axvspan(f.start_nm, f.end_nm, color="#f4a259" if key else "0.85", alpha=0.35 if key else 0.3, lw=0)
        ax2.plot(f.center_nm, 1 - f.depth, "v", color="#d1495b" if key else "#555", ms=7 if key else 5)
        ax2.annotate(f"{f.center_nm:.0f}", (f.center_nm, 1 - f.depth), textcoords="offset points",
                     xytext=(0, -12), ha="center", fontsize=7)
    ax2.set_xlabel("Wavelength (nm)")
    ax2.set_ylabel("Continuum-removed")
    ax2.set_ylim(max(0, float(np.min(p.continuum_removed)) - 0.08), 1.02)
    ax2.legend(handles=[
        plt.Line2D([], [], color="#2b2d42", label="continuum removed"),
        plt.Line2D([], [], marker="v", color="#555", ls="", label="absorption feature (≥2 % deep)"),
        plt.Line2D([], [], marker="v", color="#d1495b", ls="", label="supports the prediction"),
    ], loc="lower left", fontsize=8)
    fig.tight_layout()
    return fig


def plot_pca_clusters(model: dict, highlight: np.ndarray | None = None):
    Z = model["reference_embeddings"]
    clusters = model["reference"]["cluster"].to_numpy()
    var = model["pca"].explained_variance_ratio_
    fig, ax = plt.subplots(figsize=(7, 5.5))
    cmap = plt.get_cmap("tab10")
    for c in np.unique(clusters):
        m = clusters == c
        ax.scatter(Z[m, 0], Z[m, 1], s=22, color=cmap(int(c) % 10), label=f"cluster {c} (n={m.sum()})", alpha=0.85)
    if highlight is not None:
        ax.scatter([highlight[0]], [highlight[1]], s=180, marker="*", color="black", label="this spectrum", zorder=5)
    ax.set_xlabel(f"PC1 ({100 * var[0]:.1f} % of variance)")
    ax.set_ylabel(f"PC2 ({100 * var[1]:.1f} % of variance)")
    ax.set_title("Continuum-removed spectra in PCA space (K-Means clusters)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return fig
