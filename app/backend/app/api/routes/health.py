"""
Health check endpoint.
"""
from datetime import datetime

from fastapi import APIRouter

from app.core.config import settings
from app.schemas.common import HealthResponse
from app.providers.registry import provider_registry

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Check if the API is running and which AI provider is active",
)
async def health_check():
    """
    Health check endpoint.
    
    Returns:
    - API status
    - Version
    - Active AI provider
    - Timestamp
    """
    active_provider = provider_registry.get_active_provider()
    provider_name = active_provider.name if active_provider else "none"
    
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        ai_provider=provider_name,
        timestamp=datetime.utcnow(),
    )


__all__ = ["router"]
