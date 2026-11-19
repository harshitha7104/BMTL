"""Label-free evaluation: cluster structure, replicate consistency, neighbour
consistency, feature stability, rule-engine behaviour and evidence summary.

No accuracy / precision / recall / F1 is computed: there is no ground truth.
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations

import numpy as np
import pandas as pd

from .analysis import Analysis
from .fusion import jaccard, members_of
from .model import normalise_rows

FEATURE_MATCH_NM = 10.0
STABILITY_MIN_DEPTH = 0.03


def _pair_same_cluster(ref: pd.DataFrame, key: str) -> tuple[float, int]:
    same, n = 0, 0
    for _, grp in ref.dropna(subset=[key]).groupby(key):
        for a, b in combinations(grp["cluster"].tolist(), 2):
            same += a == b
            n += 1
    return (same / n if n else float("nan")), n


def feature_stability(ref: pd.DataFrame, analyses: list[Analysis]) -> tuple[float, int]:
    """Share of features (>=3 % deep) in one replicate that reappear within 10 nm in the other."""
    by_name = dict(zip(ref["sample"], analyses))
    scores = []
    for _, grp in ref.dropna(subset=["measurement_id"]).groupby("measurement_id"):
        for a, b in combinations(grp["sample"].tolist(), 2):
            for x, y in ((a, b), (b, a)):
                fx = [f.center_nm for f in by_name[x].features if f.depth >= STABILITY_MIN_DEPTH]
                fy = np.array([f.center_nm for f in by_name[y].features if f.depth >= STABILITY_MIN_DEPTH])
                if fx:
                    scores.append(np.mean([fy.size > 0 and np.min(np.abs(fy - c)) <= FEATURE_MATCH_NM for c in fx]))
    return (float(np.mean(scores)) if scores else float("nan")), len(scores)


def evaluate(model: dict, analyses: list[Analysis], results: list[dict]) -> dict:
    ref = model["reference"]
    rocks = ref["rock_id"].fillna(ref["sample"]).to_numpy()
    Zn = normalise_rows(model["reference_embeddings"])
    S = Zn @ Zn.T
    np.fill_diagonal(S, -np.inf)
    S_other = np.where(rocks[:, None] == rocks[None, :], -np.inf, S)
    nn = S_other.argmax(axis=1)
    cl = ref["cluster"].to_numpy()
    labels = ref["rule_hypothesis"].to_numpy()
    both = np.array([bool(members_of(labels[i])) and bool(members_of(labels[j])) for i, j in enumerate(nn)])
    agree = np.array([jaccard(labels[i], labels[j]) >= 0.5 for i, j in enumerate(nn)])

    # Baseline: chance that two random different-rock spectra share a cluster.
    diff = rocks[:, None] != rocks[None, :]
    baseline = float((cl[:, None] == cl[None, :])[diff].mean())

    rep_rate, rep_n = _pair_same_cluster(ref, "measurement_id")
    rock_rate, rock_n = _pair_same_cluster(ref, "rock_id")
    stab, stab_n = feature_stability(ref, analyses)

    fired, excluded = Counter(), Counter()
    for r in results:
        for c in r["rule_evidence"]:
            fired[c["name"]] += 1
            if not c["plausible"]:
                excluded[c["name"]] += 1

    res = pd.DataFrame([{"type": r["prediction_type"], "prediction": r["prediction"], "confidence": r["confidence"],
                         "outcome": outcome(r), "dark": any("low_albedo" in w for w in r["warnings"])}
                        for r in results])
    # Do technical replicates (same spot) receive the same final prediction?
    pred_of = dict(zip([r["sample"] for r in results], [r["prediction"] for r in results]))
    rep_same, rep_pairs = 0, 0
    for _, grp in ref.dropna(subset=["measurement_id"]).groupby("measurement_id"):
        for a, b in combinations(grp["sample"].tolist(), 2):
            rep_pairs += 1
            rep_same += pred_of.get(a) == pred_of.get(b)
    clusters = []
    for c in sorted(ref["cluster"].unique()):
        m = ref[ref["cluster"] == c]
        clusters.append({"cluster": int(c), "n_spectra": int(len(m)), "n_rocks": int(m["rock_id"].nunique()),
                         "rule_hypotheses": m["rule_hypothesis"].value_counts().to_dict(),
                         "unlabelled": int(m["rule_hypothesis"].isna().sum()),
                         "surfaces": m["surface"].value_counts().to_dict()})
    return {
        "k_table": model["k_table"],
        "chosen_k": int(model["kmeans"].n_clusters),
        "pca_components": int(model["pca"].n_components_),
        "pca_variance": float(model["pca"].explained_variance_ratio_.sum()),
        "replicate_same_cluster": (rep_rate, rep_n),
        "same_rock_same_cluster": (rock_rate, rock_n),
        "different_rock_same_cluster_baseline": baseline,
        "nn_other_rock_same_cluster": float((cl == cl[nn]).mean()),
        "nn_other_rock_rule_agreement": (float(agree[both].mean()) if both.any() else float("nan"), int(both.sum())),
        "nn_similarity_median": float(np.median(S_other.max(axis=1))),
        "feature_stability": (stab, stab_n),
        "rule_hypothesis_counts": ref["rule_hypothesis"].value_counts(dropna=False).to_dict(),
        "rules_fired": dict(fired.most_common()),
        "rules_context_excluded": dict(excluded.most_common()),
        "prediction_types": res["type"].value_counts().to_dict(),
        "outcomes": res["outcome"].value_counts().to_dict(),
        "replicate_prediction_agreement": (rep_same / rep_pairs if rep_pairs else float("nan"), rep_pairs),
        "inferred_predictions": res.loc[res["type"] == "INFERRED", "prediction"].value_counts().to_dict(),
        "dark_prediction_types": res.loc[res["dark"], "type"].value_counts().to_dict(),
        "confidence_by_type": res.groupby("type")["confidence"].describe()[["count", "mean", "min", "max"]].round(3),
        "clusters": clusters,
        "ood_threshold": float(model["ood_similarity_threshold"]),
    }


def outcome(r: dict) -> str:
    """'specific (HIGH)', 'group (MODERATE)', 'OBSERVED', 'UNKNOWN'."""
    if r["prediction_type"] == "INFERRED":
        return f"{r['prediction_kind']} ({r['support_level']})"
    return r["prediction_type"]


def compare_with_baseline(new: pd.DataFrame, baseline: pd.DataFrame) -> str:
    """Markdown comparison of the current predictions.csv with a previous one.

    Confidence check: for spectra whose best candidate hypothesis is the same
    rule set as before, the evidence confidence must be identical (the formula
    is unchanged). Any change in confidence must come from a different
    candidate being chosen, never from a lowered threshold."""
    m = new.merge(baseline, on="Sample", suffixes=("", "_old"))
    m["same_candidate"] = [members_of(a) == members_of(b) for a, b in zip(m["Best_Candidate"], m["Best_Candidate_old"])]
    same = m[m["same_candidate"]]
    diff = (same["Evidence_Confidence"] - same["Evidence_Confidence_old"]).abs()
    changed = m[~m["same_candidate"]]
    delta = changed["Evidence_Confidence"] - changed["Evidence_Confidence_old"]
    trans = pd.crosstab(m["Prediction_Type_old"], m["Outcome"])
    lines = [
        "# Fusion layer v2 vs v1 (same data, same model, same features)", "",
        "| outcome | v1 (previous) | v2 (ranked candidates) |", "|---|---|---|",
    ]
    v1 = m["Prediction_Type_old"].value_counts()
    v2 = m["Outcome"].value_counts()
    v1_kind = {"specific": 0, "group": 0}
    for lab, t in zip(m["Best_Candidate_old"], m["Prediction_Type_old"]):
        if t == "INFERRED":
            v1_kind["specific" if len(members_of(lab)) == 1 else "group"] += 1
    rows = [("INFERRED — specific mineral", v1_kind["specific"], int(v2[[i for i in v2.index if i.startswith("specific")]].sum())),
            ("INFERRED — mineral group", v1_kind["group"], int(v2[[i for i in v2.index if i.startswith("group")]].sum())),
            ("   of which HIGH support", int(v1.get("INFERRED", 0)), int(v2[[i for i in v2.index if "HIGH" in i]].sum())),
            ("   of which MODERATE support", 0, int(v2[[i for i in v2.index if "MODERATE" in i]].sum())),
            ("OBSERVED", int(v1.get("OBSERVED", 0)), int(v2.get("OBSERVED", 0))),
            ("UNKNOWN", int(v1.get("UNKNOWN", 0)), int(v2.get("UNKNOWN", 0)))]
    lines += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    lines += ["", "(v1 had no HIGH/MODERATE levels; all its INFERRED results required the HIGH condition.)", "",
              "## Transitions (rows: v1 type, columns: v2 outcome)", "", _md(trans.reset_index()), "",
              "## Confidence check",
              f"- Spectra whose best candidate is the same rule set as in v1: {len(same)}; maximum absolute change "
              f"in evidence confidence: {diff.max() if len(diff) else 0:.6f} (formula unchanged → must be 0).",
              f"- Spectra whose best candidate changed: {len(changed)}; confidence change "
              f"min {delta.min() if len(delta) else 0:+.3f}, median {delta.median() if len(delta) else 0:+.3f}, "
              f"max {delta.max() if len(delta) else 0:+.3f}. These come from a different hypothesis being ranked "
              "first (e.g. a partial-match or narrower candidate), not from a threshold change.",
              f"- Median evidence confidence of INFERRED results: v1 "
              f"{m.loc[m['Prediction_Type_old'] == 'INFERRED', 'Evidence_Confidence_old'].median():.3f}, v2 HIGH "
              f"{m.loc[m['Outcome'].str.contains('HIGH'), 'Evidence_Confidence'].median():.3f}, v2 MODERATE "
              f"{m.loc[m['Outcome'].str.contains('MODERATE'), 'Evidence_Confidence'].median():.3f}.",
              "- MODERATE results keep their (lower) confidence values; the level label reflects which evidence "
              "sources exist, the number is not raised.", ""]
    return "\n".join(lines)


def _md(df: pd.DataFrame) -> str:
    rows = [list(map(str, df.columns))] + [[str(v) for v in r] for r in df.itertuples(index=False)]
    return "\n".join(["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])] +
                     ["| " + " | ".join(r) + " |" for r in rows[1:]])


def report_markdown(ev: dict) -> str:
    rr, rn = ev["replicate_same_cluster"]
    kr, kn = ev["same_rock_same_cluster"]
    na, nn_n = ev["nn_other_rock_rule_agreement"]
    st, st_n = ev["feature_stability"]
    lines = [
        "# Model evaluation (label-free)", "",
        "> There is **no ground-truth label file**. No accuracy, precision, recall, F1 or confusion matrix is "
        "reported, because none can be computed honestly. Everything below measures internal consistency.", "",
        "## Unsupervised model",
        f"- PCA: {ev['pca_components']} components explain {100 * ev['pca_variance']:.1f} % of the variance of the "
        "measurement-level continuum-removed vectors.",
        f"- K-Means: k = {ev['chosen_k']} chosen by the highest silhouette score (k = 2–10):", "",
        _md(ev["k_table"].round(3)), "",
        "Silhouette ranges from −1 to 1; values around 0.25–0.5 indicate weak-to-moderate, not crisp, structure.", "",
        "## Replicate-aware consistency",
        f"- Technical replicates in the same cluster: **{100 * rr:.1f} %** of {rn} pairs",
        f"- Spectra of the same rock in the same cluster: **{100 * kr:.1f} %** of {kn} pairs",
        f"- Baseline (two random different-rock spectra share a cluster): {100 * ev['different_rock_same_cluster_baseline']:.1f} %",
        f"- Nearest spectrum from a *different rock* is in the same cluster: {100 * ev['nn_other_rock_same_cluster']:.1f} %",
        f"- Nearest different-rock spectrum carries a matching rule-based hypothesis (Jaccard ≥ 0.5): {100 * na:.1f} % "
        f"(of {nn_n} spectra where both have one)",
        f"- Median cosine similarity to nearest different-rock spectrum (PCA space): {ev['nn_similarity_median']:.3f}; "
        f"out-of-distribution threshold (5th percentile): {ev['ood_threshold']:.3f}", "",
        "## Preprocessing / feature-extraction stability",
        f"- Features ≥3 % deep that reappear within ±10 nm in the replicate spectrum: **{100 * st:.1f} %** "
        f"({st_n} replicate comparisons)", "",
        "## Rule engine (i.hyper.spectroscopy) on extracted features",
        f"- Strong rule-based hypotheses used as pseudo-labels (R ≥ 0.40; NOT ground truth): "
        f"{ {('none' if k is None or k != k else k): v for k, v in ev['rule_hypothesis_counts'].items()} }",
        f"- Composite rules that fired (spectra): {ev['rules_fired']}",
        f"- Fired but excluded as implausible for rock spectra: {ev['rules_context_excluded']}", "",
        "## Clusters", "",
        _md(pd.DataFrame(ev["clusters"])), "",
        "Cluster numbers are arbitrary; a cluster is a group of similar spectral shapes, not a confirmed mineral class.", "",
        "## Final predictions (leave-own-rock-out)",
        f"- Prediction types: {ev['prediction_types']}",
        f"- Outcomes (kind and support level): {ev['outcomes']}",
        f"- Technical replicates with the identical final prediction: "
        f"{100 * ev['replicate_prediction_agreement'][0]:.1f} % of {ev['replicate_prediction_agreement'][1]} pairs",
        f"- INFERRED predictions: {ev['inferred_predictions']}",
        f"- Dark (low-albedo) spectra: {ev['dark_prediction_types']}", "",
        _md(ev["confidence_by_type"].reset_index()), "",
        "Evidence confidence is a documented combination of rule, neighbour and cluster agreement — not a probability.", "",
    ]
    return "\n".join(lines)
