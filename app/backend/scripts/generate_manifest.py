"""Validate dataset images and write a metadata-only JSON manifest."""
import argparse
import json
from collections import Counter
from pathlib import Path

from PIL import Image


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_ROOT = WORKSPACE_ROOT / "data" / "raw" / "WASTES"
DEFAULT_MANIFEST_PATH = WORKSPACE_ROOT / "data" / "manifests" / "wastes_manifest.json"
SUPPORTED_IMAGE_FORMATS = {"JPEG", "PNG"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}


def build_manifest(dataset_root: Path) -> dict:
    dataset_root = dataset_root.resolve()
    if not dataset_root.is_dir():
        raise FileNotFoundError(f"Dataset root not found: {dataset_root}")

    records = []
    summary = {
        "dataset_root": dataset_root.as_posix(),
        "splits": {},
        "total_image_count": 0,
        "total_file_count": 0,
        "valid_image_count": 0,
        "invalid_file_count": 0,
        "unreadable_image_count": 0,
        "unsupported_format_count": 0,
        "categories": [],
        "formats_valid_images": {},
        "dimensions_valid_images": {},
        "missing_split_directories": [],
        "empty_directories": [],
        "structural_problems": [],
    }
    all_formats = Counter()
    all_dimensions = Counter()
    all_categories = set()

    for split in ("train", "test"):
        split_root = dataset_root / split
        if not split_root.is_dir():
            summary["missing_split_directories"].append(split_root.as_posix())
            summary["structural_problems"].append(
                f"Missing split directory: {split_root.as_posix()}"
            )
            summary["splits"][split] = {
                "image_count": 0,
                "file_count": 0,
                "valid_count": 0,
                "invalid_file_count": 0,
                "corrupt_count": 0,
                "unsupported_format_count": 0,
                "categories": [],
                "category_image_counts": {},
                "formats_valid_images": {},
                "dimensions_valid_images": {},
                "empty_directories": [],
            }
            continue

        categories = sorted(
            (path for path in split_root.iterdir() if path.is_dir()),
            key=lambda path: path.name.casefold(),
        )
        all_categories.update(path.name for path in categories)
        split_files = sorted(
            (path for path in split_root.rglob("*") if path.is_file()),
            key=lambda path: path.as_posix().casefold(),
        )
        format_counts = Counter()
        dimension_counts = Counter()
        category_image_counts = Counter()
        split_image_count = 0
        valid_image_count = 0
        invalid_file_count = 0
        corrupt_count = 0
        unsupported_format_count = 0

        for path in split_files:
            relative_path = path.relative_to(split_root)
            category_name = (
                relative_path.parts[0]
                if len(relative_path.parts) > 1
                and (split_root / relative_path.parts[0]).is_dir()
                else None
            )
            image_format = path.suffix.lstrip(".").upper() or None
            width = height = None
            validation_error = None
            is_image = path.suffix.lower() in IMAGE_EXTENSIONS
            try:
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    image.load()
                    image_format = (image.format or image_format or "").upper() or None
                    width, height = image.size
                is_image = True
                if image_format not in SUPPORTED_IMAGE_FORMATS:
                    is_valid = False
                    validity_status = "unsupported_format"
                    unsupported_format_count += 1
                    validation_error = f"Unsupported image format: {image_format}"
                else:
                    is_valid = True
                    validity_status = "valid"
                    format_counts[image_format] += 1
                    dimension_counts[f"{width}x{height}"] += 1
            except Exception as error:
                is_valid = False
                validity_status = "corrupt_or_unreadable" if is_image else "invalid_file"
                validation_error = f"{type(error).__name__}: {error}"
                if is_image:
                    corrupt_count += 1

            if is_image:
                split_image_count += 1
                if category_name is not None:
                    category_image_counts[category_name] += 1
                if is_valid:
                    valid_image_count += 1
            if not is_valid:
                invalid_file_count += 1

            try:
                file_path = path.relative_to(WORKSPACE_ROOT).as_posix()
            except ValueError:
                file_path = path.relative_to(dataset_root).as_posix()

            record = {
                "file_path": file_path,
                "split": split,
                "category_name": category_name,
                "image_format": image_format,
                "width": width,
                "height": height,
                "is_image": is_image,
                "is_valid": is_valid,
                "validity_status": validity_status,
                "validation_error": validation_error,
            }
            records.append(record)

        directories = [split_root, *(path for path in split_root.rglob("*") if path.is_dir())]
        empty_directories = [
            path.as_posix() for path in directories if not any(path.iterdir())
        ]
        if empty_directories:
            summary["structural_problems"].extend(
                f"Empty directory: {path}" for path in empty_directories
            )
            summary["empty_directories"].extend(empty_directories)

        all_formats.update(format_counts)
        all_dimensions.update(dimension_counts)
        summary["total_image_count"] += split_image_count
        summary["total_file_count"] += len(split_files)
        summary["valid_image_count"] += valid_image_count
        summary["invalid_file_count"] += invalid_file_count
        summary["unreadable_image_count"] += corrupt_count
        summary["unsupported_format_count"] += unsupported_format_count

        summary["splits"][split] = {
            "image_count": split_image_count,
            "file_count": len(split_files),
            "valid_count": valid_image_count,
            "invalid_file_count": invalid_file_count,
            "corrupt_count": corrupt_count,
            "unsupported_format_count": unsupported_format_count,
            "categories": [path.name for path in categories],
            "category_image_counts": dict(sorted(
                category_image_counts.items(), key=lambda item: item[0].casefold()
            )),
            "formats_valid_images": dict(sorted(format_counts.items())),
            "dimensions_valid_images": dict(sorted(dimension_counts.items())),
            "empty_directories": empty_directories,
        }

    summary["categories"] = sorted(all_categories, key=str.casefold)
    summary["formats_valid_images"] = dict(sorted(all_formats.items()))
    summary["dimensions_valid_images"] = dict(sorted(all_dimensions.items()))

    return {
        "manifest_version": 1,
        "dataset_root": (
            dataset_root.relative_to(WORKSPACE_ROOT).as_posix()
            if dataset_root.is_relative_to(WORKSPACE_ROOT)
            else dataset_root.as_posix()
        ),
        "record_count": len(records),
        "metadata_only_note": (
            "category_name and split are metadata only and must not be passed to "
            "DINOv2 embeddings or K-Means; they may be used after clustering for evaluation."
        ),
        "summary": summary,
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_MANIFEST_PATH)
    args = parser.parse_args()

    manifest = build_manifest(args.dataset_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "manifest_path": args.output.as_posix(),
                "record_count": manifest["record_count"],
                "summary": manifest["summary"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()