"""Extract resumable, label-blind DINOv2 embeddings from a Phase A manifest."""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = WORKSPACE_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.dinov2_embedding_service import (  # noqa: E402
    EMBEDDING_DIMENSION,
    IMAGE_SIZE,
    MODEL_NAME,
    DINOv2EmbeddingService,
)


DEFAULT_MANIFEST = WORKSPACE_ROOT / "data" / "manifests" / "wastes_manifest.json"
DEFAULT_OUTPUT = WORKSPACE_ROOT / "data" / "embeddings" / "dinov2_vits14"


def load_valid_image_paths(manifest_path: Path, limit: int | None = None) -> tuple[list[str], str]:
    """Return only valid image paths; labels and split fields are never read."""
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    paths = [
        record["file_path"]
        for record in manifest["records"]
        if record.get("is_image") is True and record.get("is_valid") is True
    ]
    if limit is not None:
        paths = paths[:limit]
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    return paths, digest


def _write_json_atomic(path: Path, payload: dict) -> None:
    temporary_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for attempt in range(10):
        try:
            os.replace(temporary_path, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.1 * (attempt + 1))


def _load_or_create_store(
    output_dir: Path,
    paths: list[str],
    manifest_sha256: str,
) -> tuple[np.memmap, np.memmap, dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    embeddings_path = output_dir / "embeddings.npy"
    status_path = output_dir / "status.npy"
    paths_path = output_dir / "image_paths.jsonl"
    metadata_path = output_dir / "metadata.json"
    expected = {
        "model_name": MODEL_NAME,
        "embedding_dimension": EMBEDDING_DIMENSION,
        "image_size": IMAGE_SIZE,
        "manifest_sha256": manifest_sha256,
        "image_count": len(paths),
    }

    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        for key, value in expected.items():
            if metadata.get(key) != value:
                raise ValueError(
                    f"Existing output metadata differs for {key}; choose a new output directory"
                )
        if not all(path.exists() for path in (embeddings_path, status_path, paths_path)):
            raise ValueError("Embedding output is incomplete; preserve it and use a new output directory")
        stored_paths = [
            json.loads(line)["file_path"]
            for line in paths_path.read_text(encoding="utf-8").splitlines()
        ]
        if stored_paths != paths:
            raise ValueError("Stored image paths do not match the manifest; use a new output directory")
        embeddings = np.lib.format.open_memmap(embeddings_path, mode="r+")
        statuses = np.lib.format.open_memmap(status_path, mode="r+")
        if embeddings.shape != (len(paths), EMBEDDING_DIMENSION) or statuses.shape != (len(paths),):
            raise ValueError("Stored embedding arrays have unexpected dimensions")
        return embeddings, statuses, metadata

    existing_files = [embeddings_path, status_path, paths_path]
    if any(path.exists() for path in existing_files):
        raise ValueError("Output files exist without metadata; use a new output directory")

    embeddings = np.lib.format.open_memmap(
        embeddings_path,
        mode="w+",
        dtype=np.float32,
        shape=(len(paths), EMBEDDING_DIMENSION),
    )
    statuses = np.lib.format.open_memmap(
        status_path,
        mode="w+",
        dtype=np.uint8,
        shape=(len(paths),),
    )
    statuses[:] = 0
    with paths_path.open("w", encoding="utf-8", newline="\n") as path_file:
        for index, file_path in enumerate(paths):
            path_file.write(
                json.dumps(
                    {"image_id": f"image_{index:06d}", "embedding_index": index, "file_path": file_path},
                    ensure_ascii=False,
                )
                + "\n"
            )
    metadata = {
        **expected,
        "embedding_file": embeddings_path.name,
        "path_file": paths_path.name,
        "status_file": status_path.name,
        "status_values": {"0": "pending", "1": "embedded", "2": "failed"},
        "preprocessing": "RGB; resize shortest side to 256; bicubic center crop 224; ImageNet normalization",
        "feature_source": "normalized DINOv2 x_norm_clstoken only",
        "labels_used_as_features": False,
    }
    _write_json_atomic(metadata_path, metadata)
    return embeddings, statuses, metadata


def extract_embeddings(
    manifest_path: Path,
    output_dir: Path,
    batch_size: int = 4,
    device: str = "auto",
    limit: int | None = None,
    retry_failed: bool = False,
) -> dict:
    paths, manifest_sha256 = load_valid_image_paths(manifest_path, limit)
    if not paths:
        raise ValueError("The manifest contains no valid images to embed")
    embeddings, statuses, metadata = _load_or_create_store(
        output_dir, paths, manifest_sha256
    )
    if retry_failed:
        statuses[statuses == 2] = 0
        statuses.flush()
    service = DINOv2EmbeddingService(device=device)
    failures_path = output_dir / "failures.jsonl"
    elapsed_before_run = float(
        metadata.get("cumulative_elapsed_seconds", metadata.get("elapsed_seconds", 0.0))
    )
    started = time.monotonic()
    attempted_this_run = 0

    def embed_batch(batch_indices: list[int], images: list[object]) -> None:
        nonlocal attempted_this_run
        try:
            batch_tensor = service.preprocess_images(images)
            vectors = service.embed_tensor(batch_tensor)
        except RuntimeError as error:
            is_cuda_oom = "out of memory" in str(error).lower() and service.device.type == "cuda"
            if is_cuda_oom and len(batch_indices) > 1:
                service.torch.cuda.empty_cache()
                midpoint = len(batch_indices) // 2
                embed_batch(batch_indices[:midpoint], images[:midpoint])
                embed_batch(batch_indices[midpoint:], images[midpoint:])
                return
            _record_failures(batch_indices, paths, statuses, failures_path, error)
            attempted_this_run += len(batch_indices)
            return
        except Exception as error:
            _record_failures(batch_indices, paths, statuses, failures_path, error)
            attempted_this_run += len(batch_indices)
            return

        embeddings[batch_indices] = vectors
        statuses[batch_indices] = 1
        attempted_this_run += len(batch_indices)

    pending = np.flatnonzero(statuses == 0).tolist()
    total = len(paths)
    for offset in range(0, len(pending), batch_size):
        batch_indices = pending[offset : offset + batch_size]
        loaded_indices: list[int] = []
        loaded_images: list[object] = []
        for index in batch_indices:
            image_path = Path(paths[index])
            if not image_path.is_absolute():
                image_path = WORKSPACE_ROOT / image_path
            try:
                loaded_images.append(service.load_rgb_image(image_path))
                loaded_indices.append(index)
            except Exception as error:
                _record_failures([index], paths, statuses, failures_path, error)
                attempted_this_run += 1

        if loaded_indices:
            embed_batch(loaded_indices, loaded_images)
        embeddings.flush()
        statuses.flush()
        processed = int(np.count_nonzero(statuses))
        embedded = int(np.count_nonzero(statuses == 1))
        failures = int(np.count_nonzero(statuses == 2))
        elapsed = max(time.monotonic() - started, 1e-9)
        speed = attempted_this_run / elapsed
        cumulative_elapsed = elapsed_before_run + elapsed
        metadata.update(
            {
                "processed_count": processed,
                "embedded_count": embedded,
                "remaining_count": total - processed,
                "failed_count": failures,
                "elapsed_seconds": round(elapsed, 2),
                "cumulative_elapsed_seconds": round(cumulative_elapsed, 2),
                "processing_images_per_second": round(speed, 3),
                "cumulative_processing_images_per_second": round(
                    processed / max(cumulative_elapsed, 1e-9), 3
                ),
                "device": str(service.device),
                "requested_batch_size": batch_size,
            }
        )
        _write_json_atomic(output_dir / "metadata.json", metadata)
        print(
            f"processed={processed}/{total} remaining={total - processed} "
            f"speed={speed:.2f} images/s failures={failures} elapsed={elapsed:.1f}s",
            flush=True,
        )

    statuses.flush()
    embeddings.flush()
    metadata["processed_count"] = int(np.count_nonzero(statuses))
    metadata["embedded_count"] = int(np.count_nonzero(statuses == 1))
    metadata["remaining_count"] = total - metadata["processed_count"]
    metadata["failed_count"] = int(np.count_nonzero(statuses == 2))
    metadata["elapsed_seconds"] = round(time.monotonic() - started, 2)
    metadata["processing_images_per_second"] = round(
        attempted_this_run / max(time.monotonic() - started, 1e-9), 3
    )
    metadata["cumulative_elapsed_seconds"] = round(
        elapsed_before_run + time.monotonic() - started, 2
    )
    metadata["cumulative_processing_images_per_second"] = round(
        metadata["processed_count"] / max(metadata["cumulative_elapsed_seconds"], 1e-9),
        3,
    )
    _write_json_atomic(output_dir / "metadata.json", metadata)
    return metadata


def _record_failures(
    indices: list[int],
    paths: list[str],
    statuses: np.memmap,
    failures_path: Path,
    error: Exception,
) -> None:
    with failures_path.open("a", encoding="utf-8") as failures_file:
        for index in indices:
            statuses[index] = 2
            failures_file.write(
                json.dumps(
                    {
                        "image_id": f"image_{index:06d}",
                        "embedding_index": index,
                        "file_path": paths[index],
                        "error": f"{type(error).__name__}: {error}",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--limit", type=int, help="Embed only the first N valid manifest images")
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    if args.batch_size < 1 or (args.limit is not None and args.limit < 1):
        parser.error("--batch-size and --limit must be positive")
    result = extract_embeddings(
        args.manifest.resolve(),
        args.output_dir.resolve(),
        batch_size=args.batch_size,
        device=args.device,
        limit=args.limit,
        retry_failed=args.retry_failed,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()