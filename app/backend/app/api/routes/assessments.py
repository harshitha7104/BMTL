"""
Assessment API routes.

Handles image upload, assessment creation, and retrieval.
"""
import logging
from typing import List

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.core.ownership import can_access, owned_record_ids, record_owner
from app.core.security import User, current_user, rate_limited

from app.api.deps import get_assessment_service, get_repository
from app.core.config import settings
from app.core.exceptions import (
    ValidationError,
    FileTooLargeError,
    UnsupportedFormatError,
    CorruptedFileError,
    NotFoundError,
)
from app.schemas.assessment import (
    Assessment,
    AssessmentResponse,
    AssessmentListResponse,
)
from app.services.assessment_service import AssessmentService
from app.repositories.local_repository import LocalRepository
from app.utils.image_utils import create_image_data, ImageData

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/assessments",
    response_model=AssessmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new assessment",
    description="Upload scrap material images for AI-assisted visual assessment",
)
async def create_assessment(
    images: List[UploadFile] = File(
        ...,
        description="Scrap material images (max 5, JPEG/PNG/WebP, max 10MB each)",
    ),
    assessment_service: AssessmentService = Depends(get_assessment_service),
    user: User = Depends(rate_limited("assessment", "rate_limit_per_minute")),
):
    """
    Create a new assessment from uploaded images.
    
    Validates:
    - File count (max 5)
    - File types (JPEG, PNG, WebP only)
    - File sizes (max 10MB each)
    - File integrity (not corrupted)
    - Magic bytes (not just extensions)
    
    Returns:
    - Complete assessment with observations, inferences, unknowns
    - Quality assessment and recommendations
    - Review triggers if human review is required
    """
    # Validate file count
    if len(images) == 0:
        raise ValidationError("At least one image is required")
    
    if len(images) > settings.max_images_per_assessment:
        raise ValidationError(
            f"Maximum {settings.max_images_per_assessment} images per assessment"
        )
    
    # Validate and process each file
    image_data_list: List[ImageData] = []
    
    for upload_file in images:
        # Check file size while reading (never buffer more than the limit + 1 byte)
        content = await upload_file.read(settings.max_upload_size_bytes + 1)
        
        if len(content) > settings.max_upload_size_bytes:
            raise FileTooLargeError(
                upload_file.filename or "unknown",
                len(content),
                settings.max_upload_size_bytes,
            )
        
        if len(content) == 0:
            raise CorruptedFileError(
                upload_file.filename or "unknown",
                "File is empty"
            )
        
        # Validate content type and create ImageData
        try:
            image_data = create_image_data(
                content=content,
                filename=upload_file.filename or "unknown",
                declared_content_type=upload_file.content_type or "",
                allowed_types=settings.allowed_image_types_list,
            )
            image_data_list.append(image_data)
        except Exception as e:
            # Re-raise as appropriate exception
            if "unsupported" in str(e).lower():
                raise UnsupportedFormatError(
                    upload_file.filename or "unknown",
                    upload_file.content_type or "unknown",
                    settings.allowed_image_types_list,
                )
            else:
                raise CorruptedFileError(
                    upload_file.filename or "unknown",
                    str(e)
                )
    
    # Create assessment
    try:
        assessment = await assessment_service.create_assessment(image_data_list)
        record_owner(assessment.assessment_id, user)
        from app.records.store import get_records

        get_records().log(user.username, "photo_assessment", object_id=assessment.assessment_id,
                          summary=f"photo assessment of {len(image_data_list)} image(s)",
                          detail=assessment.model_dump(mode="json") if hasattr(assessment, "model_dump") else str(assessment))

        return AssessmentResponse(
            success=True,
            data=assessment,
            message="Assessment created successfully",
        )
    except Exception as e:
        logger.error(f"Assessment creation failed: {e}", exc_info=True)
        raise


@router.get(
    "/assessments/{assessment_id}",
    response_model=AssessmentResponse,
    summary="Get assessment by ID",
    description="Retrieve a completed assessment with full analysis results",
)
async def get_assessment(
    assessment_id: str,
    repository: LocalRepository = Depends(get_repository),
    user: User = Depends(current_user),
):
    """
    Retrieve an assessment by its unique identifier.
    
    Returns the complete assessment including:
    - Evidence quality assessment
    - Visual observations
    - Inferences with confidence levels
    - Unknown items
    - Proposed assessment (if available)
    - Review triggers and recommendations
    """
    assessment = await repository.get_assessment(assessment_id) if can_access(assessment_id, user) else None

    if not assessment:
        raise NotFoundError("Assessment", assessment_id)
    
    return AssessmentResponse(
        success=True,
        data=assessment,
    )


@router.get(
    "/assessments",
    response_model=AssessmentListResponse,
    summary="List assessments",
    description="Get paginated list of assessments",
)
async def list_assessments(
    skip: int = 0,
    limit: int = 20,
    repository: LocalRepository = Depends(get_repository),
    user: User = Depends(current_user),
):
    """
    List assessments with pagination.
    
    Returns assessments sorted by creation date (most recent first).
    """
    skip, limit = max(0, skip), min(max(1, limit), 100)
    if user.has_role("admin"):      # admins see everything, newest first, one page at a time
        assessments = await repository.list_assessments(skip=skip, limit=limit)
    else:                           # audit L-04: read only the caller's own records, never the whole store
        mine = [a for a in [await repository.get_assessment(i) for i in owned_record_ids(user.username)] if a is not None]
        mine.sort(key=lambda a: a.created_at, reverse=True)
        assessments = mine[skip:skip + limit]
    
    return AssessmentListResponse(
        success=True,
        data=assessments,
        count=len(assessments),
    )


__all__ = ["router"]
