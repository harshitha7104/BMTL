# Mineral Spectral Interpretation (unlabelled VNIR–SWIR spectra)

A local prototype that takes a reflectance spectrum (350–2500 nm) and returns the **most compatible
mineral/material interpretation supported by the spectral evidence**. If the evidence is weak or
conflicting, it returns no mineral at all.

> **Scientific status.** There is **no ground-truth label file** for this dataset. Nothing here has been
> validated against known mineralogy. No accuracy, precision, recall or F1 is reported, because none can be
> computed honestly. This is a hypothesis-generation tool, not a validated mineral classifier or a
> geological instrument.

## What is (and is not) in the system

| Component | What it is | Learned from data? |
|---|---|---|
| `i.hyper.spectroscopy.py` (unmodified, in `i.hyper.spectroscopy-main/`) | Rule-based knowledge engine: 163 absorption-feature entries and 58 composite rules with hand-set `base_score`s | **No.** It has no weights and no training. It is **not** a pretrained AI model. |
| PCA + K-Means (`models/spectral_model.joblib`) | Unsupervised representation of the continuum-removed spectra | Fitted on the 170 unlabelled spectra. **No labels** are used. |
| Rule-based hypotheses for reference spectra | The engine's strongest hypothesis for each reference spectrum | These are **pseudo-labels (weak supervision), not ground truth** |
| Final prediction | Conservative fusion of rule, similarity and cluster evidence | Rules plus documented thresholds. Nothing is trained or fine-tuned. |

## Installation (Windows, PowerShell)

```powershell
cd C:\Users\admin\OneDrive\Desktop\ACE\mineral
python -m venv .venv                 # use "python", not "py": "py" defaults to the free-threaded 3.13t build here
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

GRASS GIS is **not** needed. The engine is loaded with `grass.script` stubbed out, the same way its
authors' own tests load it (`i.hyper.spectroscopy-main/test_suite.py`).

## Usage

```powershell
python -m pytest                                        # our tests (65)
python -m pytest -p no:cacheprovider i.hyper.spectroscopy-main\test_suite.py   # the engine authors' tests (51)
python run_pipeline.py                                  # quality report + fit model + predict all 170 spectra
python build_demo.py                                    # DEMO pseudo-labelled dataset + DEMO classifier (optional)
python predict.py data\example_new_spectrum.csv         # predict a new spectrum file
streamlit run app.py                                    # web app at http://localhost:8501
```

### DEMO mode (pseudo-labels — not ground truth)
`python build_demo.py` builds a demonstration dataset from the 170 original spectra:
- It writes `data/demo_labelled/`, `models/demo/` and `outputs/demo/`.
- It overwrites nothing. The original CSV and `models/spectral_model.joblib` are only read.
- Labels are **pseudo-labels** taken from the rule engine and the fusion evidence checks. Each label is the
  union of a chemical-family group of rules the engine cannot separate.
- The demo classifier (PCA + Random Forest on continuum-removed spectra) is validated with folds **grouped by
  rock**. Its scores are reported as *pseudo-label validation performance*: they measure agreement with the
  rule engine, not mineral accuracy.
- It is a closed-set classifier: it always answers with one of its classes, and it warns when that answer
  contradicts the evidence.

In the app, choose **Mode → "DEMO labelled (pseudo-label classifier)"** in the sidebar. The details are in
`data/demo_labelled/demo_dataset_summary.md` and `outputs/demo/pseudo_label_validation.md`.

From Python:

```python
from src.predict import predict_spectrum
result = predict_spectrum(wavelengths, reflectance)   # wavelengths in µm or nm (auto-detected)
result["prediction"], result["prediction_type"], result["confidence"]
```

### Input format
A CSV or XLSX file. The first column holds wavelength (named `Wavelength` or numeric), in µm or nm. Every
other column is one reflectance spectrum (0–1). The spectrum must cover 400–2500 nm (5 nm tolerance at the
ends), and gaps of up to 10 nm are interpolated. `data/example_new_spectrum.csv` is a **synthetic**
test spectrum (Al-OH doublet at 1412 + 2206 nm, sampled every 2 nm, in nm). It is not a measurement.

## The dataset (`68026941d4be0210cde07d8c.csv`, never modified)
- 170 spectra × 2151 bands. Wavelengths run 0.350–2.500 → **µm**, converted to nm in memory. Spacing is 1 nm,
  with two sub-nm grid offsets at the detector joins (995 and 1800 nm).
- Reflectance is 0.004–0.929. It has no NaN, negative or >1 values. No spikes occur between 400 and 2500 nm.
- 35 rocks and 94 measurement spots (rock + surface + spot number), with technical replicates (`-1`, `-2`, …).
  NBOR24 `f`/`w` are read as fresh/weathered (flagged `surface_inferred`). `NBCA24-14` and `NBCA24-14B` are kept
  as separate rocks.
- 12 dark spectra (max reflectance < 0.10) are kept, flagged, and their evidence is down-weighted (×0.8).
- Detector-join steps are statistically detectable but ≤ 0.28 % of the mean reflectance, so they are not
  corrected. Full details are in `outputs/phase1/quality_report.md`.

## How a prediction is made

```
spectrum ─► unit detection (µm→nm) ─► quality flags
        ─► resample to 400–2500 nm @ 1 nm (350–399 nm excluded: outside engine range, ~7x noisier)
        ─► Savitzky–Golay 11 nm smoothing (copy) ─► upper convex-hull continuum removal
        ─► absorption features (centre, depth, FWHM, start/end, area; ≥1 % prominence, ≥8 nm FWHM)
        ─► i.hyper.spectroscopy rules on the FEATURES (not on 2101 raw bands)
        ─► 210-value continuum-removed vector ─► PCA ─► K-Means cluster + cosine nearest spectra
        ─► evidence fusion ─► INFERRED / OBSERVED / UNKNOWN
```

**Why not feed the raw spectrum to the engine?** The engine treats every band as a candidate absorption.
At 1 nm sampling, ~46 of 58 rules fire on every spectrum, and the same class wins almost everywhere. We pass
one triplet per extracted feature, plus continuum "anchor" triplets (value 1.0) at the feature shoulders.
The anchors make the engine's own depth calculation equal our continuum-removed depth. This is verified by a test.

**The unsupervised model.** PCA (95 % variance, 6 components) and K-Means (k chosen by silhouette over 2–10;
k = 2, silhouette 0.567) are fitted on **one averaged vector per measurement spot** (94). This stops a spot
measured four times from counting four times. All 170 spectra are then projected as the reference library.
Seeds are fixed (`random_state=42`), and refitting reproduces identical clusters (tested).

**Ranked candidate system (`src/fusion.py`).** Candidates come from four sources:
1. **Rule engine.** Composite rules that fired on the spectrum's own absorption features.
2. **Absorption features.** Rules that did not fire but whose required absorptions are partly present. These
   count at most half, which gives E ≤ 0.29, so a partial match is never a spectral source on its own.
3. **Similar reference spectra.** Their rule-based hypotheses are pseudo-labels, **not ground truth**.
4. **Cluster.** The same pseudo-labels within the spectrum's cluster.

**Groups vs specific minerals.** In these rocks, talc, dolomite, ankerite, calcite, siderite and the asbestos
rules are all triggered mainly by the **same ~2320–2345 nm absorption**. Rules that share their deepest
feature and score within 0.10 of each other cannot be separated by the engine, so the system reports a
**chemical-family group**, e.g. *Carbonate mineral group: 1. dolomite 2. ankerite*. Members are ordered by
member-level support; that order is a ranking, not an identification. A **specific mineral** is returned only
when one rule stands alone **and** at least two independent sources support it.

**Evidence confidence** (0–1, **not a probability**). The formula is the same as in v1:

```
EC = Q × (0.5·E + 0.3·N + 0.2·C)
E = own-spectrum evidence: rule score × feature strength   (feature strength = min(1, mean matched depth / 0.05))
    partial (non-fired) rule: 0.5 × rule score × feature strength × matched share (< 1)
N = similarity-weighted Jaccard agreement with the 5 most similar reference spectra
    (one per rock, the query's own rock excluded) × feature match (do they share the query's absorptions?)
C = Jaccard agreement with the pseudo-labels in the query's cluster × mean neighbour feature match
Q = 0.8 dark spectrum, 0.7 novel / out-of-distribution, 0.9 interpolated gaps (multiplied)
```

**Decision levels** (applied to the best eligible candidate; eligible = plausible for rock and ≤ 3 chemical
families):
- **INFERRED / HIGH.** EC ≥ 0.45, ≥ 2 supporting sources (E ≥ 0.40, N ≥ 0.50, C ≥ 0.50) and own-spectrum
  evidence (E > 0). This is the same condition v1 used for INFERRED.
- **INFERRED / MODERATE.** The spectrum's own rule evidence alone (E ≥ 0.40), or ≥ 2 sources with EC < 0.45.
  Alternatives are always shown, and the confidence number is **not** raised.
- **OBSERVED.** Absorptions ≥ 2 % deep are measured, but no candidate qualifies.
- **UNKNOWN.** No usable absorption, conflicting evidence (the similar spectra clearly favour a different
  hypothesis), or a spectrum that fails the quality checks.

Pseudo-labels alone can never produce INFERRED: own-spectrum evidence (E > 0) is always required. Every
result carries a **"Why this prediction?"** list naming each evidence source, its value and whether it
contributed. Rule groups from categories that make no sense for rock spectra (vegetation, water, plastics,
urban, ice) are reported but can never become the prediction. Results that include asbestos rules always
carry a "confirm by XRD/microscopy" warning.

**Rule score** is the engine's heuristic `base_score × (1 + 0.05 × bonus species)`. It is a fixed prior per
rule, not a probability.

## Results on the 170 reference spectra (each predicted with its own rock excluded)
From `outputs/model_evaluation.md` and `outputs/comparison_vs_v1.md`:

| outcome | v1 fusion | v2 ranked candidates |
|---|---|---|
| INFERRED — specific mineral | 0 | 0 |
| INFERRED — mineral group, HIGH | 46 | 80 |
| INFERRED — mineral group, MODERATE | — | 90 |
| OBSERVED | 124 | 0 |
| UNKNOWN | 0 | 0 |

- No spectrum gets a specific mineral: no single, separable rule has two independent supporting sources.
- Every reference spectrum has a measured 2300–2350 nm absorption (own-spectrum evidence E ≥ 0.57), so a
  family-level claim is supported for all 170. The groups are Carbonate (75), Mg-OH silicate / Carbonate (40),
  Mg-OH silicate / Fe-OH amphibole / Carbonate (30), Fe-OH amphibole / Carbonate (24) and Sulphate (1).
  Results whose best alternative is within 0.03 in evidence confidence carry a "near-tie" warning.
- **Confidence was not inflated.** All 170 spectra keep the same best candidate as v1, and their evidence
  confidence is identical (maximum change 0.000000). MODERATE results have a median confidence of 0.58,
  versus 0.69 for HIGH.
- Technical replicates with the identical final prediction: 67.0 % of 112 pairs (see limitations).
- Technical replicates in the same cluster: 98.2 %. Same-rock pairs: 90.9 % (random different-rock baseline 80.6 %).
- Absorption features (≥ 3 % deep) reproduced within ±10 nm in the replicate: 77.0 %.
- The nearest different-rock spectrum has a matching rule hypothesis (Jaccard ≥ 0.5) in 71.2 % of cases.

These numbers measure **consistency**, not correctness.

## Outputs
| Path | Content |
|---|---|
| `models/spectral_model.joblib` | Fitted PCA, K-Means, reference library, thresholds, preprocessing config |
| `models/model_card.json`, `models/preprocessing_config.json` | Human-readable model and preprocessing parameters |
| `outputs/predictions.csv` / `.json` | Prediction, type, evidence confidence, R/N/C/Q, features and warnings for all 170 spectra |
| `outputs/absorption_features.csv` | All extracted features |
| `outputs/model_evaluation.md` | Label-free evaluation |
| `outputs/comparison_vs_v1.md` | Outcome counts and confidence check against the previous fusion layer (`baseline_v1_predictions.csv`) |
| `outputs/pca_clusters.png`, `outputs/example_spectrum_features.png` | Figures |
| `outputs/phase1/` | Data-quality report, per-sample metrics, flags, replicate consistency |
| `logs/` | Run logs |

## Limitations
- **No ground truth.** Predictions are not validated, and evidence confidence is not calibrated.
- **The engine is generic and permissive.** It was designed for imaging spectrometers, not lab spectra of these
  rocks. It has no quartz or feldspar class, and its overlapping wavelength ranges mean one ~2320 nm feature
  satisfies several mineral rules. Predictions are therefore mostly family-level groups, not specific minerals.
- **MODERATE results rest on the spectrum's own rule evidence only.** They are candidate interpretations; read
  them together with the alternatives.
- **Replicates agree on the final prediction for only 67 % of pairs.** Small differences in feature depth
  decide which rules fire. For example, `NBOR24-09_w3` gives a Sulphate group and its replicate a Carbonate group.
- **The reference library contains these 35 rocks only.** A genuinely new mineral (e.g. a clay) can have
  strong rule evidence but no supporting neighbours. It then gets at most MODERATE support, with a
  "novel spectrum" warning.
- **k = 2 is coarse** (152 / 18 spectra). Cluster agreement therefore carries limited information and has the
  smallest weight.
- The 2400–2500 nm edge is ~3x noisier. Features touching 400 or 2500 nm are marked `edge_truncated`.
- All weights and thresholds are documented engineering choices, not values fitted to labels.

## Future improvements
- Get mineralogical ground truth (XRD) for a subset. That would allow honest validation and calibration, and
  a supervised classifier evaluated with grouped (by-rock) cross-validation.
- Compare against a measured spectral library (e.g. USGS splib07) to separate carbonate from Mg-OH minerals
  by band position and shape.

## Project layout
```
68026941d4be0210cde07d8c.csv   original data (read-only)
i.hyper.spectroscopy-main/     original rule engine repository (unmodified)
data/                          example (synthetic) new-spectrum input
src/                           data_loader, quality, preprocessing, features, engine, analysis,
                               fusion, model, predict, evaluation, visualization
tests/                         test_data.py, test_detector.py
models/  outputs/  logs/       generated by run_pipeline.py
app.py  predict.py  run_pipeline.py  requirements.txt
```
