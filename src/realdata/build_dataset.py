"""Build the REAL-data BMTL dataset from the ACE company files.

Usage:  .venv/Scripts/python.exe -m src.realdata.build_dataset

PROVENANCE: every input is a genuine company file under data/raw/ace_company/
(checksummed in SHA256SUMS). Nothing is simulated. Outputs go to data/processed/real/.

What is produced:
  bruker_readings_long.csv   every S1 TITAN reading x analyte (Results.csv), "< LOD" kept censored
  bruker_pdz_results.csv     26-Oct .pdz element results: factory AND type-standardised values
  bruker_spectra.npz         26-Oct raw spectra: 9 readings x 3 phases x 2048 channels
  icp_reference.csv          ICP master values (wt%) for samples A,B,C,1-6 (+ secondary source)
  reading_labels.csv         reading -> sample label with label_source and confidence
  xrf_icp_pairs.csv          training table: one row per (labelled reading), XRF features + ICP targets
  xsort_readings.csv         SPECTRO xSORT handheld readings (transcribed from photos) + material class
  company_model_outputs.csv  outputs of the company's earlier BMTL v0.2.1 (comparison only, never a target)
  dataset_card.json          counts, sources, caveats (computed, not hand-written)

Labelling rules (no label is ever invented):
  CONFIRMED  readings 839-847 (26 Oct): Bruker's own report maps .pdz 01287-01295 to samples
             A,B,C,1,2,3,4,5,6 (Results _New.pdf, pages 6-10); 120 s gun values come from the
             company workbook.
  MATCHED    19-Oct readings whose composition (centred log-ratio of Co,Ni,Mn,Fe,Cu,P, same
             calibration basis) is within MATCH_MAX_DIST of exactly one sample and at least
             MATCH_MIN_MARGIN closer than the runner-up. Thresholds are ~5x the observed
             90 s vs 120 s replicate distance (0.03-0.09).
  AMBIGUOUS  close to two compositional twins (1|3, 4|5): kept as candidates, never trained on.
  UNLABELLED everything else.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.realdata.bruker_csv import read_results_csv
from src.realdata.icp_xlsx import icp_reference, read_icp_workbook
from src.realdata.pdz import read_pdz

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "ace_company"
OUT = ROOT / "data" / "processed" / "real"
WORKBOOK = RAW / "icp_reference" / "BMTL_Output_vs_ICP_90s_120s_29Oct2026 R2.xlsx"
XSORT = ROOT / "data" / "interim" / "real" / "xsort_transcription.csv"

BRUKER_REPORT_MAP = {839: "A", 840: "B", 841: "C", 842: "1", 843: "2", 844: "3", 845: "4", 846: "5", 847: "6"}
# "Shared Composition" table sent to Bruker (Results _New.pdf p.4), rounded to 2 dp; secondary source only.
SHARED_ICP = {"A": {"P": 0.26, "Ni": 1.65, "Fe": 1.30, "Co": 14.30, "Mg": 0.40, "Mn": 10.59, "Cu": 2.99, "Al": 5.51},
              "B": {"P": 1.74, "Ni": 26.47, "Fe": 0.66, "Co": 4.93, "Mg": 0.07, "Mn": 1.90, "Cu": 2.45, "Al": 1.41},
              "C": {"P": 13.04, "Ni": 0.39, "Fe": 17.22, "Co": 0.19, "Mg": 0.11, "Mn": 0.73, "Cu": 3.02, "Al": 1.37},
              "1": {"P": 0.45, "Ni": 1.90, "Fe": 0.08, "Co": 29.41, "Mg": 0.09, "Mn": 2.96, "Cu": 0.94, "Al": 1.03},
              "2": {"P": 0.46, "Ni": 10.61, "Fe": 1.07, "Co": 11.38, "Mg": 0.10, "Mn": 15.34, "Cu": 1.20, "Al": 0.76},
              "3": {"P": 0.55, "Ni": 1.90, "Fe": 0.07, "Co": 33.74, "Mg": 0.17, "Mn": 2.75, "Cu": 0.81, "Al": 0.87}}
MATCH_ELEMENTS = ["Co", "Ni", "Mn", "Fe", "Cu", "P"]
MATCH_MAX_DIST, MATCH_MIN_MARGIN = 0.5, 0.3
TARGETS = ["Ni", "Co", "Mn", "Fe", "Cu", "Al", "P", "Li"]
XRF_FEATURES = ["Ni", "Co", "Mn", "Fe", "Cu", "Al", "P", "Si", "S", "Ca", "Ti", "Cr", "Zn", "Mg"]


def _clr(frame: pd.DataFrame) -> np.ndarray:
    x = np.log(frame.clip(lower=0.05).to_numpy(dtype=float))
    return x - x.mean(axis=1, keepdims=True)


def _oxide_to_element(analyte: str, value: float | None) -> tuple[str, float | None]:
    """Al2O3/SiO2/MgO/K2O -> element wt% with exact stoichiometric factors."""
    factors = {"Al2O3": ("Al", 2 * 26.9815 / 101.9613), "SiO2": ("Si", 28.0855 / 60.0843), "MgO": ("Mg", 24.305 / 40.3044), "K2O": ("K", 2 * 39.0983 / 94.196)}
    if analyte in factors:
        element, f = factors[analyte]
        return element, None if value is None else value * f
    return analyte, value


def load_pdz() -> tuple[pd.DataFrame, dict]:
    rows, spectra = [], {}
    for path in sorted(glob.glob(str(RAW / "bruker_s1titan" / "pdz_90s" / "*.pdz"))):
        f = read_pdz(path)
        rid = int(f.strings[f.strings.index("ID") + 1])
        spectra[rid] = np.stack([p.counts for p in sorted(f.phases, key=lambda p: p.index)])
        for e in f.elements.values():
            element, factory = _oxide_to_element(e.name, e.factory_pct)
            _, standardised = _oxide_to_element(e.name, e.standardised_pct)
            rows.append({"reading_id": rid, "pdz_file": Path(path).name, "analyte": e.name, "element": element, "factory_pct": factory,
                         "standardised_pct": None if e.below_lod else standardised, "below_lod": e.below_lod, "sigma_pct": e.sigma_pct})
        kv = [p.kv for p in sorted(f.phases, key=lambda p: p.index)]
        spectra[f"{rid}_kv"] = np.array(kv)
    return pd.DataFrame(rows), spectra


def label_readings(long: pd.DataFrame, pdz: pd.DataFrame) -> pd.DataFrame:
    wide = long.assign(element=[_oxide_to_element(a, v)[0] for a, v in zip(long.analyte, long.value_pct)],
                       value=[_oxide_to_element(a, v)[1] for a, v in zip(long.analyte, long.value_pct)])
    meta = long.groupby("reading_id").agg(measured_at=("measured_at", "first"), method=("method", "first"), application=("application", "first"),
                                           type_standardised=("type_standardised", "first"), elapsed_s=("elapsed_s", "first")).reset_index()
    comp = wide.pivot_table(index="reading_id", columns="element", values="value", aggfunc="first").reindex(columns=MATCH_ELEMENTS).fillna(0.0)
    ref_std = comp.loc[list(BRUKER_REPORT_MAP)].rename(index=BRUKER_REPORT_MAP)
    ref_fac = pdz.pivot_table(index="reading_id", columns="element", values="factory_pct").reindex(columns=MATCH_ELEMENTS).fillna(0.0).rename(index=BRUKER_REPORT_MAP)
    rows = []
    for _, m in meta.iterrows():
        rid = int(m.reading_id)
        if rid in BRUKER_REPORT_MAP:
            rows.append({**m, "sample": BRUKER_REPORT_MAP[rid], "label_source": "CONFIRMED", "basis": "type_standardised",
                         "match_distance": 0.0, "match_margin": None, "candidates": BRUKER_REPORT_MAP[rid],
                         "evidence": "Bruker report Results _New.pdf maps .pdz 01287-01295 to A,B,C,1-6"})
            continue
        if m.method == "OxideConcentrates":
            ref, basis = (ref_std, "type_standardised") if m.type_standardised else (ref_fac, "factory")
        else:
            ref, basis = ref_std, "cross_application_ratio"   # Li-Elements application vs OxideConcentrates reference: ratios only
        dist = np.linalg.norm(_clr(ref) - _clr(comp.loc[[rid]]), axis=1)
        order = np.argsort(dist)
        best, second = ref.index[order[0]], ref.index[order[1]]
        d0, d1 = float(dist[order[0]]), float(dist[order[1]])
        if d0 <= MATCH_MAX_DIST and d1 - d0 >= MATCH_MIN_MARGIN and basis != "cross_application_ratio":
            source, sample, cands = "MATCHED", best, best
        elif d0 <= MATCH_MAX_DIST and basis != "cross_application_ratio":
            source, sample, cands = "AMBIGUOUS", None, "|".join(sorted([best, second]))
        else:
            source, sample, cands = "UNLABELLED", None, None
        rows.append({**m, "sample": sample, "label_source": source, "basis": basis, "match_distance": round(d0, 3), "match_margin": round(d1 - d0, 3),
                     "candidates": cands, "evidence": f"nearest {best} ({d0:.2f}), next {second} ({d1:.2f}); clr over {','.join(MATCH_ELEMENTS)}"})
    return pd.DataFrame(rows)


def build_pairs(long: pd.DataFrame, pdz: pd.DataFrame, labels: pd.DataFrame, icp: pd.DataFrame, workbook: pd.DataFrame) -> pd.DataFrame:
    """One row per labelled XRF measurement with ICP targets. Censored -> NaN plus a *_lod flag (never 0)."""
    rows = []
    elem = long.assign(element=[_oxide_to_element(a, v)[0] for a, v in zip(long.analyte, long.value_pct)],
                       value=[_oxide_to_element(a, v)[1] for a, v in zip(long.analyte, long.value_pct)])
    for _, lab in labels[labels.label_source.isin(["CONFIRMED", "MATCHED"])].iterrows():
        sub = elem[elem.reading_id == lab.reading_id]
        rec = {"record_id": f"S1T_{int(lab.reading_id)}", "instrument": "Bruker S1 TITAN 800", "reading_id": int(lab.reading_id), "sample": lab["sample"],
               "label_source": lab.label_source, "measured_at": lab.measured_at, "dwell_s": lab.elapsed_s, "calibration_basis": lab.basis,
               "source": "Results.csv"}
        for e in XRF_FEATURES:
            hit = sub[sub.element == e]
            rec[f"xrf_{e}"] = float(hit.value.iloc[0]) if len(hit) and pd.notna(hit.value.iloc[0]) else np.nan
            rec[f"xrf_{e}_lod"] = bool(len(hit) and hit.below_lod.iloc[0])
            rec[f"xrf_{e}_reported"] = bool(len(hit))
        rows.append(rec)
        if lab.label_source == "CONFIRMED":   # the same 26-Oct shot, factory calibration (from .pdz): a second, un-standardised view
            fac = pdz[pdz.reading_id == lab.reading_id]
            rec2 = {**rec, "record_id": f"S1T_{int(lab.reading_id)}_factory", "calibration_basis": "factory", "source": "pdz"}
            for e in XRF_FEATURES:
                hit = fac[fac.element == e]
                rec2[f"xrf_{e}"] = float(hit.factory_pct.iloc[0]) if len(hit) and hit.factory_pct.iloc[0] > 0 else np.nan
                rec2[f"xrf_{e}_lod"] = bool(len(hit) and hit.factory_pct.iloc[0] == 0)
                rec2[f"xrf_{e}_reported"] = bool(len(hit))
            rows.append(rec2)
    # 120 s gun set (pdz 01305-01313 not supplied): type-standardised values from the company workbook
    g120 = workbook[workbook.column == "Gun 120 s"].pivot_table(index="sample", columns="element", values="value", aggfunc="first")
    for sample, values in g120.iterrows():
        rec = {"record_id": f"S1T_120s_{sample}", "instrument": "Bruker S1 TITAN 800", "reading_id": None, "sample": sample, "label_source": "CONFIRMED",
               "measured_at": "2026-10-28", "dwell_s": 120.0, "calibration_basis": "type_standardised", "source": "workbook Gun 120 s"}
        for e in XRF_FEATURES:
            v = values.get(e, np.nan)
            rec[f"xrf_{e}"] = float(v) if pd.notna(v) else np.nan
            rec[f"xrf_{e}_lod"] = bool(pd.isna(v) and e in g120.columns)   # workbook: blank = "not detected"
            rec[f"xrf_{e}_reported"] = e in g120.columns
        rows.append(rec)
    pairs = pd.DataFrame(rows)
    for t in TARGETS:
        pairs[f"icp_{t}"] = pairs["sample"].map(icp[t])
    return pairs


def build_xsort() -> pd.DataFrame:
    x = pd.read_csv(XSORT, dtype={"bag_label": str})
    def material_class(row) -> str:
        text = f"{row.material_on_bag} {row.bag_label}".lower()
        if "lithium carbonate" in text:
            return "lithium_carbonate"
        if "battery paste" in text or "lead" in text:
            return "lead_acid_or_lead"
        if row.analysis_note == "alloy_grade_pattern":
            return "black_mass_alloy_mode_artifact"
        return "black_mass_nmc_declared" if "nmc" in text else "black_mass_undeclared"
    x["material_class"] = x.apply(material_class, axis=1)
    x["usable_reading"] = (x.screen_state == "complete") & (x.material_class != "black_mass_alloy_mode_artifact")
    x["instrument"] = "SPECTRO xSORT (Precious Metals mode)"
    x["source"] = "photo transcription (data/raw/ace_company/xsort_handheld_photos), verify against originals"
    return x


def run(out: Path = OUT) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    long = read_results_csv(RAW / "bruker_s1titan" / "Results.csv")
    pdz, spectra = load_pdz()
    workbook = read_icp_workbook(WORKBOOK)
    icp = icp_reference(WORKBOOK)
    labels = label_readings(long, pdz)
    pairs = build_pairs(long, pdz, labels, icp, workbook)
    xsort = build_xsort()

    secondary = pd.DataFrame(SHARED_ICP).T
    icp_out = icp.copy()
    icp_out.columns = [f"{c}_wtpct" for c in icp_out.columns]
    for e in ["Ni", "Co", "Mn", "Fe", "Cu", "Al", "P"]:
        icp_out[f"{e}_shared_table"] = secondary[e].reindex(icp_out.index)
        icp_out[f"{e}_sources_disagree"] = (icp_out[f"{e}_wtpct"] - icp_out[f"{e}_shared_table"]).abs() > 0.15
    icp_out["reference"] = "in-house master ICP (workbook); shared_table = values sent to Bruker (secondary)"
    icp_out["note"] = ""
    icp_out.loc["6", "note"] = "lot A-17KGVER, Co 57.8% - excluded by the company from its own test; treated as out-of-domain"

    long.to_csv(out / "bruker_readings_long.csv", index=False)
    pdz.to_csv(out / "bruker_pdz_results.csv", index=False)
    np.savez_compressed(out / "bruker_spectra.npz", **{str(k): v for k, v in spectra.items()})
    icp_out.to_csv(out / "icp_reference.csv", index_label="sample")
    labels.to_csv(out / "reading_labels.csv", index=False)
    pairs.to_csv(out / "xrf_icp_pairs.csv", index=False)
    xsort.to_csv(out / "xsort_readings.csv", index=False)
    company = workbook[workbook.column.str.startswith(("BMTL", "Diff"))]
    company.to_csv(out / "company_model_outputs.csv", index=False)

    card = {
        "dataset": "bmtl_real_ace_2026_10", "data_origin": "REAL (company-supplied)", "built_from": str(RAW.relative_to(ROOT)),
        "bruker_readings": int(long.reading_id.nunique()),
        "reading_labels": labels.label_source.value_counts().to_dict(),
        "icp_samples": sorted(icp.index.tolist()),
        "training_pairs": int(len(pairs)), "pairs_by_basis": pairs.calibration_basis.value_counts().to_dict(),
        "pairs_by_sample": pairs["sample"].value_counts().sort_index().to_dict(),
        "xsort_readings": int(len(xsort)), "xsort_by_class": xsort.material_class.value_counts().to_dict(),
        "spectra": {"readings": len([k for k in spectra if isinstance(k, int)]), "phases": 3, "channels": 2048},
        "caveats": [
            "Only 9 physical samples have ICP; every metric is a small-sample estimate (leave-one-sample-out).",
            "Bruker received ICP for A,B,C,1,2,3 before the 26-Oct run and its 'Black mass powder' type standardisation was created "
            "on 19 Oct (readings >= 806); standardised gun values may be partly fitted to these samples. Factory-calibration values from the .pdz are the clean view.",
            "Samples 1 and 3, and 4 and 5, are compositional twins; their 19-Oct readings cannot be told apart and are not used.",
            "Sample A: in-house ICP and the table sent to Bruker disagree (Ni, Al, P); in-house is the reference by user decision.",
            "Sample 6 (Co 57.8%) lies outside the black-mass range of the others.",
            "120 s .pdz files (01305-01313) were not supplied; 120 s values come from the company workbook.",
            "xSORT readings were transcribed by hand from photos; folders 9-14 (readings 34-39) are missing; some screens were mid-measurement.",
            "Lithium: ICP Li exists for the 9 samples; XRF cannot measure Li. Li estimation from XRF metals is allowed by user decision (2026-11-16) and is always INFERRED.",
        ],
    }
    (out / "dataset_card.json").write_text(json.dumps(card, indent=2, default=str) + "\n", encoding="utf-8")
    return card


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
