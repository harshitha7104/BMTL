# Phase 3 Test Results

Executed with the existing project venv on 2026-09-28.

## Focused Phase 3 Suite

Command: `C:\Users\admin\AppData\Local\Temp\scrap-ai-phase-a-venv\Scripts\python.exe -m pytest backend/tests/test_phase3_data_foundation.py -q`

Result: **12 passed**. No failures or skips.

Coverage includes non-destructive image quality audit, zero-byte/missing file handling, exact/pHash/DINOv2 duplicate groups, embedding/path/status/cluster alignment, source-label trust status, taxonomy generation, deterministic evaluation selection, duplicate-aware split isolation, provenance preservation, evaluation schema/readiness, inventory discovery, and evaluation coverage reporting.

## Full Backend Suite

Command: `C:\Users\admin\AppData\Local\Temp\scrap-ai-phase-a-venv\Scripts\python.exe -m pytest backend/tests -q`

Result: **69 passed, 14 failed, 51 warnings**; exit code 1. No skipped tests were reported.

Existing failures outside Phase 3:

- Seven assessment-route tests and two health-route tests receive an async-generator fixture instead of an `AsyncClient`.
- Three assessment-service integration tests raise `UnboundLocalError` for local variable `quality`.
- One configuration test finds a test API key in the settings string representation.
- One image-validation test uses invalid hand-constructed JPEG bytes, which Pillow cannot decode.

The Phase 3 tests pass independently; these unrelated failures were not modified in this phase.

## Static Check

`C:\Users\admin\AppData\Local\Temp\scrap-ai-phase-a-venv\Scripts\python.exe -m py_compile backend/scripts/phase3_data_foundation.py backend/tests/test_phase3_data_foundation.py` completed without errors.
