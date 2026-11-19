"""
Repository interface for assessment storage.

Abstract interface that can be implemented by different storage backends
(local files, SQLite, PostgreSQL, etc.).
"""
from typing import List, Optional, Protocol

from app.schemas.assessment import Assessment, FeedbackRecord


class AssessmentRepository(Protocol):
    """Interface for assessment storage."""
    
    async def initialize(self) -> None:
        """Initialize the repository (create tables, directories, etc.)."""
        ...
    
    async def close(self) -> None:
        """Close the repository and release resources."""
        ...
    
    async def save_assessment(self, assessment: Assessment) -> None:
        """Save an assessment record."""
        ...
    
    async def get_assessment(self, assessment_id: str) -> Optional[Assessment]:
        """Retrieve an assessment by ID."""
        ...
    
    async def list_assessments(
        self,
        skip: int = 0,
        limit: int = 20,
    ) -> List[Assessment]:
        """List assessments with pagination."""
        ...
    
    async def save_feedback(self, feedback: FeedbackRecord) -> None:
        """Save a feedback record (separate from assessment)."""
        ...
    
    async def get_feedback(
        self,
        assessment_id: str,
    ) -> List[FeedbackRecord]:
        """Get all feedback for an assessment."""
        ...


__all__ = ["AssessmentRepository"]
