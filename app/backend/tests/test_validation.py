"""
Image validation tests.
"""
import pytest

from app.utils.image_utils import (
    compute_sha256,
    detect_content_type,
    validate_image_content,
    create_image_data,
)
from app.core.exceptions import UnsupportedFormatError, CorruptedFileError


def test_compute_sha256():
    """Test SHA-256 hash computation."""
    content = b"test content"
    hash1 = compute_sha256(content)
    hash2 = compute_sha256(content)
    
    # Same content should produce same hash
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 produces 64 hex chars


def test_detect_content_type_jpeg():
    """Test JPEG detection from magic bytes."""
    jpeg_bytes = bytes([0xFF, 0xD8, 0xFF, 0xE0])
    assert detect_content_type(jpeg_bytes) == "image/jpeg"


def test_detect_content_type_png():
    """Test PNG detection from magic bytes."""
    png_bytes = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
    assert detect_content_type(png_bytes) == "image/png"


def test_detect_content_type_webp():
    """Test WebP detection from magic bytes."""
    webp_bytes = bytes([0x52, 0x49, 0x46, 0x46]) + b"\x00" * 4 + bytes([0x57, 0x45, 0x42, 0x50])
    assert detect_content_type(webp_bytes) == "image/webp"


def test_detect_content_type_unknown():
    """Test unknown format detection."""
    unknown_bytes = b"random data"
    assert detect_content_type(unknown_bytes) is None


def test_validate_image_content_valid():
    """Test validation of valid image content."""
    jpeg_bytes = bytes([0xFF, 0xD8, 0xFF, 0xE0])
    
    content_type, format_name = validate_image_content(
        jpeg_bytes,
        "test.jpg",
        "image/jpeg",
        ["image/jpeg", "image/png"],
    )
    
    assert content_type == "image/jpeg"
    assert format_name == "JPEG"


def test_validate_image_content_unsupported():
    """Test validation rejects unsupported formats."""
    jpeg_bytes = bytes([0xFF, 0xD8, 0xFF, 0xE0])
    
    with pytest.raises(UnsupportedFormatError):
        validate_image_content(
            jpeg_bytes,
            "test.jpg",
            "image/jpeg",
            ["image/png"],  # JPEG not in allowed list
        )


def test_validate_image_content_corrupted():
    """Test validation detects corrupted content."""
    corrupted_bytes = b"not an image"
    
    with pytest.raises(CorruptedFileError):
        validate_image_content(
            corrupted_bytes,
            "test.jpg",
            "image/jpeg",
            ["image/jpeg"],
        )


def test_create_image_data_valid_jpeg(sample_jpeg_bytes: bytes):
    """Test creating ImageData from valid JPEG."""
    image_data = create_image_data(
        sample_jpeg_bytes,
        "test.jpg",
        "image/jpeg",
        ["image/jpeg"],
    )
    
    assert image_data.content == sample_jpeg_bytes
    assert image_data.content_type == "image/jpeg"
    assert image_data.filename == "test.jpg"
    assert len(image_data.hash_sha256) == 64
    assert image_data.width > 0
    assert image_data.height > 0


def test_create_image_data_invalid_content():
    """Test creating ImageData from invalid content."""
    with pytest.raises((CorruptedFileError, UnsupportedFormatError)):
        create_image_data(
            b"not an image",
            "test.jpg",
            "image/jpeg",
            ["image/jpeg"],
        )


__all__ = [
    "test_compute_sha256",
    "test_detect_content_type_jpeg",
    "test_detect_content_type_png",
    "test_detect_content_type_webp",
    "test_detect_content_type_unknown",
    "test_validate_image_content_valid",
    "test_validate_image_content_unsupported",
    "test_validate_image_content_corrupted",
    "test_create_image_data_valid_jpeg",
    "test_create_image_data_invalid_content",
]
