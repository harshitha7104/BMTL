# CLAUDE.md — BMTL (Black Mass Trust Layer), real-data edition

Rebuilt 2026-11-16 on ACE's real company data. The synthetic-data era (Phases 1–9) is in
`archive/synthetic_era/` (see its `ARCHIVE_README.md`); do not import from it.

## Purpose
Assess lithium-ion battery black mass from handheld XRF (Bruker S1 TITAN, SPECTRO xSORT) against ICP-OES,
with uncertainty, and serve it through the ScrapTrust app (chat Copilot + web). Every quantity is labelled:
- **OBSERVED**: the instrument's own value (gun reading, ICP result).
- **INFERRED**: model estimate, always with a 90 % band and its training basis.
- **UNKNOWN**: not supportable (censored "< LOD", missing element, no model). Never invent a value.

## Layout
| Path | Role |
|---|---|
| `data/raw/ace_company/` | company files, **read-only**, checksummed (`SHA256SUMS`); original in `D:\ace comapny data\` (never modify) |
| `data/interim/real/xsort_transcription.csv` | xSORT screen values transcribed by hand from photos (verify against originals) |
| `data/processed/real/` | built dataset (regenerate, don't edit) |
| `src/realdata/` | `pdz.py` (.pdz reader), `bruker_csv.py`, `icp_xlsx.py`, `build_dataset.py` |
| `src/realdata/extract.py`, `ocr_screen.py` | element values from ANY input: CSV/TSV/XLSX/JSON (any column names, either orientation), free text / PDF text / transcripts, photos of XRF screens (local OCR) |
| `src/realmodels/` | `train.py` (element correction, bands, LiX lithium, material detector), `predict.py` (`assess_reading`), `compound.py` (names the cathode compound: NMC111/532/622/811, NCA, LCO, LMO, LFP, mixed), `augment.py` (AUGMENTED replicates/blends) |
| `data/processed/augmented/` | augmented training rows (never evidence, never used to report accuracy) |
| `models/real/`, `reports/real/` | fitted models + model card; LOSO evaluation + `REPORT.md` |
| `tests/real/` | pipeline tests (root venv) |
| `app/` | ScrapTrust (merged from `D:\workspace`): `backend/` FastAPI + Copilot, `src/` React web, `mineral/` spectral engine, `wastes/` + `data/` image dataset |
| `app/backend/app/copilot/engines/black_mass.py` | bridge: Copilot tools `assess_black_mass_xrf` (any attachment kind or text), `get_black_mass_model_info` → `src/realmodels` |
| `app/backend/app/copilot/agents/` | AI agent team: `checker.py` (every composition number in a reply must trace to tool output; Claude repairs once, else flagged), `lot.py` (lot-analyst: spread, outliers, ICP plan), `report.py` (report-writer: Word .docx saved as a "report" attachment), `speech.py` (spoken summary for hands-free voice mode, `app/src/components/chat/VoiceMode.tsx`). All deterministic; work without an AI key |
| `app/backend/app/records/` | `store.py` records.db (`app/backend/data/records/`): admin activity log (FTS search, day/month/year calendar), per-user library (rename/pin/open, TXT/PDF via dependency-free `pdf.py`), structured observations (UNLABELLED until an admin attaches ICP), learning runs; `hooks.py` records every chat turn. Routes `api/routes/library.py` (own items only, 404 otherwise) and `api/routes/admin_records.py` (admin role only). Import old chats: `scripts/backfill_records.py` |
| `src/realmodels/learning.py` | self-learning: retrain a candidate on real + CONFIRMED field rows, compare on the original samples held out, promote only if clearly better (backup in `models/history/`); run via `scripts/housekeeping.py --learn` |
| `app/backend/app/copilot/engines/intake.py` | folders/zip (bomb + traversal safe) and links (SSRF safe) |
| `app/backend/app/core/security.py`, `middleware.py`, `ownership.py`, `routes/auth.py` | login, roles, ownership, rate limits, headers; threat model in `docs/SECURITY.md` |
| `docs/spec/BMTL Model Stack v0.pdf` | original spec (Li rule superseded, see below) |

## Commands (Windows)
```
.venv/Scripts/python.exe -m src.realdata.build_dataset      # raw company files -> data/processed/real/
.venv/Scripts/python.exe -m src.realmodels.train            # -> models/real/, reports/real/ (overwrites; cheap, deterministic)
.venv/Scripts/python.exe -m pytest -q                       # tests/real
app/ScrapTrust.bat                                          # web app + API + Copilot on http://localhost:8010
cd app/backend; ./venv/Scripts/python.exe -m pytest -q      # app tests (own venv)
```

## Data facts
- 9 ICP-referenced samples A, B, C, 1–6 (in-house master ICP in the BMTL_Output_vs_ICP workbooks; Sample A's
  secondary "shared with Bruker" table disagrees — in-house is the reference, user decision 2026-11-16).
- Bruker readings 839–847 (26 Oct, 90 s, .pdz 01287–01295) = A,B,C,1–6, confirmed by Bruker's report. 120 s values only
  in the workbook (.pdz 01305–01313 not supplied). 19-Oct readings: 6 MATCHED by composition, 4 AMBIGUOUS (twins 1|3, 4|5,
  never trained on), 17 UNLABELLED.
- .pdz holds factory AND "Black mass powder" type-standardised values + 3x2048-channel spectra. Bruker had the ICP of
  A,B,C,1,2,3 before the standardisation, so standardised values may be partly fitted to them; factory is the clean view.
- Sample 6 (Co 57.8 %) is out of domain: never fitted, reported separately.
- xSORT: 29 readings; Ni ~72–79 % screens are an alloy-mode artefact; lead paste / Pb / Li2CO3 bags are negatives.

## Modelling rules
- Evaluate leave-one-SAMPLE-out (all readings of a sample held out together). Never report in-sample numbers as accuracy.
- Element correction: univariate linear per element per calibration basis; keep it only if it beats the raw gun by
  >= 10 % out-of-sample, else pass-through. PLS only once >= 30 paired samples exist.
- **Lithium from XRF metals is allowed (user decision 2026-11-16, supersedes the spec's LIBS-only rule):** LiX =
  Li per transition-metal atom (Fe counted only with P), fitted on ICP Li, always INFERRED with band; XRF never "measures" Li.
- Labels: CONFIRMED / MATCHED only become training rows; AMBIGUOUS and UNLABELLED never do. Inferred labels are INFERRED.
- Censored "< LOD" stays censored (None + flag), never 0, LOD or LOD/2.
- Every report carries the banner in `src/realmodels/train.py` (BANNER); reports are generated from computed values.
- Never fabricate measurements, labels, calibrations or pairings. Ask the user for missing data instead.
- **AI provider: offline only (manager decision 2026-11-17: do not use Anthropic).** `COPILOT_PROVIDER=offline`; agents run deterministically. Any other provider needs the user's confirmation first.
- Augmentation (manager request 2026-11-16) is allowed only as clearly labelled AUGMENTED training rows with parent samples;
  LOSO drops every augmented row descended from the held-out sample. Augmented or synthetic rows are used only if they beat
  the real-only model out-of-sample (element: >= 5 %). Result so far: no gain for element correction; synthetic v2 HURTS the
  detector (abstention 2.5 % -> 17.5 %), so real-only is selected. Report this honestly; never present augmented rows as data.
- OCR'd photo values are OBSERVED-from-photo, never measurements; unlabelled numbers are never assigned; totals > 105 % are refused.

## Security rules (app)
- Every `/api/v1` route needs a signed-in user; per-object ownership answers 404 for others' objects. Never add a route without
  `current_user` (router-level dependency in `main.py`) and an ownership check for user data.
- Never serve user uploads inline except images/audio/video with a server-chosen type. Never fetch URLs except via `intake.fetch_link`.
- Tests run in `disabled_local_dev`; `tests/test_security.py` covers `required` mode — keep it green.
- Shared state lives in `app/backend/data/security/security.db` (SQLite WAL: users, rate limits, ownership, session index,
  revoked tokens, audit log; `app/core/db.py`). Never reintroduce JSON/in-memory state for these (breaks multi-worker).
- Models load only via `app/core/models_safe.py` (vendored DINOv2, pinned CLIP revision, SHA-256-checked weights). Never call
  `torch.hub.load` on a remote repo or `from_pretrained` without a pinned revision.
- `EarlyGuard` (`app/core/middleware.py`) must stay the outermost middleware: Host allow-list (set `TRUSTED_HOSTS` in production; loopback only in local-dev), early 401 before multipart parsing, streamed size cap. Local-dev mode only serves loopback clients.
- Office files go through `check_office_zip` before any parser. Conversation writes use `CopilotService._session_lease` (cross-process).
- Model files load only via `verified_model_path` (SHA-256 in `model_card.json`). Self-learning only stages candidates in `models/candidates/`; a person activates one with `python -m src.realmodels.learning --activate <stamp>`.
- Audit + fix status: `docs/SECURITY_AUDIT_2026-11-17.md`; regression tests `app/backend/tests/test_audit_fixes.py` and `test_audit_fixes_2.py`.
- Untrusted text shown in answers goes through `md_safe()` (offline provider); tool errors never show paths; the activity log is an HMAC chain (`GET /api/v1/admin/records/integrity`).
- Production image installs only `app/backend/requirements-image.lock` (hash-locked, tested versions); regenerate it after any
  requirements change (see `requirements-image.in`). Test tools live in `requirements-dev.txt`.
- Keep `pip-audit` and `npm audit` at 0 before any release. Deployment: `deploy/` (Docker, Caddy, compose) and
  `deploy/DEPLOYMENT.md`; testing-session script: `docs/TESTING_SESSION.md`.

## Open data requests
In-house ICP sheets behind the company's LiX (44 results, 18 lots); 120 s .pdz 01305–01313; WhatsApp folders 9–14;
operator log for 19-Oct readings 788–799 / 806–814.

## Conventions
Module docstring with provenance caveats; `from __future__ import annotations`; type hints; `pathlib`;
`ROOT = Path(__file__).resolve().parents[2]`; pure functions + `run()` orchestrator with output-root args.
The app keeps its own conventions (see `app/README.md`, `app/docs/`). `app/backend/.env` holds API keys: never commit.
