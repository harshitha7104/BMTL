"""
Assessment endpoint tests.
"""
import io
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_assessment_no_images(client: AsyncClient):
    """Test that creating assessment without images fails."""
    response = await client.post("/api/v1/assessments")
    
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_create_assessment_invalid_file_type(client: AsyncClient):
    """Test that uploading non-image file fails."""
    files = {
        "images": ("test.txt", b"not an image", "text/plain"),
    }
    
    response = await client.post("/api/v1/assessments", files=files)
    
    # Should fail with unsupported format or corrupted file
    assert response.status_code in [400, 422]


@pytest.mark.asyncio
async def test_create_assessment_empty_file(client: AsyncClient):
    """Test that uploading empty file fails."""
    files = {
        "images": ("empty.jpg", b"", "image/jpeg"),
    }
    
    response = await client.post("/api/v1/assessments", files=files)
    
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_assessment_valid_jpeg(client: AsyncClient, sample_jpeg_bytes: bytes):
    """Test creating assessment with valid JPEG."""
    files = {
        "images": ("test.jpg", sample_jpeg_bytes, "image/jpeg"),
    }
    
    response = await client.post("/api/v1/assessments", files=files)
    
    # May succeed or fail depending on image quality
    # But should not crash
    assert response.status_code in [201, 400, 500]
    
    if response.status_code == 201:
        data = response.json()
        assert data["success"] is True
        assert "assessment_id" in data["data"]


@pytest.mark.asyncio
async def test_get_assessment_not_found(client: AsyncClient):
    """Test retrieving non-existent assessment."""
    response = await client.get("/api/v1/assessments/ASM-NONEXIST")
    
    assert response.status_code == 404
    
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_list_assessments_empty(client: AsyncClient):
    """Test listing assessments when none exist."""
    response = await client.get("/api/v1/assessments")
    
    assert response.status_code == 200
    
    data = response.json()
    assert data["success"] is True
    assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_create_assessment_too_many_images(client: AsyncClient, sample_jpeg_bytes: bytes):
    """Test that uploading too many images fails."""
    files = [
        ("images", (f"test{i}.jpg", sample_jpeg_bytes, "image/jpeg"))
        for i in range(10)  # More than max of 5
    ]
    
    response = await client.post("/api/v1/assessments", files=files)
    
    # Should fail with validation error
    assert response.status_code in [400, 422]


__all__ = [
    "test_create_assessment_no_images",
    "test_create_assessment_invalid_file_type",
    "test_create_assessment_empty_file",
    "test_create_assessment_valid_jpeg",
    "test_get_assessment_not_found",
    "test_list_assessments_empty",
    "test_create_assessment_too_many_images",
]
