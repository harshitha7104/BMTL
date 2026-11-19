import json
from pathlib import Path

import numpy as np
from PIL import Image

import scripts.extract_embeddings as extraction
from scripts.extract_embeddings import load_valid_image_paths


def test_embedding_input_uses_only_valid_image_paths(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "file_path": "train/metal/metal_0001.jpg",
                        "is_image": True,
                        "is_valid": True,
                        "category_name": "metal",
                        "split": "train",
                    },
                    {
                        "file_path": "test/plastic/plastic_0001.png",
                        "is_image": True,
                        "is_valid": False,
                        "category_name": "plastic",
                        "split": "test",
                    },
                    {
                        "file_path": "train/glass/glass_0001.gif",
                        "is_image": False,
                        "is_valid": False,
                        "category_name": "glass",
                        "split": "train",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    paths, manifest_hash = load_valid_image_paths(manifest_path)

    assert paths == ["train/metal/metal_0001.jpg"]
    assert len(manifest_hash) == 64


def test_embedding_extraction_resumes_and_accumulates_elapsed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image_path = tmp_path / "image.jpg"
    Image.new("RGB", (16, 16), color=(30, 120, 210)).save(image_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "records": [
                    {"file_path": str(image_path), "is_image": True, "is_valid": True}
                ]
            }
        ),
        encoding="utf-8",
    )

    class FakeEmbeddingService:
        def __init__(self, device: str) -> None:
            self.device = device

        @staticmethod
        def load_rgb_image(path: Path):
            with Image.open(path) as image:
                return image.convert("RGB")

        @staticmethod
        def preprocess_images(images):
            return images

        @staticmethod
        def embed_tensor(images):
            return np.ones((len(images), 384), dtype=np.float32)

    monkeypatch.setattr(extraction, "DINOv2EmbeddingService", FakeEmbeddingService)
    output_dir = tmp_path / "embeddings"

    first_run = extraction.extract_embeddings(
        manifest_path,
        output_dir,
        batch_size=1,
        device="cpu",
    )
    resumed_run = extraction.extract_embeddings(
        manifest_path,
        output_dir,
        batch_size=1,
        device="cpu",
    )

    assert first_run["embedded_count"] == 1
    assert resumed_run["embedded_count"] == 1
    assert resumed_run["remaining_count"] == 0
    assert resumed_run["cumulative_elapsed_seconds"] >= first_run["cumulative_elapsed_seconds"]