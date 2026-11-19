# BMTL — Black Mass Trust Layer

Handheld-XRF assessment of lithium-ion battery black mass, trained on ACE's real ICP-referenced samples, served
through the ScrapTrust Copilot (chat + web app).

> **Real company data, 9 ICP-referenced samples.** Accuracy figures are leave-one-sample-out estimates on a very
> small set. Confirm by ICP-OES before any commercial use. See `reports/real/REPORT.md`.

## What it does
- Reads Bruker S1 TITAN `.pdz` files (results + raw spectra) and results exports, the ACE ICP workbooks and
  SPECTRO xSORT readings.
- Corrects gun values to ICP-equivalent wt% for Ni, Co, Mn, Fe, Cu, Al, P, with a 90 % band.
- Estimates lithium from the corrected metals (LiX, always INFERRED).
- Detects material type: NMC, LCO, LFP, lead-acid paste/lead, instrument-mode artefact, or UNKNOWN.
- Names the most likely cathode compound ("mineral"): NMC111/532/622/811, NCA, LCO, LMO, LFP/LMFP, LCO-rich or mixed feed.
- Takes almost anything in the Copilot: typed or spoken values ("Ni 18.1, Co 7.9…"), voice notes, photos of an XRF
  screen or printout (read by local OCR), `.pdz` files, CSV/XLSX/JSON tables with any column names, PDF/text/Markdown
  reports, whole folders (pick a folder or send a .zip) and web links. Every value is labelled OBSERVED / INFERRED / UNKNOWN.
- Sign-in required; each user sees only their own work. Security model and go-live checklist: `docs/SECURITY.md`.

## Start
```
app\ScrapTrust.bat                      # web app + API + Copilot, http://localhost:8010
```
Rebuild data and models (root `.venv`, Python 3.13):
```
.venv\Scripts\python.exe -m src.realdata.build_dataset
.venv\Scripts\python.exe -m src.realmodels.train
.venv\Scripts\python.exe -m pytest -q
```

## Layout
```
data/raw/ace_company/   company files (read-only, checksummed)
data/processed/real/    built dataset
src/realdata/           parsers + dataset builder
src/realmodels/         training + prediction
models/real/            fitted models + model card
reports/real/           evaluation + REPORT.md
tests/real/             pipeline tests
app/                    ScrapTrust: backend (FastAPI + Copilot), src (React), mineral engine, waste image data
archive/synthetic_era/  previous synthetic-data BMTL (kept for reference)
docs/spec/              original BMTL spec
```
Developer guide: `CLAUDE.md`.
