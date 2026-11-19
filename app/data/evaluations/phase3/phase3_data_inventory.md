# Phase 3 Data Inventory

Generated: 2026-09-27T20:37:52.403799+00:00

- Workspace: `D:/workspace`
- Source: Kaggle waste-image dataset (owner-provided; URL not found in repository)
- Image records: 11521
- Phase A valid / invalid: 11521 / 0
- Phase 3 quality statuses: `{"PASS": 8290, "WARN": 3231}`
- Image formats: JPEG: 10748, PNG: 773
- Distinct dimensions: 5941
- Total image bytes: 5837867616
- Project files inventoried: 11643
- Metadata/document files: 34
- Assessment/annotation files found: 0
- Missing source URL/date/verified ground truth: `{"source_url": 11521, "acquisition_date": 11521, "verified_ground_truth": 11521, "missing_source_label": 0}`
- DINOv2 aligned rows: 11521
- Duplicate/near-duplicate groups: 723

## Existing Source Categories

| Category (source label only) | Original split | Records |
|---|---:|---:|
| automobile wastes | train | 871 |
| battery waste | train | 848 |
| E-waste | train | 1248 |
| glass waste | train | 1022 |
| light bulbs | train | 420 |
| metal waste | train | 1231 |
| organic waste | train | 889 |
| paper waste | train | 1370 |
| plastic waste | train | 1315 |
| automobile wastes | test | 218 |
| battery waste | test | 213 |
| E-waste | test | 312 |
| glass waste | test | 256 |
| light bulbs | test | 105 |
| metal waste | test | 308 |
| organic waste | test | 223 |
| paper waste | test | 343 |
| plastic waste | test | 329 |

## Provenance and Ground Truth

The owner identifies the source as a Kaggle waste-image dataset, but the repository contains no original URL or acquisition date. Directory categories are unverified source labels. No verified human/expert/laboratory ground truth was found. No synthetic dataset or persisted assessment records were found in the inspected data locations.

## Existing Phase B Artifacts

- Embeddings: `D:/workspace/data/embeddings/dinov2_vits14`
- Cluster outputs: `D:/workspace/data/embeddings/clusters`
- Existing clusters and embeddings were reused; no DINOv2 recomputation was performed for this inventory.
