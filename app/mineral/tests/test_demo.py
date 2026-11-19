"""Integrity tests for the DEMO pseudo-labelled dataset and DEMO classifier.

Skipped if `python build_demo.py` has not been run."""
import hashlib
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from src.data_loader import load_spectra
from src.demo import LABEL_SOURCE, DemoPredictor, family_class, select_balanced
from src.fusion import members_of
from src.predict import DEFAULT_MODEL_PATH, Predictor

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "68026941d4be0210cde07d8c.csv"
DEMO_DIR = ROOT / "data" / "demo_labelled"
DEMO_MODEL = ROOT / "models" / "demo" / "demo_classifier.joblib"
SOURCE_SHA256 = "a43ef17bb707f450e01b8f34c2ef7dc74e338ef4ced4ddc0505d6f03a6887be7"

built = pytest.mark.skipif(not (DEMO_DIR / "demo_labels.csv").is_file() or not DEMO_MODEL.is_file(),
                           reason="run `python build_demo.py` first")


def test_source_csv_checksum_unchanged():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA256


def test_family_class_names():
    assert family_class({"dolomite", "ankerite"}) == "Carbonate"
    assert family_class({"talc", "crocidolite_asbestos", "calcite"}) == "Mg-OH silicate + Fe-OH amphibole + Carbonate"


def test_select_balanced_never_duplicates_and_caps():
    df = pd.DataFrame({"family_class": ["A"] * 8 + ["B"] * 2, "pseudo_label_confidence": np.linspace(0.9, 0.1, 10),
                       "original_sample_id": [f"s{i}" for i in range(10)]})
    sel = select_balanced(df, 6)
    assert len(sel) == 6 and sel["original_sample_id"].is_unique
    assert (sel["family_class"] == "B").sum() == 2  # the minority class is kept in full


@built
def test_demo_spectra_are_verbatim_copies_of_original_columns():
    ds = load_spectra(SOURCE)
    spec = pd.read_csv(DEMO_DIR / "demo_labelled_spectra.csv")
    wl_cols = [c for c in spec.columns if c.endswith("nm")]
    assert len(wl_cols) == ds.n_bands
    for _, row in spec.iterrows():
        name = row["original_sample_id"]
        assert name in ds.sample_names                                   # only original spectra
        assert ds.sample_names.index(name) + 1 == row["source_column_index"]
        np.testing.assert_allclose(row[wl_cols].to_numpy(float), ds.spectrum(name), rtol=0, atol=1e-12)
    assert spec["original_sample_id"].is_unique                          # nothing duplicated / fabricated


@built
def test_every_label_is_a_traceable_pseudo_label():
    labels = pd.read_csv(DEMO_DIR / "demo_labels.csv")
    assert 50 <= len(labels) <= 100
    assert labels["is_pseudo_label"].all()
    assert (labels["label_source"] == LABEL_SOURCE).all()
    assert labels["supporting_wavelengths"].notna().all() and labels["supporting_features"].notna().all()
    for _, r in labels.iterrows():
        assert members_of(r["rule_set"]) <= members_of(r["pseudo_label"])  # label never more specific than evidence
        assert family_class(members_of(r["rule_set"])) == r["family_class"]
    assert (labels["pseudo_label_confidence"] <= labels["evidence_confidence"] + 1e-9).all()
    assert (labels["max_feature_depth"] >= 0.03).all()


@built
def test_dark_spectra_not_used_as_pseudo_labels():
    labels = pd.read_csv(DEMO_DIR / "demo_labels.csv")
    rejected = pd.read_csv(DEMO_DIR / "demo_rejected.csv")
    dark = rejected[rejected["rejection_reasons"].str.contains("dark spectrum")]["original_sample_id"]
    assert len(dark) == 12 and not set(dark) & set(labels["original_sample_id"])
    assert len(labels) + len(rejected) == 170


@built
def test_grouped_validation_has_no_rock_leakage():
    m = joblib.load(DEMO_MODEL)
    v = m["validation"]
    assert v["no_rock_in_train_and_validation"]
    assert "Pseudo-label validation" in v["metric_name"]


@built
def test_demo_predictor_runs_and_labels_source():
    if not DEFAULT_MODEL_PATH.is_file():
        pytest.skip("evidence model missing")
    ds = load_spectra(SOURCE)
    dp = DemoPredictor(joblib.load(DEMO_MODEL), Predictor())
    name = pd.read_csv(DEMO_DIR / "demo_labels.csv")["original_sample_id"].iloc[0]
    r = dp.predict(ds.wavelength_nm, ds.spectrum(name), name)
    assert r["predicted"] in dp.m["classes"]
    assert r["prediction_source"].startswith("demo classifier")
    assert r["in_demo_training_set"] and "out_of_fold_prediction" in r
    assert 0.0 <= r["vote_share"] <= 1.0 and r["alternatives"]
