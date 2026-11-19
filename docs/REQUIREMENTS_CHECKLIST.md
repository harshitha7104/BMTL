# Requirements checklist — BMTL vs the two source documents

Checked 2026-11-17 against:
- **A** = *Black Mass Composition Assessment — Discussion Summary* (25 Sep 2026)
- **B** = *BMTL Model Stack v0* spec (24 Oct 2026)

Analysis only — nothing in the system was changed. Status: ✅ done · 🟡 partly / done differently · ❌ not done · ⏸ blocked by missing data.
All accuracy numbers are leave-one-sample-out on the 8 in-domain ICP-referenced samples (sample 6 excluded), wt% points.

## 1. Discussion summary (A)

| # | Requirement | Status | Evidence / what is missing |
|---|---|---|---|
| A1 | Estimate **Ni, Co, Li** at or near the point of handling without lab digestion (first priority) | 🟡 | Ni: error 0.68 (factory) / 0.88 (standardised). Co: 1.27–1.61 — weakest. Li: 0.43, inferred from XRF metals (XRF cannot see Li). Works end to end; only 9 lab samples, so "reliable" is not yet proven |
| A2 | Technology chain Material → Sensing → Measurement → Composition estimate → **Validation against lab** | ✅ | XRF (.pdz / CSV / photo) → corrected estimate → compared with in-house ICP, reported in `reports/real/REPORT.md` |
| A3 | Imaging alone is not enough; use sensing beyond photos | ✅ | Photos are used only to read instrument screens and flag material type, never to estimate composition |
| A4 | Investigate several sensing methods (XRF, LIBS, ultrasonic, EM/radar, spectral) | 🟡 | Two XRF guns used (Bruker S1 TITAN, SPECTRO xSORT). LIBS: no black-mass LIBS data. Ultrasonic / EM / radar: none. Research shortlist exists in the company portal pages, not in the software |
| A5 | Elements of interest incl. Mn, Fe, P, Al, Cu | ✅ | All corrected with bands; Pb/Zn read when present |
| A6 | Action 4: collect varied samples **with lab results** | ⏸ | 9 ICP samples (A, B, C, 1–6). Open: the 44 in-house ICP results / 18 lots, more lots, US samples |
| A7 | Action 5: hands-on testing vs lab, not a long theory study | ✅ | Bruker trial (19 and 26 Oct) data parsed and used; xSORT photos transcribed and used |
| A8 | Out of scope now: trading, customs, payments | ✅ | Not built (note: spec B §2.6 adds a commercial decision step — see B6) |
| A9 | Future: lead battery materials, ores, copper | 🟡 (ahead) | Lead-acid paste and lead are *recognised as not black mass*; not quantified (Pb/Sb/Sn) |
| A10 | Success question: "sufficiently reliable estimate near the handling point?" | ⏸ | Cannot be answered on 9 samples; needs a blind test on new lots with ICP |

## 2. Model stack spec (B)

### Job 1 — Element correction (Ni, Co, Mn, Cu, Fe, Al) — §2.1

| Requirement | Status | Evidence / gap |
|---|---|---|
| One correction model per element → ICP-equivalent wt% | ✅ | 7 elements × 2 calibration bases |
| < 4 samples pass-through; ≥ 4 linear; ≥ 30 PLS | 🟡 | Pass-through / linear / proportional in use (8 samples). **PLS not built on real data** — threshold of 30 not reached |
| Choose simplest model; a richer one must be > 10 % better on held-out lots | ✅ | Correction kept only if ≥ 10 % better than the raw gun; alternatives need a stable win in a nested test and ≥ 5 % |
| Input: factory-mode value **averaged over spots** | 🟡 | Factory values read from .pdz ✅; only one spot per sample, so no spot averaging |
| Input: net Kα peak areas (Mn, Fe, Co, Ni, Cu, Al), background-subtracted | ❌ | Raw spectra are parsed from .pdz (3 × 2048 channels) but **no peak-area features yet** (energy calibration not set up) |
| Input: normalise to Rh Compton scatter band 18.5–19.6 keV | ❌ | Not built |
| Input: ratios Ni/Co, Ni/Mn, Fe/Ni | 🟡 | Used in the chemistry detector, not in element correction |
| Input: spot-to-spot Ni spread (heterogeneity) | ❌ | Needs several spots per sample |
| Full spectrum for PLS (1–25 keV, 0.05 keV steps) | ❌ | Not built (needs ≥ 30 samples anyway) |
| Leakage control: grouped by lot, sample never on both sides | ✅ | Leave-one-sample-out; augmented rows from the held-out sample are removed |

### Job 2 — Uncertainty band — §2.2

| Requirement | Status | Evidence / gap |
|---|---|---|
| Split-conformal band at nominal 90 % | ✅ | Jackknife+ style from held-out residuals |
| Band clipped at 0 wt% | ✅ | Lower edge floored at 0 |
| Inflate × 1.5 with very few samples | ❌ | Not applied |
| Band honesty: ICP inside band in 85–95 % of held-out cases | 🟡 | **8 of 14** element/basis combinations inside 85–95 % (corrected 17 Nov: the report now measures the band of the model actually served). Below target: factory Co, Cu, Fe, Mn, P (75–83 %) and standardised Mn (83 %) — bands too narrow for those; more samples needed |

### Job 3 — Chemistry family — §2.3

| Requirement | Status | Evidence / gap |
|---|---|---|
| Logistic regression → NMC / LFP / MIXED + probability | 🟡 | Built as **k-nearest-neighbour + chemistry rules** (classes NMC, LCO, LFP, lead paste, instrument artefact); 100 % correct on decided readings, 2.5 % abstain (40 readings, 28 bags/samples). Different method and class set from the spec |
| Rule fallback (Ni+Co < 3 & Fe > 5 → LFP; Ni+Co ≥ 8 & Fe < 6 → NMC; else MIXED) | 🟡 | Different rules (LFP by Fe-dominant + P/Fe; lead by Pb share); spec rule not implemented as written |
| MIXED class | 🟡 | Expressed as "Mixed feed / LCO-rich feed" in the compound name, not as a detector class |
| Trained on genuine samples only | ✅ | Real readings only; synthetic data tested and rejected (made it worse) |
| *(beyond spec)* Name the cathode compound (NMC111/532/622/811, NCA, LCO, LMO, LFP) | ✅ | Matches ICP for all 9 reference samples |

### Job 4 — Fraud / unknown-material gate — §2.4

| Requirement | Status | Evidence / gap |
|---|---|---|
| PCA one-class model (Hotelling T² + Q residual), limits from held-out lots | ❌ | **Not built on real data** (existed only in the archived synthetic version) |
| Robust z rules (single > 8; ≥ 2 features > 4.5) | ❌ | Not built |
| Declared vs measured chemistry check | ❌ | The app has no "declared chemistry" input |
| One model per chemistry at ≥ 8 genuine samples / 3 lots | ⏸ | Data too small (spec itself: needs ~10 lots per chemistry) |
| *(partial substitute)* Flag non-black-mass input | 🟡 | Lead paste, lead, lithium salt (no metals), xSORT alloy-mode screens and impossible totals (> 105 %) are caught — not the spec's statistical gate |

### Job 5 — Lithium — §2.5

| Requirement | Status | Evidence / gap |
|---|---|---|
| Li from **LIBS only, never XRF** | 🟡 **changed by your decision (16 Nov)** | Li inferred from corrected XRF metals (per-metal factors), always labelled INFERRED with a band; error 0.43 vs ICP. Spec's hard rule is deliberately overridden |
| LIBS Li 670.78 nm peak, continuum 500–520 nm, cross-check lines | ⏸ | LIBS feature code exists in the archive; **no black-mass LIBS spectra** to train on |

### Decision step — §2.6

| Requirement | Status | Evidence / gap |
|---|---|---|
| Value per kg = Σ (wt% × price × payable), basis Ni + Co + Mn | ❌ | Not in the current system; prices/payables were never supplied |
| RELEASE only if gate IN_DOMAIN, moisture ≤ 5 %, every basis element learned, conservative value ≥ share × estimate | ❌ | No RELEASE / HOLD_FOR_ICP output in the current app; no moisture input. (Archived synthetic version had R1–R8.) Note: doc A puts commercial decisions out of scope for now |
| LFP held under Ni + Co + Mn basis | ❌ | Not built (LFP is identified, no decision attached) |
| Overpay rule | ❌ | Not built |
| Plain-language reason | 🟡 | Every value carries OBSERVED / INFERRED / UNKNOWN and a reason; no decision reason because there is no decision |

### §3 Software bill of materials

| Item | Status | Notes |
|---|---|---|
| scikit-learn 1.9.1, numpy 2.5, pandas 3 | ✅ | In use |
| read-pdz | 🟡 | Replaced by our own `.pdz` reader (no extra dependency; verified against the printed report) |
| Streamlit | 🟡 | Replaced by the merged ScrapTrust web app (React + FastAPI) |
| SQLite → Azure SQL later | 🟡 | SQLite (multi-worker safe, one server); Azure SQL / PostgreSQL still to do for several servers |
| Permissive licences only | ✅ | Plus vendored DINOv2 (Apache-2.0) |

### §4 Later items (spec says "not yet built")

| Item | Status |
|---|---|
| TabPFN at ~30 samples | ❌ not started (licence to confirm) |
| Calibration transfer between guns | ❌ **gap today:** xSORT readings are corrected with the S1 TITAN model, which is not calibrated for xSORT |
| Self-supervised spectral model (> 5,000 spectra) | ❌ not started |
| Multi-sensor fusion (XRF + LIBS + moisture + photo) | 🟡 all inputs accepted in one chat, but not fused into one estimate |
| LLM reporting layer, model-agnostic, never computes numbers | ✅ done early (Claude / OpenAI / Gemini / offline; numbers come only from tools) |

### §5 Known limits of v0 — current position

| Limit in the spec | Now |
|---|---|
| Tested on synthetic data only | ✅ resolved: real ACE data (9 ICP samples, 36 Bruker readings, 29 xSORT readings) |
| Gate needs ~10 lots per chemistry | ⏸ still true; gate not built |
| Li unproven until LIBS | 🟡 Li now from XRF metals (by decision), 0.43 error on 8 samples |
| SQLite suits a small team | 🟡 now multi-worker safe on one server; multi-server still needs a server database |

## 3. Summary

**Done:** element correction with stage switching and leakage-safe testing; uncertainty bands; chemistry/material detection and compound naming; real-data validation against ICP; any-input intake; LLM layer; security and deployment hardening (beyond both documents).

**Partly / done differently:** PLS (not enough samples), spot averaging, chemistry method (kNN instead of logistic regression), lithium (XRF metals instead of LIBS, by decision), several sensing methods (XRF only).

**Not done:** spectral peak-area and Compton features; band × 1.5 inflation; band honesty for 6 of 14 combinations; the PCA fraud gate with declared-vs-measured check; the decision step (value, RELEASE / HOLD_FOR_ICP, moisture, overpay); calibration transfer for the xSORT; TabPFN / self-supervised models.

**Blocked by data:** more ICP-referenced lots (incl. the 44 in-house results), black-mass LIBS spectra, multiple spots per sample, ≥ 30 samples for PLS, ≥ 10 lots per chemistry for the gate.

**Fixed after this check (17 Nov):** the report measured coverage with the straight-line band even where the app serves the raw gun value or the proportional fit. It now measures the band actually served: 8 of 14 combinations meet 85–95 % (was reported as 3). Accuracy figures unchanged.
