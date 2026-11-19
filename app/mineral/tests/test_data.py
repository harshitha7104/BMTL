"""Phase 1 tests: loading, unit handling, name parsing, quality flags."""
import numpy as np
import pandas as pd
import pytest

from src.data_loader import (
    DataLoadError, build_sample_table, convert_wavelength_units, infer_wavelength_unit,
    load_spectra, parse_sample_name, validate_wavelengths,
)
from src.quality import find_spikes, run_quality_checks, spectral_angle, splice_step_z


def _write_csv(tmp_path, wl, columns: dict, name="spectra.csv"):
    df = pd.DataFrame({"Wavelength": wl, **columns})
    path = tmp_path / name
    df.to_csv(path, index=False)
    return path


def _smooth(wl, base=0.3, depth=0.1, centre=2200.0, width=30.0):
    return base - depth * np.exp(-0.5 * ((wl - centre) / width) ** 2) + 0.00005 * (wl - wl[0]) / 10


@pytest.fixture
def um_grid():
    return np.round(np.arange(350, 2501) / 1000.0, 3)  # 0.350 … 2.500 µm


# --- wavelength units --------------------------------------------------------------

def test_unit_inferred_as_micrometres(um_grid):
    unit, _ = infer_wavelength_unit(um_grid)
    assert unit == "um"


def test_unit_inferred_as_nanometres():
    assert infer_wavelength_unit(np.arange(350, 2501.0))[0] == "nm"


def test_unit_rejects_implausible_range():
    with pytest.raises(DataLoadError):
        infer_wavelength_unit(np.array([4000.0, 10000.0]))


def test_conversion_um_to_nm_is_exact_and_returns_copy(um_grid):
    nm = convert_wavelength_units(um_grid, "um")
    assert nm[0] == pytest.approx(350.0) and nm[-1] == pytest.approx(2500.0)
    assert um_grid[0] == pytest.approx(0.35)  # input untouched


def test_validate_reports_irregular_step():
    wl = np.concatenate([np.arange(400, 1000.0), np.arange(1000.1, 1100.1)])
    wl = np.insert(wl, 600, 999.5)[:-1]  # 999 -> 999.5 -> 1000.1 breaks the 1 nm grid
    rep = validate_wavelengths(np.sort(wl), "nm", "")
    assert rep.modal_step_nm == 1.0
    assert not rep.is_uniform


# --- loading -------------------------------------------------------------------------

def test_load_converts_and_keeps_original(tmp_path, um_grid):
    nm = um_grid * 1000
    path = _write_csv(tmp_path, um_grid, {"A-1_f1": _smooth(nm), "A-1_f1-1": _smooth(nm) * 1.01})
    before = path.read_bytes()
    ds = load_spectra(path)
    assert ds.n_samples == 2 and ds.n_bands == 2151
    assert ds.wavelength_report.unit_detected == "um"
    assert ds.wavelength_nm[0] == pytest.approx(350.0)
    assert ds.wavelength_original[0] == pytest.approx(0.35)
    assert path.read_bytes() == before  # source file never modified


def test_spectrum_extraction_by_name(tmp_path, um_grid):
    nm = um_grid * 1000
    s = _smooth(nm)
    ds = load_spectra(_write_csv(tmp_path, um_grid, {"A-1_f1": s, "A-2_w1": s * 2}))
    np.testing.assert_allclose(ds.spectrum("A-2_w1"), s * 2)
    with pytest.raises(KeyError):
        ds.spectrum("missing")


def test_missing_values_become_nan_and_are_flagged(tmp_path, um_grid):
    nm = um_grid * 1000
    s = _smooth(nm).astype(object)
    s[100] = "n/a"
    ds = load_spectra(_write_csv(tmp_path, um_grid, {"A-1_f1": s, "A-2_f1": _smooth(nm)}))
    assert np.isnan(ds.reflectance[0, 100])
    q = run_quality_checks(ds, build_sample_table(ds.sample_names))
    assert ((q["flags"]["sample"] == "A-1_f1") & (q["flags"]["check"] == "non_finite_values")).any()


def test_wrong_file_type_rejected(tmp_path):
    p = tmp_path / "spectra.txt"
    p.write_text("x")
    with pytest.raises(DataLoadError, match=".csv or .xlsx"):
        load_spectra(p)


def test_nonnumeric_wavelength_rejected(tmp_path):
    p = tmp_path / "bad.csv"
    pd.DataFrame({"Wavelength": ["0.35", "abc", "0.37"], "S": [0.1, 0.2, 0.3]}).to_csv(p, index=False)
    with pytest.raises(DataLoadError, match="non-numeric"):
        load_spectra(p)


def test_unsorted_wavelength_rejected(tmp_path):
    p = tmp_path / "bad.csv"
    pd.DataFrame({"Wavelength": [0.37, 0.35, 0.36], "S": [0.1, 0.2, 0.3]}).to_csv(p, index=False)
    with pytest.raises(DataLoadError, match="increasing"):
        load_spectra(p)


def test_duplicate_column_names_rejected(tmp_path):
    p = tmp_path / "dup.csv"
    p.write_text("Wavelength,S,S\n0.35,0.1,0.1\n0.36,0.2,0.2\n0.37,0.3,0.3\n")
    with pytest.raises(DataLoadError, match="Duplicate"):
        load_spectra(p)


# --- sample names ----------------------------------------------------------------------

@pytest.mark.parametrize("name, rock, surface, idx, rep, inferred", [
    ("NBCA24-14B_fresh1", "NBCA24-14B", "fresh", 1, 0, False),
    ("NBCA24-11D_weathered2-3", "NBCA24-11D", "weathered", 2, 3, False),
    ("NBOR24-09_w3-1", "NBOR24-09", "weathered", 3, 1, True),
    ("NBOR24-02_f1", "NBOR24-02", "fresh", 1, 0, True),
])
def test_parse_sample_name(name, rock, surface, idx, rep, inferred):
    p = parse_sample_name(name)
    assert (p["rock_id"], p["surface"], p["surface_index"], p["replicate"], p["surface_inferred"]) == \
        (rock, surface, idx, rep, inferred)


def test_parse_name_without_suffix():
    p = parse_sample_name("NBCA24-14")
    assert p["parsed"] and p["surface"] == "unspecified" and p["rock_id"] == "NBCA24-14"


def test_unparseable_name_is_kept_not_guessed():
    p = parse_sample_name("random sample")
    assert not p["parsed"] and p["rock_id"] is None


def test_sample_table_groups_and_ambiguity():
    t = build_sample_table(["NBCA24-14B_fresh1", "NBCA24-14B_fresh1-1", "NBCA24-14", "NBCA24-01_fresh1"])
    row = t.set_index("sample")
    assert row.loc["NBCA24-14B_fresh1", "n_in_measurement"] == 2
    assert row.loc["NBCA24-14", "rock_id_ambiguity"] == "NBCA24-14B"
    assert row.loc["NBCA24-01_fresh1", "rock_id_ambiguity"] == ""


# --- quality primitives -------------------------------------------------------------------

def test_spectral_angle_ignores_brightness():
    a = np.linspace(0.1, 0.5, 50)
    assert spectral_angle(a, 3 * a) == pytest.approx(0.0, abs=1e-7)
    assert spectral_angle(a, a[::-1]) > 0.1


def test_spike_detected_only_inside_range():
    wl = np.arange(350, 2501.0)
    x = _smooth(wl)
    x[1000] += 0.05  # 1350 nm spike
    x[10] += 0.05    # 360 nm, outside the checked range
    hits = find_spikes(x, wl)
    assert list(wl[hits]) == [1350.0]


def test_splice_step_detected():
    rng = np.random.default_rng(0)
    x = np.linspace(0.2, 0.3, 200) + rng.normal(0, 1e-4, 200)
    x[101:] += 0.01
    _, z = splice_step_z(x, 100)
    assert z > 6
    _, z_clean = splice_step_z(x, 50)
    assert abs(z_clean) < 6


def test_negligible_splice_step_not_flagged(tmp_path):
    """A step that is statistically sharp but tiny in reflectance is reported, not flagged."""
    wl_um = np.round(np.arange(350, 2501) / 1000.0, 3)
    wl_um[1450:] += 0.0009  # mimic the 1799 -> 1801 nm grid jump
    nm = wl_um * 1000
    x = 0.3 + 0.00001 * np.arange(nm.size)
    x[1450:] += 0.0001       # 0.03 % of mean: negligible
    y = x.copy()
    y[1450:] += 0.01         # ~3 % of mean: material
    ds = load_spectra(_write_csv(tmp_path, wl_um, {"A-1_f1": x, "A-2_f1": y}))
    q = run_quality_checks(ds, build_sample_table(ds.sample_names))
    flagged = set(q["flags"].loc[q["flags"]["check"] == "splice_discontinuity", "sample"])
    assert flagged == {"A-2_f1"}
