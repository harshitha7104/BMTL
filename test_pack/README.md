# ScrapTrust / BMTL test pack (built 2026-11-17)

Copies of real company files plus a few hand-made edge cases, for testing the Copilot
(`assess_black_mass_xrf`) and the web app. The originals in `data/raw/ace_company/` were not changed.
Open the app with `app/ScrapTrust.bat` → http://localhost:8010, then attach the files in chat.

## Photos (xSORT screens, OBSERVED-from-photo). Each reading has two photos (a, b)
| File | Reading | What it should do |
|---|---|---|
| `01_nmc_ok_reading30_*` | 30, bag B-19217-TECHE-16, NMC | Normal reading: Ni ≈13.64, Co ≈8.37, Mn ≈9.13, Cu ≈3.40 (Fe not shown) → INFERRED assessment with bands |
| `02_nmc_ok_reading43_*` | 43, bag TECHE-3, NMC | Normal NMC screen → assessment |
| `03_alloy_artefact_Ni79_reading26_*` | 26, TECHE-14 | Ni ≈79 %, sum ≈100 % (alloy-mode artefact) → should be **flagged**, not trusted as black mass |
| `04_lead_paste_negative_reading56_*` | 56, DS Battery Paste | Lead-acid paste → **negative** (not Li-ion black mass) |
| `05_li2co3_no_result_reading25_*` | 25, Li₂CO₃ bag | "No suitable calibration" screen → **no values / UNKNOWN**, nothing invented |

Exact screen values: `data/interim/real/xsort_transcription.csv` (reading_no column).

## Data files
| File | What it is | Expected result |
|---|---|---|
| `06_sampleA_reading839.pdz` | Bruker S1 TITAN raw file, sample A, 26 Oct 2026, 90 s | Compare with ICP A below |
| `07_sample6_out_of_domain_reading847.pdz` | Sample 6 (Co 57.8 %) | Must say **out of domain** (never fitted) |
| `08_bruker_export_A_2_6.csv` | Bruker CSV export rows for readings 839 (A), 843 (2), 847 (6) | Three readings; sample 6 out of domain, Ni UNKNOWN |
| `09_typed_reading_sampleA.txt` | Reading 839 typed as text | Same as A |
| `10_messy_columns_sample2.csv` | Odd column names, `;` separator, reading 843 | Columns recognised; compare with ICP 2 |
| `11_censored_lod.txt` | `Ni < LOD` | Ni stays **censored** (not 0 or a guess) |
| `12_bad_total_over_105.txt` | Values sum to 120 % | **Refused** as implausible |

## ICP reference to check against (in-house master ICP, wt %)
| Sample | Ni | Co | Mn | Li |
|---|---|---|---|---|
| A | 2.13 | 14.49 | 10.32 | 1.99 |
| 2 | 10.61 | 11.38 | 15.34 | 3.40 |
| 6 (out of domain) | 0.51 | 57.82 | 0.29 | 6.82 |

Samples A and 2 are in the training set, so a close match is expected and is **not** a measure of accuracy.
Real accuracy is the leave-one-sample-out figure in `reports/real/REPORT.md`.

## Note on sample 6 (reading 847): Ni is UNKNOWN, Cu reads high
Bruker reports **no Ni** for reading 847: it isn't in the CSV header block for that row or in the `.pdz`. With Co at 46–71 %,
the Co Kβ line (7.65 keV) covering Ni Kα (7.48 keV) is the likely reason; this hasn't been confirmed with Bruker. The app should show Ni as **UNKNOWN**, not 0.
Cu is 0.66 % type-standardised but 0.019 % factory (ICP 0.015 %). The standardisation inflates Cu for this out-of-domain sample.
In file 08 each row has its own Bruker header block, the same as the original export. Using one header for all rows misaligns the
columns. File 08 labels the readings by Bruker file number (1287 / 1291 / 1295), not reading ID (839 / 843 / 847).
