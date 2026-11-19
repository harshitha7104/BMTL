"""
Feedback API routes.

Handles human expert feedback submission.
Feedback is stored SEPARATELY from the original AI assessment.
Original AI output is NEVER modified.
"""
import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, status

from app.api.deps import get_repository
from app.core.exceptions import NotFoundError
from app.schemas.assessment import (
    FeedbackSubmission,
    FeedbackRecord,
    FeedbackResponse,
    VerificationStatus,
)
from app.repositories.local_repository import LocalRepository
from app.core.ownership import can_access
from app.core.security import User, current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/assessments/{assessment_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit feedback for assessment",
    description="Submit human expert feedback. Stored separately from AI output.",
)
async def submit_feedback(
    assessment_id: str,
    feedback: FeedbackSubmission,
    repository: LocalRepository = Depends(get_repository),
    user: User = Depends(current_user),
):
    """
    Submit human expert feedback for an assessment.
    
    IMPORTANT:
    - Feedback is stored SEPARATELY from the original AI assessment
    - The original AI output is NEVER modified
    - Feedback is marked as unverified until reviewed
    - No automatic retraining uses unverified feedback
    
    This implements the principle that AI-generated output and human
    corrections must be kept separate for auditability and trust.
    """
    # Check if assessment exists
    assessment = await repository.get_assessment(assessment_id) if can_access(assessment_id, user) else None
    if not assessment:
        raise NotFoundError("Assessment", assessment_id)
    
    # Create feedback record
    feedback_id = f"FB-{uuid4().hex[:6].upper()}"
    
    feedback_record = FeedbackRecord(
        feedback_id=feedback_id,
        assessment_id=assessment_id,
        reviewer_name=user.username,   # the signed-in user, never the client-supplied name
        feedback_category=feedback.feedback_category,
        corrections=feedback.corrections,
        confidence_override=feedback.confidence_override,
        verified=feedback.verified,
        verification_status=VerificationStatus.unverified,  # Always starts unverified
        submitted_at=datetime.utcnow(),
    )
    
    # Save feedback (separate from assessment)
    await repository.save_feedback(feedback_record)
    
    logger.info(
        f"Feedback {feedback_id} submitted for assessment {assessment_id} "
        f"by {feedback.reviewer_name}"
    )
    
    return FeedbackResponse(
        success=True,
        data=feedback_record,
        message="Feedback recorded successfully. Original AI output preserved.",
    )


@router.get(
    "/assessments/{assessment_id}/feedback",
    response_model=dict,
    summary="Get feedback for assessment",
    description="Retrieve all feedback records for an assessment",
)
async def get_feedback(
    assessment_id: str,
    repository: LocalRepository = Depends(get_repository),
    user: User = Depends(current_user),
):
    """
    Retrieve all feedback records for an assessment.
    
    Returns feedback in chronological order (most recent first).
    Each feedback record includes:
    - Reviewer name
    - Corrections made
    - Verification status
    - Submission timestamp
    """
    # Check if assessment exists
    assessment = await repository.get_assessment(assessment_id) if can_access(assessment_id, user) else None
    if not assessment:
        raise NotFoundError("Assessment", assessment_id)
    
    # Get all feedback
    feedbacks = await repository.get_feedback(assessment_id)
    
    return {
        "success": True,
        "data": feedbacks,
        "count": len(feedbacks),
    }


__all__ = ["router"]
