"""Train and evaluate BMTL models on the REAL ACE dataset (data/processed/real/).

Usage:  .venv/Scripts/python.exe -m src.realmodels.train

PROVENANCE: real company data only (9 ICP-referenced samples, 2 XRF instruments).
Every metric is leave-one-SAMPLE-out: all readings of the held-out sample (any dwell,
any day, any calibration view) are removed before fitting, so a sample never helps
predict itself. With 8 training samples per fold these are small-sample estimates.

Models
  1. Element correction (per element, per calibration basis): ICP_wt% = a + b * XRF_wt%
     (univariate linear, spec stage for >= 4 paired samples). Baseline = raw gun value.
  2. Uncertainty band: split-conformal style, from the leave-one-sample-out absolute
     residuals of the OTHER samples (jackknife+); nominal 90 %.
  3. Lithium (LiX): Li_wt% = k * 6.941 * sum(metal moles per 100 g), metal = Ni+Co+Mn (+Fe only
     when P supports LiFePO4). k = Li atoms per transition-metal atom, fitted on ICP Li.
     Inputs are XRF-derived corrected metals; XRF never "sees" Li. Always INFERRED.
  4. Material / chemistry detector: k-nearest-neighbour on composition ratios (instrument-
     agnostic) with abstention, trained on labelled readings from both XRF instruments.
Sample 6 (Co 57.8 %, outside the range of the others) is excluded from fitting by default
and reported as an out-of-domain check.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "processed" / "real"
MODELS = ROOT / "models" / "real"
REPORTS = ROOT / "reports" / "real"
BANNER = "REAL COMPANY DATA — 9 ICP-REFERENCED SAMPLES; SMALL-SAMPLE ESTIMATES, NOT A VALIDATED METHOD"

ELEMENTS = ["Ni", "Co", "Mn", "Fe", "Cu", "Al", "P"]
ATOMIC_WEIGHT = {"Ni": 58.693, "Co": 58.933, "Mn": 54.938, "Fe": 55.845, "P": 30.974, "Li": 6.941}
OOD_SAMPLES = ["6"]
COVERAGE = 0.90


def file_sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class ModelIntegrityError(RuntimeError):
    """The model file does not match the SHA-256 recorded in its model card (tampered or half-copied)."""


def verified_model_path(models_dir: Path) -> Path:
    """joblib files are pickles: loading one runs code. Only load a file whose hash matches the model card."""
    path = models_dir / "bmtl_real_models.joblib"
    card = json.loads((models_dir / "model_card.json").read_text(encoding="utf-8"))
    expected = card.get("model_sha256")
    if not expected:
        raise ModelIntegrityError(f"{models_dir / 'model_card.json'} has no model_sha256; retrain with python -m src.realmodels.train")
    if file_sha256(path) != expected:
        raise ModelIntegrityError(f"{path} does not match the SHA-256 in its model card; refusing to load it")
    return path


# ---------------------------------------------------------------- 1-2. element correction + bands
def fit_line(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    if len(np.unique(x)) < 2:
        return float(np.mean(y - x)), 1.0
    b, a = np.polyfit(x, y, 1)
    return float(a), float(b)


def element_rows(pairs: pd.DataFrame, element: str, basis: str) -> pd.DataFrame:
    d = pairs[(pairs.calibration_basis == basis) & pairs[f"icp_{element}"].notna()].copy()
    d["x"] = d[f"xrf_{element}"]
    lod = d[f"xrf_{element}_lod"].astype(bool) & d.x.isna()
    d.loc[lod, "x"] = 0.0          # the gun reported "not detected": it is the gun's own result (0) for the raw baseline
    d["censored"] = lod
    d["y"] = d[f"icp_{element}"]
    return d[d.x.notna()]


def loso_element(d: pd.DataFrame, samples: list[str]) -> pd.DataFrame:
    out = []
    for s in samples:
        train, test = d[(d["sample"] != s) & ~d["sample"].isin(OOD_SAMPLES)], d[d["sample"] == s]
        if test.empty or train["sample"].nunique() < 4:
            continue
        a, b = fit_line(train.x.to_numpy(), train.y.to_numpy())
        # jackknife+ style band: residuals of each training sample under a model that never saw it
        inner = []
        for s2 in train["sample"].unique():
            tr2, te2 = train[train["sample"] != s2], train[train["sample"] == s2]
            a2, b2 = fit_line(tr2.x.to_numpy(), tr2.y.to_numpy())
            inner.extend(np.abs(te2.y - (a2 + b2 * te2.x)).tolist())
        q = float(np.quantile(inner, min(1.0, COVERAGE * (1 + 1 / len(inner))))) if inner else np.nan
        pred = a + b * test.x
        out.append(test.assign(pred=pred, raw=test.x, band=q, lo=pred - q, hi=pred + q, fold_a=a, fold_b=b))
    return pd.concat(out) if out else pd.DataFrame()


def fit_weighted(real: pd.DataFrame, aug: pd.DataFrame) -> tuple[float, float]:
    """Line fit on real + augmented rows; augmented rows are down-weighted so they carry the same total weight as the real ones."""
    if aug.empty:
        return fit_line(real.x.to_numpy(), real.y.to_numpy())
    x = np.concatenate([real.x.to_numpy(), aug.x.to_numpy()])
    y = np.concatenate([real.y.to_numpy(), aug.y.to_numpy()])
    w = np.concatenate([np.ones(len(real)), np.full(len(aug), len(real) / len(aug))])
    b, a = np.polyfit(x, y, 1, w=np.sqrt(w))
    return float(a), float(b)


def loso_element_augmented(d: pd.DataFrame, aug_d: pd.DataFrame, samples: list[str]) -> pd.DataFrame:
    """Leave-one-sample-out where the fold's augmented rows never descend from the held-out sample."""
    from src.realmodels.augment import drop_parents

    out = []
    for s in samples:
        train, test = d[(d["sample"] != s) & ~d["sample"].isin(OOD_SAMPLES)], d[d["sample"] == s]
        if test.empty or train["sample"].nunique() < 4:
            continue
        a, b = fit_weighted(train, drop_parents(aug_d, s))
        out.append(test.assign(pred=a + b * test.x, raw=test.x))
    return pd.concat(out) if out else pd.DataFrame()


def train_element_models(pairs: pd.DataFrame, aug: pd.DataFrame | None = None) -> tuple[dict, pd.DataFrame]:
    models, evals = {}, []
    samples = sorted(pairs["sample"].unique())
    for basis in ["factory", "type_standardised"]:
        for e in ELEMENTS:
            d = element_rows(pairs, e, basis)
            if d["sample"].nunique() < 5:
                continue
            ev = loso_element(d, samples)
            aug_d = element_rows(aug, e, basis) if aug is not None and len(aug) else pd.DataFrame()
            ev_aug = loso_element_augmented(d, aug_d, samples) if len(aug_d) else pd.DataFrame()
            fit = d[~d["sample"].isin(OOD_SAMPLES)]
            a, b = fit_line(fit.x.to_numpy(), fit.y.to_numpy())
            resid = []
            for s in fit["sample"].unique():
                tr, te = fit[fit["sample"] != s], fit[fit["sample"] == s]
                a2, b2 = fit_line(tr.x.to_numpy(), tr.y.to_numpy())
                resid.extend(np.abs(te.y - (a2 + b2 * te.x)).tolist())
            band = float(np.quantile(resid, min(1.0, COVERAGE * (1 + 1 / len(resid)))))
            ind = ev[~ev["sample"].isin(OOD_SAMPLES)]
            mae_raw, mae_lin = float((ind.raw - ind.y).abs().mean()), float((ind.pred - ind.y).abs().mean())
            mae_aug = float((ev_aug[~ev_aug["sample"].isin(OOD_SAMPLES)].pred - ev_aug[~ev_aug["sample"].isin(OOD_SAMPLES)].y).abs().mean()) \
                if len(ev_aug) else np.inf
            # stage selection, all out-of-sample: a correction must beat the raw gun by >= 10 %; the augmented
            # fit is used only if it also beats the real-only fit.
            best_corr = min(mae_lin, mae_aug)
            if best_corr > 0.9 * mae_raw:
                stage = "passthrough"
            else:
                # augmentation must earn its place: >= 5 % better than the real-only fit out-of-sample
                stage = "linear_augmented" if mae_aug <= 0.95 * mae_lin else "linear"
            raw_band = float(np.quantile((ind.raw - ind.y).abs(), COVERAGE))
            if stage == "linear_augmented":
                a, b = fit_weighted(fit, aug_d)
                ind_aug = ev_aug[~ev_aug["sample"].isin(OOD_SAMPLES)]
                band = float(np.quantile((ind_aug.pred - ind_aug.y).abs(), COVERAGE))
                ev = ev.assign(pred=ev_aug.set_index(ev_aug.index).pred.reindex(ev.index).fillna(ev.pred))
            models[(basis, e)] = {"stage": stage, "a": a if stage != "passthrough" else 0.0, "b": b if stage != "passthrough" else 1.0,
                                  "band_90": band if stage != "passthrough" else raw_band, "loso_mae_raw": mae_raw, "loso_mae_linear": mae_lin,
                                  "loso_mae_linear_augmented": None if mae_aug == np.inf else mae_aug,
                                  "n_samples": int(fit["sample"].nunique()), "n_readings": int(len(fit)),
                                  "n_augmented_rows": int(len(aug_d)) if stage == "linear_augmented" else 0,
                                  "fit_samples": sorted(fit["sample"].unique().tolist())}
            # Nested search (src/realmodels/model_search.py): switch to a proportional fit only when the inner
            # selection picked it in >= 6 of 8 held-out folds (stable) AND its nested error beats the current choice by >= 5 %.
            from collections import Counter
            from src.realmodels.model_search import _rows as ms_rows, fit_element, loso_mae, nested_element
            current_mae = mae_raw if stage == "passthrough" else (mae_aug if stage == "linear_augmented" else mae_lin)
            d_ms = ms_rows(pairs, e, basis)
            nested = nested_element(d_ms)
            picks = Counter(nested["chosen_per_fold"])
            if picks.get("proportional", 0) >= 6 and nested["nested_mae"] <= 0.95 * current_mae:
                tr_all = d_ms
                b_prop = float(np.sum(tr_all.x * tr_all.y) / np.sum(tr_all.x ** 2))
                resid = []
                for s_ in tr_all["sample"].unique():
                    tr_, te_ = tr_all[tr_all["sample"] != s_], tr_all[tr_all["sample"] == s_]
                    k_ = float(np.sum(tr_.x * tr_.y) / np.sum(tr_.x ** 2))
                    resid += list(np.abs(k_ * te_.x - te_.y))
                stage, a, b = "proportional", 0.0, b_prop
                models[(basis, e)].update(stage=stage, a=0.0, b=b_prop, band_90=float(np.quantile(resid, min(1.0, COVERAGE * (1 + 1 / len(resid))))),
                                          loso_mae_proportional=loso_mae(d_ms, "proportional"), nested_mae_selected=nested["nested_mae"],
                                          nested_picks=dict(picks))
                # held-out predictions for the report: each sample predicted by a factor fitted without it
                fold_k = {s_: float(np.sum(tr_all[tr_all["sample"] != s_].x * tr_all[tr_all["sample"] != s_].y) /
                                    np.sum(tr_all[tr_all["sample"] != s_].x ** 2)) for s_ in ev["sample"].unique()}
                ev = ev.assign(pred=[fold_k[s_] * r for s_, r in zip(ev["sample"], ev.raw)])
                # held-out bands for the report, from the PROPORTIONAL model (jackknife+ style, like the linear path):
                # for each held-out sample, residuals of every training sample under a factor fitted without it
                def _k(d_):
                    return float(np.sum(d_.x * d_.y) / np.sum(d_.x ** 2))
                fold_q = {}
                for s_ in ev["sample"].unique():
                    tr_ = tr_all[tr_all["sample"] != s_]
                    inner = []
                    for s2 in tr_["sample"].unique():
                        te2 = tr_[tr_["sample"] == s2]
                        inner += list(np.abs(_k(tr_[tr_["sample"] != s2]) * te2.x - te2.y))
                    fold_q[s_] = float(np.quantile(inner, min(1.0, COVERAGE * (1 + 1 / len(inner)))))
                band_s = ev["sample"].map(fold_q)
                ev = ev.assign(band=band_s, lo=ev.pred - band_s, hi=ev.pred + band_s)
            else:
                models[(basis, e)].update(nested_picks=dict(picks), nested_mae_search=nested["nested_mae"])
            if stage == "passthrough":
                # the served value is the raw gun reading: report its held-out band (quantile of the OTHER samples' raw errors)
                ind_raw = ev[~ev["sample"].isin(OOD_SAMPLES)]
                fq = {}
                for s_ in ev["sample"].unique():
                    others = ind_raw[ind_raw["sample"] != s_]
                    errs = (others.raw - others.y).abs().to_numpy()
                    fq[s_] = float(np.quantile(errs, min(1.0, COVERAGE * (1 + 1 / len(errs)))))
                band_s = ev["sample"].map(fq)
                ev = ev.assign(pred_linear=ev.pred, pred=ev.raw, band=band_s, lo=ev.raw - band_s, hi=ev.raw + band_s)
            evals.append(ev.assign(element=e, basis=basis, stage=stage, mae_linear_augmented=None if mae_aug == np.inf else mae_aug))
    return models, pd.concat(evals)


def summarise_elements(ev: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (basis, e), g in ev.groupby(["basis", "element"]):
        ind = g[~g["sample"].isin(OOD_SAMPLES)]
        per_sample = ind.groupby("sample").agg(y=("y", "first"), pred=("pred", "mean"), raw=("raw", "mean"), lo=("lo", "mean"), hi=("hi", "mean"))
        covered = ((ind.y >= ind.lo) & (ind.y <= ind.hi)).mean()
        rows.append({"basis": basis, "element": e, "n_samples": len(per_sample), "n_readings": len(ind),
                     "mae_raw_gun": float((ind.raw - ind.y).abs().mean()), "mae_corrected": float(((ind.pred_linear.fillna(ind.pred) if "pred_linear" in ind else ind.pred) - ind.y).abs().mean()),
                     "mae_per_sample_corrected": float((per_sample.pred - per_sample.y).abs().mean()),
                     "mae_linear_augmented": g.mae_linear_augmented.iloc[0] if "mae_linear_augmented" in g else None,
                     "selected_stage": g.stage.iloc[0],
                     "mae_selected": float(((ind.pred if g.stage.iloc[0] != "passthrough" else ind.raw) - ind.y).abs().mean()),
                     "max_abs_err_corrected": float((ind.pred - ind.y).abs().max()), "band_coverage": float(covered),
                     "mean_band_halfwidth": float(ind.band.mean()),
                     "ood_sample6_err": float((g[g["sample"].isin(OOD_SAMPLES)].pred - g[g["sample"].isin(OOD_SAMPLES)].y).abs().mean()) if g["sample"].isin(OOD_SAMPLES).any() else None})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 3. lithium (LiX)
def metal_moles(comp: pd.DataFrame) -> np.ndarray:
    """Transition-metal moles per 100 g. Fe counts only up to the P moles (LiFePO4 pairing)."""
    n = sum(comp[e].fillna(0).clip(lower=0) / ATOMIC_WEIGHT[e] for e in ["Ni", "Co", "Mn"])
    fe = comp["Fe"].fillna(0).clip(lower=0) / ATOMIC_WEIGHT["Fe"]
    p = comp["P"].fillna(0).clip(lower=0) / ATOMIC_WEIGHT["P"]
    return (n + np.minimum(fe, p)).to_numpy()


def corrected_metals(pairs: pd.DataFrame, models: dict, basis: str, exclude: str | None = None, element_fold_models: dict | None = None) -> pd.DataFrame:
    rows = pairs[pairs.calibration_basis == basis].copy()
    comp = pd.DataFrame(index=rows.index)
    for e in ["Ni", "Co", "Mn", "Fe", "P"]:
        m = (element_fold_models or models).get((basis, e))
        x = rows[f"xrf_{e}"].fillna(0.0)
        comp[e] = (m["a"] + m["b"] * x).clip(lower=0) if m else x
    return rows.assign(**{f"corr_{e}": comp[e] for e in comp.columns}), comp


LI_METALS = ["Ni", "Co", "Mn", "FeP"]
LI_RIDGE = 0.1


def li_moles(comp: pd.DataFrame) -> pd.DataFrame:
    m = pd.DataFrame({e: comp[e].fillna(0).clip(lower=0) / ATOMIC_WEIGHT[e] for e in ["Ni", "Co", "Mn", "Fe", "P"]})
    m["FeP"] = np.minimum(m.Fe, m.P)
    return m[LI_METALS]


def fit_li_per_metal(mol: pd.DataFrame, li: np.ndarray) -> np.ndarray:
    """Li atoms per Ni / Co / Mn / (Fe paired with P) atom, ridge-shrunk toward one common factor, non-negative."""
    X = mol.to_numpy() * ATOMIC_WEIGHT["Li"]
    common = float(np.sum(li * X.sum(1)) / np.sum(X.sum(1) ** 2))
    lam = LI_RIDGE * len(li) * float(np.mean(np.sum(X ** 2, 0)))
    k = np.linalg.solve(X.T @ X + lam * np.eye(X.shape[1]), X.T @ li + lam * np.full(X.shape[1], common))
    return np.clip(k, 0, None)


def train_lithium(pairs: pd.DataFrame, models: dict) -> tuple[dict, pd.DataFrame]:
    evals, fits = [], {}
    for basis in ["factory", "type_standardised"]:
        rows = pairs[(pairs.calibration_basis == basis) & pairs.icp_Li.notna()]
        samples = sorted(rows["sample"].unique())
        out = []
        for s in samples:
            train = rows[(rows["sample"] != s) & ~rows["sample"].isin(OOD_SAMPLES)]
            if train["sample"].nunique() < 4:
                continue
            # element models refit without sample s, so the Li fold is clean end-to-end
            fold_models = {}
            for e in ["Ni", "Co", "Mn", "Fe", "P"]:
                d = element_rows(train, e, basis)
                if d["sample"].nunique() >= 3:
                    fold_models[(basis, e)] = dict(zip(("a", "b"), fit_line(d.x.to_numpy(), d.y.to_numpy())))
            _, comp_tr = corrected_metals(train, models, basis, element_fold_models=fold_models)
            mol = metal_moles(comp_tr)
            k = float(np.sum(train.icp_Li / ATOMIC_WEIGHT["Li"] * mol) / np.sum(mol ** 2))   # least squares through origin
            test = rows[rows["sample"] == s]
            _, comp_te = corrected_metals(test, models, basis, element_fold_models=fold_models)
            pred = k * ATOMIC_WEIGHT["Li"] * metal_moles(comp_te)
            kv = fit_li_per_metal(li_moles(comp_tr), train.icp_Li.to_numpy(float))
            pred_pm = (li_moles(comp_te).to_numpy() * ATOMIC_WEIGHT["Li"]) @ kv
            out.append(test.assign(pred=pred, pred_per_metal=pred_pm, y=test.icp_Li, k=k))
        ev = pd.concat(out)
        fit_rows = rows[~rows["sample"].isin(OOD_SAMPLES)]
        _, comp = corrected_metals(fit_rows, models, basis)
        mol = metal_moles(comp)
        k = float(np.sum(fit_rows.icp_Li / ATOMIC_WEIGHT["Li"] * mol) / np.sum(mol ** 2))
        ind = ev[~ev["sample"].isin(OOD_SAMPLES)]
        mae_one, mae_pm = float((ind.pred - ind.y).abs().mean()), float((ind.pred_per_metal - ind.y).abs().mean())
        use_pm = mae_pm <= 0.95 * mae_one
        if use_pm:
            ev = ev.assign(pred=ev.pred_per_metal)
            ind = ev[~ev["sample"].isin(OOD_SAMPLES)]
        band = float(np.quantile((ind.pred - ind.y).abs(), COVERAGE))
        fits[basis] = {"k_li_per_metal_atom": k, "band_90": band, "fit_samples": sorted(fit_rows["sample"].unique().tolist()),
                       "method": "per_metal" if use_pm else "one_factor", "loso_mae_one_factor": mae_one, "loso_mae_per_metal": mae_pm}
        if use_pm:
            fits[basis]["k_per_metal"] = dict(zip(LI_METALS, fit_li_per_metal(li_moles(comp), fit_rows.icp_Li.to_numpy(float)).round(5).tolist()))
        evals.append(ev.assign(basis=basis))
    return fits, pd.concat(evals)


# ---------------------------------------------------------------- 4. material / chemistry detector
RATIO_ELEMENTS = ["Ni", "Co", "Mn", "Fe", "Cu"]


def chemistry_from_icp(row: pd.Series) -> str:
    """Reference label from ICP (documented rule, applied to lab values only)."""
    if row.P_wtpct > 5 and row.Fe_wtpct > 5:
        return "LFP"
    tm = row.Ni_wtpct + row.Co_wtpct + row.Mn_wtpct
    if row.Co_wtpct / tm > 0.75:
        return "LCO"
    return "NMC"


def ratio_features(frame: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    vals = pd.DataFrame({e: pd.to_numeric(frame[f"{prefix}{e}"], errors="coerce").fillna(0).clip(lower=0) for e in RATIO_ELEMENTS + ["P", "Pb"] if f"{prefix}{e}" in frame})
    for e in ["P", "Pb"]:
        if e not in vals:
            vals[e] = 0.0
    tm = vals[RATIO_ELEMENTS].sum(axis=1)
    feats = pd.DataFrame({f"frac_{e}": vals[e] / tm.where(tm > 0) for e in RATIO_ELEMENTS}, index=frame.index)
    feats["p_to_fe"] = (vals.P / vals.Fe.where(vals.Fe > 0.05)).clip(upper=2.0)   # capped: tiny Fe must not make it explode
    feats["pb_share"] = vals.Pb / (vals.Pb + tm).where((vals.Pb + tm) > 0)
    feats["tm_total"] = tm
    return feats.fillna(0.0)


def detector_table(pairs: pd.DataFrame, icp: pd.DataFrame, xsort: pd.DataFrame) -> pd.DataFrame:
    chem = icp.apply(chemistry_from_icp, axis=1)
    b = pairs[pairs.calibration_basis == "type_standardised"].copy()
    b["label"] = b["sample"].map(chem)
    b["group"] = "bruker_" + b["sample"]
    b["label_source"] = "ICP rule"
    fb = ratio_features(b, prefix="xrf_").assign(label=b.label.values, group=b.group.values, instrument="S1 TITAN", record=b.record_id.values,
                                                  label_source=b.label_source.values)
    x = xsort.copy()
    lab = {"black_mass_nmc_declared": "NMC", "lead_acid_or_lead": "NOT_BLACK_MASS_LEAD", "black_mass_alloy_mode_artifact": "INSTRUMENT_MODE_ARTIFACT"}
    x["label"] = x.material_class.map(lab)
    x.loc[x.screen_state != "complete", "label"] = None
    x["group"] = "xsort_" + x.bag_label.astype(str)
    fx = ratio_features(x).assign(label=x.label.values, group=x.group.values, instrument="xSORT", record="xsort_" + x.reading_no.astype(str),
                                  label_source="bag label")
    fx["alloy_sum"] = pd.DataFrame({e: pd.to_numeric(x[e], errors="coerce") for e in ["Ni", "Co", "Mn", "Fe", "Cu", "Zr"]}).fillna(0).sum(axis=1).values
    fb["alloy_sum"] = 0.0
    return pd.concat([fb, fx], ignore_index=True)


FEATURES = [f"frac_{e}" for e in RATIO_ELEMENTS] + ["p_to_fe", "pb_share"]


RULE_ONLY_CLASSES = {"INSTRUMENT_MODE_ARTIFACT", "NOT_BLACK_MASS_LEAD", "NO_TRANSITION_METAL_SIGNAL"}


def knn_predict(train: pd.DataFrame, test: pd.DataFrame, k: int = 3) -> tuple[list, list]:
    # Classes defined by instrument behaviour or by explicit chemistry rules are never voted by similarity:
    # a Ni-rich NMC811 must not be called an "alloy-mode artefact" just because its ratios resemble one.
    train = train[~train.label.isin(RULE_ONLY_CLASSES)]
    mu, sd = train[FEATURES].mean(), train[FEATURES].std().replace(0, 1)
    A, B = ((train[FEATURES] - mu) / sd).to_numpy(), ((test[FEATURES] - mu) / sd).to_numpy()
    labels, conf = [], []
    for row in B:
        dist = np.linalg.norm(A - row, axis=1)
        idx = np.argsort(dist)[:k]
        votes = train.label.to_numpy()[idx]
        top, count = pd.Series(votes).value_counts().index[0], pd.Series(votes).value_counts().iloc[0]
        nearest = dist[idx[0]]
        labels.append(top)
        conf.append(float(count / k) * float(np.exp(-nearest / 3.0)))
    return labels, conf


def rule_flags(table: pd.DataFrame) -> pd.Series:
    """Deterministic pre-checks applied before the kNN (documented, not learned)."""
    flags = pd.Series("", index=table.index)
    # later lines take precedence: the most specific explanation wins
    flags[table.tm_total < 1.0] = "NO_TRANSITION_METAL_SIGNAL"
    flags[(table.frac_Fe > 0.5) & (table.p_to_fe > 0.3)] = "LFP"          # LiFePO4 stoichiometry: Fe dominant with P (P/Fe ~0.55 by mass)
    flags[table.pb_share > 0.5] = "NOT_BLACK_MASS_LEAD"
    flags[(table.alloy_sum > 95) & (table.instrument == "xSORT")] = "INSTRUMENT_MODE_ARTIFACT"
    return flags


def detector_extra_rows(table: pd.DataFrame, use_augmented: bool, use_synthetic: bool, seed: int = 20261116) -> pd.DataFrame:
    """Extra TRAINING-ONLY rows for the detector. Each carries `parent_group` so a held-out group's
    augmented copies are removed from its fold; synthetic rows have no real parent."""
    rows = []
    rng = np.random.default_rng(seed)
    labelled = table[table.label.notna()]
    if use_augmented:
        for _, r in labelled.iterrows():
            for k in range(20):
                row = r.copy()
                for f in [c for c in FEATURES if c.startswith("frac_")]:
                    row[f] = max(0.0, r[f] * (1 + rng.normal(0, 0.03)))
                total = sum(row[c] for c in FEATURES if c.startswith("frac_")) or 1.0
                for f in [c for c in FEATURES if c.startswith("frac_")]:
                    row[f] = row[f] / total
                row["parent_group"], row["group"] = r.group, f"aug_{r.group}"
                rows.append(row)
    if use_synthetic:
        syn_dir = ROOT / "archive" / "synthetic_era" / "data" / "synthetic_v2"
        if (syn_dir / "02_xrf_data.csv").exists():
            x = pd.read_csv(syn_dir / "02_xrf_data.csv")
            lab = pd.read_csv(syn_dir / "04_chemistry_labels.csv")[["SampleID", "Chemistry", "DomainStatus"]]
            x = x.merge(lab, on="SampleID")
            x = x[(x.DomainStatus == "in_domain") & x.Chemistry.isin(["NMC", "LFP"])]   # MIXED has no real counterpart
            feats = ratio_features(x.rename(columns={f"{e}_wtpct": e for e in ["Ni", "Co", "Mn", "Fe", "Cu", "P"]}))
            feats = feats.assign(label=x.Chemistry.values, group="synthetic_v2", parent_group="synthetic_v2", instrument="synthetic",
                                 record="syn_" + x.SampleID.values, label_source="SYNTHETIC v2 (not real)", alloy_sum=0.0)
            rows += [r for _, r in feats.iterrows()]
    return pd.DataFrame(rows)


def evaluate_detector(table: pd.DataFrame, abstain_below: float = 0.4, extra: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    labelled = table[table.label.notna()].copy()
    preds = []
    for g in labelled.group.unique():
        train, test = labelled[labelled.group != g], labelled[labelled.group == g]
        if extra is not None and len(extra):
            train = pd.concat([train, extra[extra.parent_group != g]], ignore_index=True)
        lab, conf = knn_predict(train, test)
        rules = rule_flags(test)
        final = [r if r else (l if c >= abstain_below else "UNKNOWN") for r, l, c in zip(rules, lab, conf)]
        preds.append(test.assign(pred=final, knn=lab, confidence=conf, rule=rules.values))
    ev = pd.concat(preds)
    decided = ev[ev.pred != "UNKNOWN"]
    summary = {"n_labelled_readings": int(len(ev)), "n_groups": int(ev.group.nunique()), "classes": ev.label.value_counts().to_dict(),
               "accuracy_on_decided": float((decided.pred == decided.label).mean()) if len(decided) else None,
               "abstention_rate": float((ev.pred == "UNKNOWN").mean()),
               "per_class_recall": {c: float((g.pred == c).mean()) for c, g in ev.groupby("label")},
               "evaluation": "leave-one-group-out (all readings of one physical sample / bag held out together)"}
    return ev, summary


def label_unlabelled(table: pd.DataFrame, abstain_below: float = 0.4) -> pd.DataFrame:
    labelled, unl = table[table.label.notna()], table[table.label.isna()].copy()
    if unl.empty:
        return unl
    lab, conf = knn_predict(labelled, unl)
    rules = rule_flags(unl)
    unl["inferred_label"] = [r if r else (l if c >= abstain_below else "UNKNOWN") for r, l, c in zip(rules, lab, conf)]
    unl["confidence"] = conf
    unl["label_state"] = "INFERRED"
    return unl


# ---------------------------------------------------------------- orchestration
def run(data: Path = DATA, models_dir: Path = MODELS, reports_dir: Path = REPORTS, aug_dir: Path | None = None) -> dict:
    models_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    pairs = pd.read_csv(data / "xrf_icp_pairs.csv", dtype={"sample": str})
    icp = pd.read_csv(data / "icp_reference.csv", dtype={"sample": str}).set_index("sample")
    xsort = pd.read_csv(data / "xsort_readings.csv", dtype={"bag_label": str})

    from src.realmodels.augment import augment
    aug = augment(pairs)
    aug_dir = aug_dir or ROOT / "data" / "processed" / "augmented"   # candidate runs (learning.py) write elsewhere
    aug_dir.mkdir(parents=True, exist_ok=True)
    aug.to_csv(aug_dir / "xrf_icp_pairs_augmented.csv", index=False)
    element_models, element_eval = train_element_models(pairs, aug)
    element_summary = summarise_elements(element_eval)
    li_models, li_eval = train_lithium(pairs, element_models)
    li_summary = (li_eval[~li_eval["sample"].isin(OOD_SAMPLES)].assign(err=lambda d: (d.pred - d.y).abs())
                  .groupby("basis").agg(mae=("err", "mean"), max_err=("err", "max"), n=("err", "size")).reset_index())
    table = detector_table(pairs, icp, xsort)
    variants = {}
    for name, use_aug, use_syn in [("real_only", False, False), ("real+augmented", True, False), ("real+synthetic_v2", False, True),
                                   ("real+augmented+synthetic_v2", True, True)]:
        extra = detector_extra_rows(table, use_aug, use_syn)
        ev_v, sum_v = evaluate_detector(table, extra=extra)
        variants[name] = {"accuracy_on_decided": sum_v["accuracy_on_decided"], "abstention_rate": sum_v["abstention_rate"],
                          "extra_training_rows": int(len(extra)), "per_class_recall": sum_v["per_class_recall"]}
    # keep the simplest variant unless another is strictly better on real held-out groups (accuracy, then abstention)
    best = min(variants, key=lambda n: (-(variants[n]["accuracy_on_decided"] or 0), variants[n]["abstention_rate"], list(variants).index(n)))
    det_extra = detector_extra_rows(table, "augmented" in best, "synthetic" in best)
    det_eval, det_summary = evaluate_detector(table, extra=det_extra)
    det_summary["variant_comparison"] = variants
    det_summary["selected_variant"] = best
    inferred = label_unlabelled(table)

    company = pd.read_csv(data / "company_model_outputs.csv", dtype={"sample": str})
    comp_gap = (company[(company.column.isin(["Diff 90 s (points)", "Diff 120 s (points)"])) & (company.variant.isna() | (company.variant == "LiX-0.2")) & ~company["sample"].isin(OOD_SAMPLES)]
                .assign(abs_gap=lambda d: d.value.abs()).groupby("element").abs_gap.mean().rename("company_bmtl_v021_mean_abs_gap_excl_sample6"))

    stamp = {"trained_on": date.today().isoformat(), "banner": BANNER, "data": str(data.relative_to(ROOT)) if data.is_relative_to(ROOT) else str(data), "evaluation": "leave-one-sample-out"}
    joblib.dump({"element": element_models, "lithium": li_models, "detector_table": pd.concat([table[table.label.notna()], det_extra], ignore_index=True) if len(det_extra) else table[table.label.notna()], "features": FEATURES, **stamp},
                models_dir / "bmtl_real_models.joblib")
    model_sha256 = file_sha256(models_dir / "bmtl_real_models.joblib")   # security audit L-12: loaders verify this
    (models_dir / "model_card.json").write_text(json.dumps({**stamp, "model_sha256": model_sha256,
                                                            "element_models": {f"{b}:{e}": v for (b, e), v in element_models.items()},
                                                            "lithium": li_models, "detector": det_summary}, indent=2) + "\n", encoding="utf-8")
    element_eval.to_csv(reports_dir / "element_loso_predictions.csv", index=False)
    element_summary.to_csv(reports_dir / "element_loso_summary.csv", index=False)
    li_eval.to_csv(reports_dir / "lithium_loso_predictions.csv", index=False)
    det_eval.to_csv(reports_dir / "detector_logo_predictions.csv", index=False)
    inferred.to_csv(reports_dir / "inferred_labels_unlabelled_readings.csv", index=False)
    comp_gap.to_csv(reports_dir / "company_model_gap.csv")
    result = {"element_summary": element_summary.round(3).to_dict(orient="records"), "lithium": li_summary.round(3).to_dict(orient="records"),
              "lithium_models": li_models, "detector": det_summary, "company_v021_gap": comp_gap.round(3).to_dict(),
              "inferred_labels": inferred[["record", "inferred_label", "confidence"]].round(2).to_dict(orient="records")}
    (reports_dir / "training_summary.json").write_text(json.dumps({**stamp, **result}, indent=2, default=str) + "\n", encoding="utf-8")
    write_report(reports_dir, stamp, element_summary, li_summary, li_models, det_summary, inferred, comp_gap)
    return result


def write_report(reports_dir: Path, stamp: dict, es: pd.DataFrame, li: pd.DataFrame, li_models: dict, det: dict, inferred: pd.DataFrame,
                 company: pd.Series) -> None:
    """Markdown report generated from the computed tables (no hand-typed numbers)."""
    cols = ["basis", "element", "n_samples", "n_readings", "mae_raw_gun", "mae_corrected", "mae_linear_augmented", "selected_stage", "mae_selected", "band_coverage",
            "mean_band_halfwidth", "ood_sample6_err"]
    lines = ["# BMTL real-data model report", "", f"> **{stamp['banner']}**", "",
             f"Trained {stamp['trained_on']} on `{stamp['data']}`. Every number is {stamp['evaluation']} (all readings of a sample held out together).", "",
             "## Element correction (wt%, mean absolute error vs in-house ICP)", "", es[cols].round(3).to_markdown(index=False), "",
             "`selected_stage` keeps the linear correction only where it beats the raw gun by >= 10 % out-of-sample; otherwise the gun value passes through.",
             "Sample 6 (Co 57.8 %) is never fitted; `ood_sample6_err` shows how far off it lands.", "",
             "## Lithium (LiX, INFERRED from corrected XRF metals; XRF never measures Li)", "", li.round(3).to_markdown(index=False), "",
             "Li atoms per transition-metal atom (k): " + ", ".join(f"{b} = {v['k_li_per_metal_atom']:.3f}" for b, v in li_models.items()), "",
             "Company BMTL v0.2.1 mean |gap| on the same 8 samples (its own leave-one-lot-out run; LiX-0.2 for Li; 90 s and 120 s pooled; its Li model also used 44 in-house ICP results that are not in this dataset):", "",
             company.round(3).to_frame().to_markdown(), "",
             "## Material / chemistry detector", "",
             f"Evaluation: {det['evaluation']}. Labelled readings: {det['n_labelled_readings']} from {det['n_groups']} physical samples/bags.", "",
             f"- Accuracy on decided readings: {det['accuracy_on_decided']:.3f}; abstention rate: {det['abstention_rate']:.3f}",
             "- Per-class recall: " + ", ".join(f"{k} {v:.2f}" for k, v in det["per_class_recall"].items()),
             "- LFP and lead are decided by explicit chemistry rules (only one LFP sample exists); NMC/LCO by kNN on composition ratios.", "",
             "### Does extra data help? (scored only on real held-out bags)", "",
             pd.DataFrame(det.get("variant_comparison", {})).T[["accuracy_on_decided", "abstention_rate", "extra_training_rows"]].round(3).to_markdown()
             if det.get("variant_comparison") else "", "",
             f"Selected: **{det.get('selected_variant')}**. Element correction: augmented fits are listed in `mae_linear_augmented` above and are "
             "used only where they beat the real-only fit by >= 5 % out-of-sample. Augmented and synthetic rows are training aids, never evidence.", "",
             "## Labels inferred for unlabelled readings (INFERRED, confirm before use)", "",
             inferred[["record", "inferred_label", "confidence"]].round(2).to_markdown(index=False) if len(inferred) else "none", ""]
    (reports_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    out = run()
    pd.set_option("display.width", 220)
    print(BANNER)
    print(pd.DataFrame(out["element_summary"]).to_string(index=False))
    print(pd.DataFrame(out["lithium"]).to_string(index=False), out["lithium_models"])
    print(json.dumps(out["detector"], indent=2))
    print(pd.DataFrame(out["inferred_labels"]).to_string(index=False))
