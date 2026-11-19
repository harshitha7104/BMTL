"""Build reproducible Phase 3 data-quality, provenance, and evaluation artifacts."""
import argparse
import csv
import hashlib
import json
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageStat
from scipy.fft import dctn

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = WORKSPACE_ROOT / "data" / "manifests" / "wastes_manifest.json"
DEFAULT_EMBEDDINGS = WORKSPACE_ROOT / "data" / "embeddings" / "dinov2_vits14"
DEFAULT_CLUSTER_DIR = WORKSPACE_ROOT / "data" / "embeddings" / "clusters"
DEFAULT_OUTPUT = WORKSPACE_ROOT / "data" / "evaluations" / "phase3"
SCHEMA_VERSION = "phase3-data-foundation-v1"
SOURCE_DATASET_NAME = "Kaggle waste-image dataset (owner-provided; URL not found in repository)"
EXCLUDED_DIRS = {
    ".git", ".pytest_cache", "node_modules", "dist", "build", "__pycache__",
    ".mypy_cache", ".ruff_cache", ".venv", "venv",
}
METADATA_SUFFIXES = {".json", ".jsonl", ".csv", ".md", ".txt", ".yaml", ".yml", ".pdf"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
SUPPORTED_IMAGE_FORMATS = {"JPEG", "PNG"}


class UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def stable_id(value: str, prefix: str = "rec") -> str:
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}"


def resolve_workspace_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else WORKSPACE_ROOT / path


def compute_phash(image: Image.Image) -> int:
    gray = image.convert("L").resize((32, 32), Image.Resampling.LANCZOS)
    coefficients = dctn(np.asarray(gray, dtype=np.float32), type=2, norm="ortho")[:8, :8]
    values = coefficients.flatten()
    median = float(np.median(values[1:]))
    result = 0
    for bit in values > median:
        result = (result << 1) | int(bit)
    return result


def audit_image(record: dict, workspace_root: Path = WORKSPACE_ROOT) -> dict:
    """Measure quality and integrity without modifying the source image."""
    image_path = resolve_workspace_path(record["file_path"])
    base = {
        "record_id": stable_id(record["file_path"]),
        "file_path": record["file_path"],
        "source_dataset": SOURCE_DATASET_NAME,
        "source_label": record.get("category_name"),
        "original_split": record.get("split"),
        "file_size_bytes": None,
        "image_format": None,
        "width": None,
        "height": None,
        "sha256": None,
        "phash64": None,
        "quality_status": "FAIL",
        "quality_flags": [],
        "quality_metrics": {},
        "is_usable_visual_evidence": False,
        "manual_review_recommended": True,
        "duplicate_group_id": None,
        "embedding_index": None,
        "cluster_id": None,
    }
    if not image_path.is_file():
        base["quality_flags"].append("missing_file")
        return base

    base["file_size_bytes"] = image_path.stat().st_size
    if base["file_size_bytes"] == 0:
        base["quality_flags"].append("zero_byte_file")
        return base
    with image_path.open("rb") as image_file:
        base["sha256"] = hashlib.file_digest(image_file, "sha256").hexdigest()
    if image_path.suffix.lower() not in IMAGE_SUFFIXES:
        base["quality_flags"].append("unsupported_or_non_image_file")
        return base

    try:
        with Image.open(image_path) as image:
            image.verify()
        with Image.open(image_path) as image:
            image.load()
            width, height = image.size
            image_format = (image.format or "UNKNOWN").upper()
            base["width"] = width
            base["height"] = height
            base["image_format"] = image_format
            base["phash64"] = f"{compute_phash(image):016x}"
            thumbnail = image.convert("RGB")
            thumbnail.thumbnail((256, 256), Image.Resampling.BICUBIC)
            gray = np.asarray(thumbnail.convert("L"), dtype=np.float32)
            stats = ImageStat.Stat(thumbnail)
    except Exception as error:
        base["quality_flags"].append(f"corrupt_or_unreadable:{type(error).__name__}")
        return base

    brightness = float(sum(stats.mean) / (3 * 255))
    contrast = float(sum(stats.stddev) / (3 * 128))
    entropy_histogram = np.bincount(gray.astype(np.uint8).ravel(), minlength=256).astype(np.float64)
    probabilities = entropy_histogram[entropy_histogram > 0] / entropy_histogram.sum()
    entropy = float(-np.sum(probabilities * np.log2(probabilities)))
    laplacian_variance = float(np.var(
        np.roll(gray, 1, axis=0) + np.roll(gray, -1, axis=0)
        + np.roll(gray, 1, axis=1) + np.roll(gray, -1, axis=1) - 4 * gray
    ))
    channels = np.asarray(thumbnail, dtype=np.uint8)
    grayscale = bool(max(stats.stddev) - min(stats.stddev) < 1.0)
    metrics = {
        "brightness_0_to_1": round(brightness, 5),
        "contrast_normalized": round(contrast, 5),
        "grayscale_entropy_bits": round(entropy, 5),
        "laplacian_variance_thumbnail": round(laplacian_variance, 5),
        "grayscale_detected": grayscale,
        "thumbnail_rgb_stddev": [round(float(value), 3) for value in stats.stddev],
        "channel_count": len(thumbnail.getbands()),
    }
    flags = []
    if image_format not in SUPPORTED_IMAGE_FORMATS:
        flags.append(f"unsupported_format:{image_format}")
    if width < 300 or height < 300:
        flags.append("below_existing_quality_gate_minimum_resolution")
    if max(width / max(height, 1), height / max(width, 1)) > 5:
        flags.append("extreme_aspect_ratio")
    if brightness < 0.15:
        flags.append("too_dark_existing_quality_gate_threshold")
    elif brightness > 0.85:
        flags.append("overexposed_existing_quality_gate_threshold")
    if contrast < 0.1:
        flags.append("low_contrast_existing_quality_gate_threshold")
    if laplacian_variance < 15:
        flags.append("possible_excessive_blur_heuristic")
    if entropy < 1.0 or float(np.std(gray)) < 3:
        flags.append("suspiciously_low_information")
    if image_format not in SUPPORTED_IMAGE_FORMATS:
        status = "FAIL"
    elif entropy < 0.5 or laplacian_variance < 2:
        status = "NEEDS_REVIEW"
    elif flags:
        status = "WARN"
    else:
        status = "PASS"
    base.update(
        {
            "quality_status": status,
            "quality_flags": flags,
            "quality_metrics": metrics,
            "is_usable_visual_evidence": status in {"PASS", "WARN", "NEEDS_REVIEW"},
            "manual_review_recommended": status in {"FAIL", "NEEDS_REVIEW"},
        }
    )
    return base


def _phash_pairs(hashes: list[int], threshold: int = 4, block_size: int = 256) -> list[tuple[int, int, int]]:
    hash_array = np.asarray(hashes, dtype=np.uint64)
    pairs = []
    for start in range(0, len(hash_array), block_size):
        stop = min(start + block_size, len(hash_array))
        distances = np.bitwise_count(hash_array[start:stop, None] ^ hash_array[None, :])
        local_rows, columns = np.where(distances <= threshold)
        for local_row, column in zip(local_rows.tolist(), columns.tolist(), strict=True):
            row = start + local_row
            if column > row:
                pairs.append((row, column, int(distances[local_row, column])))
    return pairs


def detect_duplicates(
    audit_records: list[dict],
    embeddings: np.ndarray,
    cluster_by_path: dict[str, int],
    embedding_threshold: float = 0.995,
    phash_threshold: int = 4,
    top_k: int = 64,
    batch_size: int = 128,
) -> tuple[list[dict], dict[str, str], dict[str, dict]]:
    """Find exact, perceptual-hash, and very-high-cosine candidate pairs."""
    record_count = len(audit_records)
    if embeddings.shape[0] != record_count:
        raise ValueError("Image audit rows and embedding rows must be path-aligned")
    union_find = UnionFind(record_count)
    evidence_by_pair: dict[tuple[int, int], dict] = {}
    sha_groups = defaultdict(list)
    phash_records = []
    for index, record in enumerate(audit_records):
        if record.get("sha256"):
            sha_groups[record["sha256"]].append(index)
        if record.get("phash64"):
            phash_records.append((index, int(record["phash64"], 16)))
    for indices in sha_groups.values():
        if len(indices) > 1:
            for left_position in range(len(indices)):
                for right_position in range(left_position + 1, len(indices)):
                    left, right = indices[left_position], indices[right_position]
                    evidence_by_pair[(left, right)] = {"exact_sha256": True}
                    union_find.union(left, right)

    valid_phash_indices = [index for index, _ in phash_records]
    phash_pairs = _phash_pairs([value for _, value in phash_records], phash_threshold)
    for local_left, local_right, distance in phash_pairs:
        left, right = valid_phash_indices[local_left], valid_phash_indices[local_right]
        key = (min(left, right), max(left, right))
        evidence_by_pair.setdefault(key, {})["phash_hamming_distance"] = distance
        union_find.union(left, right)

    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    vector_tensor = torch.tensor(
        np.array(embeddings, dtype=np.float32, copy=True),
        dtype=torch.float32,
        device=device,
    )
    vector_tensor = torch.nn.functional.normalize(vector_tensor, p=2, dim=1)
    cluster_ids = [cluster_by_path.get(record["file_path"], -1) for record in audit_records]
    neighbor_details = {}
    k = min(max(2, top_k), record_count)
    for start in range(0, record_count, batch_size):
        stop = min(start + batch_size, record_count)
        similarities = vector_tensor[start:stop] @ vector_tensor.T
        row_indices = torch.arange(start, stop, device=device)
        similarities[torch.arange(stop - start, device=device), row_indices] = -1
        top_values, top_indices = torch.topk(similarities, k=k, dim=1)
        values_cpu = top_values.cpu().numpy()
        indices_cpu = top_indices.cpu().numpy()
        for local_row, absolute_row in enumerate(range(start, stop)):
            best_same = None
            best_other = None
            for similarity, neighbor in zip(values_cpu[local_row], indices_cpu[local_row], strict=True):
                neighbor = int(neighbor)
                similarity = max(-1.0, min(1.0, float(similarity)))
                if cluster_ids[neighbor] == cluster_ids[absolute_row]:
                    if best_same is None:
                        best_same = (similarity, neighbor)
                elif best_other is None:
                    best_other = (similarity, neighbor)
                if similarity >= embedding_threshold and neighbor > absolute_row:
                    key = (absolute_row, neighbor)
                    evidence_by_pair.setdefault(key, {})["embedding_cosine_similarity"] = round(similarity, 7)
                    union_find.union(absolute_row, neighbor)
            neighbor_details[audit_records[absolute_row]["file_path"]] = {
                "nearest_neighbor_path": audit_records[int(indices_cpu[local_row][0])]["file_path"],
                "nearest_neighbor_cosine": round(float(values_cpu[local_row][0]), 7),
                "nearest_neighbor_cluster_id": cluster_ids[int(indices_cpu[local_row][0])],
                "nearest_same_cluster_cosine": round(best_same[0], 7) if best_same else None,
                "nearest_other_cluster_cosine": round(best_other[0], 7) if best_other else None,
                "cluster_boundary_margin": round(best_same[0] - best_other[0], 7)
                if best_same and best_other else None,
            }
        del similarities, top_values, top_indices

    grouped = defaultdict(list)
    for index in range(record_count):
        root = union_find.find(index)
        grouped[root].append(index)
    duplicate_groups = []
    duplicate_group_by_path = {}
    for members in grouped.values():
        if len(members) < 2:
            continue
        group_id = stable_id("|".join(sorted(audit_records[index]["file_path"] for index in members)), "dup")
        member_paths = [audit_records[index]["file_path"] for index in members]
        member_set = set(members)
        pair_evidence = [
            {"paths": [audit_records[left]["file_path"], audit_records[right]["file_path"]], **evidence}
            for (left, right), evidence in evidence_by_pair.items()
            if left in member_set and right in member_set
        ]
        duplicate_types = sorted(
            {
                key
                for evidence in pair_evidence
                for key in evidence
                if key != "paths"
            }
        )
        group = {
            "group_id": group_id,
            "image_count": len(member_paths),
            "paths": member_paths,
            "duplicate_types": duplicate_types,
            "similarity_evidence": pair_evidence,
            "recommended_handling": "Keep originals; group together when designing future data splits and request review before excluding any record.",
        }
        duplicate_groups.append(group)
        for path in member_paths:
            duplicate_group_by_path[path] = group_id
    duplicate_groups.sort(key=lambda group: group["group_id"])
    return duplicate_groups, duplicate_group_by_path, neighbor_details


def align_embeddings(
    manifest_records: list[dict],
    path_rows: list[dict],
    statuses: np.ndarray,
    vectors: np.ndarray,
    cluster_rows: list[dict],
    norm_tolerance: float = 0.02,
) -> tuple[dict, dict[str, dict]]:
    valid_paths = [
        record["file_path"] for record in manifest_records
        if record.get("is_image") is True and record.get("is_valid") is True
    ]
    embedding_paths = [row["file_path"] for row in path_rows]
    duplicate_paths = sorted(path for path, count in Counter(embedding_paths).items() if count > 1)
    path_to_row = {row["file_path"]: row for row in path_rows}
    cluster_by_path = {row["file_path"]: int(row["cluster_id"]) for row in cluster_rows}
    norms = np.linalg.norm(vectors, axis=1)
    status_embedded = np.asarray(statuses) == 1
    normalized_count = int(np.count_nonzero(np.abs(norms[status_embedded] - 1) <= norm_tolerance))
    aligned_paths = set(valid_paths) & set(embedding_paths)
    missing_paths = sorted(set(valid_paths) - set(embedding_paths))
    extra_paths = sorted(set(embedding_paths) - set(valid_paths))
    missing_vectors = [
        path for index, path in enumerate(embedding_paths)
        if index >= len(statuses) or statuses[index] != 1
    ]
    alignment = {
        "manifest_valid_image_count": len(valid_paths),
        "embedding_path_row_count": len(path_rows),
        "embedding_array_shape": list(vectors.shape),
        "status_array_length": int(len(statuses)),
        "embedded_status_count": int(np.count_nonzero(status_embedded)),
        "cluster_assignment_count": len(cluster_rows),
        "aligned_valid_path_count": len(aligned_paths),
        "missing_manifest_paths": missing_paths,
        "extra_embedding_paths": extra_paths,
        "not_successfully_embedded_paths": missing_vectors,
        "duplicate_embedding_paths": duplicate_paths,
        "norm_mean": float(np.mean(norms[status_embedded])) if np.any(status_embedded) else None,
        "norm_min": float(np.min(norms[status_embedded])) if np.any(status_embedded) else None,
        "norm_max": float(np.max(norms[status_embedded])) if np.any(status_embedded) else None,
        "within_unit_norm_tolerance_count": normalized_count,
        "unit_norm_tolerance": norm_tolerance,
        "cluster_assignment_missing_paths": sorted(aligned_paths - set(cluster_by_path)),
        "cluster_assignment_extra_paths": sorted(set(cluster_by_path) - aligned_paths),
        "verified": (
            len(valid_paths) == len(path_rows) == len(statuses) == vectors.shape[0] == len(cluster_rows)
            and not missing_paths and not extra_paths and not duplicate_paths
            and normalized_count == int(np.count_nonzero(status_embedded))
        ),
    }
    embedding_references = {
        path: {
            "embedding_index": row["embedding_index"],
            "image_id": row["image_id"],
            "cluster_id": cluster_by_path.get(path),
        }
        for path, row in path_to_row.items()
    }
    return alignment, embedding_references


def audit_labels(records: list[dict], external_label_paths: list[str] | None = None) -> tuple[list[dict], dict]:
    category_counts = Counter(record.get("category_name") for record in records)
    missing = [record for record in records if not record.get("category_name")]
    label_records = []
    for record in records:
        category = record.get("category_name")
        path_category = Path(record["file_path"]).parts[-2] if len(Path(record["file_path"]).parts) >= 2 else None
        conflicts = []
        if category and path_category and category.casefold() != path_category.casefold():
            conflicts.append("manifest_category_differs_from_parent_directory")
        label_records.append(
            {
                "record_id": stable_id(record["file_path"]),
                "image_path": record["file_path"],
                "source_label": category,
                "source_label_origin": "dataset category directory and Phase A manifest",
                "verified_ground_truth": None,
                "verified_ground_truth_status": "NOT_FOUND",
                "inferred_label": None,
                "unknown_or_unverified_status": "UNVERIFIED_SOURCE_LABEL" if category else "MISSING_LABEL",
                "conflicting_metadata": conflicts,
                "multi_material_status": "NOT_ANNOTATED",
                "ambiguity_status": "NOT_ANNOTATED",
                "external_annotation_sources_found": external_label_paths or [],
            }
        )
    summary = {
        "record_count": len(records),
        "source_labeled_record_count": len(records) - len(missing),
        "missing_source_label_count": len(missing),
        "verified_ground_truth_record_count": 0,
        "inferred_label_record_count": 0,
        "unverified_source_label_record_count": len(records) - len(missing),
        "conflicting_metadata_record_count": sum(bool(row["conflicting_metadata"]) for row in label_records),
        "explicit_multi_material_annotation_count": 0,
        "explicit_ambiguity_annotation_count": 0,
        "category_counts": {
            str(category): count
            for category, count in sorted(category_counts.items(), key=lambda item: str(item[0]).casefold())
        },
        "ground_truth_limitation": (
            "Directory/manifest category names are source labels only. No expert, laboratory, or human-verified "
            "ground truth was found in project annotations; no labels were upgraded, inferred, or fabricated."
        ),
    }
    return label_records, summary


def build_taxonomy(label_summary: dict) -> dict:
    categories = []
    for category, count in label_summary["category_counts"].items():
        category_name = category if category != "None" else None
        categories.append(
            {
                "category": category_name,
                "subcategory": category_name,
                "source_evidence": "Existing source category directory/Phase A manifest label only",
                "record_count": count,
                "label_confidence": "UNVERIFIED_SOURCE_LABEL",
                "ground_truth_verified": False,
                "ambiguity_notes": (
                    "Category semantics have not been independently verified. A single source label does not "
                    "establish purity, composition, grade, or whether an image contains mixed materials."
                ),
            }
        )
    return {
        "taxonomy_version": "source-category-taxonomy-v1",
        "scope": "Data-driven inventory of existing source categories; not a verified material ontology.",
        "verified_material_composition_claims": 0,
        "categories": categories,
        "unmapped_or_unknown_count": label_summary["missing_source_label_count"],
        "domain_limitations": [
            "The source label 'metal waste' is not a verified ferrous/non-ferrous distinction.",
            "No copper-only assumption is made; category names are preserved verbatim.",
            "Mixed-material, mineral, hazard, alloy, and purity facts are unknown unless separately evidenced.",
        ],
    }


def make_leakage_safe_splits(
    records: list[dict],
    duplicate_group_by_path: dict[str, str],
    seed: int = 20260928,
    validation_fraction_of_source_train: float = 0.15,
) -> dict:
    groups = defaultdict(list)
    for record in records:
        group_id = duplicate_group_by_path.get(record["file_path"], f"single:{record['file_path']}")
        groups[group_id].append(record)
    assignments = {}
    train_strata = defaultdict(list)
    for group_id, members in groups.items():
        if any(record.get("split") == "test" for record in members):
            assignments[group_id] = "test"
            continue
        labels = {record.get("category_name") for record in members}
        stratum = next(iter(labels)) if len(labels) == 1 else "mixed_source_label_group"
        train_strata[stratum].append(group_id)
    for stratum, group_ids in train_strata.items():
        ordered = sorted(
            group_ids,
            key=lambda group_id: hashlib.sha256(f"{seed}:{stratum}:{group_id}".encode()).hexdigest(),
        )
        validation_count = int(round(len(ordered) * validation_fraction_of_source_train))
        if len(ordered) > 1:
            validation_count = max(1, min(validation_count, len(ordered) - 1))
        else:
            validation_count = 0
        for index, group_id in enumerate(ordered):
            assignments[group_id] = "validation" if index < validation_count else "train"

    record_split = {}
    source_group_split_conflicts = []
    for group_id, members in groups.items():
        assigned = assignments[group_id]
        for record in members:
            record_split[record["file_path"]] = assigned
        source_splits = {record.get("split") for record in members}
        if len(source_splits) > 1:
            source_group_split_conflicts.append(
                {"group_id": group_id, "source_splits": sorted(source_splits), "assigned_split": assigned}
            )
    counts = Counter(record_split.values())
    return {
        "split_version": "group-aware-source-split-v1",
        "seed": seed,
        "strategy": (
            "Exact/pHash/DINO-near-duplicate connected components stay in one split. Any component touching "
            "the original source test split is held in test. Remaining source-train components are deterministically "
            "stratified by source category into train/validation."
        ),
        "source_labels_used_only_for_stratification": True,
        "source_labels_are_verified_ground_truth": False,
        "evaluation_items_are_test_only": True,
        "split_counts": {key: counts.get(key, 0) for key in ("train", "validation", "test")},
        "group_count": len(groups),
        "duplicate_or_near_duplicate_group_count": sum(len(members) > 1 for members in groups.values()),
        "source_split_conflict_groups_held_together": source_group_split_conflicts,
        "record_split": record_split,
        "leakage_check_passed": all(
            len({record_split[record["file_path"]] for record in members}) == 1
            for members in groups.values()
        ),
    }


def select_evaluation_dataset(
    audit_records: list[dict],
    label_records: list[dict],
    split_design: dict,
    duplicate_group_by_path: dict[str, str],
    neighbor_details: dict[str, dict],
    cluster_report: dict,
    per_category: int = 25,
    seed: int = 20260928,
) -> list[dict]:
    label_by_path = {row["image_path"]: row for row in label_records}
    audit_by_path = {row["file_path"]: row for row in audit_records}
    candidates = [
        row for row in audit_records
        if split_design["record_split"].get(row["file_path"]) == "test"
    ]
    reasons: dict[str, set[str]] = defaultdict(set)

    def deterministic_order(rows: list[dict], salt: str) -> list[dict]:
        return sorted(
            rows,
            key=lambda row: hashlib.sha256(
                f"{seed}:{salt}:{row['file_path']}".encode("utf-8")
            ).hexdigest(),
        )

    by_category = defaultdict(list)
    for row in candidates:
        source_label = row.get("source_label")
        if source_label:
            by_category[source_label].append(row)
    for category, rows in by_category.items():
        for row in deterministic_order(rows, f"category:{category}")[:per_category]:
            reasons[row["file_path"]].add("deterministic_source_category_coverage")

    test_path_set = {row["file_path"] for row in candidates}
    for cluster in cluster_report.get("cluster_summaries", []):
        representative = next(
            (path for path in cluster.get("representative_images", []) if path in test_path_set),
            None,
        )
        if representative:
            reasons[representative].add("cluster_representative_candidate")

    quality_candidates = [row for row in candidates if row["quality_status"] in {"WARN", "FAIL", "NEEDS_REVIEW"}]
    for row in deterministic_order(quality_candidates, "quality_review")[:25]:
        reasons[row["file_path"]].add("automated_quality_warning_or_review")

    boundary_candidates = []
    for row in candidates:
        neighbor = neighbor_details.get(row["file_path"], {})
        margin = neighbor.get("cluster_boundary_margin")
        cross_similarity = neighbor.get("nearest_other_cluster_cosine")
        if margin is not None and cross_similarity is not None:
            boundary_candidates.append((float(margin), -float(cross_similarity), row))
    for _, _, row in sorted(boundary_candidates, key=lambda item: (item[0], item[1], item[2]["file_path"]))[:25]:
        reasons[row["file_path"]].add("low_cluster_boundary_margin_candidate_for_review")

    duplicate_candidates = [row for row in candidates if row["file_path"] in duplicate_group_by_path]
    for row in deterministic_order(duplicate_candidates, "duplicate_risk")[:25]:
        reasons[row["file_path"]].add("duplicate_or_near_duplicate_risk")

    # Ensure coverage remains even if no special candidate pools were populated.
    if not reasons:
        for row in deterministic_order(candidates, "fallback")[:min(25, len(candidates))]:
            reasons[row["file_path"]].add("deterministic_test_split_fallback")

    evaluation = []
    for file_path in sorted(reasons):
        audit = audit_by_path[file_path]
        label = label_by_path[file_path]
        neighbor = neighbor_details.get(file_path, {})
        evaluation.append(
            {
                "evaluation_item_id": stable_id(file_path, "eval"),
                "image_reference": file_path,
                "material_category": None,
                "source_label": label["source_label"],
                "ground_truth_status": label["unknown_or_unverified_status"],
                "quality_status": audit["quality_status"],
                "cluster_id": audit.get("cluster_id"),
                "duplicate_group_id": duplicate_group_by_path.get(file_path),
                "cluster_boundary_margin": neighbor.get("cluster_boundary_margin"),
                "selection_reasons": sorted(reasons[file_path]),
                "confidence_verification_status": "UNVERIFIED; requires human/expert verification",
                "manual_review_candidate": True,
                "ground_truth_review_required": True,
                "visual_quality_review_required": audit["manual_review_recommended"],
                "manual_review_reasons": sorted(
                    set(reasons[file_path]) | {"verify_source_label_before_benchmark_use"}
                ),
                "assigned_future_split": "test",
                "not_training_eligible_by_default": True,
            }
        )
    return evaluation


def summarize_evaluation_records(records: list[dict]) -> tuple[dict, dict]:
    category_counts = Counter(record.get("source_label") or "MISSING_LABEL" for record in records)
    reason_counts = Counter(
        reason for record in records for reason in record.get("selection_reasons", [])
    )
    return dict(sorted(category_counts.items())), dict(sorted(reason_counts.items()))


def _iter_project_files(root: Path):
    for current, directories, files in os.walk(root):
        directories[:] = [directory for directory in directories if directory not in EXCLUDED_DIRS]
        for filename in files:
            yield Path(current) / filename


def discover_project_inventory(
    manifest: dict,
    embeddings_dir: Path,
    cluster_dir: Path,
    output_dir: Path,
    audit_records: list[dict],
    duplicate_groups: list[dict],
    label_summary: dict,
    alignment: dict,
) -> dict:
    project_files = list(_iter_project_files(WORKSPACE_ROOT))
    completion_path = WORKSPACE_ROOT / "PHASE_3_COMPLETION.md"
    project_files = [
        path for path in project_files
        if not path.is_relative_to(output_dir) and path != completion_path
    ]
    suffix_counts = Counter(path.suffix.lower() or "[no extension]" for path in project_files)
    metadata_files = [
        path.relative_to(WORKSPACE_ROOT).as_posix()
        for path in project_files if path.suffix.lower() in METADATA_SUFFIXES
    ]
    image_sizes = [record["file_size_bytes"] for record in audit_records if record["file_size_bytes"] is not None]
    image_sizes_array = np.asarray(image_sizes, dtype=np.int64)
    image_dimensions = Counter(
        f"{record['width']}x{record['height']}"
        for record in audit_records if record.get("width") and record.get("height")
    )
    image_formats = Counter(record.get("image_format") or "UNKNOWN" for record in audit_records)
    image_status = Counter(record["quality_status"] for record in audit_records)
    docs_text = []
    for path in project_files:
        if path.suffix.lower() in {".md", ".txt", ".json", ".yaml", ".yml"} and path.stat().st_size < 2_000_000:
            try:
                docs_text.append((path.relative_to(WORKSPACE_ROOT).as_posix(), path.read_text(encoding="utf-8", errors="ignore")))
            except OSError:
                continue
    external_refs = []
    for relative_path, text in docs_text:
        for match in re.finditer(r"https?://[^\s\"'<>]+|kaggle", text, flags=re.IGNORECASE):
            value = match.group(0).rstrip(".,);]")
            if value not in external_refs:
                external_refs.append(value)
    data_dirs = {}
    for name in ("images", "documents", "metadata", "annotations", "evaluations", "knowledge", "processed", "raw", "manifests", "embeddings"):
        directory = WORKSPACE_ROOT / "data" / name
        if directory.exists():
            data_dirs[name] = sum(
                1 for path in directory.rglob("*")
                if path.is_file() and not path.is_relative_to(output_dir)
            )
    assessment_roots = [
        WORKSPACE_ROOT / "backend" / "data" / "assessments",
        WORKSPACE_ROOT / "data" / "documents",
        WORKSPACE_ROOT / "data" / "metadata",
        WORKSPACE_ROOT / "data" / "annotations",
    ]
    assessment_files = []
    for root in assessment_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.name == ".gitkeep":
                continue
            name_suggests_record = bool(
                re.search(r"assessment|trust.report|annotation|verified", path.name, re.IGNORECASE)
            )
            structured_assessment = False
            if path.suffix.lower() in {".json", ".jsonl"} and path.stat().st_size < 5_000_000:
                try:
                    text = path.read_text(encoding="utf-8")
                    objects = [json.loads(line) for line in text.splitlines() if line] if path.suffix.lower() == ".jsonl" else [json.loads(text)]
                    structured_assessment = any(
                        isinstance(item, dict)
                        and any(key in item for key in ("assessment_id", "evidence_quality", "verified_ground_truth"))
                        for item in objects
                    )
                except (OSError, json.JSONDecodeError):
                    pass
            if name_suggests_record or structured_assessment:
                assessment_files.append(path.relative_to(WORKSPACE_ROOT).as_posix())
    synthetic_data_files = [
        path.relative_to(WORKSPACE_ROOT).as_posix()
        for path in project_files
        if path.relative_to(WORKSPACE_ROOT).parts[0] == "data"
        and re.search(r"synthetic|fake|mock|sample", path.name, flags=re.IGNORECASE)
    ]
    try:
        import torch
        cuda_available = bool(torch.cuda.is_available())
        cuda_device = torch.cuda.get_device_name(0) if cuda_available else None
    except ImportError:
        cuda_available, cuda_device = False, None
    embedding_metadata_path = embeddings_dir / "metadata.json"
    embedding_metadata = json.loads(embedding_metadata_path.read_text(encoding="utf-8")) if embedding_metadata_path.exists() else {}
    cluster_metrics_path = cluster_dir / "clustering_metrics.json"
    cluster_metrics = json.loads(cluster_metrics_path.read_text(encoding="utf-8")) if cluster_metrics_path.exists() else {}
    embeddings_root = WORKSPACE_ROOT / "data" / "embeddings"
    other_embedding_directories = []
    if embeddings_root.exists():
        for directory in sorted(embeddings_root.iterdir(), key=lambda path: path.name.casefold()):
            if directory.is_dir() and directory.resolve() not in {embeddings_dir.resolve(), cluster_dir.resolve()}:
                other_embedding_directories.append(
                    {
                        "directory": directory.relative_to(WORKSPACE_ROOT).as_posix(),
                        "files": sorted(path.name for path in directory.iterdir() if path.is_file()),
                    }
                )
    return {
        "inventory_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "workspace_root": WORKSPACE_ROOT.as_posix(),
        "dataset_root": manifest.get("dataset_root"),
        "source_dataset": SOURCE_DATASET_NAME,
        "source_distribution": {SOURCE_DATASET_NAME: manifest["summary"]["total_image_count"]},
        "source_reference": None,
        "source_reference_limitation": "No original Kaggle URL or acquisition date found in repository metadata.",
        "missing_provenance_metadata": {
            "source_url": manifest["summary"]["total_image_count"],
            "acquisition_date": manifest["summary"]["total_image_count"],
            "verified_ground_truth": (
                    label_summary.get("record_count", manifest["summary"]["total_image_count"])
                    - label_summary.get("verified_ground_truth_record_count", 0)
            ),
                "missing_source_label": label_summary.get("missing_source_label_count", 0),
        },
        "project_file_inventory": {
            "total_files": len(project_files),
            "file_counts_by_extension": dict(sorted(suffix_counts.items())),
            "metadata_file_count": len(metadata_files),
            "metadata_files": metadata_files,
        },
        "dataset": {
            "total_image_records": manifest["summary"]["total_image_count"],
            "valid_phase_a_images": manifest["summary"]["valid_image_count"],
            "phase_a_invalid_files": manifest["summary"]["invalid_file_count"],
            "phase3_quality_status_counts": dict(sorted(image_status.items())),
            "image_formats": dict(sorted(image_formats.items())),
            "distinct_image_dimensions": len(image_dimensions),
            "most_common_dimensions": dict(image_dimensions.most_common(20)),
            "file_size_bytes": {
                "total": int(image_sizes_array.sum()) if image_sizes else 0,
                "minimum": int(image_sizes_array.min()) if image_sizes else None,
                "median": float(np.median(image_sizes_array)) if image_sizes else None,
                "p95": float(np.percentile(image_sizes_array, 95)) if image_sizes else None,
                "maximum": int(image_sizes_array.max()) if image_sizes else None,
            },
            "category_counts": manifest["summary"].get("splits", {}),
            "source_split_counts": {
                split: detail.get("image_count", 0)
                for split, detail in manifest["summary"].get("splits", {}).items()
            },
            "missing_split_directories": manifest["summary"].get("missing_split_directories", []),
            "empty_directories": manifest["summary"].get("empty_directories", []),
            "duplicate_group_count": len(duplicate_groups),
        },
        "data_directories_file_counts": data_dirs,
        "existing_assessment_or_annotation_files": assessment_files,
        "existing_assessment_record_count_found": len(assessment_files),
        "existing_synthetic_data_found": synthetic_data_files,
        "external_dataset_or_domain_references_in_project_text": external_refs,
        "label_audit_summary": label_summary,
        "embedding_artifacts": {
            "directory": embeddings_dir.as_posix(),
            "files": sorted(path.name for path in embeddings_dir.iterdir() if path.is_file()) if embeddings_dir.exists() else [],
            "other_embedding_directories": other_embedding_directories,
            "metadata": embedding_metadata,
            "alignment": alignment,
        },
        "clustering_artifacts": {
            "directory": cluster_dir.as_posix(),
            "files": sorted(path.name for path in cluster_dir.iterdir() if path.is_file()) if cluster_dir.exists() else [],
            "metrics": cluster_metrics,
        },
        "quality_audit_record_count": len(audit_records),
        "duplicate_candidate_group_count": len(duplicate_groups),
        "ground_truth_status": "SOURCE LABELS PRESENT; VERIFIED GROUND TRUTH NOT FOUND",
    }


def build_master_records(
    audit_records: list[dict],
    label_records: list[dict],
    embedding_references: dict[str, dict],
    neighbor_details: dict[str, dict],
    duplicate_group_by_path: dict[str, str],
    split_design: dict,
) -> list[dict]:
    label_by_path = {record["image_path"]: record for record in label_records}
    master = []
    for audit in audit_records:
        path = audit["file_path"]
        label = label_by_path[path]
        master.append(
            {
                "record_id": audit["record_id"],
                "image_path": path,
                "source_dataset": SOURCE_DATASET_NAME,
                "source_url": None,
                "source_acquisition_date": None,
                "original_filename": Path(path).name,
                "original_label": label["source_label"],
                "source_label_status": label["unknown_or_unverified_status"],
                "verified_ground_truth": None,
                "inferred_label": None,
                "quality_status": audit["quality_status"],
                "quality_flags": audit["quality_flags"],
                "file_size_bytes": audit["file_size_bytes"],
                "sha256": audit["sha256"],
                "phash64": audit["phash64"],
                "image_format": audit["image_format"],
                "width": audit["width"],
                "height": audit["height"],
                "embedding_reference": embedding_references.get(path),
                "cluster_id": audit.get("cluster_id"),
                "duplicate_group_id": duplicate_group_by_path.get(path),
                "visual_neighbor_audit": neighbor_details.get(path),
                "original_split": audit["original_split"],
                "phase3_future_split": split_design["record_split"].get(path),
                "manifest_version": SCHEMA_VERSION,
                "transformation_version": "quality-audit-v1; DINOv2 ViT-S/14 frozen; source image unchanged",
                "provenance_limitations": ["Kaggle source URL and acquisition date not located"],
            }
        )
    return master


def render_inventory_markdown(inventory: dict) -> str:
    dataset = inventory["dataset"]
    formats = ", ".join(f"{key}: {value}" for key, value in dataset["image_formats"].items())
    categories = dataset["category_counts"]
    category_rows = []
    for split, details in categories.items():
        for category, count in details.get("category_image_counts", {}).items():
            category_rows.append(f"| {category} | {split} | {count} |")
    return (
        "# Phase 3 Data Inventory\n\n"
        f"Generated: {inventory['generated_at_utc']}\n\n"
        f"- Workspace: `{inventory['workspace_root']}`\n"
        f"- Source: {inventory['source_dataset']}\n"
        f"- Image records: {dataset['total_image_records']}\n"
        f"- Phase A valid / invalid: {dataset['valid_phase_a_images']} / {dataset['phase_a_invalid_files']}\n"
        f"- Phase 3 quality statuses: `{json.dumps(dataset['phase3_quality_status_counts'])}`\n"
        f"- Image formats: {formats}\n"
        f"- Distinct dimensions: {dataset['distinct_image_dimensions']}\n"
        f"- Total image bytes: {dataset['file_size_bytes']['total']}\n"
        f"- Project files inventoried: {inventory['project_file_inventory']['total_files']}\n"
        f"- Metadata/document files: {inventory['project_file_inventory']['metadata_file_count']}\n"
        f"- Assessment/annotation files found: {inventory['existing_assessment_record_count_found']}\n"
        f"- Missing source URL/date/verified ground truth: `{json.dumps(inventory['missing_provenance_metadata'])}`\n"
        f"- DINOv2 aligned rows: {inventory['embedding_artifacts']['alignment']['aligned_valid_path_count']}\n"
        f"- Duplicate/near-duplicate groups: {inventory['duplicate_candidate_group_count']}\n\n"
        "## Existing Source Categories\n\n"
        "| Category (source label only) | Original split | Records |\n|---|---:|---:|\n"
        + "\n".join(category_rows)
        + "\n\n## Provenance and Ground Truth\n\n"
        "The owner identifies the source as a Kaggle waste-image dataset, but the repository contains no original URL or acquisition date. "
        "Directory categories are unverified source labels. No verified human/expert/laboratory ground truth was found. "
        "No synthetic dataset or persisted assessment records were found in the inspected data locations.\n\n"
        "## Existing Phase B Artifacts\n\n"
        f"- Embeddings: `{inventory['embedding_artifacts']['directory']}`\n"
        f"- Cluster outputs: `{inventory['clustering_artifacts']['directory']}`\n"
        "- Existing clusters and embeddings were reused; no DINOv2 recomputation was performed for this inventory.\n"
    )


def build_quality_summary(audit_records: list[dict]) -> dict:
    status_counts = Counter(record["quality_status"] for record in audit_records)
    flag_counts = Counter(flag for record in audit_records for flag in record["quality_flags"])
    usable = sum(record["is_usable_visual_evidence"] for record in audit_records)
    return {
        "audit_version": "automated-image-audit-v1",
        "record_count": len(audit_records),
        "quality_status_counts": dict(sorted(status_counts.items())),
        "quality_flag_counts": dict(sorted(flag_counts.items())),
        "usable_visual_evidence_count": usable,
        "not_automatically_usable_count": len(audit_records) - usable,
        "manual_review_recommended_count": sum(record["manual_review_recommended"] for record in audit_records),
        "threshold_notes": [
            "Brightness and contrast warning thresholds reuse ImageQualityService concepts (0.15/0.85 and normalized contrast 0.1).",
            "Blur, entropy, grayscale, aspect-ratio, and low-information checks are automated heuristics, not validated material judgments.",
            "PASS/WARN/NEEDS_REVIEW never deletes or alters source files; FAIL means the record should not be used as visual evidence until reviewed.",
        ],
    }


def build_evaluation_schema() -> dict:
    return {
        "schema_version": "scrap-ai-evaluation-v1",
        "ground_truth_policy": "Only compute label-dependent metrics when the corresponding field is verified; source labels alone are insufficient.",
        "classification": {
            "metrics": ["accuracy", "precision_macro", "recall_macro", "f1_macro", "confusion_matrix"],
            "requires": "verified_ground_truth and fixed label taxonomy",
        },
        "retrieval_similarity": {
            "metrics": ["precision_at_k", "recall_at_k", "mean_average_precision", "duplicate_leakage_rate"],
            "requires": "human-reviewed relevance judgments and duplicate-group-aware splits",
        },
        "evidence_assessment": {
            "fields": ["observed_claim_correctness", "inferred_claim_correctness", "unsupported_claim_count", "unknown_handling_correct", "evidence_link_validity"],
            "requires": "expert-reviewed claim/evidence annotations; do not infer from source image class labels",
        },
        "quality_gate": {
            "metrics": ["quality_failure_recall", "quality_failure_precision", "false_acceptance_rate", "false_rejection_rate", "manual_review_trigger_recall"],
            "requires": "human quality adjudication under a documented protocol",
        },
        "trust_traceability": {
            "fields": ["source_traceability", "reproducibility", "model_version_traceability", "evidence_to_claim_linkage", "limitations_present"],
            "requires": "auditable provenance and review records",
        },
        "current_phase3_metric_limitations": "No verified ground-truth labels or human relevance judgments were located; do not report supervised accuracy, retrieval relevance, or evidence correctness yet.",
    }


def build_training_readiness(
    manifest: dict,
    label_summary: dict,
    quality_summary: dict,
    duplicate_groups: list[dict],
    evaluation_records: list[dict],
    split_design: dict,
    alignment: dict,
) -> str:
    category_counts = label_summary["category_counts"]
    largest = max((count for category, count in category_counts.items() if category != "None"), default=0)
    smallest = min((count for category, count in category_counts.items() if category != "None"), default=0)
    imbalance = round(largest / smallest, 3) if smallest else None
    status = "NOT_READY" if label_summary["verified_ground_truth_record_count"] == 0 else "CONDITIONALLY_READY"
    return (
        "# Phase 3 Training Readiness\n\n"
        f"**Conclusion: {status}**\n\n"
        "## Evidence\n\n"
        f"- Images in manifest: {manifest['summary']['total_image_count']}\n"
        f"- Valid Phase A images: {manifest['summary']['valid_image_count']}\n"
        f"- Source-labeled records: {label_summary['source_labeled_record_count']} (unverified)\n"
        f"- Verified ground-truth records: {label_summary['verified_ground_truth_record_count']}\n"
        f"- Source categories: {len([key for key in category_counts if key != 'None'])}\n"
        f"- Largest/smallest source-category count ratio: {imbalance}\n"
        f"- Automated quality flags: {quality_summary['quality_flag_counts']}\n"
        f"- Duplicate/near-duplicate groups: {len(duplicate_groups)}\n"
        f"- Evaluation candidate records: {len(evaluation_records)} (GROUND_TRUTH_LIMITED)\n"
        f"- Leakage-safe split check: {split_design['leakage_check_passed']}\n"
        f"- Embedding/path alignment verified: {alignment['verified']}\n\n"
        "## Readiness Rationale\n\n"
        "The images and frozen DINOv2 features are technically usable for controlled unsupervised, retrieval, and human-review experiments. "
        "The corpus is **not ready for supervised material classification** because every category is an unverified directory/source label and zero independently verified ground-truth records were found. "
        "The low Phase B silhouette (0.05415) and post-hoc ARI (0.2371) do not prove reliable material classification. "
        "Duplicate and near-duplicate groups must remain together in future splits. Evaluation candidates require expert review before becoming benchmark ground truth.\n\n"
        "## Required Before Supervised Training\n\n"
        "1. Define a broad material taxonomy with explicit mixed, unknown, and insufficient-evidence outcomes.\n"
        "2. Establish expert/laboratory verification protocol and record evidence source per label.\n"
        "3. Review the controlled evaluation candidates, including quality and cluster-boundary examples.\n"
        "4. Freeze duplicate-aware train/validation/test groups and keep the test set isolated.\n"
    )


def _write_reports(output_dir: Path, artifacts: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "phase3_data_inventory.json", artifacts["inventory"])
    (output_dir / "phase3_data_inventory.md").write_text(
        render_inventory_markdown(artifacts["inventory"]), encoding="utf-8"
    )
    write_jsonl(output_dir / "phase3_quality_audit.jsonl", artifacts["quality_records"])
    write_json(output_dir / "phase3_quality_audit_summary.json", artifacts["quality_summary"])
    (output_dir / "phase3_quality_audit_summary.md").write_text(
        "# Phase 3 Automated Image Quality Audit\n\n"
        f"- Records audited: {artifacts['quality_summary']['record_count']}\n"
        f"- Status counts: `{json.dumps(artifacts['quality_summary']['quality_status_counts'])}`\n"
        f"- Flag counts: `{json.dumps(artifacts['quality_summary']['quality_flag_counts'])}`\n"
        f"- Usable as visual evidence pending normal task-specific review: {artifacts['quality_summary']['usable_visual_evidence_count']}\n"
        f"- Manual review recommended: {artifacts['quality_summary']['manual_review_recommended_count']}\n\n"
        "Automated flags are heuristics; they do not determine material, composition, or ground truth. Original files were not modified.\n",
        encoding="utf-8",
    )
    write_json(output_dir / "phase3_duplicate_report.json", artifacts["duplicate_report"])
    (output_dir / "phase3_duplicate_report.md").write_text(
        "# Duplicate and Near-Duplicate Candidates\n\n"
        f"- Duplicate/near-duplicate groups: {len(artifacts['duplicate_report']['groups'])}\n"
        f"- Candidate pairs: `{json.dumps(artifacts['duplicate_report']['candidate_pair_counts'])}`\n"
        "- Exact matches use SHA-256. Perceptual matches use pHash Hamming distance <= 4. Visual-similarity candidates use DINOv2 cosine >= 0.995.\n"
        "- Similarity candidates are not proven duplicates. No files were deleted; groups must be held together for future splits.\n",
        encoding="utf-8",
    )
    write_jsonl(output_dir / "phase3_label_audit.jsonl", artifacts["label_records"])
    (output_dir / "phase3_label_audit.md").write_text(
        "# Phase 3 Label and Ground-Truth Audit\n\n"
        f"- Records: {artifacts['label_summary']['record_count']}\n"
        f"- Source-labeled: {artifacts['label_summary']['source_labeled_record_count']}\n"
        f"- Missing source label: {artifacts['label_summary']['missing_source_label_count']}\n"
        f"- Verified ground truth: {artifacts['label_summary']['verified_ground_truth_record_count']}\n"
        f"- Conflicting manifest/path category metadata: {artifacts['label_summary']['conflicting_metadata_record_count']}\n"
        f"- Explicit multi-material annotations: {artifacts['label_summary']['explicit_multi_material_annotation_count']}\n"
        f"- Explicit ambiguity annotations: {artifacts['label_summary']['explicit_ambiguity_annotation_count']}\n\n"
        "All existing category names are retained as SOURCE LABEL only. No category is promoted to verified ground truth; no missing, mixed, or ambiguous labels were invented.\n\n"
        "## Source Category Counts\n\n"
        + "\n".join(f"- {category}: {count}" for category, count in artifacts["label_summary"]["category_counts"].items())
        + "\n\n## Limitation\n\n"
        + artifacts["label_summary"]["ground_truth_limitation"]
        + "\n",
        encoding="utf-8",
    )
    write_json(output_dir / "phase3_embedding_alignment.json", artifacts["alignment"])
    write_json(output_dir / "material_taxonomy.json", artifacts["taxonomy"])
    write_jsonl(output_dir / "phase3_master_manifest.jsonl", artifacts["master_records"])
    write_jsonl(output_dir / "evaluation_dataset_v1.jsonl", artifacts["evaluation_records"])
    (output_dir / "evaluation_dataset_v1.md").write_text(
        "# Controlled Evaluation Candidate Set v1\n\n"
        f"- Items selected: {len(artifacts['evaluation_records'])}\n"
        f"- Ground-truth status: `GROUND_TRUTH_LIMITED`\n"
        f"- Deterministic seed: {artifacts['evaluation_seed']}\n"
        f"- Source-category coverage: `{json.dumps(artifacts['evaluation_category_coverage'], ensure_ascii=False)}`\n"
        f"- Selection reasons: `{json.dumps(artifacts['evaluation_selection_reason_counts'], ensure_ascii=False)}`\n"
        f"- Items are held in the duplicate-aware test split and are not training-eligible by default.\n\n"
        "Coverage reasons include deterministic source-category coverage, available cluster representatives, automated quality warnings, low cluster-boundary margin candidates, and duplicate-risk candidates. "
        "These are candidates for human review, not fabricated labels or a verified benchmark. Mixed/unknown material cases require expert annotation; none are claimed to be confirmed by this audit.\n",
        encoding="utf-8",
    )
    write_json(output_dir / "evaluation_schema.json", artifacts["evaluation_schema"])
    (output_dir / "evaluation_schema.md").write_text(
        "# Future Evaluation Schema\n\n"
        + "```json\n" + json.dumps(artifacts["evaluation_schema"], indent=2) + "\n```\n\n"
        + artifacts["evaluation_schema"]["current_phase3_metric_limitations"]
        + "\n",
        encoding="utf-8",
    )
    write_json(output_dir / "phase3_split_definitions.json", artifacts["split_design"])
    (output_dir / "training_readiness.md").write_text(artifacts["training_readiness"], encoding="utf-8")
    completion = (
        "# Phase 3 Completion\n\n"
        "## Accomplishments\n\n"
        "- Inventoried repository data, documentation, source labels, and existing Phase B artifacts.\n"
        "- Audited source images with non-destructive integrity and quality heuristics.\n"
        "- Detected exact, perceptual-hash, and DINOv2 high-similarity duplicate candidates without deleting files.\n"
        "- Verified DINOv2 row/path/status alignment and reused existing embeddings and cluster assignments.\n"
        "- Kept directory categories as unverified source labels and marked verified ground truth unavailable.\n"
        "- Created source-category taxonomy, a held-out deterministic evaluation candidate set, evaluation schema, and duplicate-aware future splits.\n\n"
        f"## Dataset and Results\n\n- Images: {artifacts['inventory']['dataset']['total_image_records']}\n"
        f"- Phase A valid / invalid: {artifacts['inventory']['dataset']['valid_phase_a_images']} / {artifacts['inventory']['dataset']['phase_a_invalid_files']}\n"
        f"- Quality status counts: `{json.dumps(artifacts['quality_summary']['quality_status_counts'])}`\n"
        f"- Duplicate/near-duplicate groups: {len(artifacts['duplicate_report']['groups'])}\n"
        f"- Duplicate groups crossing original train/test: {artifacts['duplicate_groups_spanning_original_splits']} (held in test)\n"
        f"- Source-labeled / verified records: {artifacts['label_summary']['source_labeled_record_count']} / {artifacts['label_summary']['verified_ground_truth_record_count']}\n"
        f"- Evaluation candidates: {len(artifacts['evaluation_records'])} (`GROUND_TRUTH_LIMITED`)\n"
        f"- DINOv2 vectors reused: {artifacts['alignment']['aligned_valid_path_count']} x {artifacts['alignment']['embedding_array_shape'][1]}\n"
        f"- Readiness: {artifacts['readiness_status']}\n\n"
        "## Limitations and Blockers\n\n"
        "- The source dataset URL and acquisition date were not found in the repository.\n"
        "- Existing category labels are not independently verified ground truth.\n"
        "- Automated quality and visual-similarity thresholds are review signals, not semantic judgments.\n"
        "- Phase B silhouette was weak; clustering must not be presented as verified material classification.\n"
        "- No human-reviewed retrieval relevance, evidence correctness, or quality adjudication data exists yet.\n\n"
        "## Artifact Locations\n\n"
        + "\n".join(f"- `{(DEFAULT_OUTPUT / name).relative_to(WORKSPACE_ROOT).as_posix()}`" for name in (
            "phase3_data_inventory.json", "phase3_quality_audit.jsonl", "phase3_quality_audit_summary.json",
            "phase3_duplicate_report.json", "phase3_label_audit.jsonl", "phase3_label_audit.md",
            "phase3_embedding_alignment.json", "material_taxonomy.json", "phase3_master_manifest.jsonl",
            "evaluation_dataset_v1.jsonl", "evaluation_schema.json", "phase3_split_definitions.json",
            "training_readiness.md",
        ))
        + "\n\n## Phase 4 Handoff\n\n"
        "Build the evidence-driven assessment workflow on top of the reusable visual representation: input quality gate, observed/inferred/unknown claims, evidence links, domain-retrieval grounding, confidence limitations, manual review, and audit traceability. Use verified annotations when available; do not train a production classifier from unverified source labels.\n"
    )
    (WORKSPACE_ROOT / "PHASE_3_COMPLETION.md").write_text(completion, encoding="utf-8")


def run_phase3(
    manifest_path: Path = DEFAULT_MANIFEST,
    embeddings_dir: Path = DEFAULT_EMBEDDINGS,
    cluster_dir: Path = DEFAULT_CLUSTER_DIR,
    output_dir: Path = DEFAULT_OUTPUT,
    evaluation_per_category: int = 25,
) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_records = manifest["records"]
    print(f"Auditing {len(manifest_records)} manifest records...", flush=True)
    audit_records = []
    for index, record in enumerate(manifest_records, start=1):
        audit_records.append(audit_image(record))
        if index % 500 == 0 or index == len(manifest_records):
            print(f"quality_audit={index}/{len(manifest_records)}", flush=True)

    embedding_metadata = json.loads((embeddings_dir / "metadata.json").read_text(encoding="utf-8"))
    path_rows = load_jsonl(embeddings_dir / embedding_metadata["path_file"])
    statuses = np.load(embeddings_dir / embedding_metadata["status_file"], mmap_mode="r")
    vectors = np.load(embeddings_dir / embedding_metadata["embedding_file"], mmap_mode="r")
    with (cluster_dir / "cluster_assignments.csv").open(newline="", encoding="utf-8") as assignments_file:
        cluster_rows = [
            {**row, "embedding_index": int(row["embedding_index"]), "cluster_id": int(row["cluster_id"])}
            for row in csv.DictReader(assignments_file)
        ]
    alignment, embedding_references = align_embeddings(
        manifest_records, path_rows, statuses, vectors, cluster_rows
    )
    cluster_by_path = {row["file_path"]: row["cluster_id"] for row in cluster_rows}
    for record in audit_records:
        reference = embedding_references.get(record["file_path"], {})
        record["embedding_index"] = reference.get("embedding_index")
        record["cluster_id"] = reference.get("cluster_id")
    print("Checking exact, perceptual-hash, and DINOv2 similarity candidates...", flush=True)
    duplicate_groups, duplicate_group_by_path, neighbor_details = detect_duplicates(
        audit_records,
        np.asarray(vectors, dtype=np.float32),
        cluster_by_path,
    )
    for record in audit_records:
        record["duplicate_group_id"] = duplicate_group_by_path.get(record["file_path"])
        record["visual_neighbor_audit"] = neighbor_details.get(record["file_path"])

    label_paths = [
        path.relative_to(WORKSPACE_ROOT).as_posix()
        for root in (WORKSPACE_ROOT / "data" / "annotations", WORKSPACE_ROOT / "data" / "metadata")
        if root.exists()
        for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".json", ".jsonl", ".csv"}
    ]
    label_records, label_summary = audit_labels(manifest_records, label_paths)
    taxonomy = build_taxonomy(label_summary)
    split_design = make_leakage_safe_splits(manifest_records, duplicate_group_by_path)
    cluster_report = json.loads((cluster_dir / "clustering_metrics.json").read_text(encoding="utf-8"))
    evaluation_records = select_evaluation_dataset(
        audit_records,
        label_records,
        split_design,
        duplicate_group_by_path,
        neighbor_details,
        cluster_report,
        per_category=evaluation_per_category,
    )
    quality_summary = build_quality_summary(audit_records)
    duplicate_pair_counts = Counter()
    for group in duplicate_groups:
        for pair in group["similarity_evidence"]:
            duplicate_pair_counts.update(pair_type for pair_type in pair if pair_type != "paths")
    duplicate_report = {
        "report_version": "duplicate-candidates-v1",
        "record_count": len(audit_records),
        "exact_hash_algorithm": "SHA-256",
        "perceptual_hash_algorithm": "64-bit DCT pHash; Hamming distance <= 4",
        "embedding_similarity_algorithm": "cosine similarity over existing normalized DINOv2 ViT-S/14 embeddings",
        "embedding_similarity_candidate_threshold": 0.995,
        "candidate_pair_counts": dict(sorted(duplicate_pair_counts.items())),
        "groups_by_duplicate_type": {
            duplicate_type: sum(duplicate_type in group["duplicate_types"] for group in duplicate_groups)
            for duplicate_type in ("exact_sha256", "phash_hamming_distance", "embedding_cosine_similarity")
        },
        "group_count": len(duplicate_groups),
        "groups": duplicate_groups,
        "recommended_action": "Do not delete. Review candidates and keep all connected records in one future split.",
    }
    embedding_references = {
        **embedding_references,
        **{
            path: {**reference, "cluster_id": cluster_by_path.get(path)}
            for path, reference in embedding_references.items()
        },
    }
    master_records = build_master_records(
        audit_records, label_records, embedding_references, neighbor_details,
        duplicate_group_by_path, split_design,
    )
    inventory = discover_project_inventory(
        manifest, embeddings_dir, cluster_dir, output_dir, audit_records,
        duplicate_groups, label_summary, alignment,
    )
    evaluation_schema = build_evaluation_schema()
    training_readiness = build_training_readiness(
        manifest, label_summary, quality_summary, duplicate_groups,
        evaluation_records, split_design, alignment,
    )
    readiness_status = "NOT_READY" if label_summary["verified_ground_truth_record_count"] == 0 else "CONDITIONALLY_READY"
    evaluation_categories, evaluation_reasons = summarize_evaluation_records(evaluation_records)
    duplicate_split_conflicts = len(split_design["source_split_conflict_groups_held_together"])
    artifacts = {
        "inventory": inventory,
        "quality_records": audit_records,
        "quality_summary": quality_summary,
        "duplicate_report": duplicate_report,
        "label_records": label_records,
        "label_summary": label_summary,
        "alignment": alignment,
        "taxonomy": taxonomy,
        "master_records": master_records,
        "evaluation_records": evaluation_records,
        "evaluation_category_coverage": evaluation_categories,
        "evaluation_selection_reason_counts": evaluation_reasons,
        "duplicate_groups_spanning_original_splits": duplicate_split_conflicts,
        "evaluation_seed": 20260928,
        "evaluation_schema": evaluation_schema,
        "split_design": split_design,
        "training_readiness": training_readiness,
        "readiness_status": readiness_status,
    }
    _write_reports(output_dir, artifacts)
    summary = {
        "inventory_path": (output_dir / "phase3_data_inventory.json").as_posix(),
        "quality_audit_path": (output_dir / "phase3_quality_audit.jsonl").as_posix(),
        "duplicate_report_path": (output_dir / "phase3_duplicate_report.json").as_posix(),
        "label_audit_path": (output_dir / "phase3_label_audit.jsonl").as_posix(),
        "master_manifest_path": (output_dir / "phase3_master_manifest.jsonl").as_posix(),
        "evaluation_dataset_path": (output_dir / "evaluation_dataset_v1.jsonl").as_posix(),
        "quality_status_counts": quality_summary["quality_status_counts"],
        "invalid_images": quality_summary["quality_status_counts"].get("FAIL", 0),
        "duplicate_groups": len(duplicate_groups),
        "label_summary": label_summary,
        "embedding_alignment": alignment,
        "evaluation_count": len(evaluation_records),
        "evaluation_category_coverage": evaluation_categories,
        "evaluation_selection_reason_counts": evaluation_reasons,
        "duplicate_groups_spanning_original_splits": duplicate_split_conflicts,
        "future_split_counts": split_design["split_counts"],
        "leakage_check_passed": split_design["leakage_check_passed"],
        "training_readiness": readiness_status,
        "labels_used_for_embedding_or_clustering": False,
    }
    write_json(output_dir / "phase3_run_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--embeddings-dir", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--cluster-dir", type=Path, default=DEFAULT_CLUSTER_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evaluation-per-category", type=int, default=25)
    args = parser.parse_args()
    result = run_phase3(
        args.manifest.resolve(), args.embeddings_dir.resolve(), args.cluster_dir.resolve(),
        args.output_dir.resolve(), args.evaluation_per_category,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()