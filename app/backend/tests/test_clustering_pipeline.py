import json
from pathlib import Path

import numpy as np

from scripts.cluster_embeddings import evaluate_labels_after_clustering, run_clustering


def test_clustering_is_separate_from_post_hoc_label_evaluation(tmp_path: Path) -> None:
    embeddings_dir = tmp_path / "embeddings"
    embeddings_dir.mkdir()
    paths = [
        {"image_id": f"image_{index:06d}", "embedding_index": index, "file_path": f"image-{index}.jpg"}
        for index in range(6)
    ]
    vectors = np.array(
        [[0.0, 0.0], [0.1, 0.0], [0.0, 0.1], [10.0, 10.0], [10.1, 10.0], [10.0, 10.1]],
        dtype=np.float32,
    )
    np.save(embeddings_dir / "embeddings.npy", vectors)
    np.save(embeddings_dir / "status.npy", np.ones(6, dtype=np.uint8))
    (embeddings_dir / "image_paths.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in paths),
        encoding="utf-8",
    )
    (embeddings_dir / "metadata.json").write_text(
        json.dumps(
            {
                "embedding_file": "embeddings.npy",
                "status_file": "status.npy",
                "path_file": "image_paths.jsonl",
            }
        ),
        encoding="utf-8",
    )

    cluster_dir = tmp_path / "clusters"
    discovery = run_clustering(
        embeddings_dir,
        cluster_dir,
        k_values=[2, 3],
        silhouette_sample=6,
        representative_count=2,
    )

    assert discovery["candidate_k_values"] == [2, 3]
    assert discovery["selected_k"] in [2, 3]
    assert discovery["labels_used_for_clustering"] is False
    assert sum(cluster["size"] for cluster in discovery["cluster_summaries"]) == 6
    assert (cluster_dir / "clusters_pca.png").is_file()

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "file_path": row["file_path"],
                        "is_image": True,
                        "is_valid": True,
                        "category_name": "group_a" if index < 3 else "group_b",
                    }
                    for index, row in enumerate(paths)
                ]
            }
        ),
        encoding="utf-8",
    )
    evaluation = evaluate_labels_after_clustering(
        manifest_path,
        cluster_dir / "cluster_assignments.csv",
        cluster_dir,
    )

    assert evaluation["stage"] == "post_hoc_label_evaluation"
    assert evaluation["matched_image_count"] == 6
    assert evaluation["adjusted_rand_index"] == 1.0
    assert (cluster_dir / "posthoc_contingency.csv").is_file()