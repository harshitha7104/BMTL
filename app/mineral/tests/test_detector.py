"""Tests for preprocessing, continuum removal, features, rule engine, model,
fusion and end-to-end prediction."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.analysis import analyse_spectrum, cr_vector
from src.data_loader import DataLoadError, build_sample_table, load_spectra
from src.engine import features_to_triplets, load_engine, run_rules
from src.features import extract_features
from src.fusion import (STRONG_RULE, hypothesis_groups, jaccard, members_of, partial_feature_candidates,
                        rank_candidates, rule_candidates)
from src.model import fit_model, load_model, reconstruction_error, save_model
from src.predict import DEFAULT_MODEL_PATH, Predictor, predict_file, to_serialisable
from src.preprocessing import (PreprocessConfig, PreprocessError, continuum_remove, preprocess_spectrum,
                               resample_spectrum, upper_hull)

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_CSV = ROOT / "68026941d4be0210cde07d8c.csv"
WL = np.arange(350, 2501, 1.0)


def gauss(wl, c, w, d):
    return d * np.exp(-0.5 * ((wl - c) / w) ** 2)


def synthetic(wl=WL, bands=((2206, 18, 0.18), (1412, 12, 0.10)), base=None):
    base = base if base is not None else 0.25 + 0.15 * (wl - wl[0]) / (wl[-1] - wl[0])
    absorb = sum(gauss(wl, c, w, d) for c, w, d in bands) if bands else 0
    return base * (1 - absorb)


# --- preprocessing / continuum removal ------------------------------------------------

def test_resample_trims_to_range_and_reports():
    r, notes = resample_spectrum(WL, synthetic(), PreprocessConfig())
    assert r.size == 2101  # 400..2500 nm at 1 nm
    assert any("outside" in n for n in notes)


def test_resample_rejects_short_range():
    wl = np.arange(900, 2501, 1.0)
    with pytest.raises(PreprocessError, match="required"):
        resample_spectrum(wl, np.full(wl.size, 0.3), PreprocessConfig())


def test_resample_bridges_small_gap_rejects_large():
    x = synthetic()
    x[1000:1005] = np.nan
    _, notes = resample_spectrum(WL, x, PreprocessConfig())
    assert any("bridged" in n for n in notes)
    x[1000:1100] = np.nan
    with pytest.raises(PreprocessError, match="Gap"):
        resample_spectrum(WL, x, PreprocessConfig())


def test_upper_hull_lies_on_or_above_spectrum():
    x = synthetic()
    hull = upper_hull(WL, x)
    assert np.all(hull >= x - 1e-12)


def test_continuum_removed_flat_line_is_one():
    cont, cr = continuum_remove(WL, np.linspace(0.2, 0.5, WL.size))
    np.testing.assert_allclose(cr, 1.0, atol=1e-9)


def test_continuum_removal_recovers_depth():
    p = preprocess_spectrum(WL, synthetic(bands=((2206, 18, 0.18),)))
    i = np.argmin(p.continuum_removed)
    assert abs(p.wavelength_nm[i] - 2206) <= 2
    assert 1 - p.continuum_removed[i] == pytest.approx(0.18, abs=0.02)


def test_preprocessing_is_deterministic_and_does_not_modify_input():
    x = synthetic()
    x_copy = x.copy()
    a, b = preprocess_spectrum(WL, x), preprocess_spectrum(WL, x)
    np.testing.assert_array_equal(a.continuum_removed, b.continuum_removed)
    np.testing.assert_array_equal(x, x_copy)


# --- features ---------------------------------------------------------------------------

def test_features_found_with_centre_depth_width_bounds():
    p = preprocess_spectrum(WL, synthetic())
    feats = extract_features(p.wavelength_nm, p.continuum_removed, p.smoothed)
    centres = sorted(round(f.center_nm) for f in feats)
    assert any(abs(c - 2206) <= 3 for c in centres) and any(abs(c - 1412) <= 3 for c in centres)
    f = next(f for f in feats if abs(f.center_nm - 2206) <= 3)
    assert f.start_nm < f.center_nm < f.end_nm
    assert 30 < f.fwhm_nm < 60          # Gaussian sigma 18 nm -> FWHM ~42 nm
    assert f.area > 0


def test_noise_does_not_create_one_feature_per_band():
    rng = np.random.default_rng(1)
    x = synthetic(bands=()) + rng.normal(0, 0.001, WL.size)
    p = preprocess_spectrum(WL, x)
    assert len(extract_features(p.wavelength_nm, p.continuum_removed, p.smoothed)) < 5


def test_cr_vector_length():
    assert cr_vector(np.ones(2101), 1.0).size == 210


# --- rule engine integration ------------------------------------------------------------------

def test_engine_loads_without_grass():
    eng = load_engine()
    assert len(eng.COMPOSITE_RULES) == 58 and hasattr(eng, "interpret_spectrum")


def test_anchor_triplets_make_engine_depth_equal_feature_depth():
    p = preprocess_spectrum(WL, synthetic())
    feats = extract_features(p.wavelength_nm, p.continuum_removed, p.smoothed)
    res = load_engine().interpret_spectrum(features_to_triplets(feats))
    engine_depths = {round(f.center_nm): f.depth for f in res.features}
    for f in feats:
        if f.depth >= 0.02:
            assert engine_depths[round(f.center_nm)] == pytest.approx(f.depth, abs=1e-9)


def test_engine_finds_al_oh_doublet_rules():
    a = analyse_spectrum(WL, synthetic())
    names = {h["name"] for h in a.rules.hypotheses}
    assert "kaolinite" in names


def test_flat_spectrum_gives_no_rule_hypotheses():
    a = analyse_spectrum(WL, np.full(WL.size, 0.3))
    assert a.features == [] and a.rules.hypotheses == []


# --- fusion -------------------------------------------------------------------------------------

def test_jaccard_and_members():
    assert members_of(float("nan")) == set() and members_of(None) == set()
    assert jaccard("a / b", "b / a") == 1.0
    assert jaccard("a / b", "c") == 0.0


def test_implausible_categories_never_win():
    a = analyse_spectrum(WL, synthetic())
    for c in rule_candidates(a):
        if c["category"] not in {"mineral", "geological"}:
            assert not c["plausible"] and c["R"] == 0.0


def _neigh(label, fm=1.0, sim=0.95, n=5):
    return [{"rule_hypothesis": label, "similarity": sim, "feature_match": fm}] * n


def test_rank_unknown_without_features_or_candidates():
    a = analyse_spectrum(WL, np.full(WL.size, 0.3))
    d = rank_candidates(a, [], [], [], {})
    assert d["prediction_type"] == "UNKNOWN"


def test_single_spectral_source_is_moderate_family_group_not_specific():
    a = analyse_spectrum(WL, synthetic())
    d = rank_candidates(a, rule_candidates(a), neighbours=[], cluster_labels=[], quality_factors={})
    assert d["prediction_type"] == "INFERRED" and d["support_level"] == "MODERATE"
    assert d["prediction_kind"] == "group" and d["prediction"].endswith("mineral group")
    assert "Al-OH clay/mica" in d["prediction"]


def test_high_support_when_sources_agree():
    a = analyse_spectrum(WL, synthetic())
    cands = rule_candidates(a)
    label = hypothesis_groups(cands)[0]["label"]
    d = rank_candidates(a, cands, _neigh(label), [label] * 10, {})
    assert d["prediction_type"] == "INFERRED" and d["support_level"] == "HIGH"
    assert d["unit"]["label"] == label


def test_specific_prediction_needs_singleton_and_two_sources():
    a = analyse_spectrum(WL, synthetic())
    cands = rule_candidates(a)
    best = next(c for c in cands if c["plausible"])
    for c in cands:  # make the best rule distinguishable from all others
        c["competing"] = []
    d = rank_candidates(a, cands, _neigh(best["name"]), [best["name"]] * 10, {})
    assert d["prediction_kind"] == "specific" and d["prediction"] == best["name"]


def test_confidence_formula_is_unchanged():
    a = analyse_spectrum(WL, synthetic())
    cands = rule_candidates(a)
    label = hypothesis_groups(cands)[0]["label"]
    d = rank_candidates(a, cands, _neigh(label, fm=0.5), [label] * 4 + [None] * 2, {"low_albedo": 0.8})
    u = d["unit"]
    expected = u["Q"] * (0.5 * u["E"] + 0.3 * u["N"] + 0.2 * u["C"])
    assert u["evidence_confidence"] == pytest.approx(expected, abs=2e-3)


def test_too_many_families_not_inferred():
    a = analyse_spectrum(WL, synthetic())
    cands = rule_candidates(a)
    best = next(c for c in cands if c["plausible"])
    best["competing"] = ["calcite", "talc", "crocidolite_asbestos", "hematite_iron_oxide"]  # 5 families
    d = rank_candidates(a, [best], [], [], {})
    assert not d["candidates"][0]["eligible"]
    assert d["prediction_type"] == "OBSERVED"


def test_feature_mismatch_downweights_neighbours():
    a = analyse_spectrum(WL, synthetic())
    cands = rule_candidates(a)
    label = hypothesis_groups(cands)[0]["label"]
    d = rank_candidates(a, cands, _neigh(label, fm=0.0), [label] * 10, {})
    assert d["unit"]["N"] == 0.0 and d["support_level"] == "MODERATE"


def test_pseudo_labels_alone_never_infer():
    """A spectrum whose own absorptions do not match any rule must not be labelled from its neighbours."""
    a = analyse_spectrum(WL, synthetic(bands=((1000, 60, 0.08),)))  # one broad Fe2+-type band only
    d = rank_candidates(a, rule_candidates(a), _neigh("dolomite / ankerite"), ["dolomite / ankerite"] * 10, {})
    assert d["prediction_type"] == "OBSERVED"


def test_partial_feature_candidates_are_discounted():
    a = analyse_spectrum(WL, synthetic(bands=((1000, 60, 0.08),)))
    partial = partial_feature_candidates(a, fired=set())
    assert partial and all(p["E"] < STRONG_RULE for p in partial)


# --- model fitting and prediction (uses the real CSV) -----------------------------------------------

@pytest.fixture(scope="module")
def fitted(tmp_path_factory):
    ds = load_spectra(REFERENCE_CSV)
    model, analyses = fit_model(ds, build_sample_table(ds.sample_names))
    path = tmp_path_factory.mktemp("model") / "model.joblib"
    save_model(model, path)
    return ds, model, path


def test_model_fit_structure(fitted):
    ds, model, path = fitted
    assert 2 <= model["kmeans"].n_clusters <= 10
    assert model["reference_embeddings"].shape == (ds.n_samples, model["pca"].n_components_)
    assert model["n_fit_units"] < ds.n_samples  # replicates averaged before fitting
    assert load_model(path)["version"] == model["version"]
    assert reconstruction_error(model["pca"], np.zeros(210)).shape == (1,)


def test_model_fit_is_reproducible(fitted):
    ds, model, _ = fitted
    model2, _ = fit_model(ds, build_sample_table(ds.sample_names))
    np.testing.assert_array_equal(model["reference"]["cluster"], model2["reference"]["cluster"])


def test_prediction_on_existing_spectrum(fitted):
    ds, model, _ = fitted
    p = Predictor(model=model)
    name = ds.sample_names[0]
    r = p.predict(ds.wavelength_nm, ds.reflectance[0], "nm", name, exclude_rock="NBCA24-14B")
    for key in ("prediction", "prediction_type", "support_level", "prediction_kind", "alternatives",
                "confidence", "evidence_sources", "key_features", "why", "cluster", "similar_samples",
                "spectral_features", "rule_evidence", "warnings", "explanation", "evidence"):
        assert key in r
    assert r["prediction_type"] in {"INFERRED", "OBSERVED", "UNKNOWN"}
    assert all(n["rock_id"] != "NBCA24-14B" for n in r["similar_samples"])
    assert len({n["rock_id"] for n in r["similar_samples"]}) == len(r["similar_samples"])
    assert 0.0 <= r["confidence"] <= 1.0


def test_prediction_on_new_synthetic_spectrum_in_micrometres(fitted):
    _, model, _ = fitted
    wl_um = np.arange(350, 2501, 2.0) / 1000
    r = Predictor(model=model).predict(wl_um, synthetic(wl_um * 1000), sample_name="synthetic")
    assert any(abs(f["center_nm"] - 2206) <= 3 for f in r["spectral_features"])
    # Clay-like absorptions are absent from the reference library: only the spectrum's own rule evidence
    # supports it, so at most a MODERATE family-level group, with a novelty warning.
    assert r["support_level"] != "HIGH" and r["prediction_kind"] != "specific"
    assert any("Novel spectrum" in w for w in r["warnings"])
    assert r["why"] and r["alternatives"] is not None


def test_flat_spectrum_is_unknown(fitted):
    _, model, _ = fitted
    r = Predictor(model=model).predict(WL, np.full(WL.size, 0.3), "nm")
    assert r["prediction_type"] == "UNKNOWN"


def test_constant_zero_spectrum_is_unusable(fitted):
    _, model, _ = fitted
    r = Predictor(model=model).predict(WL, np.zeros(WL.size), "nm")
    assert r["prediction_type"] == "UNKNOWN" and r["decision_reason"] == "spectrum failed quality checks"


def test_malformed_input_raises_readable_error(fitted):
    _, model, _ = fitted
    with pytest.raises(PreprocessError):
        Predictor(model=model).predict(np.arange(1000, 1100.0), np.full(100, 0.3), "nm")
    with pytest.raises(DataLoadError):
        Predictor(model=model).predict(np.array([5000.0, 6000.0]), np.array([0.1, 0.2]))


def test_predict_file_and_serialisable(fitted, tmp_path):
    _, model, _ = fitted
    path = tmp_path / "new.csv"
    pd.DataFrame({"Wavelength": WL / 1000, "s1": synthetic(), "s2": np.full(WL.size, 0.3)}).to_csv(path, index=False)
    results = predict_file(path, Predictor(model=model))
    assert [r["sample"] for r in results] == ["s1", "s2"]
    import json
    json.dumps([to_serialisable(r) for r in results], default=str)


def test_saved_default_model_works_if_present():
    if not DEFAULT_MODEL_PATH.is_file():
        pytest.skip("run `python run_pipeline.py` to create the default model")
    r = predict_file(ROOT / "data" / "example_new_spectrum.csv")[0]
    assert r["support_level"] != "HIGH"
