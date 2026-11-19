"""Choose K and cluster saved embeddings without loading category or split metadata."""
import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import (
    adjusted_mutual_info_score,
    adjusted_rand_score,
    completeness_score,
    homogeneity_score,
    silhouette_score,
    v_measure_score,
)

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EMBEDDINGS_DIR = WORKSPACE_ROOT / "data" / "embeddings" / "dinov2_vits14"
DEFAULT_CLUSTER_DIR = WORKSPACE_ROOT / "data" / "embeddings" / "clusters"


def _load_embedding_rows(embeddings_dir: Path) -> tuple[np.ndarray, list[dict]]:
    metadata = json.loads((embeddings_dir / "metadata.json").read_text(encoding="utf-8"))
    embeddings_path = embeddings_dir / metadata["embedding_file"]
    statuses = np.load(embeddings_dir / metadata["status_file"], mmap_mode="r")
    paths = [
        json.loads(line)
        for line in (embeddings_dir / metadata["path_file"]).read_text(encoding="utf-8").splitlines()
    ]
    valid_indices = np.flatnonzero(statuses == 1)
    if len(valid_indices) < 3:
        raise ValueError("At least three successfully embedded images are required")
    vectors = np.load(embeddings_path, mmap_mode="r")
    if vectors.shape[0] != len(paths) or statuses.shape[0] != len(paths):
        raise ValueError("Embedding, status, and path index row counts do not match")
    return np.asarray(vectors[valid_indices], dtype=np.float32), [paths[i] for i in valid_indices]


def run_clustering(
    embeddings_dir: Path,
    output_dir: Path,
    k_values: list[int],
    silhouette_sample: int = 1000,
    random_state: int = 42,
    representative_count: int = 5,
) -> dict:
    vectors, image_rows = _load_embedding_rows(embeddings_dir)
    sample_size = min(silhouette_sample, len(vectors))
    if len(set(k_values)) < 2 or any(k < 2 or k >= len(vectors) for k in k_values):
        raise ValueError("Provide at least two distinct K values, each between 2 and image count - 1")

    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    metrics = []
    fitted = {}
    for k in k_values:
        model = KMeans(
            n_clusters=k,
            n_init=5,
            max_iter=200,
            random_state=random_state,
            algorithm="lloyd",
        )
        labels = model.fit_predict(vectors)
        silhouette = silhouette_score(
            vectors,
            labels,
            sample_size=sample_size,
            random_state=random_state,
        )
        counts = Counter(int(label) for label in labels)
        result = {
            "k": k,
            "silhouette_score": float(silhouette),
            "inertia": float(model.inertia_),
            "iterations": int(model.n_iter_),
            "cluster_sizes": {str(key): counts[key] for key in sorted(counts)},
        }
        metrics.append(result)
        fitted[k] = (model, labels)
        print(
            f"evaluated_k={k} silhouette={silhouette:.6f} "
            f"inertia={model.inertia_:.3f} elapsed={time.monotonic() - started:.1f}s",
            flush=True,
        )

    selected = max(metrics, key=lambda item: item["silhouette_score"])
    selected_k = selected["k"]
    model, labels = fitted[selected_k]
    cluster_csv = output_dir / "cluster_assignments.csv"
    with cluster_csv.open("w", newline="", encoding="utf-8") as cluster_file:
        writer = csv.DictWriter(
            cluster_file,
            fieldnames=("image_id", "file_path", "embedding_index", "cluster_id"),
        )
        writer.writeheader()
        for row, label in zip(image_rows, labels, strict=True):
            writer.writerow(
                {
                    "image_id": row["image_id"],
                    "file_path": row["file_path"],
                    "embedding_index": row["embedding_index"],
                    "cluster_id": int(label),
                }
            )

    cluster_summaries = []
    for cluster_id, count in sorted(Counter(int(value) for value in labels).items()):
        members = np.flatnonzero(labels == cluster_id)
        distances = np.sum((vectors[members] - model.cluster_centers_[cluster_id]) ** 2, axis=1)
        representatives = [
            image_rows[members[position]]["file_path"]
            for position in np.argsort(distances)[:representative_count]
        ]
        cluster_summaries.append(
            {
                "cluster_id": cluster_id,
                "size": count,
                "representative_images": representatives,
            }
        )

    elapsed = time.monotonic() - started
    report = {
        "method": "KMeans",
        "embedding_directory": str(embeddings_dir),
        "embedding_count": len(vectors),
        "embedding_dimension": int(vectors.shape[1]),
        "candidate_k_values": k_values,
        "silhouette_sample_size": sample_size,
        "selection_metric": "maximum sampled silhouette score; labels not loaded",
        "selected_k": selected_k,
        "selected_metrics": selected,
        "candidate_metrics": metrics,
        "cluster_summaries": cluster_summaries,
        "assignment_file": cluster_csv.name,
        "elapsed_seconds": round(elapsed, 2),
        "labels_used_for_clustering": False,
    }
    (output_dir / "clustering_metrics.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_pca_visualization(vectors, labels, output_dir / "clusters_pca.png", random_state)
    return report


def _write_pca_visualization(
    vectors: np.ndarray,
    labels: np.ndarray,
    output_path: Path,
    random_state: int,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    coordinates = PCA(n_components=2, random_state=random_state).fit_transform(vectors)
    figure, axis = plt.subplots(figsize=(10, 8))
    scatter = axis.scatter(
        coordinates[:, 0],
        coordinates[:, 1],
        c=labels,
        cmap="tab20",
        s=8,
        alpha=0.72,
    )
    axis.set_title("DINOv2 embedding clusters (PCA)")
    axis.set_xlabel("Principal component 1")
    axis.set_ylabel("Principal component 2")
    figure.colorbar(scatter, ax=axis, label="Cluster ID")
    figure.tight_layout()
    figure.savefig(output_path, dpi=160)
    plt.close(figure)


def evaluate_labels_after_clustering(
    manifest_path: Path,
    assignment_path: Path,
    output_dir: Path,
) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    category_by_path = {
        record["file_path"]: record["category_name"]
        for record in manifest["records"]
        if record.get("is_image") is True
        and record.get("is_valid") is True
        and record.get("category_name") is not None
    }
    assignment_rows = []
    with assignment_path.open(newline="", encoding="utf-8") as assignment_file:
        for row in csv.DictReader(assignment_file):
            category = category_by_path.get(row["file_path"])
            if category is not None:
                assignment_rows.append((category, int(row["cluster_id"])))
    if len(assignment_rows) < 2:
        raise ValueError("Fewer than two clustered images matched manifest categories")

    true_categories = [row[0] for row in assignment_rows]
    clusters = [row[1] for row in assignment_rows]
    report = {
        "stage": "post_hoc_label_evaluation",
        "source_manifest": str(manifest_path),
        "source_assignments": str(assignment_path),
        "matched_image_count": len(assignment_rows),
        "category_names_used_only_after_clustering": sorted(set(true_categories)),
        "adjusted_rand_index": float(adjusted_rand_score(true_categories, clusters)),
        "adjusted_mutual_information": float(adjusted_mutual_info_score(true_categories, clusters)),
        "homogeneity": float(homogeneity_score(true_categories, clusters)),
        "completeness": float(completeness_score(true_categories, clusters)),
        "v_measure": float(v_measure_score(true_categories, clusters)),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "posthoc_label_evaluation.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    contingency = defaultdict(Counter)
    for category, cluster_id in assignment_rows:
        contingency[category][cluster_id] += 1
    with (output_dir / "posthoc_contingency.csv").open(
        "w", newline="", encoding="utf-8"
    ) as contingency_file:
        writer = csv.writer(contingency_file)
        cluster_ids = sorted(set(clusters))
        writer.writerow(["category_name_metadata", *cluster_ids])
        for category in sorted(contingency):
            writer.writerow([category, *(contingency[category][cluster] for cluster in cluster_ids)])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embeddings-dir", type=Path, default=DEFAULT_EMBEDDINGS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_CLUSTER_DIR)
    parser.add_argument("--k-values", default="2,3,4,5,6,8,10,12")
    parser.add_argument("--silhouette-sample", type=int, default=1000)
    parser.add_argument("--representative-count", type=int, default=5)
    parser.add_argument("--evaluate-labels", action="store_true")
    parser.add_argument("--manifest", type=Path, default=WORKSPACE_ROOT / "data" / "manifests" / "wastes_manifest.json")
    args = parser.parse_args()

    if args.evaluate_labels:
        result = evaluate_labels_after_clustering(
            args.manifest.resolve(),
            args.output_dir.resolve() / "cluster_assignments.csv",
            args.output_dir.resolve(),
        )
    else:
        k_values = [int(value) for value in args.k_values.split(",") if value]
        result = run_clustering(
            args.embeddings_dir.resolve(),
            args.output_dir.resolve(),
            k_values,
            silhouette_sample=args.silhouette_sample,
            representative_count=args.representative_count,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()