# Controlled Evaluation Candidate Set v1

- Items selected: 295
- Ground-truth status: `GROUND_TRUTH_LIMITED`
- Deterministic seed: 20260928
- Source-category coverage: `{"E-waste": 28, "automobile wastes": 28, "battery waste": 31, "glass waste": 47, "light bulbs": 28, "metal waste": 40, "organic waste": 30, "paper waste": 34, "plastic waste": 29}`
- Selection reasons: `{"automated_quality_warning_or_review": 25, "cluster_representative_candidate": 4, "deterministic_source_category_coverage": 225, "duplicate_or_near_duplicate_risk": 25, "low_cluster_boundary_margin_candidate_for_review": 25}`
- Items are held in the duplicate-aware test split and are not training-eligible by default.

Coverage reasons include deterministic source-category coverage, available cluster representatives, automated quality warnings, low cluster-boundary margin candidates, and duplicate-risk candidates. These are candidates for human review, not fabricated labels or a verified benchmark. Mixed/unknown material cases require expert annotation; none are claimed to be confirmed by this audit.
