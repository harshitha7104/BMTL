"""Predict new spectra with the fitted model.

Input: a CSV/XLSX file whose first column is wavelength (µm or nm, detected
automatically) and whose other columns are reflectance spectra (0–1).

    python predict.py data\\example_new_spectrum.csv
    python predict.py my_spectra.xlsx --json results.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.data_loader import DataLoadError
from src.engine import EngineUnavailable
from src.model import ModelError
from src.predict import DEFAULT_MODEL_PATH, Predictor, predict_file, to_serialisable
from src.preprocessing import PreprocessError


def summarise(r: dict) -> str:
    level = f" / {r['support_level']} support" if r["support_level"] else ""
    lines = [f"=== {r['sample']} ===",
             f"FINAL PREDICTION   : {r['prediction']}",
             f"Type               : {r['prediction_type']}{level}"
             + (f" ({r['prediction_kind']})" if r["prediction_kind"] else ""),
             f"Evidence confidence: {r['confidence']:.2f}  (not a probability)",
             f"Evidence sources   : {', '.join(r['evidence_sources']) or 'none'}",
             f"Rule score         : {r['rule_score'] if r['rule_score'] is not None else 'n/a'}"]
    if r["group_members"]:
        lines.append("Group members      : " + ", ".join(f"{i + 1}. {m['rule']}" for i, m in enumerate(r["group_members"])))
    if r["alternatives"]:
        lines.append("Top alternatives   : " + " | ".join(f"{a['name']} [{a['label']}] ({a['evidence_confidence']:.2f})"
                                                         for a in r["alternatives"][:3]))
    if r["key_features"]:
        lines.append("Key absorptions    : " + ", ".join(f"{f['center_nm']:.0f} nm ({100 * f['depth']:.1f} %)"
                                                         for f in r["key_features"][:5]))
    if r["similar_samples"]:
        lines.append("Similar samples    : " + ", ".join(f"{n['sample']} ({n['similarity']:.3f})"
                                                         for n in r["similar_samples"][:3]))
    lines.append("Why this prediction?")
    for w in r["why"]:
        mark = {True: "+", False: "-", None: "·"}[w["contributed"]]
        val = "" if w["value"] is None else f" = {w['value']}"
        lines.append(f"  [{mark}] {w['source']}{val}: {w['detail']}")
    for w in r["warnings"]:
        lines.append(f"  ! {w}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path, help="CSV/XLSX with a wavelength column and spectrum column(s)")
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    ap.add_argument("--json", type=Path, help="also write full results to this JSON file")
    ap.add_argument("--leave-rock-out", action="store_true",
                    help="exclude each sample's own rock from similarity evidence (use for the reference CSV)")
    args = ap.parse_args(argv)
    try:
        results = predict_file(args.file, Predictor(model_path=args.model), args.leave_rock_out)
    except (DataLoadError, PreprocessError, ModelError, EngineUnavailable) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for r in results:
        print(summarise(r), end="\n\n")
    if args.json:
        args.json.write_text(json.dumps([to_serialisable(r) for r in results], indent=1, default=str), encoding="utf-8")
        print(f"Full results written to {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
