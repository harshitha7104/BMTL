"""Unstructured-input extraction, compound naming and augmentation leakage (real ACE files)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.realdata.extract import pair_ocr_boxes, parse_header, parse_value, readings_for_file, readings_from_text
from src.realmodels.compound import name_compound

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "ace_company"


def test_headers_and_values():
    assert parse_header("Ni_wtpct") == ("Ni", 1.0)
    assert parse_header("Nickel (%)")[0] == "Ni"
    assert parse_header("Co_mgkg") == ("Co", 1e-4)
    el, f = parse_header("Al2O3")
    assert el == "Al" and abs(f - 0.5293) < 1e-3
    assert parse_header("Ni Err")[0] is None and parse_header("Ni_below_LOD")[0] is None
    assert parse_value("< LOD") == (None, True) and parse_value("<0.100%") == (None, True) and parse_value("ND") == (None, True)
    assert parse_value("12.5 %") == (12.5, False) and parse_value("+ 10.96 %")[0] == 10.96


def test_bruker_results_csv_with_repeated_headers():
    readings = readings_for_file((RAW / "bruker_s1titan" / "Results.csv").read_bytes(), "Results.csv")
    assert len(readings) == 36
    r = next(x for x in readings if x["label"] == "1287")            # sample A, 26 Oct
    assert r["values"]["Co"] == pytest.approx(15.0167)
    assert "MgO" not in r["values"] and "Mg" in r["below_lod"]       # "< LOD" stays censored


def test_company_workbook_transposed_is_read_as_icp():
    wb = next((RAW / "icp_reference").glob("*90s_120s*.xlsx"))
    readings = readings_for_file(wb.read_bytes(), wb.name)
    assert readings and any(r["basis_hint"] == "icp" for r in readings)


def test_json_any_shape():
    doc = {"lot": "B-1", "readings": [{"sample": "S1", "Nickel": "18.6 %", "Co": 7.9, "Mn (wt%)": 9.1, "Fe": "<LOD"}]}
    r = readings_for_file(json.dumps(doc).encode(), "x.json")
    assert r[0]["label"] == "S1" and r[0]["values"]["Ni"] == 18.6 and r[0]["below_lod"] == ["Fe"]


def test_free_text_and_pdf_report_text():
    r = readings_from_text("The gun said nickel 18.1%, Co: 7.9 and Mn = 9.2 wt%, iron < LOD")
    assert r[0]["values"] == {"Ni": 18.1, "Co": 7.9, "Mn": 9.2} and r[0]["below_lod"] == ["Fe"]
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(str(RAW / "bruker_s1titan" / "Instrument Results.pdf"))
    text = "\n".join(p.extract_text() for p in reader.pages)
    readings = readings_from_text(text, "Instrument Results.pdf")
    assert len(readings) == 9                                          # one per .pdz measurement
    assert readings[0]["values"]["Co"] == pytest.approx(15.02)


def test_ocr_pairing_never_assigns_unlabelled_numbers():
    boxes = [(160, 690, "Cu", 0.9), (320, 670, "3.54 %", 0.9), (300, 720, "± 0.04", 0.9),
             (160, 800, "Zn", 0.9), (240, 780, "<", 0.9), (300, 780, "0.100%", 0.9),
             (640, 670, "10.96", 0.9),                                  # its label tile was not read
             (490, 808, "Fe", 0.9), (638, 786, "0.223", 0.9)]
    out = pair_ocr_boxes(boxes, 1600)
    assert out["values"] == {"Cu": 3.54, "Fe": 0.223}
    assert out["below_lod"] == ["Zn"] and 10.96 in out["unlabelled_values"]
    bad = pair_ocr_boxes([(100, 100, "Pb", 0.9), (200, 100, "91", 0.9), (100, 200, "Sn", 0.9), (200, 200, "84", 0.9)], 1600)
    assert bad["plausible"] is False                                   # 175 % in one sample is impossible


@pytest.mark.parametrize("comp,expected", [
    ({"Ni": 26.47, "Co": 4.93, "Mn": 1.90, "Al": 1.41}, "NMC811"),
    ({"Fe": 17.22, "P": 13.04, "Ni": 0.39, "Co": 0.19, "Mn": 0.73}, "LFP"),
    ({"Co": 57.8, "Ni": 0.51, "Mn": 0.29}, "LCO"),
    ({"Ni": 18.65, "Co": 6.91, "Mn": 7.60}, "NMC622"),
])
def test_compound_names(comp, expected):
    assert name_compound(comp)["name"].startswith(expected)


def test_compound_unknown_without_metals():
    assert name_compound({"Ni": 0, "Co": 0})["state"] == "UNKNOWN"


@pytest.mark.skipif(not (ROOT / "data" / "processed" / "real" / "xrf_icp_pairs.csv").exists(), reason="build dataset first")
def test_augmentation_is_labelled_and_leak_free():
    from src.realmodels.augment import augment, drop_parents
    pairs = pd.read_csv(ROOT / "data" / "processed" / "real" / "xrf_icp_pairs.csv", dtype={"sample": str})
    aug = augment(pairs, n_replicates=3, n_blends_per_row=3)
    assert (aug.label_source == "AUGMENTED").all() and aug.data_origin.str.contains("not a measurement").all()
    assert not aug["sample"].eq("6").any()                             # out-of-domain sample never augmented
    kept = drop_parents(aug, "B")
    assert not kept["parents"].astype(str).str.split("|").apply(lambda p: "B" in p).any()
    assert len(kept) < len(aug)
