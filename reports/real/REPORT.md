# BMTL real-data model report

> **REAL COMPANY DATA — 9 ICP-REFERENCED SAMPLES; SMALL-SAMPLE ESTIMATES, NOT A VALIDATED METHOD**

Trained 2026-11-17 on `data\processed\real`. Every number is leave-one-sample-out (all readings of a sample held out together).

## Element correction (wt%, mean absolute error vs in-house ICP)

| basis             | element   |   n_samples |   n_readings |   mae_raw_gun |   mae_corrected |   mae_linear_augmented | selected_stage   |   mae_selected |   band_coverage |   mean_band_halfwidth |   ood_sample6_err |
|:------------------|:----------|------------:|-------------:|--------------:|----------------:|-----------------------:|:-----------------|---------------:|----------------:|----------------------:|------------------:|
| factory           | Al        |           8 |           12 |         0.428 |           0.775 |                  0.775 | passthrough      |          0.428 |           0.917 |                 0.863 |             0.21  |
| factory           | Co        |           8 |           12 |         5     |           1.61  |                  1.608 | linear           |          1.61  |           0.833 |                 3.908 |            12.375 |
| factory           | Cu        |           8 |           12 |         0.643 |           0.835 |                  0.834 | passthrough      |          0.643 |           0.833 |                 1.981 |             0.004 |
| factory           | Fe        |           8 |           12 |         1.459 |           0.406 |                  0.398 | linear           |          0.406 |           0.833 |                 1.679 |             0.339 |
| factory           | Mn        |           8 |           12 |         1.354 |           0.459 |                  0.456 | linear           |          0.459 |           0.75  |                 1.239 |             0.363 |
| factory           | Ni        |           8 |           12 |         6.546 |           0.681 |                  0.765 | proportional     |          0.681 |           0.917 |                 1.784 |           nan     |
| factory           | P         |           8 |           12 |         0.818 |           0.158 |                  0.166 | linear           |          0.158 |           0.833 |                 1.26  |             0.774 |
| type_standardised | Al        |           8 |           18 |         1.104 |           0.687 |                  0.684 | linear           |          0.687 |           0.889 |                 1.771 |             0.211 |
| type_standardised | Co        |           8 |           18 |         1.272 |           1.658 |                  1.668 | passthrough      |          1.272 |           0.889 |                 2.309 |            12.236 |
| type_standardised | Cu        |           8 |           18 |         0.367 |           0.523 |                  0.524 | passthrough      |          0.367 |           0.889 |                 1.179 |             0.646 |
| type_standardised | Fe        |           8 |           18 |         0.217 |           0.249 |                  0.249 | passthrough      |          0.217 |           0.944 |                 0.445 |             0.34  |
| type_standardised | Mn        |           8 |           18 |         0.479 |           0.428 |                  0.448 | proportional     |          0.428 |           0.833 |                 1.249 |             0.212 |
| type_standardised | Ni        |           8 |           18 |         1.043 |           0.878 |                  1.008 | proportional     |          0.878 |           0.889 |                 1.902 |             0.511 |
| type_standardised | P         |           8 |           18 |         0.144 |           0.202 |                  0.203 | passthrough      |          0.144 |           0.889 |                 0.417 |             0.148 |

`selected_stage` keeps the linear correction only where it beats the raw gun by >= 10 % out-of-sample; otherwise the gun value passes through.
Sample 6 (Co 57.8 %) is never fitted; `ood_sample6_err` shows how far off it lands.

## Lithium (LiX, INFERRED from corrected XRF metals; XRF never measures Li)

| basis             |   mae |   max_err |   n |
|:------------------|------:|----------:|----:|
| factory           | 0.43  |     0.893 |  12 |
| type_standardised | 0.431 |     0.88  |  18 |

Li atoms per transition-metal atom (k): factory = 0.850, type_standardised = 0.870

Company BMTL v0.2.1 mean |gap| on the same 8 samples (its own leave-one-lot-out run; LiX-0.2 for Li; 90 s and 120 s pooled; its Li model also used 44 in-house ICP results that are not in this dataset):

| element   |   company_bmtl_v021_mean_abs_gap_excl_sample6 |
|:----------|----------------------------------------------:|
| Al        |                                         0.632 |
| Co        |                                         2.306 |
| Cu        |                                         0.582 |
| Fe        |                                         0.609 |
| Li        |                                         0.258 |
| Mn        |                                         0.475 |
| Ni        |                                         0.858 |
| P         |                                         0.329 |

## Material / chemistry detector

Evaluation: leave-one-group-out (all readings of one physical sample / bag held out together). Labelled readings: 40 from 28 physical samples/bags.

- Accuracy on decided readings: 1.000; abstention rate: 0.025
- Per-class recall: INSTRUMENT_MODE_ARTIFACT 0.75, LCO 1.00, LFP 1.00, NMC 1.00, NOT_BLACK_MASS_LEAD 1.00
- LFP and lead are decided by explicit chemistry rules (only one LFP sample exists); NMC/LCO by kNN on composition ratios.

### Does extra data help? (scored only on real held-out bags)

|                             |   accuracy_on_decided |   abstention_rate |   extra_training_rows |
|:----------------------------|----------------------:|------------------:|----------------------:|
| real_only                   |                     1 |             0.025 |                     0 |
| real+augmented              |                     1 |             0.025 |                   800 |
| real+synthetic_v2           |                     1 |             0.15  |                   705 |
| real+augmented+synthetic_v2 |                     1 |             0.125 |                  1505 |

Selected: **real_only**. Element correction: augmented fits are listed in `mae_linear_augmented` above and are used only where they beat the real-only fit by >= 5 % out-of-sample. Augmented and synthetic rows are training aids, never evidence.

## Labels inferred for unlabelled readings (INFERRED, confirm before use)

| record   | inferred_label             |   confidence |
|:---------|:---------------------------|-------------:|
| xsort_25 | NO_TRANSITION_METAL_SIGNAL |         0.36 |
| xsort_29 | NOT_BLACK_MASS_LEAD        |         0.34 |
| xsort_41 | NMC                        |         0.88 |
| xsort_45 | NMC                        |         0.55 |
| xsort_47 | NMC                        |         0.91 |
| xsort_58 | NMC                        |         0.93 |
| xsort_59 | NMC                        |         0.8  |
| xsort_60 | NMC                        |         0.69 |
| xsort_61 | NMC                        |         0.79 |
