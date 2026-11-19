"""
Waste-image similarity engine (unsupervised).

Uses the Phase B artifacts already in the repository:
- data/embeddings/dinov2_vits14/  L2-normalised DINOv2 ViT-S/14 CLS vectors (11,521 x 384)
- data/embeddings/clusters/       K-Means (k=8) assignments fitted without labels

For a new photo it embeds the image with the same DINOv2 model, then reports
the nearest dataset images, the folder (source) categories of those
neighbours, the nearest K-Means cluster and how novel the image is.

Folder categories are *unverified source labels*, never ground truth, and the
clustering silhouette is weak (~0.05). Results are evidence for the LLM to
reason over, not a classification.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

log = logging.getLogger(__name__)

EMBEDDED_STATUS = 1
NEAR_DUPLICATE_SIMILARITY = 0.995   # same threshold the Phase 3 duplicate audit used
LOW_SIMILARITY_WARNING = 0.60       # heuristic novelty flag, not a calibrated threshold

CAVEATS = [
    "Neighbour categories come from dataset folder names; they are unverified source labels, not ground truth.",
    "K-Means clusters were fitted without labels and separate poorly (silhouette about 0.05); "
    "treat cluster membership as weak evidence.",
    "Visual similarity cannot determine alloy grade, chemistry or contamination levels; "
    "confirm with XRF/LIBS or lab analysis before pricing or sorting decisions.",
]

Embedder = Callable[[bytes], np.ndarray]


@dataclass
class DatasetRecord:
    index: int
    file_path: str
    category: str
    split: str
    cluster_id: Optional[int]


def _category_and_split(file_path: str) -> tuple[str, str]:
    parts = Path(file_path).parts
    for i, part in enumerate(parts):
        # .../<split>/<category>/<file>; the category must not be the filename itself
        if part.lower() in {"train", "test"} and i + 2 < len(parts):
            return parts[i + 1], part.lower()
    return "unknown", "unknown"


class DinoV2Embedder:
    """Lazy wrapper around the project's DINOv2 embedding service (needs torch)."""

    def __init__(self) -> None:
        self._service = None
        self._lock = threading.Lock()

    def __call__(self, image_bytes: bytes) -> np.ndarray:
        from PIL import Image

        with self._lock:
            if self._service is None:
                from app.services.dinov2_embedding_service import DINOv2EmbeddingService

                self._service = DINOv2EmbeddingService(device="auto")
        with Image.open(io.BytesIO(image_bytes)) as img:
            rgb = img.convert("RGB")
        return self._service.embed_images([rgb])[0]


class WasteSimilarityIndex:
    """Nearest-neighbour + cluster lookup over the stored DINOv2 embeddings."""

    def __init__(
        self,
        embeddings_dir: Path,
        embedder: Optional[Embedder] = None,
        model_subdir: str = "dinov2_vits14",
    ) -> None:
        self.embeddings_dir = Path(embeddings_dir)
        self.model_dir = self.embeddings_dir / model_subdir
        self.cluster_dir = self.embeddings_dir / "clusters"
        self._embedder = embedder
        self._embedder_error: Optional[str] = None
        self._loaded = False
        self._load_lock = threading.Lock()

        self.vectors: np.ndarray = np.empty((0, 0), dtype=np.float32)
        self.records: List[DatasetRecord] = []
        self.centroids: Dict[int, np.ndarray] = {}
        self.cluster_composition: Dict[int, Counter] = {}
        self.metadata: dict = {}
        self.clustering_metrics: dict = {}

    # ------------------------------------------------------------------ loading
    @property
    def available(self) -> bool:
        return (self.model_dir / "embeddings.npy").exists() and (self.model_dir / "image_paths.jsonl").exists()

    def load(self) -> None:
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            if not self.available:
                raise FileNotFoundError(f"DINOv2 embeddings not found in {self.model_dir}")

            vectors = np.load(self.model_dir / "embeddings.npy").astype(np.float32, copy=False)
            status_path = self.model_dir / "status.npy"
            status = np.load(status_path) if status_path.exists() else np.full(len(vectors), EMBEDDED_STATUS)

            paths: Dict[int, str] = {}
            with open(self.model_dir / "image_paths.jsonl", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        row = json.loads(line)
                        paths[int(row["embedding_index"])] = row["file_path"]

            clusters: Dict[int, int] = {}
            assignments = self.cluster_dir / "cluster_assignments.csv"
            if assignments.exists():
                with open(assignments, encoding="utf-8", newline="") as fh:
                    for row in csv.DictReader(fh):
                        clusters[int(row["embedding_index"])] = int(row["cluster_id"])

            keep = [i for i in range(len(vectors)) if status[i] == EMBEDDED_STATUS and i in paths]
            self.vectors = vectors[keep]
            self.records = []
            for row_idx, emb_idx in enumerate(keep):
                category, split = _category_and_split(paths[emb_idx])
                self.records.append(
                    DatasetRecord(row_idx, paths[emb_idx], category, split, clusters.get(emb_idx))
                )

            members: Dict[int, List[int]] = defaultdict(list)
            composition: Dict[int, Counter] = defaultdict(Counter)
            for rec in self.records:
                if rec.cluster_id is not None:
                    members[rec.cluster_id].append(rec.index)
                    composition[rec.cluster_id][rec.category] += 1
            for cid, idxs in members.items():
                centroid = self.vectors[idxs].mean(axis=0)
                self.centroids[cid] = centroid / (np.linalg.norm(centroid) + 1e-12)
            self.cluster_composition = dict(composition)

            for name, target in (("metadata.json", "metadata"),):
                p = self.model_dir / name
                if p.exists():
                    setattr(self, target, json.loads(p.read_text(encoding="utf-8")))
            metrics = self.cluster_dir / "clustering_metrics.json"
            if metrics.exists():
                self.clustering_metrics = json.loads(metrics.read_text(encoding="utf-8"))

            self._loaded = True
            log.info("Waste index loaded: %d vectors, %d clusters", len(self.records), len(self.centroids))

    # ---------------------------------------------------------------- embedding
    def embed(self, image_bytes: bytes) -> Optional[np.ndarray]:
        """Embed an image; returns None (and records why) when DINOv2 is unavailable."""
        if self._embedder is None:
            self._embedder = DinoV2Embedder()
        try:
            vec = np.asarray(self._embedder(image_bytes), dtype=np.float32).reshape(-1)
        except ImportError as exc:
            self._embedder_error = (
                f"DINOv2 needs torch/torchvision ({exc.name or exc}); install backend/requirements-phase-b.txt"
            )
            return None
        except Exception as exc:  # model download / decode failures
            self._embedder_error = f"DINOv2 embedding failed: {exc}"
            log.warning(self._embedder_error)
            return None
        return vec / (np.linalg.norm(vec) + 1e-12)

    @property
    def embedder_error(self) -> Optional[str]:
        return self._embedder_error

    # ----------------------------------------------------------------- queries
    def cluster_profile(self, cluster_id: int, top: int = 9) -> dict:
        self.load()
        if cluster_id not in self.cluster_composition:
            raise KeyError(f"Unknown cluster_id {cluster_id}; valid: {sorted(self.cluster_composition)}")
        comp = self.cluster_composition[cluster_id]
        total = sum(comp.values())
        return {
            "cluster_id": cluster_id,
            "size": total,
            "source_category_composition": [
                {"category": c, "count": n, "share": round(n / total, 3)} for c, n in comp.most_common(top)
            ],
            "purity": round(comp.most_common(1)[0][1] / total, 3) if total else 0.0,
        }

    def overview(self) -> dict:
        self.load()
        cats = Counter(r.category for r in self.records)
        splits = Counter(r.split for r in self.records)
        selected = self.clustering_metrics.get("selected_metrics", {})
        return {
            "image_count": len(self.records),
            "embedding_model": self.metadata.get("model_name", "dinov2_vits14"),
            "embedding_dimension": int(self.vectors.shape[1]) if self.vectors.size else 0,
            "source_categories": dict(cats.most_common()),
            "splits": dict(splits),
            "clustering": {
                "method": self.clustering_metrics.get("method", "KMeans"),
                "k": self.clustering_metrics.get("selected_k", len(self.centroids)),
                "silhouette": selected.get("silhouette_score"),
                "clusters": [self.cluster_profile(cid, top=3) for cid in sorted(self.cluster_composition)],
            },
            "caveats": CAVEATS,
        }

    def query(self, vector: np.ndarray, top_k: int = 8) -> dict:
        self.load()
        top_k = max(1, min(int(top_k), 25))
        sims = self.vectors @ vector.astype(np.float32)
        order = np.argsort(-sims)[:top_k]

        neighbours = []
        votes: Dict[str, float] = defaultdict(float)
        for rank, idx in enumerate(order, start=1):
            rec = self.records[int(idx)]
            sim = float(sims[idx])
            votes[rec.category] += max(sim, 0.0)
            neighbours.append(
                {
                    "rank": rank,
                    "similarity": round(sim, 4),
                    "source_category": rec.category,
                    "split": rec.split,
                    "cluster_id": rec.cluster_id,
                    "file": rec.file_path,
                }
            )
        vote_total = sum(votes.values()) or 1.0
        category_votes = sorted(
            ({"category": c, "weighted_share": round(v / vote_total, 3)} for c, v in votes.items()),
            key=lambda d: -d["weighted_share"],
        )

        nearest_cluster = None
        if self.centroids:
            cid, csim = max(((c, float(v @ vector)) for c, v in self.centroids.items()), key=lambda t: t[1])
            nearest_cluster = {"centroid_similarity": round(csim, 4), **self.cluster_profile(cid, top=4)}

        max_sim = float(sims[order[0]])
        if max_sim >= NEAR_DUPLICATE_SIMILARITY:
            novelty = "near_duplicate_of_dataset_image"
        elif max_sim < LOW_SIMILARITY_WARNING:
            novelty = "low_similarity_possibly_out_of_distribution"
        else:
            novelty = "within_dataset_distribution"

        top_share = category_votes[0]["weighted_share"] if category_votes else 0.0
        agreement = "strong" if top_share >= 0.75 else "moderate" if top_share >= 0.5 else "weak"
        return {
            "status": "ok",
            "neighbours": neighbours,
            "neighbour_category_votes": category_votes,
            "neighbour_agreement": agreement,
            "max_similarity": round(max_sim, 4),
            "novelty": novelty,
            "nearest_cluster": nearest_cluster,
            "caveats": CAVEATS,
        }

    def analyze_image(self, image_bytes: bytes, top_k: int = 8) -> dict:
        if not self.available:
            return {"status": "unavailable", "reason": f"No embeddings found in {self.model_dir}"}
        vec = self.embed(image_bytes)
        if vec is None:
            return {
                "status": "embedding_unavailable",
                "reason": self.embedder_error,
                "hint": "Visual reasoning by the LLM still works; dataset similarity needs the DINOv2 model.",
            }
        self.load()
        if vec.shape[0] != self.vectors.shape[1]:
            return {"status": "error", "reason": f"Embedding dim {vec.shape[0]} != index dim {self.vectors.shape[1]}"}
        return self.query(vec, top_k=top_k)


def resolve_dataset_file(rel_path: str, roots: Sequence[Path]) -> Optional[Path]:
    """Map a manifest path like data/raw/wastes/train/x/y.jpg onto an existing image root."""
    parts = Path(rel_path).parts
    for i, part in enumerate(parts):
        if part.lower() in {"train", "test"}:
            tail = Path(*parts[i:])
            for root in roots:
                candidate = Path(root) / tail
                if candidate.exists():
                    return candidate
            break
    return None
