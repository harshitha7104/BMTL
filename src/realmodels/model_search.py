"""Honest model search for element correction and lithium (nested leave-one-sample-out).

PROVENANCE: real ACE data only (8 in-domain ICP-referenced samples; sample 6 excluded as out-of-domain).
Why nested: picking the best of several model types on the same leave-one-sample-out errors makes the
winner look better than it is. Here, for every held-out sample, the model type is chosen by an INNER
leave-one-sample-out on the remaining samples only; the outer error is the honest estimate.

Element candidates (per element, per calibration basis):
  passthrough   y = x
  linear        y = a + b x
  proportional  y = b x
  loglinear     log y = a + b log x
  matrix        y = a + b x + c T,  T = total Ni+Co+Mn+Fe+Cu signal (XRF matrix / absorption effect), ridge-shrunk
Lithium candidates (inputs: ICP-equivalent metals from the element models, never XRF Li):
  lix           Li = k * 6.941 * (Ni+Co+Mn mol + min(Fe,P) mol)                    (current)
  lix_affine    Li = k * 6.941 * mol + b
  lix_per_metal Li = 6.941 * sum_e k_e mol_e  (non-negative per-metal factors, ridge-shrunk)
  lix_by_family Li = k_family * 6.941 * mol, family = phosphate (LFP) vs layered oxide
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "processed" / "real"
REPORTS = ROOT / "reports" / "real"
OOD = {"6"}
EL = ["Ni", "Co", "Mn", "Fe", "Cu", "Al", "P"]
AW = {"Ni": 58.693, "Co": 58.933, "Mn": 54.938, "Fe": 55.845, "P": 30.974, "Li": 6.941}
RIDGE = 0.1


# ---------------------------------------------------------------- element candidates
def _rows(pairs: pd.DataFrame, e: str, basis: str) -> pd.DataFrame:
    d = pairs[(pairs.calibration_basis == basis) & pairs[f"icp_{e}"].notna() & ~pairs["sample"].isin(OOD)].copy()
    d["x"] = d[f"xrf_{e}"].where(~(d[f"xrf_{e}_lod"].astype(bool) & d[f"xrf_{e}"].isna()), 0.0)
    d["T"] = sum(d[f"xrf_{m}"].fillna(0) for m in ["Ni", "Co", "Mn", "Fe", "Cu"])
    d["y"] = d[f"icp_{e}"]
    return d[d.x.notna()]


def fit_element(kind: str, tr: pd.DataFrame):
    x, y, t = tr.x.to_numpy(float), tr.y.to_numpy(float), tr["T"].to_numpy(float)
    if kind == "passthrough":
        return lambda d: d.x.to_numpy(float)
    if kind == "linear":
        b, a = np.polyfit(x, y, 1) if len(np.unique(x)) > 1 else (1.0, float(np.mean(y - x)))
        return lambda d: a + b * d.x.to_numpy(float)
    if kind == "proportional":
        b = float(np.sum(x * y) / max(np.sum(x * x), 1e-12))
        return lambda d: b * d.x.to_numpy(float)
    if kind == "loglinear":
        ok = (x > 0) & (y > 0)
        if ok.sum() < 3:
            return None
        b, a = np.polyfit(np.log(x[ok]), np.log(y[ok]), 1)
        return lambda d: np.exp(a + b * np.log(np.clip(d.x.to_numpy(float), 1e-6, None)))
    if kind == "matrix":
        X = np.column_stack([np.ones_like(x), x, t])
        mu, sd = X[:, 1:].mean(0), X[:, 1:].std(0) + 1e-9
        Xs = np.column_stack([np.ones_like(x), (X[:, 1:] - mu) / sd])
        pen = RIDGE * len(x) * np.diag([0, 1, 1])
        w = np.linalg.solve(Xs.T @ Xs + pen, Xs.T @ y)

        def pred(d, w=w, mu=mu, sd=sd):
            Z = (np.column_stack([d.x.to_numpy(float), d["T"].to_numpy(float)]) - mu) / sd
            return w[0] + Z @ w[1:]
        return pred
    raise ValueError(kind)


ELEMENT_KINDS = ["passthrough", "linear", "proportional", "loglinear", "matrix"]


def loso_mae(d: pd.DataFrame, kind: str) -> float:
    errs = []
    for s in d["sample"].unique():
        tr, te = d[d["sample"] != s], d[d["sample"] == s]
        f = fit_element(kind, tr)
        if f is None:
            return np.inf
        errs += list(np.abs(np.clip(f(te), 0, None) - te.y.to_numpy(float)))
    return float(np.mean(errs))


def nested_element(d: pd.DataFrame) -> dict:
    outer, chosen = [], []
    for s in sorted(d["sample"].unique()):
        tr, te = d[d["sample"] != s], d[d["sample"] == s]
        scores = {k: loso_mae(tr, k) for k in ELEMENT_KINDS}
        best = min(scores, key=scores.get)
        chosen.append(best)
        f = fit_element(best, tr)
        outer += list(np.abs(np.clip(f(te), 0, None) - te.y.to_numpy(float)))
    return {"nested_mae": float(np.mean(outer)), "chosen_per_fold": chosen,
            "flat_loso_mae": {k: round(loso_mae(d, k), 4) for k in ELEMENT_KINDS}}


# ---------------------------------------------------------------- lithium candidates
def _moles(c: pd.DataFrame) -> pd.DataFrame:
    m = pd.DataFrame({e: c[e].clip(lower=0) / AW[e] for e in ["Ni", "Co", "Mn", "Fe", "P"]})
    m["FeP"] = np.minimum(m.Fe, m.P)
    m["layered"] = m.Ni + m.Co + m.Mn
    m["phosphate"] = (m.Fe > m.layered) & (m.P > 0.5 * m.Fe)
    return m


def fit_li(kind: str, m: pd.DataFrame, li: np.ndarray):
    tot = (m.layered + m.FeP).to_numpy()
    if kind == "lix":
        k = float(np.sum(li / AW["Li"] * tot) / np.sum(tot ** 2))
        return lambda mm: k * AW["Li"] * (mm.layered + mm.FeP).to_numpy()
    if kind == "lix_affine":
        b, a = np.polyfit(tot, li, 1)
        return lambda mm: a + b * (mm.layered + mm.FeP).to_numpy()
    if kind == "lix_per_metal":
        X = m[["Ni", "Co", "Mn", "FeP"]].to_numpy() * AW["Li"]
        lam = RIDGE * len(li) * np.mean(np.sum(X ** 2, 0))
        target_k = np.full(4, float(np.sum(li * X.sum(1)) / np.sum(X.sum(1) ** 2)))   # shrink toward one common k
        k = np.linalg.solve(X.T @ X + lam * np.eye(4), X.T @ li + lam * target_k)
        k = np.clip(k, 0, None)
        return lambda mm: (mm[["Ni", "Co", "Mn", "FeP"]].to_numpy() * AW["Li"]) @ k
    if kind == "lix_by_family":
        ks = {}
        common = float(np.sum(li / AW["Li"] * tot) / np.sum(tot ** 2))
        for fam in (True, False):
            sel = m.phosphate.to_numpy() == fam
            ks[fam] = float(np.sum(li[sel] / AW["Li"] * tot[sel]) / np.sum(tot[sel] ** 2)) if sel.sum() >= 2 else common
        return lambda mm: np.array([ks[bool(p)] for p in mm.phosphate]) * AW["Li"] * (mm.layered + mm.FeP).to_numpy()
    raise ValueError(kind)


LI_KINDS = ["lix", "lix_affine", "lix_per_metal", "lix_by_family"]


def li_frame(pairs: pd.DataFrame, basis: str, element_fit) -> pd.DataFrame:
    """ICP-equivalent metals predicted by element models fitted WITHOUT the rows' own sample (passed in)."""
    d = pairs[(pairs.calibration_basis == basis) & pairs.icp_Li.notna() & ~pairs["sample"].isin(OOD)].copy()
    return d


def li_errors(pairs, basis, kind, samples_train, samples_test, elem_kind="linear"):
    def corrected(rows, train_rows):
        out = {}
        for e in ["Ni", "Co", "Mn", "Fe", "P"]:
            tr = _rows(train_rows, e, basis)
            te = rows.copy()
            te["x"] = te[f"xrf_{e}"].fillna(0.0)
            te["T"] = sum(te[f"xrf_{m}"].fillna(0) for m in ["Ni", "Co", "Mn", "Fe", "Cu"])
            f = fit_element(elem_kind, tr) if len(tr["sample"].unique()) >= 3 else None
            out[e] = np.clip(f(te), 0, None) if f else te.x.to_numpy(float)
        return pd.DataFrame(out, index=rows.index)
    base = pairs[(pairs.calibration_basis == basis) & pairs.icp_Li.notna() & ~pairs["sample"].isin(OOD)]
    tr_rows, te_rows = base[base["sample"].isin(samples_train)], base[base["sample"].isin(samples_test)]
    m_tr, m_te = _moles(corrected(tr_rows, tr_rows)), _moles(corrected(te_rows, tr_rows))
    f = fit_li(kind, m_tr, tr_rows.icp_Li.to_numpy(float))
    return list(np.abs(f(m_te) - te_rows.icp_Li.to_numpy(float)))


def nested_li(pairs, basis) -> dict:
    samples = sorted(pairs[(pairs.calibration_basis == basis) & pairs.icp_Li.notna() & ~pairs["sample"].isin(OOD)]["sample"].unique())
    def flat(kind, pool):
        errs = []
        for s in pool:
            errs += li_errors(pairs, basis, kind, [x for x in pool if x != s], [s])
        return float(np.mean(errs))
    outer, chosen = [], []
    for s in samples:
        inner = [x for x in samples if x != s]
        scores = {k: flat(k, inner) for k in LI_KINDS}
        best = min(scores, key=scores.get)
        chosen.append(best)
        outer += li_errors(pairs, basis, best, inner, [s])
    return {"nested_mae": float(np.mean(outer)), "chosen_per_fold": chosen, "flat_loso_mae": {k: round(flat(k, samples), 4) for k in LI_KINDS}}


def run(out: Path = REPORTS) -> dict:
    pairs = pd.read_csv(DATA / "xrf_icp_pairs.csv", dtype={"sample": str})
    res = {"banner": "REAL COMPANY DATA - 8 in-domain samples; nested leave-one-sample-out", "elements": {}, "lithium": {}}
    for basis in ["factory", "type_standardised"]:
        for e in EL:
            d = _rows(pairs, e, basis)
            if d["sample"].nunique() >= 6:
                res["elements"][f"{basis}:{e}"] = nested_element(d)
        res["lithium"][basis] = nested_li(pairs, basis)
    out.mkdir(parents=True, exist_ok=True)
    (out / "model_search_nested.json").write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    return res


if __name__ == "__main__":
    r = run()
    print(r["banner"])
    for k, v in r["elements"].items():
        print(f"{k:24s} nested {v['nested_mae']:.3f}  flat {v['flat_loso_mae']}  picks {sorted(set(v['chosen_per_fold']))}")
    for k, v in r["lithium"].items():
        print(f"Li {k:20s} nested {v['nested_mae']:.3f}  flat {v['flat_loso_mae']}  picks {sorted(set(v['chosen_per_fold']))}")
