"""Self-learning: improve the BMTL models over time from field readings that have a LAB result attached.

Usage:  .venv/Scripts/python.exe -m src.realmodels.learning [--records PATH] [--dry-run]

PROVENANCE AND RULES (CLAUDE.md, never relaxed by automation)
- The app records every black-mass reading as an UNLABELLED observation (app/backend/data/records/records.db).
  An observation becomes CONFIRMED only when an admin attaches that sample's ICP-OES result. Only CONFIRMED
  observations are ever used for training; unlabelled readings never become training rows and no label is
  ever inferred, invented or copied from a model prediction.
- Readings that share the same ICP result are the same physical sample: they form one group, so leave-one-
  SAMPLE-out holds them out together (no leakage between repeated readings of one bag).
- A candidate model is trained on the original real data + confirmed field rows. It is compared with a baseline
  retrained from the original data alone (same code, same run), on the ORIGINAL ICP-referenced samples held out
  leave-one-sample-out. It is promoted only if it is clearly better and nothing important gets worse:
    mean relative element error <= 0.98 of baseline, no element worse than 1.10x, lithium MAE <= 1.10x,
    detector accuracy not lower by more than 0.02.
  Otherwise the current model stays. Every run is written to learning_runs with its metrics.
- A passing candidate is only STAGED in models/candidates/<stamp>/ (security audit M-06). A person activates it with
  --activate <stamp>, which verifies its SHA-256, backs up the live model to models/history/ and copies it in;
  the app then reloads the (hash-verified) model file.
- Unlabelled readings are only summarised (counts per inferred material) to show how the field population
  drifts from the training domain; they are never fitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.realmodels import train

ROOT = train.ROOT
RECORDS = ROOT / "app" / "backend" / "data" / "records" / "records.db"
HISTORY = ROOT / "models" / "history"
ELEMENTS = train.ELEMENTS
ICP_ELEMENTS = ELEMENTS + ["Li"]
RULES = {"mean_rel_max": 0.98, "element_rel_max": 1.10, "lithium_rel_max": 1.10, "detector_drop_max": 0.02}

RUNS_SCHEMA = """CREATE TABLE IF NOT EXISTS learning_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, status TEXT NOT NULL, confirmed_rows INTEGER,
    promoted INTEGER NOT NULL DEFAULT 0, metrics TEXT, note TEXT);"""


def _db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    conn.executescript(RUNS_SCHEMA)
    return conn


def confirmed(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    try:
        rows = conn.execute("SELECT * FROM observations WHERE label_state = 'CONFIRMED' ORDER BY id").fetchall()
    except sqlite3.OperationalError:     # app never recorded anything yet
        return []
    return [dict(r) | {"observed": json.loads(r["observed"] or "{}"), "icp": json.loads(r["icp"] or "{}")} for r in rows]


def drift_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    try:
        rows = conn.execute("SELECT COALESCE(material, 'UNKNOWN') AS m, COUNT(*) AS n FROM observations "
                            "WHERE label_state = 'UNLABELLED' GROUP BY m ORDER BY n DESC").fetchall()
    except sqlite3.OperationalError:
        return {}
    return {r["m"]: r["n"] for r in rows}


def field_frames(obs: list[dict[str, Any]], pairs_columns: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """CONFIRMED observations -> rows in the xrf_icp_pairs / icp_reference formats. One group per distinct ICP result."""
    pair_rows, icp_rows = [], {}
    for o in obs:
        icp = {e: float(v) for e, v in o["icp"].items() if e in ICP_ELEMENTS}
        group = "F" + hashlib.sha256(json.dumps(sorted(icp.items())).encode()).hexdigest()[:8]
        basis = o.get("basis") if o.get("basis") in ("factory", "type_standardised") else "type_standardised"
        row: dict[str, Any] = {c: None for c in pairs_columns}
        row.update({"record_id": f"FIELD_{o['id']}_{basis}", "instrument": o.get("instrument") or "field", "reading_id": float(o["id"]),
                    "sample": group, "label_source": "CONFIRMED_FIELD", "measured_at": datetime.fromtimestamp(o["ts"]).strftime("%Y-%m-%d %H:%M:%S"),
                    "calibration_basis": basis, "source": "records.db"})
        for e in ELEMENTS:
            v = o["observed"].get(e)
            row[f"xrf_{e}"] = float(v) if v is not None else None
            row[f"xrf_{e}_lod"] = False
            row[f"xrf_{e}_reported"] = v is not None
        for e in ICP_ELEMENTS:
            row[f"icp_{e}"] = icp.get(e)
        pair_rows.append(row)
        icp_rows[group] = {"sample": group, **{f"{e}_wtpct": icp.get(e, 0.0) for e in ICP_ELEMENTS},
                           "reference": "field ICP attached by admin in ScrapTrust", "note": f"observations {o['id']}"}
    return pd.DataFrame(pair_rows, columns=pairs_columns), pd.DataFrame(list(icp_rows.values()))


def drop_reference_duplicates(obs: list[dict[str, Any]], icp: pd.DataFrame, abs_tol: float = 0.5, rel_tol: float = 0.05
                              ) -> tuple[list[dict[str, Any]], list[int]]:
    """A field label close to an original reference sample's ICP IS (or imitates) that sample: using it would put the
    held-out sample into its own training fold and inflate the candidate's score. Security audit M-06: a fixed
    0.05 wt% tolerance was bypassed by shifting values by 0.06, so "close" is now max(0.5 wt%, 5 % relative) on
    each of Ni, Co and Mn."""
    keep, dup = [], []

    def near(a: float, b: float) -> bool:
        return abs(a - b) <= max(abs_tol, rel_tol * abs(b))

    for o in obs:
        same = any(all(near(float(o["icp"].get(e, -99)), float(r[f"{e}_wtpct"])) for e in ("Ni", "Co", "Mn"))
                   for _, r in icp.iterrows())
        (dup if same else keep).append(o if not same else o["id"])
    return keep, dup


def _scores(reports: Path, original: set[str]) -> dict[str, Any]:
    ev = pd.read_csv(reports / "element_loso_predictions.csv", dtype={"sample": str})
    summ = train.summarise_elements(ev[ev["sample"].isin(original)])
    li = pd.read_csv(reports / "lithium_loso_predictions.csv", dtype={"sample": str})
    li = li[li["sample"].isin(original) & ~li["sample"].isin(train.OOD_SAMPLES)]
    det = json.loads((reports / "training_summary.json").read_text(encoding="utf-8"))["detector"]
    return {"elements": {f"{r.basis}:{r.element}": float(r.mae_selected) for r in summ.itertuples()},
            "lithium_mae": float((li.pred - li.y).abs().mean()) if len(li) else None,
            "detector_accuracy": det.get("accuracy_on_decided"), "detector_abstention": det.get("abstention_rate")}


def decide(base: dict[str, Any], cand: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    rel = {k: cand["elements"][k] / base["elements"][k] for k in base["elements"] if k in cand["elements"] and base["elements"][k] > 1e-9}
    mean_rel = sum(rel.values()) / len(rel) if rel else 1.0
    li_rel = (cand["lithium_mae"] / base["lithium_mae"]) if base.get("lithium_mae") and cand.get("lithium_mae") is not None else 1.0
    det_drop = (base.get("detector_accuracy") or 0) - (cand.get("detector_accuracy") or 0)
    checks = {"mean_relative_error": round(mean_rel, 4), "worst_element": max(rel, key=rel.get) if rel else None,
              "worst_element_relative_error": round(max(rel.values()), 4) if rel else None,
              "lithium_relative_error": round(li_rel, 4), "detector_accuracy_drop": round(det_drop, 4), "rules": RULES}
    ok = (mean_rel <= RULES["mean_rel_max"] and (max(rel.values()) if rel else 1.0) <= RULES["element_rel_max"]
          and li_rel <= RULES["lithium_rel_max"] and det_drop <= RULES["detector_drop_max"])
    return ok, checks


CANDIDATES = ROOT / "models" / "candidates"


def stage(cand_models: Path, cand_reports: Path, stamp: str, result: dict[str, Any]) -> Path:
    """Security audit M-06: a candidate that passes the gate is only STAGED; a person activates it (activate())."""
    out = CANDIDATES / stamp
    shutil.copytree(cand_models, out / "models")
    shutil.copytree(cand_reports, out / "reports")
    (out / "learning_result.json").write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    return out


def activate(stamp: str) -> Path:
    """Make a staged candidate live: verify its hash, back up the current model, then copy it in."""
    src = CANDIDATES / stamp
    if not (src / "models" / "model_card.json").exists():
        raise SystemExit(f"no staged candidate {stamp} in {CANDIDATES}")
    train.verified_model_path(src / "models")              # refuses a tampered candidate
    backup = HISTORY / datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copytree(train.MODELS, backup / "models")
    shutil.copytree(train.REPORTS, backup / "reports")
    for f in (src / "reports").iterdir():
        shutil.copy2(f, train.REPORTS / f.name)
    # card first, then the model file, so a reader never sees a new model with an old hash
    shutil.copy2(src / "models" / "model_card.json", train.MODELS / "model_card.json")
    shutil.copy2(src / "models" / "bmtl_real_models.joblib", train.MODELS / "bmtl_real_models.joblib")
    train.verified_model_path(train.MODELS)
    return backup


def run(records: Path = RECORDS, dry_run: bool = False) -> dict[str, Any]:
    conn = _db(records)
    obs = confirmed(conn)
    drift = drift_summary(conn)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result: dict[str, Any] = {"confirmed_rows": len(obs), "unlabelled_by_material": drift, "promoted": False}
    if not obs:
        result |= {"status": "skipped_no_labels",
                   "note": "No readings with a lab (ICP) result yet. Unlabelled readings are never used for training."}
    else:
        pairs = pd.read_csv(train.DATA / "xrf_icp_pairs.csv", dtype={"sample": str})
        icp = pd.read_csv(train.DATA / "icp_reference.csv", dtype={"sample": str})
        original = set(pairs["sample"].astype(str))
        obs, duplicates = drop_reference_duplicates(obs, icp)
        result["excluded_as_reference_samples"] = duplicates
        if not obs:
            result |= {"status": "skipped_only_reference_samples",
                       "note": "All labelled readings carry the ICP of an existing reference sample; they would leak into the evaluation."}
    if obs and "status" not in result:
        field_pairs, field_icp = field_frames(obs, list(pairs.columns))
        with tempfile.TemporaryDirectory(prefix="bmtl_learning_") as tmp:
            tmp = Path(tmp)
            base_dir, cand_dir = tmp / "baseline", tmp / "candidate"
            for d in (base_dir, cand_dir):
                shutil.copytree(train.DATA, d / "data")
            pd.concat([pairs, field_pairs], ignore_index=True).to_csv(cand_dir / "data" / "xrf_icp_pairs.csv", index=False)
            pd.concat([icp, field_icp], ignore_index=True).to_csv(cand_dir / "data" / "icp_reference.csv", index=False)
            for d in (base_dir, cand_dir):
                train.run(data=d / "data", models_dir=d / "models", reports_dir=d / "reports", aug_dir=d / "augmented")
            base, cand = _scores(base_dir / "reports", original), _scores(cand_dir / "reports", original)
            ok, checks = decide(base, cand)
            result |= {"field_samples": int(field_pairs["sample"].nunique()), "baseline": base, "candidate": cand, "checks": checks}
            if ok and not dry_run:
                staged = stage(cand_dir / "models", cand_dir / "reports", stamp, result)
                field_pairs.to_csv(staged / "field_pairs.csv", index=False)
                field_icp.to_csv(staged / "field_icp.csv", index=False)
                result |= {"status": "candidate_ready", "candidate": stamp,
                           "note": f"Candidate beat the current model on the original held-out samples. Review it, then activate with: "
                                   f"python -m src.realmodels.learning --activate {stamp}"}
            else:
                result |= {"status": "dry_run" if dry_run else "kept_current",
                           "note": "Candidate not promoted: " + ("dry run." if dry_run else "it did not clearly beat the current model.")}
    conn.execute("INSERT INTO learning_runs(ts, status, confirmed_rows, promoted, metrics, note) VALUES (?,?,?,?,?,?)",
                 (time.time(), result["status"], len(obs), int(result["promoted"]), json.dumps(result, default=str), result["note"]))
    conn.commit()
    conn.close()
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--records", type=Path, default=RECORDS)
    ap.add_argument("--dry-run", action="store_true", help="evaluate a candidate but never stage it")
    ap.add_argument("--activate", metavar="STAMP", help="make a staged candidate (models/candidates/STAMP) the live model")
    args = ap.parse_args()
    if args.activate:
        backup = activate(args.activate)
        print(f"activated candidate {args.activate}; previous model backed up to {backup.relative_to(ROOT)}")
        return
    out = run(args.records, args.dry_run)
    print(json.dumps({k: v for k, v in out.items() if k not in ("baseline", "candidate")}, indent=2, default=str))


if __name__ == "__main__":
    main()
