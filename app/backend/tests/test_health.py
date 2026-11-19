"""
Health endpoint tests.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Test that health endpoint returns expected response."""
    response = await client.get("/health")
    
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "ai_provider" in data
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_health_check_provider_is_mock(client: AsyncClient):
    """Test that mock provider is active by default."""
    response = await client.get("/health")
    
    data = response.json()
    assert data["ai_provider"] == "mock"


__all__ = ["test_health_check", "test_health_check_provider_is_mock"]
