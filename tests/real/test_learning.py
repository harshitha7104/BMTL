"""Self-learning pipeline: only CONFIRMED (lab-labelled) observations train; reference duplicates are excluded;
dry runs never promote. Uses a temporary records database with TEST FIXTURE values (not company data)."""
from __future__ import annotations

import json
import sqlite3
import time

import pandas as pd
import pytest

from src.realmodels import learning, train

pytestmark = pytest.mark.skipif(not (train.DATA / "xrf_icp_pairs.csv").exists(), reason="real dataset not built")

SCHEMA = """CREATE TABLE observations (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, day TEXT, username TEXT, session_id TEXT,
    source TEXT, label TEXT, instrument TEXT, basis TEXT, kind TEXT, observed TEXT, results TEXT, material TEXT, compound TEXT,
    label_state TEXT, icp TEXT, icp_by TEXT, icp_at REAL, icp_note TEXT);"""


def _db(tmp_path, rows):
    path = tmp_path / "records.db"
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    for observed, icp, state, material in rows:
        c.execute("INSERT INTO observations(ts, day, username, basis, instrument, observed, label_state, icp, material) VALUES (?,?,?,?,?,?,?,?,?)",
                  (time.time(), "2026-11-17", "t", "factory", "S1 TITAN", json.dumps(observed), state, json.dumps(icp) if icp else None, material))
    c.commit()
    c.close()
    return path


def _gun_values(sample: str) -> dict:
    pairs = pd.read_csv(train.DATA / "xrf_icp_pairs.csv", dtype={"sample": str})
    row = pairs[(pairs["sample"] == sample) & (pairs.calibration_basis == "factory")].iloc[0]
    return {e: float(row[f"xrf_{e}"]) for e in train.ELEMENTS if pd.notna(row[f"xrf_{e}"])}


def test_no_labels_means_no_training(tmp_path):
    path = _db(tmp_path, [(_gun_values("2"), None, "UNLABELLED", "NMC")])
    out = learning.run(path, dry_run=True)
    assert out["status"] == "skipped_no_labels" and not out["promoted"]
    assert out["unlabelled_by_material"] == {"NMC": 1}
    runs = sqlite3.connect(path).execute("SELECT status FROM learning_runs").fetchall()
    assert runs == [("skipped_no_labels",)]


def test_reference_sample_labels_are_excluded(tmp_path):
    icp = pd.read_csv(train.DATA / "icp_reference.csv", dtype={"sample": str}).set_index("sample").loc["2"]
    label = {e: float(icp[f"{e}_wtpct"]) for e in ("Ni", "Co", "Mn", "Li")}
    out = learning.run(_db(tmp_path, [(_gun_values("2"), label, "CONFIRMED", "NMC")]), dry_run=True)
    assert out["status"] == "skipped_only_reference_samples" and out["excluded_as_reference_samples"] == [1]


def test_candidate_is_evaluated_but_dry_run_never_promotes(tmp_path):
    before = (train.MODELS / "bmtl_real_models.joblib").stat().st_mtime
    fixture_icp = {"Ni": 12.0, "Co": 11.0, "Mn": 14.0, "Fe": 1.0, "Cu": 1.1, "Al": 0.8, "P": 0.4, "Li": 3.3}   # test fixture
    out = learning.run(_db(tmp_path, [(_gun_values("2"), fixture_icp, "CONFIRMED", "NMC")]), dry_run=True)
    assert out["status"] == "dry_run" and out["field_samples"] == 1 and not out["promoted"]
    assert set(out["checks"]) >= {"mean_relative_error", "lithium_relative_error", "detector_accuracy_drop"}
    assert (train.MODELS / "bmtl_real_models.joblib").stat().st_mtime == before


def test_decide_rules():
    base = {"elements": {"factory:Ni": 1.0, "factory:Co": 1.0}, "lithium_mae": 0.4, "detector_accuracy": 1.0}
    better = {"elements": {"factory:Ni": 0.9, "factory:Co": 0.95}, "lithium_mae": 0.4, "detector_accuracy": 1.0}
    one_worse = {"elements": {"factory:Ni": 0.5, "factory:Co": 1.2}, "lithium_mae": 0.4, "detector_accuracy": 1.0}
    assert learning.decide(base, better)[0] is True
    assert learning.decide(base, one_worse)[0] is False
    assert learning.decide(base, better | {"detector_accuracy": 0.9})[0] is False


def test_tampered_model_file_is_refused(tmp_path):
    """Security audit L-12: a joblib model is a pickle; one that does not match its model card's SHA-256 never loads."""
    import shutil

    shutil.copytree(train.MODELS, tmp_path / "models")
    assert train.verified_model_path(tmp_path / "models").exists()
    with open(tmp_path / "models" / "bmtl_real_models.joblib", "ab") as fh:
        fh.write(b"tampered")
    with pytest.raises(train.ModelIntegrityError):
        train.verified_model_path(tmp_path / "models")


def test_shifted_reference_labels_are_still_excluded(tmp_path):
    """Security audit M-06: shifting a reference sample's ICP by 0.06 wt% used to slip past the 0.05 tolerance."""
    icp = pd.read_csv(train.DATA / "icp_reference.csv", dtype={"sample": str}).set_index("sample").loc["2"]
    shifted = {e: float(icp[f"{e}_wtpct"]) + 0.06 for e in ("Ni", "Co", "Mn")} | {"Li": float(icp["Li_wtpct"])}
    out = learning.run(_db(tmp_path, [(_gun_values("2"), shifted, "CONFIRMED", "NMC")]), dry_run=True)
    assert out["status"] == "skipped_only_reference_samples"
