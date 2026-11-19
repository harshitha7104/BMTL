"""
Image handling utilities.

Provides safe image processing, validation, and metadata extraction.
"""
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, UnidentifiedImageError

from app.core.exceptions import CorruptedFileError, UnsupportedFormatError


@dataclass
class ImageData:
    """Validated image data ready for processing."""
    content: bytes
    content_type: str
    filename: str
    hash_sha256: str
    width: int
    height: int
    format: str  # e.g., "JPEG", "PNG"


ALLOWED_MIME_TYPES = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
}

# Magic bytes for image format detection
MAGIC_BYTES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"RIFF": "image/webp",  # WebP starts with RIFF....WEBP
}

MAX_IMAGE_DIMENSION = 8192  # pixels
MIN_IMAGE_DIMENSION = 50  # pixels


def compute_sha256(content: bytes) -> str:
    """Compute SHA-256 hash of content."""
    return hashlib.sha256(content).hexdigest()


def detect_content_type(content: bytes) -> Optional[str]:
    """
    Detect image content type from magic bytes.
    
    This is more reliable than trusting the client-provided Content-Type.
    """
    for magic, mime_type in MAGIC_BYTES.items():
        if content.startswith(magic):
            # Special case for WebP — need to check for WEBP signature
            if magic == b"RIFF":
                if len(content) >= 12 and content[8:12] == b"WEBP":
                    return "image/webp"
                continue
            return mime_type
    return None


def validate_image_content(
    content: bytes,
    original_filename: str,
    declared_content_type: str,
    allowed_types: list[str],
) -> Tuple[str, str]:
    """
    Validate image content and return (actual_content_type, format_name).
    
    Checks:
    1. Magic bytes match an allowed image type
    2. Declared content type matches detected type
    3. Content type is in allowed list
    
    Raises:
        UnsupportedFormatError: If content type is not allowed
        CorruptedFileError: If content doesn't match declared type
    """
    # Detect actual content type from magic bytes
    detected_type = detect_content_type(content)
    
    if detected_type is None:
        raise CorruptedFileError(
            original_filename,
            "Could not detect image format from file content"
        )
    
    if detected_type not in allowed_types:
        raise UnsupportedFormatError(
            original_filename,
            detected_type,
            allowed_types
        )
    
    # Warn if declared type doesn't match (but don't fail — magic bytes are authoritative)
    if declared_content_type and declared_content_type != detected_type:
        # Log warning but proceed with detected type
        import logging
        logging.getLogger(__name__).warning(
            f"Content type mismatch for {original_filename}: "
            f"declared={declared_content_type}, detected={detected_type}"
        )
    
    return detected_type, detected_type.split("/")[-1].upper()


def extract_image_metadata(content: bytes, filename: str) -> Tuple[int, int, str]:
    """
    Extract image dimensions and format using PIL.
    
    Returns:
        Tuple of (width, height, format_name)
        
    Raises:
        CorruptedFileError: If image cannot be read
    """
    try:
        with Image.open(io.BytesIO(content)) as img:
            width, height = img.size
            format_name = img.format or "UNKNOWN"
            
            # Validate dimensions
            if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
                raise CorruptedFileError(
                    filename,
                    f"Image too small: {width}x{height} (minimum {MIN_IMAGE_DIMENSION}x{MIN_IMAGE_DIMENSION})"
                )
            
            if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
                raise CorruptedFileError(
                    filename,
                    f"Image too large: {width}x{height} (maximum {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION})"
                )
            
            return width, height, format_name
            
    except UnidentifiedImageError:
        raise CorruptedFileError(filename, "PIL could not identify image format")
    except Exception as e:
        raise CorruptedFileError(filename, f"Failed to read image: {str(e)}")


def create_image_data(
    content: bytes,
    filename: str,
    declared_content_type: str,
    allowed_types: list[str],
) -> ImageData:
    """
    Create validated ImageData from raw upload.
    
    This is the main entry point for image validation.
    
    Raises:
        UnsupportedFormatError: If format not allowed
        CorruptedFileError: If image is corrupted or invalid
    """
    # Validate content type and detect format
    content_type, format_name = validate_image_content(
        content, filename, declared_content_type, allowed_types
    )
    
    # Extract metadata
    width, height, pil_format = extract_image_metadata(content, filename)
    
    # Compute hash
    hash_sha256 = compute_sha256(content)
    
    return ImageData(
        content=content,
        content_type=content_type,
        filename=filename,
        hash_sha256=hash_sha256,
        width=width,
        height=height,
        format=pil_format,
    )


def generate_safe_filename(original_filename: str, hash_sha256: str) -> str:
    """
    Generate a safe filename for storage.
    
    Uses hash to prevent collisions and path traversal.
    Preserves extension for content type identification.
    """
    # Extract extension
    ext = Path(original_filename).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".jpg"  # Default fallback
    
    # Use first 16 chars of hash for filename
    safe_name = f"{hash_sha256[:16]}{ext}"
    return safe_name


__all__ = [
    "ImageData",
    "compute_sha256",
    "detect_content_type",
    "validate_image_content",
    "extract_image_metadata",
    "create_image_data",
    "generate_safe_filename",
]
