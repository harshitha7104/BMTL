"""Tests for the real-data ingestion, dataset and models (ACE company data)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.realdata.bruker_csv import read_results_csv
from src.realdata.icp_xlsx import icp_reference
from src.realdata.pdz import read_pdz

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "ace_company"
PROC = ROOT / "data" / "processed" / "real"


def test_pdz_matches_printed_report():
    f = read_pdz(RAW / "bruker_s1titan" / "pdz_90s" / "01287-GeoMining.pdz")
    assert f.serial == "800N12237"
    assert [(p.kv, p.ua) for p in f.phases] == [(30.0, 11.65), (50.0, 15.8), (15.0, 9.0)]   # Instrument Results.pdf excitation table
    assert all(p.counts.shape == (2048,) for p in f.phases)
    assert f.elements["Co"].standardised_pct == pytest.approx(15.0167, abs=1e-3)              # report: Co 15.02 +-0.04
    assert 2 * f.elements["Co"].sigma_pct == pytest.approx(0.04, abs=0.005)
    assert f.elements["MgO"].below_lod                                                         # report: MgO <LOD


def test_results_csv_keeps_lod_censored():
    d = read_results_csv(RAW / "bruker_s1titan" / "Results.csv")
    assert d.reading_id.nunique() == 36
    lod = d[d.below_lod]
    assert len(lod) > 0 and lod.value_pct.isna().all()   # never converted to 0


def test_icp_reference_values():
    icp = icp_reference(RAW / "icp_reference" / "BMTL_Output_vs_ICP_90s_120s_29Oct2026 R2.xlsx")
    assert sorted(icp.index) == ["1", "2", "3", "4", "5", "6", "A", "B", "C"]
    assert icp.loc["B", "Ni"] == pytest.approx(26.4709)
    assert icp.loc["C", "P"] == pytest.approx(13.0427)


@pytest.mark.skipif(not (PROC / "xrf_icp_pairs.csv").exists(), reason="run python -m src.realdata.build_dataset first")
def test_pairs_never_mix_labels():
    pairs = pd.read_csv(PROC / "xrf_icp_pairs.csv", dtype={"sample": str})
    labels = pd.read_csv(PROC / "reading_labels.csv", dtype={"sample": str})
    assert set(pairs.label_source) <= {"CONFIRMED", "MATCHED"}            # AMBIGUOUS / UNLABELLED never become training rows
    assert not labels[labels.label_source == "AMBIGUOUS"]["sample"].notna().any()
    assert "xrf_Li" not in pairs.columns                                   # XRF never carries lithium


@pytest.mark.skipif(not (ROOT / "models" / "real" / "bmtl_real_models.joblib").exists(), reason="run python -m src.realmodels.train first")
def test_assess_reading_labels_evidence():
    from src.realmodels.predict import assess_reading
    r = assess_reading({"Ni": 20.09, "Co": 5.52, "Mn": 8.25, "Fe": 1.22, "Cu": 1.78, "Al": 1.78, "P": 0.86}, basis="type_standardised")
    assert r["elements"]["Ni"]["observed"]["state"] == "OBSERVED"
    assert r["elements"]["Ni"]["inferred"]["state"] == "INFERRED"
    assert r["lithium"]["state"] == "INFERRED" and r["lithium"]["value_pct"] > 0
    assert r["material"]["label"] == "NMC"
    missing = assess_reading({"Co": 5.0}, basis="type_standardised")
    assert missing["elements"]["Ni"]["inferred"]["state"] == "UNKNOWN"
    assert missing["lithium"]["state"] == "UNKNOWN"
    lead = assess_reading({"Pb": 99.1, "Fe": 0.6, "Ni": 0.18, "Co": 0.14}, basis="type_standardised", instrument="xSORT")
    assert lead["material"]["label"] == "NOT_BLACK_MASS_LEAD"
