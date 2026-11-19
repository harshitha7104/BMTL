"""
Black-mass XRF engine: bridges the Copilot to BMTL's real-data models.

The models live in the BMTL repository root (this app sits in ``<BMTL>/app``):
  src/realdata/pdz.py          Bruker S1 TITAN .pdz reader
  src/realmodels/predict.py    element correction + bands, LiX lithium, material detector
  models/real/                 fitted models (trained on 9 ICP-referenced ACE samples)

Every result keeps BMTL's evidence labels: OBSERVED (gun value), INFERRED (model
estimate with a 90 % band), UNKNOWN (not supportable). Nothing is invented.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.config import REPO_ROOT

BMTL_ROOT = REPO_ROOT.parent
OXIDE_TO_ELEMENT = {"Al2O3": ("Al", 2 * 26.9815 / 101.9613), "SiO2": ("Si", 28.0855 / 60.0843), "MgO": ("Mg", 24.305 / 40.3044)}


class BlackMassEngineUnavailable(RuntimeError):
    """The BMTL models are missing (run src.realdata.build_dataset and src.realmodels.train)."""


class BlackMassEngine:
    def __init__(self, bmtl_root: Path = BMTL_ROOT) -> None:
        self.root = Path(bmtl_root)
        self._models: Optional[dict] = None
        self._models_mtime: float = 0.0

    def _import(self):
        if str(self.root) not in sys.path:
            sys.path.insert(0, str(self.root))
        try:
            from src.realdata.pdz import read_pdz
            from src.realmodels.predict import assess_reading, load_models
        except ImportError as exc:  # pragma: no cover - depends on deployment
            raise BlackMassEngineUnavailable(f"BMTL model code not importable from {self.root}: {exc}") from exc
        model_file = self.root / "models" / "real" / "bmtl_real_models.joblib"
        if not model_file.exists():
            raise BlackMassEngineUnavailable(f"model file missing: {model_file} (run python -m src.realmodels.train in {self.root})")
        mtime = model_file.stat().st_mtime
        if self._models is None or mtime != self._models_mtime:   # an activated new model is picked up live
            import joblib

            from src.realmodels.train import ModelIntegrityError, verified_model_path

            try:
                verified = verified_model_path(model_file.parent)   # audit L-12: never unpickle an unverified file
            except (ModelIntegrityError, OSError, ValueError) as exc:
                raise BlackMassEngineUnavailable(str(exc)) from exc
            self._models = joblib.load(verified)
            self._models_mtime = mtime
        return read_pdz, assess_reading

    def assess_values(self, values: Dict[str, Any], basis: str, instrument: str = "S1 TITAN") -> Dict[str, Any]:
        _, assess_reading = self._import()
        clean = {k: (None if v is None or v == "" else float(v)) for k, v in values.items()}
        below = {k for k, v in values.items() if isinstance(v, str) and v.strip().upper().replace(" ", "") == "<LOD"}
        return assess_reading(clean, basis=basis, instrument=instrument, below_lod=below, models=self._models)

    def assess_pdz(self, path: str) -> Dict[str, Any]:
        read_pdz, assess_reading = self._import()
        f = read_pdz(path)
        factory, standardised, lod = {}, {}, set()
        for e in f.elements.values():
            name, factor = OXIDE_TO_ELEMENT.get(e.name, (e.name, 1.0))
            factory[name] = e.factory_pct * factor if e.factory_pct > 0 else None
            standardised[name] = e.standardised_pct * factor if not e.below_lod else None
            if e.below_lod:
                lod.add(name)
        reading_id = f.strings[f.strings.index("ID") + 1] if "ID" in f.strings else None
        return {
            "file": Path(path).name,
            "instrument": f"Bruker S1 TITAN (serial {f.serial})",
            "reading_id": reading_id,
            "excitation": [{"kv": p.kv, "ua": p.ua, "total_counts": int(p.counts.sum())} for p in f.phases],
            "factory_calibration": assess_reading(factory, basis="factory", models=self._models),
            "type_standardised": assess_reading(standardised, basis="type_standardised", below_lod=lod, models=self._models),
            "note": "Two views of the same shot. 'factory' is the instrument's factory calibration; 'type_standardised' is Bruker's "
                    "'Black mass powder' standardisation, which may already be partly fitted to the ACE reference samples.",
        }

    # ------------------------------------------------------------ any input
    def _extract(self):
        self._import()
        from src.realdata import extract
        return extract

    def table_readings(self, data: bytes, filename: str) -> list:
        """Element readings in a CSV/TSV/XLSX/JSON table (any column naming, either orientation)."""
        return self._extract().readings_for_file(data, filename)

    def looks_like_table(self, data: bytes, filename: str) -> bool:
        try:
            return bool(self.table_readings(data, filename))
        except Exception:   # malformed input is simply "not an element table"
            return False

    def assess_readings(self, readings: list, source: str, max_readings: int = 25) -> Dict[str, Any]:
        """Assess each extracted reading. ICP/lab tables are OBSERVED lab values (no XRF correction applied)."""
        _, assess_reading = self._import()
        results = []
        for r in readings[:max_readings]:
            total = sum(v for v in r["values"].values() if v is not None)
            negative = sorted(e for e, v in r["values"].items() if v is not None and v < 0)
            if negative:   # e.g. a "Diff" (gun minus lab) row in a comparison workbook: not a composition
                results.append({"label": r["label"], "read_from_input": {"values": r["values"]}, "status": "NOT_ASSESSED",
                                "reason": f"negative values for {', '.join(negative)}: this row looks like a difference, not a sample"})
                continue
            if total > 105 or any(v > 100 for v in r["values"].values() if v is not None):
                results.append({"label": r["label"], "read_from_input": {"values": r["values"]}, "status": "NOT_ASSESSED",
                                "reason": f"values add up to {total:.1f} %, which is impossible for one sample; check units/columns"})
                continue
            if r.get("basis_hint") == "icp":
                assessed = assess_reading(r["values"], basis="type_standardised", below_lod=set(r.get("below_lod", [])), models=self._models)
                for e in assessed["elements"].values():   # lab values are the reference itself: never "corrected"
                    if e.get("observed") and e["observed"].get("value_pct") is not None:
                        e["observed"]["source"] = "laboratory (ICP) value from the input"
                        e["inferred"] = {"value_pct": None, "state": "NOT_APPLICABLE", "reason": "already a laboratory value"}
                assessed["value_kind"] = "laboratory values (ICP), reported as given"
            else:
                assessed = assess_reading(r["values"], basis="type_standardised", below_lod=set(r.get("below_lod", [])), models=self._models)
                assessed["value_kind"] = "XRF gun values, corrected to ICP-equivalent"
            results.append({"label": r["label"], "read_from_input": {"values": r["values"], "below_lod": r.get("below_lod", [])}, **assessed})
        return {"source": source, "readings_found": len(readings), "readings_assessed": len(results), "results": results,
                "note": None if len(readings) <= max_readings else f"only the first {max_readings} readings are shown"}

    def assess_text(self, text: str, source: str) -> Dict[str, Any]:
        readings = self._extract().readings_from_text(text or "", source)
        if not readings:
            return {"source": source, "readings_found": 0, "status": "no element readings found in this text"}
        return self.assess_readings(readings, source)

    def assess_image(self, data: bytes, source: str) -> Dict[str, Any]:
        """Photo of an XRF screen or printed report: OCR, then assess what was read."""
        self._import()
        try:
            from src.realdata.ocr_screen import read_screen
        except ImportError as exc:
            raise BlackMassEngineUnavailable(f"OCR not installed: {exc}") from exc
        from app.core.limits import heavy_job

        with heavy_job():   # OCR is CPU-heavy: bounded concurrency per worker
            screen = read_screen(data)
        screen_ok = len(screen["values"]) + len(screen["below_lod"]) >= 3
        # line-by-line text readings are for printed reports; on a screen they only duplicate the layout reading
        readings = [] if screen_ok else [r for r in (screen.get("text_readings") or []) if len(r["values"]) >= 3]
        used = set(screen["values"].values())
        screen["unlabelled_values"] = [v for v in screen["unlabelled_values"] if v not in used]
        if not screen.get("plausible", True):
            return {"source": source, "readings_found": 0, "status": "photo could not be read reliably",
                    "reason": screen.get("plausibility_note"), "values_seen_not_used": screen["values"]}
        if screen_ok:
            readings.insert(0, {"label": "screen", "values": screen["values"], "below_lod": screen["below_lod"], "basis_hint": "xrf"})
        if not readings:
            return {"source": source, "readings_found": 0, "status": "no instrument readings recognised in this photo",
                    "unlabelled_numbers": screen["unlabelled_values"][:10]}
        out = self.assess_readings(readings, source)
        out["photo_reading"] = {"state": "OBSERVED (read from photo by OCR; check against the photo)",
                                "unlabelled_numbers_not_used": screen["unlabelled_values"][:10],
                                "grade_flags": screen.get("grade_flags", []), "mean_ocr_confidence": screen.get("mean_confidence")}
        return out

    def model_card(self) -> Dict[str, Any]:
        self._import()
        import json

        card = json.loads((self.root / "models" / "real" / "model_card.json").read_text(encoding="utf-8"))
        report = self.root / "reports" / "real" / "REPORT.md"
        card["report_path"] = str(report)
        return card
