from pathlib import Path

from PIL import Image

from scripts.generate_manifest import build_manifest
from scripts.validate_dataset import validate_dataset


def _write_image(path: Path, image_format: str, size: tuple[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=(30, 120, 210)).save(path, format=image_format)


def test_validation_discovers_images_recursively_and_builds_consistent_manifest(
    tmp_path: Path,
) -> None:
    dataset_root = tmp_path / "WASTES"
    _write_image(dataset_root / "train" / "metal" / "direct.jpg", "JPEG", (3, 2))
    _write_image(
        dataset_root / "test" / "plastic" / "nested" / "nested.png",
        "PNG",
        (4, 5),
    )
    _write_image(dataset_root / "test" / "plastic" / "animated.gif", "GIF", (2, 2))
    (dataset_root / "train" / "metal" / "broken.jpg").write_bytes(b"not an image")
    (dataset_root / "train" / "metal" / "notes.txt").write_text("not an image")
    (dataset_root / "train" / "empty-category").mkdir()
    (dataset_root / "test" / "plastic" / "empty").mkdir()

    report = validate_dataset(dataset_root)
    manifest = build_manifest(dataset_root)
    summary = report["summary"]

    assert (dataset_root / "train").is_dir()
    assert (dataset_root / "test").is_dir()
    assert summary["total_image_count"] == 4
    assert summary["splits"]["train"]["image_count"] == 2
    assert summary["splits"]["test"]["image_count"] == 2
    assert summary["categories"] == ["empty-category", "metal", "plastic"]
    assert summary["formats_valid_images"] == {"JPEG": 1, "PNG": 1}
    assert summary["dimensions_valid_images"] == {"3x2": 1, "4x5": 1}
    assert summary["unreadable_image_count"] == 1
    assert summary["unsupported_format_count"] == 1
    assert summary["invalid_file_count"] == 3
    assert len(summary["empty_directories"]) == 2
    assert summary["missing_split_directories"] == []
    assert manifest["record_count"] == 5
    assert manifest["records"] == report["records"]
    required_fields = {
        "file_path",
        "split",
        "category_name",
        "image_format",
        "width",
        "height",
        "is_valid",
    }
    assert all(required_fields <= record.keys() for record in manifest["records"])
    assert "metadata only" in manifest["metadata_only_note"]
    assert "must not be passed" in manifest["metadata_only_note"]
    assert any(record["file_path"].endswith("direct.jpg") for record in report["records"])
    assert any(record["file_path"].endswith("nested.png") for record in report["records"])


def test_validation_reports_missing_split_directories(tmp_path: Path) -> None:
    dataset_root = tmp_path / "WASTES"
    (dataset_root / "train" / "metal").mkdir(parents=True)

    report = validate_dataset(dataset_root)

    assert report["summary"]["missing_split_directories"] == [
        (dataset_root / "test").as_posix()
    ]
    assert report["summary"]["splits"]["train"]["categories"] == ["metal"]
    assert report["summary"]["splits"]["test"]["image_count"] == 0