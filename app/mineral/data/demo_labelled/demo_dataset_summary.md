# DEMO pseudo-labelled dataset

> **These are PSEUDO-LABELS, not ground truth.** They were generated from the existing i.hyper.spectroscopy rule engine applied to absorption features extracted by this project's pipeline, and checked against similar spectra, replicates and data quality. No mineral identity has been verified (e.g. by XRD). Use them for demonstration only.

- Source: the 170 spectra of `68026941d4be0210cde07d8c.csv` (unchanged; reflectance values copied verbatim). No spectra were fabricated, resampled or duplicated.
- **Samples selected: 100** from 29 rocks
- **Unique pseudo-labels: 4**
- **Rejected / not selected: 70**

## Acceptance criteria (all required)
- Fusion layer returned INFERRED with an eligible, plausible rock/mineral hypothesis
- Own-spectrum rule evidence E ≥ 0.4; deepest supporting absorption ≥ 3 %
- Most similar other-rock spectrum shares ≥ 50 % of its absorption depth
- Replicates of the same spot agree (≥ 50 % compatible) when replicates exist
- Not dark (low albedo), not novel/out-of-distribution, no near-tie with an alternative, no QC error
- At most 100 samples; if more pass, classes are filled round-robin by confidence (no oversampling)

## Pseudo-label definition
Each spectrum's rule engine output is a set of composite rules the engine cannot separate (they rest on the same deepest absorption). These sets fall into chemical-family classes; each class is labelled with the **union** of its member rules (a weaker claim than any individual set — it never adds certainty). The exact per-spectrum rule set is kept in `demo_labels.csv` (`rule_set`).

## Class distribution

| family class | pseudo_label | samples | rocks |
|---|---|---|---|
| Carbonate | ankerite / calcite / dolomite / siderite | 38 | 14 |
| Fe-OH amphibole + Carbonate | ankerite / calcite / crocidolite_asbestos / dolomite / siderite | 15 | 8 |
| Mg-OH silicate + Carbonate | calcite / chrysotile_asbestos / dolomite / siderite / talc | 25 | 13 |
| Mg-OH silicate + Fe-OH amphibole + Carbonate | calcite / chrysotile_asbestos / crocidolite_asbestos / dolomite / siderite / talc | 22 | 6 |

## Mineral groups that could not be separated
- **Carbonate**: 4 different indistinguishable rule sets occur, e.g. `ankerite / dolomite`
- **Fe-OH amphibole + Carbonate**: 4 different indistinguishable rule sets occur, e.g. `ankerite / calcite / crocidolite_asbestos / dolomite`
- **Mg-OH silicate + Carbonate**: 7 different indistinguishable rule sets occur, e.g. `calcite / chrysotile_asbestos / dolomite / talc`
- **Mg-OH silicate + Fe-OH amphibole + Carbonate**: 6 different indistinguishable rule sets occur, e.g. `calcite / chrysotile_asbestos / crocidolite_asbestos / dolomite / siderite / talc`
- All classes share the ~2320–2345 nm absorption; Mg-OH silicate classes additionally have a ~2380–2390 nm absorption (talc rule), Fe-OH amphibole classes a ~440 nm Fe³⁺ absorption (crocidolite rule). Asbestos rule names are spectral hypotheses only and need mineralogical confirmation.

## Pseudo-label confidence
pseudo_label_confidence = evidence confidence × replicate factor (0.5 + 0.5 × replicate agreement; 0.75 if no replicates). It is never higher than the evidence confidence and is not a probability.
- min 0.439, median 0.647, max 0.768
- Evidence status: {'multi_source_high_replicates_consistent': 49, 'single_source_moderate_replicates_consistent': 27, 'multi_source_high': 11, 'single_source_moderate': 8, 'single_source_moderate_replicates_mostly_consistent': 3, 'multi_source_high_replicates_mostly_consistent': 2}

## Rejection reasons (a spectrum can have several)

| reason | spectra |
|---|---|
| unlike other reference spectra (novel / out-of-distribution) | 21 |
| absorptions not shared by the most similar other-rock spectrum | 21 |
| replicates of the same spot disagree | 19 |
| passed evidence checks but not selected (class balance cap of the demo set) | 13 |
| dark spectrum (low albedo): kept in data, not used as pseudo-label | 12 |
| conflicting evidence: alternative hypothesis almost equally supported | 4 |

## Demo classifier
- Pseudo-label validation performance (NOT mineral accuracy): accuracy 0.660, balanced accuracy 0.645, macro F1 0.631 (majority baseline 0.380); grouped by rock. See `outputs/demo/pseudo_label_validation.md`.
