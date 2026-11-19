"""
Assessment API Routes
"""
import logging
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import ValidationError

from app.schemas.assessment import (
    Assessment,
    AssessmentResponse,
    AssessmentStatus,
)
from app.services.assessment_service import AssessmentService
from app.services.validation_service import ValidationService
from app.api.deps import get_assessment_service, get_validation_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/assessments",
    response_model=AssessmentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create new assessment",
    description="Upload scrap material images for AI-assisted visual assessment",
)
async def create_assessment(
    images: List[UploadFile] = File(..., description="Scrap material images (max 5)"),
    assessment_service: AssessmentService = Depends(get_assessment_service),
    validation_service: ValidationService = Depends(get_validation_service),
):
    """
    Create a new assessment from uploaded images.
    
    Validates:
    - File count (max 5)
    - File types (JPEG, PNG, WebP only)
    - File sizes (max 10MB each)
    - File integrity (not corrupted)
    - Magic bytes (not just extensions)
    """
    # Validate number of files
    if len(images) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "VALIDATION_ERROR", "message": "At least one image is required"},
        )
    
    if len(images) > 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "VALIDATION_ERROR", "message": "Maximum 5 images per assessment"},
        )

    # Validate each file
    validated_files = []
    for upload_file in images:
        try:
            validated = await validation_service.validate_upload(upload_file)
            validated_files.append(validated)
        except ValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "VALIDATION_ERROR", "message": str(e)},
            )

    # Create assessment
    try:
        assessment = await assessment_service.create_assessment(validated_files)
        return AssessmentResponse(
            success=True,
            data=assessment,
            message="Assessment created successfully",
        )
    except Exception as e:
        logger.error(f"Assessment creation failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "PROCESSING_ERROR", "message": "Assessment processing failed"},
        )


@router.get(
    "/assessments/{assessment_id}",
    response_model=AssessmentResponse,
    summary="Get assessment by ID",
    description="Retrieve a completed assessment with full analysis results",
)
async def get_assessment(
    assessment_id: str,
    assessment_service: AssessmentService = Depends(get_assessment_service),
):
    """Retrieve an assessment by its unique identifier."""
    assessment = await assessment_service.get_assessment(assessment_id)
    
    if not assessment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": f"Assessment '{assessment_id}' not found"},
        )
    
    return AssessmentResponse(success=True, data=assessment)


@router.get(
    "/assessments",
    response_model=dict,
    summary="List assessments",
    description="Get paginated list of assessments",
)
async def list_assessments(
    skip: int = 0,
    limit: int = 20,
    status_filter: str | None = None,
    assessment_service: AssessmentService = Depends(get_assessment_service),
):
    """List assessments with optional filtering and pagination."""
    assessments = await assessment_service.list_assessments(
        skip=skip, limit=limit, status=status_filter
    )
    return {"success": True, "data": assessments, "count": len(assessments)}
