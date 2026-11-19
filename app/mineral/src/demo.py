"""DEMO pseudo-labelled dataset and DEMO classifier.

Everything here is built from the 170 original spectra and the existing
evidence pipeline. The labels are PSEUDO-LABELS generated from the
i.hyper.spectroscopy rule engine (plus the fusion layer's evidence checks).
They are NOT ground truth, and any accuracy computed against them measures
how well a classifier reproduces the rule engine — not mineral accuracy.
"""
from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline

from .analysis import Analysis
from .data_loader import SpectralDataset
from .fusion import family_of, jaccard, members_of
from .model import normalise_rows

log = logging.getLogger(__name__)

LABEL_SOURCE = "spectroscopy_rule_engine"
DEMO_BANNER = ("DEMO MODEL — trained using pseudo-labels generated from the spectral rule engine. "
               "These labels are not ground truth.")
RANDOM_STATE = 42

# --- acceptance criteria for a pseudo-label (all must hold) ----------------------------------
MIN_E = 0.40                 # own-spectrum rule evidence counts as a spectral source
MIN_FEATURE_DEPTH = 0.03     # deepest supporting absorption is clearly measurable (>= 3 %)
MIN_NEIGHBOUR_FEATURE_MATCH = 0.50   # the most similar other-rock spectrum shares its absorptions
MIN_REPLICATE_AGREEMENT = 0.50       # replicates of the same spot reach a compatible hypothesis
TARGET_MAX = 100
MIN_ROCKS_FOR_CLASSIFIER = 3


def family_class(rule_set: set[str]) -> str:
    """Class name from the chemical families of the indistinguishable rule set."""
    order = ["Mg-OH silicate", "Fe-OH amphibole", "Carbonate"]
    fams = {family_of(r) for r in rule_set}
    ordered = [f for f in order if f in fams] + sorted(fams - set(order))
    return " + ".join(ordered)


def _evidence_row(name: str, rock: str, measurement: str | None, result: dict) -> dict:
    comp = result["evidence_components"] or {}
    label = comp.get("label")
    rules = members_of(label)
    support = [s for c in result["rule_evidence"] if c["name"] in rules for s in c["supporting_features"]]
    rule_scores = [c["rule_score"] for c in result["rule_evidence"] if c["name"] in rules]
    w = result["warnings"]
    return {
        "original_sample_id": name, "rock_id": rock, "measurement_id": measurement,
        "prediction_type": result["prediction_type"], "support_level": result["support_level"],
        "rule_set": " / ".join(sorted(rules)) if rules else None,
        "E": comp.get("E"), "N": comp.get("N"), "C": comp.get("C"), "Q": comp.get("Q"),
        "evidence_confidence": result["confidence"],
        "rule_score": max(rule_scores) if rule_scores else None,
        "max_feature_depth": max((s["depth"] for s in support), default=0.0),
        "supporting_features": "; ".join(f"{s['species']}@{s['center_nm']:.0f}nm({100 * s['depth']:.1f}%)"
                                         for s in sorted(support, key=lambda s: -s["depth"])),
        "supporting_wavelengths": ";".join(f"{c:.0f}" for c in sorted({s["center_nm"] for s in support})),
        "nn_feature_match": result["similar_samples"][0]["feature_match"] if result["similar_samples"] else 0.0,
        "dark": any("low_albedo" in x for x in w),
        "novel": any(("Novel spectrum" in x) or ("less similar to any reference" in x) for x in w),
        "near_tie": any("Near-tie" in x for x in w),
        "qc_error": any(x.startswith("[ERROR]") for x in w),
    }


def build_pseudo_labels(ds: SpectralDataset, samples: pd.DataFrame, predictor) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate every original spectrum; return (accepted, rejected) tables with full evidence."""
    meta = samples.set_index("sample")
    rows = []
    for i, name in enumerate(ds.sample_names):
        rock = meta.loc[name, "rock_id"] or name
        res = predictor.predict(ds.wavelength_nm, ds.reflectance[i], "nm", name, exclude_rock=rock)
        row = _evidence_row(name, rock, meta.loc[name, "measurement_id"], res)
        row["source_column_index"] = i + 1      # column position in the original CSV (0 = Wavelength)
        rows.append(row)
    ev = pd.DataFrame(rows)

    # Replicate consistency: share of the other replicates of the same spot whose rule set is compatible.
    agree = []
    for _, r in ev.iterrows():
        others = ev[(ev["measurement_id"] == r["measurement_id"]) & (ev["original_sample_id"] != r["original_sample_id"])]
        if r["measurement_id"] is None or others.empty or not r["rule_set"]:
            agree.append(np.nan)
        else:
            agree.append(float(np.mean([jaccard(r["rule_set"], o) >= 0.5 for o in others["rule_set"]])))
    ev["replicate_agreement"] = agree

    reasons = []
    for _, r in ev.iterrows():
        why = []
        if r["qc_error"]:
            why.append("severely degraded spectrum (quality-check error)")
        if r["prediction_type"] != "INFERRED" or not r["rule_set"]:
            why.append("no supported mineral prediction")
        if r["dark"]:
            why.append("dark spectrum (low albedo): kept in data, not used as pseudo-label")
        if r["novel"]:
            why.append("unlike other reference spectra (novel / out-of-distribution)")
        if r["near_tie"]:
            why.append("conflicting evidence: alternative hypothesis almost equally supported")
        if (r["E"] or 0) < MIN_E:
            why.append(f"own-spectrum rule evidence E < {MIN_E}")
        if r["max_feature_depth"] < MIN_FEATURE_DEPTH:
            why.append(f"supporting absorption shallower than {100 * MIN_FEATURE_DEPTH:.0f} %")
        if r["nn_feature_match"] < MIN_NEIGHBOUR_FEATURE_MATCH:
            why.append("absorptions not shared by the most similar other-rock spectrum")
        if not np.isnan(r["replicate_agreement"]) and r["replicate_agreement"] < MIN_REPLICATE_AGREEMENT:
            why.append("replicates of the same spot disagree")
        reasons.append(why)
    ev["rejection_reasons"] = ["; ".join(w) for w in reasons]
    passed = ev[[not w for w in reasons]].copy()

    rep = passed["replicate_agreement"]
    # Confidence never exceeds the fusion layer's evidence confidence.
    passed["pseudo_label_confidence"] = (passed["evidence_confidence"] *
                                         np.where(rep.isna(), 0.75, 0.5 + 0.5 * rep.fillna(0))).round(3)
    passed["family_class"] = [family_class(members_of(s)) for s in passed["rule_set"]]
    union = passed.groupby("family_class")["rule_set"].apply(
        lambda s: " / ".join(sorted(set().union(*(members_of(x) for x in s)))))
    passed["pseudo_label"] = passed["family_class"].map(union)
    passed["evidence_status"] = [
        f"{'multi_source' if lvl == 'HIGH' else 'single_source'}_{lvl.lower()}"
        f"{'' if np.isnan(a) else ('_replicates_consistent' if a == 1 else '_replicates_mostly_consistent')}"
        for lvl, a in zip(passed["support_level"], passed["replicate_agreement"])]

    selected = select_balanced(passed, TARGET_MAX)
    capped = passed[~passed["original_sample_id"].isin(selected["original_sample_id"])].copy()
    capped["rejection_reasons"] = "passed evidence checks but not selected (class balance cap of the demo set)"
    rejected = pd.concat([ev[[bool(w) for w in reasons]], capped], ignore_index=True)
    return selected.reset_index(drop=True), rejected


def select_balanced(passed: pd.DataFrame, target: int) -> pd.DataFrame:
    """Keep everything if <= target; otherwise round-robin over classes by confidence (no duplication)."""
    if len(passed) <= target:
        return passed.sort_values(["family_class", "pseudo_label_confidence"], ascending=[True, False])
    queues = {c: g.sort_values("pseudo_label_confidence", ascending=False).index.tolist()
              for c, g in passed.groupby("family_class")}
    chosen = []
    while len(chosen) < target and any(queues.values()):
        for c in sorted(queues, key=lambda c: len(queues[c])):
            if queues[c] and len(chosen) < target:
                chosen.append(queues[c].pop(0))
    return passed.loc[chosen].sort_values(["family_class", "pseudo_label_confidence"], ascending=[True, False])


# --------------------------------------------------------------------------------------------------
# Demo classifier
# --------------------------------------------------------------------------------------------------

def make_classifier() -> Pipeline:
    return Pipeline([
        ("pca", PCA(n_components=10, random_state=RANDOM_STATE)),
        ("rf", RandomForestClassifier(n_estimators=300, min_samples_leaf=2, class_weight="balanced",
                                      random_state=RANDOM_STATE)),
    ])


def train_demo_classifier(X: np.ndarray, y: np.ndarray, groups: np.ndarray, names: list[str]) -> dict:
    """Grouped (by rock) cross-validation, then a final fit on all demo samples."""
    classes, counts = np.unique(y, return_counts=True)
    rocks_per_class = {c: len(set(groups[y == c])) for c in classes}
    usable = [c for c in classes if rocks_per_class[c] >= MIN_ROCKS_FOR_CLASSIFIER]
    keep = np.isin(y, usable)
    X, y, groups = X[keep], y[keep], groups[keep]
    names = [n for n, k in zip(names, keep) if k]
    n_splits = min(5, min(rocks_per_class[c] for c in usable))
    cv = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=RANDOM_STATE)
    oof = np.empty(len(y), dtype=object)
    oof_share = np.zeros(len(y))
    leak_free = True
    for tr, te in cv.split(X, y, groups):
        leak_free &= not (set(groups[tr]) & set(groups[te]))
        clf = make_classifier().fit(X[tr], y[tr])
        proba = clf.predict_proba(X[te])
        oof[te] = clf.classes_[proba.argmax(axis=1)]
        oof_share[te] = proba.max(axis=1)
    majority = pd.Series(y).value_counts().idxmax()
    labels = sorted(usable)
    validation = {
        "metric_name": "Pseudo-label validation performance (NOT mineral accuracy)",
        "n_samples": int(len(y)), "n_rocks": int(len(set(groups))), "n_splits": int(n_splits),
        "grouping": "rock_id (all replicates and surfaces of a rock stay in the same fold)",
        "no_rock_in_train_and_validation": bool(leak_free),
        "accuracy": float(accuracy_score(y, oof)),
        "balanced_accuracy": float(balanced_accuracy_score(y, oof)),
        "macro_f1": float(f1_score(y, oof, average="macro")),
        "majority_class_baseline_accuracy": float(np.mean(y == majority)),
        "labels": labels,
        "confusion_matrix": confusion_matrix(y, oof, labels=labels).tolist(),
        "per_class_f1": dict(zip(labels, f1_score(y, oof, labels=labels, average=None).round(3).tolist())),
    }
    final = make_classifier().fit(X, y)
    return {
        "classifier": final, "classes": list(final.classes_), "validation": validation,
        "excluded_classes": {c: int(rocks_per_class[c]) for c in classes if c not in usable},
        "oof": pd.DataFrame({"original_sample_id": names, "pseudo_label": y, "oof_prediction": oof,
                             "oof_vote_share": oof_share.round(3), "rock_id": groups}),
        "train_X": X, "train_y": y, "train_rocks": groups, "train_names": names,
        "created": datetime.now().isoformat(timespec="seconds"), "random_state": RANDOM_STATE,
        "banner": DEMO_BANNER, "label_source": LABEL_SOURCE,
    }


class DemoPredictor:
    """Predict with the demo classifier and attach rule-engine evidence for comparison."""

    def __init__(self, demo_model: dict, evidence_predictor):
        self.m = demo_model
        self.evidence = evidence_predictor
        self.train_unit = normalise_rows(self.m["train_X"])
        self.oof = self.m["oof"].set_index("original_sample_id")
        self.labels = self.m["labels_table"].set_index("original_sample_id")

    def predict(self, wavelengths_nm, reflectance, sample_name: str | None = None,
                exclude_rock: str | None = None) -> dict:
        res = self.evidence.predict(wavelengths_nm, reflectance, "nm", sample_name, exclude_rock)
        analysis: Analysis = res["_analysis"]
        out = {"banner": DEMO_BANNER, "prediction_source": "demo classifier (pseudo-label trained)",
               "evidence_result": res, "warnings": list(res["warnings"])}
        if res["decision_reason"] == "spectrum failed quality checks":
            out.update(predicted=None, vote_share=0.0, alternatives=[], similar_demo_spectra=[],
                       supporting_features=[])
            out["warnings"].append("Demo classifier not applied: spectrum failed quality checks.")
            return out
        proba = self.m["classifier"].predict_proba(analysis.vector[None, :])[0]
        order = np.argsort(-proba)
        classes = self.m["classifier"].classes_
        predicted = classes[order[0]]
        rules = members_of(predicted)
        support = [s for c in res["rule_evidence"] if c["name"] in rules for s in c["supporting_features"]]
        sims = self.train_unit @ normalise_rows(analysis.vector)
        similar = []
        for j in np.argsort(-sims):
            if self.m["train_rocks"][j] == exclude_rock:
                continue
            similar.append({"sample": self.m["train_names"][j], "rock_id": self.m["train_rocks"][j],
                            "cosine_similarity": round(float(sims[j]), 4), "pseudo_label": self.m["train_y"][j]})
            if len(similar) == 5:
                break
        rule_rules = members_of((res["evidence_components"] or {}).get("label"))
        out.update(
            predicted=predicted,
            predicted_family=family_class(rules),
            vote_share=round(float(proba[order[0]]), 3),
            alternatives=[{"pseudo_label": classes[k], "family": family_class(members_of(classes[k])),
                           "vote_share": round(float(proba[k]), 3)} for k in order[1:4]],
            supporting_features=sorted(support, key=lambda s: -s["depth"]),
            similar_demo_spectra=similar,
            rule_engine_prediction=res["prediction"], rule_engine_rule_set=" / ".join(sorted(rule_rules)),
            agrees_with_rule_engine=bool(rule_rules & rules) and rule_rules <= rules,
        )
        if not support:
            out["warnings"].append("The demo classifier's class is not supported by any rule-engine absorption "
                                   "match in this spectrum.")
        novel = any(("Novel spectrum" in x) or ("less similar to any reference" in x) for x in res["warnings"])
        if novel or not out["agrees_with_rule_engine"]:
            out["warnings"].append(
                f"Closed-set demo classifier: it can only answer with one of its {len(classes)} pseudo-label classes. "
                + ("This spectrum is unlike the reference spectra" if novel else
                   "The rule engine's own evidence points elsewhere")
                + ", so the demo class is unreliable here; prefer the normal (evidence-based) mode.")
        if sample_name is not None and sample_name in self.labels.index:
            lab = self.labels.loc[sample_name]
            out["in_demo_training_set"] = True
            out["pseudo_label_of_this_sample"] = lab["pseudo_label"]
            if sample_name in self.oof.index:
                o = self.oof.loc[sample_name]
                out["out_of_fold_prediction"] = o["oof_prediction"]
                out["out_of_fold_vote_share"] = float(o["oof_vote_share"])
            out["warnings"].append("This spectrum is part of the demo training set; the main prediction is not an "
                                   "independent test. The out-of-fold prediction (its rock held out) is shown too.")
        else:
            out["in_demo_training_set"] = False
        return out
