"""Recursively validate the waste image dataset without requiring an images/ folder."""
import argparse
import json
from pathlib import Path

if __package__:
    from .generate_manifest import DEFAULT_DATASET_ROOT, build_manifest
else:
    from generate_manifest import DEFAULT_DATASET_ROOT, build_manifest


def validate_dataset(dataset_root: Path = DEFAULT_DATASET_ROOT) -> dict:
    """Return the same validated inventory used by manifest generation."""
    return build_manifest(dataset_root)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    args = parser.parse_args()

    report = validate_dataset(args.dataset_root)
    summary = report["summary"]
    output = {
        "dataset_root": report["dataset_root"],
        "total_image_count": summary["total_image_count"],
        "train_image_count": summary["splits"]["train"]["image_count"],
        "test_image_count": summary["splits"]["test"]["image_count"],
        "categories": summary["categories"],
        "formats_valid_images": summary["formats_valid_images"],
        "dimensions_valid_images": summary["dimensions_valid_images"],
        "unreadable_image_count": summary["unreadable_image_count"],
        "invalid_file_count": summary["invalid_file_count"],
        "invalid_files": [
            {
                "file_path": record["file_path"],
                "validity_status": record["validity_status"],
                "validation_error": record["validation_error"],
            }
            for record in report["records"]
            if not record["is_valid"]
        ],
        "empty_directories": summary["empty_directories"],
        "missing_split_directories": summary["missing_split_directories"],
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))

    if summary["invalid_file_count"] or summary["missing_split_directories"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()