"""Unsupervised spectral model: PCA + K-Means on continuum-removed spectra,
plus the reference library used for nearest-spectrum search.

Replicate handling: PCA and K-Means are fitted on one mean vector per
measurement spot (rock + surface + spot number), so a spot measured 4 times
does not count 4 times. All 170 spectra are then projected and kept as the
reference library.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score

from .analysis import VECTOR_BIN_NM, Analysis, analyse_spectrum
from .data_loader import SpectralDataset
from .fusion import rule_candidates, rule_hypothesis
from .preprocessing import PreprocessConfig

log = logging.getLogger(__name__)

MODEL_VERSION = 2
RANDOM_STATE = 42
PCA_VARIANCE = 0.95
PCA_MAX_COMPONENTS = 15
K_RANGE = range(2, 11)
OOD_PERCENTILE = 5
RECON_PERCENTILE = 99
FEATURE_STORE_MIN_DEPTH = 0.02


class ModelError(RuntimeError):
    pass


def normalise_rows(z: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(z, axis=-1, keepdims=True)
    return z / np.where(norm == 0, 1.0, norm)


def analyse_dataset(ds: SpectralDataset, cfg: PreprocessConfig) -> list[Analysis]:
    out = []
    for i, name in enumerate(ds.sample_names):
        out.append(analyse_spectrum(ds.wavelength_nm, ds.reflectance[i], cfg))
    log.info("Analysed %d reference spectra", len(out))
    return out


def fit_model(ds: SpectralDataset, samples: pd.DataFrame, cfg: PreprocessConfig | None = None,
              analyses: list[Analysis] | None = None) -> tuple[dict, list[Analysis]]:
    cfg = cfg or PreprocessConfig()
    analyses = analyses or analyse_dataset(ds, cfg)
    V = np.vstack([a.vector for a in analyses])
    meta = samples.set_index("sample").loc[ds.sample_names].reset_index()
    unit = meta["measurement_id"].fillna(meta["sample"]).to_numpy()

    unit_ids = pd.unique(unit)
    M = np.vstack([V[unit == u].mean(axis=0) for u in unit_ids])
    log.info("Fitting on %d measurement-level vectors (from %d spectra)", len(M), len(V))

    pca = PCA(n_components=PCA_VARIANCE, svd_solver="full", random_state=RANDOM_STATE).fit(M)
    if pca.n_components_ > PCA_MAX_COMPONENTS:
        pca = PCA(n_components=PCA_MAX_COMPONENTS, random_state=RANDOM_STATE).fit(M)
    Zm = pca.transform(M)

    k_rows = []
    for k in K_RANGE:
        if k >= len(M):
            break
        km = KMeans(n_clusters=k, n_init=10, random_state=RANDOM_STATE).fit(Zm)
        k_rows.append({"k": k, "silhouette": float(silhouette_score(Zm, km.labels_)), "inertia": float(km.inertia_)})
    k_table = pd.DataFrame(k_rows)
    best_k = int(k_table.loc[k_table["silhouette"].idxmax(), "k"])
    kmeans = KMeans(n_clusters=best_k, n_init=10, random_state=RANDOM_STATE).fit(Zm)
    log.info("PCA: %d components (%.1f%% variance); K-Means k=%d (silhouette %.3f)", pca.n_components_,
             100 * pca.explained_variance_ratio_.sum(), best_k, k_table["silhouette"].max())

    Z = pca.transform(V)
    clusters = kmeans.predict(Z)
    ref = meta[["sample", "rock_id", "measurement_id", "surface"]].copy()
    ref["cluster"] = clusters
    hyps = [rule_hypothesis(rule_candidates(a)) for a in analyses]
    ref["rule_hypothesis"] = pd.Series([h for h, _ in hyps], dtype=object)
    ref["rule_R"] = [round(r, 3) for _, r in hyps]
    ref["low_albedo"] = [a.has_flag("low_albedo") for a in analyses]
    ref["n_features"] = [len(a.features) for a in analyses]
    ref["features"] = [[(f.center_nm, round(f.depth, 4)) for f in a.features if f.depth >= FEATURE_STORE_MIN_DEPTH]
                       for a in analyses]
    recon = reconstruction_error(pca, V)

    # Out-of-distribution threshold: how similar is each reference spectrum to
    # its most similar spectrum from a *different* rock?
    Zn = normalise_rows(Z)
    S = Zn @ Zn.T
    rocks = ref["rock_id"].fillna(ref["sample"]).to_numpy()
    S_other = np.where(rocks[:, None] == rocks[None, :], -np.inf, S)
    top1 = S_other.max(axis=1)
    ood = float(np.percentile(top1, OOD_PERCENTILE))

    model = {
        "version": MODEL_VERSION,
        "created": datetime.now().isoformat(timespec="seconds"),
        "sklearn_version": sklearn.__version__,
        "source_file": ds.source_path.name,
        "preprocess_config": cfg.to_dict(),
        "vector_bin_nm": VECTOR_BIN_NM,
        "pca": pca,
        "kmeans": kmeans,
        "k_table": k_table,
        "fit_level": "measurement (replicates averaged)",
        "n_fit_units": int(len(M)),
        "reference": ref,
        "reference_embeddings": Z,
        "reference_top1_other_rock_similarity": top1,
        "ood_similarity_threshold": ood,
        "reconstruction_error_threshold": float(np.percentile(recon, RECON_PERCENTILE)),
        "random_state": RANDOM_STATE,
    }
    return model, analyses


def reconstruction_error(pca: PCA, V: np.ndarray) -> np.ndarray:
    """RMSE between a vector and its PCA reconstruction: high = shape not representable by the model."""
    V = np.atleast_2d(V)
    return np.sqrt(((V - pca.inverse_transform(pca.transform(V))) ** 2).mean(axis=1))


def save_model(model: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    log.info("Model saved to %s", path)


def load_model(path: Path) -> dict:
    if not Path(path).is_file():
        raise ModelError(f"No fitted model at {path}. Run:  python run_pipeline.py")
    model = joblib.load(path)
    if model.get("version") != MODEL_VERSION:
        raise ModelError(f"Model file version {model.get('version')} does not match code version "
                         f"{MODEL_VERSION}. Re-run:  python run_pipeline.py")
    return model


def preprocess_config_from(model: dict) -> PreprocessConfig:
    d = dict(model["preprocess_config"])
    d["range_nm"] = tuple(d["range_nm"])
    return PreprocessConfig(**d)
