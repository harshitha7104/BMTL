import json
from pathlib import Path

import numpy as np
from PIL import Image

import scripts.phase3_data_foundation as phase3


def _record(path: str, category: str | None = "metal waste", split: str = "train") -> dict:
    return {
        "file_path": path,
        "category_name": category,
        "split": split,
        "is_image": True,
        "is_valid": True,
        "image_format": "JPEG",
    }


def test_image_audit_preserves_source_and_flags_quality(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(phase3, "WORKSPACE_ROOT", tmp_path)
    source = tmp_path / "small.jpg"
    Image.new("RGB", (32, 24), color=(240, 240, 240)).save(source, format="JPEG")
    before = source.read_bytes()

    result = phase3.audit_image(_record("small.jpg"))

    assert result["quality_status"] in {"WARN", "NEEDS_REVIEW"}
    assert "below_existing_quality_gate_minimum_resolution" in result["quality_flags"]
    assert result["file_size_bytes"] == len(before)
    assert source.read_bytes() == before


def test_image_audit_detects_zero_byte_and_missing_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(phase3, "WORKSPACE_ROOT", tmp_path)
    (tmp_path / "empty.jpg").write_bytes(b"")

    zero = phase3.audit_image(_record("empty.jpg"))
    missing = phase3.audit_image(_record("absent.jpg"))

    assert zero["quality_status"] == "FAIL"
    assert "zero_byte_file" in zero["quality_flags"]
    assert missing["quality_status"] == "FAIL"
    assert "missing_file" in missing["quality_flags"]


def test_duplicate_detection_uses_exact_phash_and_embedding_candidates() -> None:
    records = [
        {"file_path": "a.jpg", "sha256": "same", "phash64": "0000000000000000"},
        {"file_path": "b.jpg", "sha256": "same", "phash64": "0000000000000000"},
        {"file_path": "c.jpg", "sha256": "other", "phash64": "0000000000000001"},
    ]
    vectors = np.array([[1, 0], [1, 0], [0, 1]], dtype=np.float32)

    groups, group_by_path, _ = phase3.detect_duplicates(
        records, vectors, {"a.jpg": 0, "b.jpg": 0, "c.jpg": 1}, top_k=2
    )

    assert len(groups) == 1
    assert set(groups[0]["paths"]) == {"a.jpg", "b.jpg", "c.jpg"}
    assert group_by_path["a.jpg"] == group_by_path["c.jpg"]
    evidence_types = set(groups[0]["duplicate_types"])
    assert {"exact_sha256", "phash_hamming_distance", "embedding_cosine_similarity"} <= evidence_types


def test_embedding_alignment_checks_paths_status_norms_and_clusters() -> None:
    records = [_record("a.jpg"), _record("b.jpg")]
    paths = [
        {"file_path": "a.jpg", "image_id": "image_000000", "embedding_index": 0},
        {"file_path": "b.jpg", "image_id": "image_000001", "embedding_index": 1},
    ]
    vectors = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    clusters = [
        {"file_path": "a.jpg", "cluster_id": 0},
        {"file_path": "b.jpg", "cluster_id": 1},
    ]

    alignment, references = phase3.align_embeddings(
        records, paths, np.array([1, 1], dtype=np.uint8), vectors, clusters
    )

    assert alignment["verified"] is True
    assert alignment["aligned_valid_path_count"] == 2
    assert references["b.jpg"]["embedding_index"] == 1
    assert references["b.jpg"]["cluster_id"] == 1


def test_label_audit_never_promotes_source_labels_to_ground_truth() -> None:
    rows, summary = phase3.audit_labels(
        [_record("train/metal waste/a.jpg"), _record("test/unknown/b.jpg", None, "test")]
    )

    assert summary["verified_ground_truth_record_count"] == 0
    assert summary["source_labeled_record_count"] == 1
    assert rows[0]["verified_ground_truth"] is None
    assert rows[0]["unknown_or_unverified_status"] == "UNVERIFIED_SOURCE_LABEL"
    assert rows[1]["unknown_or_unverified_status"] == "MISSING_LABEL"


def test_taxonomy_preserves_only_observed_source_categories() -> None:
    taxonomy = phase3.build_taxonomy(
        {"category_counts": {"battery waste": 5, "metal waste": 9}, "missing_source_label_count": 0}
    )

    assert {item["category"] for item in taxonomy["categories"]} == {"battery waste", "metal waste"}
    assert all(item["ground_truth_verified"] is False for item in taxonomy["categories"])
    assert all(item["label_confidence"] == "UNVERIFIED_SOURCE_LABEL" for item in taxonomy["categories"])
    assert taxonomy["verified_material_composition_claims"] == 0


def test_evaluation_sampling_is_deterministic_and_test_only() -> None:
    audit_records = [
        {
            **_record(f"{split}/{category}/{index}.jpg", category, split),
            "record_id": f"{split}-{category}-{index}",
            "source_label": category,
            "quality_status": "PASS",
            "manual_review_recommended": False,
            "cluster_id": index % 2,
        }
        for split in ("train", "test")
        for category in ("battery waste", "metal waste")
        for index in range(12)
    ]
    labels, _ = phase3.audit_labels([_record(row["file_path"], row["category_name"], row["split"]) for row in audit_records])
    split_design = {"record_split": {row["file_path"]: row["split"] for row in audit_records}}
    cluster_report = {"cluster_summaries": []}

    first = phase3.select_evaluation_dataset(
        audit_records, labels, split_design, {}, {}, cluster_report, per_category=4
    )
    second = phase3.select_evaluation_dataset(
        audit_records, labels, split_design, {}, {}, cluster_report, per_category=4
    )

    assert [row["evaluation_item_id"] for row in first] == [row["evaluation_item_id"] for row in second]
    assert {row["assigned_future_split"] for row in first} == {"test"}
    assert {row["source_label"] for row in first} == {"battery waste", "metal waste"}
    assert all(row["material_category"] is None for row in first)


def test_evaluation_summary_reports_coverage_and_selection_reasons() -> None:
    categories, reasons = phase3.summarize_evaluation_records(
        [
            {"source_label": "battery waste", "selection_reasons": ["category", "quality"]},
            {"source_label": None, "selection_reasons": ["quality"]},
        ]
    )

    assert categories == {"MISSING_LABEL": 1, "battery waste": 1}
    assert reasons == {"category": 1, "quality": 2}


def test_grouped_split_keeps_duplicate_groups_together_and_test_isolated() -> None:
    records = [_record(f"train/metal/{index}.jpg", split="train") for index in range(10)]
    records += [_record("test/metal/duplicate.jpg", split="test")]
    duplicate_groups = {"train/metal/0.jpg": "dup_1", "test/metal/duplicate.jpg": "dup_1"}

    result = phase3.make_leakage_safe_splits(records, duplicate_groups, seed=7)

    assert result["leakage_check_passed"] is True
    assert result["record_split"]["train/metal/0.jpg"] == "test"
    assert result["record_split"]["test/metal/duplicate.jpg"] == "test"
    assert result == phase3.make_leakage_safe_splits(records, duplicate_groups, seed=7)


def test_master_manifest_preserves_provenance_and_unknown_ground_truth() -> None:
    audit = [{
        **_record("data/raw/wastes/train/metal waste/a.jpg"),
        "record_id": "rec_a", "quality_status": "PASS", "quality_flags": [],
        "file_size_bytes": 123, "sha256": "hash", "phash64": "0" * 16,
        "width": 300, "height": 300, "original_split": "train", "cluster_id": 2,
    }]
    labels = [{
        "image_path": audit[0]["file_path"], "source_label": "metal waste",
        "unknown_or_unverified_status": "UNVERIFIED_SOURCE_LABEL", "verified_ground_truth": None,
    }]

    rows = phase3.build_master_records(
        audit, labels,
        {audit[0]["file_path"]: {"embedding_index": 0, "image_id": "image_000000", "cluster_id": 2}},
        {}, {}, {"record_split": {audit[0]["file_path"]: "train"}},
    )

    assert rows[0]["verified_ground_truth"] is None
    assert rows[0]["original_filename"] == "a.jpg"
    assert rows[0]["embedding_reference"]["embedding_index"] == 0
    assert rows[0]["cluster_id"] == 2
    assert rows[0]["source_url"] is None


def test_evaluation_schema_and_readiness_disclose_ground_truth_gap() -> None:
    schema = phase3.build_evaluation_schema()
    readiness = phase3.build_training_readiness(
        {"summary": {"total_image_count": 10, "valid_image_count": 10}},
        {"category_counts": {"metal": 10}, "source_labeled_record_count": 10,
         "verified_ground_truth_record_count": 0},
        {"quality_flag_counts": {}}, [], [],
        {"leakage_check_passed": True}, {"verified": True},
    )

    assert "confusion_matrix" in schema["classification"]["metrics"]
    assert "precision_at_k" in schema["retrieval_similarity"]["metrics"]
    assert "false_acceptance_rate" in schema["quality_gate"]["metrics"]
    assert "NOT_READY" in readiness
    assert "zero independently verified ground-truth records" in readiness


def test_discovered_inventory_records_project_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(phase3, "WORKSPACE_ROOT", tmp_path)
    (tmp_path / "data" / "annotations").mkdir(parents=True)
    (tmp_path / "data" / "annotations" / ".gitkeep").write_text("")
    (tmp_path / "data" / "metadata").mkdir()
    (tmp_path / "data" / "metadata" / "source.json").write_text("{}")
    output_dir = tmp_path / "data" / "evaluations" / "phase3"
    output_dir.mkdir(parents=True)
    (output_dir / "phase3_data_inventory.json").write_text("{}")
    (tmp_path / "PHASE_3_COMPLETION.md").write_text("generated")
    embeddings_dir = tmp_path / "data" / "embeddings" / "vits14"
    clusters_dir = tmp_path / "data" / "embeddings" / "clusters"
    embeddings_dir.mkdir(parents=True)
    clusters_dir.mkdir(parents=True)
    (embeddings_dir / "metadata.json").write_text(json.dumps({"model_name": "dinov2_vits14"}))
    (clusters_dir / "clustering_metrics.json").write_text(json.dumps({"selected_k": 8}))
    manifest = {"dataset_root": "data/raw/WASTES", "summary": {
        "total_image_count": 1, "valid_image_count": 1, "invalid_file_count": 0,
        "splits": {"train": {"image_count": 1, "category_image_counts": {"metal": 1}}},
        "missing_split_directories": [], "empty_directories": [],
    }}
    alignment = {"aligned_valid_path_count": 1}

    inventory = phase3.discover_project_inventory(
        manifest, embeddings_dir, clusters_dir, output_dir,
        [{"file_path": "data/raw/WASTES/train/metal/a.jpg", "file_size_bytes": 10,
          "width": 300, "height": 200, "image_format": "JPEG", "quality_status": "PASS"}],
        [], {"verified_ground_truth_record_count": 0}, alignment,
    )

    assert inventory["existing_assessment_record_count_found"] == 0
    assert inventory["embedding_artifacts"]["metadata"]["model_name"] == "dinov2_vits14"
    assert inventory["clustering_artifacts"]["metrics"]["selected_k"] == 8
    assert inventory["source_reference"] is None
    assert "data/evaluations/phase3/phase3_data_inventory.json" not in inventory["project_file_inventory"]["metadata_files"]
    assert "PHASE_3_COMPLETION.md" not in inventory["project_file_inventory"]["metadata_files"]
    assert inventory["data_directories_file_counts"]["evaluations"] == 0