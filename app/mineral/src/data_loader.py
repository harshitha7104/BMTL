"""Loading, wavelength validation/conversion and sample-name parsing.

The source file is only ever read. All conversions happen in memory and the
results are returned as new objects.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".csv", ".xlsx", ".xls"}

# Factor that converts a unit to nanometres.
UNIT_TO_NM = {"nm": 1.0, "um": 1000.0}


class DataLoadError(ValueError):
    """Raised with a beginner-readable message when an input file is unusable."""


@dataclass
class WavelengthReport:
    n_bands: int
    unit_detected: str
    unit_reason: str
    min_nm: float
    max_nm: float
    modal_step_nm: float
    is_strictly_increasing: bool
    n_duplicates: int
    irregular_steps: list[dict] = field(default_factory=list)

    @property
    def is_uniform(self) -> bool:
        return not self.irregular_steps


@dataclass
class SpectralDataset:
    """Spectra exactly as read, plus the wavelength axis converted to nm.

    reflectance has shape (n_samples, n_bands); row i belongs to sample_names[i].
    """
    source_path: Path
    wavelength_original: np.ndarray      # values exactly as in the file
    wavelength_nm: np.ndarray            # converted copy
    reflectance: np.ndarray              # (n_samples, n_bands), never modified
    sample_names: list[str]
    wavelength_report: WavelengthReport

    @property
    def n_samples(self) -> int:
        return self.reflectance.shape[0]

    @property
    def n_bands(self) -> int:
        return self.reflectance.shape[1]

    def spectrum(self, name: str) -> np.ndarray:
        try:
            return self.reflectance[self.sample_names.index(name)]
        except ValueError:
            raise KeyError(f"Sample '{name}' is not in the dataset.") from None


# ---------------------------------------------------------------------------
# Wavelength handling
# ---------------------------------------------------------------------------

def infer_wavelength_unit(values: np.ndarray) -> tuple[str, str]:
    """Infer the unit from the numeric range of a VNIR–SWIR wavelength axis.

    Reflectance spectrometers in this domain cover roughly 0.3–3 µm
    (300–3000 nm). Anything else is rejected rather than guessed.
    """
    lo, hi = float(np.nanmin(values)), float(np.nanmax(values))
    if 0.2 <= lo and hi <= 3.0:
        return "um", f"values span {lo:g}–{hi:g}; only plausible as micrometres (=> {lo*1000:g}–{hi*1000:g} nm)"
    if 200 <= lo and hi <= 3000:
        return "nm", f"values span {lo:g}–{hi:g}; consistent with nanometres"
    raise DataLoadError(
        f"Cannot determine the wavelength unit: values span {lo:g} to {hi:g}. "
        "Expected micrometres (about 0.35–2.5) or nanometres (about 350–2500)."
    )


def convert_wavelength_units(values: np.ndarray, unit: str) -> np.ndarray:
    """Return a new array in nm. No rounding is applied, so float32 storage
    noise in the source (e.g. 0.350000024 µm -> 350.000024 nm) is preserved."""
    if unit not in UNIT_TO_NM:
        raise DataLoadError(f"Unsupported wavelength unit '{unit}'.")
    return np.asarray(values, dtype=np.float64) * UNIT_TO_NM[unit]


def validate_wavelengths(values_nm: np.ndarray, unit: str, unit_reason: str) -> WavelengthReport:
    wl = np.asarray(values_nm, dtype=np.float64)
    steps = np.diff(wl)
    # Round to 0.01 nm only for finding the modal step; float32 noise in the
    # source would otherwise make every step look unique.
    rounded = np.round(steps, 2)
    vals, counts = np.unique(rounded, return_counts=True)
    modal = float(vals[np.argmax(counts)])
    irregular = [
        {"index": int(i), "from_nm": float(wl[i]), "to_nm": float(wl[i + 1]),
         "step_nm": float(round(steps[i], 4))}
        for i in np.flatnonzero(np.abs(rounded - modal) > 0.01)
    ]
    return WavelengthReport(
        n_bands=len(wl), unit_detected=unit, unit_reason=unit_reason,
        min_nm=float(wl.min()), max_nm=float(wl.max()), modal_step_nm=modal,
        is_strictly_increasing=bool(np.all(steps > 0)),
        n_duplicates=int(len(wl) - len(np.unique(wl))),
        irregular_steps=irregular,
    )


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise DataLoadError(
            f"'{path.name}' is a {suffix or 'extension-less'} file. "
            "Please provide a .csv or .xlsx spectral table.")
    try:
        if suffix == ".csv":
            return pd.read_csv(path, encoding="utf-8-sig")
        return pd.read_excel(path)
    except ImportError as exc:
        raise DataLoadError(f"Reading {suffix} files needs an extra package: {exc}") from exc
    except Exception as exc:
        raise DataLoadError(f"Could not read '{path.name}': {exc}") from exc


def _find_wavelength_column(df: pd.DataFrame) -> str:
    for col in df.columns:
        if str(col).strip().lower() in {"wavelength", "wavelengths", "wl", "lambda", "wavelength_nm", "wavelength_um"}:
            return col
    first = df.columns[0]
    if pd.to_numeric(df[first], errors="coerce").notna().all():
        log.warning("No column named 'Wavelength'; using first column '%s'", first)
        return first
    raise DataLoadError("No wavelength column found. The first column should be named 'Wavelength'.")


def load_spectra(path: str | Path) -> SpectralDataset:
    """Read a wide spectral table: one wavelength column, one column per sample."""
    path = Path(path)
    if not path.is_file():
        raise DataLoadError(f"File not found: {path}")
    log.info("Loading spectra from %s", path.name)
    df = _read_table(path)
    if df.shape[1] < 2 or df.shape[0] < 3:
        raise DataLoadError(f"'{path.name}' has shape {df.shape}; expected a wavelength column plus sample columns.")

    wl_col = _find_wavelength_column(df)
    wl_raw = pd.to_numeric(df[wl_col], errors="coerce")
    if wl_raw.isna().any():
        bad = df.loc[wl_raw.isna(), wl_col].head(5).tolist()
        raise DataLoadError(f"Wavelength column has {int(wl_raw.isna().sum())} non-numeric/empty values, e.g. {bad}.")
    wl_original = wl_raw.to_numpy(dtype=np.float64)

    sample_cols = [c for c in df.columns if c != wl_col]
    names = [str(c) for c in sample_cols]
    # pandas renames duplicate headers to "name.1"; report rather than hide it.
    mangled = [n for n in names if re.search(r"\.\d+$", n) and n.rsplit(".", 1)[0] in names]
    if mangled:
        raise DataLoadError(f"Duplicate sample column names found: {mangled}. Please make column names unique.")

    values = df[sample_cols].apply(pd.to_numeric, errors="coerce")
    n_bad = int(values.isna().sum().sum() - df[sample_cols].isna().sum().sum())
    if n_bad:
        log.warning("%d non-numeric spectral cells converted to NaN", n_bad)

    unit, reason = infer_wavelength_unit(wl_original)
    wl_nm = convert_wavelength_units(wl_original, unit)
    report = validate_wavelengths(wl_nm, unit, reason)
    if not report.is_strictly_increasing:
        raise DataLoadError("Wavelengths are not strictly increasing (unsorted or duplicated). Please check the file.")
    log.info("Wavelengths: %d bands, %.1f–%.1f nm (unit detected: %s); %d irregular step(s)",
             report.n_bands, report.min_nm, report.max_nm, unit, len(report.irregular_steps))
    log.info("Samples: %d", len(names))

    return SpectralDataset(
        source_path=path, wavelength_original=wl_original, wavelength_nm=wl_nm,
        reflectance=values.to_numpy(dtype=np.float64).T.copy(),
        sample_names=names, wavelength_report=report,
    )


# ---------------------------------------------------------------------------
# Sample-name structure
# ---------------------------------------------------------------------------

# e.g. NBCA24-11D_weathered2-1 -> campaign NBCA24, rock 11D, surface weathered,
# surface index 2, replicate 1. NBOR24 names use f/w abbreviations.
_NAME_RE = re.compile(
    r"^(?P<campaign>[A-Za-z]+\d+)-(?P<rock>[0-9]+[A-Za-z]*)"
    r"(?:_(?P<surface>fresh|weathered|f|w)(?P<surface_idx>\d+)(?:-(?P<replicate>\d+))?)?$"
)
_SURFACE_ALIASES = {"fresh": "fresh", "weathered": "weathered", "f": "fresh", "w": "weathered"}


def parse_sample_name(name: str) -> dict:
    """Split a sample name into rock / surface / replicate fields.

    Returned fields describe *naming structure only*; they say nothing about
    mineralogy. 'f'/'w' are mapped to fresh/weathered and marked as inferred.
    """
    m = _NAME_RE.match(name.strip())
    if not m:
        return {"sample": name, "parsed": False, "campaign": None, "rock_id": None,
                "surface_raw": None, "surface": "unparsed", "surface_inferred": False,
                "surface_index": None, "replicate": None, "measurement_id": None,
                "note": "name does not follow the CAMPAIGN-ROCK_surfaceN[-R] pattern"}
    g = m.groupdict()
    rock_id = f"{g['campaign']}-{g['rock']}"
    surface_raw = g["surface"]
    if surface_raw is None:
        return {"sample": name, "parsed": True, "campaign": g["campaign"], "rock_id": rock_id,
                "surface_raw": None, "surface": "unspecified", "surface_inferred": False,
                "surface_index": None, "replicate": 0, "measurement_id": rock_id,
                "note": "no surface/replicate suffix in name"}
    surface = _SURFACE_ALIASES[surface_raw.lower()]
    idx = int(g["surface_idx"])
    return {"sample": name, "parsed": True, "campaign": g["campaign"], "rock_id": rock_id,
            "surface_raw": surface_raw, "surface": surface,
            "surface_inferred": surface_raw.lower() in {"f", "w"},
            "surface_index": idx, "replicate": int(g["replicate"] or 0),
            "measurement_id": f"{rock_id}_{surface}{idx}",
            "note": f"'{surface_raw}' interpreted as '{surface}'" if surface_raw.lower() in {"f", "w"} else ""}


def build_sample_table(names: list[str]) -> pd.DataFrame:
    """One row per sample with parsed naming fields and group sizes.

    measurement_id groups technical replicates (same rock, same surface spot
    number); rock_id groups everything measured on one physical rock.
    """
    table = pd.DataFrame([parse_sample_name(n) for n in names])
    table["n_in_measurement"] = table.groupby("measurement_id", dropna=False)["sample"].transform("size")
    table["n_in_rock"] = table.groupby("rock_id", dropna=False)["sample"].transform("size")
    # Flag rock IDs that are a prefix of another rock ID (e.g. NBCA24-14 vs NBCA24-14B):
    # these may or may not be the same rock, so the user must decide.
    rocks = sorted(set(table["rock_id"].dropna()))
    table["rock_id_ambiguity"] = table["rock_id"].map(
        lambda r: ", ".join(_letter_suffix_relatives(r, rocks)) if isinstance(r, str) else "")
    return table


def _letter_suffix_relatives(rock: str, rocks: list[str]) -> list[str]:
    """Rock IDs that differ from `rock` only by one trailing letter."""
    def differs_by_letter(a: str, b: str) -> bool:
        return b.startswith(a) and len(b) == len(a) + 1 and b[-1].isalpha()
    return [o for o in rocks if differs_by_letter(rock, o) or differs_by_letter(o, rock)]
