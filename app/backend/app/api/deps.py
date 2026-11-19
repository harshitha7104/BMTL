"""
Dependency injection for FastAPI routes.

Provides service instances to route handlers.
"""
from functools import lru_cache

from app.core.config import settings
from app.repositories.local_repository import LocalRepository
from app.services.assessment_service import AssessmentService
from app.services.image_quality_service import ImageQualityService


@lru_cache()
def get_repository() -> LocalRepository:
    """Get the assessment repository instance."""
    return LocalRepository(settings.local_storage_path)


@lru_cache()
def get_quality_service() -> ImageQualityService:
    """Get the image quality service instance."""
    return ImageQualityService()


def get_assessment_service() -> AssessmentService:
    """Get the assessment service instance."""
    repository = get_repository()
    quality_service = get_quality_service()
    return AssessmentService(repository, quality_service)


__all__ = [
    "get_repository",
    "get_quality_service",
    "get_assessment_service",
]
