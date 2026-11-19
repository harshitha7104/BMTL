"""Build the DEMO pseudo-labelled dataset and the DEMO classifier.

    python build_demo.py

Requires the evidence model (run `python run_pipeline.py` first). Writes:
    data/demo_labelled/   demo_labelled_spectra.csv, demo_labels.csv, demo_rejected.csv,
                          demo_dataset_summary.md
    models/demo/          demo_classifier.joblib, demo_model_card.json
    outputs/demo/         pseudo_label_validation.md, oof_predictions.csv, confusion matrix figure

The original CSV, the evidence model and i.hyper.spectroscopy.py are only read.
Labels are PSEUDO-LABELS from the rule engine, not ground truth.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.analysis import analyse_spectrum  # noqa: E402
from src.data_loader import build_sample_table, load_spectra  # noqa: E402
from src.demo import (DEMO_BANNER, LABEL_SOURCE, MIN_E, MIN_FEATURE_DEPTH, MIN_NEIGHBOUR_FEATURE_MATCH,  # noqa: E402
                      MIN_REPLICATE_AGREEMENT, TARGET_MAX, build_pseudo_labels, train_demo_classifier)
from src.predict import Predictor  # noqa: E402

ROOT = Path(__file__).resolve().parent
SOURCE_CSV = ROOT / "68026941d4be0210cde07d8c.csv"
DATA_DIR = ROOT / "data" / "demo_labelled"
MODEL_DIR = ROOT / "models" / "demo"
OUT_DIR = ROOT / "outputs" / "demo"
DEMO_MODEL_PATH = MODEL_DIR / "demo_classifier.joblib"
log = logging.getLogger("build_demo")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    src_hash = sha256(SOURCE_CSV)
    ds = load_spectra(SOURCE_CSV)
    samples = build_sample_table(ds.sample_names)
    predictor = Predictor()
    accepted, rejected = build_pseudo_labels(ds, samples, predictor)
    log.info("Pseudo-labels: %d accepted, %d rejected", len(accepted), len(rejected))

    for d in (DATA_DIR, MODEL_DIR, OUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
    accepted = accepted.reset_index(drop=True)
    accepted.insert(0, "sample_id", [f"demo_{i + 1:03d}" for i in range(len(accepted))])
    accepted["is_pseudo_label"] = True
    accepted["label_source"] = LABEL_SOURCE

    # 2. labels table
    labels = accepted[["sample_id", "pseudo_label", "family_class", "rule_set", "pseudo_label_confidence",
                       "rule_score", "evidence_status", "label_source", "is_pseudo_label",
                       "supporting_features", "supporting_wavelengths", "original_sample_id",
                       "source_column_index", "rock_id", "measurement_id", "E", "N", "C", "Q",
                       "evidence_confidence", "replicate_agreement", "max_feature_depth", "nn_feature_match"]]
    labels.to_csv(DATA_DIR / "demo_labels.csv", index=False)
    rejected[["original_sample_id", "rock_id", "rule_set", "prediction_type", "support_level",
              "evidence_confidence", "rejection_reasons"]].to_csv(DATA_DIR / "demo_rejected.csv", index=False)

    # 1. spectra + metadata: reflectance copied verbatim from the original columns
    wl_cols = [f"{w:.3f}nm" for w in ds.wavelength_nm]
    spec = pd.DataFrame(ds.reflectance[[ds.sample_names.index(n) for n in accepted["original_sample_id"]]],
                        columns=wl_cols)
    meta = labels[["sample_id", "original_sample_id", "source_column_index", "rock_id", "pseudo_label",
                   "family_class", "pseudo_label_confidence", "evidence_status", "is_pseudo_label", "label_source"]]
    pd.concat([meta, spec], axis=1).to_csv(DATA_DIR / "demo_labelled_spectra.csv", index=False)

    # Demo classifier on continuum-removed vectors (same preprocessing as the evidence pipeline)
    X = np.vstack([analyse_spectrum(ds.wavelength_nm, ds.spectrum(n), predictor.cfg).vector
                   for n in accepted["original_sample_id"]])
    demo = train_demo_classifier(X, accepted["pseudo_label"].to_numpy(), accepted["rock_id"].to_numpy(),
                                 accepted["original_sample_id"].tolist())
    demo["labels_table"] = labels
    demo["source_csv_sha256"] = src_hash
    joblib.dump(demo, DEMO_MODEL_PATH)
    v = demo["validation"]
    card = {k: demo[k] for k in ("created", "random_state", "banner", "label_source", "classes", "excluded_classes")}
    card.update(validation=v, features="continuum-removed 10 nm vector -> PCA(10) -> RandomForest(300, balanced)",
                n_training_samples=int(len(demo["train_y"])), source_csv_sha256=src_hash)
    (MODEL_DIR / "demo_model_card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    demo["oof"].to_csv(OUT_DIR / "oof_predictions.csv", index=False)

    fig, ax = plt.subplots(figsize=(7.5, 6))
    cm = np.array(v["confusion_matrix"])
    ax.imshow(cm, cmap="Blues")
    short = [lab.replace(" / ", "/")[:38] for lab in v["labels"]]
    fam = labels.drop_duplicates("pseudo_label").set_index("pseudo_label")["family_class"]
    ax.set_xticks(range(len(short)), [fam[lab] for lab in v["labels"]], rotation=30, ha="right", fontsize=8)
    ax.set_yticks(range(len(short)), [fam[lab] for lab in v["labels"]], fontsize=8)
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, cm[i, j], ha="center", va="center", color="white" if cm[i, j] > cm.max() / 2 else "black")
    ax.set_xlabel("Out-of-fold demo prediction")
    ax.set_ylabel("Pseudo-label (rule engine)")
    ax.set_title("Pseudo-label validation (grouped by rock) — NOT mineral accuracy", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "pseudo_label_confusion_matrix.png", dpi=130)

    (OUT_DIR / "pseudo_label_validation.md").write_text(validation_md(v, demo), encoding="utf-8")
    (DATA_DIR / "demo_dataset_summary.md").write_text(summary_md(accepted, rejected, labels, v, demo), encoding="utf-8")

    assert sha256(SOURCE_CSV) == src_hash, "source CSV changed!"
    log.info("Demo dataset: %d samples, %d classes. Source CSV unchanged (sha256 %s…)",
             len(accepted), accepted["pseudo_label"].nunique(), src_hash[:16])
    return 0


def validation_md(v: dict, demo: dict) -> str:
    lines = [
        "# Pseudo-label validation performance", "", f"> {DEMO_BANNER}", "",
        "This measures how well a classifier trained on continuum-removed spectra **reproduces the rule engine's "
        "pseudo-labels on rocks it has not seen**. It is **not** mineral identification accuracy: there is no "
        "ground truth.", "",
        f"- Samples: {v['n_samples']} from {v['n_rocks']} rocks; {v['n_splits']}-fold StratifiedGroupKFold, "
        f"grouped by {v['grouping']}",
        f"- No rock in both training and validation in any fold: {v['no_rock_in_train_and_validation']}",
        f"- Pseudo-label validation accuracy: {v['accuracy']:.3f}",
        f"- Pseudo-label validation balanced accuracy: {v['balanced_accuracy']:.3f}",
        f"- Pseudo-label validation macro F1: {v['macro_f1']:.3f}",
        f"- Majority-class baseline accuracy: {v['majority_class_baseline_accuracy']:.3f}",
        f"- Per-class F1: {v['per_class_f1']}",
        f"- Classes excluded from the classifier (< 3 rocks): {demo['excluded_classes'] or 'none'}", "",
        "Caveats: the pseudo-labels themselves were derived using similarity to other rocks' rule-based "
        "hypotheses (fusion layer), so folds are not fully independent of each other's labels. Labels are "
        "chemical-family groups of rules the engine cannot separate.", "",
    ]
    return "\n".join(lines)


def summary_md(acc: pd.DataFrame, rej: pd.DataFrame, labels: pd.DataFrame, v: dict, demo: dict) -> str:
    reasons = rej["rejection_reasons"].str.split("; ").explode().value_counts()
    dist = acc.groupby(["family_class", "pseudo_label"]).agg(samples=("sample_id", "size"),
                                                            rocks=("rock_id", "nunique")).reset_index()
    exact = acc.groupby("family_class")["rule_set"].nunique()
    conf = acc["pseudo_label_confidence"].describe()
    lines = [
        "# DEMO pseudo-labelled dataset", "",
        "> **These are PSEUDO-LABELS, not ground truth.** They were generated from the existing "
        "i.hyper.spectroscopy rule engine applied to absorption features extracted by this project's pipeline, "
        "and checked against similar spectra, replicates and data quality. No mineral identity has been "
        "verified (e.g. by XRD). Use them for demonstration only.", "",
        f"- Source: the 170 spectra of `68026941d4be0210cde07d8c.csv` (unchanged; reflectance values copied "
        "verbatim). No spectra were fabricated, resampled or duplicated.",
        f"- **Samples selected: {len(acc)}** from {acc['rock_id'].nunique()} rocks",
        f"- **Unique pseudo-labels: {acc['pseudo_label'].nunique()}**",
        f"- **Rejected / not selected: {len(rej)}**", "",
        "## Acceptance criteria (all required)",
        "- Fusion layer returned INFERRED with an eligible, plausible rock/mineral hypothesis",
        f"- Own-spectrum rule evidence E ≥ {MIN_E}; deepest supporting absorption ≥ {100 * MIN_FEATURE_DEPTH:.0f} %",
        f"- Most similar other-rock spectrum shares ≥ {100 * MIN_NEIGHBOUR_FEATURE_MATCH:.0f} % of its absorption depth",
        f"- Replicates of the same spot agree (≥ {100 * MIN_REPLICATE_AGREEMENT:.0f} % compatible) when replicates exist",
        "- Not dark (low albedo), not novel/out-of-distribution, no near-tie with an alternative, no QC error",
        f"- At most {TARGET_MAX} samples; if more pass, classes are filled round-robin by confidence (no oversampling)", "",
        "## Pseudo-label definition",
        "Each spectrum's rule engine output is a set of composite rules the engine cannot separate (they rest on "
        "the same deepest absorption). These sets fall into chemical-family classes; each class is labelled with "
        "the **union** of its member rules (a weaker claim than any individual set — it never adds certainty). "
        "The exact per-spectrum rule set is kept in `demo_labels.csv` (`rule_set`).", "",
        "## Class distribution", "",
        "| family class | pseudo_label | samples | rocks |", "|---|---|---|---|",
        *[f"| {r.family_class} | {r.pseudo_label} | {r.samples} | {r.rocks} |" for r in dist.itertuples()], "",
        "## Mineral groups that could not be separated",
        *[f"- **{fc}**: {n} different indistinguishable rule sets occur, e.g. "
          f"`{acc.loc[acc['family_class'] == fc, 'rule_set'].value_counts().index[0]}`" for fc, n in exact.items()],
        "- All classes share the ~2320–2345 nm absorption; Mg-OH silicate classes additionally have a ~2380–2390 nm "
        "absorption (talc rule), Fe-OH amphibole classes a ~440 nm Fe³⁺ absorption (crocidolite rule). "
        "Asbestos rule names are spectral hypotheses only and need mineralogical confirmation.", "",
        "## Pseudo-label confidence",
        f"pseudo_label_confidence = evidence confidence × replicate factor (0.5 + 0.5 × replicate agreement; 0.75 if "
        f"no replicates). It is never higher than the evidence confidence and is not a probability.",
        f"- min {conf['min']:.3f}, median {conf['50%']:.3f}, max {conf['max']:.3f}",
        f"- Evidence status: {acc['evidence_status'].value_counts().to_dict()}", "",
        "## Rejection reasons (a spectrum can have several)", "",
        "| reason | spectra |", "|---|---|", *[f"| {k} | {n} |" for k, n in reasons.items()], "",
        "## Demo classifier",
        f"- {v['metric_name']}: accuracy {v['accuracy']:.3f}, balanced accuracy {v['balanced_accuracy']:.3f}, "
        f"macro F1 {v['macro_f1']:.3f} (majority baseline {v['majority_class_baseline_accuracy']:.3f}); "
        "grouped by rock. See `outputs/demo/pseudo_label_validation.md`.", "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
