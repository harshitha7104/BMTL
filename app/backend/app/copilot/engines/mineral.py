"""
Mineral spectral-interpretation engine adapter.

Wraps the existing, unmodified project in <repo>/mineral (rule-based
i.hyper.spectroscopy absorption engine + PCA/K-Means spectral model fitted on
170 unlabelled VNIR-SWIR spectra). The package's ``src`` directory is loaded
under the private module name ``mineral_src`` so it cannot collide with other
packages called ``src``.

The mineral project has no ground-truth labels: its "confidence" is an
evidence-agreement score, not a probability, and predictions are hypotheses.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import math
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, List, Optional

log = logging.getLogger(__name__)

PACKAGE_NAME = "mineral_src"
MAX_SPECTRA_PER_FILE = 10

CAVEATS = [
    "The mineral model has no ground-truth labels; predictions are evidence-based hypotheses, not validated identifications.",
    "'confidence' is an evidence-agreement score (0-1), not a probability or a measured accuracy.",
    "Confirm economically or safety-relevant identifications with XRD, XRF or petrography.",
]

# Keys kept from each prediction (others, e.g. full feature tables, are dropped to keep tool output small).
KEEP_KEYS = [
    "sample", "prediction", "prediction_type", "prediction_kind", "confidence", "confidence_label",
    "decision_reason", "support_level", "rule_score", "key_features", "prediction_features_nm",
    "evidence_components", "alternatives", "similar_samples", "cluster", "rule_engine_dominant_class",
    "observed", "inferred", "unknown", "explanation", "warnings",
]


class MineralEngineUnavailable(RuntimeError):
    pass


def _jsonable(value: Any, depth: int = 0, max_list: int = 6, max_str: int = 600) -> Any:
    """Convert numpy/pandas values to JSON-safe Python and cap size."""
    if depth > 6:
        return str(value)[:max_str]
    if isinstance(value, dict):
        return {str(k): _jsonable(v, depth + 1, max_list, max_str) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, (list, tuple)):
        items = [_jsonable(v, depth + 1, max_list, max_str) for v in list(value)[:max_list]]
        if len(value) > max_list:
            items.append(f"... {len(value) - max_list} more")
        return items
    if isinstance(value, str):
        return value if len(value) <= max_str else value[:max_str] + "..."
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    try:
        f = float(value)  # numpy scalars
    except (TypeError, ValueError):
        return str(value)[:max_str]
    if math.isnan(f) or math.isinf(f):
        return None
    return int(f) if f.is_integer() and abs(f) < 1e15 and "int" in type(value).__name__ else round(f, 4)


class MineralEngine:
    """Lazy loader around mineral/src/predict.py."""

    def __init__(self, mineral_dir: Path) -> None:
        self.mineral_dir = Path(mineral_dir)
        self._predict_module = None
        self._lock = threading.Lock()
        self._error: Optional[str] = None

    @property
    def available(self) -> bool:
        return (self.mineral_dir / "src" / "predict.py").exists() and (
            self.mineral_dir / "models" / "spectral_model.joblib"
        ).exists()

    def _load(self):
        if self._predict_module is not None:
            return self._predict_module
        with self._lock:
            if self._predict_module is not None:
                return self._predict_module
            if not self.available:
                raise MineralEngineUnavailable(f"Mineral project not found or model missing under {self.mineral_dir}")
            src = self.mineral_dir / "src"
            if PACKAGE_NAME not in sys.modules:
                spec = importlib.util.spec_from_file_location(
                    PACKAGE_NAME, src / "__init__.py", submodule_search_locations=[str(src)]
                )
                if spec is None or spec.loader is None:
                    raise MineralEngineUnavailable(f"Cannot import {src}")
                module = importlib.util.module_from_spec(spec)
                sys.modules[PACKAGE_NAME] = module
                spec.loader.exec_module(module)
            try:
                self._predict_module = importlib.import_module(f"{PACKAGE_NAME}.predict")
            except ImportError as exc:
                raise MineralEngineUnavailable(
                    f"Mineral engine dependency missing ({exc.name or exc}); install backend/requirements-copilot.txt"
                ) from exc
            return self._predict_module

    def model_card(self) -> dict:
        import json

        card_path = self.mineral_dir / "models" / "model_card.json"
        card = json.loads(card_path.read_text(encoding="utf-8")) if card_path.exists() else {}
        return {
            "status": "ok" if self.available else "unavailable",
            "components": [
                "Rule-based absorption-feature engine (i.hyper.spectroscopy, 163 features, 58 composite rules; no training)",
                "PCA + K-Means fitted on continuum-removed spectra of 170 unlabelled VNIR-SWIR measurements",
                "Conservative fusion of rule, nearest-reference and cluster evidence",
            ],
            "input_requirements": "CSV/XLSX, first column wavelength (nm or um), other columns reflectance 0-1, covering 400-2500 nm",
            "model_card": _jsonable(card, max_list=12),
            "caveats": CAVEATS,
        }

    def interpret_file(self, data: bytes, filename: str) -> dict:
        predict = self._load()
        suffix = Path(filename).suffix.lower() or ".csv"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"spectrum{suffix}"
            path.write_bytes(data)
            try:
                results: List[dict] = predict.predict_file(path)
            except ImportError as exc:  # e.g. pyarrow needed to unpickle the saved model
                raise MineralEngineUnavailable(
                    f"Mineral engine dependency missing ({exc.name or exc}); install backend/requirements-copilot.txt"
                ) from exc
        spectra = []
        for raw in results[:MAX_SPECTRA_PER_FILE]:
            clean = predict.to_serialisable(raw)
            spectra.append(_jsonable({k: clean[k] for k in KEEP_KEYS if k in clean}))
        return {
            "status": "ok",
            "spectra_in_file": len(results),
            "spectra_reported": len(spectra),
            "results": spectra,
            "confidence_definition": getattr(predict, "CONFIDENCE_DEFINITION", ""),
            "caveats": CAVEATS,
        }
