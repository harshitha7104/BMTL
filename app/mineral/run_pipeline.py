"""Run the unlabelled spectral-analysis pipeline.

Usage (from the project folder, with the virtual environment active):
    python run_pipeline.py                      # uses the CSV in this folder
    python run_pipeline.py --data path\\to\\spectra.csv --out outputs
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.data_loader import DataLoadError, build_sample_table, load_spectra
from src.evaluation import compare_with_baseline, evaluate, outcome, report_markdown
from src.model import fit_model, save_model
from src.predict import DEFAULT_MODEL_PATH, Predictor, to_serialisable
from src.preprocessing import PreprocessConfig
from src.quality import run_quality_checks
from src.visualization import plot_pca_clusters, plot_spectrum_analysis

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA = PROJECT_DIR / "68026941d4be0210cde07d8c.csv"

log = logging.getLogger("pipeline")


def setup_logging(log_dir: Path, debug: bool) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"pipeline_{datetime.now():%Y%m%d_%H%M%S}.log"
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )
    return log_file


def run_phase1(data_path: Path, out_dir: Path) -> dict:
    ds = load_spectra(data_path)
    samples = build_sample_table(ds.sample_names)
    q = run_quality_checks(ds, samples)

    out = out_dir / "phase1"
    out.mkdir(parents=True, exist_ok=True)
    samples.to_csv(out / "sample_metadata.csv", index=False)
    q["metrics"].to_csv(out / "sample_quality_metrics.csv", index=False)
    q["flags"].to_csv(out / "quality_flags.csv", index=False)
    q["replicates"].to_csv(out / "replicate_consistency.csv", index=False)
    q["cross_rock_similar"].to_csv(out / "cross_rock_replicate_like_pairs.csv", index=False)

    wr = ds.wavelength_report
    summary = {
        "source_file": ds.source_path.name,
        "n_samples": ds.n_samples,
        "n_bands": ds.n_bands,
        "wavelength": {
            "unit_detected": wr.unit_detected, "unit_reason": wr.unit_reason,
            "original_first_last": [float(ds.wavelength_original[0]), float(ds.wavelength_original[-1])],
            "min_nm": wr.min_nm, "max_nm": wr.max_nm, "modal_step_nm": wr.modal_step_nm,
            "strictly_increasing": wr.is_strictly_increasing, "duplicates": wr.n_duplicates,
            "irregular_steps": wr.irregular_steps,
        },
        "reflectance": {
            "min": float(q["metrics"]["min"].min()), "max": float(q["metrics"]["max"].max()),
            "n_nan": int(q["metrics"]["n_nan"].sum()), "n_inf": int(q["metrics"]["n_inf"].sum()),
            "n_negative": int(q["metrics"]["n_negative"].sum()), "n_above_1": int(q["metrics"]["n_above_1"].sum()),
        },
        "naming": {
            "n_rocks": int(samples["rock_id"].nunique()),
            "n_measurements": int(samples["measurement_id"].nunique()),
            "campaigns": samples["campaign"].value_counts().to_dict(),
            "surfaces": samples["surface"].value_counts().to_dict(),
            "n_unparsed": int((~samples["parsed"]).sum()),
            "ambiguous_rock_ids": sorted(samples.loc[samples["rock_id_ambiguity"] != "", "rock_id"].unique().tolist()),
        },
        "quality": {
            **q["dataset"],
            "flag_counts": q["flags"].groupby(["check", "severity"]).size().rename("n").reset_index().to_dict("records"),
            "samples_with_warning": int(q["flags"].loc[q["flags"]["severity"] == "WARNING", "sample"].nunique()),
            "samples_with_error": int(q["flags"].loc[q["flags"]["severity"] == "ERROR", "sample"].nunique()),
        },
    }
    (out / "dataset_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (out / "quality_report.md").write_text(_phase1_report(summary, samples, q), encoding="utf-8")
    log.info("Phase 1 outputs written to %s", out)
    return ds, samples, summary


def run_model(ds, samples, out_dir: Path, model_path: Path) -> list[dict]:
    cfg = PreprocessConfig()
    model, analyses = fit_model(ds, samples, cfg)
    save_model(model, model_path)
    card = {k: model[k] for k in ("version", "created", "sklearn_version", "source_file", "preprocess_config",
                                  "vector_bin_nm", "fit_level", "n_fit_units", "ood_similarity_threshold", "random_state")}
    card.update(pca_components=int(model["pca"].n_components_),
                pca_explained_variance=float(model["pca"].explained_variance_ratio_.sum()),
                kmeans_k=int(model["kmeans"].n_clusters), k_selection=model["k_table"].to_dict("records"),
                note="Unsupervised model: no labels were used or learned. Rule-based hypotheses are pseudo-labels, not ground truth.")
    (model_path.parent / "model_card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    (model_path.parent / "preprocessing_config.json").write_text(json.dumps(cfg.to_dict(), indent=2), encoding="utf-8")

    predictor = Predictor(model=model)
    results = []
    for i, name in enumerate(ds.sample_names):
        rock = model["reference"].iloc[i]["rock_id"] or name
        results.append(predictor.predict(ds.wavelength_nm, ds.reflectance[i], "nm", name, exclude_rock=rock))
    log.info("Predicted %d reference spectra (own rock excluded from similarity evidence)", len(results))

    out = out_dir
    out.mkdir(parents=True, exist_ok=True)
    rows, feat_rows = [], []
    for r in results:
        comp = r["evidence_components"] or {}
        rows.append({
            "Sample": r["sample"], "Prediction": r["prediction"], "Prediction_Type": r["prediction_type"],
            "Outcome": outcome(r), "Support_Level": r["support_level"], "Prediction_Kind": r["prediction_kind"],
            "Group_Members_Ranked": ";".join(m["rule"] for m in r["group_members"]),
            "Evidence_Confidence": r["confidence"], "Rule_Score": r["rule_score"],
            "Best_Candidate": comp.get("label"), "E_own_spectrum": comp.get("E"), "N_neighbours": comp.get("N"),
            "C_cluster": comp.get("C"), "Q_quality": comp.get("Q"),
            "Evidence_Sources": ";".join(r["evidence_sources"]),
            "Top_Alternatives": " | ".join(f"{a['name']} ({a['evidence_confidence']:.2f})" for a in r["alternatives"][:3]),
            "Cluster": (r["cluster"] or {}).get("cluster"),
            "Nearest_Other_Rock": r["similar_samples"][0]["sample"] if r["similar_samples"] else None,
            "Nearest_Similarity": r["similar_samples"][0]["similarity"] if r["similar_samples"] else None,
            "Top_Features_nm": ";".join(f"{f['center_nm']:.0f}({100 * f['depth']:.1f}%)" for f in r["spectral_features"][:5]),
            "Rule_Engine_Dominant": r["rule_engine_dominant_class"],
            "Decision_Reason": r["decision_reason"],
            "Warnings": " | ".join(w for w in r["warnings"] if not w.startswith("Atmospheric")),
        })
        for f in r["spectral_features"]:
            feat_rows.append({"Sample": r["sample"], **f})
    pred_df = pd.DataFrame(rows)
    pred_df.to_csv(out / "predictions.csv", index=False)
    baseline = out / "baseline_v1_predictions.csv"
    if baseline.is_file():
        (out / "comparison_vs_v1.md").write_text(compare_with_baseline(pred_df, pd.read_csv(baseline)),
                                                 encoding="utf-8")
    pd.DataFrame(feat_rows).to_csv(out / "absorption_features.csv", index=False)
    (out / "predictions.json").write_text(json.dumps([to_serialisable(r) for r in results], indent=1, default=str),
                                          encoding="utf-8")

    ev = evaluate(model, analyses, results)
    (out / "model_evaluation.md").write_text(report_markdown(ev), encoding="utf-8")
    fig = plot_pca_clusters(model)
    fig.savefig(out / "pca_clusters.png", dpi=130)
    first = results[0]
    fig = plot_spectrum_analysis(first["_analysis"], f"{first['sample']}: {first['prediction']}",
                                 original=(ds.wavelength_nm, ds.reflectance[0]))
    fig.savefig(out / "example_spectrum_features.png", dpi=130)
    log.info("Model outputs written to %s and %s", out, model_path.parent)
    return results


def _phase1_report(s: dict, samples: pd.DataFrame, q: dict) -> str:
    wl, rf, nm, qd = s["wavelength"], s["reflectance"], s["naming"], s["quality"]
    flags = q["flags"]
    lines = [
        "# Phase 1 — Dataset quality report", "",
        f"Source: `{s['source_file']}` (read-only; never modified)", "",
        "## Structure",
        f"- Spectra (sample columns): **{s['n_samples']}**",
        f"- Wavelength bands: **{s['n_bands']}**",
        f"- Wavelength unit detected: **{wl['unit_detected']}** — {wl['unit_reason']}",
        f"- Range: {wl['min_nm']:.1f}–{wl['max_nm']:.1f} nm; modal step {wl['modal_step_nm']} nm; "
        f"strictly increasing: {wl['strictly_increasing']}; duplicates: {wl['duplicates']}",
        "- Irregular steps in the wavelength grid (candidate detector joins):",
        *[f"  - {x['from_nm']:.2f} → {x['to_nm']:.2f} nm (step {x['step_nm']} nm)" for x in wl["irregular_steps"]],
        f"- Bands below the engine's 400 nm limit: {qd['bands_below_engine_range']} "
        "(retained here; handled explicitly in Phase 2)", "",
        "## Values",
        f"- Reflectance range: {rf['min']:.4f}–{rf['max']:.4f}",
        f"- NaN: {rf['n_nan']}, infinite: {rf['n_inf']}, negative: {rf['n_negative']}, >1: {rf['n_above_1']}", "",
        "## Sample naming (structure only — not mineralogy)",
        f"- Rocks (physical samples): {nm['n_rocks']}; measurement groups (rock + surface spot): {nm['n_measurements']}",
        f"- Campaign prefixes: {nm['campaigns']}",
        f"- Surface types: {nm['surfaces']} (`f`/`w` read as fresh/weathered — an assumption from naming)",
        f"- Names not matching the pattern: {nm['n_unparsed']}",
        f"- Rock IDs differing only by a trailing letter (user decision needed): {nm['ambiguous_rock_ids']}", "",
        "## Edge-region noise (median over spectra, vs adjacent 50 nm on same detector)",
        *[f"- {k.replace('_', '–')} nm: {v:.1f}x" for k, v in qd["edge_noise_ratio_median"].items()], "",
        "## Detector-join (splice) steps",
        *[f"- {k}: statistically detectable in {v['n_statistically_detectable']} spectra; largest step "
          f"{v['max_abs_step']:.5f} reflectance ({100 * v['max_relative_step']:.2f}% of mean); "
          f"material (>0.5% of mean) in {v['n_flagged_material']}" for k, v in qd["splice"].items()],
        "",
        "## Replicate structure",
        f"- Median spectral angle between technical replicates: {qd['replicate_angle_median_rad']:.4f} rad",
        f"- Median spectral angle between different rocks: {qd['different_rock_angle_median_rad']:.4f} rad",
        f"- Replicate-outlier threshold (Q3 + 3·IQR): {qd['replicate_outlier_cut_rad']:.4f} rad",
        f"- Different-rock pairs closer than the median replicate pair: {len(q['cross_rock_similar'])} "
        "(see `cross_rock_replicate_like_pairs.csv`)", "",
        "## Flags (nothing was removed or altered)",
    ]
    if flags.empty:
        lines.append("- none")
    else:
        for (check, sev), grp in flags.groupby(["check", "severity"]):
            lines.append(f"- **{check}** [{sev}]: {grp['sample'].nunique()} sample(s)")
            for _, r in grp.head(8).iterrows():
                lines.append(f"  - {r['sample']}: {r['detail']}")
            if len(grp) > 8:
                lines.append(f"  - … {len(grp) - 8} more in `quality_flags.csv`")
    material_splice = sum(v["n_flagged_material"] for v in qd["splice"].values())
    decisions = ["whether rock IDs differing by a trailing letter are one rock: "
                 f"{nm['ambiguous_rock_ids'] or 'none'}",
                 "whether flagged (low-albedo / replicate-inconsistent) spectra stay in the interpretation"]
    if material_splice:
        decisions.insert(0, f"splice-step correction ({material_splice} material step(s) found)")
    lines += ["", "## What can be corrected automatically vs needs a decision",
              "- Safe/automatic (later phases, applied to a *copy*): µm→nm conversion; restricting engine input to ≥400 nm.",
              *([] if material_splice else ["- Splice correction: not needed — no step exceeds 0.5% of mean reflectance."]),
              "- Needs your decision:", *[f"  - {d}" for d in decisions], ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="spectral CSV/XLSX file")
    parser.add_argument("--out", type=Path, default=PROJECT_DIR / "outputs", help="output folder")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH, help="where to save the fitted model")
    parser.add_argument("--debug", action="store_true", help="show full Python tracebacks")
    args = parser.parse_args(argv)

    log_file = setup_logging(PROJECT_DIR / "logs", args.debug)
    try:
        ds, samples, _ = run_phase1(args.data, args.out)
        run_model(ds, samples, args.out, args.model)
    except DataLoadError as exc:
        log.error("%s", exc)
        return 2
    except Exception as exc:
        if args.debug:
            raise
        log.error("Unexpected error: %s (re-run with --debug for details; log: %s)", exc, log_file)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
