"""Streamlit app: spectral interpretation of reference or uploaded spectra.

    streamlit run app.py
"""
from __future__ import annotations

import json
import tempfile
import traceback
from pathlib import Path

import joblib
import pandas as pd
import streamlit as st

from src.data_loader import DataLoadError, load_spectra, parse_sample_name
from src.demo import DEMO_BANNER, DemoPredictor
from src.engine import EngineUnavailable
from src.model import ModelError
from src.predict import DEFAULT_MODEL_PATH, Predictor, to_serialisable
from src.preprocessing import PreprocessError
from src.visualization import plot_pca_clusters, plot_spectrum_analysis

PROJECT_DIR = Path(__file__).resolve().parent
REFERENCE_CSV = PROJECT_DIR / "68026941d4be0210cde07d8c.csv"
DEMO_MODEL_PATH = PROJECT_DIR / "models" / "demo" / "demo_classifier.joblib"
TYPE_COLOURS = {"INFERRED": "#2e7d32", "OBSERVED": "#1565c0", "UNKNOWN": "#757575"}
KNOWN_ERRORS = (DataLoadError, PreprocessError, ModelError, EngineUnavailable)

st.set_page_config(page_title="Mineral Spectral Interpretation", layout="wide")


@st.cache_resource
def get_predictor() -> Predictor:
    return Predictor(model_path=DEFAULT_MODEL_PATH)


@st.cache_resource
def get_dataset(path: str, _mtime: float):
    return load_spectra(path)


@st.cache_resource
def get_demo_predictor(_mtime: float) -> DemoPredictor:
    return DemoPredictor(joblib.load(DEMO_MODEL_PATH), get_predictor())


def render_demo(ds, sample: str, exclude_rock: str | None, debug: bool):
    st.error(DEMO_BANNER)
    if not DEMO_MODEL_PATH.is_file():
        st.info("The demo model has not been built yet. Run:  `python build_demo.py`")
        st.stop()
    try:
        with st.spinner("Running demo classifier…"):
            r = get_demo_predictor(DEMO_MODEL_PATH.stat().st_mtime).predict(
                ds.wavelength_nm, ds.spectrum(sample), sample, exclude_rock)
    except Exception as exc:  # noqa: BLE001
        show_error(exc, debug)
        st.stop()
    st.markdown(f"#### Demo prediction for `{sample}`")
    if r["predicted"] is None:
        st.warning("No demo prediction: the spectrum failed quality checks.")
    else:
        left, right = st.columns([2, 1])
        with left:
            st.markdown(f"**Predicted mineral (pseudo-label class):** {r['predicted_family']}")
            st.markdown(f"<div style='font-size:1.3rem;font-weight:600'>{r['predicted']}</div>", unsafe_allow_html=True)
            st.markdown(f"**Prediction source:** {r['prediction_source']}")
            st.markdown(f"**Rule engine (normal mode) says:** {r['rule_engine_prediction']} "
                        f"(rules: {r['rule_engine_rule_set'] or 'none'}) — "
                        f"{'consistent with' if r['agrees_with_rule_engine'] else 'NOT consistent with'} the demo class")
        with right:
            st.metric("Classifier vote share", f"{r['vote_share']:.2f}",
                      help="Share of Random-Forest trees voting for this pseudo-label class. Not a probability and "
                           "not a mineral-identification confidence.")
        if r.get("in_demo_training_set"):
            st.info(f"This spectrum is in the demo training set (pseudo-label: {r['pseudo_label_of_this_sample']}). "
                    f"Out-of-fold prediction with its rock held out: **{r.get('out_of_fold_prediction', 'n/a')}** "
                    f"(vote share {r.get('out_of_fold_vote_share', float('nan')):.2f}).")
        st.markdown("##### Alternative minerals (pseudo-label classes)")
        st.dataframe(pd.DataFrame(r["alternatives"]), hide_index=True, width="stretch")
        st.markdown("##### Supporting absorption features (rule-engine matches for the predicted class)")
        st.dataframe(pd.DataFrame(r["supporting_features"]), hide_index=True, width="stretch")
        st.markdown("##### Similar pseudo-labelled spectra (own rock excluded)")
        st.dataframe(pd.DataFrame(r["similar_demo_spectra"]), hide_index=True, width="stretch")
    for w in r["warnings"]:
        st.warning(w)
    ev = r["evidence_result"]
    highlight = sorted({s["center_nm"] for s in r.get("supporting_features", [])})
    st.pyplot(plot_spectrum_analysis(ev["_analysis"], f"{sample}: demo class {r.get('predicted_family')}",
                                     original=(ds.wavelength_nm, ds.spectrum(sample)), highlight_nm=highlight))
    st.caption("Pseudo-label validation performance (grouped by rock, NOT mineral accuracy): see "
               "`outputs/demo/pseudo_label_validation.md`.")


def load_upload(uploaded):
    suffix = Path(uploaded.name).suffix.lower()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"upload{suffix}"
        path.write_bytes(uploaded.getvalue())
        return load_spectra(path)


def show_error(exc: Exception, debug: bool):
    st.error(str(exc) if isinstance(exc, KNOWN_ERRORS) else f"Unexpected error: {exc}")
    if debug:
        st.code(traceback.format_exc())


st.title("Mineral Spectral Interpretation")
st.caption("Predicts the most compatible mineral/material interpretation from absorption features, the "
           "i.hyper.spectroscopy rule engine and similarity to 170 unlabelled reference spectra. "
           "No ground-truth labels exist: results are evidence-based hypotheses, not validated identifications.")

with st.sidebar:
    mode = st.radio("Mode", ["Normal (evidence-based)", "DEMO labelled (pseudo-label classifier)"],
                    help="DEMO mode uses a classifier trained on pseudo-labels from the rule engine — not ground truth.")
    st.header("Input")
    source = st.radio("Spectrum source", ["Existing reference spectrum", "Upload new spectrum (CSV/XLSX)"])
    debug = st.checkbox("Debug mode (show tracebacks)", value=False)

try:
    predictor = get_predictor()
except KNOWN_ERRORS as exc:
    st.error(f"{exc}")
    st.info("Fit the model first from the project folder:  `python run_pipeline.py`")
    st.stop()

ds, sample, exclude_rock = None, None, None
try:
    if source.startswith("Existing"):
        if not REFERENCE_CSV.is_file():
            st.error(f"Reference CSV not found: {REFERENCE_CSV.name}")
            st.stop()
        ds = get_dataset(str(REFERENCE_CSV), REFERENCE_CSV.stat().st_mtime)
        with st.sidebar:
            sample = st.selectbox("Sample", ds.sample_names)
            leave_out = st.checkbox("Exclude the sample's own rock from similarity evidence", value=True,
                                    help="Prevents a spectrum from being confirmed by its own replicates.")
        exclude_rock = (parse_sample_name(sample)["rock_id"] or sample) if leave_out else None
    else:
        with st.sidebar:
            uploaded = st.file_uploader("Spectrum file", type=["csv", "xlsx", "xls"],
                                        help="First column: wavelength (µm or nm). Other columns: reflectance 0–1.")
        if uploaded is None:
            st.info("Upload a CSV/XLSX file: first column wavelength (µm or nm), one column per spectrum. "
                    "An example is in `data/example_new_spectrum.csv`.")
            st.stop()
        ds = load_upload(uploaded)
        with st.sidebar:
            sample = st.selectbox("Spectrum column", ds.sample_names)
except Exception as exc:  # noqa: BLE001 — shown to the user in plain language
    show_error(exc, debug)
    st.stop()

wr = ds.wavelength_report
c1, c2, c3, c4 = st.columns(4)
c1.metric("Spectra in file", ds.n_samples)
c2.metric("Wavelength bands", ds.n_bands)
c3.metric("Range (nm)", f"{wr.min_nm:.0f}–{wr.max_nm:.0f}")
c4.metric("Unit detected", "µm → nm" if wr.unit_detected == "um" else "nm")

if mode.startswith("DEMO"):
    render_demo(ds, sample, exclude_rock, debug)
    st.stop()

try:
    with st.spinner("Analysing spectrum…"):
        result = predictor.predict(ds.wavelength_nm, ds.spectrum(sample), "nm", sample, exclude_rock)
except Exception as exc:  # noqa: BLE001
    show_error(exc, debug)
    st.stop()

st.divider()
ptype = result["prediction_type"]
level = result["support_level"]
badge = ptype + (f" · {level} support" if level else "") + (f" · {result['prediction_kind']}" if result["prediction_kind"] else "")
left, right = st.columns([2, 1])
with left:
    st.markdown(f"#### Final prediction for `{sample}`")
    st.markdown(f"<div style='font-size:1.6rem;font-weight:600'>{result['prediction']}</div>"
                f"<span style='background:{TYPE_COLOURS[ptype]};color:white;padding:2px 10px;border-radius:10px'>"
                f"{badge}</span>", unsafe_allow_html=True)
    if result["group_members"]:
        st.markdown("**Ranked group members** (the rule evidence cannot separate them; order is by member-level support):")
        st.markdown("\n".join(f"{i + 1}. {m['rule']} — {m['family']}, member support {m['evidence_confidence']:.2f}"
                              for i, m in enumerate(result["group_members"])))
    st.markdown(f"**Evidence sources:** {', '.join(result['evidence_sources']) or 'none'}")
with right:
    st.metric("Evidence confidence", f"{result['confidence']:.2f}",
              help="Not a probability. " + result["confidence_definition"])
    st.metric("Rule score (best rule)", "n/a" if result["rule_score"] is None else f"{result['rule_score']:.2f}",
              help="Heuristic score of the i.hyper.spectroscopy composite rule. Not a probability.")
st.markdown(result["explanation"])

st.markdown("##### Why this prediction?")
st.dataframe(pd.DataFrame([{"evidence source": w["source"],
                            "contributed": {True: "yes", False: "no", None: "—"}[w["contributed"]],
                            "value": "" if w["value"] is None else f"{w['value']:.3f}", "detail": w["detail"]}
                           for w in result["why"]]), hide_index=True, width="stretch")
if result["alternatives"]:
    st.markdown("##### Top alternatives")
    st.dataframe(pd.DataFrame([{"candidate": a["name"], "rules": a["label"], "origin": a["origin"],
                                "evidence confidence": a["evidence_confidence"],
                                "sources": ", ".join(a["supporting_sources"]) or "none",
                                "E": a["E"], "N": a["N"], "C": a["C"]} for a in result["alternatives"]]),
                 hide_index=True, width="stretch")
for w in result["warnings"]:
    st.warning(w)

tab_spec, tab_ev, tab_rules, tab_sim, tab_model, tab_json = st.tabs(
    ["Key absorption features", "Observed / Inferred / Unknown", "Rule hypotheses", "Similar samples",
     "Cluster / PCA", "Raw result"])

analysis = result["_analysis"]
with tab_spec:
    fig = plot_spectrum_analysis(analysis, f"{sample}: {result['prediction']}",
                                 original=(ds.wavelength_nm, ds.spectrum(sample)),
                                 highlight_nm=result["prediction_features_nm"])
    st.pyplot(fig)
    feats = pd.DataFrame(result["spectral_features"])
    if feats.empty:
        st.write("No absorption features detected.")
    else:
        st.dataframe(feats, hide_index=True, width="stretch")
        st.download_button("Download features (CSV)", feats.to_csv(index=False), f"{sample}_features.csv", "text/csv")

with tab_ev:
    ev = result["evidence"]
    st.markdown("**OBSERVED** — directly measured")
    st.markdown("\n".join(f"- {x}" for x in ev["observed"]) or "- none")
    st.markdown("**INFERRED** — supported by the evidence sources listed")
    st.markdown("\n".join(f"- {x}" for x in ev["inferred"]) or "- none")
    st.markdown("**UNKNOWN** — insufficient or conflicting evidence")
    st.markdown("\n".join(f"- {x}" for x in ev["unknown"]) or "- none")
    comp = result["evidence_components"]
    if comp:
        st.markdown("**Evidence components of the reported candidate**")
        st.dataframe(pd.DataFrame([comp]), hide_index=True)

with tab_rules:
    rows = [{"rule": c["name"], "category": c["category"], "rule_score": c["rule_score"], "R": c["R"],
             "feature_strength": c["feature_strength"], "plausible": c["plausible"],
             "supporting wavelengths (nm)": ", ".join(f"{s['center_nm']:.0f}" for s in c["supporting_features"]),
             "indistinguishable from": ", ".join(c["competing"]), "excluded because": c["excluded_reason"]}
            for c in result["rule_evidence"]]
    st.caption("Composite-rule hypotheses from the unmodified i.hyper.spectroscopy engine, run on the extracted "
               "absorption features. Rule scores are heuristic, not probabilities.")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if result["chromophores"]:
        st.markdown("**Matched absorbing species (chromophores)**")
        st.dataframe(pd.DataFrame(result["chromophores"]), hide_index=True, width="stretch")

with tab_sim:
    st.caption("Most similar reference spectra (cosine similarity in PCA space; one per rock). "
               "Feature match = share of this spectrum's absorption depth also present in the neighbour (±15 nm). "
               "Their rule-based hypotheses are pseudo-labels, not ground truth.")
    st.dataframe(pd.DataFrame(result["similar_samples"]), hide_index=True, width="stretch")

with tab_model:
    cl = result["cluster"]
    if cl:
        st.markdown(f"**Cluster {cl['cluster']}** — {cl['n_members']} reference spectra from {cl['n_rocks']} rocks "
                    "(own rock excluded). A cluster is a group of similar spectral shapes, not a mineral class.")
        st.dataframe(pd.DataFrame(list(cl["rule_hypothesis_counts"].items()),
                                  columns=["rule-based hypothesis", "spectra"]), hide_index=True)
        z = predictor.embed(analysis)
        st.pyplot(plot_pca_clusters(predictor.model, highlight=z))

with tab_json:
    payload = json.dumps(to_serialisable(result), indent=1, default=str)
    st.download_button("Download result (JSON)", payload, f"{sample}_prediction.json", "application/json")
    st.json(to_serialisable(result), expanded=False)
